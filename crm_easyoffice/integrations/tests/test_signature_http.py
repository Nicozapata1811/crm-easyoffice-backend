"""The HTTP signature adapter against a mocked provider. No network."""

from __future__ import annotations

import json
import time
from http import HTTPStatus

import httpx
import pytest

from crm_easyoffice.integrations.signature.base import SignatureError
from crm_easyoffice.integrations.signature.base import SignatureEventType
from crm_easyoffice.integrations.signature.base import SignatureRequest
from crm_easyoffice.integrations.signature.base import SignatureStatus
from crm_easyoffice.integrations.signature.base import Signer
from crm_easyoffice.integrations.signature.base import SignerState
from crm_easyoffice.integrations.signature.http import HttpSignatureProvider
from crm_easyoffice.integrations.signature.http import firma_webhook

BASE = "http://firma-sandbox:8100/api/v1/"
CLAVE = "clave-api-de-prueba"
SECRETO = "secreto-de-prueba"


def estado(estado_solicitud="pendiente", firmantes=("pendiente", "pendiente"), **extra):
    return {
        "id": "8f0e2c1a-0000-4000-8000-000000000001",
        "estado": estado_solicitud,
        "ambiente": "pruebas",
        "sha256_original": "a" * 64,
        "sha256_firmado": None,
        "terminada_en": None,
        "firmantes": [
            {
                "id": f"firmante-{i}",
                "orden": i,
                "nombre": f"Persona Ficticia {i}",
                "referencia": str(10 + i),
                "estado": e,
                "firmado_en": "2026-10-26T12:00:00+00:00" if e == "firmado" else None,
                "rechazado_en": None,
                "motivo_rechazo": "No corresponde." if e == "rechazado" else "",
            }
            for i, e in enumerate(firmantes, start=1)
        ],
        **extra,
    }


def proveedor(manejar) -> tuple[HttpSignatureProvider, list[httpx.Request]]:
    enviadas: list[httpx.Request] = []

    def registrar(request: httpx.Request) -> httpx.Response:
        enviadas.append(request)
        return manejar(request)

    cliente = httpx.Client(base_url=BASE, transport=httpx.MockTransport(registrar))
    return HttpSignatureProvider(BASE, CLAVE, SECRETO, client=cliente), enviadas


def solicitud() -> SignatureRequest:
    return SignatureRequest(
        document_id="42",
        document_name="Contrato LF-0001-2026",
        content=b"%PDF-1.7 documento",
        signers=[
            Signer(
                "Persona Ficticia 1",
                "uno@example.test",
                "11111111-1",
                1,
                "cliente",
                "11",
            ),
            Signer(
                "Persona Ficticia 2",
                "dos@example.test",
                "22222222-2",
                2,
                "emisor",
                "12",
            ),
        ],
        callback_url="http://django:8000/api/firma/webhooks/http/",
        expires_at="2026-11-01T23:59:59+00:00",
    )


def test_create_request_sends_the_pdf_and_signers_with_the_api_key():
    adaptador, enviadas = proveedor(
        lambda r: httpx.Response(HTTPStatus.CREATED, json=estado()),
    )

    resultado = adaptador.create_request(solicitud())

    [peticion] = enviadas
    assert peticion.method == "POST"
    assert str(peticion.url) == f"{BASE}solicitudes"
    assert peticion.headers["Authorization"] == f"Bearer {CLAVE}"
    cuerpo = peticion.content
    assert b"%PDF-1.7 documento" in cuerpo
    datos = json.loads(cuerpo.split(b'name="datos"\r\n\r\n')[1].split(b"\r\n--")[0])
    assert datos["referencia_externa"] == "42"
    assert datos["url_notificacion"] == "http://django:8000/api/firma/webhooks/http/"
    assert [(f["orden"], f["rut"], f["referencia"]) for f in datos["firmantes"]] == [
        (1, "11111111-1", "11"),
        (2, "22222222-2", "12"),
    ]
    assert resultado.status is SignatureStatus.PENDING
    assert resultado.test_environment
    assert resultado.original_sha256 == "a" * 64
    assert [s.reference for s in resultado.signers] == ["11", "12"]


def test_states_map_to_the_contract():
    adaptador, _ = proveedor(
        lambda r: httpx.Response(
            HTTPStatus.OK,
            json=estado(firmantes=("firmado", "pendiente")),
        ),
    )
    resultado = adaptador.get_status("x")
    assert resultado.status is SignatureStatus.PARTIALLY_SIGNED
    assert [s.status for s in resultado.signers] == [
        SignerState.SIGNED,
        SignerState.PENDING,
    ]

    for remoto, local in [
        ("completada", SignatureStatus.SIGNED),
        ("rechazada", SignatureStatus.REJECTED),
        ("expirada", SignatureStatus.EXPIRED),
        ("cancelada", SignatureStatus.REJECTED),
    ]:
        adaptador, _ = proveedor(
            lambda r, remoto=remoto: httpx.Response(HTTPStatus.OK, json=estado(remoto)),
        )
        assert adaptador.get_status("x").status is local


def test_download_cancel_and_resend_call_their_endpoints():
    def manejar(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/documento"):
            return httpx.Response(HTTPStatus.OK, content=b"%PDF firmado")
        return httpx.Response(HTTPStatus.OK, json=estado("cancelada"))

    adaptador, enviadas = proveedor(manejar)

    assert adaptador.download_signed("abc") == b"%PDF firmado"
    adaptador.cancel("abc")
    adaptador.resend("abc", "firmante-2")

    assert [(r.method, r.url.path) for r in enviadas] == [
        ("GET", "/api/v1/solicitudes/abc/documento"),
        ("POST", "/api/v1/solicitudes/abc/cancelar"),
        ("POST", "/api/v1/solicitudes/abc/firmantes/firmante-2/reenviar"),
    ]


@pytest.mark.parametrize(
    ("respuesta", "transitorio"),
    [
        (httpx.Response(HTTPStatus.SERVICE_UNAVAILABLE), True),
        (httpx.Response(HTTPStatus.CONFLICT, json={"codigo": "no_completada"}), False),
    ],
)
def test_errors_say_whether_a_retry_may_help(respuesta, transitorio):
    adaptador, _ = proveedor(lambda r: respuesta)
    with pytest.raises(SignatureError) as error:
        adaptador.download_signed("abc")
    assert error.value.transient is transitorio


def test_an_unreachable_provider_is_transient():
    def caido(request: httpx.Request) -> httpx.Response:
        msg = "sin red"
        raise httpx.ConnectError(msg, request=request)

    adaptador, _ = proveedor(caido)
    with pytest.raises(SignatureError) as error:
        adaptador.get_status("abc")
    assert error.value.transient


def _webhook(
    tipo="solicitud.completada",
    *,
    marca=None,
    secreto=SECRETO,
    evento="ev-1",
):
    cuerpo = json.dumps(
        {"id_evento": evento, "tipo": tipo, "solicitud": estado("completada")},
    ).encode()
    marca = str(int(time.time()) if marca is None else marca)
    encabezados = {
        "X-PSC-Evento": evento,
        "X-PSC-Timestamp": marca,
        "X-PSC-Firma": firma_webhook(secreto, marca, cuerpo),
    }
    return cuerpo, encabezados


def test_a_signed_webhook_is_accepted():
    adaptador, _ = proveedor(lambda r: httpx.Response(HTTPStatus.OK))
    cuerpo, encabezados = _webhook()

    evento = adaptador.parse_webhook(cuerpo, encabezados)

    assert evento.event_id == "ev-1"
    assert evento.type is SignatureEventType.COMPLETED
    assert evento.result.status is SignatureStatus.SIGNED


@pytest.mark.parametrize(
    "falsificar",
    [
        lambda c, e: (c, {**e, "X-PSC-Firma": "v1=" + "0" * 64}),
        lambda c, e: (c + b" ", e),
        lambda c, e: (c, {k: v for k, v in e.items() if k != "X-PSC-Firma"}),
        lambda c, e: _webhook(secreto="otro"),
        lambda c, e: _webhook(marca=int(time.time()) - 301),
        lambda c, e: _webhook(marca=int(time.time()) + 301),
        lambda c, e: (c, {**e, "X-PSC-Evento": "otro"}),
        lambda c, e: _webhook(tipo="desconocido"),
    ],
    ids=[
        "forged",
        "body changed",
        "unsigned",
        "other secret",
        "too old",
        "from the future",
        "event id mismatch",
        "unknown type",
    ],
)
def test_forged_stale_or_malformed_webhooks_are_refused(falsificar):
    adaptador, _ = proveedor(lambda r: httpx.Response(HTTPStatus.OK))
    cuerpo, encabezados = falsificar(*_webhook())
    with pytest.raises(SignatureError):
        adaptador.parse_webhook(cuerpo, encabezados)


def test_the_adapter_needs_its_credentials():
    with pytest.raises(SignatureError):
        HttpSignatureProvider(BASE, "", SECRETO)

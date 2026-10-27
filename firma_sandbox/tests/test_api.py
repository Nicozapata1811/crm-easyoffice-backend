import json
from http import HTTPStatus

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from psc.models import ClienteApi
from psc.models import Solicitud

from .conftest import API_KEY
from .conftest import HOST_INTERNO
from .conftest import PERSONAS
from .conftest import firmar_todo

pytestmark = pytest.mark.django_db

DATOS = {
    "nombre_documento": "Contrato de prueba",
    "referencia_externa": "documento-7",
    "url_notificacion": "http://django:8000/api/firma/webhooks/http/",
    "firmantes": [
        {
            "orden": i + 1,
            "nombre": n,
            "rut": r,
            "email": e,
            "rol": "cliente",
            "referencia": str(10 + i),
        }
        for i, (n, r, _, e) in enumerate(PERSONAS)
    ],
}


def _crear(api, pdf, datos=DATOS):
    return api.post(
        "/api/v1/solicitudes",
        {
            "documento": SimpleUploadedFile("c.pdf", pdf, "application/pdf"),
            "datos": json.dumps(datos),
        },
        format="multipart",
    )


def test_the_api_key_is_required(cliente_api, pdf):
    sin_clave = APIClient(SERVER_NAME=HOST_INTERNO)
    assert _crear(sin_clave, pdf).status_code == HTTPStatus.UNAUTHORIZED
    sin_clave.credentials(HTTP_AUTHORIZATION="Bearer otra")
    assert _crear(sin_clave, pdf).status_code == HTTPStatus.UNAUTHORIZED


def test_the_api_key_is_stored_hashed(cliente_api):
    assert API_KEY not in ClienteApi.objects.values_list("hash_api_key", flat=True)[0]


def test_the_api_is_not_served_on_the_public_host(cliente_api, pdf):
    publica = APIClient(SERVER_NAME="localhost")
    publica.credentials(HTTP_AUTHORIZATION=f"Bearer {API_KEY}")
    assert _crear(publica, pdf).status_code == HTTPStatus.NOT_FOUND


def test_create_then_follow_a_request(api, identidades, pdf, mailoutbox):
    creada = _crear(api, pdf)
    assert creada.status_code == HTTPStatus.CREATED, creada.content
    cuerpo = creada.json()
    assert cuerpo["ambiente"] == "pruebas"
    assert cuerpo["url_firma"].startswith("http://localhost:8100/firmar/")
    assert [f["estado"] for f in cuerpo["firmantes"]] == ["pendiente"] * 3
    assert "rut" not in cuerpo["firmantes"][0]
    assert "email" not in cuerpo["firmantes"][0]

    pk = cuerpo["id"]
    assert (
        api.get(f"/api/v1/solicitudes/{pk}/documento").status_code
        == HTTPStatus.CONFLICT
    )

    firmar_todo(Solicitud.objects.get(pk=pk), mailoutbox)

    estado = api.get(f"/api/v1/solicitudes/{pk}").json()
    assert estado["estado"] == "completada"
    assert [f["referencia"] for f in estado["firmantes"]] == ["10", "11", "12"]
    descarga = api.get(f"/api/v1/solicitudes/{pk}/documento")
    assert descarga.status_code == HTTPStatus.OK
    assert descarga["Content-Type"] == "application/pdf"
    assert descarga["X-PSC-Sha256"] == estado["sha256_firmado"]
    assert descarga.content.startswith(pdf)

    informe = api.post(
        "/api/v1/validaciones",
        {"documento": SimpleUploadedFile("f.pdf", descarga.content, "application/pdf")},
        format="multipart",
    ).json()
    assert informe["valido"]
    assert len(informe["firmas"]) == len(PERSONAS)


def test_creation_validates_its_data(api, pdf):
    assert _crear(api, b"no es pdf").status_code == HTTPStatus.BAD_REQUEST
    sin_firmantes = _crear(api, pdf, {**DATOS, "firmantes": []})
    assert sin_firmantes.status_code == HTTPStatus.BAD_REQUEST


def test_cancel_and_resend(api, identidades, pdf, mailoutbox):
    cuerpo = _crear(api, pdf).json()
    pk, primero = cuerpo["id"], cuerpo["firmantes"][0]["id"]

    reenviado = api.post(f"/api/v1/solicitudes/{pk}/firmantes/{primero}/reenviar")
    assert reenviado.status_code == HTTPStatus.OK
    assert reenviado.json()["url_firma"] != cuerpo["url_firma"]
    assert len(mailoutbox) == 2  # noqa: PLR2004 - the invitation and the resend

    assert (
        api.post(f"/api/v1/solicitudes/{pk}/cancelar").json()["estado"] == "cancelada"
    )
    assert (
        api.post(f"/api/v1/solicitudes/{pk}/cancelar").status_code
        == HTTPStatus.CONFLICT
    )


def test_a_client_sees_only_its_own_requests(api, pdf):
    pk = _crear(api, pdf).json()["id"]
    ClienteApi.objects.create(nombre="otro", hash_api_key="x" * 64, secreto_webhook="s")
    Solicitud.objects.filter(pk=pk).update(
        cliente=ClienteApi.objects.get(nombre="otro"),
    )
    assert api.get(f"/api/v1/solicitudes/{pk}").status_code == HTTPStatus.NOT_FOUND


def test_the_openapi_schema_is_published(api):
    esquema = api.get("/api/v1/schema", HTTP_ACCEPT="application/json")
    assert esquema.status_code == HTTPStatus.OK
    assert "/api/v1/solicitudes" in esquema.content.decode()


def test_pki_downloads_are_public(client):
    assert client.get("/pki/raiz.crt").status_code == HTTPStatus.OK
    assert client.get("/pki/emisora.crl")["Content-Type"] == "application/pkix-crl"
    assert client.get("/pki/otra.crt").status_code == HTTPStatus.NOT_FOUND

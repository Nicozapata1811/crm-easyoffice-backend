from __future__ import annotations

import io
from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from pyhanko.pdf_utils import generic
from pyhanko.pdf_utils.writer import PageObject
from pyhanko.pdf_utils.writer import PdfFileWriter
from rest_framework.test import APIClient

from psc import pki
from psc import servicios
from psc.models import ClienteApi
from psc.models import IdentidadFicticia
from psc.models import resumen

if TYPE_CHECKING:
    from pathlib import Path

API_KEY = "clave-api-de-prueba"
SECRETO = "secreto-webhook-de-prueba"
HOST_INTERNO = "firma-sandbox"

# Fictitious people only.
PERSONAS = [
    ("Persona Ficticia Uno", "90000301-3", "A90000301", "uno@example.test"),
    ("Persona Ficticia Dos", "90000302-1", "A90000302", "dos@example.test"),
    ("Persona Ficticia Tres", "90000303-K", "A90000303", "tres@example.test"),
]


@pytest.fixture(scope="session")
def directorio_pki(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directorio = tmp_path_factory.mktemp("pki")
    settings.PKI_DIR = directorio
    pki.generar(directorio)
    return directorio


@pytest.fixture(autouse=True)
def _on_commit_inmediato(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests run inside a transaction that never commits: run the callbacks now."""
    monkeypatch.setattr(
        servicios.transaction,
        "on_commit",
        lambda funcion, **_: funcion(),
    )


@pytest.fixture(autouse=True)
def _pki(directorio_pki: Path, settings) -> None:
    settings.PKI_DIR = directorio_pki
    settings.PUBLIC_URL = "http://localhost:8100"
    pki.cargar.cache_clear()


def pdf_simple(paginas: int = 1, texto: bytes = b"Contrato de prueba") -> bytes:
    escritor = PdfFileWriter()
    fuente = generic.DictionaryObject(
        {
            generic.pdf_name("/Type"): generic.pdf_name("/Font"),
            generic.pdf_name("/Subtype"): generic.pdf_name("/Type1"),
            generic.pdf_name("/BaseFont"): generic.pdf_name("/Helvetica"),
        },
    )
    recursos = generic.DictionaryObject(
        {
            generic.pdf_name("/Font"): generic.DictionaryObject(
                {generic.pdf_name("/F1"): fuente},
            ),
        },
    )
    for numero in range(paginas):
        contenido = (
            b"BT /F1 14 Tf 72 760 Td (" + texto + f" {numero + 1}".encode() + b") Tj ET"
        )
        escritor.insert_page(
            PageObject(
                contents=escritor.add_object(
                    generic.StreamObject(stream_data=contenido),
                ),
                media_box=(0, 0, 595, 842),
                resources=recursos,
            ),
        )
    salida = io.BytesIO()
    escritor.write(salida)
    return salida.getvalue()


@pytest.fixture
def pdf() -> bytes:
    return pdf_simple()


@pytest.fixture
def cliente_api(db) -> ClienteApi:
    return ClienteApi.objects.create(
        nombre="crm",
        hash_api_key=resumen(API_KEY),
        secreto_webhook=SECRETO,
    )


@pytest.fixture
def identidades(db) -> None:
    for nombre, rut, serie, _ in PERSONAS:
        IdentidadFicticia.objects.create(rut=rut, numero_serie=serie, nombre=nombre)


@pytest.fixture
def api(cliente_api: ClienteApi) -> APIClient:
    cliente = APIClient(SERVER_NAME=HOST_INTERNO)
    cliente.credentials(HTTP_AUTHORIZATION=f"Bearer {API_KEY}")
    return cliente


def firmantes(cantidad: int = 3) -> list[servicios.FirmanteNuevo]:
    return [
        servicios.FirmanteNuevo(
            orden=i + 1,
            nombre=n,
            rut=r,
            email=e,
            rol=f"rol{i + 1}",
            referencia=str(i + 1),
        )
        for i, (n, r, _, e) in enumerate(PERSONAS[:cantidad])
    ]


@pytest.fixture
def solicitud(cliente_api, identidades, pdf):
    creada, _ = servicios.crear_solicitud(
        cliente_api,
        pdf,
        nombre_documento="Contrato de prueba",
        firmantes=firmantes(),
        referencia_externa="doc-1",
        url_notificacion="http://django:8000/api/firma/webhooks/http/",
    )
    return creada


def ultimo_codigo(mailoutbox) -> str:
    asunto = next(m.subject for m in reversed(mailoutbox) if "código" in m.subject)
    return asunto.rsplit(" ", 1)[-1]


def firmar_todo(solicitud, mailoutbox, hasta: int | None = None):
    """Take every signer (or the first ``hasta``) through identity, code, signature."""
    for firmante in solicitud.firmantes.order_by("orden")[:hasta]:
        _, _, serie, _ = PERSONAS[firmante.orden - 1]
        assert servicios.verificar_identidad(
            firmante,
            {"rut": firmante.rut, "numero_serie": serie},
        )
        servicios.enviar_codigo(firmante)
        servicios.firmar(firmante, ultimo_codigo(mailoutbox), consiente=True)
    solicitud.refresh_from_db()
    return solicitud

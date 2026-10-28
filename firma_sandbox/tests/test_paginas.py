from http import HTTPStatus

import pytest

from psc import servicios
from psc.models import Firmante

from .conftest import firmantes
from .conftest import ultimo_codigo

pytestmark = pytest.mark.django_db


@pytest.fixture
def enlace(cliente_api, identidades, pdf):
    _, url = servicios.crear_solicitud(
        cliente_api,
        pdf,
        nombre_documento="Contrato de prueba",
        firmantes=firmantes(),
    )
    return url.removeprefix("http://localhost:8100")


def test_an_unknown_link_is_not_found(client):
    assert client.get("/firmar/no-existe/").status_code == HTTPStatus.NOT_FOUND


def test_the_page_shows_the_document(client, enlace):
    pagina = client.get(enlace).content.decode()
    assert "Contrato de prueba" in pagina
    assert "documento.pdf" in pagina
    documento = client.get(f"{enlace}documento.pdf")
    assert documento["Content-Type"] == "application/pdf"


def test_a_signer_signs_from_the_page(client, enlace, mailoutbox):
    malo = client.post(
        enlace,
        {"accion": "identidad", "rut": "90000301-3", "numero_serie": "X"},
    )
    assert malo.status_code == HTTPStatus.BAD_REQUEST
    assert "no coinciden" in malo.content.decode()

    client.post(
        enlace,
        {"accion": "identidad", "rut": "90.000.301-3", "numero_serie": "A90000301"},
    )
    client.post(enlace, {"accion": "codigo"})
    firmado = client.post(
        enlace,
        {"accion": "firmar", "codigo": ultimo_codigo(mailoutbox), "consiento": "si"},
    )

    assert "Documento firmado" in firmado.content.decode()
    assert Firmante.objects.get(orden=1).estado == Firmante.Estado.FIRMADO
    assert mailoutbox[-1].to == ["dos@example.test"]


def test_a_signer_declines_from_the_page(client, enlace):
    respuesta = client.post(enlace, {"accion": "rechazar", "motivo": "No corresponde."})
    assert "rechazo" in respuesta.content.decode()
    assert Firmante.objects.get(orden=1).estado == Firmante.Estado.RECHAZADO


def test_the_verification_page(client, enlace, mailoutbox):
    client.post(
        enlace,
        {"accion": "identidad", "rut": "90000301-3", "numero_serie": "A90000301"},
    )
    client.post(enlace, {"accion": "codigo"})
    client.post(
        enlace,
        {"accion": "firmar", "codigo": ultimo_codigo(mailoutbox), "consiento": "si"},
    )
    codigo = Firmante.objects.get(orden=1).codigo_verificacion

    pagina = client.get(f"/verificar/{codigo}/")
    assert pagina.status_code == HTTPStatus.OK
    assert "Persona Ficticia Uno" in pagina.content.decode()
    assert client.get("/verificar/PRU-NADA/").status_code == HTTPStatus.NOT_FOUND

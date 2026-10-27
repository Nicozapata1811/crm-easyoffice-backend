"""PAdES signing and validation, without the HTTP layer."""

import io

import pytest
from pyhanko.pdf_utils.reader import PdfFileReader

from psc import firma
from psc import pki

from .conftest import pdf_simple

pytestmark = pytest.mark.django_db

PERSONAS = [
    ("Persona Ficticia Uno", "90000301-3"),
    ("Persona Ficticia Dos", "90000302-1"),
]


def _firmar(documento: bytes, indice: int, total: int) -> bytes:
    generada = pki.cargar()
    nombre, rut = PERSONAS[indice - 1]
    cert, clave = pki.emitir_firmante(generada, nombre, rut)
    crls = [
        pki.asn1_crl_de(pki.lista_revocacion(generada.raiz, generada.clave_raiz)),
        pki.asn1_crl_de(pki.lista_revocacion(generada.emisora, generada.clave_emisora)),
    ]
    ocsps = [pki.asn1_ocsp_de(pki.respuesta_ocsp(generada, cert, None))]
    return firma.firmar(
        documento,
        firma.Firma(indice, total, nombre, rut, f"PRU-{indice}", cert, clave),
        generada,
        crls=crls,
        ocsps=ocsps,
    )


@pytest.fixture(scope="module")
def firmado_por_dos(directorio_pki) -> tuple[bytes, bytes, bytes]:
    original = pdf_simple(paginas=2)
    preparado = firma.preparar(original, 2)
    uno = _firmar(preparado, 1, 2)
    return original, uno, _firmar(uno, 2, 2)


def test_preparation_adds_the_signature_page_and_one_field_per_signer():
    original = pdf_simple(paginas=3)
    preparado = firma.preparar(original, 3)

    assert preparado.startswith(original)
    lector = PdfFileReader(io.BytesIO(preparado))
    assert int(lector.root["/Pages"]["/Count"]) == 3 + 1
    campos = [c.get_object()["/T"] for c in lector.root["/AcroForm"]["/Fields"]]
    assert campos == ["Firma1", "Firma2", "Firma3"]


def test_a_signed_pdf_is_not_prepared_again(firmado_por_dos):
    _, uno, _ = firmado_por_dos
    with pytest.raises(firma.DocumentoInvalidoError):
        firma.preparar(uno, 1)


def test_each_signature_validates_against_the_test_root(firmado_por_dos):
    _, uno, _ = firmado_por_dos
    informe = firma.validar(uno, pki.cargar())

    assert informe.valido, informe.errores
    [unica] = informe.firmas
    assert unica.nombre == "Persona Ficticia Uno"
    assert unica.rut == "90000301-3"
    assert unica.confiable
    assert unica.sello_de_tiempo
    assert unica.revocacion_embebida


def test_earlier_signatures_keep_validating_after_later_ones(firmado_por_dos):
    original, uno, dos = firmado_por_dos
    informe = firma.validar(dos, pki.cargar())

    assert informe.valido, informe.errores
    assert [f.nombre for f in informe.firmas] == [
        "Persona Ficticia Uno",
        "Persona Ficticia Dos",
    ]
    assert all(f.valida and f.sello_de_tiempo for f in informe.firmas)
    assert informe.sello_documento, (
        "the last signature adds a document timestamp (B-LTA)"
    )
    assert dos.startswith(uno)
    assert dos.startswith(original)


def test_a_tampered_pdf_fails_validation(firmado_por_dos):
    _, _, dos = firmado_por_dos
    alterado = bytearray(dos)
    posicion = dos.index(b"Contrato de prueba")
    alterado[posicion] = ord("X")

    informe = firma.validar(bytes(alterado), pki.cargar())

    assert not informe.valido
    assert not informe.documento_sin_cambios
    assert not any(f.intacta for f in informe.firmas)


def test_a_document_signed_under_another_root_is_not_trusted(firmado_por_dos, tmp_path):
    _, _, dos = firmado_por_dos
    otra = pki.generar(tmp_path)

    informe = firma.validar(dos, otra)

    assert not informe.valido
    assert not any(f.confiable for f in informe.firmas)


def test_an_unsigned_pdf_is_reported_as_such():
    informe = firma.validar(pdf_simple(), pki.cargar())
    assert not informe.valido
    assert informe.errores == ["El documento no tiene firmas."]


def test_not_a_pdf():
    with pytest.raises(firma.DocumentoInvalidoError):
        firma.preparar(b"esto no es un PDF", 1)

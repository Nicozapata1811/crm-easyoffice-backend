import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import NameOID

from psc import pki


def _cn(cert: x509.Certificate) -> str:
    return cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value


def test_generation_writes_a_test_root_issuing_ca_and_tsa(tmp_path, settings):
    generada = pki.generar(tmp_path)

    assert pki.existe(tmp_path)
    assert _cn(generada.raiz) == "CRM Easy Office – CA Raíz de PRUEBAS"  # noqa: RUF001
    assert _cn(generada.emisora) == "CRM Easy Office – CA Emisora de PRUEBAS"  # noqa: RUF001
    assert "PRUEBAS" in _cn(generada.tsa)
    organizacion = generada.raiz.subject.get_attributes_for_oid(
        NameOID.ORGANIZATION_NAME,
    )[0].value
    assert "sin validez legal" in organizacion
    generada.emisora.verify_directly_issued_by(generada.raiz)
    generada.tsa.verify_directly_issued_by(generada.emisora)


def test_private_keys_are_encrypted_at_rest(tmp_path):
    pki.generar(tmp_path)
    for nombre in pki.ARCHIVOS:
        datos = (tmp_path / f"{nombre}.key").read_bytes()
        assert b"ENCRYPTED PRIVATE KEY" in datos
        with pytest.raises(TypeError):
            serialization.load_pem_private_key(datos, password=None)
        assert (tmp_path / f"{nombre}.key").stat().st_mode & 0o077 == 0


def test_rotation_keeps_the_root_and_replaces_the_rest(tmp_path):
    antes = pki.generar(tmp_path)
    despues = pki.generar(tmp_path, conservar_raiz=True)

    assert despues.raiz.fingerprint(
        despues.raiz.signature_hash_algorithm,
    ) == antes.raiz.fingerprint(
        antes.raiz.signature_hash_algorithm,
    )
    assert despues.emisora.serial_number != antes.emisora.serial_number
    despues.emisora.verify_directly_issued_by(antes.raiz)


def test_loading_without_a_pki_says_how_to_create_it(tmp_path):
    pki.cargar.cache_clear()
    with pytest.raises(pki.PkiNoGeneradaError, match="generar_pki"):
        pki.cargar(tmp_path / "vacio")


def test_signer_certificates_carry_name_rut_and_revocation_pointers(settings):
    generada = pki.cargar()
    cert, _ = pki.emitir_firmante(generada, "Persona Ficticia Uno", "90000301-3")

    assert _cn(cert) == "Persona Ficticia Uno"
    assert (
        cert.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER)[0].value
        == "90000301-3"
    )
    assert (
        cert.not_valid_after_utc - cert.not_valid_before_utc
    ).days <= settings.CERTIFICADO_DIAS
    accesos = cert.extensions.get_extension_for_class(
        x509.AuthorityInformationAccess,
    ).value
    assert accesos[0].access_location.value == "http://localhost:8100/pki/ocsp"
    cert.verify_directly_issued_by(generada.emisora)

"""The test PKI: a root CA, an issuing CA, a timestamp authority, and the
single-use certificates issued to signers.

Everything is named as a test system and generated on the machine that runs
it, into an ignored directory. Nothing here is ever committed.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING

from asn1crypto import crl as asn1_crl
from asn1crypto import keys as asn1_keys
from asn1crypto import ocsp as asn1_ocsp
from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509 import ocsp
from cryptography.x509.oid import AuthorityInformationAccessOID
from cryptography.x509.oid import ExtendedKeyUsageOID
from cryptography.x509.oid import NameOID
from django.conf import settings

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from cryptography.hazmat.primitives.asymmetric.types import (
        CertificateIssuerPrivateKeyTypes,
    )
    from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes

ORGANIZACION = "PSC de pruebas (sin validez legal)"
NOMBRE_RAIZ = "CRM Easy Office – CA Raíz de PRUEBAS"  # noqa: RUF001
NOMBRE_EMISORA = "CRM Easy Office – CA Emisora de PRUEBAS"  # noqa: RUF001
NOMBRE_TSA = "CRM Easy Office – TSA de PRUEBAS"  # noqa: RUF001
DIAS_RAIZ = 5 * 365
DIAS_EMISORA = 2 * 365
VIGENCIA_REVOCACION = timedelta(days=7)

ARCHIVOS = ("raiz", "emisora", "tsa")


class PkiNoGeneradaError(Exception):
    """The test PKI has not been generated yet (manage.py generar_pki)."""


@dataclass(frozen=True)
class Pki:
    raiz: x509.Certificate
    clave_raiz: ec.EllipticCurvePrivateKey
    emisora: x509.Certificate
    clave_emisora: ec.EllipticCurvePrivateKey
    tsa: x509.Certificate
    clave_tsa: rsa.RSAPrivateKey


def _ahora() -> datetime:
    return datetime.now(UTC)


def _nombre(cn: str, *extra: x509.NameAttribute) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "CL"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, ORGANIZACION),
            *extra,
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
        ],
    )


def _uso(**permitidos: bool) -> x509.KeyUsage:
    usos = dict.fromkeys(
        (
            "digital_signature",
            "content_commitment",
            "key_encipherment",
            "data_encipherment",
            "key_agreement",
            "key_cert_sign",
            "crl_sign",
            "encipher_only",
            "decipher_only",
        ),
        False,
    )
    usos.update(permitidos)
    return x509.KeyUsage(**usos)


def _distribucion(nombre_crl: str) -> x509.CRLDistributionPoints:
    url = f"{settings.PUBLIC_URL}/pki/{nombre_crl}.crl"
    return x509.CRLDistributionPoints(
        [
            x509.DistributionPoint(
                [x509.UniformResourceIdentifier(url)],
                None,
                None,
                None,
            ),
        ],
    )


def _certificado(  # noqa: PLR0913
    sujeto: x509.Name,
    publica: ec.EllipticCurvePublicKey | rsa.RSAPublicKey,
    emisor: x509.Certificate | None,
    clave_emisor: CertificateIssuerPrivateKeyTypes,
    *,
    dias: int,
    ca: bool,
    extensiones: Iterable[tuple[x509.ExtensionType, bool]] = (),
) -> x509.Certificate:
    ahora = _ahora()
    constructor = (
        x509.CertificateBuilder()
        .subject_name(sujeto)
        .issuer_name(emisor.subject if emisor else sujeto)
        .public_key(publica)
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - timedelta(minutes=5))
        .not_valid_after(ahora + timedelta(days=dias))
        .add_extension(
            x509.BasicConstraints(
                ca=ca,
                path_length=None if not ca else (0 if emisor else 1),
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(publica),
            critical=False,
        )
    )
    if emisor is not None:
        constructor = constructor.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(emisor.public_key()),  # type: ignore[arg-type]
            critical=False,
        )
    for extension, critica in extensiones:
        constructor = constructor.add_extension(extension, critical=critica)
    return constructor.sign(clave_emisor, hashes.SHA256())


def _guardar(
    directorio: Path,
    nombre: str,
    cert: x509.Certificate,
    clave: PrivateKeyTypes,
) -> None:
    (directorio / f"{nombre}.crt").write_bytes(
        cert.public_bytes(serialization.Encoding.PEM),
    )
    ruta_clave = directorio / f"{nombre}.key"
    ruta_clave.write_bytes(cifrar_clave(clave))
    ruta_clave.chmod(0o600)


def _emitir_intermedias(
    raiz: x509.Certificate,
    clave_raiz: ec.EllipticCurvePrivateKey,
) -> tuple:
    clave_emisora = ec.generate_private_key(ec.SECP384R1())
    emisora = _certificado(
        _nombre(NOMBRE_EMISORA),
        clave_emisora.public_key(),
        raiz,
        clave_raiz,
        dias=DIAS_EMISORA,
        ca=True,
        extensiones=[
            (_uso(key_cert_sign=True, crl_sign=True), True),
            (_distribucion("raiz"), False),
        ],
    )
    # pyHanko's timestamper signs with RSA only.
    clave_tsa = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    tsa = _certificado(
        _nombre(NOMBRE_TSA),
        clave_tsa.public_key(),
        emisora,
        clave_emisora,
        dias=DIAS_EMISORA,
        ca=False,
        extensiones=[
            (_uso(digital_signature=True), True),
            (x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), True),
            (_distribucion("emisora"), False),
        ],
    )
    return emisora, clave_emisora, tsa, clave_tsa


def generar(directorio: Path | None = None, *, conservar_raiz: bool = False) -> Pki:
    """Create the test PKI; with ``conservar_raiz`` only the issuing CA and the TSA.

    Keeping the root is what a rotation does: documents signed before it
    still chain to the same trust anchor, through the certificates their
    DSS embeds.
    """
    directorio = directorio or settings.PKI_DIR
    directorio.mkdir(parents=True, exist_ok=True)
    directorio.chmod(0o700)
    if conservar_raiz:
        actual = cargar(directorio)
        raiz, clave_raiz = actual.raiz, actual.clave_raiz
    else:
        clave_raiz = ec.generate_private_key(ec.SECP384R1())
        raiz = _certificado(
            _nombre(NOMBRE_RAIZ),
            clave_raiz.public_key(),
            None,
            clave_raiz,
            dias=DIAS_RAIZ,
            ca=True,
            extensiones=[(_uso(key_cert_sign=True, crl_sign=True), True)],
        )
        _guardar(directorio, "raiz", raiz, clave_raiz)
    emisora, clave_emisora, tsa, clave_tsa = _emitir_intermedias(raiz, clave_raiz)
    _guardar(directorio, "emisora", emisora, clave_emisora)
    _guardar(directorio, "tsa", tsa, clave_tsa)
    cargar.cache_clear()
    return Pki(raiz, clave_raiz, emisora, clave_emisora, tsa, clave_tsa)


def existe(directorio: Path | None = None) -> bool:
    directorio = directorio or settings.PKI_DIR
    return all(
        (directorio / f"{n}.{ext}").exists() for n in ARCHIVOS for ext in ("crt", "key")
    )


@functools.cache
def cargar(directorio: Path | None = None) -> Pki:
    directorio = directorio or settings.PKI_DIR
    if not existe(directorio):
        msg = f"No test PKI in {directorio}: run manage.py generar_pki."
        raise PkiNoGeneradaError(msg)

    def par(nombre: str) -> tuple[x509.Certificate, PrivateKeyTypes]:
        cert = x509.load_pem_x509_certificate(
            (directorio / f"{nombre}.crt").read_bytes(),
        )
        return cert, descifrar_clave((directorio / f"{nombre}.key").read_bytes())

    raiz, clave_raiz = par("raiz")
    emisora, clave_emisora = par("emisora")
    tsa, clave_tsa = par("tsa")
    return Pki(raiz, clave_raiz, emisora, clave_emisora, tsa, clave_tsa)  # type: ignore[arg-type]


def emitir_firmante(
    pki: Pki,
    nombre: str,
    rut: str,
) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    """Issue a signer's single-use certificate: name and RUT, a week of validity."""
    clave = ec.generate_private_key(ec.SECP256R1())
    sujeto = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "CL"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, ORGANIZACION),
            x509.NameAttribute(NameOID.SERIAL_NUMBER, rut),
            x509.NameAttribute(NameOID.COMMON_NAME, nombre),
        ],
    )
    ocsp_url = x509.UniformResourceIdentifier(f"{settings.PUBLIC_URL}/pki/ocsp")
    cert = _certificado(
        sujeto,
        clave.public_key(),
        pki.emisora,
        pki.clave_emisora,
        dias=settings.CERTIFICADO_DIAS,
        ca=False,
        extensiones=[
            (_uso(digital_signature=True, content_commitment=True), True),
            (
                x509.AuthorityInformationAccess(
                    [
                        x509.AccessDescription(
                            AuthorityInformationAccessOID.OCSP,
                            ocsp_url,
                        ),
                    ],
                ),
                False,
            ),
            (_distribucion("emisora"), False),
        ],
    )
    return cert, clave


def lista_revocacion(
    emisor: x509.Certificate,
    clave: ec.EllipticCurvePrivateKey,
    revocados: Iterable[tuple[int, datetime]] = (),
) -> x509.CertificateRevocationList:
    ahora = _ahora()
    constructor = (
        x509.CertificateRevocationListBuilder()
        .issuer_name(emisor.subject)
        .last_update(ahora - timedelta(minutes=5))
        .next_update(ahora + VIGENCIA_REVOCACION)
        .add_extension(x509.CRLNumber(int(ahora.timestamp())), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(emisor.public_key()),
            critical=False,
        )  # type: ignore[arg-type]
    )
    for serie, fecha in revocados:
        constructor = constructor.add_revoked_certificate(
            x509.RevokedCertificateBuilder()
            .serial_number(serie)
            .revocation_date(fecha)
            .build(),
        )
    return constructor.sign(clave, hashes.SHA256())


def respuesta_ocsp(
    pki: Pki,
    cert: x509.Certificate,
    revocado_en: datetime | None,
) -> ocsp.OCSPResponse:
    """A response signed by the issuing CA itself, which RFC 6960 allows."""
    ahora = _ahora()
    estado = ocsp.OCSPCertStatus.REVOKED if revocado_en else ocsp.OCSPCertStatus.GOOD
    return (
        ocsp.OCSPResponseBuilder()
        .add_response(
            cert=cert,
            issuer=pki.emisora,
            algorithm=hashes.SHA256(),
            cert_status=estado,
            this_update=ahora - timedelta(minutes=1),
            next_update=ahora + VIGENCIA_REVOCACION,
            revocation_time=revocado_en,
            revocation_reason=x509.ReasonFlags.cessation_of_operation
            if revocado_en
            else None,
        )
        .responder_id(ocsp.OCSPResponderEncoding.HASH, pki.emisora)
        .sign(pki.clave_emisora, hashes.SHA256())
    )


def respuesta_ocsp_desconocida() -> ocsp.OCSPResponse:
    return ocsp.OCSPResponseBuilder.build_unsuccessful(
        ocsp.OCSPResponseStatus.UNAUTHORIZED,
    )


def cifrar_clave(clave: PrivateKeyTypes) -> bytes:
    return clave.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(settings.KEY_PASSPHRASE.encode()),
    )


def descifrar_clave(datos: bytes) -> PrivateKeyTypes:
    return serialization.load_pem_private_key(
        datos,
        password=settings.KEY_PASSPHRASE.encode(),
    )


# -- asn1crypto views, which pyHanko works with ---------------------------------


def asn1_certificado(cert: x509.Certificate) -> asn1_x509.Certificate:
    return asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER))


def asn1_clave(clave: PrivateKeyTypes) -> asn1_keys.PrivateKeyInfo:
    return asn1_keys.PrivateKeyInfo.load(
        clave.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )


def asn1_crl_de(lista: x509.CertificateRevocationList) -> asn1_crl.CertificateList:
    return asn1_crl.CertificateList.load(lista.public_bytes(serialization.Encoding.DER))


def asn1_ocsp_de(respuesta: ocsp.OCSPResponse) -> asn1_ocsp.OCSPResponse:
    return asn1_ocsp.OCSPResponse.load(
        respuesta.public_bytes(serialization.Encoding.DER),
    )

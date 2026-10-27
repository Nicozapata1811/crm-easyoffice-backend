"""PAdES signing and validation with pyHanko.

Every change is an incremental update, so the original bytes stay an exact
prefix of the result and earlier signatures keep validating:

1. ``preparar`` appends a signature page with one empty field per signer.
2. ``firmar`` adds one signer's signature (PAdES B-LT: a signature timestamp,
   plus the chain, the CRLs and an OCSP response in the DSS). The last
   signer's revision also gets a document timestamp (B-LTA).
3. ``validar`` checks every signature offline, against the test root and
   only the validation data the file carries.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

from pyhanko.pdf_utils import generic
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.layout import BoxConstraints
from pyhanko.pdf_utils.misc import PdfError
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.pdf_utils.writer import PageObject
from pyhanko.sign import fields
from pyhanko.sign import signers
from pyhanko.sign.timestamps.dummy_client import DummyTimeStamper
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko.sign.validation import validate_pdf_timestamp
from pyhanko.sign.validation.dss import DocumentSecurityStore
from pyhanko.stamp import TextStamp
from pyhanko.stamp import TextStampStyle
from pyhanko.stamp.text import TextBoxStyle
from pyhanko_certvalidator import ValidationContext
from pyhanko_certvalidator.registry import SimpleCertificateStore

from . import pki as pki_mod

if TYPE_CHECKING:
    from datetime import datetime

    from asn1crypto import crl as asn1_crl
    from asn1crypto import ocsp as asn1_ocsp
    from cryptography import x509
    from cryptography.hazmat.primitives.asymmetric import ec

logger = logging.getLogger(__name__)

TITULO_HOJA = "Hoja de firmas"
LEYENDA_FIRMA = "Firma electrónica avanzada"

ANCHO_PAGINA, ALTO_PAGINA = 595, 842
ALTO_CAMPO = 120
SEPARACION = 20
MARGEN = 60


class DocumentoInvalidoError(Exception):
    """The file is not a PDF this service can work with."""


def _campo(indice: int) -> str:
    return f"Firma{indice}"


def _caja(posicion: int) -> tuple[int, int, int, int]:
    """Where signer ``posicion`` (0-based) goes on the signature page."""
    alto = ALTO_PAGINA - 150 - posicion * (ALTO_CAMPO + SEPARACION)
    return (MARGEN, alto - ALTO_CAMPO, ANCHO_PAGINA - MARGEN, alto)


def _escritor(pdf: bytes) -> IncrementalPdfFileWriter:
    try:
        return IncrementalPdfFileWriter(io.BytesIO(pdf), strict=False)
    except (PdfError, ValueError) as exc:
        msg = "The file is not a readable PDF."
        raise DocumentoInvalidoError(msg) from exc


def preparar(pdf: bytes, firmantes: int) -> bytes:
    """Append the signature page, with one empty field per signer.

    Raises:
        DocumentoInvalidoError: Not a readable PDF, or already signed.
    """
    escritor = _escritor(pdf)
    if escritor.prev.embedded_signatures:
        msg = "The document is already signed."
        raise DocumentoInvalidoError(msg)
    paginas = int(escritor.root["/Pages"]["/Count"])
    contenido = escritor.add_object(generic.StreamObject(stream_data=b""))
    escritor.insert_page(
        PageObject(contents=contenido, media_box=(0, 0, ANCHO_PAGINA, ALTO_PAGINA)),
    )
    TextStamp(
        escritor,
        TextStampStyle(
            stamp_text=TITULO_HOJA,
            border_width=0,
            text_box_style=TextBoxStyle(font_size=12),
        ),
        box=BoxConstraints(width=ANCHO_PAGINA - 2 * MARGEN, height=50),
    ).apply(paginas, MARGEN, ALTO_PAGINA - 100)
    for posicion in range(firmantes):
        fields.append_signature_field(
            escritor,
            fields.SigFieldSpec(
                _campo(posicion + 1),
                on_page=paginas,
                box=_caja(posicion),
            ),
        )
    salida = io.BytesIO()
    escritor.write(salida)
    return salida.getvalue()


def timestamper(pki: pki_mod.Pki) -> DummyTimeStamper:
    return DummyTimeStamper(
        tsa_cert=pki_mod.asn1_certificado(pki.tsa),
        tsa_key=pki_mod.asn1_clave(pki.clave_tsa),
        certs_to_embed=SimpleCertificateStore.from_certs(
            [pki_mod.asn1_certificado(pki.emisora), pki_mod.asn1_certificado(pki.raiz)],
        ),
    )


@dataclass(frozen=True)
class Firma:
    """One signer's signature, with everything it needs to be made."""

    indice: int
    total: int
    nombre: str
    rut: str
    codigo_verificacion: str
    certificado: x509.Certificate
    clave: ec.EllipticCurvePrivateKey


def firmar(
    pdf: bytes,
    firma: Firma,
    pki: pki_mod.Pki,
    *,
    crls: list[asn1_crl.CertificateList],
    ocsps: list[asn1_ocsp.OCSPResponse],
) -> bytes:
    """Add one signature, PAdES B-LT, in its own incremental revision.

    The revocation data is built in-process by the caller: the service is its
    own CA, so it never needs to fetch anything.
    """
    raiz = pki_mod.asn1_certificado(pki.raiz)
    intermedias = [pki_mod.asn1_certificado(pki.emisora), raiz]
    firmante = signers.SimpleSigner(
        signing_cert=pki_mod.asn1_certificado(firma.certificado),
        signing_key=pki_mod.asn1_clave(firma.clave),
        cert_registry=SimpleCertificateStore.from_certs(intermedias),
    )
    contexto = ValidationContext(
        trust_roots=[raiz],
        allow_fetching=False,
        crls=crls,
        ocsps=ocsps,
        other_certs=[*intermedias, pki_mod.asn1_certificado(pki.tsa)],
    )
    metadatos = signers.PdfSignatureMetadata(
        field_name=_campo(firma.indice),
        name=firma.nombre,
        reason=LEYENDA_FIRMA,
        location="Chile",
        subfilter=fields.SigSeedSubFilter.PADES,
        embed_validation_info=True,
        validation_context=contexto,
        use_pades_lta=firma.indice == firma.total,
    )
    estilo = TextStampStyle(
        stamp_text=(
            "%(nombre)s - RUT %(rut)s\n"
            "%(ts)s\n"
            f"{LEYENDA_FIRMA}\n"
            "Código de verificación: %(codigo)s"
        ),
        timestamp_format="%d-%m-%Y %H:%M:%S %Z",
        text_box_style=TextBoxStyle(font_size=9),
    )
    salida = io.BytesIO()
    signers.PdfSigner(
        metadatos,
        signer=firmante,
        timestamper=timestamper(pki),
        stamp_style=estilo,
    ).sign_pdf(
        _escritor(pdf),
        output=salida,
        appearance_text_params={
            "nombre": firma.nombre,
            "rut": firma.rut,
            "codigo": firma.codigo_verificacion,
        },
    )
    return salida.getvalue()


@dataclass
class FirmaValidada:
    campo: str
    nombre: str | None
    rut: str | None
    firmado_en: datetime | None
    intacta: bool
    confiable: bool
    valida: bool
    cubre_revision: bool
    sello_de_tiempo: bool
    revocacion_embebida: bool
    modificaciones_permitidas: bool


@dataclass
class Informe:
    firmas: list[FirmaValidada] = field(default_factory=list)
    sello_documento: bool = False
    documento_sin_cambios: bool = False
    errores: list[str] = field(default_factory=list)

    @property
    def valido(self) -> bool:
        return (
            bool(self.firmas)
            and self.documento_sin_cambios
            and all(f.valida for f in self.firmas)
        )


def _atributo(nombre, oid: str) -> str | None:
    for rdn in nombre.chosen:
        for atributo in rdn:
            if atributo["type"].native == oid:
                return atributo["value"].native
    return None


def validar(pdf: bytes, pki: pki_mod.Pki) -> Informe:
    """Validate every signature offline against the test root.

    Only the validation data embedded in the file (the DSS) is used, with
    revocation checking in hard-fail mode: a signature that validates here
    validates on any machine that trusts the test root.
    """
    informe = Informe()
    try:
        lector = PdfFileReader(io.BytesIO(pdf), strict=False)
        firmas = lector.embedded_signatures
    except (PdfError, ValueError) as exc:
        informe.errores.append(f"No es un PDF legible: {exc}")
        return informe

    if not firmas:
        informe.errores.append("El documento no tiene firmas.")
        return informe

    dss = DocumentSecurityStore.read_dss(lector) if "/DSS" in lector.root else None
    raiz = pki_mod.asn1_certificado(pki.raiz)
    parametros = {
        "trust_roots": [raiz],
        "allow_fetching": False,
        "revocation_mode": "hard-fail",
    }
    contexto = (
        dss.as_validation_context(parametros)
        if dss
        else ValidationContext(**parametros)
    )
    revocacion = bool(dss and (dss.ocsps or dss.crls))

    sin_cambios = True
    for embebida in firmas:
        if embebida.sig_object_type == "/DocTimeStamp":
            estado = validate_pdf_timestamp(embebida, validation_context=contexto)
            informe.sello_documento = estado.valid and estado.intact and estado.trusted
            sin_cambios &= estado.intact
            continue
        try:
            estado = validate_pdf_signature(embebida, contexto)
        except Exception as exc:  # noqa: BLE001 - any failure means "not valid", reported as such
            logger.info("Signature %s did not validate: %s", embebida.field_name, exc)
            informe.errores.append(f"{embebida.field_name}: {exc}")
            sin_cambios = False
            continue
        sujeto = estado.signing_cert.subject
        cubre = estado.coverage is not None and estado.coverage.name in {
            "ENTIRE_FILE",
            "ENTIRE_REVISION",
        }
        permitidas = (
            estado.modification_level is not None
            and estado.modification_level.name
            in {
                "NONE",
                "LTA_UPDATES",
                "FORM_FILLING",
            }
        )
        con_sello = (
            estado.timestamp_validity is not None and estado.timestamp_validity.trusted
        )
        informe.firmas.append(
            FirmaValidada(
                campo=embebida.field_name,
                nombre=_atributo(sujeto, "common_name"),
                rut=_atributo(sujeto, "serial_number"),
                firmado_en=estado.timestamp_validity.timestamp
                if con_sello
                else estado.signer_reported_dt,
                intacta=estado.intact,
                confiable=estado.trusted,
                valida=estado.bottom_line and cubre and permitidas and con_sello,
                cubre_revision=cubre,
                sello_de_tiempo=con_sello,
                revocacion_embebida=revocacion,
                modificaciones_permitidas=permitidas,
            ),
        )
        sin_cambios &= estado.intact and cubre and permitidas
    informe.documento_sin_cambios = sin_cambios
    return informe

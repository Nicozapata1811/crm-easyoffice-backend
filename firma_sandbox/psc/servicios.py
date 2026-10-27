"""What the PSC does: create requests, check identity, send codes, sign in
order, decline, cancel and expire. Views and commands only call these."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from . import firma as firma_pdf
from . import pki as pki_mod
from . import webhooks
from .identidad import normalizar_rut
from .identidad import verificador
from .models import Certificado
from .models import ClienteApi
from .models import CodigoOtp
from .models import Firmante
from .models import Solicitud
from .models import resumen

if TYPE_CHECKING:
    from datetime import datetime

logger = logging.getLogger(__name__)

MAX_BYTES = 10 * 1024 * 1024
MAX_FIRMANTES = 10
MAX_DIAS = 30


class OperacionNoPermitidaError(Exception):
    """The request or the signer is not in a state that allows this."""


class DatosInvalidosError(Exception):
    def __init__(self, errores: dict[str, Any]) -> None:
        super().__init__(str(errores))
        self.errores = errores


@dataclass(frozen=True)
class FirmanteNuevo:
    orden: int
    nombre: str
    rut: str
    email: str
    rol: str = ""
    referencia: str = ""


# -- Requests ------------------------------------------------------------------


def _validar(
    pdf: bytes,
    firmantes: list[FirmanteNuevo],
    expira_en: datetime | None,
) -> dict[str, Any]:
    errores: dict[str, Any] = {}
    if not pdf.startswith(b"%PDF-"):
        errores["documento"] = "Debe ser un PDF."
    elif len(pdf) > MAX_BYTES:
        errores["documento"] = "El PDF supera los 10 MB."
    if not 1 <= len(firmantes) <= MAX_FIRMANTES:
        errores["firmantes"] = f"Entre 1 y {MAX_FIRMANTES} firmantes."
    elif sorted(f.orden for f in firmantes) != list(range(1, len(firmantes) + 1)):
        errores["firmantes"] = "El orden debe ser 1, 2, … sin repetir."
    ahora = timezone.now()
    if expira_en is not None and not ahora < expira_en <= ahora + timedelta(
        days=MAX_DIAS,
    ):
        errores["expira_en"] = f"Debe estar entre ahora y {MAX_DIAS} días más."
    return errores


def url_firma(token: str) -> str:
    return f"{settings.PUBLIC_URL}/firmar/{token}/"


def crear_solicitud(  # noqa: PLR0913
    cliente: ClienteApi,
    pdf: bytes,
    *,
    nombre_documento: str,
    firmantes: list[FirmanteNuevo],
    referencia_externa: str = "",
    url_notificacion: str = "",
    expira_en: datetime | None = None,
) -> tuple[Solicitud, str]:
    """Create a request; the first signer is invited by email.

    Returns the request and the first signer's link. Each later signer gets
    a fresh link by email when their turn comes; only link hashes are stored.

    Raises:
        DatosInvalidosError: The PDF or the signers are not acceptable.
    """
    if errores := _validar(pdf, firmantes, expira_en):
        raise DatosInvalidosError(errores)
    try:
        preparado = firma_pdf.preparar(pdf, len(firmantes))
    except firma_pdf.DocumentoInvalidoError as exc:
        raise DatosInvalidosError({"documento": str(exc)}) from exc

    with transaction.atomic():
        solicitud = Solicitud.objects.create(
            cliente=cliente,
            nombre_documento=nombre_documento[:200],
            referencia_externa=referencia_externa[:200],
            url_notificacion=url_notificacion,
            documento_original=pdf,
            sha256_original=resumen(pdf),
            documento_actual=preparado,
            expira_en=expira_en
            or timezone.now() + timedelta(days=settings.SOLICITUD_DIAS_POR_DEFECTO),
        )
        for nuevo in sorted(firmantes, key=lambda f: f.orden):
            firmante = Firmante(
                solicitud=solicitud,
                orden=nuevo.orden,
                nombre=nuevo.nombre[:200],
                rut=normalizar_rut(nuevo.rut),
                email=nuevo.email,
                rol=nuevo.rol[:50],
                referencia=nuevo.referencia[:100],
            )
            token = firmante.nuevo_token()
            firmante.save()
            if nuevo.orden == 1:
                primero, enlace = firmante, url_firma(token)
        transaction.on_commit(lambda: _invitar(primero, enlace))
    return solicitud, enlace


def _invitar(firmante: Firmante, enlace: str) -> None:
    send_mail(
        f"Documento para firmar: {firmante.solicitud.nombre_documento}",
        (
            f"Hola, {firmante.nombre}:\n\n"
            f"Tienes un documento para firmar: {firmante.solicitud.nombre_documento}.\n"
            f"Ábrelo aquí: {enlace}\n"
        ),
        None,
        [firmante.email],
    )
    Firmante.objects.filter(pk=firmante.pk).update(invitado_en=timezone.now())


def _exigir_abierta(solicitud: Solicitud) -> None:
    if not solicitud.abierta:
        msg = f"La solicitud está {solicitud.estado}."
        raise OperacionNoPermitidaError(msg)


def cancelar(solicitud: Solicitud) -> Solicitud:
    with transaction.atomic():
        solicitud = Solicitud.objects.select_for_update().get(pk=solicitud.pk)
        _exigir_abierta(solicitud)
        _terminar(solicitud, Solicitud.Estado.CANCELADA)
    return solicitud


def reenviar(firmante: Firmante) -> str:
    """A new link for a pending signer, sent by email; the old one stops working."""
    with transaction.atomic():
        firmante = (
            Firmante.objects.select_for_update()
            .select_related("solicitud")
            .get(pk=firmante.pk)
        )
        _exigir_abierta(firmante.solicitud)
        if firmante.estado != Firmante.Estado.PENDIENTE:
            msg = "Este firmante ya no tiene una firma pendiente."
            raise OperacionNoPermitidaError(msg)
        enlace = url_firma(firmante.nuevo_token())
        firmante.intentos_identidad = 0
        firmante.save(update_fields=["hash_token", "intentos_identidad"])
        if es_su_turno(firmante):
            transaction.on_commit(lambda: _invitar(firmante, enlace))
    return enlace


def expirar_vencidas(ahora: datetime | None = None) -> int:
    ahora = ahora or timezone.now()
    vencidas = 0
    for pk in Solicitud.objects.filter(
        estado__in=Solicitud.ABIERTAS,
        expira_en__lte=ahora,
    ).values_list("pk", flat=True):
        with transaction.atomic():
            solicitud = Solicitud.objects.select_for_update().get(pk=pk)
            if solicitud.abierta:
                _terminar(solicitud, Solicitud.Estado.EXPIRADA)
                webhooks.encolar(solicitud, webhooks.SOLICITUD_EXPIRADA)
                vencidas += 1
    return vencidas


def _terminar(solicitud: Solicitud, estado: str) -> None:
    """Close a request that did not complete; unused certificates are revoked."""
    ahora = timezone.now()
    solicitud.estado = estado
    solicitud.terminada_en = ahora
    solicitud.save(update_fields=["estado", "terminada_en"])
    Certificado.objects.filter(
        firmante__solicitud=solicitud,
        revocado_en__isnull=True,
        clave_cifrada__isnull=False,
    ).update(revocado_en=ahora, clave_cifrada=None)


# -- One signer's steps --------------------------------------------------------


def firmante_por_token(token: str) -> Firmante | None:
    return (
        Firmante.objects.select_related("solicitud")
        .filter(hash_token=resumen(token))
        .first()
    )


def es_su_turno(firmante: Firmante) -> bool:
    return (
        not firmante.solicitud.firmantes.filter(
            orden__lt=firmante.orden,
        )
        .exclude(estado=Firmante.Estado.FIRMADO)
        .exists()
    )


def _exigir_turno(firmante: Firmante) -> None:
    _exigir_abierta(firmante.solicitud)
    if firmante.estado != Firmante.Estado.PENDIENTE:
        msg = "Ya respondiste esta solicitud."
        raise OperacionNoPermitidaError(msg)
    if not es_su_turno(firmante):
        msg = "Todavía no es tu turno: firma primero quien te antecede."
        raise OperacionNoPermitidaError(msg)


def verificar_identidad(firmante: Firmante, datos: dict[str, str]) -> bool:
    """Check identity; on success, issue the signer's single-use certificate."""
    with transaction.atomic():
        firmante = (
            Firmante.objects.select_for_update()
            .select_related("solicitud")
            .get(pk=firmante.pk)
        )
        _exigir_turno(firmante)
        if firmante.identidad_verificada_en:
            return True
        if firmante.bloqueado:
            msg = "Superaste los intentos de verificación. Pide un nuevo enlace."
            raise OperacionNoPermitidaError(msg)
        if not verificador().verificar(firmante, datos):
            firmante.intentos_identidad += 1
            firmante.save(update_fields=["intentos_identidad"])
            return False
        pki = pki_mod.cargar()
        cert, clave = pki_mod.emitir_firmante(pki, firmante.nombre, firmante.rut)
        Certificado.objects.update_or_create(
            firmante=firmante,
            defaults={
                "numero_serie": str(cert.serial_number),
                "pem": cert.public_bytes(serialization.Encoding.PEM).decode(),
                "clave_cifrada": pki_mod.cifrar_clave(clave),
                "revocado_en": None,
            },
        )
        firmante.identidad_verificada_en = timezone.now()
        firmante.save(update_fields=["identidad_verificada_en"])
    return True


def enviar_codigo(firmante: Firmante) -> None:
    """Email a fresh one-time code; earlier codes stop working."""
    with transaction.atomic():
        firmante = (
            Firmante.objects.select_for_update()
            .select_related("solicitud")
            .get(pk=firmante.pk)
        )
        _exigir_turno(firmante)
        if not firmante.identidad_verificada_en:
            msg = "Primero verifica tu identidad."
            raise OperacionNoPermitidaError(msg)
        ahora = timezone.now()
        firmante.codigos.filter(usado_en__isnull=True).update(usado_en=ahora)
        codigo = f"{secrets.randbelow(1_000_000):06d}"
        CodigoOtp.objects.create(
            firmante=firmante,
            hash_codigo=resumen(f"{firmante.pk}:{codigo}"),
            expira_en=ahora + timedelta(minutes=settings.OTP_MINUTOS),
        )
        transaction.on_commit(
            lambda: send_mail(
                f"Tu código de firma: {codigo}",
                (
                    f"Tu código para firmar «{firmante.solicitud.nombre_documento}» "
                    f"es {codigo}.\nVence en {settings.OTP_MINUTOS} minutos. "
                    "No lo compartas.\n"
                ),
                None,
                [firmante.email],
            ),
        )


def _consumir_codigo(firmante: Firmante, codigo: str) -> str | None:
    """Use the signer's current code. Returns why it was refused, if it was.

    Runs in its own transaction, so a wrong attempt is counted even though
    the signature that asked for it does not go ahead.
    """
    with transaction.atomic():
        otp = firmante.codigos.select_for_update().filter(usado_en__isnull=True).first()
        if otp is None or otp.expira_en <= timezone.now():
            return "El código venció. Pide uno nuevo."
        if otp.intentos >= settings.OTP_INTENTOS:
            return "Superaste los intentos del código. Pide uno nuevo."
        if not secrets.compare_digest(
            otp.hash_codigo,
            resumen(f"{firmante.pk}:{codigo.strip()}"),
        ):
            otp.intentos += 1
            otp.save(update_fields=["intentos"])
            restantes = settings.OTP_INTENTOS - otp.intentos
            return f"Código incorrecto. Te quedan {restantes} intentos."
        otp.usado_en = timezone.now()
        otp.save(update_fields=["usado_en"])
    return None


def revocados() -> list[tuple[int, datetime]]:
    """Serial number and date of every revoked signer certificate."""
    return [
        (int(serie), fecha)
        for serie, fecha in Certificado.objects.filter(
            revocado_en__isnull=False,
        ).values_list(
            "numero_serie",
            "revocado_en",
        )
    ]


def revocacion(pki: pki_mod.Pki, cert: x509.Certificate) -> tuple[list, list]:
    """The CRLs and the OCSP response a signature embeds (for B-LT)."""
    crls = [
        pki_mod.asn1_crl_de(pki_mod.lista_revocacion(pki.raiz, pki.clave_raiz)),
        pki_mod.asn1_crl_de(
            pki_mod.lista_revocacion(pki.emisora, pki.clave_emisora, revocados()),
        ),
    ]
    ocsps = [pki_mod.asn1_ocsp_de(pki_mod.respuesta_ocsp(pki, cert, None))]
    return crls, ocsps


def firmar(firmante: Firmante, codigo: str, *, consiente: bool) -> Solicitud:
    """Sign with the signer's own certificate, once the code checks out.

    The private key is decrypted only here and deleted right after: the
    certificate is single-use.
    """
    if not consiente:
        msg = "Debes aceptar firmar el documento."
        raise OperacionNoPermitidaError(msg)
    firmante = Firmante.objects.select_related("solicitud").get(pk=firmante.pk)
    _exigir_turno(firmante)
    if not firmante.identidad_verificada_en:
        msg = "Primero verifica tu identidad."
        raise OperacionNoPermitidaError(msg)
    if rechazo := _consumir_codigo(firmante, codigo):
        raise OperacionNoPermitidaError(rechazo)

    with transaction.atomic():
        solicitud = Solicitud.objects.select_for_update().get(pk=firmante.solicitud_id)
        firmante = (
            Firmante.objects.select_for_update()
            .select_related("solicitud", "certificado")
            .get(pk=firmante.pk)
        )
        _exigir_turno(firmante)

        certificado = firmante.certificado
        if certificado.clave_cifrada is None or certificado.revocado_en:
            msg = "Tu certificado ya no es válido. Pide un nuevo enlace."
            raise OperacionNoPermitidaError(msg)
        pki = pki_mod.cargar()
        cert = x509.load_pem_x509_certificate(certificado.pem.encode())
        crls, ocsps = revocacion(pki, cert)
        total = solicitud.firmantes.count()
        firmante.codigo_verificacion = (
            f"PRU-{secrets.token_hex(3).upper()}-{secrets.token_hex(3).upper()}"
        )
        firmado = firma_pdf.firmar(
            bytes(solicitud.documento_actual),
            firma_pdf.Firma(
                indice=firmante.orden,
                total=total,
                nombre=firmante.nombre,
                rut=firmante.rut,
                codigo_verificacion=firmante.codigo_verificacion,
                certificado=cert,
                clave=pki_mod.descifrar_clave(bytes(certificado.clave_cifrada)),
            ),
            pki,
            crls=crls,
            ocsps=ocsps,
        )
        certificado.clave_cifrada = None
        certificado.save(update_fields=["clave_cifrada"])

        ahora = timezone.now()
        firmante.estado = Firmante.Estado.FIRMADO
        firmante.firmado_en = ahora
        firmante.save(update_fields=["estado", "firmado_en", "codigo_verificacion"])
        solicitud.documento_actual = firmado
        campos = ["documento_actual"]
        siguiente = solicitud.firmantes.filter(orden=firmante.orden + 1).first()
        if siguiente is None:
            solicitud.estado = Solicitud.Estado.COMPLETADA
            solicitud.sha256_firmado = resumen(firmado)
            solicitud.terminada_en = ahora
            campos += ["estado", "sha256_firmado", "terminada_en"]
        solicitud.save(update_fields=campos)

        webhooks.encolar(solicitud, webhooks.FIRMANTE_FIRMO)
        if siguiente is None:
            webhooks.encolar(solicitud, webhooks.SOLICITUD_COMPLETADA)
        else:
            enlace = url_firma(siguiente.nuevo_token())
            siguiente.save(update_fields=["hash_token"])
            transaction.on_commit(lambda: _invitar(siguiente, enlace))
    return solicitud


def rechazar(firmante: Firmante, motivo: str) -> Solicitud:
    motivo = motivo.strip()
    if not motivo:
        msg = "Indica el motivo del rechazo."
        raise OperacionNoPermitidaError(msg)
    with transaction.atomic():
        solicitud = Solicitud.objects.select_for_update().get(pk=firmante.solicitud_id)
        firmante = (
            Firmante.objects.select_for_update()
            .select_related("solicitud")
            .get(pk=firmante.pk)
        )
        _exigir_turno(firmante)
        firmante.estado = Firmante.Estado.RECHAZADO
        firmante.rechazado_en = timezone.now()
        firmante.motivo_rechazo = motivo[:1000]
        firmante.save(update_fields=["estado", "rechazado_en", "motivo_rechazo"])
        _terminar(solicitud, Solicitud.Estado.RECHAZADA)
        webhooks.encolar(solicitud, webhooks.FIRMANTE_RECHAZO)
    return solicitud

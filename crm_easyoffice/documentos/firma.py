"""Advanced signature through the external provider (IN-01, RF-25, RF-39, RF-40).

For case types whose ``firma.nivel`` is ``avanzada``:

1. When the case starts waiting for a signature, ``enviar`` sends the current
   document and its signers, in order, to the provider (Celery).
2. The provider's webhooks (verified, deduplicated) and a periodic sync both
   end in ``aplicar_estado``, which reads the provider's current state and
   moves each signer, and the case, on. It is idempotent and tolerates events
   that arrive late or twice.
3. On completion the signed PDF is checked against the document sent (RF-39)
   and stored through ``guardar_firmado``, the same end state as the assisted
   upload: the case completes and its contract enters into force.

The provider itself is behind ``integrations.signature``. Locally it is the
test PSC, whose signatures have no legal validity.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from datetime import time
from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from crm_easyoffice.integrations.signature.base import SignatureError
from crm_easyoffice.integrations.signature.base import SignatureRequest
from crm_easyoffice.integrations.signature.base import SignatureStatus
from crm_easyoffice.integrations.signature.base import Signer
from crm_easyoffice.integrations.signature.base import SignerState
from crm_easyoffice.integrations.signature.registry import exigir_resultado_admitido
from crm_easyoffice.integrations.signature.registry import get_signature_provider
from crm_easyoffice.integrations.signature.registry import webhook_url
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.services import AVANZADA
from crm_easyoffice.tramites.services import FIRMA
from crm_easyoffice.tramites.services import PENDIENTE
from crm_easyoffice.tramites.services import FechaInicioVencidaError
from crm_easyoffice.tramites.services import TransicionInvalidaError
from crm_easyoffice.tramites.services import firma_no_completada
from crm_easyoffice.tramites.services import nivel_firma
from crm_easyoffice.tramites.services import situacion
from crm_easyoffice.tramites.services import verificar_para_firma

from .models import Documento
from .models import Firmante
from .models import SolicitudFirma
from .services import documento_vigente
from .services import guardar_firmado

if TYPE_CHECKING:
    from crm_easyoffice.integrations.signature.base import SignatureResult
    from crm_easyoffice.users.models import User

logger = logging.getLogger(__name__)

# How long the backoffice waits before it asks the provider again.
SINCRONIZAR_CADA = timedelta(seconds=10)

CANCELADA_POR_EJECUTIVO = "Firma cancelada por el ejecutivo."
EXPIRADA = "La solicitud de firma expiró sin todas las firmas."
CANCELADA_EN_PROVEEDOR = "La solicitud de firma fue cancelada en el proveedor."


class FirmaNoGestionableError(Exception):
    """The document has no request in a state that allows this action."""


def solicitud_actual(documento: Documento) -> SolicitudFirma | None:
    return documento.solicitudes_firma.order_by("-created_at", "-pk").first()


def _expiracion(tramite: Tramite) -> datetime:
    """Now plus the TTL, but never past the contract's start date.

    ASSUMPTION: pending validation with Easy Office. A contract is never
    backdated, so a link that outlived the start date would collect
    signatures for a document that can no longer enter into force.
    """
    limite = timezone.now() + timedelta(days=settings.SIGNATURE_REQUEST_TTL_DAYS)
    if tramite.contrato is not None:
        fin_del_dia = timezone.make_aware(
            datetime.combine(tramite.contrato.fecha_inicio, time.max),
        )
        limite = min(limite, fin_del_dia)
    return limite


def _correo(firmante: Firmante) -> str:
    """Where the provider sends the signer's link.

    ASSUMPTION: pending validation with Easy Office. The client's
    representative may have no email of their own on record; the contract's
    notice email (the form's) stands in for it.
    """
    if firmante.persona.email:
        return firmante.persona.email
    contrato = firmante.documento.tramite.contrato
    if firmante.rol == Firmante.Rol.CLIENTE_REPRESENTANTE and contrato is not None:
        return contrato.email_aviso
    return ""


def _signer(firmante: Firmante) -> Signer:
    persona = firmante.persona
    return Signer(
        full_name=persona.nombre_completo,
        email=_correo(firmante),
        rut=persona.rut,
        order=firmante.orden,
        role=firmante.rol,
        reference=str(firmante.pk),
    )


def _sin_correo(documento: Documento) -> list[str]:
    return [f.persona.nombre_completo for f in _firmantes(documento) if not _correo(f)]


def _firmantes(documento: Documento) -> list[Firmante]:
    return list(
        documento.firmantes.select_related("persona", "documento__tramite__contrato"),
    )


def _por_enviar(tramite: Tramite) -> Documento | None:
    """The document to send, if the case is waiting for an advanced signature."""
    if nivel_firma(tramite.tipo) != AVANZADA:
        return None
    documento = documento_vigente(tramite)
    if documento is None or documento.estado != Documento.Estado.GENERADO:
        return None
    try:
        verificar_para_firma(tramite)
    except TransicionInvalidaError, FechaInicioVencidaError:
        logger.info("%s is not waiting for a signature; nothing sent.", tramite)
        return None
    return documento


def _solicitud_nueva(documento: Documento, tramite: Tramite) -> SolicitudFirma | None:
    """The request to send: an open one not sent yet (a retry), or a new one.

    None when the document already has a request at the provider.
    """
    solicitud = solicitud_actual(documento)
    if solicitud is not None and solicitud.abierta:
        return None if solicitud.id_externo else solicitud
    try:
        with transaction.atomic():
            return SolicitudFirma.objects.create(
                documento=documento,
                proveedor=settings.SIGNATURE_PROVIDER,
                expira_en=_expiracion(tramite),
            )
    except IntegrityError:
        return None


def enviar(tramite_id: int) -> SolicitudFirma | None:
    """Send the case's current document to the provider, once.

    Returns the request, or None when there is nothing to send: the type
    signs assisted, the case is not waiting for a signature, its start date
    has passed (the case then asks for a new one), or it was already sent.

    Raises:
        SignatureError: The provider failed; ``transient`` says whether a
            retry may help. A permanent failure is also recorded on the
            request for the executive.
    """
    tramite = Tramite.objects.select_related("tipo", "contrato").get(pk=tramite_id)
    documento = _por_enviar(tramite)
    solicitud = documento and _solicitud_nueva(documento, tramite)
    if solicitud is None:
        return None
    if faltan := _sin_correo(documento):
        _fallar(solicitud, f"Falta el correo de: {', '.join(faltan)}.")
        return solicitud

    with documento.archivo_pdf.open("rb") as archivo:
        contenido = archivo.read()
    peticion = SignatureRequest(
        document_id=str(documento.pk),
        document_name=f"Contrato {tramite.contrato.folio}",
        content=contenido,
        signers=[_signer(f) for f in _firmantes(documento)],
        callback_url=webhook_url(),
        metadata={"folio": tramite.contrato.folio},
        expires_at=solicitud.expira_en.isoformat() if solicitud.expira_en else None,
    )
    try:
        proveedor = get_signature_provider()
        resultado = proveedor.create_request(peticion)
        exigir_resultado_admitido(resultado)
    except SignatureError as error:
        if not error.transient:
            _fallar(solicitud, str(error))
        raise

    with transaction.atomic():
        solicitud.id_externo = resultado.external_id
        solicitud.estado = SolicitudFirma.Estado.ENVIADA
        solicitud.ambiente_pruebas = resultado.test_environment
        solicitud.enviada_en = timezone.now()
        solicitud.detalle_error = ""
        solicitud.save()
        for estado in resultado.signers:
            Firmante.objects.filter(documento=documento, pk=estado.reference).update(
                id_externo=estado.external_id,
            )
    # TODO(RF-15): record the request sent in the audit log (HU-30).
    return solicitud


def _fallar(solicitud: SolicitudFirma, detalle: str) -> None:
    logger.warning("Signature request %s failed: %s", solicitud.pk, detalle)
    SolicitudFirma.objects.filter(pk=solicitud.pk).update(
        estado=SolicitudFirma.Estado.ERROR,
        detalle_error=detalle[:2000],
        terminada_en=timezone.now(),
    )


def fallo_definitivo(tramite_id: int, detalle: str) -> None:
    """The task gave up retrying: record it for the executive."""
    tramite = Tramite.objects.get(pk=tramite_id)
    documento = documento_vigente(tramite)
    solicitud = documento and solicitud_actual(documento)
    if solicitud is not None and solicitud.abierta:
        _fallar(solicitud, detalle)


def _fecha(valor: str | None) -> datetime | None:
    return parse_datetime(valor) if valor else None


def _marcar_firmantes(documento: Documento, resultado: SignatureResult) -> None:
    firmantes = {str(f.pk): f for f in documento.firmantes.all()}
    for estado in resultado.signers:
        firmante = firmantes.get(estado.reference)
        if firmante is None or firmante.estado != Firmante.Estado.PENDIENTE:
            continue
        if estado.status is SignerState.SIGNED:
            firmante.estado = Firmante.Estado.FIRMADO
            firmante.firmado_en = _fecha(estado.signed_at) or timezone.now()
        elif estado.status is SignerState.DECLINED:
            firmante.estado = Firmante.Estado.RECHAZADO
            firmante.rechazado_en = _fecha(estado.declined_at) or timezone.now()
            firmante.motivo_rechazo = estado.declined_reason[:2000]
        else:
            continue
        firmante.id_externo = firmante.id_externo or estado.external_id
        firmante.save(
            update_fields=[
                "estado",
                "firmado_en",
                "rechazado_en",
                "motivo_rechazo",
                "id_externo",
            ],
        )


def problemas_de_integridad(
    documento: Documento,
    resultado: SignatureResult,
    firmado: bytes,
) -> list[str]:
    """What does not match between the file sent and the file returned (RF-39).

    A PAdES signature is an incremental update, so the document sent must
    be an exact prefix of the signed file: nothing it said was changed.
    """
    with documento.archivo_pdf.open("rb") as archivo:
        original = archivo.read()
    problemas = []
    if resultado.original_sha256 != documento.sha256_pdf:
        problemas.append(
            "El proveedor no informa el mismo documento que se envió "
            f"(SHA-256 {resultado.original_sha256!r}).",
        )
    if not firmado.startswith(b"%PDF-"):
        problemas.append("El archivo firmado no es un PDF.")
    if not firmado.startswith(original):
        problemas.append("El archivo firmado no conserva el documento enviado.")
    calculado = hashlib.sha256(firmado).hexdigest()
    if resultado.signed_hash and resultado.signed_hash != calculado:
        problemas.append("El SHA-256 del archivo descargado no es el informado.")
    return problemas


def aplicar_estado(solicitud: SolicitudFirma, resultado: SignatureResult) -> None:
    """Bring a request, its signers and its case to the provider's state.

    Idempotent: a terminal request is left alone, a signer already marked
    keeps its first time, and an older state never undoes a newer one.
    """
    with transaction.atomic():
        solicitud = (
            SolicitudFirma.objects.select_for_update()
            .select_related("documento__tramite")
            .get(pk=solicitud.pk)
        )
        solicitud.sincronizada_en = timezone.now()
        solicitud.save(update_fields=["sincronizada_en", "updated_at"])
        if not solicitud.abierta or resultado.external_id != solicitud.id_externo:
            return
        documento = solicitud.documento
        _marcar_firmantes(documento, resultado)

        if resultado.status is SignatureStatus.SIGNED:
            _completar(solicitud, resultado)
        elif resultado.status is SignatureStatus.REJECTED:
            rechazo = documento.firmantes.filter(
                estado=Firmante.Estado.RECHAZADO,
            ).first()
            if rechazo is not None:
                detalle = (
                    f"{rechazo.persona.nombre_completo} rechazó la firma: "
                    f"{rechazo.motivo_rechazo}"
                )
                _cerrar(solicitud, SolicitudFirma.Estado.RECHAZADA, detalle)
            else:
                _cerrar(
                    solicitud,
                    SolicitudFirma.Estado.CANCELADA,
                    CANCELADA_EN_PROVEEDOR,
                )
        elif resultado.status is SignatureStatus.EXPIRED:
            _cerrar(solicitud, SolicitudFirma.Estado.EXPIRADA, EXPIRADA)


def _cerrar(
    solicitud: SolicitudFirma,
    estado: str,
    detalle: str,
    usuario: User | None = None,
) -> None:
    solicitud.estado = estado
    solicitud.detalle_error = detalle
    solicitud.terminada_en = timezone.now()
    solicitud.save()
    tramite = solicitud.documento.tramite
    if situacion(tramite) == (PENDIENTE, FIRMA):
        firma_no_completada(tramite, detalle, usuario)


def _completar(solicitud: SolicitudFirma, resultado: SignatureResult) -> None:
    documento = solicitud.documento
    if documento != documento_vigente(documento.tramite):
        _fallar(solicitud, "El documento fue reemplazado mientras se firmaba.")
        return
    firmado = get_signature_provider().download_signed(solicitud.id_externo)
    if problemas := problemas_de_integridad(documento, resultado, firmado):
        _fallar(solicitud, " ".join(problemas))
        return
    try:
        verificar_para_firma(documento.tramite)
    except FechaInicioVencidaError:
        # ASSUMPTION: pending validation with Easy Office. As with the upload,
        # a contract is never backdated: the case already asks for a new date.
        _fallar(solicitud, "Se firmó después de la fecha de inicio; no se registró.")
        return
    guardar_firmado(documento, firmado)
    solicitud.estado = SolicitudFirma.Estado.COMPLETADA
    solicitud.terminada_en = timezone.now()
    solicitud.save()
    # TODO(RF-15): record the signed PDF stored in the audit log (HU-30).


def sincronizar(solicitud_id: int) -> None:
    """Ask the provider for the request's state: the fallback when webhooks are lost."""
    solicitud = SolicitudFirma.objects.get(pk=solicitud_id)
    if not solicitud.abierta or not solicitud.id_externo:
        return
    aplicar_estado(solicitud, get_signature_provider().get_status(solicitud.id_externo))


def abiertas() -> list[int]:
    return list(
        SolicitudFirma.objects.filter(
            estado=SolicitudFirma.Estado.ENVIADA,
        ).values_list("pk", flat=True),
    )


def por_sincronizar(documento: Documento) -> SolicitudFirma | None:
    """The document's open request, if it has not been checked recently."""
    solicitud = solicitud_actual(documento)
    if solicitud is None or solicitud.estado != SolicitudFirma.Estado.ENVIADA:
        return None
    ultima = solicitud.sincronizada_en or solicitud.enviada_en
    if ultima and timezone.now() - ultima < SINCRONIZAR_CADA:
        return None
    return solicitud


def _solicitud_enviada(documento: Documento) -> SolicitudFirma:
    solicitud = solicitud_actual(documento)
    if solicitud is None or solicitud.estado != SolicitudFirma.Estado.ENVIADA:
        msg = "This document has no signature request in progress."
        raise FirmaNoGestionableError(msg)
    return solicitud


def preparar_reenvio(documento: Documento, firmante_id: int) -> tuple[int, str]:
    """Check a pending signer can get a new link. Returns what the task needs."""
    solicitud = _solicitud_enviada(documento)
    firmante = documento.firmantes.filter(pk=firmante_id).first()
    if (
        firmante is None
        or firmante.estado != Firmante.Estado.PENDIENTE
        or not firmante.id_externo
    ):
        msg = "This signer has no pending signature."
        raise FirmaNoGestionableError(msg)
    return solicitud.pk, firmante.id_externo


def reenviar(solicitud_id: int, firmante_externo: str) -> None:
    solicitud = SolicitudFirma.objects.get(pk=solicitud_id)
    get_signature_provider().resend(solicitud.id_externo, firmante_externo)


def preparar_cancelacion(documento: Documento) -> int:
    return _solicitud_enviada(documento).pk


def cancelar(solicitud_id: int, usuario_id: int | None = None) -> None:
    """Cancel at the provider; the case goes back to the executive.

    ASSUMPTION: pending validation with Easy Office. A cancelled signature
    is handled like a declined one: the executive corrects and regenerates.
    """
    solicitud = SolicitudFirma.objects.get(pk=solicitud_id)
    if not solicitud.abierta:
        return
    if solicitud.id_externo:
        get_signature_provider().cancel(solicitud.id_externo)
    usuario = get_user_model().objects.filter(pk=usuario_id).first()
    with transaction.atomic():
        solicitud = SolicitudFirma.objects.select_for_update().get(pk=solicitud.pk)
        if solicitud.abierta:
            _cerrar(
                solicitud,
                SolicitudFirma.Estado.CANCELADA,
                CANCELADA_POR_EJECUTIVO,
                usuario,
            )


def cancelar_reemplazadas(tramite_id: int) -> list[int]:
    """Cancel requests left open on documents a regeneration replaced."""
    abiertas_reemplazadas = SolicitudFirma.objects.filter(
        documento__tramite_id=tramite_id,
        documento__estado=Documento.Estado.REEMPLAZADO,
        estado__in=SolicitudFirma.ABIERTAS,
    )
    canceladas = []
    for solicitud in abiertas_reemplazadas:
        if solicitud.id_externo:
            try:
                get_signature_provider().cancel(solicitud.id_externo)
            except SignatureError:
                logger.warning("Could not cancel signature request %s.", solicitud.pk)
        SolicitudFirma.objects.filter(pk=solicitud.pk).update(
            estado=SolicitudFirma.Estado.CANCELADA,
            detalle_error="El documento fue reemplazado por una nueva versión.",
            terminada_en=timezone.now(),
        )
        canceladas.append(solicitud.pk)
    return canceladas


def preparar_reintento(documento: Documento) -> int:
    """A request that failed may be sent again while the case waits for it."""
    solicitud = solicitud_actual(documento)
    tramite = documento.tramite
    if (
        solicitud is None
        or solicitud.estado != SolicitudFirma.Estado.ERROR
        or documento != documento_vigente(tramite)
        or situacion(tramite) != (PENDIENTE, FIRMA)
    ):
        msg = "There is no failed signature request to retry."
        raise FirmaNoGestionableError(msg)
    return tramite.pk

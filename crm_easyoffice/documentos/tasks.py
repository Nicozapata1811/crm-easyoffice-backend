from __future__ import annotations

import logging

from celery import shared_task

from crm_easyoffice.integrations.signature.base import SignatureError
from crm_easyoffice.tramites.models import Tramite

from . import firma
from .models import EventoFirma
from .services import generar

logger = logging.getLogger(__name__)

MAX_REINTENTOS = 3


@shared_task
def generar_documento(tramite_id: int) -> None:
    """Generate a case's document; its state says what happened."""
    tramite = Tramite.objects.filter(pk=tramite_id).first()
    if tramite is not None:
        generar(tramite)
        firma.cancelar_reemplazadas(tramite.pk)


@shared_task(bind=True, max_retries=MAX_REINTENTOS, default_retry_delay=5)
def enviar_a_firma(self, tramite_id: int) -> None:
    """Send the case's document to the advanced-signature provider."""
    try:
        firma.enviar(tramite_id)
    except SignatureError as exc:
        if exc.transient and self.request.retries < MAX_REINTENTOS:
            raise self.retry(exc=exc) from exc
        logger.warning("Case %s could not be sent to signature: %s", tramite_id, exc)
        firma.fallo_definitivo(tramite_id, str(exc))


@shared_task(bind=True, max_retries=MAX_REINTENTOS, default_retry_delay=5)
def procesar_evento_firma(self, evento_id: int) -> None:
    """Apply a verified webhook by reading the request's current state.

    Reading the state, rather than trusting the event's snapshot, is what
    makes late or repeated events harmless.
    """
    evento = EventoFirma.objects.select_related("solicitud").get(pk=evento_id)
    if evento.solicitud_id is None:
        return
    try:
        firma.sincronizar(evento.solicitud_id)
    except SignatureError as exc:
        if exc.transient and self.request.retries < MAX_REINTENTOS:
            raise self.retry(exc=exc) from exc
        logger.warning("Signature event %s could not be applied: %s", evento_id, exc)


@shared_task
def sincronizar_solicitud_firma(solicitud_id: int) -> None:
    """Ask the provider for a request's state, as a fallback to webhooks."""
    try:
        firma.sincronizar(solicitud_id)
    except SignatureError as exc:
        logger.warning(
            "Signature request %s could not be checked: %s",
            solicitud_id,
            exc,
        )


@shared_task
def sincronizar_solicitudes_abiertas() -> int:
    """Periodic: every request in progress, in case a webhook was lost."""
    pendientes = firma.abiertas()
    for solicitud_id in pendientes:
        sincronizar_solicitud_firma.delay(solicitud_id)
    return len(pendientes)


@shared_task
def reenviar_enlace_firma(solicitud_id: int, firmante_externo: str) -> None:
    try:
        firma.reenviar(solicitud_id, firmante_externo)
    except SignatureError as exc:
        logger.warning("Signing link for %s not resent: %s", solicitud_id, exc)


@shared_task
def cancelar_solicitud_firma(solicitud_id: int, usuario_id: int | None = None) -> None:
    try:
        firma.cancelar(solicitud_id, usuario_id)
    except SignatureError as exc:
        logger.warning("Signature request %s not cancelled: %s", solicitud_id, exc)

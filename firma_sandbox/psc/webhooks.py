"""Signed webhooks with retries: an outbox the ``despachar`` command drains.

Each delivery carries three headers:

- ``X-PSC-Evento``: the event id, the same on every retry, so the receiver
  can deduplicate;
- ``X-PSC-Timestamp``: Unix seconds at the moment of this attempt;
- ``X-PSC-Firma``: ``v1=`` and the hex HMAC-SHA256, with the client's
  webhook secret, of ``"{timestamp}.{body}"``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import timedelta
from typing import TYPE_CHECKING

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .estado import estado_solicitud
from .models import EntregaWebhook

if TYPE_CHECKING:
    from datetime import datetime

    from .models import Solicitud

logger = logging.getLogger(__name__)

FIRMANTE_FIRMO = "firmante.firmo"
FIRMANTE_RECHAZO = "firmante.rechazo"
SOLICITUD_COMPLETADA = "solicitud.completada"
SOLICITUD_EXPIRADA = "solicitud.expirada"
TIPOS = (FIRMANTE_FIRMO, FIRMANTE_RECHAZO, SOLICITUD_COMPLETADA, SOLICITUD_EXPIRADA)


def firma(secreto: str, timestamp: int, cuerpo: bytes) -> str:
    mensaje = f"{timestamp}.".encode() + cuerpo
    return "v1=" + hmac.new(secreto.encode(), mensaje, hashlib.sha256).hexdigest()


def encolar(solicitud: Solicitud, tipo: str) -> EntregaWebhook | None:
    """Queue an event for the client, with the request's state as of now."""
    if not solicitud.url_notificacion:
        return None
    entrega = EntregaWebhook(
        solicitud=solicitud,
        tipo=tipo,
        url=solicitud.url_notificacion,
        proximo_intento=timezone.now(),
    )
    entrega.cuerpo = json.dumps(
        {
            "id_evento": str(entrega.id_evento),
            "tipo": tipo,
            "creado_en": timezone.now().isoformat(),
            "solicitud": estado_solicitud(solicitud),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    entrega.save()
    return entrega


def _espera(intentos: int) -> timedelta:
    escalones = settings.WEBHOOK_BACKOFF_SEGUNDOS
    segundos = escalones[min(intentos, len(escalones)) - 1]
    return timedelta(seconds=segundos * settings.WEBHOOK_BACKOFF_FACTOR)


def entregar(entrega: EntregaWebhook, cliente: httpx.Client) -> bool:
    """One attempt. A 2xx answer delivers it; anything else is retried later."""
    cuerpo = entrega.cuerpo.encode()
    marca = int(timezone.now().timestamp())
    encabezados = {
        "Content-Type": "application/json",
        "X-PSC-Evento": str(entrega.id_evento),
        "X-PSC-Timestamp": str(marca),
        "X-PSC-Firma": firma(entrega.solicitud.cliente.secreto_webhook, marca, cuerpo),
    }
    entrega.intentos += 1
    try:
        respuesta = cliente.post(entrega.url, content=cuerpo, headers=encabezados)
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}: {exc}"
    else:
        if respuesta.is_success:
            entrega.estado = EntregaWebhook.Estado.ENTREGADA
            entrega.entregada_en = timezone.now()
            entrega.ultimo_error = ""
            entrega.save()
            return True
        error = f"HTTP {respuesta.status_code}"

    entrega.ultimo_error = error[:500]
    if entrega.intentos >= settings.WEBHOOK_MAX_INTENTOS:
        entrega.estado = EntregaWebhook.Estado.FALLIDA
        logger.warning(
            "Webhook %s gave up after %s attempts: %s",
            entrega,
            entrega.intentos,
            error,
        )
    else:
        entrega.proximo_intento = timezone.now() + _espera(entrega.intentos)
    entrega.save()
    return False


def entregar_pendientes(
    ahora: datetime | None = None,
    cliente: httpx.Client | None = None,
) -> int:
    """Attempt every delivery that is due, oldest first. Returns how many arrived."""
    ahora = ahora or timezone.now()
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=settings.WEBHOOK_TIMEOUT_SEGUNDOS)
    entregadas = 0
    try:
        pendientes = EntregaWebhook.objects.filter(
            estado=EntregaWebhook.Estado.PENDIENTE,
            proximo_intento__lte=ahora,
        ).select_related("solicitud__cliente")
        for entrega in pendientes:
            with transaction.atomic():
                entregadas += entregar(entrega, cliente)
    finally:
        if propio:
            cliente.close()
    return entregadas

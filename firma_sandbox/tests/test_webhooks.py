import json
from datetime import timedelta

import httpx
import pytest
from django.utils import timezone

from psc import webhooks
from psc.models import EntregaWebhook

from .conftest import SECRETO
from .conftest import firmar_todo

pytestmark = pytest.mark.django_db


def _receptor(respuestas: list[int]):
    recibidas: list[httpx.Request] = []

    def manejar(request: httpx.Request) -> httpx.Response:
        recibidas.append(request)
        return httpx.Response(respuestas.pop(0) if respuestas else 200)

    return httpx.Client(transport=httpx.MockTransport(manejar)), recibidas


def test_deliveries_are_signed_with_hmac_over_timestamp_and_body(solicitud, mailoutbox):
    firmar_todo(solicitud, mailoutbox, hasta=1)
    cliente, recibidas = _receptor([200])

    assert webhooks.entregar_pendientes(cliente=cliente) == 1

    [peticion] = recibidas
    marca = int(peticion.headers["X-PSC-Timestamp"])
    assert peticion.headers["X-PSC-Firma"] == webhooks.firma(
        SECRETO,
        marca,
        peticion.content,
    )
    cuerpo = json.loads(peticion.content)
    assert cuerpo["tipo"] == "firmante.firmo"
    assert cuerpo["id_evento"] == peticion.headers["X-PSC-Evento"]
    assert cuerpo["solicitud"]["firmantes"][0]["estado"] == "firmado"
    assert EntregaWebhook.objects.get().estado == EntregaWebhook.Estado.ENTREGADA


def test_failed_deliveries_are_retried_with_backoff_and_the_same_event_id(
    solicitud,
    mailoutbox,
    settings,
):
    firmar_todo(solicitud, mailoutbox, hasta=1)
    cliente, recibidas = _receptor([500, 503, 200])

    assert webhooks.entregar_pendientes(cliente=cliente) == 0
    entrega = EntregaWebhook.objects.get()
    espera = entrega.proximo_intento - timezone.now()
    assert (
        timedelta(seconds=settings.WEBHOOK_BACKOFF_SEGUNDOS[0] - 5)
        < espera
        <= timedelta(
            seconds=settings.WEBHOOK_BACKOFF_SEGUNDOS[0],
        )
    )
    assert webhooks.entregar_pendientes(cliente=cliente) == 0, "not due yet"

    despues = timezone.now() + timedelta(hours=1)
    webhooks.entregar_pendientes(ahora=despues, cliente=cliente)
    entrega.refresh_from_db()
    assert entrega.intentos == 2  # noqa: PLR2004
    assert entrega.proximo_intento - timezone.now() > timedelta(
        seconds=settings.WEBHOOK_BACKOFF_SEGUNDOS[1] - 5,
    )

    assert (
        webhooks.entregar_pendientes(
            ahora=despues + timedelta(hours=1),
            cliente=cliente,
        )
        == 1
    )
    assert len({p.headers["X-PSC-Evento"] for p in recibidas}) == 1
    assert len(recibidas) == 3  # noqa: PLR2004 - two failures, then the delivery


def test_deliveries_give_up_after_the_last_attempt(solicitud, mailoutbox, settings):
    firmar_todo(solicitud, mailoutbox, hasta=1)
    cliente, _ = _receptor([500] * settings.WEBHOOK_MAX_INTENTOS)
    momento = timezone.now()
    for _ in range(settings.WEBHOOK_MAX_INTENTOS):
        momento += timedelta(days=1)
        webhooks.entregar_pendientes(ahora=momento, cliente=cliente)

    entrega = EntregaWebhook.objects.get()
    assert entrega.estado == EntregaWebhook.Estado.FALLIDA
    assert entrega.ultimo_error == "HTTP 500"


def test_connection_errors_are_retried(solicitud, mailoutbox):
    firmar_todo(solicitud, mailoutbox, hasta=1)

    def caido(request: httpx.Request) -> httpx.Response:
        msg = "sin red"
        raise httpx.ConnectError(msg, request=request)

    webhooks.entregar_pendientes(
        cliente=httpx.Client(transport=httpx.MockTransport(caido)),
    )

    entrega = EntregaWebhook.objects.get()
    assert entrega.estado == EntregaWebhook.Estado.PENDIENTE
    assert "ConnectError" in entrega.ultimo_error

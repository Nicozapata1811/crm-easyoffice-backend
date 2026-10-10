from __future__ import annotations

import logging
from dataclasses import replace

from celery import shared_task
from django.db import IntegrityError
from django.db import transaction
from django.utils import timezone

from crm_easyoffice.integrations.payment.base import Payer
from crm_easyoffice.integrations.payment.base import PaymentError
from crm_easyoffice.integrations.payment.base import PaymentItem
from crm_easyoffice.integrations.payment.base import PaymentRequest
from crm_easyoffice.integrations.payment.registry import get_payment_provider
from crm_easyoffice.integrations.payment.registry import webhook_base_url

from .models import EventoPago
from .models import OrdenPago
from .services import aplicar_resultado
from .services import orden_de_resultado

logger = logging.getLogger(__name__)

MAX_REINTENTOS = 3


def construir_solicitud(orden: OrdenPago, webhooks: str) -> PaymentRequest:
    venta = orden.venta
    cliente = venta.cliente
    parte = cliente.parte
    cuenta = cliente.cuentas.select_related("user").first()
    email = parte.email or (cuenta.user.email if cuenta else "")
    if cliente.es_empresa:
        # ASSUMPTION: pending validation with Easy Office. Klap requires a last
        # name; a company sends its trade name, or its legal name again.
        payer = Payer(
            email=email,
            rut=parte.rut,
            first_name=parte.razon_social,
            last_name=parte.nombre_fantasia or parte.razon_social,
        )
    else:
        payer = Payer(
            email=email,
            rut=parte.rut,
            first_name=parte.nombres,
            last_name=parte.apellido_paterno,
        )
    base = webhooks.rstrip("/")
    # Flow returns the browser with a POST, so the browser comes back through
    # the backend, which redirects it to the portal.
    retorno = f"{base}/api/pagos/retorno/{orden.pk}/" if base else ""
    return PaymentRequest(
        reference=str(orden.referencia),
        amount=orden.monto,
        description=f"Easy Office {venta.folio}",
        return_url=retorno or None,
        cancel_url=f"{retorno}?cancelado=1" if retorno else None,
        notification_url=(
            f"{base}/api/pagos/webhooks/{orden.proveedor}/" if base else None
        ),
        payer=payer,
        items=tuple(
            PaymentItem(
                code=item.servicio.codigo,
                name=item.nombre,
                unit_price=item.precio_unitario,
                quantity=item.cantidad,
            )
            for item in venta.items.select_related("servicio")
        ),
    )


@shared_task(bind=True, max_retries=MAX_REINTENTOS, default_retry_delay=2)
def crear_orden_en_proveedor(self, orden_id: int) -> None:
    orden = OrdenPago.objects.select_related(
        "venta__cliente__persona",
        "venta__cliente__empresa",
    ).get(pk=orden_id)
    if orden.estado != OrdenPago.Estado.CREANDO:
        return

    try:
        solicitud = construir_solicitud(orden, webhook_base_url())
        resultado = get_payment_provider(orden.proveedor).create_payment(solicitud)
    except PaymentError as exc:
        if exc.transient and self.request.retries < MAX_REINTENTOS:
            raise self.retry(exc=exc) from exc
        logger.warning("Order %s could not be created: %s", orden.pk, exc)
        orden.estado = OrdenPago.Estado.ERROR
        orden.detalle_error = str(exc)
        orden.save(update_fields=["estado", "detalle_error", "updated_at"])
        return

    orden.id_externo = resultado.external_id
    orden.redirect_url = resultado.redirect_url or ""
    orden.save(update_fields=["id_externo", "redirect_url", "updated_at"])
    aplicar_resultado(orden.pk, resultado, origen="creacion")


@shared_task
def sincronizar_orden(orden_id: int) -> None:
    """Ask the provider for the order's state, as a fallback to webhooks."""
    orden = OrdenPago.objects.get(pk=orden_id)
    if not orden.id_externo or orden.estado not in OrdenPago.ABIERTAS:
        return
    OrdenPago.objects.filter(pk=orden.pk).update(sincronizada_en=timezone.now())
    try:
        resultado = get_payment_provider(orden.proveedor).get_status(orden.id_externo)
    except PaymentError as exc:
        logger.warning("Order %s could not be checked: %s", orden.pk, exc)
        return
    aplicar_resultado(orden.pk, resultado, origen="consulta")


@shared_task(bind=True, max_retries=MAX_REINTENTOS, default_retry_delay=2)
def procesar_notificacion(self, recibido: dict) -> None:
    """Verify and apply a notification whose provider must be asked about it.

    ``recibido`` holds the EventoPago fields the webhook view collected; the
    event is written here, once the outcome is known.
    """
    if EventoPago.objects.filter(clave_dedup=recibido["clave_dedup"]).exists():
        return
    proveedor = get_payment_provider(recibido["proveedor"])
    try:
        resultado = proveedor.parse_webhook(
            recibido["payload"],
            {},
            event=recibido["evento"],
        )
    except PaymentError as exc:
        if exc.transient and self.request.retries < MAX_REINTENTOS:
            raise self.retry(exc=exc) from exc
        logger.warning("Rejected %s notification: %s", recibido["proveedor"], exc)
        _registrar_evento(recibido, None, EventoPago.Resultado.FIRMA_INVALIDA)
        return

    orden = orden_de_resultado(resultado)
    if orden is None:
        _registrar_evento(recibido, None, EventoPago.Resultado.RECHAZADO)
        return
    if orden.id_externo and not resultado.external_id:
        resultado = replace(resultado, external_id=orden.id_externo)
    cambio = aplicar_resultado(
        orden.pk,
        resultado,
        origen=f"webhook:{recibido['evento']}",
    )
    _registrar_evento(
        recibido,
        orden,
        EventoPago.Resultado.PROCESADO if cambio else EventoPago.Resultado.IGNORADO,
    )


def _registrar_evento(recibido: dict, orden: OrdenPago | None, resultado: str) -> None:
    try:
        with transaction.atomic():
            EventoPago.objects.create(**recibido, orden=orden, resultado=resultado)
    except IntegrityError:
        logger.info("Notification %s already recorded.", recibido["clave_dedup"])

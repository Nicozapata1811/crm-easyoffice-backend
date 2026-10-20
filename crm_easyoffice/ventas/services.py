"""Sale and payment state changes, and the catalogue reads other apps need.

Every state change of a sale or a payment goes through here.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.db.models import Sum
from django.dispatch import Signal
from django.utils import timezone

from crm_easyoffice.integrations.payment.base import PaymentStatus
from crm_easyoffice.integrations.payment.registry import proveedores_habilitados

from .models import CicloPago
from .models import ItemVenta
from .models import OrdenPago
from .models import Pago
from .models import PlanServicio
from .models import Servicio
from .models import Venta

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date
    from decimal import Decimal

    from django.db.models import QuerySet

    from crm_easyoffice.clientes.models import Cliente
    from crm_easyoffice.integrations.payment.base import PaymentResult


logger = logging.getLogger(__name__)

# Sent once a sale is paid, after the transaction commits, with ``venta``.
# Other apps observe it; this app does not know who is listening.
venta_pagada = Signal()

# ASSUMPTION: pending validation with Easy Office. The advanced electronic
# signature charged on top of a plan that does not include it.
SERVICIO_FIRMA = "firma-electronica-avanzada"

Estado = OrdenPago.Estado

ESTADO_POR_RESULTADO = {
    PaymentStatus.PENDING: Estado.PENDIENTE,
    PaymentStatus.AUTHORIZED: Estado.PENDIENTE,
    PaymentStatus.PAID: Estado.PAGADA,
    PaymentStatus.REJECTED: Estado.RECHAZADA,
    PaymentStatus.FAILED: Estado.RECHAZADA,
    PaymentStatus.CANCELLED: Estado.CANCELADA,
    PaymentStatus.EXPIRED: Estado.EXPIRADA,
    PaymentStatus.REFUNDED: Estado.REEMBOLSADA,
}

CERRADAS_SIN_PAGO = {Estado.RECHAZADA, Estado.EXPIRADA, Estado.CANCELADA, Estado.ERROR}

# A provider may report a payment after an earlier rejection of the same order
# (the client retries inside the checkout), so money received always wins.
TRANSICIONES = {
    Estado.CREANDO: {Estado.PENDIENTE, *CERRADAS_SIN_PAGO, Estado.PAGADA},
    Estado.PENDIENTE: {*CERRADAS_SIN_PAGO, Estado.PAGADA},
    **{estado: {Estado.PAGADA} for estado in CERRADAS_SIN_PAGO},
    Estado.PAGADA: {Estado.REEMBOLSADA},
    Estado.REEMBOLSADA: set(),
}


class VentaNoPagableError(Exception):
    """The sale is not waiting for payment."""


class ProveedorNoHabilitadoError(Exception):
    """The client chose a payment provider that is not enabled."""


class PlanNoDisponibleError(Exception):
    """The plan cannot be sold: inactive, off the portal, or missing a price."""


@dataclass(frozen=True)
class LineaVenta:
    """A line to sell. ``precio`` is a plan's price; None means the list price."""

    servicio: Servicio
    cantidad: int = 1
    precio: Decimal | None = None
    nombre: str | None = None


def _item(linea: LineaVenta | tuple[Servicio, int]) -> ItemVenta:
    if not isinstance(linea, LineaVenta):
        linea = LineaVenta(*linea)
    precio = linea.precio if linea.precio is not None else linea.servicio.precio_base
    return ItemVenta(
        servicio=linea.servicio,
        nombre=linea.nombre or linea.servicio.nombre,
        precio_unitario=precio,
        cantidad=linea.cantidad,
        subtotal=precio * linea.cantidad,
    )


def crear_venta(
    cliente: Cliente,
    items: Iterable[LineaVenta | tuple[Servicio, int]],
) -> Venta:
    """Record a sale at today's list or plan prices (RN-08).

    ``items`` are lines, or (servicio, cantidad) pairs sold at list price.
    """
    lineas = [_item(item) for item in items]
    with transaction.atomic():
        venta = Venta.objects.create(
            cliente=cliente,
            total=sum(linea.subtotal for linea in lineas),
        )
        for linea in lineas:
            linea.venta = venta
        ItemVenta.objects.bulk_create(lineas)
    # TODO(RF-15): record the sale in the audit log (HU-30).
    return venta


def planes_en_portal(servicio_codigo: str) -> QuerySet[PlanServicio]:
    """Active plans of a service the portal may sell, in display order."""
    return PlanServicio.objects.filter(
        servicio__codigo=servicio_codigo,
        servicio__activo=True,
        activo=True,
        se_vende_en_portal=True,
    ).select_related("servicio", "ciclo_pago")


def precio_firma() -> Decimal | None:
    """The list price of the signature charged on top of some plans."""
    return (
        Servicio.objects.filter(codigo=SERVICIO_FIRMA, activo=True)
        .values_list("precio_base", flat=True)
        .first()
    )


def lineas_de_plan(plan: PlanServicio) -> list[LineaVenta]:
    """What selling ``plan`` charges: the plan, plus the signature if not included.

    Raises:
        PlanNoDisponibleError: The plan or the signature cannot be sold.
    """
    if not (plan.activo and plan.se_vende_en_portal and plan.servicio.activo):
        raise PlanNoDisponibleError
    lineas = [
        LineaVenta(
            plan.servicio,
            precio=plan.precio,
            nombre=f"{plan.servicio.nombre} · {plan.nombre}",
        ),
    ]
    if not plan.firma_incluida:
        firma = Servicio.objects.filter(codigo=SERVICIO_FIRMA, activo=True).first()
        if firma is None or firma.precio_base is None:
            raise PlanNoDisponibleError
        lineas.append(LineaVenta(firma))
    return lineas


def anular_venta(venta: Venta) -> None:
    """Cancel a sale still waiting for payment, and its open attempts.

    A payment that still arrives for a cancelled attempt is recorded anyway,
    as for any closed attempt (see TRANSICIONES).

    Raises:
        VentaNoPagableError: The sale is not waiting for payment.
    """
    with transaction.atomic():
        venta = Venta.objects.select_for_update().get(pk=venta.pk)
        if venta.estado != Venta.Estado.PENDIENTE_PAGO:
            raise VentaNoPagableError
        venta.ordenes.filter(estado__in=OrdenPago.ABIERTAS).update(
            estado=Estado.CANCELADA,
        )
        venta.estado = Venta.Estado.ANULADA
        venta.save(update_fields=["estado", "updated_at"])
    # TODO(RF-15): record the cancellation in the audit log (HU-30).


def iniciar_pago(venta: Venta, proveedor: str) -> OrdenPago:
    """Return the sale's open attempt with ``proveedor``, or start a new one.

    An open attempt with another provider is cancelled: the client switched.
    A payment that still arrives for it is recorded anyway.

    Raises:
        VentaNoPagableError: The sale is not waiting for payment.
        ProveedorNoHabilitadoError: ``proveedor`` is not enabled.
    """
    from .tasks import crear_orden_en_proveedor  # noqa: PLC0415

    if proveedor not in proveedores_habilitados():
        raise ProveedorNoHabilitadoError
    with transaction.atomic():
        venta = Venta.objects.select_for_update().get(pk=venta.pk)
        if venta.estado != Venta.Estado.PENDIENTE_PAGO:
            raise VentaNoPagableError

        vigente_desde = timezone.now() - timedelta(
            minutes=settings.PAYMENT_ORDER_EXPIRATION_MINUTES,
        )
        abiertas = venta.ordenes.filter(estado__in=OrdenPago.ABIERTAS)
        abiertas.filter(created_at__lt=vigente_desde).update(estado=Estado.EXPIRADA)
        abiertas.exclude(proveedor=proveedor).update(estado=Estado.CANCELADA)
        abierta = abiertas.filter(proveedor=proveedor).first()
        if abierta is not None:
            return abierta

        orden = OrdenPago.objects.create(
            venta=venta,
            proveedor=proveedor,
            monto=venta.total,
        )
        transaction.on_commit(lambda: crear_orden_en_proveedor.delay(orden.pk))
    # TODO(RF-15): record the payment attempt in the audit log (HU-30).
    return orden


def orden_de_resultado(resultado: PaymentResult) -> OrdenPago | None:
    """The attempt a provider result refers to, by our reference and its id."""
    try:
        orden = OrdenPago.objects.get(referencia=uuid.UUID(resultado.reference))
    except ValueError, OrdenPago.DoesNotExist:
        return None
    if (
        orden.id_externo
        and resultado.external_id
        and orden.id_externo != resultado.external_id
    ):
        return None
    return orden


def aplicar_resultado(orden_id: int, resultado: PaymentResult, *, origen: str) -> bool:
    """Move an order, and its sale, to what the provider reports (RF-23).

    Safe to call again with the same result, and with results that arrive out
    of order: a move the transition table does not allow is ignored.

    Returns:
        Whether anything changed.
    """
    with transaction.atomic():
        orden = (
            OrdenPago.objects.select_for_update()
            .select_related("venta")
            .get(pk=orden_id)
        )
        nuevo = ESTADO_POR_RESULTADO[resultado.status]
        if nuevo == Estado.REEMBOLSADA and orden.estado in OrdenPago.ABIERTAS:
            # Reversed before we recorded the payment: no money stayed.
            orden.estado = Estado.RECHAZADA
            orden.detalle_error = "El proveedor reversó el cobro."
            orden.save(update_fields=["estado", "detalle_error", "updated_at"])
            return True
        if nuevo == orden.estado or nuevo not in TRANSICIONES[orden.estado]:
            return False

        if nuevo == Estado.PAGADA and resultado.amount not in (None, orden.monto):
            logger.error(
                "Order %s: provider reported %s paid, expected %s (%s).",
                orden.pk,
                resultado.amount,
                orden.monto,
                origen,
            )
            orden.estado = Estado.ERROR
            orden.detalle_error = (
                f"Monto informado {resultado.amount} distinto de {orden.monto}."
            )
            orden.save(update_fields=["estado", "detalle_error", "updated_at"])
            return True

        orden.estado = nuevo
        orden.save(update_fields=["estado", "updated_at"])
        if nuevo == Estado.PAGADA:
            _registrar_pago(orden, resultado)
        elif nuevo == Estado.REEMBOLSADA:
            Venta.objects.filter(pk=orden.venta_id).update(
                estado=Venta.Estado.REEMBOLSADA,
            )
    # TODO(RF-15): record the change and its origin in the audit log (HU-30).
    return True


def _registrar_pago(orden: OrdenPago, resultado: PaymentResult) -> None:
    detalles = resultado.details
    cuotas = detalles.get("installments", "")
    Pago.objects.get_or_create(
        orden=orden,
        tipo=Pago.Tipo.VENTA,
        defaults={
            "id_externo": resultado.authorization_code,
            "monto": resultado.amount or orden.monto,
            "medio": detalles.get("method", ""),
            "marca": detalles.get("brand", ""),
            "tipo_tarjeta": detalles.get("card_type", ""),
            "ultimos_digitos": detalles.get("last_digits", ""),
            "cuotas": int(cuotas) if cuotas.isdigit() else None,
            "billetera": detalles.get("wallet", ""),
            "pagado_en": timezone.now(),
            "respuesta": resultado.raw_response,
        },
    )
    venta = orden.venta
    if venta.estado == Venta.Estado.PAGADA:
        logger.error("Sale %s was already paid; order %s paid it again.", venta, orden)
        return
    venta.estado = Venta.Estado.PAGADA
    venta.pagada_en = timezone.now()
    venta.save(update_fields=["estado", "pagada_en", "updated_at"])
    transaction.on_commit(
        lambda: venta_pagada.send(sender=Venta, venta=venta),
    )


def ciclos_pago_activos() -> QuerySet[CicloPago]:
    """Payment cycles a contracted service may use, in display order."""
    return CicloPago.objects.filter(activo=True)


def servicios_contratables() -> QuerySet[Servicio]:
    """Active services an executive may put in a contract, portal or not."""
    return Servicio.objects.filter(activo=True).select_related("ciclo_pago_default")


def ventas_pagadas(desde: date, hasta: date) -> QuerySet[Venta]:
    """Sales paid within a period, both bounds inclusive in local time (RF-14).

    Refunded and annulled sales are left out, and so are sales still waiting
    for payment.
    """
    return Venta.objects.filter(
        estado=Venta.Estado.PAGADA,
        pagada_en__date__range=(desde, hasta),
    )


def total_vendido(ventas: QuerySet[Venta]) -> int:
    """Sum of the sales' totals in CLP."""
    return int(ventas.aggregate(total=Sum("total"))["total"] or 0)


def ventas_por_servicio(ventas: QuerySet[Venta]) -> list[dict[str, Any]]:
    """Amount and number of sales per catalogue service, largest amount first.

    Lines are grouped by their catalogue service, not by the name copied
    into the line (a plan line reads "Domicilio tributario · Plan anual").
    ``cantidad`` counts the sales that include the service, so a sale with
    two services counts once under each.
    """
    filas = (
        ItemVenta.objects.filter(venta__in=ventas)
        .values("servicio_id", "servicio__nombre")
        .annotate(monto=Sum("subtotal"), cantidad=Count("venta", distinct=True))
        .order_by("-monto", "servicio__nombre")
    )
    return [
        {
            "servicio": fila["servicio__nombre"],
            "monto": int(fila["monto"]),
            "cantidad": fila["cantidad"],
        }
        for fila in filas
    ]

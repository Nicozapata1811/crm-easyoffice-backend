"""Factories for sales. Every value they produce is synthetic."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from typing import Any

from factory import LazyAttribute
from factory import Sequence
from factory import SubFactory
from factory.django import DjangoModelFactory

from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.models import Servicio
from crm_easyoffice.ventas.models import Venta
from crm_easyoffice.ventas.services import crear_venta

if TYPE_CHECKING:
    from datetime import datetime


class ServicioFactory(DjangoModelFactory[Servicio]):
    codigo = Sequence(lambda n: f"servicio-{n}")
    nombre = Sequence(lambda n: f"Servicio de ejemplo {n}")
    precio_base = Decimal(10000)

    class Meta:
        model = Servicio


class VentaFactory(DjangoModelFactory[Venta]):
    cliente = SubFactory(ClienteFactory)
    total = Decimal(18400)

    class Meta:
        model = Venta


class OrdenPagoFactory(DjangoModelFactory[OrdenPago]):
    venta = SubFactory(VentaFactory)
    proveedor = "klap"
    monto = LazyAttribute(lambda orden: orden.venta.total)
    estado = OrdenPago.Estado.PENDIENTE
    id_externo = Sequence(lambda n: f"KLAP-{n}")

    class Meta:
        model = OrdenPago


def venta_pagada(
    pagada_en: datetime,
    *lineas: tuple[Servicio, int],
    estado: str = Venta.Estado.PAGADA,
    **campos: Any,
) -> Venta:
    """A sale of ``lineas`` at list price, paid at ``pagada_en``, left in ``estado``."""
    venta = crear_venta(campos.pop("cliente", None) or ClienteFactory.create(), lineas)
    Venta.objects.filter(pk=venta.pk).update(estado=estado, pagada_en=pagada_en)
    venta.refresh_from_db()
    return venta

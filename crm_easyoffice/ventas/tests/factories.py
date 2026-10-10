"""Factories for sales. Every value they produce is synthetic."""

from __future__ import annotations

from decimal import Decimal

from factory import LazyAttribute
from factory import Sequence
from factory import SubFactory
from factory.django import DjangoModelFactory

from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.models import Servicio
from crm_easyoffice.ventas.models import Venta


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

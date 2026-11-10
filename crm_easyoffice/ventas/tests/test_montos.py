"""Net, VAT and total: computed once, and unchanged for prices that include VAT."""

from __future__ import annotations

from decimal import Decimal

import pytest

from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.ventas.models import PlanServicio
from crm_easyoffice.ventas.models import Servicio
from crm_easyoffice.ventas.montos import desglosar
from crm_easyoffice.ventas.services import crear_venta
from crm_easyoffice.ventas.services import lineas_de_plan
from crm_easyoffice.ventas.tests.factories import ServicioFactory

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("precio", "incluye_iva", "esperado"),
    [
        # "Más IVA": 19 % on top, rounded half up.
        (30000, False, (30000, 5700, 35700)),
        (50000, False, (50000, 9500, 59500)),
        (12345, False, (12345, 2346, 14691)),
        # VAT included: the total is the price, never changed.
        (59990, True, (50412, 9578, 59990)),
        (39990, True, (33605, 6385, 39990)),
        (5000, True, (4202, 798, 5000)),
    ],
)
def test_a_price_splits_into_net_vat_and_total(precio, incluye_iva, esperado):
    desglose = desglosar(Decimal(precio), incluye_iva=incluye_iva)

    assert tuple(int(v) for v in desglose) == esperado
    assert desglose.neto + desglose.iva == desglose.total


def test_a_net_service_is_charged_with_its_vat():
    servicio = ServicioFactory.create(
        precio_base=Decimal(30000),
        precio_incluye_iva=False,
    )

    venta = crear_venta(ClienteFactory.create(), [(servicio, 2)])

    assert (venta.neto, venta.iva, venta.total) == (60000, 11400, 71400)
    (item,) = venta.items.all()
    assert (item.precio_unitario, item.subtotal) == (35700, 71400)
    assert (item.neto, item.iva) == (60000, 11400)


@pytest.mark.parametrize(
    ("plan", "total", "neto"),
    [("anual", 59990, 50412), ("semestral", 44990, 37807)],
)
def test_the_domicile_plans_charge_what_they_always_did(plan, total, neto):
    """The semestral plan adds the signature (39.990 + 5.000), both VAT included."""
    registro = PlanServicio.objects.get(
        servicio__codigo="domicilio-tributario",
        codigo=plan,
    )

    venta = crear_venta(ClienteFactory.create(), lineas_de_plan(registro))

    assert venta.total == total
    assert (venta.neto, venta.iva) == (neto, total - neto)
    assert sum(i.subtotal for i in venta.items.all()) == total
    assert sum(i.neto for i in venta.items.all()) == neto


def test_the_warehouse_plan_charges_what_it_always_did():
    registro = PlanServicio.objects.get(servicio__codigo="bodega", codigo="anual")

    venta = crear_venta(ClienteFactory.create(), lineas_de_plan(registro))

    assert (venta.neto, venta.iva, venta.total) == (50412, 9578, 59990)


def test_only_the_new_document_services_read_plus_vat():
    netos = set(
        Servicio.objects.filter(precio_incluye_iva=False).values_list(
            "codigo",
            flat=True,
        ),
    )

    assert netos == {"arriendo-vehiculo"}

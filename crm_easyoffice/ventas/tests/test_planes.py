"""Plans in which a service is sold online (HU-24). All data is synthetic."""

from __future__ import annotations

import importlib
from decimal import Decimal

import pytest
from django.apps import apps
from django.db import IntegrityError

from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.models import PlanServicio
from crm_easyoffice.ventas.models import Servicio
from crm_easyoffice.ventas.models import Venta
from crm_easyoffice.ventas.services import PlanNoDisponibleError
from crm_easyoffice.ventas.services import VentaNoPagableError
from crm_easyoffice.ventas.services import anular_venta
from crm_easyoffice.ventas.services import crear_venta
from crm_easyoffice.ventas.services import lineas_de_plan
from crm_easyoffice.ventas.services import planes_en_portal
from crm_easyoffice.ventas.services import precio_firma
from crm_easyoffice.ventas.services import venta_pagada
from crm_easyoffice.ventas.tests.factories import OrdenPagoFactory
from crm_easyoffice.ventas.tests.factories import VentaFactory

pytestmark = pytest.mark.django_db

seed = importlib.import_module(
    "crm_easyoffice.ventas.migrations.0012_seed_planes_domicilio",
)


def plan(codigo: str) -> PlanServicio:
    return PlanServicio.objects.select_related("servicio", "ciclo_pago").get(
        servicio__codigo="domicilio-tributario",
        codigo=codigo,
    )


class TestSeed:
    def test_seed_offers_two_domicile_plans(self):
        planes = list(planes_en_portal("domicilio-tributario"))

        assert [(p.codigo, p.duracion_meses, p.ciclo_pago.codigo) for p in planes] == [
            ("anual", 12, "anual"),
            ("semestral", 6, "semestral"),
        ]
        assert [p.precio for p in planes] == [Decimal(59990), Decimal(39990)]
        assert [p.firma_incluida for p in planes] == [True, False]
        assert not any(p.precio_confirmado for p in planes)

    def test_seed_charges_the_signature_at_the_website_price(self):
        assert precio_firma() == Decimal(5000)

    def test_seed_is_idempotent_and_keeps_admin_edits(self):
        anual = plan("anual")
        anual.precio = Decimal(61000)
        anual.save()

        seed.seed(apps, None)

        assert PlanServicio.objects.count() == 2  # noqa: PLR2004
        assert plan("anual").precio == Decimal(61000)

    def test_seed_keeps_an_edited_signature_price(self):
        Servicio.objects.filter(codigo="firma-electronica-avanzada").update(
            precio_base=Decimal(5900),
        )

        seed.seed(apps, None)

        assert precio_firma() == Decimal(5900)


class TestPlanes:
    def test_a_plan_code_is_unique_per_service(self):
        anual = plan("anual")

        with pytest.raises(IntegrityError):
            PlanServicio.objects.create(
                servicio=anual.servicio,
                codigo="anual",
                nombre="Otro",
                duracion_meses=12,
                ciclo_pago=anual.ciclo_pago,
                precio=Decimal(1),
            )

    def test_inactive_or_offline_plans_are_not_offered(self):
        PlanServicio.objects.filter(codigo="anual").update(activo=False)
        PlanServicio.objects.filter(codigo="semestral").update(se_vende_en_portal=False)

        assert not planes_en_portal("domicilio-tributario").exists()


class TestLineasDePlan:
    def test_a_plan_with_the_signature_included_is_one_line(self):
        venta = crear_venta(ClienteFactory.create(), lineas_de_plan(plan("anual")))

        (item,) = venta.items.all()
        assert item.servicio.codigo == "domicilio-tributario"
        assert item.nombre == "Domicilio tributario · Plan anual"
        assert item.precio_unitario == Decimal(59990)
        assert venta.total == Decimal(59990)

    def test_a_plan_without_the_signature_adds_it(self):
        venta = crear_venta(ClienteFactory.create(), lineas_de_plan(plan("semestral")))

        items = {i.servicio.codigo: i.precio_unitario for i in venta.items.all()}
        assert items == {
            "domicilio-tributario": Decimal(39990),
            "firma-electronica-avanzada": Decimal(5000),
        }
        assert venta.total == Decimal(44990)

    def test_the_plan_price_is_copied(self):
        semestral = plan("semestral")
        venta = crear_venta(ClienteFactory.create(), lineas_de_plan(semestral))
        semestral.precio = Decimal(1)
        semestral.save()

        assert venta.items.get(servicio__codigo="domicilio-tributario").subtotal == (
            Decimal(39990)
        )

    def test_an_inactive_plan_cannot_be_sold(self):
        anual = plan("anual")
        anual.activo = False

        with pytest.raises(PlanNoDisponibleError):
            lineas_de_plan(anual)

    def test_without_a_signature_service_the_plan_cannot_be_sold(self):
        Servicio.objects.filter(codigo="firma-electronica-avanzada").update(
            activo=False,
        )

        with pytest.raises(PlanNoDisponibleError):
            lineas_de_plan(plan("semestral"))


class TestAnularVenta:
    def test_cancels_the_sale_and_its_open_attempts(self):
        orden = OrdenPagoFactory.create()

        anular_venta(orden.venta)

        orden.refresh_from_db()
        orden.venta.refresh_from_db()
        assert orden.venta.estado == Venta.Estado.ANULADA
        assert orden.estado == OrdenPago.Estado.CANCELADA

    def test_a_paid_sale_cannot_be_cancelled(self):
        venta = VentaFactory.create(estado=Venta.Estado.PAGADA)

        with pytest.raises(VentaNoPagableError):
            anular_venta(venta)


def test_a_paid_sale_announces_itself(django_capture_on_commit_callbacks):
    from crm_easyoffice.integrations.payment.base import PaymentResult  # noqa: PLC0415
    from crm_easyoffice.integrations.payment.base import PaymentStatus  # noqa: PLC0415
    from crm_easyoffice.ventas.services import aplicar_resultado  # noqa: PLC0415

    recibidas: list[Venta] = []

    def receptor(sender, venta, **kwargs):
        recibidas.append(venta)

    venta_pagada.connect(receptor)
    try:
        orden = OrdenPagoFactory.create()
        with django_capture_on_commit_callbacks(execute=True):
            aplicar_resultado(
                orden.pk,
                PaymentResult(
                    external_id=orden.id_externo,
                    reference=str(orden.referencia),
                    status=PaymentStatus.PAID,
                    amount=orden.monto,
                ),
                origen="test",
            )
    finally:
        venta_pagada.disconnect(receptor)

    assert [v.pk for v in recibidas] == [orden.venta_id]

"""Sale and payment state rules. All data here is synthetic."""

from __future__ import annotations

from datetime import date
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.integrations.payment.base import PaymentResult
from crm_easyoffice.integrations.payment.base import PaymentStatus
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.models import Pago
from crm_easyoffice.ventas.models import Venta
from crm_easyoffice.ventas.services import ProveedorNoHabilitadoError
from crm_easyoffice.ventas.services import VentaNoPagableError
from crm_easyoffice.ventas.services import aplicar_resultado
from crm_easyoffice.ventas.services import crear_venta
from crm_easyoffice.ventas.services import iniciar_pago
from crm_easyoffice.ventas.services import total_vendido
from crm_easyoffice.ventas.services import ventas_pagadas
from crm_easyoffice.ventas.services import ventas_por_servicio
from crm_easyoffice.ventas.tests.factories import OrdenPagoFactory
from crm_easyoffice.ventas.tests.factories import ServicioFactory
from crm_easyoffice.ventas.tests.factories import VentaFactory
from crm_easyoffice.ventas.tests.factories import venta_pagada

pytestmark = pytest.mark.django_db

Estado = OrdenPago.Estado


def resultado(orden: OrdenPago, status: PaymentStatus, **extra) -> PaymentResult:
    return PaymentResult(
        external_id=orden.id_externo or "",
        reference=str(orden.referencia),
        status=status,
        **{"amount": orden.monto, **extra},
    )


@pytest.fixture(autouse=True)
def _proveedores(settings):
    settings.PAYMENT_PROVIDERS = ["klap", "flow"]


@pytest.fixture
def sin_tareas(monkeypatch):
    enviadas: list[int] = []
    monkeypatch.setattr(
        "crm_easyoffice.ventas.tasks.crear_orden_en_proveedor.delay",
        enviadas.append,
    )
    return enviadas


class TestCrearVenta:
    def test_copies_the_list_price(self):
        servicio = ServicioFactory.create(precio_base=Decimal(14900))

        venta = crear_venta(ClienteFactory.create(), [(servicio, 2)])
        servicio.precio_base = Decimal(99999)
        servicio.save()

        item = venta.items.get()
        assert item.precio_unitario == Decimal(14900)
        assert venta.total == Decimal(29800)
        assert venta.folio == f"VEN-{venta.pk:06d}"


class TestIniciarPago:
    def test_creates_an_attempt_and_queues_it(
        self,
        sin_tareas,
        django_capture_on_commit_callbacks,
    ):
        venta = VentaFactory.create()

        with django_capture_on_commit_callbacks(execute=True):
            orden = iniciar_pago(venta, "klap")

        assert orden.estado == Estado.CREANDO
        assert orden.monto == venta.total
        assert sin_tareas == [orden.pk]

    def test_reuses_the_open_attempt(self, sin_tareas):
        abierta = OrdenPagoFactory.create()

        assert iniciar_pago(abierta.venta, "klap") == abierta

    def test_expires_a_stale_attempt_and_starts_another(self, sin_tareas):
        vieja = OrdenPagoFactory.create()
        OrdenPago.objects.filter(pk=vieja.pk).update(
            created_at=timezone.now() - timedelta(hours=2),
        )

        nueva = iniciar_pago(vieja.venta, "klap")

        vieja.refresh_from_db()
        assert nueva != vieja
        assert vieja.estado == Estado.EXPIRADA

    def test_switching_provider_cancels_the_other_attempt(self, sin_tareas):
        klap = OrdenPagoFactory.create(proveedor="klap")

        flow = iniciar_pago(klap.venta, "flow")

        klap.refresh_from_db()
        assert flow.proveedor == "flow"
        assert klap.estado == Estado.CANCELADA

    def test_a_disabled_provider_is_refused(self, sin_tareas):
        with pytest.raises(ProveedorNoHabilitadoError):
            iniciar_pago(VentaFactory.create(), "simulated")

    def test_a_paid_sale_cannot_be_paid_again(self, sin_tareas):
        with pytest.raises(VentaNoPagableError):
            iniciar_pago(VentaFactory.create(estado=Venta.Estado.PAGADA), "klap")


class TestAplicarResultado:
    def test_payment_marks_order_and_sale_paid(self):
        orden = OrdenPagoFactory.create()

        cambio = aplicar_resultado(
            orden.pk,
            resultado(
                orden,
                PaymentStatus.PAID,
                authorization_code="MC-1",
                details={"brand": "VISA", "installments": "3"},
            ),
            origen="test",
        )

        orden.refresh_from_db()
        orden.venta.refresh_from_db()
        pago = Pago.objects.get()
        assert cambio
        assert orden.estado == Estado.PAGADA
        assert orden.venta.estado == Venta.Estado.PAGADA
        assert orden.venta.pagada_en
        assert (pago.id_externo, pago.marca, pago.cuotas) == ("MC-1", "VISA", 3)

    def test_is_idempotent(self):
        orden = OrdenPagoFactory.create()
        pagado = resultado(orden, PaymentStatus.PAID)

        aplicar_resultado(orden.pk, pagado, origen="webhook")
        repetido = aplicar_resultado(orden.pk, pagado, origen="consulta")

        assert not repetido
        assert Pago.objects.count() == 1

    def test_a_late_rejection_does_not_undo_a_payment(self):
        orden = OrdenPagoFactory.create(estado=Estado.PAGADA)

        cambio = aplicar_resultado(
            orden.pk,
            resultado(orden, PaymentStatus.REJECTED),
            origen="test",
        )

        orden.refresh_from_db()
        assert not cambio
        assert orden.estado == Estado.PAGADA

    def test_a_payment_after_a_rejection_is_recorded(self):
        orden = OrdenPagoFactory.create(estado=Estado.RECHAZADA)

        aplicar_resultado(orden.pk, resultado(orden, PaymentStatus.PAID), origen="test")

        orden.refresh_from_db()
        assert orden.estado == Estado.PAGADA

    def test_a_payment_reuses_a_transaction_code_seen_before(self):
        primera, segunda = OrdenPagoFactory.create_batch(2)

        for orden in (primera, segunda):
            aplicar_resultado(
                orden.pk,
                resultado(orden, PaymentStatus.PAID, authorization_code="MC-REPETIDO"),
                origen="test",
            )

        assert Pago.objects.filter(id_externo="MC-REPETIDO").count() == 2  # noqa: PLR2004

    def test_a_reversal_before_payment_closes_the_order(self):
        orden = OrdenPagoFactory.create()

        aplicar_resultado(
            orden.pk,
            resultado(orden, PaymentStatus.REFUNDED),
            origen="test",
        )

        orden.refresh_from_db()
        orden.venta.refresh_from_db()
        assert orden.estado == Estado.RECHAZADA
        assert orden.venta.estado == Venta.Estado.PENDIENTE_PAGO

    def test_a_different_amount_is_an_error(self):
        orden = OrdenPagoFactory.create()

        aplicar_resultado(
            orden.pk,
            resultado(orden, PaymentStatus.PAID, amount=Decimal(1)),
            origen="test",
        )

        orden.refresh_from_db()
        orden.venta.refresh_from_db()
        assert orden.estado == Estado.ERROR
        assert orden.venta.estado == Venta.Estado.PENDIENTE_PAGO
        assert not Pago.objects.exists()


SANTIAGO = ZoneInfo("America/Santiago")
SEPTIEMBRE = (date(2026, 9, 1), date(2026, 9, 30))


def en_santiago(*partes: int) -> datetime:
    return datetime(*partes, tzinfo=SANTIAGO)


class TestVentasDelPeriodo:
    def test_period_is_inclusive_in_local_time(self):
        servicio = ServicioFactory.create()
        venta_pagada(en_santiago(2026, 8, 31, 23, 30), (servicio, 1))
        primera = venta_pagada(en_santiago(2026, 9, 1, 0, 30), (servicio, 1))
        ultima = venta_pagada(en_santiago(2026, 9, 30, 23, 30), (servicio, 1))
        venta_pagada(en_santiago(2026, 10, 1, 0, 30), (servicio, 1))

        assert set(ventas_pagadas(*SEPTIEMBRE)) == {primera, ultima}

    @pytest.mark.parametrize(
        "estado",
        [
            Venta.Estado.REEMBOLSADA,
            Venta.Estado.ANULADA,
            Venta.Estado.PENDIENTE_PAGO,
        ],
    )
    def test_only_paid_sales_count(self, estado):
        servicio = ServicioFactory.create()
        venta_pagada(en_santiago(2026, 9, 10, 12), (servicio, 1), estado=estado)

        ventas = ventas_pagadas(*SEPTIEMBRE)

        assert not ventas.exists()
        assert total_vendido(ventas) == 0
        assert ventas_por_servicio(ventas) == []

    def test_breakdown_by_service_adds_up_to_the_total(self):
        domicilio = ServicioFactory.create(
            nombre="Servicio A de prueba",
            precio_base=Decimal(30000),
        )
        firma = ServicioFactory.create(
            nombre="Servicio B de prueba",
            precio_base=Decimal(5000),
        )
        venta_pagada(en_santiago(2026, 9, 5, 10), (domicilio, 1), (firma, 1))
        venta_pagada(en_santiago(2026, 9, 6, 10), (domicilio, 1))
        venta_pagada(en_santiago(2026, 9, 7, 10), (firma, 2))

        ventas = ventas_pagadas(*SEPTIEMBRE)

        assert total_vendido(ventas) == 75000  # noqa: PLR2004
        assert ventas_por_servicio(ventas) == [
            {"servicio": "Servicio A de prueba", "monto": 60000, "cantidad": 2},
            {"servicio": "Servicio B de prueba", "monto": 15000, "cantidad": 2},
        ]

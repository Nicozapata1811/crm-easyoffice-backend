"""Celery tasks with the provider replaced. All data here is synthetic."""

from __future__ import annotations

from decimal import Decimal

import pytest

from crm_easyoffice.integrations.payment.base import PaymentError
from crm_easyoffice.integrations.payment.base import PaymentResult
from crm_easyoffice.integrations.payment.base import PaymentStatus
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.tasks import crear_orden_en_proveedor
from crm_easyoffice.ventas.tasks import sincronizar_orden
from crm_easyoffice.ventas.tests.factories import OrdenPagoFactory

pytestmark = pytest.mark.django_db


class FakeProvider:
    def __init__(
        self,
        *,
        error: PaymentError | None = None,
        status=PaymentStatus.PENDING,
    ):
        self.error = error
        self.status = status
        self.solicitudes = []

    def create_payment(self, request):
        self.solicitudes.append(request)
        if self.error:
            raise self.error
        return PaymentResult(
            external_id="KLAP-NEW",
            reference=request.reference,
            status=PaymentStatus.PENDING,
            amount=request.amount,
            redirect_url="https://klap.invalid/order/KLAP-NEW",
        )

    def get_status(self, external_id):
        return PaymentResult(
            external_id=external_id,
            reference="",
            status=self.status,
            amount=Decimal(18400),
        )


@pytest.fixture
def provider(monkeypatch):
    def usar(fake: FakeProvider) -> FakeProvider:
        monkeypatch.setattr(
            "crm_easyoffice.ventas.tasks.get_payment_provider",
            lambda nombre: fake,
        )
        return fake

    return usar


def test_creates_the_order_at_the_provider(provider, settings):
    settings.PAYMENT_WEBHOOK_BASE_URL = "https://tunnel.invalid/"
    fake = provider(FakeProvider())
    orden = OrdenPagoFactory.create(estado=OrdenPago.Estado.CREANDO, id_externo=None)

    crear_orden_en_proveedor(orden.pk)

    orden.refresh_from_db()
    solicitud = fake.solicitudes[0]
    assert orden.estado == OrdenPago.Estado.PENDIENTE
    assert orden.id_externo == "KLAP-NEW"
    assert solicitud.reference == str(orden.referencia)
    assert (
        solicitud.notification_url == "https://tunnel.invalid/api/pagos/webhooks/klap/"
    )
    assert (
        solicitud.return_url == f"https://tunnel.invalid/api/pagos/retorno/{orden.pk}/"
    )
    assert solicitud.cancel_url == f"{solicitud.return_url}?cancelado=1"
    assert solicitud.payer.email == orden.venta.cliente.persona.email


def test_a_definitive_error_closes_the_attempt(provider):
    provider(FakeProvider(error=PaymentError("bad request")))
    orden = OrdenPagoFactory.create(estado=OrdenPago.Estado.CREANDO, id_externo=None)

    crear_orden_en_proveedor(orden.pk)

    orden.refresh_from_db()
    assert orden.estado == OrdenPago.Estado.ERROR
    assert "bad request" in orden.detalle_error


def test_a_transient_error_is_retried(provider):
    fake = provider(FakeProvider(error=PaymentError("timeout", transient=True)))
    orden = OrdenPagoFactory.create(estado=OrdenPago.Estado.CREANDO, id_externo=None)

    crear_orden_en_proveedor.apply(args=[orden.pk])

    orden.refresh_from_db()
    assert len(fake.solicitudes) == 4  # noqa: PLR2004
    assert orden.estado == OrdenPago.Estado.ERROR


def test_sync_applies_the_provider_state(provider):
    provider(FakeProvider(status=PaymentStatus.PAID))
    orden = OrdenPagoFactory.create()

    sincronizar_orden(orden.pk)

    orden.refresh_from_db()
    assert orden.estado == OrdenPago.Estado.PAGADA
    assert orden.sincronizada_en

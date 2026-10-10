"""Flow's notification and return flow, with Flow itself replaced.

All data here is synthetic.
"""

from __future__ import annotations

from decimal import Decimal
from http import HTTPStatus

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from crm_easyoffice.integrations.payment.base import PaymentError
from crm_easyoffice.integrations.payment.base import PaymentResult
from crm_easyoffice.integrations.payment.base import PaymentStatus
from crm_easyoffice.ventas.models import EventoPago
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.tests.factories import OrdenPagoFactory

pytestmark = pytest.mark.django_db


class FakeFlow:
    webhook_needs_lookup = True

    def __init__(self, resultado: PaymentResult | PaymentError):
        self.resultado = resultado
        self.tokens: list[str] = []

    def parse_webhook(self, payload, headers, *, event=None):
        self.tokens.append(payload["token"])
        if isinstance(self.resultado, PaymentError):
            raise self.resultado
        return self.resultado


@pytest.fixture(autouse=True)
def _flow(settings):
    settings.PAYMENT_PROVIDERS = ["klap", "flow"]
    settings.PORTAL_BASE_URL = "https://portal.invalid"


@pytest.fixture
def orden() -> OrdenPago:
    return OrdenPagoFactory.create(proveedor="flow", id_externo="3567899")


def flow_responde(monkeypatch, resultado) -> FakeFlow:
    fake = FakeFlow(resultado)
    for modulo in ("crm_easyoffice.ventas.tasks", "crm_easyoffice.ventas.api.views"):
        monkeypatch.setattr(f"{modulo}.get_payment_provider", lambda nombre: fake)
    return fake


def pagado(orden: OrdenPago, **extra) -> PaymentResult:
    return PaymentResult(
        external_id=orden.id_externo,
        reference=str(orden.referencia),
        status=PaymentStatus.PAID,
        amount=orden.monto,
        details={"method": "Webpay"},
        **extra,
    )


def notificar(token: str = "TOK"):  # noqa: S107
    return APIClient().post(
        reverse("pagos:webhook", args=["flow", "confirmacion"]),
        {"token": token},
    )


def test_a_confirmation_is_verified_in_the_background(
    monkeypatch,
    orden,
    django_capture_on_commit_callbacks,
):
    fake = flow_responde(monkeypatch, pagado(orden))

    with django_capture_on_commit_callbacks(execute=True):
        response = notificar()

    orden.refresh_from_db()
    evento = EventoPago.objects.get()
    assert response.status_code == HTTPStatus.OK
    assert fake.tokens == ["TOK"]
    assert orden.estado == OrdenPago.Estado.PAGADA
    assert orden.pagos.get().medio == "Webpay"
    assert (evento.resultado, evento.orden) == (EventoPago.Resultado.PROCESADO, orden)


def test_a_repeated_notification_is_processed_once(
    monkeypatch,
    orden,
    django_capture_on_commit_callbacks,
):
    fake = flow_responde(monkeypatch, pagado(orden))

    for _ in range(2):
        with django_capture_on_commit_callbacks(execute=True):
            assert notificar().status_code == HTTPStatus.OK

    assert fake.tokens == ["TOK"]
    assert EventoPago.objects.count() == 1


def test_a_token_flow_does_not_know_is_logged_and_ignored(
    monkeypatch,
    orden,
    django_capture_on_commit_callbacks,
):
    flow_responde(monkeypatch, PaymentError("Token invalid"))

    with django_capture_on_commit_callbacks(execute=True):
        notificar("NOPE")

    orden.refresh_from_db()
    assert orden.estado == OrdenPago.Estado.PENDIENTE
    assert EventoPago.objects.get().resultado == EventoPago.Resultado.FIRMA_INVALIDA


def test_a_result_for_another_order_is_refused(
    monkeypatch,
    orden,
    django_capture_on_commit_callbacks,
):
    otra = PaymentResult(
        external_id="999",
        reference="not-a-uuid",
        status=PaymentStatus.PAID,
        amount=Decimal(1),
    )
    flow_responde(monkeypatch, otra)

    with django_capture_on_commit_callbacks(execute=True):
        notificar()

    assert EventoPago.objects.get().resultado == EventoPago.Resultado.RECHAZADO


@pytest.mark.parametrize(
    ("query", "pagina"),
    [("", "resultado"), ("?cancelado=1", "cancelado")],
)
def test_the_return_redirects_the_browser_and_rechecks(
    monkeypatch,
    orden,
    query,
    pagina,
    django_capture_on_commit_callbacks,
):
    revisadas: list[int] = []
    monkeypatch.setattr(
        "crm_easyoffice.ventas.api.views.sincronizar_orden.delay",
        revisadas.append,
    )

    with django_capture_on_commit_callbacks(execute=True):
        response = APIClient().post(
            reverse("pagos:retorno", args=[orden.pk]) + query,
            {"token": "TOK"},
        )

    assert response.status_code == HTTPStatus.SEE_OTHER
    assert response["Location"] == f"https://portal.invalid/pagos/{orden.pk}/{pagina}"
    assert revisadas == [orden.pk]

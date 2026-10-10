"""The payment providers the client may choose from (``PAYMENT_PROVIDERS``)."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from .base import PaymentError
from .base import PaymentProvider
from .flow import FlowPaymentProvider
from .klap import KlapPaymentProvider
from .simulated import SimulatedPaymentProvider
from .tunnel import quick_tunnel_url

KLAP = "klap"
FLOW = "flow"
SIMULATED = "simulated"

MODAL = "modal"
REDIRECCION = "redireccion"


@dataclass(frozen=True)
class MedioPago:
    """How the portal shows a provider and opens its checkout."""

    codigo: str
    nombre: str
    descripcion: str
    checkout: str


MEDIOS = {
    KLAP: MedioPago(KLAP, "Klap", "Tarjetas de crédito, débito y prepago", MODAL),
    FLOW: MedioPago(FLOW, "Flow", "Webpay, transferencia y otros medios", REDIRECCION),
    SIMULATED: MedioPago(SIMULATED, "Pago simulado", "Solo para pruebas", REDIRECCION),
}


def proveedores_habilitados() -> list[str]:
    return [nombre for nombre in settings.PAYMENT_PROVIDERS if nombre in MEDIOS]


def medios_habilitados() -> list[MedioPago]:
    return [MEDIOS[nombre] for nombre in proveedores_habilitados()]


def get_payment_provider(nombre: str) -> PaymentProvider:
    if nombre == KLAP:
        return KlapPaymentProvider(
            settings.KLAP_API_KEY,
            settings.KLAP_API_BASE_URL,
            methods=settings.KLAP_METHODS,
            expiration_minutes=settings.PAYMENT_ORDER_EXPIRATION_MINUTES,
        )
    if nombre == FLOW:
        return FlowPaymentProvider(
            settings.FLOW_API_KEY,
            settings.FLOW_SECRET_KEY,
            settings.FLOW_API_BASE_URL,
            payment_method=settings.FLOW_PAYMENT_METHOD,
            expiration_minutes=settings.PAYMENT_ORDER_EXPIRATION_MINUTES,
        )
    if nombre == SIMULATED:
        return SimulatedPaymentProvider()
    msg = f"Unknown payment provider: {nombre!r}"
    raise PaymentError(msg)


def webhook_base_url() -> str:
    """Where the provider posts webhooks: the configured URL or the local tunnel's."""
    if settings.PAYMENT_WEBHOOK_BASE_URL:
        return settings.PAYMENT_WEBHOOK_BASE_URL
    if settings.PAYMENT_TUNNEL_METRICS_URL:
        return quick_tunnel_url(settings.PAYMENT_TUNNEL_METRICS_URL)
    return ""


def checkout_script_url(nombre: str) -> str | None:
    """The script the browser loads to open the provider's checkout, if any."""
    return settings.KLAP_CHECKOUT_JS_URL if nombre == KLAP else None

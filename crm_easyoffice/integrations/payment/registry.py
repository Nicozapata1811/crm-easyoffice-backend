"""Picks the payment provider configured in ``settings.PAYMENT_PROVIDER``."""

from __future__ import annotations

from django.conf import settings

from .base import PaymentError
from .base import PaymentProvider
from .klap import KlapPaymentProvider
from .simulated import SimulatedPaymentProvider

KLAP = "klap"
SIMULATED = "simulated"


def get_payment_provider() -> PaymentProvider:
    nombre = settings.PAYMENT_PROVIDER
    if nombre == KLAP:
        return KlapPaymentProvider(
            settings.KLAP_API_KEY,
            settings.KLAP_API_BASE_URL,
            methods=settings.KLAP_METHODS,
            expiration_minutes=settings.KLAP_ORDER_EXPIRATION_MINUTES,
        )
    if nombre == SIMULATED:
        return SimulatedPaymentProvider()
    msg = f"Unknown PAYMENT_PROVIDER: {nombre!r}"
    raise PaymentError(msg)


def checkout_script_url() -> str | None:
    """The script the browser loads to open the provider's checkout, if any."""
    return settings.KLAP_CHECKOUT_JS_URL if settings.PAYMENT_PROVIDER == KLAP else None

"""The signature provider in use (``SIGNATURE_PROVIDER``)."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import SignatureError
from .base import SignatureProvider
from .base import SignatureResult
from .http import HttpSignatureProvider
from .simulated import SimulatedSignatureProvider

HTTP = "http"
SIMULATED = "simulated"

# The test PSC's compose name, and hosts that only exist on a developer's
# machine. A provider there cannot be an accredited one.
HOSTS_DE_PRUEBA = frozenset({"firma-sandbox", "localhost"})
SUFIJOS_DE_PRUEBA = (".localhost", ".test", ".local")


def es_url_de_pruebas(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if host in HOSTS_DE_PRUEBA or host.endswith(SUFIJOS_DE_PRUEBA):
        return True
    try:
        direccion = ipaddress.ip_address(host)
    except ValueError:
        return False
    return direccion.is_loopback or direccion.is_private


def exigir_proveedor_real(proveedor: str, url: str) -> None:
    """Refuse, in production settings, the test signature service.

    Raises:
        ImproperlyConfigured: An HTTP provider at the test PSC's address or
            another development host.
    """
    if proveedor == HTTP and es_url_de_pruebas(url):
        msg = (
            f"Production cannot use the test signature service at {url!r}: its "
            "signatures have no legal validity."
        )
        raise ImproperlyConfigured(msg)


def get_signature_provider() -> SignatureProvider:
    if settings.SIGNATURE_PROVIDER == HTTP:
        if not settings.SIGNATURE_ALLOW_SANDBOX and es_url_de_pruebas(
            settings.SIGNATURE_API_BASE_URL,
        ):
            msg = "The test signature service is not allowed in this environment."
            raise SignatureError(msg)
        return HttpSignatureProvider(
            settings.SIGNATURE_API_BASE_URL,
            settings.SIGNATURE_API_KEY,
            settings.SIGNATURE_WEBHOOK_SECRET,
            tolerance_seconds=settings.SIGNATURE_WEBHOOK_TOLERANCE_SECONDS,
        )
    if settings.SIGNATURE_PROVIDER == SIMULATED:
        return SimulatedSignatureProvider(auto_sign=False)
    msg = f"Unknown signature provider: {settings.SIGNATURE_PROVIDER!r}"
    raise SignatureError(msg)


def exigir_resultado_admitido(result: SignatureResult) -> None:
    """Refuse a provider that says it is a test one where that is not allowed."""
    if result.test_environment and not settings.SIGNATURE_ALLOW_SANDBOX:
        msg = "The signature provider is a test environment, not allowed here."
        raise SignatureError(msg)


def webhook_url() -> str:
    """Where the provider posts its webhooks."""
    base = settings.SIGNATURE_WEBHOOK_BASE_URL.rstrip("/")
    return f"{base}/api/firma/webhooks/{settings.SIGNATURE_PROVIDER}/"

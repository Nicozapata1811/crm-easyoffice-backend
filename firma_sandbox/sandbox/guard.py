"""The sandbox's start guard: it never runs outside development and tests.

The signatures this service produces have no legal validity (Ley 19.799):
only an accredited provider can certify an advanced electronic signature.
Refusing to start is what keeps it out of production, so this runs before any
other setting is read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ImproperlyConfigured

if TYPE_CHECKING:
    from collections.abc import Mapping

AMBIENTES_PERMITIDOS = frozenset({"local", "test", "ci"})
VERDADERO = frozenset({"1", "true", "yes", "on"})


def exigir_ambiente_de_pruebas(entorno: Mapping[str, str]) -> str:
    """Return the environment name, or refuse to start.

    Raises:
        ImproperlyConfigured: The development flag is missing, the
            environment is not a development one, or the CRM's production
            settings are active in this process.
    """
    if entorno.get("FIRMA_SANDBOX_ENABLED", "").strip().lower() not in VERDADERO:
        msg = (
            "The test signature service is off. It runs only in development: set "
            "FIRMA_SANDBOX_ENABLED=true (see .envs.example/.local/.firma)."
        )
        raise ImproperlyConfigured(msg)

    ambiente = entorno.get("FIRMA_SANDBOX_ENV", "").strip().lower()
    if ambiente not in AMBIENTES_PERMITIDOS:
        msg = (
            f"FIRMA_SANDBOX_ENV={ambiente!r} is not allowed. The test signature "
            f"service runs only in {sorted(AMBIENTES_PERMITIDOS)}."
        )
        raise ImproperlyConfigured(msg)

    modulo = entorno.get("DJANGO_SETTINGS_MODULE", "")
    if "production" in modulo or entorno.get("DJANGO_ENV", "") == "production":
        msg = "The test signature service refuses to start with production settings."
        raise ImproperlyConfigured(msg)

    return ambiente

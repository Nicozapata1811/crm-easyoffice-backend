"""Service and plan catalogue, read from ``settings.CATALOGO_SERVICIOS``.

A stand-in until ``TipoTramite`` exists; callers go through these functions so
the source can change without touching them.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from django.conf import settings

ORIGEN_ENLACE_SITIO = "sitio"


def listar_servicios() -> list[dict[str, Any]]:
    return settings.CATALOGO_SERVICIOS


def buscar_servicio(slug: str) -> dict[str, Any] | None:
    return next((s for s in listar_servicios() if s["slug"] == slug), None)


def buscar_plan(servicio_slug: str, plan_slug: str) -> dict[str, Any] | None:
    servicio = buscar_servicio(servicio_slug)
    if servicio is None:
        return None
    return next((p for p in servicio["planes"] if p["slug"] == plan_slug), None)


def enlace_portal(servicio_slug: str, plan_slug: str) -> str:
    """Deep link into the portal with the plan preselected."""
    query = urlencode({"plan": plan_slug, "origen": ORIGEN_ENLACE_SITIO})
    return f"{settings.PORTAL_BASE_URL.rstrip('/')}/{servicio_slug}?{query}"

"""Queries other apps may run against client records."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import Cliente

if TYPE_CHECKING:
    from datetime import date


def contar_clientes(desde: date, hasta: date) -> dict[str, int]:
    """Count clients for a period, with both bounds inclusive in local time.

    Args:
        desde: First day of the period.
        hasta: Last day of the period.

    Returns:
        ``total``, every client registered up to ``hasta``, and ``nuevos``,
        those registered within the period.
    """
    registrados = Cliente.objects.filter(created_at__date__lte=hasta)
    return {
        "total": registrados.count(),
        "nuevos": registrados.filter(created_at__date__gte=desde).count(),
    }

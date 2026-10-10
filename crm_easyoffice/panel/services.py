"""Operational dashboard indicators (RF-14, HU-41)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from crm_easyoffice.clientes.services import contar_clientes

from .ejemplo import CLAVES_DE_EJEMPLO
from .ejemplo import indicadores_de_ejemplo

if TYPE_CHECKING:
    from datetime import date


def calcular_indicadores(desde: date, hasta: date) -> dict[str, Any]:
    """Return the RF-14 indicators for a period, both bounds inclusive.

    Client counts are real. The keys listed in ``datos_de_ejemplo`` hold
    example figures until the system records services, sales and documents.
    """
    return {
        "periodo": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},
        "clientes": contar_clientes(desde, hasta),
        **indicadores_de_ejemplo(desde, hasta),
        "datos_de_ejemplo": list(CLAVES_DE_EJEMPLO),
    }

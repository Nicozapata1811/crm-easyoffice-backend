"""Operational dashboard indicators (RF-14, HU-41).

Each figure comes from the service functions of the app that owns the data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django.utils import timezone

from crm_easyoffice.clientes.services import contar_clientes
from crm_easyoffice.contratos.services import resumen_vencimientos
from crm_easyoffice.documentos.services import contar_pendientes_de_firma
from crm_easyoffice.tramites.services import pendientes_por_motivo
from crm_easyoffice.tramites.services import ventas_por_ejecutivo
from crm_easyoffice.ventas.services import total_vendido
from crm_easyoffice.ventas.services import ventas_pagadas
from crm_easyoffice.ventas.services import ventas_por_servicio

if TYPE_CHECKING:
    from datetime import date

    from django.db.models import QuerySet

    from crm_easyoffice.ventas.models import Venta

# ASSUMPTION: pending validation with Easy Office. HU-42 proposes 60, 30, 15
# and 7 days of notice; the dashboard counts the 30-day window.
DIAS_AVISO = 30
EN_LINEA = "En línea (sin ejecutivo)"


def fecha_referencia(hasta: date, hoy: date | None = None) -> date:
    """The day point-in-time figures are read at: ``hasta``, or today if later."""
    return min(hasta, hoy or timezone.localdate())


def _por_ejecutivo(ventas: QuerySet[Venta]) -> list[dict[str, Any]]:
    """Sales per executive, with the sales that have none grouped last."""
    filas = ventas_por_ejecutivo(ventas)
    con_ejecutivo = [fila for fila in filas if fila["ejecutivo"] is not None]
    sin_ejecutivo = [
        {**fila, "ejecutivo": EN_LINEA} for fila in filas if fila["ejecutivo"] is None
    ]
    return con_ejecutivo + sin_ejecutivo


def calcular_indicadores(
    desde: date,
    hasta: date,
    *,
    hoy: date | None = None,
) -> dict[str, Any]:
    """Return the RF-14 indicators for a period, both bounds inclusive.

    Client counts and sales cover the period. Contracts, pending cases and
    documents waiting for a signature are read at ``fecha_referencia``.

    ``datos_de_ejemplo`` is always empty now that every figure is real.
    It stays in the payload for one release so clients reading it keep
    working; remove it afterwards.
    """
    referencia = fecha_referencia(hasta, hoy)
    ventas = ventas_pagadas(desde, hasta)
    motivos = pendientes_por_motivo(referencia)
    return {
        "periodo": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},
        "fecha_referencia": referencia.isoformat(),
        "clientes": contar_clientes(desde, hasta),
        "servicios": {
            **resumen_vencimientos(referencia, DIAS_AVISO),
            "dias_aviso": DIAS_AVISO,
        },
        "ventas": {
            "moneda": "CLP",
            "total": total_vendido(ventas),
            "por_servicio": ventas_por_servicio(ventas),
            "por_ejecutivo": _por_ejecutivo(ventas),
        },
        "tramites_pendientes": sum(fila["cantidad"] for fila in motivos),
        "tramites_pendientes_por_motivo": motivos,
        "documentos_pendientes_firma": contar_pendientes_de_firma(referencia),
        "datos_de_ejemplo": [],
    }

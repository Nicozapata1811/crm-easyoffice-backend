"""Example figures for the indicators whose data the system does not hold yet.

Services, sales, trámites and documents have no models until HU-10, HU-48 and
the documentos app land. Figures are deterministic per period. Prices are
examples, not confirmed by Easy Office.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from datetime import date

CLAVES_DE_EJEMPLO = [
    "servicios",
    "ventas",
    "tramites_pendientes",
    "documentos_pendientes_firma",
]

SERVICIOS = [
    ("Domicilio tributario", 45_000, 22),
    ("Declaración jurada", 18_000, 12),
    ("Contrato de arriendo", 60_000, 7),
]
EJECUTIVOS = [
    ("Ejecutivo/a de ejemplo 1", 0.45),
    ("Ejecutivo/a de ejemplo 2", 0.35),
    ("Ejecutivo/a de ejemplo 3", 0.2),
]
# ASSUMPTION: pending validation with Easy Office. HU-42 proposes 60, 30, 15
# and 7 days of notice; the dashboard counts the 30-day window.
DIAS_AVISO = 30


def _variacion(semilla: str) -> float:
    """Deterministic factor in [0.8, 1.2) for a seed string."""
    valor = 0
    for caracter in semilla:
        valor = (valor * 31 + ord(caracter)) % 2**32
    return 0.8 + (valor % 1000) / 2500


def _redondear(valor: float) -> int:
    return math.floor(valor + 0.5)


def _repartir(total: int, participaciones: list[float]) -> list[int]:
    """Split ``total`` by shares so the parts add up to it exactly."""
    partes = [math.floor(total * participacion) for participacion in participaciones]
    partes[-1] += total - sum(partes)
    return partes


def indicadores_de_ejemplo(desde: date, hasta: date) -> dict[str, Any]:
    meses = ((hasta - desde).days + 1) / 30
    clave = f"{desde.isoformat()}:{hasta.isoformat()}"

    por_servicio: list[dict[str, Any]] = []
    for servicio, precio, por_mes in SERVICIOS:
        cantidad = max(1, _redondear(por_mes * meses * _variacion(clave + servicio)))
        por_servicio.append(
            {"servicio": servicio, "monto": cantidad * precio, "cantidad": cantidad},
        )
    total = sum(fila["monto"] for fila in por_servicio)
    cantidad_total = sum(fila["cantidad"] for fila in por_servicio)
    participaciones = [participacion for _, participacion in EJECUTIVOS]
    montos = _repartir(total, participaciones)
    cantidades = _repartir(cantidad_total, participaciones)

    return {
        "servicios": {
            "activos": 96,
            "por_vencer": 7,
            "vencidos": 4,
            "dias_aviso": DIAS_AVISO,
        },
        "ventas": {
            "moneda": "CLP",
            "total": total,
            "por_servicio": por_servicio,
            "por_ejecutivo": [
                {"ejecutivo": ejecutivo, "monto": monto, "cantidad": cantidad}
                for (ejecutivo, _), monto, cantidad in zip(
                    EJECUTIVOS,
                    montos,
                    cantidades,
                    strict=True,
                )
            ],
        },
        "tramites_pendientes": 18,
        "documentos_pendientes_firma": 6,
    }

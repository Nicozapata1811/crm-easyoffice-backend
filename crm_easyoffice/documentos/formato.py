"""How values print in Easy Office's contracts, following their samples."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

MESES = [
    "ENERO",
    "FEBRERO",
    "MARZO",
    "ABRIL",
    "MAYO",
    "JUNIO",
    "JULIO",
    "AGOSTO",
    "SEPTIEMBRE",
    "OCTUBRE",
    "NOVIEMBRE",
    "DICIEMBRE",
]

PREFIJO_REGION = re.compile(r"^regi[oó]n\s+(de\s+(la\s+)?|del\s+)?", re.IGNORECASE)


def rut(valor: str) -> str:
    """``12345678-5`` → ``12.345.678-5``."""
    cuerpo, _, dv = valor.partition("-")
    return f"{int(cuerpo):,}".replace(",", ".") + f"-{dv.upper()}"


def fecha_larga(valor: date) -> str:
    """``2026-01-15`` → ``15 DE ENERO DE 2026``."""
    return f"{valor.day:02d} DE {MESES[valor.month - 1]} DE {valor.year}"


def pesos(valor: Decimal) -> str:
    """``59990`` → ``59.990`` (the template prints the "$")."""
    return f"{int(valor):,}".replace(",", ".")


def mayusculas(valor: str) -> str:
    return valor.strip().upper()


def region(valor: str) -> str:
    """The region as the template expects it after "región".

    ``Región Metropolitana de Santiago`` → ``METROPOLITANA DE SANTIAGO``,
    ``Región de Valparaíso`` → ``VALPARAÍSO``.

    ASSUMPTION: pending validation with Easy Office. The samples print the
    region's short name.
    """
    return mayusculas(PREFIJO_REGION.sub("", valor.strip()))

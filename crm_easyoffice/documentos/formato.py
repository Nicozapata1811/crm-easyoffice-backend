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


def _meses(meses: int) -> str:
    return "MES" if meses == 1 else "MESES"


def duracion(meses: int) -> str:
    """``12`` → ``(12 MESES)``; ``1`` → ``(1 MES)``."""
    return f"({meses} {_meses(meses)})"


UNIDADES = [
    "",
    "UN",
    "DOS",
    "TRES",
    "CUATRO",
    "CINCO",
    "SEIS",
    "SIETE",
    "OCHO",
    "NUEVE",
    "DIEZ",
    "ONCE",
    "DOCE",
    "TRECE",
    "CATORCE",
    "QUINCE",
    "DIECISÉIS",
    "DIECISIETE",
    "DIECIOCHO",
    "DIECINUEVE",
    "VEINTE",
    "VEINTIÚN",
    "VEINTIDÓS",
    "VEINTITRÉS",
    "VEINTICUATRO",
    "VEINTICINCO",
    "VEINTISÉIS",
    "VEINTISIETE",
    "VEINTIOCHO",
    "VEINTINUEVE",
]
# Tens from 30 on; below 30 Spanish writes one word (UNIDADES).
DECENAS = {
    3: "TREINTA",
    4: "CUARENTA",
    5: "CINCUENTA",
    6: "SESENTA",
    7: "SETENTA",
    8: "OCHENTA",
    9: "NOVENTA",
}


def en_letras(numero: int) -> str:
    """``12`` → ``DOCE``, ``36`` → ``TREINTA Y SEIS``, before a noun (``UN``).

    Raises:
        ValueError: Outside 1 … 99, which no contract term reaches.
    """
    if not 1 <= numero <= 99:  # noqa: PLR2004
        msg = f"{numero} is outside 1 … 99"
        raise ValueError(msg)
    if numero < len(UNIDADES):
        return UNIDADES[numero]
    decena, unidad = divmod(numero, 10)
    return f"{DECENAS[decena]} Y {UNIDADES[unidad]}" if unidad else DECENAS[decena]


def duracion_en_letras(meses: int) -> str:
    """``12`` → ``DOCE (12) MESES``, as PLT-02's authorisation writes it."""
    return f"{en_letras(meses)} ({meses}) {_meses(meses)}"


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

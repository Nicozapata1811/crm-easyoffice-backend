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


CENTENAS = {
    1: "CIENTO",
    2: "DOSCIENTOS",
    3: "TRESCIENTOS",
    4: "CUATROCIENTOS",
    5: "QUINIENTOS",
    6: "SEISCIENTOS",
    7: "SETECIENTOS",
    8: "OCHOCIENTOS",
    9: "NOVECIENTOS",
}
MAX_MONTO = 999_999_999
MIL = 1000
MILLON = 1_000_000


def _hasta_999(numero: int) -> str:
    """``100`` → ``CIEN``, ``121`` → ``CIENTO VEINTIÚN``, ``0`` → ``""``."""
    centena, resto = divmod(numero, 100)
    if centena == 1 and resto == 0:
        return "CIEN"
    partes = [CENTENAS[centena]] if centena else []
    if resto:
        partes.append(en_letras(resto))
    return " ".join(partes)


def monto_en_letras(monto: Decimal | int) -> str:
    """A whole amount before "pesos": ``30000`` → ``TREINTA MIL``.

    Apocopated as Spanish writes it before a masculine noun (``VEINTIÚN
    MIL``, ``UN MILLÓN``); round millions take ``DE`` (``DOS MILLONES DE``).

    Raises:
        ValueError: Outside 1 … 999.999.999.
    """
    numero = int(monto)
    if not 1 <= numero <= MAX_MONTO:
        msg = f"{numero} is outside 1 … {MAX_MONTO}"
        raise ValueError(msg)
    millones, resto = divmod(numero, MILLON)
    miles, unidades = divmod(resto, MIL)
    partes = []
    if millones:
        partes.append(
            "UN MILLÓN" if millones == 1 else f"{_hasta_999(millones)} MILLONES",
        )
    if miles:
        partes.append("MIL" if miles == 1 else f"{_hasta_999(miles)} MIL")
    if unidades:
        partes.append(_hasta_999(unidades))
    texto = " ".join(partes)
    return f"{texto} DE" if millones and not resto else texto


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

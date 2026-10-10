"""Amounts as providers send and expect them: whole CLP, sometimes as text."""

from __future__ import annotations

from decimal import Decimal
from decimal import InvalidOperation
from typing import Any

from .base import PaymentError


def a_entero(monto: Decimal) -> int:
    return int(monto.to_integral_value())


def a_decimal(valor: Any) -> Decimal | None:
    if isinstance(valor, dict):
        valor = valor.get("total")
    if valor in (None, ""):
        return None
    try:
        return Decimal(str(valor))
    except InvalidOperation as exc:
        msg = f"The provider sent an amount that is not a number: {valor!r}"
        raise PaymentError(msg) from exc

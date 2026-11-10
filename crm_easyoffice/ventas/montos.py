"""Net, VAT and total of a price. The one place that computes them."""

from __future__ import annotations

from decimal import ROUND_HALF_UP
from decimal import Decimal
from typing import NamedTuple

# Chile's VAT (IVA), DL 825.
TASA_IVA = Decimal("0.19")
PESO = Decimal(1)


class Desglose(NamedTuple):
    neto: Decimal
    iva: Decimal
    total: Decimal


def _pesos(valor: Decimal) -> Decimal:
    return valor.quantize(PESO, rounding=ROUND_HALF_UP)


def desglosar(precio: Decimal, *, incluye_iva: bool) -> Desglose:
    """Split ``precio`` into net, VAT and total, in whole pesos.

    A price that includes VAT is the total, and is never changed: its net is
    total / 1,19 rounded, and the VAT is the rest. A net price ("más IVA")
    adds 19 % rounded half up.
    """
    precio = Decimal(precio)
    if incluye_iva:
        neto = _pesos(precio / (1 + TASA_IVA))
        return Desglose(neto, precio - neto, precio)
    iva = _pesos(precio * TASA_IVA)
    return Desglose(precio, iva, precio + iva)

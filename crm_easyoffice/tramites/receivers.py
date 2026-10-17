"""Reactions to other apps' signals. Connected in TramitesConfig.ready."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from .services import registrar_pago

if TYPE_CHECKING:
    from crm_easyoffice.ventas.models import Venta


def al_pagar_venta(sender: type, venta: Venta, **kwargs: Any) -> None:
    registrar_pago(venta)

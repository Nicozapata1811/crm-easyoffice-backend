"""Reads other apps run against the issuing company's configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import ConfigEmpresa
from .models import CuentaPago
from .models import Marca

if TYPE_CHECKING:
    from django.db.models import QuerySet


class ConfiguracionIncompletaError(Exception):
    """Configuration a caller needs has not been entered in the admin."""


def obtener_config_empresa() -> ConfigEmpresa:
    """The issuing company's record.

    Raises:
        ConfiguracionIncompletaError: No record has been entered.
    """
    config = ConfigEmpresa.objects.select_related("representante").first()
    if config is None:
        msg = "Easy Office's company data has not been entered."
        raise ConfiguracionIncompletaError(msg)
    return config


def marcas_activas() -> QuerySet[Marca]:
    return Marca.objects.filter(activa=True).select_related("cuenta_pago_default")


def cuenta_pago_para(marca: Marca, cuenta: CuentaPago | None = None) -> CuentaPago:
    """The account a contract under ``marca`` is paid into.

    Args:
        marca: The contract's brand.
        cuenta: An explicit choice; the brand's default when omitted.

    Raises:
        ConfiguracionIncompletaError: The chosen account, or the brand's
            default when none is chosen, is missing or inactive.
    """
    elegida = cuenta or marca.cuenta_pago_default
    if elegida is None or not elegida.activa:
        msg = f"No active payment account for {marca}."
        raise ConfiguracionIncompletaError(msg)
    return elegida


def cuentas_pago_activas() -> QuerySet[CuentaPago]:
    return CuentaPago.objects.filter(activa=True)

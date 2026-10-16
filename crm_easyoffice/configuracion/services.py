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


def problemas_para_contrato(marca_nombre: str) -> list[str]:
    """What a contract under ``marca_nombre`` needs from configuration and lacks.

    Empty when Easy Office's data, its representative, the brand and the
    brand's default account are complete. The messages are for the
    executive who fills them in the admin.
    """
    problemas = []
    config = ConfigEmpresa.objects.select_related("representante").first()
    if config is None:
        problemas.append("Faltan los datos de Easy Office (configuración).")
    elif config.representante is None:
        problemas.append("Falta el representante legal de Easy Office.")
    else:
        persona = config.representante
        faltan = [
            nombre
            for nombre, valor in [
                ("RUT", persona.rut),
                ("nacionalidad", persona.nacionalidad),
                ("estado civil", persona.estado_civil),
                ("profesión", persona.profesion),
            ]
            if not valor
        ]
        if faltan:
            problemas.append(
                f"Faltan datos del representante de Easy Office: {', '.join(faltan)}.",
            )

    marca = (
        Marca.objects.select_related("cuenta_pago_default")
        .filter(nombre=marca_nombre)
        .first()
    )
    if marca is None or not marca.activa:
        problemas.append(f"La marca {marca_nombre} no existe o está inactiva.")
    else:
        cuenta = marca.cuenta_pago_default
        if cuenta is None or not cuenta.activa or not cuenta.texto_contrato:
            problemas.append(
                f"La marca {marca_nombre} no tiene una cuenta de pago activa con "
                "el texto que imprime el contrato.",
            )
    return problemas

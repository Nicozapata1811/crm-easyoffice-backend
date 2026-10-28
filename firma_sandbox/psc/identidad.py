"""The identity check before a certificate is issued.

A real provider checks the person against the civil registry, and often with
biometrics. Here a fictitious registry stands in for it; another verifier
(biometrics, say) plugs in through ``IDENTITY_VERIFIER``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from typing import Protocol

from django.conf import settings
from django.utils.module_loading import import_string

from .models import IdentidadFicticia

if TYPE_CHECKING:
    from .models import Firmante


def normalizar_rut(rut: str) -> str:
    """``12.345.678-k`` → ``12345678-K``."""
    limpio = re.sub(r"[^0-9kK]", "", rut).upper()
    return f"{limpio[:-1]}-{limpio[-1]}" if len(limpio) > 1 else limpio


def normalizar_serie(serie: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", serie).upper()


class IdentityVerifier(Protocol):
    def verificar(self, firmante: Firmante, datos: dict[str, str]) -> bool:
        """Whether ``datos`` prove the person is ``firmante``."""


class RegistroFicticio:
    """RUT and ID-card serial number, checked against ``IdentidadFicticia``."""

    def verificar(self, firmante: Firmante, datos: dict[str, str]) -> bool:
        rut = normalizar_rut(datos.get("rut", ""))
        if rut != normalizar_rut(firmante.rut):
            return False
        identidad = IdentidadFicticia.objects.filter(rut=rut).first()
        return identidad is not None and normalizar_serie(
            identidad.numero_serie,
        ) == normalizar_serie(
            datos.get("numero_serie", ""),
        )


def verificador() -> IdentityVerifier:
    return import_string(settings.IDENTITY_VERIFIER)()

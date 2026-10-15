"""Helpers for contract tests. Every value they produce is synthetic.

Contracts are built on the catalogue the migrations seed: branches LF, VL and
SA, brands EASY OFFICE and INOFFICE, and the form's services.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from typing import Any

from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.configuracion.models import Marca
from crm_easyoffice.contratos.services import LineaContrato
from crm_easyoffice.contratos.services import crear_contrato
from crm_easyoffice.inmuebles.models import Oficina
from crm_easyoffice.ventas.models import Servicio

if TYPE_CHECKING:
    from crm_easyoffice.contratos.models import Contrato

INICIO = date(2026, 10, 2)
EMISION = date(2026, 10, 14)


def sucursal(codigo: str = "LF") -> Oficina:
    return Oficina.objects.get(codigo_sucursal=codigo)


def marca(nombre: str = "EASY OFFICE") -> Marca:
    return Marca.objects.get(nombre=nombre)


def servicio(codigo: str = "domicilio-tributario") -> Servicio:
    return Servicio.objects.select_related("ciclo_pago_default").get(codigo=codigo)


def domicilio_en(codigo_sucursal: str = "LF") -> LineaContrato:
    return LineaContrato(servicio=servicio(), inmueble=sucursal(codigo_sucursal))


def nuevo_contrato(**datos: Any) -> Contrato:
    """A 12-month domicile contract at LF for a new natural-person client."""
    valores = {
        "cliente": ClienteFactory.create(),
        "marca": marca(),
        "lineas": [domicilio_en("LF")],
        "fecha_inicio": INICIO,
        "duracion_meses": 12,
        "fecha_emision": EMISION,
        **datos,
    }
    return crear_contrato(**valores)

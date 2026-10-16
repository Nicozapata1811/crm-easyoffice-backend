"""Helpers for case tests. Every value they produce is synthetic."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from typing import Any

from django.utils import timezone

from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.clientes.tests.factories import CuentaClienteFactory
from crm_easyoffice.clientes.tests.factories import EmpresaFactory
from crm_easyoffice.clientes.tests.factories import synthetic_rut
from crm_easyoffice.configuracion.tests.factories import preparar_config_contrato
from crm_easyoffice.inmuebles.tests.factories import preparar_sucursal_domicilio

if TYPE_CHECKING:
    from crm_easyoffice.clientes.models import CuentaCliente
    from crm_easyoffice.inmuebles.models import Oficina

RUT_REPRESENTANTE = synthetic_rut(32_111_222)


def preparar_domicilio(codigo: str = "LF", desde: date = date(2026, 1, 1)) -> Oficina:
    """Configuration and one branch ready for PLT-01. Returns the branch."""
    preparar_config_contrato()
    autorizante = preparar_sucursal_domicilio(codigo, desde)
    return autorizante.inmueble


def cuenta_empresa() -> CuentaCliente:
    """A portal account for a fictitious company client."""
    return CuentaClienteFactory.create(
        cliente=ClienteFactory.create(persona=None, empresa=EmpresaFactory.create()),
    )


def datos_domicilio(cliente, sucursal: Oficina, **extra: Any) -> dict[str, Any]:
    """The domicile form as the serializer leaves it (validated values)."""
    return {
        "empresa": {
            "rut": cliente.empresa.rut,
            "razon_social": "Comercial Ficticia del Sur SpA",
            "giro": "Venta al por menor de ejemplo",
        },
        "representante": {
            "rut": RUT_REPRESENTANTE,
            "nombres": "Camila Andrea",
            "apellido_paterno": "Ejemplo",
            "apellido_materno": "Prueba",
            "domicilio": "Pasaje de Prueba 123",
            "comuna": "Maipú",
            "region": "Región Metropolitana de Santiago",
        },
        "personeria": {
            "fecha_instrumento": date(2025, 12, 10),
            "sitio_o_notaria": "www.tuempresaenundia.cl",
        },
        "email_aviso": "contacto@empresa-ficticia.example",
        "movil_aviso": "912345678",
        "plan": "anual",
        "sucursal": sucursal.pk,
        "fecha_inicio": timezone.localdate(),
        **extra,
    }


def payload_domicilio(cliente, sucursal: Oficina, **extra: Any) -> dict[str, Any]:
    """The same form as the portal posts it (JSON)."""
    datos = datos_domicilio(cliente, sucursal, **extra)
    personeria = datos["personeria"]
    personeria["fecha_instrumento"] = str(personeria["fecha_instrumento"])
    datos["fecha_inicio"] = str(datos["fecha_inicio"])
    return datos

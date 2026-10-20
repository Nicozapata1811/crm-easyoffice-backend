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
from crm_easyoffice.tramites.models import EventoTramite
from crm_easyoffice.tramites.models import MotivoPendiente
from crm_easyoffice.tramites.models import TipoTramite
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.services import TIPO_DOMICILIO

if TYPE_CHECKING:
    from datetime import datetime

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


Paso = tuple["datetime", str, str | None]


def tramite_con_historia(*pasos: Paso, **campos: Any) -> Tramite:
    """A domicile case that went through ``pasos`` (when, estado, motivo), in order.

    Built directly, outside the flow, so each move can be dated: the case
    ends in the last step's state, and the history records every step.
    """
    _, estado, motivo = pasos[-1]
    campos.setdefault("cliente", ClienteFactory.create())
    tramite = Tramite.objects.create(
        tipo=TipoTramite.objects.get(codigo=TIPO_DOMICILIO),
        estado=estado,
        motivo=MotivoPendiente.objects.get(codigo=motivo) if motivo else None,
        **campos,
    )
    anterior: tuple[str, str] = ("", "")
    for fecha, estado_nuevo, motivo_nuevo in pasos:
        evento = EventoTramite.objects.create(
            tramite=tramite,
            estado_anterior=anterior[0],
            motivo_anterior=anterior[1],
            estado_nuevo=estado_nuevo,
            motivo_nuevo=motivo_nuevo or "",
        )
        EventoTramite.objects.filter(pk=evento.pk).update(fecha=fecha)
        anterior = (estado_nuevo, motivo_nuevo or "")
    return tramite

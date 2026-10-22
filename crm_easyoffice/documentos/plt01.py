"""The values PLT-01 prints, each from exactly one source.

Section A (what the client typed) comes from the contract and the client's
records; section B (filled by the system) from the contract, the contracted
services, the chosen branch, its current authoriser and Easy Office's
configuration. The paths are conversion.plt01.CAMPOS / MARCADORES; the parts
PLT-02 shares are built in documentos.comun.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from crm_easyoffice.configuracion.services import obtener_config_empresa
from crm_easyoffice.configuracion.services import problemas_para_contrato
from crm_easyoffice.inmuebles.services import autorizante_vigente
from crm_easyoffice.inmuebles.services import problemas_para_domicilio

from . import comun
from . import formato
from .comun import Contexto
from .comun import DatosIncompletosError

if TYPE_CHECKING:
    from crm_easyoffice.tramites.models import Tramite

PLANTILLA = "PLT-01"


def contexto(tramite: Tramite) -> Contexto:
    """Resolve every PLT-01 field for the case's draft contract.

    Raises:
        DatosIncompletosError: Something the document prints is missing; the
            messages are for the executive.
    """
    contrato = tramite.contrato
    servicios = comun.servicios_de(contrato)
    oficina = next((s.inmueble for s in servicios if s.inmueble), None)
    if oficina is None:
        raise DatosIncompletosError(["El contrato no tiene una sucursal."])

    problemas = [
        *problemas_para_domicilio(oficina, contrato.fecha_inicio),
        *problemas_para_contrato(contrato.marca.nombre),
        *comun.faltantes_cliente(contrato, PLANTILLA),
    ]
    if problemas:
        raise DatosIncompletosError(problemas)

    autorizante = autorizante_vigente(oficina, contrato.fecha_inicio)
    representante_autorizante = autorizante.representante.persona
    config = obtener_config_empresa()
    firmante = comun.persona(representante_autorizante)

    valores = {
        **comun.valores_contrato(contrato, servicios),
        "sucursal": {
            **comun.ubicacion(oficina),
            "rol": oficina.rol_avaluo,
            "unidad_sii": formato.mayusculas(oficina.unidad_sii),
            "municipalidad": formato.mayusculas(oficina.municipalidad),
        },
        **comun.valores_cliente(contrato),
        "eo": comun.valores_eo(config),
        "autorizante": {
            "razon_social": autorizante.empresa.razon_social,
            "rut": formato.rut(autorizante.empresa.rut),
            "representante": firmante["nombre"],
            "nacionalidad": firmante["nacionalidad"],
            "estado_civil": firmante["estado_civil"],
            "profesion": firmante["profesion"],
            "rut_representante": firmante["rut"],
        },
    }
    fuentes = {
        **comun.fuentes_comunes(tramite, contrato, servicios, config),
        "oficina": oficina.pk,
        "autorizante": autorizante.pk,
        "persona_autorizante": representante_autorizante.pk,
    }
    return Contexto(
        valores=valores,
        imagenes=comun.cedula(autorizante),
        fuentes=fuentes,
        firmantes=[
            (contrato.representante.persona, "cliente_representante"),
            (representante_autorizante, "autorizante"),
        ],
    )

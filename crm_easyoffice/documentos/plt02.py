"""The values PLT-02 prints, each from exactly one source.

The contract is PLT-01's: the client company, its representative and the
contracted services, the first of them at an Easy Office branch (PRIMERO and
the authorisation's place print that branch). The authorisation is the
warehouse's: its address, comuna, region and rol (OB-05), and its owner, a
natural person, with both sides of their identity card. The paths are
conversion.plt02.CAMPOS / MARCADORES; the shared parts come from
documentos.comun.

ASSUMPTION: pending validation with Easy Office. The warehouse sentence's
region is the warehouse's (the template merged the branch's, which matched
in its only sample), and the authorisation is dated at the branch's comuna.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from crm_easyoffice.configuracion.services import obtener_config_empresa
from crm_easyoffice.configuracion.services import problemas_para_contrato
from crm_easyoffice.inmuebles.models import TipoInmueble
from crm_easyoffice.inmuebles.services import autorizante_vigente
from crm_easyoffice.inmuebles.services import problemas_para_bodega
from crm_easyoffice.inmuebles.services import problemas_para_ubicar

from . import comun
from . import formato
from .comun import Contexto
from .comun import DatosIncompletosError

if TYPE_CHECKING:
    from crm_easyoffice.tramites.models import Tramite

PLANTILLA = "PLT-02"


def contexto(tramite: Tramite) -> Contexto:
    """Resolve every PLT-02 field for the case's draft contract.

    Raises:
        DatosIncompletosError: Something the document prints is missing; the
            messages are for the executive.
    """
    contrato = tramite.contrato
    servicios = comun.servicios_de(contrato)
    ubicados = [s.inmueble for s in servicios if s.inmueble]
    sucursal = next((i for i in ubicados if i.tipo == TipoInmueble.OFICINA), None)
    bodega = next((i for i in ubicados if i.tipo == TipoInmueble.BODEGA), None)
    faltan = [
        mensaje
        for mensaje, inmueble in [
            ("El contrato no tiene una sucursal.", sucursal),
            ("El contrato no tiene una bodega.", bodega),
        ]
        if inmueble is None
    ]
    if faltan:
        raise DatosIncompletosError(faltan)
    if ubicados[0] != sucursal:
        raise DatosIncompletosError(
            ["El primer servicio del contrato debe ser el de la sucursal."],
        )

    problemas = [
        *problemas_para_ubicar(sucursal, contrato.fecha_inicio),
        *problemas_para_bodega(bodega, contrato.fecha_inicio),
        *problemas_para_contrato(contrato.marca.nombre),
        *comun.faltantes_cliente(contrato, PLANTILLA),
    ]
    if problemas:
        raise DatosIncompletosError(problemas)

    autorizante = autorizante_vigente(bodega, contrato.fecha_inicio)
    dueno = autorizante.persona
    config = obtener_config_empresa()

    valores = {
        **comun.valores_contrato(contrato, servicios),
        "duracion_letras": formato.duracion_en_letras(contrato.duracion_meses),
        "sucursal": comun.ubicacion(sucursal),
        "bodega": {**comun.ubicacion(bodega), "rol": bodega.rol_avaluo},
        **comun.valores_cliente(contrato),
        "eo": comun.valores_eo(config),
        "autorizante": comun.persona(dueno),
    }
    fuentes = {
        **comun.fuentes_comunes(tramite, contrato, servicios, config),
        "oficina": sucursal.pk,
        "bodega": bodega.pk,
        "autorizante": autorizante.pk,
        "persona_autorizante": dueno.pk,
    }
    return Contexto(
        valores=valores,
        imagenes=comun.cedula(autorizante),
        fuentes=fuentes,
        firmantes=[
            (contrato.representante.persona, "cliente_representante"),
            (dueno, "autorizante"),
        ],
    )

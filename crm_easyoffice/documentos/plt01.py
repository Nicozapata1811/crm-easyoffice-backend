"""The values PLT-01 prints, each from exactly one source.

Section A (what the client typed) comes from the contract and the client's
records; section B (filled by the system) from the contract, the contracted
services, the chosen branch, its current authoriser and Easy Office's
configuration. The paths are conversion.plt01.CAMPOS / MARCADORES.

ASSUMPTION: pending validation with Easy Office. People's names, addresses,
comunas, regions, the giro and cycles print in upper case, as in the samples;
a razón social prints as registered (SpA, Ltda.), e-mails as typed.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Any

from crm_easyoffice.clientes.models import EstadoCivil
from crm_easyoffice.configuracion.services import obtener_config_empresa
from crm_easyoffice.configuracion.services import problemas_para_contrato
from crm_easyoffice.inmuebles.services import abrir_documento_identidad
from crm_easyoffice.inmuebles.services import autorizante_vigente
from crm_easyoffice.inmuebles.services import problemas_para_domicilio

from . import formato

if TYPE_CHECKING:
    from crm_easyoffice.clientes.models import Persona
    from crm_easyoffice.tramites.models import Tramite


class DatosIncompletosError(Exception):
    """The case lacks data the document prints; ``problemas`` says which."""

    def __init__(self, problemas: list[str]) -> None:
        super().__init__("; ".join(problemas))
        self.problemas = problemas


@dataclass
class Contexto:
    """What one PLT-01 needs: printed values, card images, and their sources."""

    valores: dict[str, Any]
    imagenes: dict[str, bytes]
    fuentes: dict[str, Any]
    firmantes: list[tuple[Persona, str]] = field(default_factory=list)


def _estado_civil(persona: Persona) -> str:
    return formato.mayusculas(str(EstadoCivil(persona.estado_civil).label))


def _persona(persona: Persona) -> dict[str, str]:
    return {
        "nombre": formato.mayusculas(persona.nombre_completo),
        "rut": formato.rut(persona.rut),
        "nacionalidad": formato.mayusculas(persona.nacionalidad),
        "estado_civil": _estado_civil(persona) if persona.estado_civil else "",
        "profesion": formato.mayusculas(persona.profesion),
    }


def _faltantes_cliente(contrato) -> list[str]:
    problemas = []
    empresa = contrato.cliente.empresa
    if empresa is None:
        return ["El contrato PLT-01 es para clientes empresa."]
    if not empresa.giro:
        problemas.append("Falta el giro de la empresa cliente.")
    representacion = contrato.representante
    if representacion is None:
        return [*problemas, "Falta el representante legal del cliente."]
    persona = representacion.persona
    faltan = [
        nombre
        for nombre, valor in [
            ("domicilio", persona.domicilio),
            ("comuna", persona.comuna),
            ("región", persona.region),
        ]
        if not valor
    ]
    if faltan:
        problemas.append(
            f"Faltan datos del representante del cliente: {', '.join(faltan)}.",
        )
    if representacion.fecha_instrumento is None or not representacion.sitio_o_notaria:
        problemas.append("Falta la personería del representante del cliente.")
    if not contrato.email_aviso or not contrato.movil_aviso:
        problemas.append("Falta el correo o el celular para notificaciones.")
    return problemas


def contexto(tramite: Tramite) -> Contexto:
    """Resolve every PLT-01 field for the case's draft contract.

    Raises:
        DatosIncompletosError: Something the document prints is missing; the
            messages are for the executive.
    """
    contrato = tramite.contrato
    servicios = list(
        contrato.servicios.select_related("ciclo_pago", "inmueble").order_by("orden"),
    )
    oficina = next((s.inmueble for s in servicios if s.inmueble), None)
    if oficina is None:
        raise DatosIncompletosError(["El contrato no tiene una sucursal."])

    problemas = [
        *problemas_para_domicilio(oficina, contrato.fecha_inicio),
        *problemas_para_contrato(contrato.marca.nombre),
        *_faltantes_cliente(contrato),
    ]
    if problemas:
        raise DatosIncompletosError(problemas)

    autorizante = autorizante_vigente(oficina, contrato.fecha_inicio)
    representante_autorizante = autorizante.representante.persona
    config = obtener_config_empresa()
    representacion = contrato.representante
    persona = representacion.persona
    empresa = contrato.cliente.empresa

    eo = _persona(config.representante)
    firmante = _persona(representante_autorizante)
    direccion = f"{oficina.calle} {oficina.numero}"
    if oficina.unidad:
        direccion = f"{direccion} {oficina.unidad}"

    valores = {
        "folio": contrato.folio,
        "fecha_inicio": formato.fecha_larga(contrato.fecha_inicio),
        "duracion": f"({contrato.duracion_meses} MESES)",
        "vencimiento": formato.fecha_larga(contrato.fecha_vencimiento),
        "bancolink": contrato.cuenta_pago.texto_contrato,
        "sucursal": {
            "direccion": formato.mayusculas(direccion),
            "comuna": formato.mayusculas(oficina.comuna),
            "region": formato.region(oficina.region),
            "rol": oficina.rol_avaluo,
            "unidad_sii": formato.mayusculas(oficina.unidad_sii),
            "municipalidad": formato.mayusculas(oficina.municipalidad),
        },
        "empresa": {
            "razon_social": empresa.razon_social,
            "rut": formato.rut(empresa.rut),
            "giro": formato.mayusculas(empresa.giro),
        },
        "representante": {
            "nombre": formato.mayusculas(persona.nombre_completo),
            "rut": formato.rut(persona.rut),
            "domicilio": formato.mayusculas(persona.domicilio),
            "comuna": formato.mayusculas(persona.comuna),
            "region": formato.region(persona.region),
        },
        "personeria": {
            "fecha": formato.fecha_larga(representacion.fecha_instrumento),
            "sitio": representacion.sitio_o_notaria,
        },
        "aviso": {"mail": contrato.email_aviso, "celular": contrato.movil_aviso},
        "servicios": [
            {
                "nombre": formato.mayusculas(servicio.nombre),
                "precio": formato.pesos(servicio.precio),
                "ciclo": formato.mayusculas(servicio.ciclo_pago.nombre),
                "descripcion": servicio.descripcion,
            }
            for servicio in servicios
        ],
        "eo": {
            "representante": eo["nombre"],
            "nacionalidad": eo["nacionalidad"],
            "estado_civil": eo["estado_civil"],
            "profesion": eo["profesion"],
            "rut": eo["rut"],
        },
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

    with abrir_documento_identidad(autorizante) as anverso:
        imagen_anverso = anverso.read()
    with abrir_documento_identidad(autorizante, reverso=True) as reverso:
        imagen_reverso = reverso.read()

    fuentes = {
        "tramite": tramite.pk,
        "contrato": contrato.pk,
        "servicios_contratados": [servicio.pk for servicio in servicios],
        "cliente": contrato.cliente_id,
        "empresa": empresa.pk,
        "representante_legal": representacion.pk,
        "persona_representante": persona.pk,
        "cuenta_pago": contrato.cuenta_pago_id,
        "oficina": oficina.pk,
        "autorizante": autorizante.pk,
        "persona_autorizante": representante_autorizante.pk,
        "config_empresa": config.pk,
        "persona_easy_office": config.representante_id,
    }
    return Contexto(
        valores=valores,
        imagenes={"cedula_anverso": imagen_anverso, "cedula_reverso": imagen_reverso},
        fuentes=fuentes,
        firmantes=[
            (persona, "cliente_representante"),
            (representante_autorizante, "autorizante"),
        ],
    )

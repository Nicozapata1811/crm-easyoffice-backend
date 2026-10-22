"""Context parts shared by Easy Office's service contracts (PLT-01, PLT-02).

Both contracts print the same contract data, the same client company and
its representative, the same notice contact, the same services and Easy
Office's representative. Each template's own module (plt01, plt02) adds the
properties and the authoriser it prints. Every value has exactly one source,
recorded in ``fuentes``.

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
from crm_easyoffice.inmuebles.services import abrir_documento_identidad

from . import formato

if TYPE_CHECKING:
    from crm_easyoffice.clientes.models import Persona
    from crm_easyoffice.configuracion.models import ConfigEmpresa
    from crm_easyoffice.contratos.models import Contrato
    from crm_easyoffice.contratos.models import ServicioContratado
    from crm_easyoffice.inmuebles.models import Autorizante
    from crm_easyoffice.inmuebles.models import Oficina
    from crm_easyoffice.tramites.models import Tramite


class DatosIncompletosError(Exception):
    """The case lacks data the document prints; ``problemas`` says which."""

    def __init__(self, problemas: list[str]) -> None:
        super().__init__("; ".join(problemas))
        self.problemas = problemas


@dataclass
class Contexto:
    """What one document needs: printed values, card images, and their sources."""

    valores: dict[str, Any]
    imagenes: dict[str, bytes]
    fuentes: dict[str, Any]
    firmantes: list[tuple[Persona, str]] = field(default_factory=list)


def _estado_civil(persona: Persona) -> str:
    return formato.mayusculas(str(EstadoCivil(persona.estado_civil).label))


def persona(registro: Persona) -> dict[str, str]:
    """A person as the contracts introduce them: name, RUT, civil data."""
    return {
        "nombre": formato.mayusculas(registro.nombre_completo),
        "rut": formato.rut(registro.rut),
        "nacionalidad": formato.mayusculas(registro.nacionalidad),
        "estado_civil": _estado_civil(registro) if registro.estado_civil else "",
        "profesion": formato.mayusculas(registro.profesion),
    }


def servicios_de(contrato: Contrato) -> list[ServicioContratado]:
    return list(
        contrato.servicios.select_related("ciclo_pago", "inmueble").order_by("orden"),
    )


def faltantes_cliente(contrato: Contrato, plantilla: str) -> list[str]:
    """What the contract prints about the client company and is missing."""
    problemas = []
    empresa = contrato.cliente.empresa
    if empresa is None:
        return [f"El contrato {plantilla} es para clientes empresa."]
    if not empresa.giro:
        problemas.append("Falta el giro de la empresa cliente.")
    representacion = contrato.representante
    if representacion is None:
        return [*problemas, "Falta el representante legal del cliente."]
    registro = representacion.persona
    faltan = [
        nombre
        for nombre, valor in [
            ("domicilio", registro.domicilio),
            ("comuna", registro.comuna),
            ("región", registro.region),
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


def direccion(inmueble: Oficina) -> str:
    texto = f"{inmueble.calle} {inmueble.numero}"
    if inmueble.unidad:
        texto = f"{texto} {inmueble.unidad}"
    return formato.mayusculas(texto)


def ubicacion(inmueble: Oficina) -> dict[str, str]:
    """A property's address, comuna and region, as the contracts print them."""
    return {
        "direccion": direccion(inmueble),
        "comuna": formato.mayusculas(inmueble.comuna),
        "region": formato.region(inmueble.region),
    }


def valores_contrato(
    contrato: Contrato,
    servicios: list[ServicioContratado],
) -> dict[str, Any]:
    """Folio, term, payment account and the contracted services."""
    return {
        "folio": contrato.folio,
        "fecha_inicio": formato.fecha_larga(contrato.fecha_inicio),
        "duracion": formato.duracion(contrato.duracion_meses),
        "vencimiento": formato.fecha_larga(contrato.fecha_vencimiento),
        "bancolink": contrato.cuenta_pago.texto_contrato,
        "servicios": [
            {
                "nombre": formato.mayusculas(servicio.nombre),
                "precio": formato.pesos(servicio.precio),
                "ciclo": formato.mayusculas(servicio.ciclo_pago.nombre),
                "descripcion": servicio.descripcion,
            }
            for servicio in servicios
        ],
    }


def valores_cliente(contrato: Contrato) -> dict[str, Any]:
    """The client company, its representative, personería and notice contact."""
    representacion = contrato.representante
    registro = representacion.persona
    empresa = contrato.cliente.empresa
    return {
        "empresa": {
            "razon_social": empresa.razon_social,
            "rut": formato.rut(empresa.rut),
            "giro": formato.mayusculas(empresa.giro),
        },
        "representante": {
            "nombre": formato.mayusculas(registro.nombre_completo),
            "rut": formato.rut(registro.rut),
            "domicilio": formato.mayusculas(registro.domicilio),
            "comuna": formato.mayusculas(registro.comuna),
            "region": formato.region(registro.region),
        },
        "personeria": {
            "fecha": formato.fecha_larga(representacion.fecha_instrumento),
            "sitio": representacion.sitio_o_notaria,
        },
        "aviso": {"mail": contrato.email_aviso, "celular": contrato.movil_aviso},
    }


def valores_eo(config: ConfigEmpresa) -> dict[str, str]:
    """Easy Office's representative."""
    eo = persona(config.representante)
    return {
        "representante": eo["nombre"],
        "nacionalidad": eo["nacionalidad"],
        "estado_civil": eo["estado_civil"],
        "profesion": eo["profesion"],
        "rut": eo["rut"],
    }


def cedula(autorizante: Autorizante) -> dict[str, bytes]:
    """Both sides of the authoriser's identity card, as the images print them."""
    with abrir_documento_identidad(autorizante) as anverso:
        imagen_anverso = anverso.read()
    with abrir_documento_identidad(autorizante, reverso=True) as reverso:
        imagen_reverso = reverso.read()
    return {"cedula_anverso": imagen_anverso, "cedula_reverso": imagen_reverso}


def fuentes_comunes(
    tramite: Tramite,
    contrato: Contrato,
    servicios: list[ServicioContratado],
    config: ConfigEmpresa,
) -> dict[str, Any]:
    """The ids of the records behind the shared values."""
    representacion = contrato.representante
    return {
        "tramite": tramite.pk,
        "contrato": contrato.pk,
        "servicios_contratados": [servicio.pk for servicio in servicios],
        "cliente": contrato.cliente_id,
        "empresa": contrato.cliente.empresa_id,
        "representante_legal": representacion.pk,
        "persona_representante": representacion.persona_id,
        "cuenta_pago": contrato.cuenta_pago_id,
        "config_empresa": config.pk,
        "persona_easy_office": config.representante_id,
    }

"""The values PLT-03 prints, each from exactly one source.

A vehicle lease between the vehicle's owner (the lessor) and the client
company (the lessee), signed by the owner and the company's representative.
Easy Office is not a party and never signs it (OB-06), and the document
carries no folio. The parties come from the client records; the vehicle and
the lease terms from the case (``Tramite.datos``, written by
tramites.formularios.plt03). The paths are conversion.plt03.MARCADORES.

ASSUMPTION: pending validation with Easy Office. Names, addresses, comunas,
dates and amounts in words print in upper case, as in the service contracts'
samples; the razón social prints as registered.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from crm_easyoffice.clientes.models import Persona
from crm_easyoffice.clientes.models import RepresentanteLegal
from crm_easyoffice.tramites.formularios import plt03 as formulario

from . import formato
from .comun import Contexto
from .comun import DatosIncompletosError
from .models import Firmante

if TYPE_CHECKING:
    from crm_easyoffice.tramites.models import Tramite

PLANTILLA = "PLT-03"


def _domicilio(persona: Persona) -> str:
    """Street and comuna, as "domiciliado/a en" introduces them."""
    return formato.mayusculas(f"{persona.domicilio}, {persona.comuna}")


def _problemas(
    arrendador: Persona | None,
    representacion: RepresentanteLegal | None,
) -> list[str]:
    problemas = []
    if arrendador is None:
        problemas.append("El arrendador del vehículo ya no está registrado.")
    elif not (arrendador.domicilio and arrendador.comuna):
        problemas.append("Al arrendador le falta el domicilio o la comuna.")
    if representacion is None or not representacion.activo:
        problemas.append("La empresa no tiene vigente al representante del trámite.")
    return problemas


def contexto(tramite: Tramite) -> Contexto:
    """Resolve every PLT-03 field for the case.

    Raises:
        DatosIncompletosError: A party is missing, or lacks what the lease
            prints.
    """
    datos = tramite.datos
    empresa = tramite.cliente.empresa
    if empresa is None:
        raise DatosIncompletosError(["El cliente del arriendo no es una empresa."])
    arrendador = Persona.objects.filter(pk=datos.get("arrendador")).first()
    representacion = (
        RepresentanteLegal.objects.select_related("persona")
        .filter(pk=datos.get("representante"), empresa=empresa)
        .first()
    )
    if problemas := _problemas(arrendador, representacion):
        raise DatosIncompletosError(problemas)
    representante = representacion.persona
    vehiculo = datos["vehiculo"]

    return Contexto(
        valores={
            "comuna": formato.mayusculas(datos["comuna"]),
            "fecha": formato.fecha_larga(date.fromisoformat(datos["fecha"])),
            "arrendador": {
                "nombre": formato.mayusculas(arrendador.nombre_completo),
                "rut": formato.rut(arrendador.rut),
                "domicilio": _domicilio(arrendador),
            },
            "empresa": {
                "razon_social": empresa.razon_social,
                "rut": formato.rut(empresa.rut),
                "domicilio": formato.mayusculas(datos["domicilio_empresa"]),
            },
            "representante": {
                "nombre": formato.mayusculas(representante.nombre_completo),
                "rut": formato.rut(representante.rut),
            },
            "vehiculo": {
                "marca": formato.mayusculas(vehiculo["marca"]),
                "modelo": formato.mayusculas(vehiculo["modelo"]),
                "anio": str(vehiculo["anio"]),
                "patente": vehiculo["patente"],
                "color": formato.mayusculas(vehiculo["color"]),
                "vin": vehiculo["vin"],
            },
            "plazo": formato.duracion_en_letras(datos["plazo_meses"]),
            "fecha_inicio": formato.fecha_larga(
                date.fromisoformat(datos["fecha_inicio"]),
            ),
            "fecha_termino": formato.fecha_larga(formulario.fecha_termino(datos)),
            "renta": formato.pesos(datos["renta"]),
            "renta_letras": formato.monto_en_letras(datos["renta"]),
            "dia_pago": str(datos["dia_pago"]),
            "medio_pago": formulario.medio_pago(datos),
        },
        imagenes={},
        fuentes={
            "tramite": tramite.pk,
            "cliente": tramite.cliente_id,
            "empresa": empresa.pk,
            "representante_legal": representacion.pk,
            "persona_representante": representante.pk,
            "persona_arrendador": arrendador.pk,
        },
        firmantes=[
            (arrendador, Firmante.Rol.ARRENDADOR),
            (representante, Firmante.Rol.CLIENTE_REPRESENTANTE),
        ],
    )

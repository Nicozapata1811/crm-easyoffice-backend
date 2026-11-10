"""The vehicle lease's request form (PLT-03).

A person leases their own vehicle to their company (the client): to accredit
a vehicle for a transport business line, or to move the car's expenses to
the company. Easy Office is not a party (OB-06). The owner is often the
company's own representative: the same Persona serves both.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from typing import Any

from django.utils import timezone
from rest_framework import serializers

from crm_easyoffice.clientes.models import Persona
from crm_easyoffice.clientes.models import RepresentanteLegal
from crm_easyoffice.clientes.services import datos_contratante
from crm_easyoffice.clientes.services import guardar_datos_contratante
from crm_easyoffice.clientes.services import representacion_vigente
from crm_easyoffice.contratos.services import calcular_vencimiento
from crm_easyoffice.tramites.api.contratante import EmpresaContratanteSerializer
from crm_easyoffice.tramites.api.contratante import PersoneriaSerializer
from crm_easyoffice.tramites.api.contratante import RepresentanteContratanteSerializer

from . import comun

if TYPE_CHECKING:
    from crm_easyoffice.clientes.models import Cliente
    from crm_easyoffice.tramites.models import Tramite

PLANTILLA = "PLT-03"

TRANSFERENCIA = "transferencia"
OTRO = "otro"
MEDIOS_PAGO = {TRANSFERENCIA: "transferencia bancaria"}

PRIMER_ANIO = 1900
# ASSUMPTION: pending validation with Easy Office. Rent is due within the
# first N days of each month; 28 keeps N valid in every month.
MAX_DIA_PAGO = 28

FALTA_MEDIO = "Escribe el medio de pago."
VIN_INVALIDO = "Escribe el VIN o número de chasis: 5 a 17 letras y números."

# ``datos`` paths that identify the vehicle or a place, or hold free text,
# and how migracion.anonimizacion replaces each.
CLAVES_SENSIBLES = {
    "domicilio_empresa": "direccion",
    "vehiculo.patente": "patente",
    "vehiculo.vin": "vin",
    "medio_pago_otro": "texto",
}
# The rest of ``datos``: record ids, choices, dates, amounts and the
# vehicle's make. A test fails when a path is in neither.
CLAVES_CONSERVADAS = {
    "personas",
    "arrendador",
    "representante",
    "comuna",
    "fecha",
    "vehiculo.marca",
    "vehiculo.modelo",
    "vehiculo.anio",
    "vehiculo.color",
    "plazo_meses",
    "fecha_inicio",
    "renta",
    "dia_pago",
    "medio_pago",
}

# What the case keeps besides its people, as the form sent it.
CLAVES_DEL_FORMULARIO = (
    "domicilio_empresa",
    "comuna",
    "fecha",
    "vehiculo",
    "plazo_meses",
    "fecha_inicio",
    "renta",
    "dia_pago",
    "medio_pago",
    "medio_pago_otro",
)


class RepresentanteSerializer(RepresentanteContratanteSerializer):
    email = serializers.EmailField(required=False, allow_blank=True, default="")


class VehiculoSerializer(serializers.Serializer):
    marca = serializers.CharField(max_length=60)
    modelo = serializers.CharField(max_length=60)
    anio = serializers.IntegerField(min_value=PRIMER_ANIO)
    patente = comun.PatenteField(max_length=10)
    color = serializers.CharField(max_length=40)
    # ASSUMPTION: pending validation with Easy Office. The template asks
    # "VIN/Chasis": a VIN has 17 characters, older chassis numbers fewer.
    vin = serializers.RegexField(
        r"^[A-Za-z0-9]{5,17}$",
        error_messages={"invalid": VIN_INVALIDO},
    )

    def validate_anio(self, valor: int) -> int:
        tope = timezone.localdate().year + 1
        if valor > tope:
            raise serializers.ValidationError(f"El año no puede pasar de {tope}.")
        return valor

    def validate_vin(self, valor: str) -> str:
        return valor.upper()


class Serializer(serializers.Serializer):
    """A vehicle lease request an executive files or edits for a company."""

    empresa = EmpresaContratanteSerializer()
    representante = RepresentanteSerializer()
    personeria = PersoneriaSerializer()
    arrendador = comun.PersonaSerializer()
    # ASSUMPTION: pending validation with Easy Office. Our records hold no
    # company address (OB-17); the lease prints the one typed here.
    domicilio_empresa = serializers.CharField(max_length=255)
    comuna = serializers.CharField(max_length=100)
    fecha = serializers.DateField(required=False)
    vehiculo = VehiculoSerializer()
    plazo_meses = serializers.IntegerField(min_value=1, max_value=comun.MAX_MESES)
    fecha_inicio = serializers.DateField()
    renta = serializers.IntegerField(min_value=1, max_value=comun.MAX_MONTO)
    dia_pago = serializers.IntegerField(min_value=1, max_value=MAX_DIA_PAGO)
    medio_pago = serializers.ChoiceField(choices=[TRANSFERENCIA, OTRO])
    medio_pago_otro = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
    )

    def validate_fecha(self, valor: date) -> date:
        return comun.fecha_documento(valor)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs.setdefault("fecha", timezone.localdate())
        if attrs["medio_pago"] == OTRO and not attrs["medio_pago_otro"].strip():
            raise serializers.ValidationError({"medio_pago_otro": FALTA_MEDIO})
        return attrs


def guardar(cliente: Cliente, datos: dict[str, Any]) -> dict[str, Any]:
    """Save the lease's parties; return what the case keeps.

    Raises:
        crm_easyoffice.clientes.services.RepresentanteNoDisponibleError: The
            representative's RUT is someone else's record.
        comun.DatosDePersonaError: The owner is on record with other data.
    """
    representante = dict(datos["representante"])
    email = representante.pop("email", "")
    representacion = guardar_datos_contratante(
        cliente,
        empresa=datos["empresa"],
        representante=representante,
        personeria=datos["personeria"],
    )
    if email and representacion.persona.email != email:
        representacion.persona.email = email
        representacion.persona.save(update_fields=["email", "updated_at"])
    arrendador = comun.guardar_parte(cliente, "arrendador", datos["arrendador"])
    otro = datos["medio_pago"] == OTRO
    return {
        "personas": [arrendador.pk],
        "arrendador": arrendador.pk,
        "representante": representacion.pk,
        "domicilio_empresa": datos["domicilio_empresa"].strip(),
        "comuna": datos["comuna"].strip(),
        "fecha": datos["fecha"].isoformat(),
        "vehiculo": dict(datos["vehiculo"]),
        "plazo_meses": datos["plazo_meses"],
        "fecha_inicio": datos["fecha_inicio"].isoformat(),
        "renta": datos["renta"],
        "dia_pago": datos["dia_pago"],
        "medio_pago": datos["medio_pago"],
        "medio_pago_otro": datos["medio_pago_otro"].strip() if otro else "",
    }


def medio_pago(datos: dict[str, Any]) -> str:
    """How the rent is paid, as the lease prints it."""
    return MEDIOS_PAGO.get(datos["medio_pago"]) or datos["medio_pago_otro"]


def fecha_termino(datos: dict[str, Any]) -> date:
    """The lease's last day.

    ASSUMPTION: pending validation with Easy Office. Start + term − 1 day,
    as RN-37 sets for the service contracts.
    """
    return calcular_vencimiento(
        date.fromisoformat(datos["fecha_inicio"]),
        datos["plazo_meses"],
    )


def prefill(cliente: Cliente) -> dict[str, Any]:
    """Section A from the client's own records; the rest is typed."""
    datos = datos_contratante(cliente)
    representacion = representacion_vigente(cliente.empresa)
    datos["representante"]["email"] = (
        representacion.persona.email if representacion else ""
    )
    return datos


def valores(tramite: Tramite) -> dict[str, Any]:
    """A saved case as the form's payload, with its people as on record now."""
    datos = tramite.datos
    actuales = datos_contratante(tramite.cliente)
    representacion = (
        RepresentanteLegal.objects.select_related("persona")
        .filter(pk=datos["representante"])
        .first()
    )
    if representacion is not None:
        actuales["representante"] = comun.ficha(representacion.persona)
        actuales["personeria"] = {
            "fecha_instrumento": representacion.fecha_instrumento,
            "sitio_o_notaria": representacion.sitio_o_notaria,
        }
    arrendador = Persona.objects.filter(pk=datos["arrendador"]).first()
    return {
        **actuales,
        "arrendador": comun.ficha(arrendador),
        **{clave: datos[clave] for clave in CLAVES_DEL_FORMULARIO},
    }


def resumen(tramite: Tramite) -> list[dict[str, str]]:
    """The lease in a few lines, for the case screens."""
    datos = tramite.datos
    arrendador = Persona.objects.filter(pk=datos["arrendador"]).first()
    vehiculo = datos["vehiculo"]
    meses = datos["plazo_meses"]
    return [
        comun.linea("Arrendador", str(arrendador) if arrendador else "—"),
        comun.linea(
            "Vehículo",
            f"{vehiculo['marca']} {vehiculo['modelo']} {vehiculo['anio']}, "
            f"{vehiculo['color']}",
        ),
        comun.linea("Patente", vehiculo["patente"]),
        comun.linea("VIN/Chasis", vehiculo["vin"]),
        comun.linea("Plazo", f"{meses} {'mes' if meses == 1 else 'meses'}"),
        comun.linea(
            "Vigencia",
            f"{comun.fecha_corta(datos['fecha_inicio'])} al "
            f"{comun.fecha_corta(fecha_termino(datos))}",
        ),
        comun.linea("Renta mensual", comun.pesos(datos["renta"])),
        comun.linea(
            "Pago",
            f"primeros {datos['dia_pago']} días de cada mes, {medio_pago(datos)}",
        ),
        comun.linea("Fecha del documento", comun.fecha_corta(datos["fecha"])),
        comun.linea("Comuna", datos["comuna"]),
    ]

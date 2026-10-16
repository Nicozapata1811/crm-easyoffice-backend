from __future__ import annotations

from typing import Any

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from crm_easyoffice.clientes.api.serializers import RutField
from crm_easyoffice.tramites.models import EventoTramite
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.services import FALTA_INFORMACION
from crm_easyoffice.tramites.services import INICIADO
from crm_easyoffice.tramites.services import NUEVA_FECHA
from crm_easyoffice.tramites.services import PAGO
from crm_easyoffice.tramites.services import REVISION_BORRADOR
from crm_easyoffice.tramites.services import TRANSICIONES
from crm_easyoffice.tramites.services import situacion
from crm_easyoffice.ventas.api.serializers import ItemVentaSerializer
from crm_easyoffice.ventas.models import Venta

MONTO = {"max_digits": 12, "decimal_places": 0}

# A Chilean mobile: 9 and eight more digits. The contract prefixes "+56".
# ASSUMPTION: pending validation with Easy Office. The template's field is
# called CELULAR_8_DIGITOS, but its sample holds nine.
MOVIL = r"^9\d{8}$"


# ---------------------------------------------------------------------------
# Input: the domicile form (section A of PLT-01)
# ---------------------------------------------------------------------------


class EmpresaSerializer(serializers.Serializer):
    rut = RutField()
    razon_social = serializers.CharField(max_length=255)
    giro = serializers.CharField(max_length=255)


class RepresentanteSerializer(serializers.Serializer):
    rut = RutField()
    nombres = serializers.CharField(max_length=100)
    apellido_paterno = serializers.CharField(max_length=100)
    apellido_materno = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
    )
    domicilio = serializers.CharField(max_length=255)
    comuna = serializers.CharField(max_length=100)
    region = serializers.CharField(max_length=100)


class PersoneriaSerializer(serializers.Serializer):
    fecha_instrumento = serializers.DateField()
    sitio_o_notaria = serializers.CharField(max_length=255)

    def validate_fecha_instrumento(self, valor):
        if valor > timezone.localdate():
            raise serializers.ValidationError(_("The date cannot be in the future."))
        return valor


class DomicilioSerializer(serializers.Serializer):
    empresa = EmpresaSerializer()
    representante = RepresentanteSerializer()
    personeria = PersoneriaSerializer()
    email_aviso = serializers.EmailField()
    movil_aviso = serializers.RegexField(
        MOVIL,
        error_messages={"invalid": _("Enter a mobile with 9 digits, starting with 9.")},
    )
    plan = serializers.SlugField()
    sucursal = serializers.IntegerField()
    fecha_inicio = serializers.DateField()


class FechaInicioSerializer(serializers.Serializer):
    fecha_inicio = serializers.DateField()


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class PlanSerializer(serializers.Serializer):
    codigo = serializers.CharField()
    nombre = serializers.CharField()
    duracion_meses = serializers.IntegerField()
    ciclo_pago = serializers.CharField(source="ciclo_pago.nombre")
    precio = serializers.DecimalField(**MONTO)
    precio_incluye_iva = serializers.BooleanField()
    precio_confirmado = serializers.BooleanField()
    firma_incluida = serializers.BooleanField()
    precio_firma = serializers.SerializerMethodField()

    @extend_schema_field(serializers.DecimalField(allow_null=True, **MONTO))
    def get_precio_firma(self, plan) -> Any:
        precio = self.context.get("precio_firma")
        if plan.firma_incluida or precio is None:
            return None
        return str(precio)


class SucursalSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    codigo = serializers.CharField(source="codigo_sucursal")
    nombre = serializers.CharField()
    direccion = serializers.CharField(source="direccion_completa")
    comuna = serializers.CharField()
    region = serializers.CharField()


class FormularioSerializer(serializers.Serializer):
    disponible = serializers.BooleanField()
    motivo_no_disponible = serializers.CharField()
    fecha_min = serializers.DateField()
    fecha_max = serializers.DateField()
    planes = PlanSerializer(many=True)
    sucursales = SucursalSerializer(many=True)
    datos = serializers.JSONField(allow_null=True)


class MotivoSerializer(serializers.Serializer):
    codigo = serializers.CharField()
    nombre = serializers.CharField()
    texto_cliente = serializers.CharField()


class VentaTramiteSerializer(serializers.ModelSerializer[Venta]):
    items = ItemVentaSerializer(many=True, read_only=True)

    class Meta:
        model = Venta
        fields = ["id", "folio", "estado", "total", "items"]
        read_only_fields = fields


class EventoPortalSerializer(serializers.ModelSerializer[EventoTramite]):
    class Meta:
        model = EventoTramite
        fields = ["fecha", "estado_nuevo", "motivo_nuevo"]
        read_only_fields = fields


class EventoBackofficeSerializer(serializers.ModelSerializer[EventoTramite]):
    usuario = serializers.EmailField(source="usuario.email", default=None)

    class Meta:
        model = EventoTramite
        fields = [
            "fecha",
            "estado_anterior",
            "motivo_anterior",
            "estado_nuevo",
            "motivo_nuevo",
            "detalle",
            "usuario",
        ]
        read_only_fields = fields


def _accion_cliente(tramite: Tramite) -> str | None:
    """What the portal asks the client to do next, if anything."""
    _, motivo = situacion(tramite)
    if motivo == REVISION_BORRADOR:
        return "revisar_borrador"
    if motivo == PAGO:
        return "pagar"
    if motivo == FALTA_INFORMACION and tramite.detalle_pendiente == NUEVA_FECHA:
        return "nueva_fecha"
    return None


class TramiteSerializer(serializers.ModelSerializer[Tramite]):
    """A case as its client sees it. Internal notes stay out."""

    tipo = serializers.CharField(source="tipo.nombre")
    motivo = MotivoSerializer(allow_null=True)
    accion_cliente = serializers.SerializerMethodField()
    editable = serializers.SerializerMethodField()
    contrato = serializers.SerializerMethodField()
    venta = VentaTramiteSerializer(allow_null=True)
    eventos = EventoPortalSerializer(many=True)

    class Meta:
        model = Tramite
        fields = [
            "id",
            "folio",
            "tipo",
            "estado",
            "motivo",
            "accion_cliente",
            "editable",
            "datos",
            "contrato",
            "venta",
            "eventos",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_accion_cliente(self, tramite: Tramite) -> str | None:
        return _accion_cliente(tramite)

    @extend_schema_field(serializers.BooleanField())
    def get_editable(self, tramite: Tramite) -> bool:
        pagada = (
            tramite.venta is not None and tramite.venta.estado == Venta.Estado.PAGADA
        )
        return not pagada and (INICIADO, None) in TRANSICIONES[situacion(tramite)]

    @extend_schema_field(serializers.JSONField(allow_null=True))
    def get_contrato(self, tramite: Tramite) -> dict[str, Any] | None:
        contrato = tramite.contrato
        if contrato is None:
            return None
        linea = contrato.servicios.select_related("inmueble", "ciclo_pago").first()
        inmueble = linea.inmueble if linea else None
        return {
            "folio": contrato.folio,
            "estado": contrato.estado,
            "fecha_inicio": contrato.fecha_inicio,
            "fecha_vencimiento": contrato.fecha_vencimiento,
            "duracion_meses": contrato.duracion_meses,
            "email_aviso": contrato.email_aviso,
            "movil_aviso": contrato.movil_aviso,
            "servicio": linea.nombre if linea else "",
            "precio": str(linea.precio) if linea and linea.precio is not None else None,
            "ciclo_pago": linea.ciclo_pago.nombre if linea else "",
            "sucursal": (
                {
                    "id": inmueble.pk,
                    "nombre": inmueble.nombre,
                    "direccion": inmueble.direccion_completa,
                }
                if inmueble
                else None
            ),
        }


class TramiteBackofficeSerializer(TramiteSerializer):
    """The executive also sees the client, the internal note and who moved it."""

    cliente = serializers.SerializerMethodField()
    eventos = EventoBackofficeSerializer(many=True)

    class Meta(TramiteSerializer.Meta):
        fields = [
            *TramiteSerializer.Meta.fields,
            "cliente",
            "detalle_pendiente",
            "canal",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.JSONField())
    def get_cliente(self, tramite: Tramite) -> dict[str, Any]:
        cliente = tramite.cliente
        return {
            "id": cliente.pk,
            "codigo": cliente.codigo,
            "nombre": cliente.nombre,
            "rut": cliente.parte.rut,
        }

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


class EmpresaContratanteSerializer(serializers.Serializer):
    rut = RutField()
    razon_social = serializers.CharField(max_length=255)
    giro = serializers.CharField(max_length=255)


class RepresentanteContratanteSerializer(serializers.Serializer):
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
    empresa = EmpresaContratanteSerializer()
    representante = RepresentanteContratanteSerializer()
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


class LineaElegidaSerializer(serializers.Serializer):
    """A line without a plan: its cycle, and the agreed price if it has no list one."""

    servicio = serializers.SlugField()
    ciclo_pago = serializers.SlugField(required=False, allow_null=True, default=None)
    precio = serializers.DecimalField(
        **MONTO,
        min_value=1,
        required=False,
        allow_null=True,
        default=None,
    )


class EdicionBackofficeSerializer(serializers.Serializer):
    """A request an executive files or edits for a client (e.g. PLT-02).

    ``sucursal`` and ``bodega`` are the property roles a type's lines name
    (inmuebles.services.ROLES); the type decides which it needs.
    """

    empresa = EmpresaContratanteSerializer()
    representante = RepresentanteContratanteSerializer()
    personeria = PersoneriaSerializer()
    email_aviso = serializers.EmailField()
    movil_aviso = serializers.RegexField(
        MOVIL,
        error_messages={"invalid": _("Enter a mobile with 9 digits, starting with 9.")},
    )
    fecha_inicio = serializers.DateField()
    duracion_meses = serializers.IntegerField(min_value=1, required=False)
    plan = serializers.SlugField(required=False)
    sucursal = serializers.IntegerField(required=False)
    bodega = serializers.IntegerField(required=False)
    lineas = LineaElegidaSerializer(many=True, required=False, default=list)


class SolicitudBackofficeSerializer(EdicionBackofficeSerializer):
    tipo = serializers.SlugField()
    cliente = serializers.IntegerField()


class SolicitudPortalSerializer(EdicionBackofficeSerializer):
    """A request a client files in the portal for a type sold by plan (PLT-02)."""

    tipo = serializers.SlugField()


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


class InmuebleSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    tipo = serializers.CharField()
    codigo = serializers.CharField(source="codigo_sucursal", allow_null=True)
    nombre = serializers.CharField()
    direccion = serializers.CharField(source="direccion_completa")
    comuna = serializers.CharField()
    region = serializers.CharField()


class LineaFormularioSerializer(serializers.Serializer):
    """A line of the type: its service as the catalogue holds it, and its role."""

    servicio = serializers.CharField(source="servicio.codigo")
    nombre = serializers.CharField(source="servicio.nombre")
    precio_base = serializers.DecimalField(
        source="servicio.precio_base",
        allow_null=True,
        **MONTO,
    )
    precio_confirmado = serializers.BooleanField(source="servicio.precio_confirmado")
    ciclo_pago_default = serializers.CharField(
        source="servicio.ciclo_pago_default.codigo",
        allow_null=True,
        default=None,
    )
    inmueble = serializers.CharField()


class CicloSerializer(serializers.Serializer):
    codigo = serializers.CharField()
    nombre = serializers.CharField()


class FormularioBackofficeSerializer(serializers.Serializer):
    """What an executive's request form offers; ``problemas`` says what is missing."""

    disponible = serializers.BooleanField()
    problemas = serializers.ListField(child=serializers.CharField())
    fecha_min = serializers.DateField()
    fecha_max = serializers.DateField()
    planes = PlanSerializer(many=True)
    duraciones = serializers.ListField(child=serializers.IntegerField())
    duracion_por_defecto = serializers.IntegerField(allow_null=True)
    inmuebles = serializers.DictField(child=InmuebleSerializer(many=True))
    lineas = LineaFormularioSerializer(many=True)
    ciclos_pago = CicloSerializer(many=True)
    datos = serializers.JSONField(allow_null=True)


class FormularioPortalSerializer(serializers.Serializer):
    """What a portal request form offers; the reason is plain, for the client."""

    nombre = serializers.CharField()
    disponible = serializers.BooleanField()
    motivo_no_disponible = serializers.CharField()
    fecha_min = serializers.DateField()
    fecha_max = serializers.DateField()
    planes = PlanSerializer(many=True)
    inmuebles = serializers.DictField(child=InmuebleSerializer(many=True))
    datos = serializers.JSONField(allow_null=True)


class TipoTramiteSerializer(serializers.Serializer):
    codigo = serializers.CharField()
    nombre = serializers.CharField()


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
    """What the portal asks the client to do next, if anything.

    A backoffice case is the executive's to move: the client only follows it.
    """
    if tramite.canal == Tramite.Canal.BACKOFFICE:
        return None
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
    tipo_codigo = serializers.CharField(source="tipo.codigo")
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
            "tipo_codigo",
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

    # The channel whose side may edit the case; the backoffice serializer
    # answers for the executive.
    canal_que_edita = Tramite.Canal.PORTAL

    @extend_schema_field(serializers.BooleanField())
    def get_editable(self, tramite: Tramite) -> bool:
        if tramite.canal != self.canal_que_edita:
            return False
        pagada = (
            tramite.venta is not None and tramite.venta.estado == Venta.Estado.PAGADA
        )
        return not pagada and (INICIADO, None) in TRANSICIONES[situacion(tramite)]

    @extend_schema_field(serializers.JSONField(allow_null=True))
    def get_contrato(self, tramite: Tramite) -> dict[str, Any] | None:
        contrato = tramite.contrato
        if contrato is None:
            return None
        lineas = list(contrato.servicios.all())
        linea = lineas[0] if lineas else None
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
            # Every line; the keys above repeat the first one, as before PLT-02.
            "servicios": [
                {
                    "nombre": s.nombre,
                    "precio": str(s.precio),
                    "ciclo_pago": s.ciclo_pago.nombre,
                    "inmueble": (
                        {
                            "id": s.inmueble.pk,
                            "tipo": s.inmueble.tipo,
                            "nombre": s.inmueble.nombre,
                            "direccion": s.inmueble.direccion_completa,
                        }
                        if s.inmueble
                        else None
                    ),
                }
                for s in lineas
            ],
        }


class TramiteBackofficeSerializer(TramiteSerializer):
    """The executive also sees the client, the internal note and who moved it."""

    cliente = serializers.SerializerMethodField()
    eventos = EventoBackofficeSerializer(many=True)

    canal_que_edita = Tramite.Canal.BACKOFFICE

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

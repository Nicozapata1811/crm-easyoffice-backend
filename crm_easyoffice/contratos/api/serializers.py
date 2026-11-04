from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.clientes.models import RepresentanteLegal
from crm_easyoffice.configuracion.models import CuentaPago
from crm_easyoffice.configuracion.models import Marca
from crm_easyoffice.contratos.models import AlertaVencimiento
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.contratos.models import ServicioContratado
from crm_easyoffice.contratos.services import LineaContrato
from crm_easyoffice.contratos.services import crear_contrato
from crm_easyoffice.inmuebles.models import Oficina
from crm_easyoffice.users.models import User
from crm_easyoffice.ventas.models import CicloPago
from crm_easyoffice.ventas.models import Servicio

if TYPE_CHECKING:
    from datetime import date

MONTO = {"max_digits": 12, "decimal_places": 0}


class ServicioContratadoSerializer(serializers.ModelSerializer[ServicioContratado]):
    servicio = serializers.SlugRelatedField(slug_field="codigo", read_only=True)
    ciclo_pago = serializers.SlugRelatedField(slug_field="codigo", read_only=True)

    class Meta:
        model = ServicioContratado
        fields = [
            "orden",
            "servicio",
            "nombre",
            "descripcion",
            "precio",
            "precio_incluye_iva",
            "ciclo_pago",
            "inmueble",
        ]
        read_only_fields = fields


class ParteSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nombre = serializers.CharField()


class ClienteContratoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    codigo = serializers.CharField()
    nombre = serializers.CharField()


def _nombre_usuario(usuario: User | None) -> str | None:
    if usuario is None:
        return None
    return usuario.name or usuario.email


def _dias_hasta(vencimiento: date) -> int:
    """Days from today, in Chile's calendar, to ``vencimiento``."""
    return (vencimiento - timezone.localdate()).days


class ContratoSerializer(serializers.ModelSerializer[Contrato]):
    marca = serializers.SerializerMethodField()
    cliente = serializers.SerializerMethodField()
    servicios = ServicioContratadoSerializer(many=True, read_only=True)
    ejecutivo_responsable_nombre = serializers.SerializerMethodField()
    dias_restantes = serializers.SerializerMethodField()

    class Meta:
        model = Contrato
        fields = [
            "id",
            "folio",
            "codigo_sucursal",
            "anio_folio",
            "correlativo",
            "estado",
            "marca",
            "cliente",
            "representante",
            "cuenta_pago",
            "fecha_inicio",
            "duracion_meses",
            "fecha_vencimiento",
            "renovacion_automatica",
            "dias_aviso_termino",
            "email_aviso",
            "movil_aviso",
            "ejecutivo_responsable",
            "ejecutivo_responsable_nombre",
            "dias_restantes",
            "terminado_en",
            "contrato_anterior",
            "servicios",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(ParteSerializer)
    def get_marca(self, contrato: Contrato) -> dict[str, Any]:
        return {"id": contrato.marca_id, "nombre": contrato.marca.nombre}

    @extend_schema_field(ClienteContratoSerializer)
    def get_cliente(self, contrato: Contrato) -> dict[str, Any]:
        cliente = contrato.cliente
        return {"id": cliente.pk, "codigo": cliente.codigo, "nombre": cliente.nombre}

    def get_ejecutivo_responsable_nombre(self, contrato: Contrato) -> str | None:
        return _nombre_usuario(contrato.ejecutivo_responsable)

    def get_dias_restantes(self, contrato: Contrato) -> int | None:
        """Days to the stored expiry, negative once past. Only a contract in force."""
        if contrato.estado != Contrato.Estado.VIGENTE:
            return None
        return _dias_hasta(contrato.fecha_vencimiento)


class EjecutivoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nombre = serializers.SerializerMethodField()

    def get_nombre(self, usuario: User) -> str:
        return _nombre_usuario(usuario) or ""


class AsignarResponsableSerializer(serializers.Serializer):
    ejecutivo = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())


class FiltrosAlertasSerializer(serializers.Serializer):
    """Query parameters of the alert list; dates are inclusive."""

    estado = serializers.ChoiceField(
        required=False,
        choices=AlertaVencimiento.Estado.choices,
    )
    mias = serializers.BooleanField(required=False)
    umbral = serializers.IntegerField(required=False, min_value=1)
    vence_desde = serializers.DateField(required=False)
    vence_hasta = serializers.DateField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        desde, hasta = attrs.get("vence_desde"), attrs.get("vence_hasta")
        if desde and hasta and desde > hasta:
            mensaje = _("La fecha final no puede ser anterior a la inicial.")
            raise serializers.ValidationError({"vence_hasta": mensaje})
        return attrs


class ResponsableSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nombre = serializers.CharField()


class AlertaVencimientoSerializer(serializers.ModelSerializer[AlertaVencimiento]):
    folio = serializers.CharField(source="contrato.folio")
    renovacion_automatica = serializers.BooleanField(
        source="contrato.renovacion_automatica",
    )
    cliente = serializers.SerializerMethodField()
    servicios = serializers.SerializerMethodField()
    ejecutivo_responsable = serializers.SerializerMethodField()
    dias_restantes = serializers.SerializerMethodField()
    gestionada_por_nombre = serializers.SerializerMethodField()

    class Meta:
        model = AlertaVencimiento
        fields = [
            "id",
            "contrato",
            "folio",
            "renovacion_automatica",
            "cliente",
            "servicios",
            "ejecutivo_responsable",
            "umbral_dias",
            "fecha_vencimiento",
            "dias_restantes",
            "estado",
            "created_at",
            "gestionada_por_nombre",
            "gestionada_en",
            "nota",
        ]
        read_only_fields = fields

    @extend_schema_field(ClienteContratoSerializer)
    def get_cliente(self, alerta: AlertaVencimiento) -> dict[str, Any]:
        cliente = alerta.contrato.cliente
        return {"id": cliente.pk, "codigo": cliente.codigo, "nombre": cliente.nombre}

    def get_servicios(self, alerta: AlertaVencimiento) -> list[str]:
        return [linea.nombre for linea in alerta.contrato.servicios.all()]

    @extend_schema_field(ResponsableSerializer(allow_null=True))
    def get_ejecutivo_responsable(
        self,
        alerta: AlertaVencimiento,
    ) -> dict[str, Any] | None:
        usuario = alerta.contrato.ejecutivo_responsable
        if usuario is None:
            return None
        return {"id": usuario.pk, "nombre": _nombre_usuario(usuario)}

    def get_dias_restantes(self, alerta: AlertaVencimiento) -> int:
        """Days to the alert's expiry, negative once past."""
        return _dias_hasta(alerta.fecha_vencimiento)

    def get_gestionada_por_nombre(self, alerta: AlertaVencimiento) -> str | None:
        return _nombre_usuario(alerta.gestionada_por)


class GestionarAlertaSerializer(serializers.Serializer):
    nota = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
        default="",
    )


class ResumenAlertasSerializer(serializers.Serializer):
    pendientes = serializers.IntegerField()
    umbrales = serializers.ListField(child=serializers.IntegerField())


class LineaContratoSerializer(serializers.Serializer):
    servicio = serializers.SlugRelatedField(
        slug_field="codigo",
        queryset=Servicio.objects.all(),
    )
    ciclo_pago = serializers.SlugRelatedField(
        slug_field="codigo",
        queryset=CicloPago.objects.filter(activo=True),
        required=False,
        allow_null=True,
    )
    inmueble = serializers.PrimaryKeyRelatedField(
        queryset=Oficina.objects.all(),
        required=False,
        allow_null=True,
    )
    precio = serializers.DecimalField(
        required=False,
        allow_null=True,
        min_value=0,
        **MONTO,
    )


class CrearContratoSerializer(serializers.Serializer):
    """The contract form. Folio, expiry and copied prices are computed."""

    cliente = serializers.PrimaryKeyRelatedField(queryset=Cliente.objects.all())
    marca = serializers.PrimaryKeyRelatedField(queryset=Marca.objects.all())
    cuenta_pago = serializers.PrimaryKeyRelatedField(
        queryset=CuentaPago.objects.all(),
        required=False,
        allow_null=True,
    )
    representante = serializers.PrimaryKeyRelatedField(
        queryset=RepresentanteLegal.objects.all(),
        required=False,
        allow_null=True,
    )
    fecha_inicio = serializers.DateField()
    duracion_meses = serializers.IntegerField(min_value=1)
    renovacion_automatica = serializers.BooleanField(default=True)
    dias_aviso_termino = serializers.IntegerField(min_value=0, default=30)
    email_aviso = serializers.EmailField(required=False, allow_blank=True, default="")
    movil_aviso = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
        default="",
    )
    codigo_sucursal = serializers.CharField(
        max_length=4,
        required=False,
        allow_blank=True,
        help_text="Only when no located service gives the folio's branch.",
    )
    servicios = LineaContratoSerializer(many=True, allow_empty=False)

    def create(self, validated_data: dict[str, Any]) -> Contrato:
        lineas = [LineaContrato(**linea) for linea in validated_data.pop("servicios")]
        try:
            return crear_contrato(
                lineas=lineas,
                codigo_sucursal=validated_data.pop("codigo_sucursal", "") or None,
                ejecutivo=self.context["request"].user,
                **validated_data,
            )
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error

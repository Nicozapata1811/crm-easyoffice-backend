from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.clientes.models import RepresentanteLegal
from crm_easyoffice.configuracion.models import CuentaPago
from crm_easyoffice.configuracion.models import Marca
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.contratos.models import ServicioContratado
from crm_easyoffice.contratos.services import LineaContrato
from crm_easyoffice.contratos.services import crear_contrato
from crm_easyoffice.inmuebles.models import Oficina
from crm_easyoffice.ventas.models import CicloPago
from crm_easyoffice.ventas.models import Servicio

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


class ContratoSerializer(serializers.ModelSerializer[Contrato]):
    marca = serializers.SerializerMethodField()
    cliente = serializers.SerializerMethodField()
    servicios = ServicioContratadoSerializer(many=True, read_only=True)

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

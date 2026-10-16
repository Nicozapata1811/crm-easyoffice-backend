from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from crm_easyoffice.integrations.payment.registry import MEDIOS
from crm_easyoffice.integrations.payment.registry import checkout_script_url
from crm_easyoffice.integrations.payment.registry import proveedores_habilitados
from crm_easyoffice.ventas.models import ItemVenta
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.models import Pago
from crm_easyoffice.ventas.models import Servicio
from crm_easyoffice.ventas.models import Venta

MAX_CANTIDAD = 10


class ServicioSerializer(serializers.ModelSerializer[Servicio]):
    ciclo_pago_default = serializers.SlugRelatedField(
        slug_field="codigo",
        read_only=True,
    )

    class Meta:
        model = Servicio
        fields = [
            "id",
            "codigo",
            "nombre",
            "descripcion",
            "precio_base",
            "precio_incluye_iva",
            "precio_confirmado",
            "ciclo_pago_default",
            "visible_en_portal",
            "se_vende_en_portal",
        ]
        read_only_fields = fields


class ItemVentaSerializer(serializers.ModelSerializer[ItemVenta]):
    servicio = serializers.SlugRelatedField(slug_field="codigo", read_only=True)

    class Meta:
        model = ItemVenta
        fields = ["servicio", "nombre", "precio_unitario", "cantidad", "subtotal"]
        read_only_fields = fields


class PagoSerializer(serializers.ModelSerializer[Pago]):
    class Meta:
        model = Pago
        fields = [
            "id",
            "tipo",
            "id_externo",
            "monto",
            "medio",
            "marca",
            "tipo_tarjeta",
            "ultimos_digitos",
            "cuotas",
            "billetera",
            "pagado_en",
        ]
        read_only_fields = fields


class CheckoutSerializer(serializers.Serializer):
    tipo = serializers.ChoiceField(choices=["modal", "redireccion"])
    script_url = serializers.URLField(allow_null=True)


class MedioPagoSerializer(serializers.Serializer):
    codigo = serializers.CharField()
    nombre = serializers.CharField()
    descripcion = serializers.CharField()
    checkout = serializers.SerializerMethodField()

    @extend_schema_field(CheckoutSerializer)
    def get_checkout(self, medio) -> dict:
        return {"tipo": medio.checkout, "script_url": checkout_script_url(medio.codigo)}


class PagarSerializer(serializers.Serializer):
    proveedor = serializers.CharField(required=False)

    def validate_proveedor(self, proveedor: str) -> str:
        if proveedor not in proveedores_habilitados():
            raise serializers.ValidationError(
                _("This payment method is not available."),
            )
        return proveedor

    def validate(self, attrs: dict) -> dict:
        habilitados = proveedores_habilitados()
        if "proveedor" not in attrs:
            if not habilitados:
                raise serializers.ValidationError(_("No payment method is enabled."))
            attrs["proveedor"] = habilitados[0]
        return attrs


class OrdenPagoSerializer(serializers.ModelSerializer[OrdenPago]):
    venta = serializers.PrimaryKeyRelatedField(read_only=True)
    checkout = serializers.SerializerMethodField()
    checkout_script_url = serializers.SerializerMethodField()

    class Meta:
        model = OrdenPago
        fields = [
            "id",
            "venta",
            "proveedor",
            "id_externo",
            "monto",
            "estado",
            "checkout",
            "checkout_script_url",
            "redirect_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_checkout_script_url(self, orden: OrdenPago) -> str | None:
        return checkout_script_url(orden.proveedor)

    @extend_schema_field(serializers.ChoiceField(choices=["modal", "redireccion"]))
    def get_checkout(self, orden: OrdenPago) -> str:
        medio = MEDIOS.get(orden.proveedor)
        return medio.checkout if medio else "redireccion"


class OrdenPagoDetalleSerializer(OrdenPagoSerializer):
    pagos = PagoSerializer(many=True, read_only=True)

    class Meta(OrdenPagoSerializer.Meta):
        fields = [*OrdenPagoSerializer.Meta.fields, "detalle_error", "pagos"]
        read_only_fields = fields


class VentaSerializer(serializers.ModelSerializer[Venta]):
    items = ItemVentaSerializer(many=True, read_only=True)
    ultima_orden = serializers.SerializerMethodField()

    class Meta:
        model = Venta
        fields = [
            "id",
            "folio",
            "estado",
            "total",
            "pagada_en",
            "created_at",
            "items",
            "ultima_orden",
        ]
        read_only_fields = fields

    @extend_schema_field(OrdenPagoSerializer(allow_null=True))
    def get_ultima_orden(self, venta: Venta) -> dict | None:
        orden = venta.ordenes.order_by("-created_at").first()
        return OrdenPagoSerializer(orden).data if orden else None


class VentaBackofficeSerializer(serializers.ModelSerializer[Venta]):
    cliente = serializers.SerializerMethodField()
    items = ItemVentaSerializer(many=True, read_only=True)
    ordenes = OrdenPagoDetalleSerializer(many=True, read_only=True)

    class Meta:
        model = Venta
        fields = [
            "id",
            "folio",
            "estado",
            "total",
            "pagada_en",
            "created_at",
            "cliente",
            "items",
            "ordenes",
        ]
        read_only_fields = fields

    @extend_schema_field(
        {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "codigo": {"type": "string"},
                "folio": {
                    "type": "string",
                    "deprecated": True,
                    "description": "Old name of codigo, kept for one release.",
                },
                "nombre": {"type": "string"},
            },
        },
    )
    def get_cliente(self, venta: Venta) -> dict:
        cliente = venta.cliente
        return {
            "id": cliente.pk,
            "codigo": cliente.codigo,
            "folio": cliente.codigo,
            "nombre": cliente.nombre,
        }


class LineaVentaSerializer(serializers.Serializer):
    servicio = serializers.SlugRelatedField(
        slug_field="codigo",
        queryset=Servicio.objects.filter(activo=True, se_vende_en_portal=True),
    )
    cantidad = serializers.IntegerField(min_value=1, max_value=MAX_CANTIDAD, default=1)


class CrearVentaSerializer(serializers.Serializer):
    items = LineaVentaSerializer(many=True, allow_empty=False)

    def validate_items(self, items: list[dict]) -> list[dict]:
        codigos = [item["servicio"].codigo for item in items]
        if len(codigos) != len(set(codigos)):
            raise serializers.ValidationError(_("Each service may appear only once."))
        return items

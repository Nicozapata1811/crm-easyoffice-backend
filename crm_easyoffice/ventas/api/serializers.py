from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from crm_easyoffice.integrations.payment.registry import checkout_script_url
from crm_easyoffice.ventas.models import ItemVenta
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.models import Pago
from crm_easyoffice.ventas.models import Servicio
from crm_easyoffice.ventas.models import Venta

MAX_CANTIDAD = 10


class ServicioSerializer(serializers.ModelSerializer[Servicio]):
    class Meta:
        model = Servicio
        fields = [
            "id",
            "codigo",
            "nombre",
            "descripcion",
            "precio_base",
            "precio_confirmado",
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


class OrdenPagoSerializer(serializers.ModelSerializer[OrdenPago]):
    venta = serializers.PrimaryKeyRelatedField(read_only=True)
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
            "checkout_script_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_checkout_script_url(self, orden: OrdenPago) -> str | None:
        return checkout_script_url()


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
                "folio": {"type": "string"},
                "nombre": {"type": "string"},
            },
        },
    )
    def get_cliente(self, venta: Venta) -> dict:
        cliente = venta.cliente
        return {"id": cliente.pk, "folio": cliente.folio, "nombre": cliente.nombre}


class LineaVentaSerializer(serializers.Serializer):
    servicio = serializers.SlugRelatedField(
        slug_field="codigo",
        queryset=Servicio.objects.filter(activo=True),
    )
    cantidad = serializers.IntegerField(min_value=1, max_value=MAX_CANTIDAD, default=1)


class CrearVentaSerializer(serializers.Serializer):
    items = LineaVentaSerializer(many=True, allow_empty=False)

    def validate_items(self, items: list[dict]) -> list[dict]:
        codigos = [item["servicio"].codigo for item in items]
        if len(codigos) != len(set(codigos)):
            raise serializers.ValidationError(_("Each service may appear only once."))
        return items

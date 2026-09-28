from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from crm_easyoffice.tramites.catalogo import enlace_portal


class PlanSerializer(serializers.Serializer):
    slug = serializers.CharField()
    nombre = serializers.CharField()
    meses = serializers.IntegerField()
    precio = serializers.IntegerField()
    moneda = serializers.CharField()
    precio_confirmado = serializers.BooleanField()
    enlace = serializers.SerializerMethodField()

    def get_enlace(self, plan) -> str:
        return enlace_portal(self.context["servicio_slug"], plan["slug"])


class ServicioSerializer(serializers.Serializer):
    slug = serializers.CharField()
    nombre = serializers.CharField()
    planes = serializers.SerializerMethodField()

    @extend_schema_field(PlanSerializer(many=True))
    def get_planes(self, servicio):
        context = {**self.context, "servicio_slug": servicio["slug"]}
        return PlanSerializer(servicio["planes"], many=True, context=context).data


class CatalogoSerializer(serializers.Serializer):
    servicios = ServicioSerializer(many=True)

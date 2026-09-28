import re

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

ORIGEN_PATTERN = re.compile(r"[a-z0-9_-]{1,50}")
ORIGEN_POR_DEFECTO = "sitio"


class ProspectoEntranteSerializer(serializers.Serializer):
    """Validation shared by every source, applied after its adapter.

    ASSUMPTION: pending validation with Easy Office. A lead needs a name plus
    an email or a phone number to be contactable.
    """

    nombre = serializers.CharField(max_length=200)
    email = serializers.EmailField(max_length=254, allow_blank=True, default="")
    telefono = serializers.CharField(max_length=30, allow_blank=True, default="")
    servicio_interes = serializers.CharField(
        max_length=100,
        allow_blank=True,
        default="",
    )
    plan = serializers.CharField(max_length=50, allow_blank=True, default="")
    origen = serializers.CharField(allow_blank=True, default=ORIGEN_POR_DEFECTO)
    mensaje = serializers.CharField(max_length=5000, allow_blank=True, default="")
    id_envio = serializers.CharField(max_length=100, allow_blank=True, default="")

    def validate_servicio_interes(self, value: str) -> str:
        return value.lower()

    def validate_plan(self, value: str) -> str:
        return value.lower()

    def validate_origen(self, value: str) -> str:
        value = value.lower()
        return value if ORIGEN_PATTERN.fullmatch(value) else ORIGEN_POR_DEFECTO

    def validate(self, attrs):
        if not attrs["email"] and not attrs["telefono"]:
            raise serializers.ValidationError(
                _("Provide an email address or a phone number."),
                code="sin_contacto",
            )
        return attrs


class ResultadoWebhookSerializer(serializers.Serializer):
    resultado = serializers.ChoiceField(choices=["creado", "duplicado"])

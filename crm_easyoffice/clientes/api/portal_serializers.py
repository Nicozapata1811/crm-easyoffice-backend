from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from crm_easyoffice.clientes.api.serializers import RutField
from crm_easyoffice.clientes.models import TipoCliente

CAMPOS_POR_TIPO = {
    TipoCliente.PERSONA: ("nombres", "apellido_paterno"),
    TipoCliente.EMPRESA: ("razon_social",),
}


class RegistroSerializer(serializers.Serializer):
    tipo = serializers.ChoiceField(choices=TipoCliente.choices)
    rut = RutField()
    nombres = serializers.CharField(max_length=100, required=False)
    apellido_paterno = serializers.CharField(max_length=100, required=False)
    apellido_materno = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
    )
    razon_social = serializers.CharField(max_length=255, required=False)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        faltantes = {
            campo: [_("This field is required.")]
            for campo in CAMPOS_POR_TIPO[attrs["tipo"]]
            if not attrs.get(campo)
        }
        if faltantes:
            raise serializers.ValidationError(faltantes)
        return attrs

    def datos_parte(self) -> dict[str, Any]:
        """The Persona or Empresa fields, ready for ``registrar_cuenta_cliente``."""
        attrs = self.validated_data
        datos = {"rut": attrs["rut"], "email": attrs["email"]}
        if attrs["tipo"] == TipoCliente.PERSONA:
            campos = ("nombres", "apellido_paterno", "apellido_materno")
        else:
            campos = ("razon_social",)
        datos.update({campo: attrs.get(campo, "") for campo in campos})
        return datos

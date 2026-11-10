"""Section A of a request form: the client company, its signer, the personería.

Kept apart from the other serializers so the per-template forms
(tramites.formularios) can reuse it without importing the case services.
"""

from __future__ import annotations

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from crm_easyoffice.clientes.api.serializers import RutField


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

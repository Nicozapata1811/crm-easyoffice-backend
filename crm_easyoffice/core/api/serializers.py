from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from crm_easyoffice.core.auditoria.consulta import nombre_entidad
from crm_easyoffice.core.models import RegistroAuditoria


class FiltrosAuditoriaSerializer(serializers.Serializer):
    """Query parameters of ``GET /api/auditoria/``; dates are local and inclusive."""

    entidad = serializers.CharField(required=False, max_length=100)
    registro_id = serializers.IntegerField(required=False, min_value=1)
    usuario = serializers.IntegerField(required=False, min_value=1)
    accion = serializers.ChoiceField(
        required=False,
        choices=RegistroAuditoria.Accion.choices,
    )
    origen = serializers.ChoiceField(
        required=False,
        choices=RegistroAuditoria.Origen.choices,
    )
    desde = serializers.DateField(required=False)
    hasta = serializers.DateField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "registro_id" in attrs and "entidad" not in attrs:
            raise serializers.ValidationError(
                {"entidad": _("Indica la entidad del registro.")},
            )
        if (
            attrs.get("desde")
            and attrs.get("hasta")
            and attrs["desde"] > attrs["hasta"]
        ):
            raise serializers.ValidationError(
                {"hasta": _("La fecha final no puede ser anterior a la inicial.")},
            )
        return attrs


class HistorialSerializer(serializers.Serializer):
    """Query parameters of ``GET /api/auditoria/historial/``."""

    entidad = serializers.CharField(max_length=100)
    registro_id = serializers.IntegerField(min_value=1)


class RegistroAuditoriaSerializer(serializers.ModelSerializer[RegistroAuditoria]):
    usuario_nombre = serializers.SerializerMethodField()
    entidad_nombre = serializers.SerializerMethodField()
    registro_nombre = serializers.SerializerMethodField()

    class Meta:
        model = RegistroAuditoria
        fields = [
            "id",
            "fecha_hora",
            "usuario",
            "usuario_nombre",
            "origen",
            "accion",
            "entidad",
            "entidad_nombre",
            "registro_id",
            "registro_nombre",
            "valor_anterior",
            "valor_nuevo",
            "direccion_ip",
        ]
        read_only_fields = fields

    def get_usuario_nombre(self, entrada: RegistroAuditoria) -> str | None:
        """The user's name, or null when the system acted."""
        usuario = entrada.usuario
        if usuario is None:
            return None
        return usuario.name or usuario.email

    def get_entidad_nombre(self, entrada: RegistroAuditoria) -> str:
        return nombre_entidad(entrada.entidad)

    def get_registro_nombre(self, entrada: RegistroAuditoria) -> str | None:
        if entrada.registro_id is None:
            return None
        nombres = self.context.get("nombres", {})
        return nombres.get(
            (entrada.entidad, entrada.registro_id),
            f"#{entrada.registro_id}",
        )

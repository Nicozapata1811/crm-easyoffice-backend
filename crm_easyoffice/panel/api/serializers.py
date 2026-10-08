from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers


class PeriodoSerializer(serializers.Serializer):
    desde = serializers.DateField()
    hasta = serializers.DateField()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["desde"] > attrs["hasta"]:
            raise serializers.ValidationError(
                {"hasta": _("Must not be earlier than desde.")},
            )
        return attrs

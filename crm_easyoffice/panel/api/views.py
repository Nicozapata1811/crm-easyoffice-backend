"""Operational dashboard endpoints (RF-14, HU-41)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_easyoffice.panel.exportacion import libro_indicadores
from crm_easyoffice.panel.exportacion import nombre_archivo
from crm_easyoffice.panel.services import calcular_indicadores

from .serializers import PeriodoSerializer

if TYPE_CHECKING:
    from datetime import date

    from rest_framework.request import Request

PERMISO_PANEL = "core.view_dashboard"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class PuedeVerPanel(BasePermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(
            request.user.is_authenticated and request.user.has_perm(PERMISO_PANEL),
        )


def _periodo(request: Request) -> tuple[date, date]:
    serializer = PeriodoSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data["desde"], serializer.validated_data["hasta"]


class IndicadoresView(APIView):
    permission_classes = [PuedeVerPanel]

    @extend_schema(parameters=[PeriodoSerializer], responses=OpenApiTypes.OBJECT)
    def get(self, request: Request) -> Response:
        return Response(calcular_indicadores(*_periodo(request)))


class ExportarIndicadoresView(APIView):
    permission_classes = [PuedeVerPanel]

    @extend_schema(
        parameters=[PeriodoSerializer],
        responses={(200, XLSX): OpenApiResponse(OpenApiTypes.BINARY)},
    )
    def get(self, request: Request) -> HttpResponse:
        indicadores = calcular_indicadores(*_periodo(request))
        return HttpResponse(
            libro_indicadores(indicadores),
            content_type=XLSX,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{nombre_archivo(indicadores)}"'
                ),
            },
        )

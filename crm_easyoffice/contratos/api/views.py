"""Contracts (HU-60): list, record and create. Contracts are never deleted."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.mixins import CreateModelMixin
from rest_framework.mixins import ListModelMixin
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from crm_easyoffice.clientes.api.views import ClientePagination
from crm_easyoffice.clientes.api.views import ClientePermissions
from crm_easyoffice.clientes.api.views import search_clientes
from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.contratos.services import opciones_contrato

from .serializers import ContratoSerializer
from .serializers import CrearContratoSerializer

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from rest_framework.request import Request


class PuedeCrearContratos(BasePermission):
    def has_permission(self, request: Request, view) -> bool:
        return bool(
            request.user.is_authenticated
            and request.user.has_perm("contratos.add_contrato"),
        )


@extend_schema(
    parameters=[
        OpenApiParameter("buscar", str, description="Folio, client RUT or name, …"),
        OpenApiParameter("estado", str, enum=Contrato.Estado.values),
        OpenApiParameter("marca", int),
        OpenApiParameter("sucursal", str, description="Branch code, e.g. LF."),
        OpenApiParameter("anio", int, description="Year of the folio."),
    ],
    methods=["GET"],
)
class ContratoViewSet(
    CreateModelMixin,
    ListModelMixin,
    RetrieveModelMixin,
    GenericViewSet,
):
    permission_classes = [ClientePermissions]
    pagination_class = ClientePagination
    serializer_class = ContratoSerializer
    http_method_names = ["get", "post", "head", "options"]
    queryset = Contrato.objects.select_related(
        "marca",
        "cliente__persona",
        "cliente__empresa",
    ).prefetch_related("servicios__servicio", "servicios__ciclo_pago")

    def get_serializer_class(self):
        if self.action == "create":
            return CrearContratoSerializer
        return ContratoSerializer

    def get_queryset(self) -> QuerySet[Contrato]:
        queryset = super().get_queryset()
        if self.action != "list":
            return queryset

        params = self.request.query_params
        if buscar := params.get("buscar", "").strip():
            clientes = search_clientes(Cliente.objects.all(), buscar)
            queryset = queryset.filter(
                Q(folio__icontains=buscar) | Q(cliente__in=clientes),
            )
        if estado := params.get("estado"):
            queryset = queryset.filter(estado=estado)
        if (marca := params.get("marca", "")).isdigit():
            queryset = queryset.filter(marca_id=int(marca))
        if sucursal := params.get("sucursal"):
            queryset = queryset.filter(codigo_sucursal=sucursal.upper())
        if (anio := params.get("anio", "")).isdigit():
            queryset = queryset.filter(anio_folio=int(anio))
        return queryset

    @extend_schema(request=CrearContratoSerializer, responses={201: ContratoSerializer})
    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = CrearContratoSerializer(
            data=request.data,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        contrato = serializer.save()
        contrato = self.get_queryset().get(pk=contrato.pk)
        return Response(
            ContratoSerializer(contrato).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(responses=OpenApiTypes.OBJECT)
    @action(detail=False, permission_classes=[PuedeCrearContratos])
    def opciones(self, request: Request) -> Response:
        """Brands, accounts, terms, cycles, branches and services to choose from."""
        return Response(opciones_contrato())

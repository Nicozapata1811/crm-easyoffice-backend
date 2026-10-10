from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import extend_schema
from rest_framework.mixins import CreateModelMixin
from rest_framework.mixins import ListModelMixin
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.mixins import UpdateModelMixin
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import DjangoModelPermissions
from rest_framework.viewsets import GenericViewSet

from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.clientes.models import TipoCliente
from crm_easyoffice.core.validators import normalize_rut

from .serializers import ClienteResumenSerializer
from .serializers import ClienteSerializer

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from rest_framework.serializers import BaseSerializer

SEARCH_FIELDS = [
    "folio",
    "persona__nombres",
    "persona__apellido_paterno",
    "persona__apellido_materno",
    "persona__email",
    "persona__telefono",
    "empresa__razon_social",
    "empresa__nombre_fantasia",
    "empresa__email",
    "empresa__telefono",
]


class ClientePermissions(DjangoModelPermissions):
    perms_map = {
        **DjangoModelPermissions.perms_map,
        "GET": ["%(app_label)s.view_%(model_name)s"],
        "HEAD": ["%(app_label)s.view_%(model_name)s"],
    }


class ClientePagination(PageNumberPagination):
    page_size = 25


def search_clientes(queryset: QuerySet[Cliente], text: str) -> QuerySet[Cliente]:
    """Keep clients matching every word of ``text`` in some searchable field.

    A word is also compared as a RUT, so ``12.345.678-5`` finds ``12345678-5``.
    """
    for word in text.split():
        rut = normalize_rut(word)
        match = Q(persona__rut__icontains=rut) | Q(empresa__rut__icontains=rut)
        for field in SEARCH_FIELDS:
            match |= Q(**{f"{field}__icontains": word})
        queryset = queryset.filter(match)
    return queryset


@extend_schema(
    parameters=[
        OpenApiParameter("buscar", str, description="RUT, name, razón social, …"),
        OpenApiParameter("tipo", str, enum=TipoCliente.values),
        OpenApiParameter("activo", bool),
    ],
    methods=["GET"],
)
class ClienteViewSet(
    CreateModelMixin,
    ListModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
    GenericViewSet,
):
    """Client records (HU-06, HU-07, HU-47, HU-49). Clients are never deleted."""

    queryset = Cliente.objects.select_related("persona", "empresa")
    permission_classes = [ClientePermissions]
    pagination_class = ClientePagination
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_serializer_class(self) -> type[BaseSerializer[Cliente]]:
        if self.action == "list":
            return ClienteResumenSerializer
        return ClienteSerializer

    def get_queryset(self) -> QuerySet[Cliente]:
        queryset = super().get_queryset().order_by("-created_at", "-pk")
        if self.action != "list":
            return queryset

        params = self.request.query_params
        if buscar := params.get("buscar", "").strip():
            queryset = search_clientes(queryset, buscar)
        if params.get("tipo") == TipoCliente.PERSONA:
            queryset = queryset.filter(persona__isnull=False)
        elif params.get("tipo") == TipoCliente.EMPRESA:
            queryset = queryset.filter(empresa__isnull=False)
        if params.get("activo") in {"true", "false"}:
            queryset = queryset.filter(activo=params["activo"] == "true")
        return queryset

"""Contracts (HU-60): list, record and create. Contracts are never deleted."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
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
from crm_easyoffice.contratos.models import AlertaVencimiento
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.contratos.services import AlertaYaGestionadaError
from crm_easyoffice.contratos.services import ContratoNoEditableError
from crm_easyoffice.contratos.services import alertas_visibles
from crm_easyoffice.contratos.services import asignar_responsable
from crm_easyoffice.contratos.services import ejecutivos_asignables
from crm_easyoffice.contratos.services import gestionar_alerta
from crm_easyoffice.contratos.services import opciones_contrato
from crm_easyoffice.contratos.services import resumen_alertas

from .serializers import AlertaVencimientoSerializer
from .serializers import AsignarResponsableSerializer
from .serializers import ContratoSerializer
from .serializers import CrearContratoSerializer
from .serializers import EjecutivoSerializer
from .serializers import FiltrosAlertasSerializer
from .serializers import GestionarAlertaSerializer
from .serializers import ResumenAlertasSerializer

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from rest_framework.request import Request


class _TienePermiso(BasePermission):
    permiso: str

    def has_permission(self, request: Request, view) -> bool:
        return bool(
            request.user.is_authenticated and request.user.has_perm(self.permiso),
        )


class PuedeCrearContratos(_TienePermiso):
    permiso = "contratos.add_contrato"


class PuedeAsignarResponsable(_TienePermiso):
    """Only the Administrador: an Ejecutivo holds ``change_contrato`` too."""

    permiso = "contratos.asignar_responsable_contrato"


class PuedeVerAlertas(_TienePermiso):
    permiso = "contratos.view_alertavencimiento"


class PuedeGestionarAlertas(_TienePermiso):
    permiso = "contratos.gestionar_alertavencimiento"


def _conflicto(detalle: str, codigo: str) -> Response:
    return Response(
        {"detail": detalle, "codigo": codigo},
        status=status.HTTP_409_CONFLICT,
    )


@extend_schema(
    parameters=[
        OpenApiParameter("buscar", str, description="Folio, client RUT or name, …"),
        OpenApiParameter("cliente", int, description="The client's contracts."),
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
        "ejecutivo_responsable",
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
        if (cliente := params.get("cliente", "")).isdigit():
            queryset = queryset.filter(cliente_id=int(cliente))
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

    @extend_schema(responses=EjecutivoSerializer(many=True))
    @action(
        detail=False,
        permission_classes=[PuedeAsignarResponsable],
        pagination_class=None,
    )
    def ejecutivos(self, request: Request) -> Response:
        """Who can be made responsible for a contract."""
        return Response(EjecutivoSerializer(ejecutivos_asignables(), many=True).data)

    @extend_schema(
        request=AsignarResponsableSerializer,
        responses={200: ContratoSerializer},
    )
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[PuedeAsignarResponsable],
    )
    def responsable(self, request: Request, pk: str | None = None) -> Response:
        """Set or change the responsible executive. Contracts have no PATCH."""
        serializer = AsignarResponsableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contrato = self.get_object()
        try:
            asignar_responsable(contrato, serializer.validated_data["ejecutivo"])
        except ContratoNoEditableError:
            return _conflicto(
                "Este contrato ya no admite cambios.",
                "contrato_no_editable",
            )
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict) from error
        return Response(ContratoSerializer(self.get_object()).data)


@extend_schema(parameters=[FiltrosAlertasSerializer], methods=["GET"])
class AlertaVencimientoViewSet(ListModelMixin, GenericViewSet):
    """Expiry alerts of the contracts the user may see (HU-42, UC-09)."""

    permission_classes = [PuedeVerAlertas]
    pagination_class = ClientePagination
    serializer_class = AlertaVencimientoSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self) -> QuerySet[AlertaVencimiento]:
        if getattr(self, "swagger_fake_view", False):  # The schema has no user.
            return AlertaVencimiento.objects.none()
        alertas = alertas_visibles(self.request.user).select_related(
            "contrato__cliente__persona",
            "contrato__cliente__empresa",
            "contrato__ejecutivo_responsable",
            "gestionada_por",
        )
        if self.action != "list":
            return alertas

        filtros = FiltrosAlertasSerializer(data=self.request.query_params)
        filtros.is_valid(raise_exception=True)
        datos = filtros.validated_data
        if "estado" in datos:
            alertas = alertas.filter(estado=datos["estado"])
        if datos.get("mias"):
            alertas = alertas.filter(contrato__ejecutivo_responsable=self.request.user)
        if "umbral" in datos:
            alertas = alertas.filter(umbral_dias=datos["umbral"])
        if "vence_desde" in datos:
            alertas = alertas.filter(fecha_vencimiento__gte=datos["vence_desde"])
        if "vence_hasta" in datos:
            alertas = alertas.filter(fecha_vencimiento__lte=datos["vence_hasta"])
        return alertas.prefetch_related("contrato__servicios")

    @extend_schema(parameters=[], responses=ResumenAlertasSerializer)
    @action(detail=False, pagination_class=None)
    def resumen(self, request: Request) -> Response:
        """The pending count for the menu badge, and the thresholds to filter by."""
        return Response(resumen_alertas(request.user))

    @extend_schema(
        parameters=[],
        request=GestionarAlertaSerializer,
        responses={200: AlertaVencimientoSerializer},
    )
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[PuedeGestionarAlertas],
    )
    def gestionar(self, request: Request, pk: str | None = None) -> Response:
        """Mark an alert as handled. Someone else's answers 404, a second time 409."""
        serializer = GestionarAlertaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        alerta = self.get_object()
        try:
            gestionar_alerta(
                alerta,
                request.user,
                serializer.validated_data["nota"].strip(),
            )
        except AlertaYaGestionadaError:
            return _conflicto("Esta alerta ya fue gestionada.", "alerta_ya_gestionada")
        return Response(AlertaVencimientoSerializer(self.get_object()).data)

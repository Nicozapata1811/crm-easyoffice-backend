"""Cases (HU-24): the client's domicile request and the executive's case list."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.mixins import ListModelMixin
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet
from rest_framework.viewsets import ReadOnlyModelViewSet

from crm_easyoffice.clientes.api.permissions import EsCliente
from crm_easyoffice.clientes.api.views import ClientePagination
from crm_easyoffice.clientes.api.views import ClientePermissions
from crm_easyoffice.clientes.api.views import search_clientes
from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.clientes.services import RepresentanteNoDisponibleError
from crm_easyoffice.tramites.models import TipoTramite
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.services import NO_DISPONIBLE
from crm_easyoffice.tramites.services import FechaInicioVencidaError
from crm_easyoffice.tramites.services import TramiteNoDisponibleError
from crm_easyoffice.tramites.services import TransicionInvalidaError
from crm_easyoffice.tramites.services import actualizar_domicilio
from crm_easyoffice.tramites.services import actualizar_tramite
from crm_easyoffice.tramites.services import cambiar_fecha_inicio
from crm_easyoffice.tramites.services import confirmar_borrador
from crm_easyoffice.tramites.services import formulario_domicilio
from crm_easyoffice.tramites.services import formulario_portal
from crm_easyoffice.tramites.services import formulario_tramite
from crm_easyoffice.tramites.services import iniciar_domicilio
from crm_easyoffice.tramites.services import iniciar_tramite
from crm_easyoffice.tramites.services import reintentar_documento
from crm_easyoffice.tramites.services import tipos_iniciables
from crm_easyoffice.ventas.services import PlanNoDisponibleError
from crm_easyoffice.ventas.services import precio_firma

from .serializers import DomicilioSerializer
from .serializers import EdicionBackofficeSerializer
from .serializers import FechaInicioSerializer
from .serializers import FormularioBackofficeSerializer
from .serializers import FormularioPortalSerializer
from .serializers import FormularioSerializer
from .serializers import SolicitudBackofficeSerializer
from .serializers import SolicitudPortalSerializer
from .serializers import TipoTramiteSerializer
from .serializers import TramiteBackofficeSerializer
from .serializers import TramiteSerializer

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.db.models import QuerySet
    from rest_framework.request import Request

REPRESENTANTE_NO_DISPONIBLE = _(
    "We cannot use this representative's RUT. Please contact Easy Office.",
)
FECHA_VENCIDA = _("The start date has passed: choose a new one.")


class PuedeGestionarTramites(BasePermission):
    def has_permission(self, request: Request, view) -> bool:
        return bool(
            request.user.is_authenticated
            and request.user.has_perm("tramites.gestionar_tramite"),
        )


class PuedeIniciarTramites(BasePermission):
    def has_permission(self, request: Request, view) -> bool:
        return bool(
            request.user.is_authenticated
            and request.user.has_perm("tramites.iniciar_tramite"),
        )


def cliente_de(request: Request) -> Cliente:
    return request.user.cuenta_cliente.cliente  # type: ignore[union-attr]


def _tipo_activo(codigo: str) -> TipoTramite:
    """The active case type a request names.

    Raises:
        rest_framework.exceptions.ValidationError: No such active type.
    """
    tipo = TipoTramite.objects.filter(codigo=codigo, activo=True).first()
    if tipo is None:
        raise ValidationError({"tipo": [_("Unknown case type.")]})
    return tipo


def _tipo_y_cliente(codigo: str, cliente_id: str | int) -> tuple[TipoTramite, Cliente]:
    """The active case type and the client a backoffice request names.

    Raises:
        rest_framework.exceptions.ValidationError: Either does not exist.
    """
    errores = {}
    tipo = TipoTramite.objects.filter(codigo=codigo, activo=True).first()
    if tipo is None:
        errores["tipo"] = [_("Unknown case type.")]
    cliente = (
        Cliente.objects.select_related("persona", "empresa")
        .filter(pk=cliente_id)
        .first()
        if str(cliente_id).isdigit()
        else None
    )
    if cliente is None:
        errores["cliente"] = [_("Unknown client.")]
    if errores:
        raise ValidationError(errores)
    return tipo, cliente


def _con_tramite(queryset: QuerySet[Tramite]) -> QuerySet[Tramite]:
    return queryset.select_related(
        "tipo",
        "motivo",
        "contrato",
        "venta",
        "cliente__persona",
        "cliente__empresa",
    ).prefetch_related(
        "eventos__usuario",
        "venta__items__servicio",
        "contrato__servicios__inmueble",
        "contrato__servicios__ciclo_pago",
    )


def _conflicto(detalle: str, codigo: str) -> Response:
    return Response(
        {"detail": detalle, "codigo": codigo},
        status=status.HTTP_409_CONFLICT,
    )


def _responder(
    operacion: Callable[[], Tramite],
    *,
    creado: bool = False,
    serializer: type[TramiteSerializer] = TramiteSerializer,
) -> Response:
    """Run a case operation and turn its domain errors into HTTP answers."""
    try:
        tramite = operacion()
    except DjangoValidationError as error:
        raise ValidationError(error.message_dict) from error
    except RepresentanteNoDisponibleError:
        raise ValidationError(
            {"representante": {"rut": [REPRESENTANTE_NO_DISPONIBLE]}},
        ) from None
    except TramiteNoDisponibleError as error:
        respuesta = _conflicto(NO_DISPONIBLE, "no_disponible")
        if serializer is TramiteBackofficeSerializer:
            # Staff see what is missing; a client never does.
            respuesta.data["problemas"] = error.detalle
        return respuesta
    except FechaInicioVencidaError:
        return _conflicto(FECHA_VENCIDA, "fecha_inicio_vencida")
    except PlanNoDisponibleError:
        return _conflicto(_("This plan is no longer available."), "plan_no_disponible")
    except TransicionInvalidaError:
        return _conflicto(
            _("The request cannot change at this step."),
            "transicion_invalida",
        )
    tramite = _con_tramite(Tramite.objects.all()).get(pk=tramite.pk)
    return Response(
        serializer(tramite).data,
        status=status.HTTP_201_CREATED if creado else status.HTTP_200_OK,
    )


class FormularioDomicilioView(APIView):
    """What the domicile form offers this client, pre-filled with their data."""

    permission_classes = [EsCliente]

    @extend_schema(responses=FormularioSerializer)
    def get(self, request: Request) -> Response:
        formulario = formulario_domicilio(cliente_de(request))
        serializer = FormularioSerializer(
            formulario,
            context={"precio_firma": precio_firma()},
        )
        return Response(serializer.data)


class TramitePortalViewSet(ListModelMixin, RetrieveModelMixin, GenericViewSet):
    """The client's own cases."""

    permission_classes = [EsCliente]
    serializer_class = TramiteSerializer
    pagination_class = ClientePagination

    def get_queryset(self) -> QuerySet[Tramite]:
        if getattr(self, "swagger_fake_view", False):
            return Tramite.objects.none()
        return _con_tramite(Tramite.objects.filter(cliente=cliente_de(self.request)))

    @extend_schema(
        parameters=[OpenApiParameter("tipo", str, required=True)],
        responses=FormularioPortalSerializer,
    )
    @action(detail=False, methods=["get"])
    def formulario(self, request: Request) -> Response:
        """What the request form of a type sold online offers this client."""
        tipo = _tipo_activo(request.query_params.get("tipo", ""))
        serializer = FormularioPortalSerializer(
            formulario_portal(tipo, cliente_de(request)),
            context={"precio_firma": precio_firma()},
        )
        return Response(serializer.data)

    @extend_schema(
        request=SolicitudPortalSerializer,
        responses={201: TramiteSerializer},
    )
    def create(self, request: Request) -> Response:
        """File a request for a type sold online (e.g. the bodega, PLT-02)."""
        serializer = SolicitudPortalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        datos = dict(serializer.validated_data)
        tipo = _tipo_activo(datos.pop("tipo"))
        return _responder(
            lambda: iniciar_tramite(
                tipo,
                cliente_de(request),
                datos,
                canal=Tramite.Canal.PORTAL,
                usuario=request.user,
            ),
            creado=True,
        )

    @extend_schema(request=EdicionBackofficeSerializer, responses=TramiteSerializer)
    def update(self, request: Request, pk: str | None = None) -> Response:
        """Change a request before it is paid; its document is generated again."""
        tramite = self.get_object()
        serializer = EdicionBackofficeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return _responder(
            lambda: actualizar_tramite(
                tramite,
                serializer.validated_data,
                request.user,
            ),
        )

    @extend_schema(request=DomicilioSerializer, responses={201: TramiteSerializer})
    @action(detail=False, methods=["post"], url_path="domicilio")
    def crear_domicilio(self, request: Request) -> Response:
        serializer = DomicilioSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return _responder(
            lambda: iniciar_domicilio(
                cliente_de(request),
                serializer.validated_data,
                request.user,
            ),
            creado=True,
        )

    @extend_schema(request=DomicilioSerializer, responses=TramiteSerializer)
    @action(detail=True, methods=["put"], url_path="domicilio")
    def editar_domicilio(self, request: Request, pk: str | None = None) -> Response:
        tramite = self.get_object()
        serializer = DomicilioSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return _responder(
            lambda: actualizar_domicilio(
                tramite,
                serializer.validated_data,
                request.user,
            ),
        )

    @extend_schema(request=FechaInicioSerializer, responses=TramiteSerializer)
    @action(detail=True, methods=["post"], url_path="fecha-inicio")
    def fecha_inicio(self, request: Request, pk: str | None = None) -> Response:
        tramite = self.get_object()
        serializer = FechaInicioSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return _responder(
            lambda: cambiar_fecha_inicio(
                tramite,
                serializer.validated_data["fecha_inicio"],
                request.user,
            ),
        )

    @extend_schema(request=None, responses=TramiteSerializer)
    @action(detail=True, methods=["post"])
    def confirmar(self, request: Request, pk: str | None = None) -> Response:
        tramite = self.get_object()
        return _responder(lambda: confirmar_borrador(tramite, request.user))


@extend_schema(
    parameters=[
        OpenApiParameter("buscar", str, description="Case folio, or client data."),
        OpenApiParameter("estado", str, enum=Tramite.Estado.values),
        OpenApiParameter("motivo", str, description="Pending reason code."),
    ],
    methods=["GET"],
)
class TramiteViewSet(ReadOnlyModelViewSet):
    """Cases for the backoffice (HU-11, HU-61). States move through actions."""

    permission_classes = [ClientePermissions]
    serializer_class = TramiteBackofficeSerializer
    pagination_class = ClientePagination
    queryset = Tramite.objects.all()

    def get_queryset(self) -> QuerySet[Tramite]:
        queryset = _con_tramite(super().get_queryset())
        params = self.request.query_params
        if estado := params.get("estado"):
            queryset = queryset.filter(estado=estado)
        if motivo := params.get("motivo"):
            queryset = queryset.filter(motivo__codigo=motivo)
        if buscar := params.get("buscar", "").strip():
            clientes = search_clientes(Cliente.objects.all(), buscar)
            queryset = queryset.filter(
                Q(folio__icontains=buscar)
                | Q(contrato__folio__icontains=buscar)
                | Q(cliente__in=clientes),
            )
        return queryset

    @extend_schema(request=None, responses=TramiteBackofficeSerializer)
    @action(detail=True, methods=["post"], permission_classes=[PuedeGestionarTramites])
    def regenerar(self, request: Request, pk: str | None = None) -> Response:
        """Generate the document again once the missing data was completed."""
        tramite = self.get_object()
        return _responder(
            lambda: reintentar_documento(tramite, request.user),
            serializer=TramiteBackofficeSerializer,
        )

    # --- Cases an executive starts for a client (PLT-02) ----------------------

    @extend_schema(
        parameters=[OpenApiParameter("canal", str, enum=Tramite.Canal.values)],
        responses=TipoTramiteSerializer(many=True),
    )
    @action(detail=False, methods=["get"])
    def tipos(self, request: Request) -> Response:
        """Case types that can be started through a channel (default backoffice)."""
        canal = request.query_params.get("canal", Tramite.Canal.BACKOFFICE)
        return Response(TipoTramiteSerializer(tipos_iniciables(canal), many=True).data)

    @extend_schema(
        parameters=[
            OpenApiParameter("tipo", str, required=True),
            OpenApiParameter("cliente", int, required=True),
        ],
        responses=FormularioBackofficeSerializer,
    )
    @action(detail=False, methods=["get"], permission_classes=[PuedeIniciarTramites])
    def formulario(self, request: Request) -> Response:
        """What the request form offers for this client and case type."""
        tipo, cliente = _tipo_y_cliente(
            request.query_params.get("tipo", ""),
            request.query_params.get("cliente", ""),
        )
        formulario = formulario_tramite(tipo, cliente)
        serializer = FormularioBackofficeSerializer(
            formulario,
            context={"precio_firma": precio_firma()},
        )
        return Response(serializer.data)

    @extend_schema(
        request=SolicitudBackofficeSerializer,
        responses={201: TramiteBackofficeSerializer},
    )
    def create(self, request: Request) -> Response:
        """Start a case for a client: its data, the draft contract, the document."""
        serializer = SolicitudBackofficeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        datos = dict(serializer.validated_data)
        tipo, cliente = _tipo_y_cliente(datos.pop("tipo"), datos.pop("cliente"))
        return _responder(
            lambda: iniciar_tramite(
                tipo,
                cliente,
                datos,
                canal=Tramite.Canal.BACKOFFICE,
                usuario=request.user,
            ),
            creado=True,
            serializer=TramiteBackofficeSerializer,
        )

    @extend_schema(
        request=EdicionBackofficeSerializer,
        responses=TramiteBackofficeSerializer,
    )
    def update(self, request: Request, pk: str | None = None) -> Response:
        """Change a backoffice request before it is signed; the document is redone."""
        tramite = self.get_object()
        serializer = EdicionBackofficeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return _responder(
            lambda: actualizar_tramite(
                tramite,
                serializer.validated_data,
                request.user,
                canal=Tramite.Canal.BACKOFFICE,
            ),
            serializer=TramiteBackofficeSerializer,
        )

    @extend_schema(request=None, responses=TramiteBackofficeSerializer)
    @action(detail=True, methods=["post"], permission_classes=[PuedeGestionarTramites])
    def confirmar(self, request: Request, pk: str | None = None) -> Response:
        """Record that the client confirmed the draft (RN-13)."""
        tramite = self.get_object()
        return _responder(
            lambda: confirmar_borrador(
                tramite,
                request.user,
                canal=Tramite.Canal.BACKOFFICE,
            ),
            serializer=TramiteBackofficeSerializer,
        )

    @extend_schema(request=FechaInicioSerializer, responses=TramiteBackofficeSerializer)
    @action(
        detail=True,
        methods=["post"],
        url_path="fecha-inicio",
        permission_classes=[PuedeGestionarTramites],
    )
    def fecha_inicio(self, request: Request, pk: str | None = None) -> Response:
        """Set a new start date once the chosen one has passed."""
        tramite = self.get_object()
        serializer = FechaInicioSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return _responder(
            lambda: cambiar_fecha_inicio(
                tramite,
                serializer.validated_data["fecha_inicio"],
                request.user,
                canal=Tramite.Canal.BACKOFFICE,
            ),
            serializer=TramiteBackofficeSerializer,
        )

    def get_permissions(self):
        if self.action == "create":
            return [PuedeIniciarTramites()]
        if self.action == "update":
            return [PuedeGestionarTramites()]
        return super().get_permissions()

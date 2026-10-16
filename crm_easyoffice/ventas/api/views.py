from __future__ import annotations

import hashlib
import logging
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import IntegrityError
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.http import HttpResponseRedirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.generics import ListAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.mixins import CreateModelMixin
from rest_framework.mixins import ListModelMixin
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet
from rest_framework.viewsets import ReadOnlyModelViewSet

from crm_easyoffice.clientes.api.permissions import EsCliente
from crm_easyoffice.clientes.api.views import ClientePagination
from crm_easyoffice.clientes.api.views import ClientePermissions
from crm_easyoffice.clientes.api.views import search_clientes
from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.integrations.payment.base import PaymentError
from crm_easyoffice.integrations.payment.base import PaymentStatus
from crm_easyoffice.integrations.payment.registry import get_payment_provider
from crm_easyoffice.integrations.payment.registry import medios_habilitados
from crm_easyoffice.integrations.payment.registry import proveedores_habilitados
from crm_easyoffice.ventas.models import EventoPago
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.models import Servicio
from crm_easyoffice.ventas.models import Venta
from crm_easyoffice.ventas.services import ProveedorNoHabilitadoError
from crm_easyoffice.ventas.services import VentaNoPagableError
from crm_easyoffice.ventas.services import aplicar_resultado
from crm_easyoffice.ventas.services import crear_venta
from crm_easyoffice.ventas.services import iniciar_pago
from crm_easyoffice.ventas.services import orden_de_resultado
from crm_easyoffice.ventas.tasks import procesar_notificacion
from crm_easyoffice.ventas.tasks import sincronizar_orden

from .serializers import CrearVentaSerializer
from .serializers import MedioPagoSerializer
from .serializers import OrdenPagoSerializer
from .serializers import PagarSerializer
from .serializers import ServicioSerializer
from .serializers import VentaBackofficeSerializer
from .serializers import VentaSerializer

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from rest_framework.request import Request

logger = logging.getLogger(__name__)

SINCRONIZAR_CADA = timedelta(seconds=10)
OK = {"status": "ok"}


def cliente_de(request: Request) -> Cliente:
    return request.user.cuenta_cliente.cliente  # type: ignore[union-attr]


class ServicioPortalView(ListAPIView):
    """Services the portal needs: landing cards and anything bookable online.

    A bookable add-on that is not a landing card is listed too, because the
    portal reads its price when it is charged inside another service.
    """

    permission_classes = [AllowAny]
    serializer_class = ServicioSerializer
    pagination_class = None
    queryset = (
        Servicio.objects.filter(activo=True)
        .filter(Q(visible_en_portal=True) | Q(se_vende_en_portal=True))
        .select_related("ciclo_pago_default")
    )


class VentaPortalViewSet(
    CreateModelMixin,
    ListModelMixin,
    RetrieveModelMixin,
    GenericViewSet,
):
    permission_classes = [EsCliente]
    serializer_class = VentaSerializer
    pagination_class = ClientePagination

    def get_queryset(self) -> QuerySet[Venta]:
        if getattr(self, "swagger_fake_view", False):
            return Venta.objects.none()
        return Venta.objects.filter(cliente=cliente_de(self.request)).prefetch_related(
            "items__servicio",
        )

    @extend_schema(request=CrearVentaSerializer, responses={201: VentaSerializer})
    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = CrearVentaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        venta = crear_venta(
            cliente_de(request),
            [
                (item["servicio"], item["cantidad"])
                for item in serializer.validated_data["items"]
            ],
        )
        return Response(VentaSerializer(venta).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=PagarSerializer, responses={202: OrdenPagoSerializer})
    @action(detail=True, methods=["post"])
    def pagar(self, request: Request, pk: str | None = None) -> Response:
        venta = self.get_object()
        serializer = PagarSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            orden = iniciar_pago(venta, serializer.validated_data["proveedor"])
        except VentaNoPagableError:
            return Response(
                {"detail": "Esta venta no está pendiente de pago."},
                status=status.HTTP_409_CONFLICT,
            )
        except ProveedorNoHabilitadoError:
            return Response(
                {"proveedor": ["Este medio de pago no está disponible."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            OrdenPagoSerializer(orden).data,
            status=status.HTTP_202_ACCEPTED,
        )


class MedioPagoPortalView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses=MedioPagoSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(MedioPagoSerializer(medios_habilitados(), many=True).data)


class OrdenPortalView(RetrieveAPIView):
    """The state the portal waits on. Asks the provider again when it is stale."""

    permission_classes = [EsCliente]
    serializer_class = OrdenPagoSerializer

    def get_queryset(self) -> QuerySet[OrdenPago]:
        if getattr(self, "swagger_fake_view", False):
            return OrdenPago.objects.none()
        return OrdenPago.objects.filter(venta__cliente=cliente_de(self.request))

    def get_object(self) -> OrdenPago:
        orden = super().get_object()
        ultima = orden.sincronizada_en or orden.updated_at
        if (
            orden.estado == OrdenPago.Estado.PENDIENTE
            and orden.id_externo
            and timezone.now() - ultima > SINCRONIZAR_CADA
        ):
            transaction.on_commit(lambda: sincronizar_orden.delay(orden.pk))
        return orden


class PagoWebhookView(APIView):
    """Notifications from the payment providers.

    Klap reverses the payment unless this answers 2xx within ten seconds, so
    this makes no outbound calls: a provider that must be asked about its
    notification (Flow) is handled by ``procesar_notificacion`` in Celery.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(request=None, responses={200: None})
    def post(self, request: Request, proveedor: str, evento: str) -> Response:
        if proveedor not in proveedores_habilitados():
            raise Http404

        clave = hashlib.sha256(
            f"{proveedor}:{evento}:".encode() + request.body,
        ).hexdigest()
        anterior = EventoPago.objects.filter(clave_dedup=clave).first()
        if anterior is not None:
            return self._respuesta(anterior.resultado)

        datos = request.data
        payload = datos.dict() if hasattr(datos, "dict") else datos
        recibido = {
            "clave_dedup": clave,
            "proveedor": proveedor,
            "evento": evento,
            "payload": payload if isinstance(payload, dict) else {},
        }
        cliente = get_payment_provider(proveedor)
        if cliente.webhook_needs_lookup:
            transaction.on_commit(lambda: procesar_notificacion.delay(recibido))
            return Response(OK)
        try:
            resultado = cliente.parse_webhook(
                recibido["payload"],
                dict(request.headers),
                event=evento,
            )
        except PaymentError as exc:
            logger.warning("Rejected %s webhook %s: %s", proveedor, evento, exc)
            return self._registrar(recibido, None, EventoPago.Resultado.FIRMA_INVALIDA)

        orden = orden_de_resultado(resultado)
        if orden is None:
            return self._registrar(recibido, None, EventoPago.Resultado.RECHAZADO)

        if resultado.status == PaymentStatus.PENDING:
            valida = orden.estado in OrdenPago.ABIERTAS and resultado.amount in (
                None,
                orden.monto,
            )
            return self._registrar(
                recibido,
                orden,
                EventoPago.Resultado.PROCESADO
                if valida
                else EventoPago.Resultado.RECHAZADO,
            )

        cambio = aplicar_resultado(orden.pk, resultado, origen=f"webhook:{evento}")
        return self._registrar(
            recibido,
            orden,
            EventoPago.Resultado.PROCESADO if cambio else EventoPago.Resultado.IGNORADO,
        )

    @staticmethod
    def _respuesta(resultado: str) -> Response:
        """The answer for an event, the same every time it is delivered."""
        if resultado == EventoPago.Resultado.FIRMA_INVALIDA:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        if resultado == EventoPago.Resultado.RECHAZADO:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        return Response(OK)

    @classmethod
    def _registrar(
        cls,
        recibido: dict,
        orden: OrdenPago | None,
        resultado: str,
    ) -> Response:
        try:
            with transaction.atomic():
                EventoPago.objects.create(**recibido, orden=orden, resultado=resultado)
        except IntegrityError:
            logger.info("Webhook %s already recorded.", recibido["clave_dedup"])
        return cls._respuesta(resultado)


class PagoRetornoView(View):
    """Where a provider sends the browser back, by GET or by POST (Flow).

    It changes nothing: it asks for a status check and redirects the browser
    to the portal page for the attempt.
    """

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, orden_id: int) -> HttpResponseRedirect:
        if OrdenPago.objects.filter(pk=orden_id).exists():
            transaction.on_commit(lambda: sincronizar_orden.delay(orden_id))
        pagina = "cancelado" if request.GET.get("cancelado") else "resultado"
        respuesta = HttpResponseRedirect(
            f"{settings.PORTAL_BASE_URL}/pagos/{orden_id}/{pagina}",
        )
        respuesta.status_code = HTTPStatus.SEE_OTHER
        return respuesta

    post = get


@extend_schema(
    parameters=[
        OpenApiParameter(
            "buscar",
            str,
            description="Folio de la venta, o datos del cliente.",
        ),
        OpenApiParameter("estado", str, enum=Venta.Estado.values),
    ],
)
class VentaViewSet(ReadOnlyModelViewSet):
    permission_classes = [ClientePermissions]
    serializer_class = VentaBackofficeSerializer
    pagination_class = ClientePagination
    queryset = Venta.objects.select_related(
        "cliente__persona",
        "cliente__empresa",
    ).prefetch_related("items__servicio", "ordenes__pagos")

    def get_queryset(self) -> QuerySet[Venta]:
        queryset = super().get_queryset()
        estado = self.request.query_params.get("estado")
        if estado:
            queryset = queryset.filter(estado=estado)
        texto = self.request.query_params.get("buscar", "").strip()
        if texto:
            clientes = search_clientes(Cliente.objects.all(), texto)
            queryset = queryset.filter(
                Q(folio__icontains=texto) | Q(cliente__in=clientes),
            )
        return queryset

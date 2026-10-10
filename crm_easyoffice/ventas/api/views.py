from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import IntegrityError
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
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
from crm_easyoffice.ventas.models import EventoPago
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.models import Servicio
from crm_easyoffice.ventas.models import Venta
from crm_easyoffice.ventas.services import VentaNoPagableError
from crm_easyoffice.ventas.services import aplicar_resultado
from crm_easyoffice.ventas.services import crear_venta
from crm_easyoffice.ventas.services import iniciar_pago
from crm_easyoffice.ventas.tasks import sincronizar_orden

from .serializers import CrearVentaSerializer
from .serializers import OrdenPagoSerializer
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
    permission_classes = [AllowAny]
    serializer_class = ServicioSerializer
    pagination_class = None
    queryset = Servicio.objects.filter(activo=True)


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

    @extend_schema(request=None, responses={202: OrdenPagoSerializer})
    @action(detail=True, methods=["post"])
    def pagar(self, request: Request, pk: str | None = None) -> Response:
        try:
            orden = iniciar_pago(self.get_object())
        except VentaNoPagableError:
            return Response(
                {"detail": "Esta venta no está pendiente de pago."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            OrdenPagoSerializer(orden).data,
            status=status.HTTP_202_ACCEPTED,
        )


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
    """Notifications from the payment provider.

    The provider reverses the payment unless this answers 2xx within ten
    seconds, so it makes no outbound calls.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(request=None, responses={200: None})
    def post(self, request: Request, proveedor: str, evento: str) -> Response:
        if proveedor != settings.PAYMENT_PROVIDER:
            raise Http404

        clave = hashlib.sha256(
            f"{proveedor}:{evento}:".encode() + request.body,
        ).hexdigest()
        if EventoPago.objects.filter(clave_dedup=clave).exists():
            return Response(OK)

        payload = request.data if isinstance(request.data, dict) else {}
        recibido = {
            "clave_dedup": clave,
            "proveedor": proveedor,
            "evento": evento,
            "payload": payload,
        }
        try:
            resultado = get_payment_provider().parse_webhook(
                payload,
                dict(request.headers),
                event=evento,
            )
        except PaymentError as exc:
            logger.warning("Rejected %s webhook %s: %s", proveedor, evento, exc)
            self._registrar(recibido, None, EventoPago.Resultado.FIRMA_INVALIDA)
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        orden = self._orden(resultado.reference, resultado.external_id)
        if orden is None:
            self._registrar(recibido, None, EventoPago.Resultado.IGNORADO)
            return Response(status=status.HTTP_400_BAD_REQUEST)

        if resultado.status == PaymentStatus.PENDING:
            self._registrar(recibido, orden, EventoPago.Resultado.PROCESADO)
            if resultado.amount in (None, orden.monto):
                return Response(OK)
            return Response(status=status.HTTP_400_BAD_REQUEST)

        cambio = aplicar_resultado(orden.pk, resultado, origen=f"webhook:{evento}")
        self._registrar(
            recibido,
            orden,
            EventoPago.Resultado.PROCESADO if cambio else EventoPago.Resultado.IGNORADO,
        )
        return Response(OK)

    @staticmethod
    def _orden(referencia: str, id_externo: str) -> OrdenPago | None:
        try:
            orden = OrdenPago.objects.get(referencia=uuid.UUID(referencia))
        except ValueError, OrdenPago.DoesNotExist:
            return None
        if orden.id_externo and id_externo and orden.id_externo != id_externo:
            return None
        return orden

    @staticmethod
    def _registrar(recibido: dict, orden: OrdenPago | None, resultado: str) -> None:
        try:
            with transaction.atomic():
                EventoPago.objects.create(**recibido, orden=orden, resultado=resultado)
        except IntegrityError:
            logger.info("Webhook %s already recorded.", recibido["clave_dedup"])


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

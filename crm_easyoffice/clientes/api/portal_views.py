"""Client portal accounts (HU-03)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth import login
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from crm_easyoffice.clientes.services import RegistroRechazadoError
from crm_easyoffice.clientes.services import registrar_cuenta_cliente
from crm_easyoffice.users.api.serializers import SessionUserSerializer

from .portal_serializers import RegistroSerializer

if TYPE_CHECKING:
    from rest_framework.request import Request

REGISTRO_RECHAZADO = _(
    "We could not create an account with these details. "
    "If you are already an Easy Office client, please contact us.",
)


@method_decorator(csrf_protect, name="dispatch")
class RegistroView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "registro"

    @extend_schema(request=RegistroSerializer, responses={201: SessionUserSerializer})
    def post(self, request: Request) -> Response:
        serializer = RegistroSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            cuenta = registrar_cuenta_cliente(
                tipo=serializer.validated_data["tipo"],
                datos=serializer.datos_parte(),
                password=serializer.validated_data["password"],
            )
        except DjangoValidationError as error:
            return Response(
                {"password": error.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except RegistroRechazadoError:
            return Response(
                {"detail": REGISTRO_RECHAZADO},
                status=status.HTTP_400_BAD_REQUEST,
            )
        login(request, cuenta.user, backend="django.contrib.auth.backends.ModelBackend")
        return Response(
            SessionUserSerializer(cuenta.user).data,
            status=status.HTTP_201_CREATED,
        )

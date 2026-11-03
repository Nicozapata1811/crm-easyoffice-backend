"""Session authentication for internal staff (HU-01).

The session lives in an httpOnly cookie (AD-03); no token reaches the browser.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from django.contrib.auth import authenticate
from django.contrib.auth import login
from django.contrib.auth import logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from drf_spectacular.utils import inline_serializer
from rest_framework import serializers
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_easyoffice.core.auditoria.eventos import Accion
from crm_easyoffice.core.auditoria.eventos import registrar_evento
from crm_easyoffice.core.throttling import IngresoThrottle

from .serializers import LoginSerializer
from .serializers import SessionUserSerializer

if TYPE_CHECKING:
    from rest_framework.request import Request

    from crm_easyoffice.users.models import User

INVALID_CREDENTIALS = _("Invalid email or password.")


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        responses=inline_serializer(
            "CsrfToken",
            {"csrfToken": serializers.CharField()},
        ),
    )
    def get(self, request: Request) -> Response:
        return Response({"csrfToken": get_token(request)})


# DRF skips CSRF for anonymous requests, which would leave login open to
# cross-site submission.
@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [IngresoThrottle]

    @extend_schema(request=LoginSerializer, responses=SessionUserSerializer)
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request,
            username=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
        )
        if user is None:
            return Response(
                {"detail": INVALID_CREDENTIALS},
                status=status.HTTP_400_BAD_REQUEST,
            )
        login(request, user)
        return Response(SessionUserSerializer(user).data)


class TokenView(ObtainAuthToken):
    """Exchange a password for an API token: a sign-in like any other."""

    throttle_classes = [IngresoThrottle]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        # Answer instead of raising: DRF would roll back the request's
        # transaction under ATOMIC_REQUESTS, and the failed sign-in's entry with it.
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        user = serializer.validated_data["user"]
        token, _created = Token.objects.get_or_create(user=user)
        # No login() here, so Django's auth signal does not record it.
        registrar_evento(
            Accion.INICIO_SESION,
            entidad="users.user",
            registro_id=user.pk,
            usuario=user,
        )
        return Response({"token": token.key})


class LogoutView(APIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    @extend_schema(responses=SessionUserSerializer)
    def get(self, request: Request) -> Response:
        return Response(SessionUserSerializer(cast("User", request.user)).data)

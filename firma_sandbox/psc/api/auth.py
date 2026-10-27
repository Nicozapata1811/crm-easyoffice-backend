"""API key authentication: ``Authorization: Bearer <key>``, stored hashed."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rest_framework import authentication
from rest_framework import exceptions
from rest_framework import permissions

from psc.models import ClienteApi
from psc.models import resumen

if TYPE_CHECKING:
    from rest_framework.request import Request


class ApiKeyAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request: Request) -> tuple[None, ClienteApi] | None:
        tipo, _, clave = request.headers.get("Authorization", "").partition(" ")
        if tipo.lower() != "bearer" or not clave:
            return None
        cliente = ClienteApi.objects.filter(
            hash_api_key=resumen(clave.strip()),
            activo=True,
        ).first()
        if cliente is None:
            msg = "API key inválida."
            raise exceptions.AuthenticationFailed(msg)
        return None, cliente

    def authenticate_header(self, request: Request) -> str:
        return 'Bearer realm="psc-pruebas"'


class EsClienteApi(permissions.BasePermission):
    def has_permission(self, request: Request, view: object) -> bool:
        return isinstance(request.auth, ClienteApi)

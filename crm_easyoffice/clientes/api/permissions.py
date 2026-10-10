from __future__ import annotations

from typing import TYPE_CHECKING

from rest_framework.permissions import BasePermission

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView


class EsCliente(BasePermission):
    """The request comes from a logged-in client with an active portal account."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        cuenta = getattr(request.user, "cuenta_cliente", None)
        return bool(request.user.is_authenticated and cuenta and cuenta.activa)

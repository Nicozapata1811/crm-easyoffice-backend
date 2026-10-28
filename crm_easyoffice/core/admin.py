from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django.contrib import admin

from .models import RegistroAuditoria

if TYPE_CHECKING:
    from django.http import HttpRequest


@admin.register(RegistroAuditoria)
class RegistroAuditoriaAdmin(admin.ModelAdmin):
    """Read-only for everyone, superusers included (RF-16, UC-13)."""

    list_display = [
        "fecha_hora",
        "usuario",
        "origen",
        "accion",
        "entidad",
        "registro_id",
    ]
    list_filter = ["origen", "accion", "entidad"]
    search_fields = ["entidad", "usuario__email"]
    list_select_related = ["usuario"]
    date_hierarchy = "fecha_hora"
    actions = None

    def has_view_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return request.user.has_perm("core.consultar_auditoria")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

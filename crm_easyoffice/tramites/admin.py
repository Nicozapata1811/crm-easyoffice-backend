from django.contrib import admin

from .models import EventoTramite
from .models import MotivoPendiente
from .models import TipoTramite
from .models import Tramite


@admin.register(TipoTramite)
class TipoTramiteAdmin(admin.ModelAdmin):
    list_display = ["nombre", "codigo", "activo"]
    list_filter = ["activo"]

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(MotivoPendiente)
class MotivoPendienteAdmin(admin.ModelAdmin):
    list_display = ["nombre", "codigo", "texto_cliente", "activo"]
    list_filter = ["activo"]

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class EventoTramiteInline(admin.TabularInline):
    model = EventoTramite
    extra = 0
    can_delete = False
    fields = [
        "fecha",
        "estado_anterior",
        "motivo_anterior",
        "estado_nuevo",
        "motivo_nuevo",
        "detalle",
        "usuario",
    ]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Tramite)
class TramiteAdmin(admin.ModelAdmin):
    """Read-only: a case changes state only through tramites.services."""

    list_display = ["folio", "tipo", "cliente", "estado", "motivo", "created_at"]
    list_filter = ["estado", "motivo", "tipo"]
    search_fields = ["folio"]
    inlines = [EventoTramiteInline]

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

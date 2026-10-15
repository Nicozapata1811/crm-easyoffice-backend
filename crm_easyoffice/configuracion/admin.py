from django.contrib import admin

from .models import ConfigEmpresa
from .models import CuentaPago
from .models import Marca


class SinEliminarAdmin(admin.ModelAdmin):
    """Configuration is deactivated, never deleted: contracts point at it."""

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(ConfigEmpresa)
class ConfigEmpresaAdmin(SinEliminarAdmin):
    list_display = ["razon_social", "rut"]
    autocomplete_fields = ["representante"]

    def has_add_permission(self, request) -> bool:
        return (
            super().has_add_permission(request) and not ConfigEmpresa.objects.exists()
        )


@admin.register(CuentaPago)
class CuentaPagoAdmin(SinEliminarAdmin):
    list_display = ["__str__", "banco", "titular", "activa"]
    list_filter = ["activa"]


@admin.register(Marca)
class MarcaAdmin(SinEliminarAdmin):
    list_display = ["nombre", "cuenta_pago_default", "activa"]
    list_filter = ["activa"]

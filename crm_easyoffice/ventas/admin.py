from django.contrib import admin

from .models import CicloPago
from .models import EventoPago
from .models import OrdenPago
from .models import Pago
from .models import Servicio
from .models import Venta


@admin.register(CicloPago)
class CicloPagoAdmin(admin.ModelAdmin):
    list_display = ["nombre", "codigo", "meses", "orden", "activo"]
    list_filter = ["activo"]


@admin.register(Servicio)
class ServicioAdmin(admin.ModelAdmin):
    list_display = [
        "codigo",
        "nombre",
        "precio_base",
        "precio_incluye_iva",
        "precio_confirmado",
        "ciclo_pago_default",
        "se_vende_en_portal",
        "visible_en_portal",
        "orden",
        "activo",
    ]
    list_editable = ["orden"]
    list_filter = [
        "activo",
        "se_vende_en_portal",
        "visible_en_portal",
        "precio_confirmado",
    ]
    search_fields = ["codigo", "nombre"]


class SoloLecturaAdmin(admin.ModelAdmin):
    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Venta)
class VentaAdmin(SoloLecturaAdmin):
    list_display = ["folio", "cliente", "estado", "total", "created_at"]
    list_filter = ["estado"]
    search_fields = ["folio"]


@admin.register(OrdenPago)
class OrdenPagoAdmin(SoloLecturaAdmin):
    list_display = ["referencia", "venta", "proveedor", "estado", "monto", "created_at"]
    list_filter = ["estado", "proveedor"]


@admin.register(Pago)
class PagoAdmin(SoloLecturaAdmin):
    list_display = ["orden", "tipo", "monto", "marca", "ultimos_digitos", "pagado_en"]


@admin.register(EventoPago)
class EventoPagoAdmin(SoloLecturaAdmin):
    list_display = ["proveedor", "evento", "resultado", "orden", "recibido_en"]
    list_filter = ["proveedor", "evento", "resultado"]

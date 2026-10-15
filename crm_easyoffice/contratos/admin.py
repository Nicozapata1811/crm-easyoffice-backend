from django.contrib import admin

from .models import Contrato
from .models import CorrelativoFolio
from .models import DuracionContrato
from .models import ServicioContratado


class SoloLecturaMixin:
    """Contracts are created through contratos.services, never here.

    That keeps the folio counter and the copied prices out of reach of a
    hand edit.
    """

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class ServicioContratadoInline(SoloLecturaMixin, admin.TabularInline):
    model = ServicioContratado
    extra = 0
    fields = [
        "orden",
        "nombre",
        "precio",
        "precio_incluye_iva",
        "ciclo_pago",
        "inmueble",
    ]
    readonly_fields = fields


@admin.register(Contrato)
class ContratoAdmin(SoloLecturaMixin, admin.ModelAdmin):
    list_display = [
        "folio",
        "cliente",
        "marca",
        "fecha_inicio",
        "fecha_vencimiento",
        "estado",
    ]
    list_filter = ["estado", "marca", "codigo_sucursal", "anio_folio"]
    search_fields = ["folio"]
    inlines = [ServicioContratadoInline]


@admin.register(DuracionContrato)
class DuracionContratoAdmin(admin.ModelAdmin):
    list_display = ["meses", "activa"]
    list_filter = ["activa"]

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(CorrelativoFolio)
class CorrelativoFolioAdmin(SoloLecturaMixin, admin.ModelAdmin):
    list_display = ["anio", "ultimo"]

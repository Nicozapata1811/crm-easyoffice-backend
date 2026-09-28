from django.contrib import admin

from .models import Prospecto


@admin.register(Prospecto)
class ProspectoAdmin(admin.ModelAdmin):
    list_display = [
        "nombre",
        "servicio_interes",
        "plan",
        "estado",
        "origen",
        "recibido_en",
    ]
    list_filter = ["estado", "origen", "servicio_desconocido", "plan_desconocido"]
    search_fields = ["nombre", "email", "telefono"]
    date_hierarchy = "recibido_en"
    fields = [
        "estado",
        "cliente",
        "nombre",
        "email",
        "telefono",
        "servicio_interes",
        "servicio_desconocido",
        "plan",
        "plan_desconocido",
        "mensaje",
        "origen",
        "formato",
        "recibido_en",
        "payload_original",
        "dedup_key",
    ]
    readonly_fields = [
        "nombre",
        "email",
        "telefono",
        "servicio_interes",
        "servicio_desconocido",
        "plan",
        "plan_desconocido",
        "mensaje",
        "origen",
        "formato",
        "recibido_en",
        "payload_original",
        "dedup_key",
    ]
    raw_id_fields = ["cliente"]

    def has_add_permission(self, request):
        return False

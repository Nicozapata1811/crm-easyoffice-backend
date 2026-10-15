"""Admin for the parties other records point at.

They are registered mainly so other admins (authorisers, the issuer's
configuration) can search them with autocomplete fields. Every field is
personal data: access follows the clientes permissions of each role, and
records are never deleted from here (RF-04).
"""

from django.contrib import admin

from .models import Empresa
from .models import Persona
from .models import RepresentanteLegal


class SinEliminarAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Persona)
class PersonaAdmin(SinEliminarAdmin):
    list_display = ["rut", "nombre_completo", "email", "activo"]
    list_filter = ["activo"]
    search_fields = ["rut", "nombres", "apellido_paterno", "apellido_materno"]


@admin.register(Empresa)
class EmpresaAdmin(SinEliminarAdmin):
    list_display = ["rut", "razon_social", "nombre_fantasia", "activa"]
    list_filter = ["activa"]
    search_fields = ["rut", "razon_social", "nombre_fantasia"]


@admin.register(RepresentanteLegal)
class RepresentanteLegalAdmin(SinEliminarAdmin):
    list_display = ["persona", "empresa", "vigente_desde", "vigente_hasta", "activo"]
    list_filter = ["activo"]
    search_fields = [
        "persona__rut",
        "persona__nombres",
        "persona__apellido_paterno",
        "empresa__rut",
        "empresa__razon_social",
    ]
    autocomplete_fields = ["persona", "empresa"]

from django.contrib import admin

from .models import Documento
from .models import Firmante
from .models import PlantillaDocumento
from .models import VersionPlantilla


class SoloLecturaAdmin(admin.ModelAdmin):
    """Templates and documents are written by the services, never by hand."""

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(PlantillaDocumento)
class PlantillaDocumentoAdmin(SoloLecturaAdmin):
    list_display = ["codigo", "nombre", "activa"]


@admin.register(VersionPlantilla)
class VersionPlantillaAdmin(SoloLecturaAdmin):
    list_display = ["plantilla", "numero", "sha256", "vigente_desde"]
    # The file has no URL (private storage): show its hash, not a link.
    exclude = ["archivo"]


class FirmanteInline(admin.TabularInline):
    model = Firmante
    extra = 0
    can_delete = False
    fields = ["orden", "rol", "persona", "firmado_en"]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Documento)
class DocumentoAdmin(SoloLecturaAdmin):
    list_display = ["tramite", "version", "estado", "version_plantilla", "generado_en"]
    list_filter = ["estado"]
    search_fields = ["tramite__folio"]
    exclude = ["archivo_docx", "archivo_pdf", "archivo_firmado"]
    inlines = [FirmanteInline]

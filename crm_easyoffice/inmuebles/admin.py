from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import Autorizante
from .models import Oficina
from .models import validar_documento_identidad
from .services import guardar_documento_identidad


@admin.register(Oficina)
class OficinaAdmin(admin.ModelAdmin):
    list_display = [
        "nombre",
        "tipo",
        "codigo_sucursal",
        "comuna",
        "rol_avaluo",
        "activa",
    ]
    list_filter = ["tipo", "activa"]
    search_fields = ["nombre", "codigo_sucursal", "comuna", "rol_avaluo"]

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class AutorizanteForm(forms.ModelForm):
    """Uploads the identity card through the service, never through the field.

    The model field's widget would render a link to the file's URL, which
    private storage refuses to build.
    """

    nuevo_documento = forms.FileField(
        label=_("cédula de identidad"),
        required=False,
        help_text=_("JPG, PNG or PDF. Replaces the current file."),
    )

    class Meta:
        model = Autorizante
        fields = [
            "inmueble",
            "persona",
            "empresa",
            "representante",
            "vigente_desde",
            "vigente_hasta",
            "activo",
        ]

    def clean_nuevo_documento(self):
        archivo = self.cleaned_data.get("nuevo_documento")
        if archivo:
            validar_documento_identidad(archivo)
        return archivo


@admin.register(Autorizante)
class AutorizanteAdmin(admin.ModelAdmin):
    form = AutorizanteForm
    list_display = ["__str__", "inmueble", "vigente_desde", "vigente_hasta", "activo"]
    list_filter = ["activo", "inmueble"]
    raw_id_fields = ["persona", "empresa", "representante"]
    readonly_fields = ["documento_actual"]

    @admin.display(description=_("cédula registrada"))
    def documento_actual(self, obj: Autorizante) -> str:
        if not obj.pk or not obj.documento_identidad:
            return "—"
        url = reverse("inmuebles:documento-identidad", args=[obj.pk])
        return format_html('<a href="{}">{}</a>', url, _("Download"))

    def save_model(self, request, obj, form, change) -> None:
        super().save_model(request, obj, form, change)
        if archivo := form.cleaned_data.get("nuevo_documento"):
            guardar_documento_identidad(obj, archivo)

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

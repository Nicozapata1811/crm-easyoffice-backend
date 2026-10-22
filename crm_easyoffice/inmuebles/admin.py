from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.html import format_html_join
from django.utils.translation import gettext_lazy as _

from .models import Autorizante
from .models import Oficina
from .models import TipoInmueble
from .models import validar_documento_identidad
from .services import guardar_documento_identidad
from .services import problemas_para_bodega
from .services import problemas_para_domicilio


def _lista(problemas: list[str]) -> str:
    return format_html(
        "<ul>{}</ul>",
        format_html_join("", "<li>{}</li>", ((p,) for p in problemas)),
    )


@admin.register(Oficina)
class OficinaAdmin(admin.ModelAdmin):
    list_display = [
        "nombre",
        "tipo",
        "codigo_sucursal",
        "comuna",
        "rol_avaluo",
        "activa",
        "lista_para_domicilio",
        "lista_para_bodega",
    ]
    list_filter = ["tipo", "activa"]
    search_fields = ["nombre", "codigo_sucursal", "comuna", "rol_avaluo"]
    readonly_fields = ["problemas_domicilio", "problemas_bodega"]

    @admin.display(description=_("lista para domicilio (PLT-01)"), boolean=True)
    def lista_para_domicilio(self, obj: Oficina) -> bool | None:
        if not obj.codigo_sucursal:
            return None
        return not problemas_para_domicilio(obj, timezone.localdate())

    @admin.display(description=_("lista para bodega (PLT-02)"), boolean=True)
    def lista_para_bodega(self, obj: Oficina) -> bool | None:
        if obj.tipo != TipoInmueble.BODEGA:
            return None
        return not problemas_para_bodega(obj, timezone.localdate())

    @admin.display(description=_("pendiente para ofrecer el domicilio en línea"))
    def problemas_domicilio(self, obj: Oficina) -> str:
        if not obj.pk or not obj.codigo_sucursal:
            return "—"
        problemas = problemas_para_domicilio(obj, timezone.localdate())
        if not problemas:
            return _("Nothing: the portal offers this branch.")
        return _lista(problemas)

    @admin.display(description=_("pendiente para ofrecer la bodega (PLT-02)"))
    def problemas_bodega(self, obj: Oficina) -> str:
        if not obj.pk or obj.tipo != TipoInmueble.BODEGA:
            return "—"
        problemas = problemas_para_bodega(obj, timezone.localdate())
        if not problemas:
            return _("Nothing: executives can choose this warehouse.")
        return _lista(problemas)

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
    nuevo_reverso = forms.FileField(
        label=_("cédula de identidad (reverso)"),
        required=False,
        help_text=_(
            "JPG or PNG to print it in the domicile contract. Replaces the "
            "current file.",
        ),
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

    def clean_nuevo_reverso(self):
        archivo = self.cleaned_data.get("nuevo_reverso")
        if archivo:
            validar_documento_identidad(archivo)
        return archivo


@admin.register(Autorizante)
class AutorizanteAdmin(admin.ModelAdmin):
    form = AutorizanteForm
    list_display = ["__str__", "inmueble", "vigente_desde", "vigente_hasta", "activo"]
    list_filter = ["activo", "inmueble"]
    autocomplete_fields = ["inmueble", "persona", "empresa", "representante"]
    readonly_fields = ["documento_actual", "reverso_actual"]
    fieldsets = [
        (None, {"fields": ["inmueble", "vigente_desde", "vigente_hasta", "activo"]}),
        (
            _("Propietario"),
            {
                "description": _(
                    "Either a person, or a company with its legal representative. "
                    "Search by RUT or name.",
                ),
                "fields": ["persona", "empresa", "representante"],
            },
        ),
        (
            _("Cédula de identidad"),
            {
                "fields": [
                    "nuevo_documento",
                    "documento_actual",
                    "nuevo_reverso",
                    "reverso_actual",
                ],
            },
        ),
    ]

    @admin.display(description=_("cédula registrada"))
    def documento_actual(self, obj: Autorizante) -> str:
        if not obj.pk or not obj.documento_identidad:
            return "—"
        url = reverse("inmuebles:documento-identidad", args=[obj.pk])
        return format_html('<a href="{}">{}</a>', url, _("Download"))

    @admin.display(description=_("reverso registrado"))
    def reverso_actual(self, obj: Autorizante) -> str:
        if not obj.pk or not obj.documento_identidad_reverso:
            return "—"
        url = reverse("inmuebles:documento-identidad", args=[obj.pk])
        return format_html('<a href="{}?lado=reverso">{}</a>', url, _("Download"))

    def save_model(self, request, obj, form, change) -> None:
        super().save_model(request, obj, form, change)
        if archivo := form.cleaned_data.get("nuevo_documento"):
            guardar_documento_identidad(obj, archivo)
        if archivo := form.cleaned_data.get("nuevo_reverso"):
            guardar_documento_identidad(obj, archivo, reverso=True)

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class VentasConfig(AppConfig):
    name = "crm_easyoffice.ventas"
    verbose_name = _("Ventas")

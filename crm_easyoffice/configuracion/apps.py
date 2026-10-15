from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ConfiguracionConfig(AppConfig):
    name = "crm_easyoffice.configuracion"
    verbose_name = _("Configuración")

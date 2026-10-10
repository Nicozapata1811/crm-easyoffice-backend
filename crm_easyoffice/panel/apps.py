from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PanelConfig(AppConfig):
    name = "crm_easyoffice.panel"
    verbose_name = _("Panel operativo")

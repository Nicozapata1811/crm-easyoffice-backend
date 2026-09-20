from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class IntegrationsConfig(AppConfig):
    name = "crm_easyoffice.integrations"
    verbose_name = _("Integrations")

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class MigracionConfig(AppConfig):
    name = "crm_easyoffice.migracion"
    verbose_name = _("Migracion")

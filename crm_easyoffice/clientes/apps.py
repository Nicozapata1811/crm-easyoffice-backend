from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ClientesConfig(AppConfig):
    name = "crm_easyoffice.clientes"
    verbose_name = _("Clientes")

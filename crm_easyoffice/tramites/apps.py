from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class TramitesConfig(AppConfig):
    name = "crm_easyoffice.tramites"
    verbose_name = _("Tramites")

    def ready(self) -> None:
        from crm_easyoffice.ventas.services import venta_pagada  # noqa: PLC0415

        from .receivers import al_pagar_venta  # noqa: PLC0415

        venta_pagada.connect(al_pagar_venta, dispatch_uid="tramites.al_pagar_venta")

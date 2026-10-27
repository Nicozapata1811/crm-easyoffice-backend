from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DocumentosConfig(AppConfig):
    name = "crm_easyoffice.documentos"
    verbose_name = _("Documentos")

    def ready(self) -> None:
        from crm_easyoffice.tramites.signals import documento_requerido  # noqa: PLC0415
        from crm_easyoffice.tramites.signals import firma_requerida  # noqa: PLC0415

        from .receivers import al_requerir_documento  # noqa: PLC0415
        from .receivers import al_requerir_firma  # noqa: PLC0415

        documento_requerido.connect(
            al_requerir_documento,
            dispatch_uid="documentos.al_requerir_documento",
        )
        firma_requerida.connect(
            al_requerir_firma,
            dispatch_uid="documentos.al_requerir_firma",
        )

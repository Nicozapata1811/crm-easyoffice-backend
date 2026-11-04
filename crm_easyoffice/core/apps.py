from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CoreConfig(AppConfig):
    name = "crm_easyoffice.core"
    verbose_name = _("Core")

    def ready(self) -> None:
        from celery.signals import task_postrun  # noqa: PLC0415
        from celery.signals import task_prerun  # noqa: PLC0415
        from django.contrib.auth.signals import user_logged_in  # noqa: PLC0415
        from django.contrib.auth.signals import user_logged_out  # noqa: PLC0415
        from django.contrib.auth.signals import user_login_failed  # noqa: PLC0415
        from django.db.backends.signals import connection_created  # noqa: PLC0415

        from .auditoria import contexto  # noqa: PLC0415
        from .auditoria import eventos  # noqa: PLC0415

        connection_created.connect(
            contexto.instalar_aplicador,
            dispatch_uid="core.auditoria.instalar_aplicador",
        )
        user_logged_in.connect(
            eventos.al_iniciar_sesion,
            dispatch_uid="core.auditoria.login",
        )
        user_logged_out.connect(
            eventos.al_cerrar_sesion,
            dispatch_uid="core.auditoria.logout",
        )
        user_login_failed.connect(
            eventos.al_fallar_inicio_sesion,
            dispatch_uid="core.auditoria.login_fallido",
        )
        task_prerun.connect(
            contexto.al_iniciar_tarea,
            dispatch_uid="core.auditoria.tarea",
        )
        task_postrun.connect(
            contexto.al_terminar_tarea,
            dispatch_uid="core.auditoria.fin_tarea",
        )

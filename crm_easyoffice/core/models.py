"""Shared model bases for the domain apps."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models.functions import Now
from django.utils.translation import gettext_lazy as _


class TimestampedModel(models.Model):
    """Abstract base recording when a row was created and last changed.

    This is convenience metadata, not the audit trail. The append-only audit
    log required by CLAUDE.md is a separate concern owned by this app.
    """

    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        abstract = True


class PermisoSistema(models.Model):
    """Holder for permissions that guard a feature rather than a model.

    No table is created. Roles are ``auth.Group`` rows, and these permissions
    are attached to them like any model permission.
    """

    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ("view_dashboard", _("Can view the operational dashboard")),
        ]

    def __str__(self) -> str:
        return str(self._meta.verbose_name)


class RegistroAuditoriaError(Exception):
    """The audit log is append-only (RF-16, RN-35)."""


class RegistroAuditoria(models.Model):
    """One entry of the audit log (RF-15, RS-04; MOD-001 §3.8).

    Row changes are written by database triggers (AD-08), installed on the
    tables listed in ``core.auditoria.registro``; access events by
    ``core.auditoria.registrar_evento``. The database rejects UPDATE, DELETE
    and TRUNCATE on this table, and this class refuses them too.
    """

    class Origen(models.TextChoices):
        API = "api", _("API del backoffice")
        PORTAL = "portal", _("Portal del cliente")
        ADMIN = "admin", _("Panel de administración")
        SISTEMA = "sistema", _("Sistema")

    class Accion(models.TextChoices):
        CREAR = "crear", _("Creación")
        MODIFICAR = "modificar", _("Modificación")
        ELIMINAR = "eliminar", _("Eliminación")
        INICIO_SESION = "inicio_sesion", _("Inicio de sesión")
        CIERRE_SESION = "cierre_sesion", _("Cierre de sesión")
        INICIO_SESION_FALLIDO = "inicio_sesion_fallido", _("Inicio de sesión fallido")
        DESCARGA_DOCUMENTO = "descarga_documento", _("Descarga de documento")
        ACCESO_DOCUMENTO_IDENTIDAD = (
            "acceso_documento_identidad",
            _("Acceso a documento de identidad"),
        )

    fecha_hora = models.DateTimeField(_("fecha y hora"), db_default=Now())
    # PROTECT: a user who acted is deactivated, never deleted.
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("usuario"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    origen = models.CharField(_("origen"), max_length=10, choices=Origen.choices)
    accion = models.CharField(_("acción"), max_length=30, choices=Accion.choices)
    entidad = models.CharField(_("entidad"), max_length=100)
    registro_id = models.BigIntegerField(_("registro"), null=True, blank=True)
    valor_anterior = models.JSONField(_("valor anterior"), null=True, blank=True)
    valor_nuevo = models.JSONField(_("valor nuevo"), null=True, blank=True)
    direccion_ip = models.GenericIPAddressField(
        _("dirección IP"),
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("registro de auditoría")
        verbose_name_plural = _("registros de auditoría")
        ordering = ["-fecha_hora", "-pk"]
        # Nobody may be granted add, change or delete, superusers aside.
        default_permissions = ()
        permissions = [
            ("consultar_auditoria", _("Puede consultar el registro de auditoría")),
        ]
        indexes = [
            models.Index(
                fields=["entidad", "registro_id"],
                name="auditoria_registro_idx",
            ),
            models.Index(fields=["fecha_hora"], name="auditoria_fecha_idx"),
        ]

    def __str__(self) -> str:
        registro = self.registro_id or ""
        return f"{self.get_accion_display()} · {self.entidad} {registro}".strip()

    def save(self, *args, **kwargs) -> None:
        if self.pk is not None:
            raise RegistroAuditoriaError
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RegistroAuditoriaError

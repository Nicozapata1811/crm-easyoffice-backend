"""Shared model bases for the domain apps."""

from __future__ import annotations

from django.db import models
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

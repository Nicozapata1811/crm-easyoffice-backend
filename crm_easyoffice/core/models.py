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

"""Leads received from the public website.

Every field here is personal data under Ley 21.719, and no real record is
ever committed to this repository.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from crm_easyoffice.core.models import TimestampedModel


class Prospecto(TimestampedModel):
    """A lead, as submitted through one of the website's forms.

    Fields that came from the submission are never edited afterwards; staff
    only move ``estado`` and link ``cliente`` once the lead converts.

    ASSUMPTION: pending validation with Easy Office. The four estados and the
    absence of transition rules between them.
    """

    class Estado(models.TextChoices):
        NUEVO = "nuevo", _("nuevo")
        CONTACTADO = "contactado", _("contactado")
        CONVERTIDO = "convertido", _("convertido")
        DESCARTADO = "descartado", _("descartado")

    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=Estado.choices,
        default=Estado.NUEVO,
    )
    formato = models.CharField(
        _("formato"),
        max_length=30,
        help_text=_("Source adapter that parsed the submission."),
    )
    origen = models.CharField(_("origen"), max_length=50)
    nombre = models.CharField(_("nombre"), max_length=200)
    email = models.EmailField(_("email"), blank=True)
    telefono = models.CharField(_("teléfono"), max_length=30, blank=True)
    servicio_interes = models.CharField(
        _("servicio de interés"),
        max_length=100,
        blank=True,
    )
    plan = models.CharField(_("plan"), max_length=50, blank=True)
    servicio_desconocido = models.BooleanField(
        _("servicio desconocido"),
        default=False,
        help_text=_("A service was given but is not in the catalogue."),
    )
    plan_desconocido = models.BooleanField(
        _("plan desconocido"),
        default=False,
        help_text=_("A plan was given but is not in the catalogue."),
    )
    mensaje = models.TextField(_("mensaje"), blank=True)
    recibido_en = models.DateTimeField(_("recibido en"))
    payload_original = models.JSONField(_("payload original"))
    dedup_key = models.CharField(
        _("clave de deduplicación"),
        max_length=64,
        unique=True,
        editable=False,
    )
    cliente = models.ForeignKey(
        "clientes.Cliente",
        verbose_name=_("cliente"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="prospectos",
    )

    class Meta:
        verbose_name = _("prospecto")
        verbose_name_plural = _("prospectos")
        ordering = ["-recibido_en"]

    def __str__(self) -> str:
        return f"{self.nombre} ({self.get_estado_display()})"

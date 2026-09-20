"""Offices and the tax domiciles assigned to them."""

from __future__ import annotations

from django.db import models
from django.db.models import F
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from crm_easyoffice.core.models import TimestampedModel


class Oficina(TimestampedModel):
    """A property Easy Office can assign as a company's tax domicile.

    ASSUMPTION: pending validation with Easy Office. comuna and region are
    free text rather than lookup tables, and nothing limits how many companies
    may be domiciled at one office.
    """

    rol_avaluo = models.CharField(
        _("rol de avalúo"),
        max_length=20,
        unique=True,
        help_text=_("Property tax roll number assigned by the SII."),
    )
    nombre = models.CharField(_("nombre"), max_length=120)
    calle = models.CharField(_("calle"), max_length=255)
    numero = models.CharField(_("número"), max_length=20)
    unidad = models.CharField(
        _("unidad"),
        max_length=20,
        blank=True,
        help_text=_("Office or apartment number, when applicable."),
    )
    comuna = models.CharField(_("comuna"), max_length=100)
    region = models.CharField(_("región"), max_length=100)
    activa = models.BooleanField(_("activa"), default=True)

    class Meta:
        verbose_name = _("oficina")
        verbose_name_plural = _("oficinas")
        ordering = ["region", "comuna", "nombre"]

    def __str__(self) -> str:
        return f"{self.nombre} ({self.comuna})"

    @property
    def direccion_completa(self) -> str:
        """Street address on one line, omitting an absent unit."""
        parts = [f"{self.calle} {self.numero}".strip(), self.unidad, self.comuna]
        return ", ".join(part for part in parts if part)


class AsignacionDomicilio(TimestampedModel):
    """A company's registered tax domicile at an office, for a period.

    Domicilio tributario is a service the company sells, so the assignment is
    periodised: an office's current occupants are those whose period covers
    today.

    ASSUMPTION: pending validation with Easy Office. Nothing prevents a
    company from holding two overlapping active domiciles. That is almost
    certainly invalid in practice, but it is a business rule and RN-001 is
    expected to state it before it is enforced here.
    """

    empresa = models.ForeignKey(
        "clientes.Empresa",
        verbose_name=_("empresa"),
        on_delete=models.PROTECT,
        related_name="domicilios",
    )
    oficina = models.ForeignKey(
        Oficina,
        verbose_name=_("oficina"),
        on_delete=models.PROTECT,
        related_name="asignaciones",
    )
    vigente_desde = models.DateField(_("vigente desde"))
    vigente_hasta = models.DateField(
        _("vigente hasta"),
        null=True,
        blank=True,
        help_text=_("Empty means the domicile has no end date."),
    )
    activa = models.BooleanField(_("activa"), default=True)

    class Meta:
        verbose_name = _("asignación de domicilio")
        verbose_name_plural = _("asignaciones de domicilio")
        ordering = ["-vigente_desde"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(vigente_hasta__isnull=True)
                    | Q(vigente_hasta__gt=F("vigente_desde"))
                ),
                name="domicilio_periodo_valido",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.empresa} @ {self.oficina}"

"""Client records: natural persons, companies, and legal representation.

Persona, Empresa and RepresentanteLegal are deliberately distinct entities: a
contract is signed by a company's legal representative, not by "the client".

Every field here is personal data under Ley 21.719. The model collects only
what a trámite needs, and no real record is ever committed to this repository.
"""

from __future__ import annotations

from django.db import models
from django.db.models import F
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from crm_easyoffice.core.models import TimestampedModel
from crm_easyoffice.core.validators import validate_rut


class Persona(TimestampedModel):
    """A natural person, whether a client, a legal representative, or both.

    Being recorded here does not make someone a client. That role is carried
    by Cliente.

    ASSUMPTION: pending validation with Easy Office. apellido_materno is
    optional because foreign nationals frequently have no second surname, and
    contact details are optional at record level because which ones are
    mandatory is expected to vary by trámite.
    """

    rut = models.CharField(
        _("RUT"),
        max_length=12,
        unique=True,
        validators=[validate_rut],
        help_text=_("Without dots and with a hyphen, for example 12345678-5."),
    )
    nombres = models.CharField(_("nombres"), max_length=100)
    apellido_paterno = models.CharField(_("apellido paterno"), max_length=100)
    apellido_materno = models.CharField(
        _("apellido materno"),
        max_length=100,
        blank=True,
    )
    email = models.EmailField(_("email"), blank=True)
    telefono = models.CharField(_("teléfono"), max_length=20, blank=True)
    activo = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("persona")
        verbose_name_plural = _("personas")
        ordering = ["apellido_paterno", "apellido_materno", "nombres"]

    def __str__(self) -> str:
        return f"{self.nombre_completo} ({self.rut})"

    @property
    def nombre_completo(self) -> str:
        """Full name, omitting the second surname when absent."""
        parts = [self.nombres, self.apellido_paterno, self.apellido_materno]
        return " ".join(part for part in parts if part)


class Empresa(TimestampedModel):
    """A legal entity.

    ASSUMPTION: pending validation with Easy Office. giro is free text rather
    than a SII activity code, and the company's legal form (SpA, Ltda, EIRL)
    is not recorded. Both are likely to appear in document templates.
    """

    rut = models.CharField(
        _("RUT"),
        max_length=12,
        unique=True,
        validators=[validate_rut],
        help_text=_("Without dots and with a hyphen, for example 76543210-K."),
    )
    razon_social = models.CharField(_("razón social"), max_length=255)
    nombre_fantasia = models.CharField(
        _("nombre de fantasía"),
        max_length=255,
        blank=True,
    )
    giro = models.CharField(_("giro"), max_length=255, blank=True)
    email = models.EmailField(_("email"), blank=True)
    telefono = models.CharField(_("teléfono"), max_length=20, blank=True)
    activa = models.BooleanField(_("activa"), default=True)

    class Meta:
        verbose_name = _("empresa")
        verbose_name_plural = _("empresas")
        ordering = ["razon_social"]

    def __str__(self) -> str:
        return f"{self.razon_social} ({self.rut})"


class Cliente(TimestampedModel):
    """A party that is a customer of Easy Office.

    Exactly one of persona or empresa is set. Downstream records point here
    rather than at Persona or Empresa directly, so the choice between the two
    is resolved once instead of at every table that references a client.

    ASSUMPTION: pending validation with Easy Office. CLAUDE.md names only
    Persona, Empresa and RepresentanteLegal. This entity is inferred from the
    product being a CRM, from clients being portal users, and from a
    representative-only Persona never being a client. Client-level attributes
    such as the assigned executive or the date of first contact are not
    modelled until the counterpart confirms them.
    """

    persona = models.OneToOneField(
        Persona,
        verbose_name=_("persona"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cliente",
    )
    empresa = models.OneToOneField(
        Empresa,
        verbose_name=_("empresa"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cliente",
    )
    activo = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("cliente")
        verbose_name_plural = _("clientes")
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(persona__isnull=False, empresa__isnull=True)
                    | Q(persona__isnull=True, empresa__isnull=False)
                ),
                name="cliente_exactamente_una_parte",
            ),
        ]

    def __str__(self) -> str:
        return str(self.persona or self.empresa)

    @property
    def es_empresa(self) -> bool:
        return self.empresa_id is not None


class RepresentanteLegal(TimestampedModel):
    """A person's authority to act for a company during a period.

    This models the representation itself, not a role flag on Persona, because
    it starts and ends. Asking who may sign for a company on a given date is a
    query over vigente_desde and vigente_hasta.

    ASSUMPTION: pending validation with Easy Office. Overlapping
    representations are permitted, since companies may have several
    representatives at once, and no field records whether they act jointly or
    severally. Both are business rules that RN-001 is expected to define.
    """

    persona = models.ForeignKey(
        Persona,
        verbose_name=_("persona"),
        on_delete=models.PROTECT,
        related_name="representaciones",
    )
    empresa = models.ForeignKey(
        Empresa,
        verbose_name=_("empresa"),
        on_delete=models.PROTECT,
        related_name="representantes",
    )
    vigente_desde = models.DateField(_("vigente desde"))
    vigente_hasta = models.DateField(
        _("vigente hasta"),
        null=True,
        blank=True,
        help_text=_("Empty means the representation has no end date."),
    )
    activo = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("representante legal")
        verbose_name_plural = _("representantes legales")
        ordering = ["-vigente_desde"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(vigente_hasta__isnull=True)
                    | Q(vigente_hasta__gt=F("vigente_desde"))
                ),
                name="representante_periodo_valido",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.persona} → {self.empresa}"

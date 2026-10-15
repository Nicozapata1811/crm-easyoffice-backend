"""Client records: natural persons, companies, and legal representation.

Persona, Empresa and RepresentanteLegal are deliberately distinct entities: a
contract is signed by a company's legal representative, not by "the client".

Every field here is personal data under Ley 21.719. The model collects only
what a trámite needs, and no real record is ever committed to this repository.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db import transaction
from django.db.models import F
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from crm_easyoffice.core.models import TimestampedModel
from crm_easyoffice.core.validators import validate_rut


class EstadoCivil(models.TextChoices):
    """Civil status as recorded by the Registro Civil, including Ley 20.830.

    ASSUMPTION: pending validation with Easy Office. Labels are neutral; the
    gendered form a contract prints ("casada", "casado") is left to the
    document template.
    """

    SOLTERO = "soltero", _("soltero(a)")
    CASADO = "casado", _("casado(a)")
    VIUDO = "viudo", _("viudo(a)")
    DIVORCIADO = "divorciado", _("divorciado(a)")
    SEPARADO_JUDICIALMENTE = "separado_judicialmente", _("separado(a) judicialmente")
    CONVIVIENTE_CIVIL = "conviviente_civil", _("conviviente civil")


class Persona(TimestampedModel):
    """A natural person, whether a client, a legal representative, or both.

    Being recorded here does not make someone a client. That role is carried
    by Cliente.

    ASSUMPTION: pending validation with Easy Office. apellido_materno is
    optional because foreign nationals frequently have no second surname, and
    contact details are optional at record level because which ones are
    mandatory is expected to vary by trámite.

    nacionalidad, estado_civil and profesion are optional too: contracts ask
    them of Easy Office's representative, property owners, shareholders and
    lessors, but not of a client company's representative.
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
    nacionalidad = models.CharField(_("nacionalidad"), max_length=60, blank=True)
    estado_civil = models.CharField(
        _("estado civil"),
        max_length=30,
        choices=EstadoCivil,
        blank=True,
    )
    profesion = models.CharField(_("profesión"), max_length=100, blank=True)
    domicilio = models.CharField(
        _("domicilio"),
        max_length=255,
        blank=True,
        help_text=_("Street and number of the person's own address."),
    )
    comuna = models.CharField(_("comuna"), max_length=100, blank=True)
    region = models.CharField(_("región"), max_length=100, blank=True)
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


class TipoCliente(models.TextChoices):
    PERSONA = "persona", _("persona")
    EMPRESA = "empresa", _("empresa")


def format_codigo(pk: int) -> str:
    """Return the internal code for a client primary key, e.g. ``CLI-000042``."""
    return f"CLI-{pk:06d}"


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

    ASSUMPTION: pending validation with Easy Office. The codigo format is
    ours; their spreadsheet may already number clients (HU-32).

    codigo was called folio until the folio moved to the contract (RN-38):
    Easy Office's folio identifies a contract, not a client.
    """

    codigo = models.CharField(  # noqa: DJ001 - null until save() assigns it
        _("código"),
        max_length=12,
        unique=True,
        null=True,
        editable=False,
        help_text=_("Internal client code, assigned on creation from the primary key."),
    )
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

    def save(self, *args, **kwargs) -> None:
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.codigo:
                self.codigo = format_codigo(self.pk)
                super().save(update_fields=["codigo"])

    @property
    def es_empresa(self) -> bool:
        return self.empresa_id is not None

    @property
    def tipo(self) -> str:
        return TipoCliente.EMPRESA if self.es_empresa else TipoCliente.PERSONA

    @property
    def parte(self) -> Persona | Empresa:
        """The Persona or Empresa this client is."""
        return self.empresa if self.es_empresa else self.persona  # type: ignore[return-value]

    @property
    def nombre(self) -> str:
        """Full name for a person, razón social for a company."""
        if self.empresa is not None:
            return self.empresa.razon_social
        return self.persona.nombre_completo if self.persona else ""


class RepresentanteLegal(TimestampedModel):
    """A person's authority to act for a company during a period.

    This models the representation itself, not a role flag on Persona, because
    it starts and ends. Asking who may sign for a company on a given date is a
    query over vigente_desde and vigente_hasta.

    The personería (fecha_instrumento, sitio_o_notaria) belongs here, not on
    Empresa: it is this person's authority for this company.

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
    fecha_instrumento = models.DateField(
        _("fecha del instrumento"),
        null=True,
        blank=True,
        help_text=_("Date of the deed or updated statute granting the personería."),
    )
    sitio_o_notaria = models.CharField(
        _("sitio o notaría"),
        max_length=255,
        blank=True,
        help_text=_("Registry or notary office where the personería was granted."),
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


class CuentaCliente(TimestampedModel):
    """A portal login for a client (HU-03).

    Kept apart from the staff roles: a client user has no group, so staff
    permission checks never let them through.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name=_("usuario"),
        on_delete=models.CASCADE,
        related_name="cuenta_cliente",
    )
    cliente = models.ForeignKey(
        Cliente,
        verbose_name=_("cliente"),
        on_delete=models.PROTECT,
        related_name="cuentas",
    )
    activa = models.BooleanField(_("activa"), default=True)

    class Meta:
        verbose_name = _("cuenta de cliente")
        verbose_name_plural = _("cuentas de cliente")

    def __str__(self) -> str:
        return f"{self.user} → {self.cliente}"

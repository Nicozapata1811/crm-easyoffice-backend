"""Properties (branch offices and warehouses) and who authorises their use."""

from __future__ import annotations

import uuid
from pathlib import PurePath

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import F
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from crm_easyoffice.core.models import TimestampedModel
from crm_easyoffice.core.storage import get_private_storage
from crm_easyoffice.core.validators import FILE_SIGNATURES
from crm_easyoffice.core.validators import validate_file_signature
from crm_easyoffice.core.validators import validate_max_file_size


class TipoInmueble(models.TextChoices):
    OFICINA = "oficina", _("oficina")
    BODEGA = "bodega", _("bodega")


class Oficina(TimestampedModel):
    """A property: a branch office or a warehouse.

    Branch offices can be assigned as a company's tax domicile and carry the
    branch code that heads a contract folio (LF-0007-2026). A warehouse
    (PLT-02) is just another property with its own address and rol de avalúo.
    The class keeps its original name so foreign keys and permission codenames
    stay stable.

    ASSUMPTION: pending validation with Easy Office. comuna and region are
    free text rather than lookup tables, and nothing limits how many companies
    may be domiciled at one office.
    """

    tipo = models.CharField(
        _("tipo"),
        max_length=20,
        choices=TipoInmueble.choices,
        default=TipoInmueble.OFICINA,
    )
    # NULL rather than "" so that only branches compete for uniqueness.
    codigo_sucursal = models.CharField(
        _("código de sucursal"),
        max_length=4,
        unique=True,
        null=True,
        blank=True,
        validators=[RegexValidator(r"^[A-Z]{2,4}$")],
        help_text=_("Heads the contract folio, for example LF. Empty for warehouses."),
    )
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
    # ASSUMPTION: pending validation with Easy Office. The SII unit printed
    # in the domicile authorisation differs per branch (OB-02); its text is
    # not known yet.
    unidad_sii = models.CharField(
        _("unidad del SII"),
        max_length=255,
        blank=True,
        help_text=_("SII unit named in the domicile authorisation."),
    )
    municipalidad = models.CharField(_("municipalidad"), max_length=120, blank=True)
    activa = models.BooleanField(_("activa"), default=True)

    class Meta:
        verbose_name = _("inmueble")
        verbose_name_plural = _("inmuebles")
        ordering = ["region", "comuna", "nombre"]
        constraints = [
            models.CheckConstraint(
                condition=Q(tipo=TipoInmueble.OFICINA)
                | Q(codigo_sucursal__isnull=True),
                name="inmueble_bodega_sin_codigo",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.nombre} ({self.comuna})"

    @property
    def direccion_completa(self) -> str:
        """Street address on one line, omitting an absent unit."""
        parts = [f"{self.calle} {self.numero}".strip(), self.unidad, self.comuna]
        return ", ".join(part for part in parts if part)


VALIDADORES_DOCUMENTO = [
    FileExtensionValidator(list(FILE_SIGNATURES)),
    validate_max_file_size,
    validate_file_signature,
]


def validar_documento_identidad(archivo) -> None:
    """Run the identity-card field validators on an upload.

    Raises:
        django.core.exceptions.ValidationError: The file is too large or is
            not a JPG, PNG or PDF.
    """
    for validador in VALIDADORES_DOCUMENTO:
        validador(archivo)


def ruta_documento_identidad(instance: Autorizante, filename: str) -> str:
    """A random name, so the path reveals no RUT or name."""
    extension = PurePath(filename).suffix.lower()
    return f"autorizantes/{uuid.uuid4().hex}{extension}"


class Autorizante(TimestampedModel):
    """The owner of a property who authorises its use as a domicile (RN-43).

    The owner is a natural person (PLT-02 warehouse) or a company acting
    through its legal representative (PLT-01 office), exactly one of the two.
    The owner can change, so the authorisation has a validity period.

    The identity card is sensitive personal data: it is stored outside
    MEDIA_ROOT, has no URL, and is read only through
    inmuebles.services.abrir_documento_identidad by holders of
    descargar_documento_identidad.

    ASSUMPTION: pending validation with Easy Office. Whose card is attached
    when the owner is a company (the representative's, per PLT-01), and how
    long cards are retained (Ley 21.719), are not confirmed.
    """

    inmueble = models.ForeignKey(
        Oficina,
        verbose_name=_("inmueble"),
        on_delete=models.PROTECT,
        related_name="autorizaciones",
    )
    persona = models.ForeignKey(
        "clientes.Persona",
        verbose_name=_("persona"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="autorizaciones_inmueble",
        help_text=_("Owner, when the owner is a natural person."),
    )
    empresa = models.ForeignKey(
        "clientes.Empresa",
        verbose_name=_("empresa"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="autorizaciones_inmueble",
        help_text=_("Owner, when the owner is a company."),
    )
    representante = models.ForeignKey(
        "clientes.RepresentanteLegal",
        verbose_name=_("representante"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="autorizaciones_inmueble",
        help_text=_("Who signs for the owner company."),
    )
    vigente_desde = models.DateField(_("vigente desde"))
    vigente_hasta = models.DateField(
        _("vigente hasta"),
        null=True,
        blank=True,
        help_text=_("Empty means the authorisation has no end date."),
    )
    documento_identidad = models.FileField(
        _("cédula de identidad"),
        storage=get_private_storage,
        upload_to=ruta_documento_identidad,
        blank=True,
        validators=VALIDADORES_DOCUMENTO,
    )
    activo = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("autorizante")
        verbose_name_plural = _("autorizantes")
        ordering = ["inmueble", "-vigente_desde"]
        permissions = [
            (
                "descargar_documento_identidad",
                _("Can download an authoriser's identity card"),
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(persona__isnull=False, empresa__isnull=True)
                    | Q(persona__isnull=True, empresa__isnull=False)
                ),
                name="autorizante_exactamente_un_propietario",
            ),
            models.CheckConstraint(
                condition=(
                    Q(persona__isnull=False, representante__isnull=True)
                    | Q(empresa__isnull=False, representante__isnull=False)
                ),
                name="autorizante_representante_solo_con_empresa",
            ),
            models.CheckConstraint(
                condition=(
                    Q(vigente_hasta__isnull=True)
                    | Q(vigente_hasta__gt=F("vigente_desde"))
                ),
                name="autorizante_periodo_valido",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.persona or self.empresa} → {self.inmueble}"

    def clean(self) -> None:
        super().clean()
        if (
            self.representante_id
            and self.empresa_id
            and self.representante.empresa_id != self.empresa_id
        ):
            raise ValidationError(
                {
                    "representante": _(
                        "This person does not represent the owner company.",
                    ),
                },
            )

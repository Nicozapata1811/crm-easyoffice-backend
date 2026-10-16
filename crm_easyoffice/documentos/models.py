"""Versioned templates, generated documents and their integrity hashes.

Decisions 1 to 3 of CLAUDE.md: a template version never changes once used; a
document points at the exact version it came from and keeps a frozen
snapshot of the data it printed; the generated and the signed files carry
their SHA-256.
"""

from __future__ import annotations

import uuid
from pathlib import PurePath

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from crm_easyoffice.core.models import TimestampedModel
from crm_easyoffice.core.storage import get_private_storage


def ruta_plantilla(instance: VersionPlantilla, filename: str) -> str:
    return f"plantillas/{uuid.uuid4().hex}{PurePath(filename).suffix.lower()}"


def ruta_documento(instance: Documento, filename: str) -> str:
    """A random name: the path reveals no client, folio or RUT."""
    return f"documentos/{uuid.uuid4().hex}{PurePath(filename).suffix.lower()}"


class PlantillaDocumentoError(Exception):
    """A template version already used by a document cannot change."""


class PlantillaDocumento(TimestampedModel):
    """A document Easy Office issues from a template, e.g. PLT-01."""

    codigo = models.CharField(_("código"), max_length=20, unique=True)
    nombre = models.CharField(_("nombre"), max_length=150)
    activa = models.BooleanField(_("activa"), default=True)

    class Meta:
        verbose_name = _("plantilla de documento")
        verbose_name_plural = _("plantillas de documento")
        ordering = ["codigo"]

    def __str__(self) -> str:
        return f"{self.codigo} · {self.nombre}"


class VersionPlantilla(TimestampedModel):
    """One version of a template: the converted Word file, immutable once used.

    If Easy Office fixes a clause, a new version is added; documents issued
    before keep pointing at theirs.
    """

    plantilla = models.ForeignKey(
        PlantillaDocumento,
        verbose_name=_("plantilla"),
        on_delete=models.PROTECT,
        related_name="versiones",
    )
    numero = models.PositiveIntegerField(_("número"))
    archivo = models.FileField(
        _("archivo"),
        storage=get_private_storage,
        upload_to=ruta_plantilla,
    )
    sha256 = models.CharField(_("SHA-256"), max_length=64)
    notas = models.TextField(_("notas"), blank=True)
    vigente_desde = models.DateTimeField(_("vigente desde"))

    class Meta:
        verbose_name = _("versión de plantilla")
        verbose_name_plural = _("versiones de plantilla")
        ordering = ["plantilla", "-numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["plantilla", "numero"],
                name="version_plantilla_numero_unico",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.plantilla.codigo} v{self.numero}"

    def save(self, *args, **kwargs) -> None:
        if self.pk is not None and self.documentos.exists():
            raise PlantillaDocumentoError
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.documentos.exists():
            raise PlantillaDocumentoError
        return super().delete(*args, **kwargs)


class Documento(TimestampedModel):
    """A document generated for a case, with the data it printed, frozen.

    Each regeneration (the client edits the draft) is a new version; the
    previous ones are kept as replaced. Files live in private storage and
    are served only through permission-checked views.
    """

    class Estado(models.TextChoices):
        GENERADO = "generado", _("generado")
        REEMPLAZADO = "reemplazado", _("reemplazado")
        FIRMADO = "firmado", _("firmado")

    tramite = models.ForeignKey(
        "tramites.Tramite",
        verbose_name=_("trámite"),
        on_delete=models.PROTECT,
        related_name="documentos",
    )
    version = models.PositiveIntegerField(_("versión"))
    version_plantilla = models.ForeignKey(
        VersionPlantilla,
        verbose_name=_("versión de plantilla"),
        on_delete=models.PROTECT,
        related_name="documentos",
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=Estado.choices,
        default=Estado.GENERADO,
    )
    archivo_docx = models.FileField(
        _("documento (Word)"),
        storage=get_private_storage,
        upload_to=ruta_documento,
    )
    sha256_docx = models.CharField(_("SHA-256 del Word"), max_length=64)
    archivo_pdf = models.FileField(
        _("documento (PDF)"),
        storage=get_private_storage,
        upload_to=ruta_documento,
    )
    sha256_pdf = models.CharField(_("SHA-256 del PDF"), max_length=64)
    datos_snapshot = models.JSONField(
        _("datos impresos"),
        help_text=_("Every value the document printed, and where it came from."),
    )
    generado_en = models.DateTimeField(_("generado en"))
    archivo_firmado = models.FileField(
        _("documento firmado"),
        storage=get_private_storage,
        upload_to=ruta_documento,
        blank=True,
    )
    sha256_firmado = models.CharField(
        _("SHA-256 del firmado"),
        max_length=64,
        blank=True,
    )
    firmado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("firmado subido por"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    firmado_en = models.DateTimeField(_("firmado en"), null=True, blank=True)

    class Meta:
        verbose_name = _("documento")
        verbose_name_plural = _("documentos")
        ordering = ["tramite", "-version"]
        permissions = [
            ("subir_documento_firmado", _("Can upload a signed document")),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tramite", "version"],
                name="documento_version_unica",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.tramite} v{self.version}"


class Firmante(models.Model):
    """Who signs a document (RN-39).

    ASSUMPTION: pending validation with Easy Office. The order of the
    signatures in the domicile contract is not confirmed (RN-39), and one
    uploaded PDF is assumed to carry every signature.
    """

    class Rol(models.TextChoices):
        CLIENTE_REPRESENTANTE = "cliente_representante", _("representante del cliente")
        AUTORIZANTE = "autorizante", _("autorizante del domicilio")

    documento = models.ForeignKey(
        Documento,
        verbose_name=_("documento"),
        on_delete=models.CASCADE,
        related_name="firmantes",
    )
    persona = models.ForeignKey(
        "clientes.Persona",
        verbose_name=_("persona"),
        on_delete=models.PROTECT,
        related_name="firmas",
    )
    rol = models.CharField(_("rol"), max_length=30, choices=Rol.choices)
    orden = models.PositiveSmallIntegerField(_("orden"))
    firmado_en = models.DateTimeField(_("firmado en"), null=True, blank=True)

    class Meta:
        verbose_name = _("firmante")
        verbose_name_plural = _("firmantes")
        ordering = ["documento", "orden"]

    def __str__(self) -> str:
        return f"{self.persona} ({self.get_rol_display()})"

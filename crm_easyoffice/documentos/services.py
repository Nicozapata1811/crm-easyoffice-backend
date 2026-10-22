"""Generating a case's document and recording its signed copy.

Generation runs in Celery (tasks.generar_documento), never in a request.
"""

from __future__ import annotations

import hashlib
import io
import logging
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import OuterRef
from django.db.models import Subquery
from django.utils import timezone
from django.utils.translation import gettext as _
from docx.shared import Mm
from docxtpl import DocxTemplate
from docxtpl import InlineImage

from crm_easyoffice.core.validators import validate_file_signature
from crm_easyoffice.integrations.pdf.base import PdfError
from crm_easyoffice.integrations.pdf.registry import get_pdf_converter
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.services import INICIADO
from crm_easyoffice.tramites.services import TransicionInvalidaError
from crm_easyoffice.tramites.services import completar
from crm_easyoffice.tramites.services import documento_fallido
from crm_easyoffice.tramites.services import documento_listo
from crm_easyoffice.tramites.services import en_firma
from crm_easyoffice.tramites.services import verificar_para_firma

from . import plt01
from . import plt02
from .comun import Contexto
from .comun import DatosIncompletosError
from .models import Documento
from .models import Firmante
from .models import VersionPlantilla

if TYPE_CHECKING:
    from datetime import date

    from django.core.files import File

    from crm_easyoffice.users.models import User

logger = logging.getLogger(__name__)

# Context builders by template code. A new template adds its own.
CONTEXTOS = {"PLT-01": plt01.contexto, "PLT-02": plt02.contexto}

# Two identity-card images side by side fit the page at 60 mm each, also with
# LibreOffice's font metrics (70 mm fit in Word but stacked in the PDF).
ANCHO_CEDULA = Mm(60)

# ASSUMPTION: pending validation with Easy Office. No size limit is agreed
# for a signed contract.
MAX_FIRMADO_BYTES = 10 * 1024 * 1024


class DocumentoNoFirmableError(Exception):
    """The document is not the current one, or its case is not at signing."""


def _sha256(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def version_vigente(codigo: str) -> VersionPlantilla:
    """The latest version of an active template.

    Raises:
        VersionPlantilla.DoesNotExist: The template has no version.
    """
    version = (
        VersionPlantilla.objects.select_related("plantilla")
        .filter(plantilla__codigo=codigo, plantilla__activa=True)
        .order_by("-numero")
        .first()
    )
    if version is None:
        raise VersionPlantilla.DoesNotExist
    return version


def renderizar(version: VersionPlantilla, contexto: Contexto) -> bytes:
    """Fill the template version with the context; returns the Word file."""
    with version.archivo.open("rb") as archivo:
        plantilla = DocxTemplate(io.BytesIO(archivo.read()))
    imagenes = {
        nombre: InlineImage(plantilla, io.BytesIO(contenido), width=ANCHO_CEDULA)
        for nombre, contenido in contexto.imagenes.items()
    }
    plantilla.render({**contexto.valores, **imagenes}, autoescape=True)
    salida = io.BytesIO()
    plantilla.save(salida)
    return salida.getvalue()


def generar(tramite: Tramite) -> Documento | None:
    """Generate the case's document as a new version and move the case on.

    Missing data or a failed conversion leaves no document: the case waits
    for information and the executive sees why.
    """
    tramite = Tramite.objects.select_related("tipo", "contrato__marca").get(
        pk=tramite.pk,
    )
    if tramite.estado != INICIADO:
        logger.info("%s is not waiting for a document; skipped.", tramite)
        return None
    codigo = tramite.tipo.configuracion.get("plantilla", "")
    try:
        version = version_vigente(codigo)
        contexto = CONTEXTOS[codigo](tramite)
        docx = renderizar(version, contexto)
        pdf = get_pdf_converter().docx_a_pdf(docx, nombre=f"{tramite.folio}.docx")
    except DatosIncompletosError as error:
        documento_fallido(tramite, "\n".join(error.problemas))
        return None
    except KeyError, VersionPlantilla.DoesNotExist:
        documento_fallido(tramite, f"No hay una plantilla vigente {codigo!r}.")
        return None
    except PdfError as error:
        logger.exception("PDF conversion failed for %s.", tramite)
        documento_fallido(tramite, f"No se pudo generar el PDF: {error}")
        return None
    except OSError:
        logger.exception("A template or card file is missing for %s.", tramite)
        documento_fallido(tramite, "Falta un archivo de la plantilla o de la cédula.")
        return None

    with transaction.atomic():
        anteriores = Documento.objects.select_for_update().filter(tramite=tramite)
        ultima = anteriores.order_by("-version").values_list("version", flat=True)
        numero = (ultima.first() or 0) + 1
        anteriores.filter(estado=Documento.Estado.GENERADO).update(
            estado=Documento.Estado.REEMPLAZADO,
        )
        documento = Documento(
            tramite=tramite,
            version=numero,
            version_plantilla=version,
            sha256_docx=_sha256(docx),
            sha256_pdf=_sha256(pdf),
            datos_snapshot={
                "valores": contexto.valores,
                "fuentes": contexto.fuentes,
                "imagenes": {
                    nombre: _sha256(contenido)
                    for nombre, contenido in contexto.imagenes.items()
                },
                "plantilla": {
                    "codigo": codigo,
                    "version": version.numero,
                    "sha256": version.sha256,
                },
            },
            generado_en=timezone.now(),
        )
        nombre = f"{tramite.contrato.folio}-v{numero}"
        documento.archivo_docx.save(f"{nombre}.docx", ContentFile(docx), save=False)
        documento.archivo_pdf.save(f"{nombre}.pdf", ContentFile(pdf), save=False)
        documento.save()
        Firmante.objects.bulk_create(
            Firmante(documento=documento, persona=persona, rol=rol, orden=orden)
            for orden, (persona, rol) in enumerate(contexto.firmantes, start=1)
        )
        documento_listo(tramite)
    return documento


def documento_vigente(tramite: Tramite) -> Documento | None:
    """The case's latest generated or signed document."""
    return (
        tramite.documentos.exclude(estado=Documento.Estado.REEMPLAZADO)
        .order_by("-version")
        .first()
    )


def registrar_firmado(documento: Documento, archivo: File, usuario: User) -> Documento:
    """Record the signed PDF of the current document; the case completes (RN-24).

    Raises:
        DocumentoNoFirmableError: Not the current document, or its case is
            not waiting for a signature.
        crm_easyoffice.tramites.services.FechaInicioVencidaError: The start
            date has passed; the case now waits for a new one.
        django.core.exceptions.ValidationError: Not a PDF, or too large.
    """
    if archivo.size > MAX_FIRMADO_BYTES:
        raise ValidationError(
            {"archivo": _("The file is larger than 10 MB.")},
        )
    if not archivo.name.lower().endswith(".pdf"):
        raise ValidationError({"archivo": _("Upload the signed document as PDF.")})
    try:
        validate_file_signature(archivo)
    except ValidationError as error:
        raise ValidationError({"archivo": error.messages}) from error

    tramite = documento.tramite
    if documento != documento_vigente(tramite) or documento.archivo_firmado:
        raise DocumentoNoFirmableError
    try:
        verificar_para_firma(tramite, usuario)
    except TransicionInvalidaError as error:
        raise DocumentoNoFirmableError from error

    archivo.seek(0)
    contenido = archivo.read()
    with transaction.atomic():
        documento = Documento.objects.select_for_update().get(pk=documento.pk)
        documento.archivo_firmado.save(
            f"{tramite.contrato.folio}-firmado.pdf",
            ContentFile(contenido),
            save=False,
        )
        documento.sha256_firmado = _sha256(contenido)
        documento.firmado_por = usuario
        documento.firmado_en = timezone.now()
        documento.estado = Documento.Estado.FIRMADO
        documento.save()
        documento.firmantes.update(firmado_en=documento.firmado_en)
        completar(tramite, usuario)
    return documento


def contar_pendientes_de_firma(fecha: date) -> int:
    """Documents waiting for a signature at the end of ``fecha`` (RF-14).

    One per case waiting for a signature: its latest version generated by
    then. Replaced versions never count, because only the latest is taken;
    a signed one does not either, because its case had completed. A case
    waiting for information keeps its last generated version but is not
    waiting for a signature.
    """
    ultima = (
        Documento.objects.filter(
            tramite=OuterRef("tramite_id"),
            generado_en__date__lte=fecha,
        )
        .order_by("-version")
        .values("pk")[:1]
    )
    return Documento.objects.filter(
        tramite__in=en_firma(fecha).values("pk"),
        pk=Subquery(ultima),
    ).count()

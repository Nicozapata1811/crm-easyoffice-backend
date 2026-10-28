from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from crm_easyoffice.documentos.models import Documento
from crm_easyoffice.documentos.models import Firmante
from crm_easyoffice.documentos.models import SolicitudFirma
from crm_easyoffice.tramites.services import nivel_firma


class FirmanteSerializer(serializers.ModelSerializer[Firmante]):
    """A signer as the client sees it: name, role and state only."""

    nombre = serializers.CharField(source="persona.nombre_completo")

    class Meta:
        model = Firmante
        fields = ["orden", "rol", "nombre", "estado", "firmado_en"]
        read_only_fields = fields


class FirmanteBackofficeSerializer(FirmanteSerializer):
    class Meta(FirmanteSerializer.Meta):
        fields = [
            "id",
            *FirmanteSerializer.Meta.fields,
            "rechazado_en",
            "motivo_rechazo",
        ]
        read_only_fields = fields


class SolicitudFirmaSerializer(serializers.ModelSerializer[SolicitudFirma]):
    class Meta:
        model = SolicitudFirma
        fields = [
            "id_externo",
            "proveedor",
            "estado",
            "ambiente_pruebas",
            "enviada_en",
            "expira_en",
            "terminada_en",
            "detalle_error",
        ]
        read_only_fields = fields


class FirmaSerializer(serializers.Serializer):
    nivel = serializers.ChoiceField(choices=["asistida", "avanzada"])
    ambiente_pruebas = serializers.BooleanField(
        help_text="The provider is a test environment: no legal validity.",
    )


class FirmaBackofficeSerializer(FirmaSerializer):
    solicitud = SolicitudFirmaSerializer(allow_null=True)


def _solicitud(documento: Documento) -> SolicitudFirma | None:
    # Prefetched, newest first (see views._documentos).
    solicitudes = list(documento.solicitudes_firma.all())
    return solicitudes[0] if solicitudes else None


def firma_de(documento: Documento) -> dict[str, Any]:
    solicitud = _solicitud(documento)
    return {
        "nivel": nivel_firma(documento.tramite.tipo),
        "ambiente_pruebas": bool(solicitud and solicitud.ambiente_pruebas),
        "solicitud": solicitud,
    }


class DocumentoSerializer(serializers.ModelSerializer[Documento]):
    """A version of a case's document: no file paths, only what it is."""

    plantilla = serializers.SerializerMethodField()
    firmantes = FirmanteSerializer(many=True)
    tiene_firmado = serializers.SerializerMethodField()
    firma = serializers.SerializerMethodField()

    class Meta:
        model = Documento
        fields = [
            "id",
            "version",
            "estado",
            "plantilla",
            "generado_en",
            "sha256_docx",
            "sha256_pdf",
            "sha256_firmado",
            "firmado_en",
            "tiene_firmado",
            "firmantes",
            "firma",
        ]
        read_only_fields = fields

    def get_plantilla(self, documento: Documento) -> str:
        return str(documento.version_plantilla)

    def get_tiene_firmado(self, documento: Documento) -> bool:
        return bool(documento.archivo_firmado)

    @extend_schema_field(FirmaSerializer)
    def get_firma(self, documento: Documento) -> dict[str, Any]:
        return FirmaSerializer(firma_de(documento)).data


class DocumentoBackofficeSerializer(DocumentoSerializer):
    """The staff view adds each signer's details and the provider's request."""

    firmantes = FirmanteBackofficeSerializer(many=True)

    @extend_schema_field(FirmaBackofficeSerializer)
    def get_firma(self, documento: Documento) -> dict[str, Any]:
        return FirmaBackofficeSerializer(firma_de(documento)).data


class ReenviarFirmaSerializer(serializers.Serializer):
    firmante = serializers.IntegerField(help_text="The signer's id.")

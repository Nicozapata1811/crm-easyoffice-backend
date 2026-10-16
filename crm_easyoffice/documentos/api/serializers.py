from __future__ import annotations

from rest_framework import serializers

from crm_easyoffice.documentos.models import Documento
from crm_easyoffice.documentos.models import Firmante


class FirmanteSerializer(serializers.ModelSerializer[Firmante]):
    nombre = serializers.CharField(source="persona.nombre_completo")

    class Meta:
        model = Firmante
        fields = ["orden", "rol", "nombre", "firmado_en"]
        read_only_fields = fields


class DocumentoSerializer(serializers.ModelSerializer[Documento]):
    """A version of a case's document: no file paths, only what it is."""

    plantilla = serializers.SerializerMethodField()
    firmantes = FirmanteSerializer(many=True)
    tiene_firmado = serializers.SerializerMethodField()

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
        ]
        read_only_fields = fields

    def get_plantilla(self, documento: Documento) -> str:
        return str(documento.version_plantilla)

    def get_tiene_firmado(self, documento: Documento) -> bool:
        return bool(documento.archivo_firmado)

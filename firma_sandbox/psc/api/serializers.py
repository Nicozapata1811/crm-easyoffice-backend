from __future__ import annotations

from urllib.parse import urlsplit

from rest_framework import serializers

from psc.estado import AMBIENTE
from psc.models import Firmante
from psc.models import Solicitud


class FirmanteEntradaSerializer(serializers.Serializer):
    orden = serializers.IntegerField(min_value=1)
    nombre = serializers.CharField(max_length=200)
    rut = serializers.RegexField(r"^[0-9.]{1,12}-?[0-9kK]$")
    email = serializers.EmailField()
    rol = serializers.CharField(max_length=50, required=False, default="")
    referencia = serializers.CharField(max_length=100, required=False, default="")


class DatosSolicitudSerializer(serializers.Serializer):
    nombre_documento = serializers.CharField(max_length=200)
    referencia_externa = serializers.CharField(
        max_length=200,
        required=False,
        default="",
    )
    # Compose names have no dots (``http://django:8000``), which URLField rejects.
    url_notificacion = serializers.CharField(max_length=500, required=False, default="")
    expira_en = serializers.DateTimeField(required=False, default=None)
    firmantes = FirmanteEntradaSerializer(many=True)

    def validate_url_notificacion(self, valor: str) -> str:
        partes = urlsplit(valor)
        if valor and (partes.scheme not in {"http", "https"} or not partes.hostname):
            msg = "Debe ser una URL http o https."
            raise serializers.ValidationError(msg)
        return valor


class CrearSolicitudSerializer(serializers.Serializer):
    """Multipart: the PDF, and the rest as a JSON string in ``datos``."""

    documento = serializers.FileField()
    datos = serializers.JSONField(binary=True)


class FirmanteSalidaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Firmante
        fields = [
            "id",
            "orden",
            "nombre",
            "rol",
            "referencia",
            "estado",
            "firmado_en",
            "rechazado_en",
            "motivo_rechazo",
        ]


class SolicitudSerializer(serializers.ModelSerializer):
    """The state of a request. It matches ``psc.estado.estado_solicitud``,
    which the webhooks send, field for field."""

    ambiente = serializers.SerializerMethodField()
    firmantes = FirmanteSalidaSerializer(many=True)
    sha256_firmado = serializers.SerializerMethodField()

    class Meta:
        model = Solicitud
        fields = [
            "id",
            "estado",
            "ambiente",
            "nombre_documento",
            "referencia_externa",
            "creada_en",
            "expira_en",
            "terminada_en",
            "sha256_original",
            "sha256_firmado",
            "firmantes",
        ]

    def get_ambiente(self, obj: Solicitud) -> str:
        return AMBIENTE

    def get_sha256_firmado(self, obj: Solicitud) -> str | None:
        return obj.sha256_firmado or None


class SolicitudCreadaSerializer(SolicitudSerializer):
    url_firma = serializers.CharField(
        help_text="Enlace del primer firmante; también se envía por correo.",
    )

    class Meta(SolicitudSerializer.Meta):
        fields = [*SolicitudSerializer.Meta.fields, "url_firma"]


class EnlaceSerializer(serializers.Serializer):
    url_firma = serializers.CharField()


class FirmaValidadaSerializer(serializers.Serializer):
    campo = serializers.CharField()
    nombre = serializers.CharField(allow_null=True)
    rut = serializers.CharField(allow_null=True)
    firmado_en = serializers.DateTimeField(allow_null=True)
    intacta = serializers.BooleanField()
    confiable = serializers.BooleanField(
        help_text="La cadena llega a la raíz de pruebas.",
    )
    valida = serializers.BooleanField()
    cubre_revision = serializers.BooleanField()
    sello_de_tiempo = serializers.BooleanField()
    revocacion_embebida = serializers.BooleanField()
    modificaciones_permitidas = serializers.BooleanField()


class InformeSerializer(serializers.Serializer):
    valido = serializers.BooleanField()
    ambiente = serializers.CharField(default=AMBIENTE)
    documento_sin_cambios = serializers.BooleanField()
    sello_documento = serializers.BooleanField()
    firmas = FirmaValidadaSerializer(many=True)
    errores = serializers.ListField(child=serializers.CharField())


class ValidarSerializer(serializers.Serializer):
    documento = serializers.FileField()

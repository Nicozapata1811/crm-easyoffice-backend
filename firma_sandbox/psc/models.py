"""What the test PSC keeps: API clients, the fictitious identity registry,
signing requests, signers, their certificates and codes, and the webhook
outbox."""

from __future__ import annotations

import hashlib
import secrets
import uuid

from django.conf import settings
from django.db import models


def resumen(valor: str | bytes) -> str:
    """SHA-256 of a secret or a file, in hex. Secrets are only stored this way."""
    datos = valor.encode() if isinstance(valor, str) else valor
    return hashlib.sha256(datos).hexdigest()


class ClienteApi(models.Model):
    """A system allowed to use the API (the CRM, in local)."""

    nombre = models.CharField(max_length=100, unique=True)
    hash_api_key = models.CharField(max_length=64, unique=True)
    # Kept readable: the service needs it to sign every webhook it sends.
    secreto_webhook = models.CharField(max_length=200)
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.nombre


class IdentidadFicticia(models.Model):
    """One entry of the fictitious civil registry the identity check reads."""

    rut = models.CharField(max_length=12, unique=True)
    numero_serie = models.CharField(max_length=20)
    nombre = models.CharField(max_length=200)

    def __str__(self) -> str:
        return self.rut


class Solicitud(models.Model):
    """A document to be signed by several people, in order."""

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente"
        COMPLETADA = "completada"
        RECHAZADA = "rechazada"
        EXPIRADA = "expirada"
        CANCELADA = "cancelada"

    ABIERTAS = (Estado.PENDIENTE,)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cliente = models.ForeignKey(
        ClienteApi,
        on_delete=models.PROTECT,
        related_name="solicitudes",
    )
    nombre_documento = models.CharField(max_length=200)
    referencia_externa = models.CharField(max_length=200, blank=True)
    url_notificacion = models.CharField(max_length=500, blank=True)
    documento_original = models.BinaryField()
    sha256_original = models.CharField(max_length=64)
    # The original plus every revision added so far: the signature page, then one
    # signature per signer. Always an incremental update of the original.
    documento_actual = models.BinaryField()
    sha256_firmado = models.CharField(max_length=64, blank=True)
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    expira_en = models.DateTimeField()
    creada_en = models.DateTimeField(auto_now_add=True)
    terminada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-creada_en"]

    def __str__(self) -> str:
        return f"{self.nombre_documento} ({self.estado})"

    @property
    def abierta(self) -> bool:
        return self.estado in self.ABIERTAS


class Firmante(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente"
        FIRMADO = "firmado"
        RECHAZADO = "rechazado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    solicitud = models.ForeignKey(
        Solicitud,
        on_delete=models.CASCADE,
        related_name="firmantes",
    )
    orden = models.PositiveSmallIntegerField()
    nombre = models.CharField(max_length=200)
    rut = models.CharField(max_length=12)
    email = models.EmailField()
    rol = models.CharField(max_length=50, blank=True)
    referencia = models.CharField(max_length=100, blank=True)
    hash_token = models.CharField(max_length=64, unique=True)
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    intentos_identidad = models.PositiveSmallIntegerField(default=0)
    identidad_verificada_en = models.DateTimeField(null=True, blank=True)
    invitado_en = models.DateTimeField(null=True, blank=True)
    firmado_en = models.DateTimeField(null=True, blank=True)
    rechazado_en = models.DateTimeField(null=True, blank=True)
    motivo_rechazo = models.TextField(blank=True)
    codigo_verificacion = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["solicitud", "orden"]
        constraints = [
            models.UniqueConstraint(
                fields=["solicitud", "orden"],
                name="firmante_orden_unico",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.orden}. {self.nombre}"

    def nuevo_token(self) -> str:
        """Issue a fresh link token; the previous link stops working."""
        token = secrets.token_urlsafe(32)
        self.hash_token = resumen(token)
        return token

    @property
    def bloqueado(self) -> bool:
        return self.intentos_identidad >= settings.IDENTIDAD_INTENTOS


class Certificado(models.Model):
    """A single-use signer certificate. Its key exists only until it signs."""

    firmante = models.OneToOneField(
        Firmante,
        on_delete=models.CASCADE,
        related_name="certificado",
    )
    numero_serie = models.CharField(max_length=60, unique=True)
    pem = models.TextField()
    # Encrypted PKCS#8; emptied as soon as the signature is made.
    clave_cifrada = models.BinaryField(null=True)
    emitido_en = models.DateTimeField(auto_now_add=True)
    revocado_en = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return self.numero_serie


class CodigoOtp(models.Model):
    """A one-time code sent to the signer's email; only its hash is stored."""

    firmante = models.ForeignKey(
        Firmante,
        on_delete=models.CASCADE,
        related_name="codigos",
    )
    hash_codigo = models.CharField(max_length=64)
    expira_en = models.DateTimeField()
    intentos = models.PositiveSmallIntegerField(default=0)
    usado_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en"]

    def __str__(self) -> str:
        return f"código de {self.firmante_id}"


class EntregaWebhook(models.Model):
    """One event waiting to reach, or already delivered to, the client."""

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente"
        ENTREGADA = "entregada"
        FALLIDA = "fallida"

    id_evento = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    solicitud = models.ForeignKey(
        Solicitud,
        on_delete=models.CASCADE,
        related_name="entregas",
    )
    tipo = models.CharField(max_length=40)
    url = models.CharField(max_length=500)
    cuerpo = models.TextField()
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    intentos = models.PositiveSmallIntegerField(default=0)
    proximo_intento = models.DateTimeField()
    ultimo_error = models.TextField(blank=True)
    entregada_en = models.DateTimeField(null=True, blank=True)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["creada_en"]
        indexes = [models.Index(fields=["estado", "proximo_intento"])]

    def __str__(self) -> str:
        return f"{self.tipo} {self.id_evento}"

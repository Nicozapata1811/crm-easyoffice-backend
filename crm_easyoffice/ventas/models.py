"""Sales, payment attempts, confirmed transactions and the webhook log."""

from __future__ import annotations

import uuid

from django.db import models
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.core.models import TimestampedModel

MONTO = {"max_digits": 12, "decimal_places": 0}


class Servicio(TimestampedModel):
    """A service the portal sells, with its list price.

    ASSUMPTION: pending validation with Easy Office. Prices are not confirmed
    (MD-06); ``precio_confirmado`` stays false until they are.
    """

    codigo = models.SlugField(_("código"), max_length=50, unique=True)
    nombre = models.CharField(_("nombre"), max_length=150)
    descripcion = models.TextField(_("descripción"), blank=True)
    precio_base = models.DecimalField(_("precio base (CLP)"), **MONTO)
    precio_confirmado = models.BooleanField(_("precio confirmado"), default=False)
    activo = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("servicio")
        verbose_name_plural = _("servicios")
        ordering = ["nombre"]

    def __str__(self) -> str:
        return self.nombre


def format_folio_venta(pk: int) -> str:
    return f"VEN-{pk:06d}"


class Venta(TimestampedModel):
    class Estado(models.TextChoices):
        PENDIENTE_PAGO = "pendiente_pago", _("pendiente de pago")
        PAGADA = "pagada", _("pagada")
        REEMBOLSADA = "reembolsada", _("reembolsada")
        ANULADA = "anulada", _("anulada")

    folio = models.CharField(  # noqa: DJ001 - null until save() assigns it
        _("folio"),
        max_length=12,
        unique=True,
        null=True,
        editable=False,
    )
    cliente = models.ForeignKey(
        Cliente,
        verbose_name=_("cliente"),
        on_delete=models.PROTECT,
        related_name="ventas",
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE_PAGO,
    )
    total = models.DecimalField(_("total (CLP)"), **MONTO)
    pagada_en = models.DateTimeField(_("pagada en"), null=True, blank=True)

    class Meta:
        verbose_name = _("venta")
        verbose_name_plural = _("ventas")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.folio or f"Venta {self.pk}"

    def save(self, *args, **kwargs) -> None:
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.folio:
                self.folio = format_folio_venta(self.pk)
                super().save(update_fields=["folio"])


class ItemVenta(models.Model):
    """A sold line. Name and price are copied at sale time (RN-08)."""

    venta = models.ForeignKey(
        Venta,
        verbose_name=_("venta"),
        on_delete=models.CASCADE,
        related_name="items",
    )
    servicio = models.ForeignKey(
        Servicio,
        verbose_name=_("servicio"),
        on_delete=models.PROTECT,
        related_name="items_vendidos",
    )
    nombre = models.CharField(_("nombre"), max_length=150)
    precio_unitario = models.DecimalField(_("precio unitario (CLP)"), **MONTO)
    cantidad = models.PositiveIntegerField(_("cantidad"), default=1)
    subtotal = models.DecimalField(_("subtotal (CLP)"), **MONTO)

    class Meta:
        verbose_name = _("ítem de venta")
        verbose_name_plural = _("ítems de venta")

    def __str__(self) -> str:
        return f"{self.cantidad} x {self.nombre}"


class OrdenPago(TimestampedModel):
    """One attempt to collect a sale through the provider (RN-28)."""

    class Estado(models.TextChoices):
        CREANDO = "creando", _("creando")
        PENDIENTE = "pendiente", _("pendiente")
        PAGADA = "pagada", _("pagada")
        RECHAZADA = "rechazada", _("rechazada")
        EXPIRADA = "expirada", _("expirada")
        CANCELADA = "cancelada", _("cancelada")
        REEMBOLSADA = "reembolsada", _("reembolsada")
        ERROR = "error", _("error")

    ABIERTAS = (Estado.CREANDO, Estado.PENDIENTE)

    venta = models.ForeignKey(
        Venta,
        verbose_name=_("venta"),
        on_delete=models.PROTECT,
        related_name="ordenes",
    )
    proveedor = models.CharField(_("proveedor"), max_length=30)
    referencia = models.UUIDField(
        _("referencia"),
        default=uuid.uuid4,
        unique=True,
        editable=False,
        help_text=_("Our id for the attempt, echoed back by the provider."),
    )
    id_externo = models.CharField(
        _("id en el proveedor"),
        max_length=100,
        unique=True,
        null=True,
        blank=True,
    )
    monto = models.DecimalField(_("monto (CLP)"), **MONTO)
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=Estado.choices,
        default=Estado.CREANDO,
    )
    redirect_url = models.URLField(_("URL de pago"), max_length=500, blank=True)
    detalle_error = models.TextField(_("detalle del error"), blank=True)
    sincronizada_en = models.DateTimeField(
        _("última consulta al proveedor"),
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("orden de pago")
        verbose_name_plural = _("órdenes de pago")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.venta} · {self.referencia}"


class Pago(TimestampedModel):
    """A transaction the provider confirmed for an order."""

    class Tipo(models.TextChoices):
        VENTA = "venta", _("venta")
        REEMBOLSO = "reembolso", _("reembolso")

    orden = models.ForeignKey(
        OrdenPago,
        verbose_name=_("orden de pago"),
        on_delete=models.PROTECT,
        related_name="pagos",
    )
    tipo = models.CharField(
        _("tipo"),
        max_length=10,
        choices=Tipo.choices,
        default=Tipo.VENTA,
    )
    id_externo = models.CharField(
        _("código de transacción"),
        max_length=100,
        unique=True,
        null=True,
        blank=True,
    )
    monto = models.DecimalField(_("monto (CLP)"), **MONTO)
    medio = models.CharField(_("medio de pago"), max_length=30, blank=True)
    marca = models.CharField(_("marca"), max_length=30, blank=True)
    tipo_tarjeta = models.CharField(_("tipo de tarjeta"), max_length=20, blank=True)
    ultimos_digitos = models.CharField(_("últimos dígitos"), max_length=4, blank=True)
    cuotas = models.PositiveSmallIntegerField(_("cuotas"), null=True, blank=True)
    billetera = models.CharField(_("billetera"), max_length=30, blank=True)
    pagado_en = models.DateTimeField(_("pagado en"))
    respuesta = models.JSONField(_("respuesta del proveedor"), default=dict)

    class Meta:
        verbose_name = _("pago")
        verbose_name_plural = _("pagos")
        ordering = ["-pagado_en"]
        constraints = [
            models.UniqueConstraint(
                fields=["orden"],
                condition=models.Q(tipo="venta"),
                name="pago_una_venta_por_orden",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} {self.monto} · {self.orden}"


class EventoPago(models.Model):
    """A webhook as received. Append-only: never updated or deleted."""

    class Resultado(models.TextChoices):
        PROCESADO = "procesado", _("procesado")
        IGNORADO = "ignorado", _("ignorado")
        RECHAZADO = "rechazado", _("rechazado")
        FIRMA_INVALIDA = "firma_invalida", _("firma inválida")

    orden = models.ForeignKey(
        OrdenPago,
        verbose_name=_("orden de pago"),
        on_delete=models.PROTECT,
        related_name="eventos",
        null=True,
        blank=True,
    )
    proveedor = models.CharField(_("proveedor"), max_length=30)
    evento = models.CharField(_("evento"), max_length=30)
    clave_dedup = models.CharField(
        _("clave de deduplicación"),
        max_length=64,
        unique=True,
    )
    payload = models.JSONField(_("payload"))
    resultado = models.CharField(
        _("resultado"),
        max_length=20,
        choices=Resultado.choices,
    )
    recibido_en = models.DateTimeField(_("recibido en"), auto_now_add=True)

    class Meta:
        verbose_name = _("evento de pago")
        verbose_name_plural = _("eventos de pago")
        ordering = ["-recibido_en"]

    def __str__(self) -> str:
        return f"{self.proveedor} {self.evento} · {self.recibido_en:%Y-%m-%d %H:%M}"

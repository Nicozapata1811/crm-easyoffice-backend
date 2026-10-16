"""Sales, payment attempts, confirmed transactions and the webhook log."""

from __future__ import annotations

import uuid

from django.db import models
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.core.models import TimestampedModel

MONTO = {"max_digits": 12, "decimal_places": 0}


class CicloPago(TimestampedModel):
    """How often a contracted service is charged: único, mensual, anual, …"""

    codigo = models.SlugField(_("código"), max_length=30, unique=True)
    nombre = models.CharField(_("nombre"), max_length=60)
    meses = models.PositiveSmallIntegerField(
        _("meses"),
        null=True,
        blank=True,
        help_text=_("Months between charges. Empty for a one-off charge."),
    )
    orden = models.PositiveSmallIntegerField(_("orden"), default=0)
    activo = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("ciclo de pago")
        verbose_name_plural = _("ciclos de pago")
        ordering = ["orden", "nombre"]

    def __str__(self) -> str:
        return self.nombre


class Servicio(TimestampedModel):
    """A service Easy Office offers, with its list price.

    Two independent portal flags:

    - ``se_vende_en_portal``: the service can be bought online. The rest are
      contracted through an executive. A service with no fixed price has no
      ``precio_base`` and can never be bought online.
    - ``visible_en_portal``: the service is shown as a card on the portal
      landing. A visible service need not be bookable ("Próximamente"), and
      a bookable add-on such as the advanced electronic signature need not
      be visible: it is charged inside another service's flow.

    ``orden`` sets the order of the landing cards.

    ASSUMPTION: pending validation with Easy Office. Prices are not confirmed
    (MD-06, TA-15) and whether they include VAT is contradictory (RN-44 says
    yes, the contract template says "más I.V.A."), so ``precio_confirmado``
    stays false and ``precio_incluye_iva`` records which reading each price
    follows.
    """

    codigo = models.SlugField(_("código"), max_length=50, unique=True)
    nombre = models.CharField(_("nombre"), max_length=150)
    descripcion = models.TextField(_("descripción"), blank=True)
    precio_base = models.DecimalField(
        _("precio base (CLP)"),
        null=True,
        blank=True,
        help_text=_("Empty when the service has no fixed price."),
        **MONTO,
    )
    precio_incluye_iva = models.BooleanField(_("precio incluye IVA"), default=True)
    precio_confirmado = models.BooleanField(_("precio confirmado"), default=False)
    ciclo_pago_default = models.ForeignKey(
        CicloPago,
        verbose_name=_("ciclo de pago por defecto"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="servicios",
    )
    se_vende_en_portal = models.BooleanField(
        _("se vende en el portal"),
        default=True,
        help_text=_("Can be bought online. Requires a price."),
    )
    visible_en_portal = models.BooleanField(
        _("visible en el portal"),
        default=False,
        help_text=_("Shown as a card on the portal landing, bookable or not."),
    )
    orden = models.PositiveSmallIntegerField(_("orden"), default=0)
    activo = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("servicio")
        verbose_name_plural = _("servicios")
        ordering = ["orden", "nombre"]
        constraints = [
            models.CheckConstraint(
                condition=Q(se_vende_en_portal=False) | Q(precio_base__isnull=False),
                name="servicio_portal_con_precio",
            ),
        ]

    def __str__(self) -> str:
        return self.nombre


class PlanServicio(TimestampedModel):
    """A fixed term at a fixed price in which a service is sold online.

    Domicilio tributario is sold as a yearly or a half-yearly plan, each with
    its own price; the advanced electronic signature of the contract is
    included in some plans and charged as the firma service in the others.

    The plan's price is a list price like ``Servicio.precio_base`` (RN-44):
    nobody gets a special one. The backoffice may still contract a service
    for any duration; plans only bound what the portal offers.

    ASSUMPTION: pending validation with Easy Office. Plans and prices come
    from Easy Office's public website (15-10-2026) and are unconfirmed.
    """

    servicio = models.ForeignKey(
        Servicio,
        verbose_name=_("servicio"),
        on_delete=models.PROTECT,
        related_name="planes",
    )
    codigo = models.SlugField(_("código"), max_length=30)
    nombre = models.CharField(_("nombre"), max_length=60)
    duracion_meses = models.PositiveSmallIntegerField(_("duración (meses)"))
    ciclo_pago = models.ForeignKey(
        CicloPago,
        verbose_name=_("ciclo de pago"),
        on_delete=models.PROTECT,
        related_name="planes",
    )
    precio = models.DecimalField(_("precio (CLP)"), **MONTO)
    precio_incluye_iva = models.BooleanField(_("precio incluye IVA"), default=True)
    precio_confirmado = models.BooleanField(_("precio confirmado"), default=False)
    firma_incluida = models.BooleanField(
        _("firma electrónica incluida"),
        default=False,
        help_text=_(
            "When unchecked, the advanced electronic signature is charged on "
            "top at the firma service's price.",
        ),
    )
    se_vende_en_portal = models.BooleanField(_("se vende en el portal"), default=True)
    orden = models.PositiveSmallIntegerField(_("orden"), default=0)
    activo = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("plan de servicio")
        verbose_name_plural = _("planes de servicio")
        ordering = ["servicio", "orden", "duracion_meses"]
        constraints = [
            models.UniqueConstraint(
                fields=["servicio", "codigo"],
                name="plan_servicio_codigo_unico",
            ),
            models.CheckConstraint(
                condition=Q(precio__gte=0),
                name="plan_servicio_precio_no_negativo",
            ),
            models.CheckConstraint(
                condition=Q(duracion_meses__gte=1),
                name="plan_servicio_duracion_positiva",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.servicio} · {self.nombre}"


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
    # Not unique: Klap's sandbox repeats the same mc_code across payments.
    id_externo = models.CharField(  # noqa: DJ001 - not every provider sends one
        _("código de transacción"),
        max_length=100,
        null=True,
        blank=True,
        db_index=True,
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

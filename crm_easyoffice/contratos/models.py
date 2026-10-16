"""Contracts, the services contracted in each, and the folio counter (HU-60).

A contract is one row of Easy Office's spreadsheet: one act of contracting,
with its folio, brand, client and term, grouping one or more services.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import F
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from crm_easyoffice.core.models import TimestampedModel

MONTO = {"max_digits": 12, "decimal_places": 0}


class DuracionContrato(TimestampedModel):
    """A term a contract may be signed for, in months (1, 3, 4, 6, 12)."""

    meses = models.PositiveSmallIntegerField(_("meses"), unique=True)
    activa = models.BooleanField(_("activa"), default=True)

    class Meta:
        verbose_name = _("duración de contrato")
        verbose_name_plural = _("duraciones de contrato")
        ordering = ["meses"]

    def __str__(self) -> str:
        return f"{self.meses} meses"


class CorrelativoFolio(models.Model):
    """The last folio correlative issued in a year, shared by every branch.

    One row per year. Contract creation locks it, so the correlative is
    gapless and never repeats however many contracts are created at once.
    """

    anio = models.PositiveSmallIntegerField(_("año"), unique=True)
    ultimo = models.PositiveIntegerField(_("último correlativo"), default=0)

    class Meta:
        verbose_name = _("correlativo de folio")
        verbose_name_plural = _("correlativos de folio")
        ordering = ["-anio"]

    def __str__(self) -> str:
        return f"{self.anio}: {self.ultimo}"


class Contrato(TimestampedModel):
    """A contract, identified by its folio (RN-38), for example LF-0007-2026.

    The folio's parts are stored too: the branch code for filtering, and the
    year and correlative under a unique constraint that backs up the lock in
    contratos.folio. Contracts are created only through
    contratos.services.crear_contrato.

    ASSUMPTION: pending validation with Easy Office. The states are a minimum
    (borrador, vigente, terminado, anulado); their transitions are not
    modelled beyond borrador. A renewal is a new contract pointing at the
    previous one (RN-10, proposed); whether it keeps the folio is open.

    A contract requested in the portal is a borrador, with its folio, until
    its case is signed: a draft never occupies a domicile.

    ASSUMPTION: pending validation with Easy Office. A draft takes its folio
    when it is created, so an abandoned draft keeps one (it is annulled, the
    row stays and the sequence has no gap).
    """

    class Estado(models.TextChoices):
        BORRADOR = "borrador", _("borrador")
        VIGENTE = "vigente", _("vigente")
        TERMINADO = "terminado", _("terminado")
        ANULADO = "anulado", _("anulado")

    folio = models.CharField(_("folio"), max_length=20, unique=True, editable=False)
    codigo_sucursal = models.CharField(
        _("código de sucursal"),
        max_length=4,
        editable=False,
    )
    anio_folio = models.PositiveSmallIntegerField(_("año del folio"), editable=False)
    correlativo = models.PositiveIntegerField(_("correlativo"), editable=False)
    marca = models.ForeignKey(
        "configuracion.Marca",
        verbose_name=_("marca"),
        on_delete=models.PROTECT,
        related_name="contratos",
    )
    cliente = models.ForeignKey(
        "clientes.Cliente",
        verbose_name=_("cliente"),
        on_delete=models.PROTECT,
        related_name="contratos",
    )
    representante = models.ForeignKey(
        "clientes.RepresentanteLegal",
        verbose_name=_("representante legal"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="contratos",
        help_text=_("Who signs for a company client. Empty for a natural person."),
    )
    cuenta_pago = models.ForeignKey(
        "configuracion.CuentaPago",
        verbose_name=_("cuenta de pago"),
        on_delete=models.PROTECT,
        related_name="contratos",
    )
    fecha_inicio = models.DateField(_("fecha de inicio"))
    duracion_meses = models.PositiveSmallIntegerField(_("duración (meses)"))
    fecha_vencimiento = models.DateField(
        _("fecha de vencimiento"),
        editable=False,
        help_text=_("Start plus duration minus one day (RN-37)."),
    )
    renovacion_automatica = models.BooleanField(
        _("renovación automática"),
        default=True,
    )
    dias_aviso_termino = models.PositiveSmallIntegerField(
        _("días de aviso de término"),
        default=30,
    )
    # ASSUMPTION: pending validation with Easy Office. Whether the form's
    # email and mobile belong to the company or its representative is open;
    # stored on the contract, either answer needs no schema change.
    email_aviso = models.EmailField(_("correo para avisos"), blank=True)
    movil_aviso = models.CharField(_("celular para avisos"), max_length=20, blank=True)
    ejecutivo_responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("ejecutivo responsable"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="contratos_a_cargo",
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=Estado.choices,
        default=Estado.VIGENTE,
    )
    terminado_en = models.DateField(_("terminado en"), null=True, blank=True)
    contrato_anterior = models.ForeignKey(
        "self",
        verbose_name=_("contrato anterior"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="renovaciones",
    )

    class Meta:
        verbose_name = _("contrato")
        verbose_name_plural = _("contratos")
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["anio_folio", "correlativo"],
                name="contrato_correlativo_unico_por_anio",
            ),
            models.CheckConstraint(
                condition=Q(fecha_vencimiento__gte=F("fecha_inicio")),
                name="contrato_vencimiento_posterior_inicio",
            ),
            models.CheckConstraint(
                condition=Q(duracion_meses__gte=1),
                name="contrato_duracion_positiva",
            ),
        ]

    def __str__(self) -> str:
        return self.folio


class ServicioContratado(models.Model):
    """A service within a contract. Name, description and price are copied.

    Copying keeps an issued contract unchanged when the catalogue changes
    later (RN-08). Only the domicile service is located at a property, and
    the first located service gives the folio its branch code.
    """

    contrato = models.ForeignKey(
        Contrato,
        verbose_name=_("contrato"),
        on_delete=models.CASCADE,
        related_name="servicios",
    )
    orden = models.PositiveSmallIntegerField(_("orden"))
    servicio = models.ForeignKey(
        "ventas.Servicio",
        verbose_name=_("servicio"),
        on_delete=models.PROTECT,
        related_name="contrataciones",
    )
    nombre = models.CharField(_("nombre"), max_length=150)
    descripcion = models.TextField(_("descripción"), blank=True)
    precio = models.DecimalField(
        _("precio (CLP)"),
        null=True,
        blank=True,
        help_text=_("Empty only while a service without a fixed price is quoted."),
        **MONTO,
    )
    precio_incluye_iva = models.BooleanField(_("precio incluye IVA"))
    ciclo_pago = models.ForeignKey(
        "ventas.CicloPago",
        verbose_name=_("ciclo de pago"),
        on_delete=models.PROTECT,
        related_name="servicios_contratados",
    )
    inmueble = models.ForeignKey(
        "inmuebles.Oficina",
        verbose_name=_("inmueble"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="servicios_contratados",
    )

    class Meta:
        verbose_name = _("servicio contratado")
        verbose_name_plural = _("servicios contratados")
        ordering = ["contrato", "orden"]
        constraints = [
            models.UniqueConstraint(
                fields=["contrato", "orden"],
                name="servicio_contratado_orden_unico",
            ),
            models.CheckConstraint(
                condition=Q(precio__isnull=True) | Q(precio__gte=0),
                name="servicio_contratado_precio_no_negativo",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.contrato} · {self.nombre}"

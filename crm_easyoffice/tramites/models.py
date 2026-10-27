"""Case types, cases and their state history.

States follow RN-42: Iniciado → Pendiente (with a reason) → Completado.
State changes happen only in tramites.services, which holds the table of
allowed moves and writes one EventoTramite per move.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from crm_easyoffice.core.models import TimestampedModel


class TipoTramite(TimestampedModel):
    """A kind of case, described by configuration rather than code.

    ``configuracion`` (JSONB, edited in the admin):

    - ``servicio``: the catalogue code whose portal plans a ``planes`` type
      sells; ``marca``; ``plantilla`` (document template code).
    - ``requiere_pago``, ``requiere_firma``: true or false, or the channels
      whose cases need the step (``["portal"]``); ``inicio_max_dias`` (how
      far ahead the start date may be).
    - ``planes``: the client picks a plan, which sets price, cycle and term;
      otherwise the term is chosen (``duracion_por_defecto``) and each line
      gets its cycle and, without a list price, the agreed price.
    - ``lineas``: the contract's services in print order, each
      ``{servicio, inmueble, requisitos, inmueble_exclusivo,
      incluido_en_plan}``: the property role it is located at (``sucursal``
      or ``bodega``), the profile that property must meet
      (inmuebles.services.REQUISITOS), whether one client at a time may hold
      it, and whether the plan of another line pays for it.
    - ``canales``: where a case is started, ``portal`` and/or ``backoffice``.
    - ``tipos_cliente``: ``empresa`` and/or ``persona``.
    - ``firma``: ``{nivel, firmantes}``. ``nivel`` is ``asistida`` (an
      executive uploads the signed PDF; the default) or ``avanzada`` (the
      advanced-signature provider). ``firmantes`` optionally lists the signer
      roles in order (``cliente_representante``, ``representante_emisor``,
      ``autorizante``).

    docs/variation-points.md compares the two seeded types.
    """

    codigo = models.SlugField(_("código"), max_length=50, unique=True)
    nombre = models.CharField(_("nombre"), max_length=120)
    configuracion = models.JSONField(_("configuración"), default=dict, blank=True)
    activo = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("tipo de trámite")
        verbose_name_plural = _("tipos de trámite")
        ordering = ["nombre"]

    def __str__(self) -> str:
        return self.nombre


class MotivoPendiente(TimestampedModel):
    """Why a case is pending (RN-42), shown to the executive and the client.

    ASSUMPTION: pending validation with Easy Office. The closed list of
    reasons (TA-13) is not defined; these four come from RN-42's examples.
    """

    codigo = models.SlugField(_("código"), max_length=40, unique=True)
    nombre = models.CharField(_("nombre"), max_length=120)
    texto_cliente = models.CharField(
        _("texto para el cliente"),
        max_length=255,
        help_text=_("What the portal tells the client while the case waits."),
    )
    activo = models.BooleanField(_("activo"), default=True)

    class Meta:
        verbose_name = _("motivo de pendiente")
        verbose_name_plural = _("motivos de pendiente")
        ordering = ["nombre"]

    def __str__(self) -> str:
        return self.nombre


def format_folio_tramite(pk: int) -> str:
    return f"TRA-{pk:06d}"


class Tramite(TimestampedModel):
    """One case for one client.

    The sale and the contract it produced are linked here (MD-10), so
    ``ventas`` and ``contratos`` stay unaware of cases.

    ``datos`` keeps the choices the client made (plan, branch, start date),
    not their personal data: that lives in the client records and, frozen,
    in each generated document.
    """

    class Estado(models.TextChoices):
        INICIADO = "iniciado", _("iniciado")
        PENDIENTE = "pendiente", _("pendiente")
        COMPLETADO = "completado", _("completado")

    class Canal(models.TextChoices):
        PORTAL = "portal", _("portal")
        BACKOFFICE = "backoffice", _("backoffice")

    folio = models.CharField(  # noqa: DJ001 - null until save() assigns it
        _("folio"),
        max_length=12,
        unique=True,
        null=True,
        editable=False,
    )
    cliente = models.ForeignKey(
        "clientes.Cliente",
        verbose_name=_("cliente"),
        on_delete=models.PROTECT,
        related_name="tramites",
    )
    tipo = models.ForeignKey(
        TipoTramite,
        verbose_name=_("tipo"),
        on_delete=models.PROTECT,
        related_name="tramites",
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=Estado.choices,
        default=Estado.INICIADO,
    )
    motivo = models.ForeignKey(
        MotivoPendiente,
        verbose_name=_("motivo de pendiente"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tramites",
    )
    detalle_pendiente = models.TextField(_("detalle del pendiente"), blank=True)
    canal = models.CharField(
        _("canal"),
        max_length=20,
        choices=Canal.choices,
        default=Canal.PORTAL,
    )
    datos = models.JSONField(_("datos"), default=dict, blank=True)
    contrato = models.ForeignKey(
        "contratos.Contrato",
        verbose_name=_("contrato"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tramites",
    )
    venta = models.ForeignKey(
        "ventas.Venta",
        verbose_name=_("venta"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tramites",
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("creado por"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tramites_creados",
    )

    class Meta:
        verbose_name = _("trámite")
        verbose_name_plural = _("trámites")
        ordering = ["-created_at", "-pk"]
        permissions = [
            ("gestionar_tramite", _("Can act on a case (retry its document)")),
            ("iniciar_tramite", _("Can start a case for a client")),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(estado="pendiente", motivo__isnull=False)
                    | (~Q(estado="pendiente") & Q(motivo__isnull=True))
                ),
                name="tramite_motivo_solo_si_pendiente",
            ),
        ]

    def __str__(self) -> str:
        return self.folio or f"Trámite {self.pk}"

    def save(self, *args, **kwargs) -> None:
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.folio:
                self.folio = format_folio_tramite(self.pk)
                super().save(update_fields=["folio"])


class EventoTramiteError(Exception):
    """A case's history is append-only."""


class EventoTramite(models.Model):
    """One move of a case: from which state and reason, to which, by whom.

    Append-only: a row is never changed or deleted.
    """

    tramite = models.ForeignKey(
        Tramite,
        verbose_name=_("trámite"),
        on_delete=models.PROTECT,
        related_name="eventos",
    )
    estado_anterior = models.CharField(_("estado anterior"), max_length=20, blank=True)
    motivo_anterior = models.CharField(_("motivo anterior"), max_length=40, blank=True)
    estado_nuevo = models.CharField(_("estado nuevo"), max_length=20)
    motivo_nuevo = models.CharField(_("motivo nuevo"), max_length=40, blank=True)
    detalle = models.TextField(_("detalle"), blank=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("usuario"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    fecha = models.DateTimeField(_("fecha"), auto_now_add=True)

    class Meta:
        verbose_name = _("evento de trámite")
        verbose_name_plural = _("eventos de trámite")
        ordering = ["fecha", "pk"]

    def __str__(self) -> str:
        return f"{self.tramite}: {self.estado_anterior} → {self.estado_nuevo}"

    def save(self, *args, **kwargs) -> None:
        if self.pk is not None:
            raise EventoTramiteError
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise EventoTramiteError

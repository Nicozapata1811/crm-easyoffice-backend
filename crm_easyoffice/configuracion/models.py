"""The issuing company's own data: Easy Office, its brands and payment accounts.

These were typed into every contract template. As configuration they are
edited once, in the admin, and read by whatever prints a contract.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from crm_easyoffice.core.models import TimestampedModel
from crm_easyoffice.core.validators import validate_rut


class ConfigEmpresa(TimestampedModel):
    """Easy Office as the party that issues contracts. Exactly one row.

    ASSUMPTION: pending validation with Easy Office. EASY OFFICE and INOFFICE
    are brands of this one company (ACTA-002, D2-02), so they share this
    record. Should they turn out to be separate companies, the singleton
    constraint is dropped and Marca gains a foreign key here.
    """

    unico = models.BooleanField(default=True, editable=False)
    razon_social = models.CharField(_("razón social"), max_length=255)
    rut = models.CharField(
        _("RUT"),
        max_length=12,
        blank=True,
        validators=[validate_rut],
        help_text=_("Without dots and with a hyphen, for example 76543210-K."),
    )
    direccion = models.CharField(_("dirección"), max_length=255, blank=True)
    comuna = models.CharField(_("comuna"), max_length=100, blank=True)
    region = models.CharField(_("región"), max_length=100, blank=True)
    representante = models.ForeignKey(
        "clientes.Persona",
        verbose_name=_("representante legal"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    fecha_personeria = models.DateField(
        _("fecha de la personería"), null=True, blank=True,
    )
    registro_personeria = models.CharField(
        _("registro de la personería"),
        max_length=255,
        default="Registro de Empresas y Sociedades, Ley 20.659",
    )
    email_contacto = models.EmailField(_("correo de contacto"), blank=True)
    email_pagos = models.EmailField(_("correo de pagos"), blank=True)
    telefono = models.CharField(_("teléfono"), max_length=20, blank=True)

    class Meta:
        verbose_name = _("configuración de la empresa")
        verbose_name_plural = _("configuración de la empresa")
        constraints = [
            models.UniqueConstraint(fields=["unico"], name="config_empresa_unica"),
            models.CheckConstraint(
                condition=Q(unico=True), name="config_empresa_unico_true",
            ),
        ]

    def __str__(self) -> str:
        return self.razon_social


class CuentaPago(TimestampedModel):
    """Where clients pay: a bank account or a payment link.

    ``texto_contrato`` is what the contract prints (the form's BANCO/LINK
    column), so it is the only required field.

    ASSUMPTION: pending validation with Easy Office. An entry may be a payment
    link with no bank data, hence the optional bank fields.
    """

    banco = models.CharField(_("banco"), max_length=100, blank=True)
    tipo_cuenta = models.CharField(_("tipo de cuenta"), max_length=50, blank=True)
    numero = models.CharField(_("número"), max_length=50, blank=True)
    titular = models.CharField(_("titular"), max_length=255, blank=True)
    texto_contrato = models.TextField(
        _("texto en el contrato"),
        help_text=_("Printed as is in the contract."),
    )
    activa = models.BooleanField(_("activa"), default=True)

    class Meta:
        verbose_name = _("cuenta de pago")
        verbose_name_plural = _("cuentas de pago")
        ordering = ["banco", "numero"]

    def __str__(self) -> str:
        etiqueta = " ".join(part for part in [self.banco, self.numero] if part)
        return etiqueta or self.texto_contrato[:40]


class Marca(TimestampedModel):
    """A brand a contract is issued under, for example EASY OFFICE or INOFFICE."""

    nombre = models.CharField(_("nombre"), max_length=60, unique=True)
    activa = models.BooleanField(_("activa"), default=True)
    cuenta_pago_default = models.ForeignKey(
        CuentaPago,
        verbose_name=_("cuenta de pago por defecto"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="marcas",
    )

    class Meta:
        verbose_name = _("marca")
        verbose_name_plural = _("marcas")
        ordering = ["nombre"]

    def __str__(self) -> str:
        return self.nombre

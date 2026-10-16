"""Factories for the issuer's configuration. Every value is synthetic."""

from __future__ import annotations

from factory import Sequence
from factory import SubFactory
from factory.django import DjangoModelFactory

from crm_easyoffice.clientes.tests.factories import PersonaFactory
from crm_easyoffice.configuracion.models import ConfigEmpresa
from crm_easyoffice.configuracion.models import CuentaPago
from crm_easyoffice.configuracion.models import Marca


class CuentaPagoFactory(DjangoModelFactory[CuentaPago]):
    banco = "Banco de Ejemplo"
    numero = Sequence(lambda n: f"00-000-{n:05d}-0")
    titular = "Titular de Ejemplo"
    texto_contrato = Sequence(lambda n: f"Cuenta de ejemplo {n}")

    class Meta:
        model = CuentaPago


class MarcaFactory(DjangoModelFactory[Marca]):
    """The migrations seed EASY OFFICE and INOFFICE; this makes others."""

    nombre = Sequence(lambda n: f"MARCA DE EJEMPLO {n}")
    cuenta_pago_default = SubFactory(CuentaPagoFactory)

    class Meta:
        model = Marca


def preparar_config_contrato() -> ConfigEmpresa:
    """Give Easy Office's seeded record a fictitious, complete representative."""
    config = ConfigEmpresa.objects.get()
    config.representante = PersonaFactory.create(con_datos_civiles=True)
    config.save()
    return config

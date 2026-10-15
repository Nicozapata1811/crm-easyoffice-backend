"""Factories for client records. Every value they produce is synthetic."""

from __future__ import annotations

from datetime import date

from factory import Faker
from factory import Sequence
from factory import SubFactory
from factory import Trait
from factory.django import DjangoModelFactory

from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.clientes.models import CuentaCliente
from crm_easyoffice.clientes.models import Empresa
from crm_easyoffice.clientes.models import EstadoCivil
from crm_easyoffice.clientes.models import Persona
from crm_easyoffice.clientes.models import RepresentanteLegal
from crm_easyoffice.core.validators import compute_rut_check_digit
from crm_easyoffice.users.tests.factories import UserFactory


def synthetic_rut(number: int) -> str:
    return f"{number}-{compute_rut_check_digit(str(number))}"


class PersonaFactory(DjangoModelFactory[Persona]):
    rut = Sequence(lambda n: synthetic_rut(30_000_000 + n))
    nombres = Faker("first_name", locale="es_CL")
    apellido_paterno = Faker("last_name", locale="es_CL")
    apellido_materno = Faker("last_name", locale="es_CL")
    email = Sequence(lambda n: f"persona{n}@example.test")

    class Meta:
        model = Persona

    class Params:
        con_datos_civiles = Trait(
            nacionalidad="chilena",
            estado_civil=EstadoCivil.SOLTERO,
            profesion="Profesión de ejemplo",
            domicilio=Sequence(lambda n: f"Calle de Ejemplo {n}"),
            comuna="Comuna de Ejemplo",
            region="Región de Ejemplo",
        )


class EmpresaFactory(DjangoModelFactory[Empresa]):
    rut = Sequence(lambda n: synthetic_rut(79_000_000 + n))
    razon_social = Sequence(lambda n: f"Empresa de Ejemplo {n} SpA")
    email = Sequence(lambda n: f"empresa{n}@example.test")

    class Meta:
        model = Empresa


class RepresentanteLegalFactory(DjangoModelFactory[RepresentanteLegal]):
    persona = SubFactory(PersonaFactory)
    empresa = SubFactory(EmpresaFactory)
    vigente_desde = date(2026, 1, 1)

    class Meta:
        model = RepresentanteLegal


class ClienteFactory(DjangoModelFactory[Cliente]):
    persona = SubFactory(PersonaFactory)
    empresa = None

    class Meta:
        model = Cliente


class CuentaClienteFactory(DjangoModelFactory[CuentaCliente]):
    user = SubFactory(UserFactory)
    cliente = SubFactory(ClienteFactory)

    class Meta:
        model = CuentaCliente

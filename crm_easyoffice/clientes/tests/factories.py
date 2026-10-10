"""Factories for client records. Every value they produce is synthetic."""

from __future__ import annotations

from factory import Faker
from factory import Sequence
from factory import SubFactory
from factory.django import DjangoModelFactory

from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.clientes.models import Empresa
from crm_easyoffice.clientes.models import Persona
from crm_easyoffice.core.validators import compute_rut_check_digit


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


class EmpresaFactory(DjangoModelFactory[Empresa]):
    rut = Sequence(lambda n: synthetic_rut(79_000_000 + n))
    razon_social = Sequence(lambda n: f"Empresa de Ejemplo {n} SpA")
    email = Sequence(lambda n: f"empresa{n}@example.test")

    class Meta:
        model = Empresa


class ClienteFactory(DjangoModelFactory[Cliente]):
    persona = SubFactory(PersonaFactory)
    empresa = None

    class Meta:
        model = Cliente

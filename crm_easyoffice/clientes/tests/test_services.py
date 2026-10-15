"""Portal registration rules. Every RUT, name and email here is synthetic."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.clientes.services import RegistroRechazadoError
from crm_easyoffice.clientes.services import registrar_cuenta_cliente
from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.clientes.tests.factories import CuentaClienteFactory
from crm_easyoffice.clientes.tests.factories import EmpresaFactory
from crm_easyoffice.clientes.tests.factories import PersonaFactory
from crm_easyoffice.clientes.tests.factories import synthetic_rut
from crm_easyoffice.users.tests.factories import UserFactory

PASSWORD = "synthetic-Pass-123"  # noqa: S105

pytestmark = pytest.mark.django_db


def persona(rut: str, email: str = "nueva@example.test") -> dict:
    return {
        "rut": rut,
        "email": email,
        "nombres": "Camila",
        "apellido_paterno": "Soto",
        "apellido_materno": "",
    }


def registrar(tipo: str, datos: dict):
    return registrar_cuenta_cliente(tipo=tipo, datos=datos, password=PASSWORD)


class TestNewClient:
    def test_creates_persona_client_and_account(self):
        cuenta = registrar("persona", persona(synthetic_rut(41_000_001)))

        assert cuenta.cliente.persona.rut == synthetic_rut(41_000_001)
        assert cuenta.cliente.codigo
        assert cuenta.user.check_password(PASSWORD)
        assert not cuenta.user.is_staff
        assert not cuenta.user.groups.exists()

    def test_creates_empresa_client(self):
        cuenta = registrar(
            "empresa",
            {
                "rut": synthetic_rut(78_000_001),
                "email": "empresa.nueva@example.test",
                "razon_social": "Servicios de Ejemplo SpA",
            },
        )

        assert cuenta.cliente.es_empresa
        assert cuenta.user.name == "Servicios de Ejemplo SpA"


class TestExistingRecord:
    def test_links_a_client_whose_email_matches(self):
        cliente = ClienteFactory.create()

        cuenta = registrar(
            "persona",
            persona(cliente.persona.rut, cliente.persona.email.upper()),
        )

        assert cuenta.cliente == cliente

    def test_links_a_persona_on_record_that_is_not_a_client(self):
        existente = PersonaFactory.create()

        cuenta = registrar("persona", persona(existente.rut, existente.email))

        assert cuenta.cliente.persona == existente

    @pytest.mark.parametrize("email", ["otra@example.test", ""])
    def test_rejects_when_the_email_on_record_differs(self, email):
        existente = PersonaFactory.create(email=email)

        with pytest.raises(RegistroRechazadoError):
            registrar("persona", persona(existente.rut, "otra.persona@example.test"))

    def test_rejects_a_client_that_already_has_an_account(self):
        cuenta = CuentaClienteFactory.create()
        parte = cuenta.cliente.persona

        with pytest.raises(RegistroRechazadoError):
            registrar("persona", persona(parte.rut, parte.email))

    def test_rejects_an_email_already_used_by_any_user(self):
        UserFactory.create(email="tomado@example.test")

        with pytest.raises(RegistroRechazadoError):
            registrar(
                "persona",
                persona(synthetic_rut(41_000_002), "TOMADO@example.test"),
            )

    def test_rejection_leaves_no_trace(self):
        empresa = EmpresaFactory.create(email="empresa@example.test")
        antes = Cliente.objects.count()

        with pytest.raises(RegistroRechazadoError):
            registrar(
                "empresa",
                {
                    "rut": empresa.rut,
                    "email": "intruso@example.test",
                    "razon_social": "Otra",
                },
            )

        assert Cliente.objects.count() == antes


def test_weak_password_is_rejected():
    with pytest.raises(ValidationError):
        registrar_cuenta_cliente(
            tipo="persona",
            datos=persona(synthetic_rut(41_000_003)),
            password="123",  # noqa: S106
        )

"""The demo users for staging: one Administrador, one Ejecutivo, two portal clients.

Every name, email and RUT is invented; the passwords come from the environment
(.envs/.staging/.django). Running it again resets those passwords.
"""

from __future__ import annotations

import os
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction

from crm_easyoffice.clientes.models import TipoCliente
from crm_easyoffice.clientes.services import registrar_cuenta_cliente
from crm_easyoffice.core.validators import compute_rut_check_digit

PERSONAL = [
    ("admin@example.test", "Administrador Demo", "Administrador", "ADMIN"),
    ("ejecutivo@example.test", "Ejecutivo Demo", "Ejecutivo", "EJECUTIVO"),
]
CLIENTES = [
    ("cliente1@example.test", "Empresa Demo Uno SpA", 76_950_001, "CLIENTE1"),
    ("cliente2@example.test", "Empresa Demo Dos SpA", 76_950_002, "CLIENTE2"),
]


def _clave(sufijo: str) -> str:
    variable = f"STAGING_DEMO_{sufijo}_PASSWORD"
    clave = os.environ.get(variable, "")
    if not clave or clave == "CHANGEME":
        msg = f"Set {variable}."
        raise CommandError(msg)
    return clave


class Command(BaseCommand):
    help = "Create or reset the demo users. DEBUG only, unless --force."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even when DEBUG is off.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG and not options["force"]:
            msg = "Refusing to load demo data with DEBUG off; pass --force."
            raise CommandError(msg)

        try:
            with transaction.atomic():
                for email, nombre, rol, sufijo in PERSONAL:
                    self._personal(email, nombre, rol, _clave(sufijo))
                for email, razon_social, numero, sufijo in CLIENTES:
                    self._cliente(email, razon_social, numero, _clave(sufijo))
        except ValidationError as error:
            raise CommandError("; ".join(error.messages)) from error
        self.stdout.write(self.style.SUCCESS("Demo users ready."))

    def _personal(self, email: str, nombre: str, rol: str, clave: str) -> None:
        User = get_user_model()  # noqa: N806
        usuario, _ = User.objects.update_or_create(
            email=email,
            defaults={"name": nombre, "is_staff": True, "is_active": True},
        )
        validate_password(clave, user=usuario)
        usuario.set_password(clave)
        usuario.save(update_fields=["password"])
        usuario.groups.set([Group.objects.get(name=rol)])

    def _cliente(self, email: str, razon_social: str, numero: int, clave: str) -> None:
        User = get_user_model()  # noqa: N806
        usuario = User.objects.filter(email=email).first()
        if usuario is not None:
            validate_password(clave, user=usuario)
            usuario.set_password(clave)
            usuario.save(update_fields=["password"])
            return
        registrar_cuenta_cliente(
            tipo=TipoCliente.EMPRESA,
            datos={
                "rut": f"{numero}-{compute_rut_check_digit(str(numero))}",
                "razon_social": razon_social,
                "giro": "Servicios de demostración",
                "email": email,
            },
            password=clave,
        )

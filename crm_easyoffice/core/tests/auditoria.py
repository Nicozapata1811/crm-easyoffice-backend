"""Helpers for the audit log tests. All data is synthetic."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from crm_easyoffice.core.models import RegistroAuditoria
from crm_easyoffice.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from crm_easyoffice.users.models import User

roles = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")


def entradas(
    entidad: str,
    registro_id: int | None = None,
) -> QuerySet[RegistroAuditoria]:
    """A record's entries, oldest first."""
    filas = RegistroAuditoria.objects.filter(entidad=entidad)
    if registro_id is not None:
        filas = filas.filter(registro_id=registro_id)
    return filas.order_by("pk")


def ultima(entidad: str, registro_id: int | None = None) -> RegistroAuditoria:
    return entradas(entidad, registro_id).last()


def usuario_con_rol(rol: str | None) -> User:
    user = UserFactory.create()
    if rol:
        user.groups.add(Group.objects.get(name=rol))
    return user


def api_como(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client

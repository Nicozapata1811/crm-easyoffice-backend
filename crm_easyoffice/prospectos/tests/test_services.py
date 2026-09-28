"""All data here is synthetic."""

from datetime import UTC
from datetime import datetime

import pytest

from crm_easyoffice.integrations.sitio_web.base import ProspectoEntrante
from crm_easyoffice.prospectos.services import calcular_dedup_key
from crm_easyoffice.prospectos.services import registrar_prospecto


def entrante(**overrides) -> ProspectoEntrante:
    values = {
        "nombre": "Luis Ejemplo",
        "email": "luis@example.com",
        "telefono": "+56 9 8765 4321",
        "servicio_interes": "domicilio-tributario",
        "plan": "semestral",
        "origen": "sitio",
        "mensaje": "Hola",
        "recibido_en": datetime(2026, 9, 27, 15, 0, tzinfo=UTC),
        "payload_original": {},
    }
    return ProspectoEntrante(**{**values, **overrides})


def test_dedup_key_ignores_formatting_differences():
    a = entrante(
        email="Luis@Example.com",
        telefono="+56 9 8765 4321",
        mensaje="Hola  mundo",
    )
    b = entrante(email="luis@example.com", telefono="56987654321", mensaje="hola mundo")

    assert calcular_dedup_key(a, "generico") == calcular_dedup_key(b, "generico")


def test_dedup_key_changes_on_another_local_day():
    hoy = entrante(recibido_en=datetime(2026, 9, 27, 15, 0, tzinfo=UTC))
    manana = entrante(recibido_en=datetime(2026, 9, 28, 15, 0, tzinfo=UTC))

    assert calcular_dedup_key(hoy, "generico") != calcular_dedup_key(manana, "generico")


def test_dedup_key_depends_on_formato():
    assert calcular_dedup_key(entrante(), "generico") != calcular_dedup_key(
        entrante(),
        "otro",
    )


@pytest.mark.django_db
def test_registrar_prospecto_is_idempotent():
    first, created_first = registrar_prospecto(entrante(), formato="generico")
    second, created_second = registrar_prospecto(entrante(), formato="generico")

    assert created_first
    assert not created_second
    assert first.pk == second.pk

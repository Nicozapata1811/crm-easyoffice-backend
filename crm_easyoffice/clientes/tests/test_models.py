"""Model tests for client records. Every value here is synthetic."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from crm_easyoffice.clientes.models import EstadoCivil
from crm_easyoffice.clientes.tests.factories import PersonaFactory

pytestmark = pytest.mark.django_db


class TestPersona:
    def test_persona_civil_fields_are_optional(self):
        persona = PersonaFactory.create()

        persona.full_clean()
        assert persona.nacionalidad == ""
        assert persona.estado_civil == ""
        assert persona.profesion == ""

    def test_rejects_unknown_estado_civil(self):
        persona = PersonaFactory.build(estado_civil="comprometido")

        with pytest.raises(ValidationError) as error:
            persona.full_clean()

        assert "estado_civil" in error.value.message_dict

    def test_stores_civil_data(self):
        persona = PersonaFactory.create(con_datos_civiles=True)

        persona.refresh_from_db()
        assert persona.estado_civil == EstadoCivil.SOLTERO
        assert persona.domicilio.startswith("Calle de Ejemplo")

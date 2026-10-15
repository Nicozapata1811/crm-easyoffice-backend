"""Model rules for properties and authorisers. Every value here is synthetic."""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from crm_easyoffice.clientes.tests.factories import EmpresaFactory
from crm_easyoffice.clientes.tests.factories import PersonaFactory
from crm_easyoffice.inmuebles.models import TipoInmueble
from crm_easyoffice.inmuebles.tests.factories import AutorizanteFactory
from crm_easyoffice.inmuebles.tests.factories import OficinaFactory
from crm_easyoffice.inmuebles.tests.factories import representacion

pytestmark = pytest.mark.django_db


class TestOficina:
    def test_branch_code_unique_among_branches(self):
        # LF is seeded by the migrations.
        with pytest.raises(IntegrityError):
            OficinaFactory.create(codigo_sucursal="LF")

    def test_warehouse_cannot_have_branch_code(self):
        with pytest.raises(IntegrityError):
            OficinaFactory.create(tipo=TipoInmueble.BODEGA, codigo_sucursal="BD")

    def test_several_properties_may_have_no_code(self):
        OficinaFactory.create(tipo=TipoInmueble.BODEGA)
        OficinaFactory.create(tipo=TipoInmueble.BODEGA)

    def test_branch_code_must_be_upper_case_letters(self):
        oficina = OficinaFactory.build(codigo_sucursal="l1")

        with pytest.raises(ValidationError) as error:
            oficina.full_clean()

        assert "codigo_sucursal" in error.value.message_dict


class TestAutorizante:
    def test_person_owner_is_valid(self):
        autorizante = AutorizanteFactory.create()

        autorizante.full_clean()

    def test_company_owner_with_its_representative_is_valid(self):
        rep = representacion()

        autorizante = AutorizanteFactory.create(
            persona=None,
            empresa=rep.empresa,
            representante=rep,
        )

        autorizante.full_clean()

    @pytest.mark.parametrize("con_ambos", [True, False])
    def test_autorizante_requires_exactly_one_owner(self, con_ambos):
        rep = representacion()
        datos = {"persona": None, "empresa": None, "representante": None}
        if con_ambos:
            datos = {
                "persona": PersonaFactory.create(),
                "empresa": rep.empresa,
                "representante": rep,
            }

        with pytest.raises(IntegrityError):
            AutorizanteFactory.create(**datos)

    def test_company_owner_requires_representative(self):
        with pytest.raises(IntegrityError):
            AutorizanteFactory.create(persona=None, empresa=EmpresaFactory.create())

    def test_person_owner_cannot_have_representative(self):
        with pytest.raises(IntegrityError):
            AutorizanteFactory.create(representante=representacion())

    def test_representative_must_belong_to_owner_company(self):
        otra_representacion = representacion()
        autorizante = AutorizanteFactory.build(
            persona=None,
            empresa=EmpresaFactory.create(),
            representante=otra_representacion,
            inmueble=OficinaFactory.create(),
        )

        with pytest.raises(ValidationError) as error:
            autorizante.full_clean()

        assert "representante" in error.value.message_dict

    def test_period_must_end_after_it_starts(self):
        with pytest.raises(IntegrityError):
            AutorizanteFactory.create(
                vigente_desde=date(2026, 6, 1),
                vigente_hasta=date(2026, 5, 31),
            )

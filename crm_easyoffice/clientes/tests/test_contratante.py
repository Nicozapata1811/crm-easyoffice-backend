"""What a client types about their company and signer. Synthetic data only."""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from crm_easyoffice.clientes.models import Persona
from crm_easyoffice.clientes.models import RepresentanteLegal
from crm_easyoffice.clientes.services import ClienteNoEsEmpresaError
from crm_easyoffice.clientes.services import RepresentanteNoDisponibleError
from crm_easyoffice.clientes.services import datos_contratante
from crm_easyoffice.clientes.services import guardar_datos_contratante
from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.clientes.tests.factories import EmpresaFactory
from crm_easyoffice.clientes.tests.factories import PersonaFactory
from crm_easyoffice.clientes.tests.factories import RepresentanteLegalFactory
from crm_easyoffice.clientes.tests.factories import synthetic_rut

pytestmark = pytest.mark.django_db

RUT_NUEVO = synthetic_rut(31_234_567)


def cliente_empresa():
    return ClienteFactory.create(persona=None, empresa=EmpresaFactory.create())


def datos(cliente, rut_representante: str = RUT_NUEVO, **extra):
    return {
        "empresa": {
            "rut": cliente.empresa.rut,
            "razon_social": "Comercial de Prueba SpA",
            "giro": "Venta de artículos de ejemplo",
        },
        "representante": {
            "rut": rut_representante,
            "nombres": "Ana María",
            "apellido_paterno": "Ejemplo",
            "apellido_materno": "Ficticia",
            "domicilio": "Pasaje de Prueba 123",
            "comuna": "Comuna de Ejemplo",
            "region": "Región Metropolitana de Santiago",
        },
        "personeria": {
            "fecha_instrumento": date(2025, 12, 10),
            "sitio_o_notaria": "www.tuempresaenundia.cl",
        },
        **extra,
    }


class TestDatosContratante:
    def test_prefills_from_the_clients_own_records(self):
        representacion = RepresentanteLegalFactory.create(
            persona=PersonaFactory.create(con_datos_civiles=True),
            fecha_instrumento=date(2025, 1, 2),
            sitio_o_notaria="Notaría de Ejemplo",
        )
        cliente = ClienteFactory.create(persona=None, empresa=representacion.empresa)

        prefill = datos_contratante(cliente)

        persona = representacion.persona
        assert prefill["empresa"]["rut"] == cliente.empresa.rut
        assert prefill["representante"]["rut"] == persona.rut
        assert prefill["representante"]["domicilio"] == persona.domicilio
        assert prefill["personeria"] == {
            "fecha_instrumento": date(2025, 1, 2),
            "sitio_o_notaria": "Notaría de Ejemplo",
        }

    def test_leaves_blanks_without_a_representative(self):
        prefill = datos_contratante(cliente_empresa())

        assert set(prefill["representante"].values()) == {""}
        assert prefill["personeria"] == {
            "fecha_instrumento": None,
            "sitio_o_notaria": "",
        }

    def test_a_person_client_has_no_company_data(self):
        with pytest.raises(ClienteNoEsEmpresaError):
            datos_contratante(ClienteFactory.create())


class TestGuardarDatosContratante:
    def test_a_new_rut_creates_the_person_and_the_representation(self):
        cliente = cliente_empresa()

        representacion = guardar_datos_contratante(cliente, **datos(cliente))

        assert representacion.persona.rut == RUT_NUEVO
        assert representacion.persona.domicilio == "Pasaje de Prueba 123"
        assert representacion.empresa == cliente.empresa
        assert representacion.vigente_desde == date(2025, 12, 10)
        assert representacion.sitio_o_notaria == "www.tuempresaenundia.cl"
        cliente.empresa.refresh_from_db()
        assert cliente.empresa.giro == "Venta de artículos de ejemplo"

    def test_the_companys_representative_is_updated(self):
        existente = RepresentanteLegalFactory.create()
        cliente = ClienteFactory.create(persona=None, empresa=existente.empresa)

        representacion = guardar_datos_contratante(
            cliente,
            **datos(cliente, existente.persona.rut),
        )

        assert representacion == existente
        existente.persona.refresh_from_db()
        assert existente.persona.nombres == "Ana María"
        assert RepresentanteLegal.objects.filter(empresa=cliente.empresa).count() == 1

    def test_someone_elses_record_is_never_touched(self):
        ajena = PersonaFactory.create(nombres="Original")
        cliente = cliente_empresa()

        with pytest.raises(RepresentanteNoDisponibleError):
            guardar_datos_contratante(cliente, **datos(cliente, ajena.rut))

        ajena.refresh_from_db()
        assert ajena.nombres == "Original"
        assert not RepresentanteLegal.objects.filter(persona=ajena).exists()
        cliente.empresa.refresh_from_db()
        assert cliente.empresa.giro == ""

    def test_the_rut_is_normalised(self):
        cliente = cliente_empresa()
        con_puntos = f"{int(RUT_NUEVO[:-2]):,}".replace(",", ".") + RUT_NUEVO[-2:]

        guardar_datos_contratante(cliente, **datos(cliente, con_puntos))

        assert Persona.objects.filter(rut=RUT_NUEVO).exists()

    def test_another_company_rut_is_rejected(self):
        cliente = cliente_empresa()
        otros = datos(cliente)
        otros["empresa"]["rut"] = EmpresaFactory.create().rut

        with pytest.raises(ValidationError):
            guardar_datos_contratante(cliente, **otros)

    def test_a_person_client_cannot_contract_for_a_company(self):
        cliente = ClienteFactory.create()

        with pytest.raises(ClienteNoEsEmpresaError):
            guardar_datos_contratante(cliente, **datos(cliente_empresa()))

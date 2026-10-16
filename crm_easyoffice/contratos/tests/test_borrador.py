"""Portal drafts: contracts on a plan, editable until signed. Synthetic data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from crm_easyoffice.clientes.tests.factories import RepresentanteLegalFactory
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.contratos.services import ContratoNoEditableError
from crm_easyoffice.contratos.services import LineaContrato
from crm_easyoffice.contratos.services import activar_contrato
from crm_easyoffice.contratos.services import actualizar_borrador
from crm_easyoffice.contratos.services import anular_borrador
from crm_easyoffice.contratos.services import ocupantes
from crm_easyoffice.contratos.tests.factories import INICIO
from crm_easyoffice.contratos.tests.factories import nuevo_contrato
from crm_easyoffice.contratos.tests.factories import servicio
from crm_easyoffice.contratos.tests.factories import sucursal
from crm_easyoffice.ventas.models import CicloPago
from crm_easyoffice.ventas.models import PlanServicio

pytestmark = pytest.mark.django_db


def plan(codigo: str) -> PlanServicio:
    return PlanServicio.objects.get(
        servicio__codigo="domicilio-tributario", codigo=codigo
    )


def linea_plan(codigo: str = "semestral", sucursal_codigo: str = "LF") -> LineaContrato:
    return LineaContrato(
        servicio=servicio(),
        inmueble=sucursal(sucursal_codigo),
        plan=plan(codigo),
    )


def borrador(**datos) -> Contrato:
    return nuevo_contrato(
        lineas=[linea_plan()],
        duracion_meses=6,
        borrador=True,
        **datos,
    )


class TestPlanes:
    def test_a_plan_sets_price_and_cycle(self):
        contrato = borrador()

        (linea,) = contrato.servicios.all()
        assert linea.precio == Decimal(39990)
        assert linea.ciclo_pago.codigo == "semestral"
        assert contrato.fecha_vencimiento == date(2027, 4, 1)

    def test_a_plan_rejects_a_different_duration(self):
        with pytest.raises(ValidationError) as error:
            nuevo_contrato(lineas=[linea_plan("anual")], duracion_meses=6)

        assert set(error.value.message_dict) == {"duracion_meses"}

    def test_a_plan_cannot_be_combined_with_a_cycle(self):
        linea = LineaContrato(
            servicio=servicio(),
            inmueble=sucursal("LF"),
            plan=plan("anual"),
            ciclo_pago=CicloPago.objects.get(codigo="mensual"),
        )

        with pytest.raises(ValidationError):
            nuevo_contrato(lineas=[linea])

    def test_a_plan_of_another_service_is_rejected(self):
        linea = LineaContrato(
            servicio=servicio("creacion-empresas"),
            plan=plan("anual"),
        )

        with pytest.raises(ValidationError):
            nuevo_contrato(lineas=[linea], codigo_sucursal="LF")


class TestBorrador:
    def test_a_draft_has_a_folio_but_occupies_no_domicile(self):
        contrato = borrador()

        assert contrato.estado == Contrato.Estado.BORRADOR
        assert contrato.folio.startswith("LF-")
        assert ocupantes(sucursal("LF"), INICIO) == []

    def test_an_active_contract_occupies_the_domicile(self):
        contrato = activar_contrato(borrador())

        assert contrato.estado == Contrato.Estado.VIGENTE
        assert ocupantes(sucursal("LF"), INICIO) == [contrato.cliente]

    def test_editing_keeps_the_folio_and_recomputes_the_term(self):
        contrato = borrador()
        folio = contrato.folio

        actualizado = actualizar_borrador(
            contrato,
            lineas=[linea_plan("anual")],
            fecha_inicio=date(2026, 10, 20),
            duracion_meses=12,
            representante=None,
            email_aviso="avisos@empresa-ficticia.example",
            movil_aviso="911111111",
        )

        assert actualizado.folio == folio
        assert actualizado.fecha_vencimiento == date(2027, 10, 19)
        assert actualizado.movil_aviso == "911111111"
        (linea,) = actualizado.servicios.all()
        assert linea.precio == Decimal(59990)

    def test_the_branch_cannot_change(self):
        contrato = borrador()

        with pytest.raises(ValidationError) as error:
            actualizar_borrador(
                contrato,
                lineas=[linea_plan("semestral", "VL")],
                fecha_inicio=INICIO,
                duracion_meses=6,
                representante=None,
                email_aviso="",
                movil_aviso="",
            )

        assert "codigo_sucursal" in error.value.message_dict

    def test_the_signer_must_represent_the_client(self):
        contrato = borrador()

        with pytest.raises(ValidationError):
            actualizar_borrador(
                contrato,
                lineas=[linea_plan()],
                fecha_inicio=INICIO,
                duracion_meses=6,
                representante=RepresentanteLegalFactory.create(),
                email_aviso="",
                movil_aviso="",
            )

    def test_only_a_draft_can_be_edited_activated_or_annulled(self):
        contrato = nuevo_contrato()

        with pytest.raises(ContratoNoEditableError):
            activar_contrato(contrato)
        with pytest.raises(ContratoNoEditableError):
            anular_borrador(contrato)
        with pytest.raises(ContratoNoEditableError):
            actualizar_borrador(
                contrato,
                lineas=[linea_plan("anual")],
                fecha_inicio=INICIO,
                duracion_meses=12,
                representante=None,
                email_aviso="",
                movil_aviso="",
            )

    def test_an_annulled_draft_keeps_its_folio(self):
        contrato = borrador()

        anulado = anular_borrador(contrato)

        assert anulado.estado == Contrato.Estado.ANULADO
        assert Contrato.objects.filter(folio=contrato.folio).exists()

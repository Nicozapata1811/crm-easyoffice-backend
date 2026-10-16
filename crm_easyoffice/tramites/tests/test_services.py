"""The domicile case and its state machine. Every value here is synthetic."""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from crm_easyoffice.clientes.services import RepresentanteNoDisponibleError
from crm_easyoffice.clientes.tests.factories import CuentaClienteFactory
from crm_easyoffice.clientes.tests.factories import PersonaFactory
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.integrations.payment.base import PaymentResult
from crm_easyoffice.integrations.payment.base import PaymentStatus
from crm_easyoffice.tramites.models import EventoTramite
from crm_easyoffice.tramites.models import EventoTramiteError
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.services import FALTA_INFORMACION
from crm_easyoffice.tramites.services import FIRMA
from crm_easyoffice.tramites.services import NO_DISPONIBLE
from crm_easyoffice.tramites.services import NUEVA_FECHA
from crm_easyoffice.tramites.services import PAGO
from crm_easyoffice.tramites.services import REVISION_BORRADOR
from crm_easyoffice.tramites.services import FechaInicioVencidaError
from crm_easyoffice.tramites.services import TramiteNoDisponibleError
from crm_easyoffice.tramites.services import TransicionInvalidaError
from crm_easyoffice.tramites.services import actualizar_domicilio
from crm_easyoffice.tramites.services import cambiar_fecha_inicio
from crm_easyoffice.tramites.services import completar
from crm_easyoffice.tramites.services import confirmar_borrador
from crm_easyoffice.tramites.services import documento_fallido
from crm_easyoffice.tramites.services import documento_listo
from crm_easyoffice.tramites.services import formulario_domicilio
from crm_easyoffice.tramites.services import iniciar_domicilio
from crm_easyoffice.tramites.services import situacion
from crm_easyoffice.tramites.services import verificar_para_firma
from crm_easyoffice.tramites.signals import documento_requerido
from crm_easyoffice.tramites.tests.factories import RUT_REPRESENTANTE
from crm_easyoffice.tramites.tests.factories import cuenta_empresa
from crm_easyoffice.tramites.tests.factories import datos_domicilio
from crm_easyoffice.tramites.tests.factories import preparar_domicilio
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.models import Venta
from crm_easyoffice.ventas.services import aplicar_resultado

pytestmark = pytest.mark.django_db


@pytest.fixture
def sucursal():
    return preparar_domicilio("LF")


@pytest.fixture
def cliente():
    return cuenta_empresa().cliente


def nuevo(cliente, sucursal, **extra) -> Tramite:
    return iniciar_domicilio(cliente, datos_domicilio(cliente, sucursal, **extra))


def en_revision(cliente, sucursal, **extra) -> Tramite:
    return documento_listo(nuevo(cliente, sucursal, **extra))


def pagar(venta: Venta, django_capture_on_commit_callbacks) -> None:
    orden = OrdenPago.objects.create(
        venta=venta,
        proveedor="simulated",
        monto=venta.total,
    )
    with django_capture_on_commit_callbacks(execute=True):
        aplicar_resultado(
            orden.pk,
            PaymentResult(
                external_id="",
                reference=str(orden.referencia),
                status=PaymentStatus.PAID,
                amount=venta.total,
            ),
            origen="test",
        )


def vencer(tramite: Tramite) -> None:
    Contrato.objects.filter(pk=tramite.contrato_id).update(
        fecha_inicio=timezone.localdate() - timedelta(days=1),
    )


class TestIniciar:
    def test_records_the_draft_contract_and_opens_the_case(self, cliente, sucursal):
        tramite = nuevo(cliente, sucursal, plan="semestral")

        assert situacion(tramite) == ("iniciado", None)
        assert tramite.folio.startswith("TRA-")
        assert tramite.datos == {
            "plan": "semestral",
            "sucursal": sucursal.pk,
            "fecha_inicio": timezone.localdate().isoformat(),
        }
        contrato = tramite.contrato
        assert contrato.estado == Contrato.Estado.BORRADOR
        assert contrato.folio.startswith("LF-")
        assert contrato.duracion_meses == 6  # noqa: PLR2004
        assert contrato.representante.persona.rut == RUT_REPRESENTANTE
        assert contrato.email_aviso == "contacto@empresa-ficticia.example"
        (linea,) = contrato.servicios.all()
        assert (linea.precio, linea.inmueble) == (Decimal(39990), sucursal)
        assert tramite.eventos.get().estado_nuevo == "iniciado"

    def test_asks_for_the_document_after_commit(
        self,
        cliente,
        sucursal,
        django_capture_on_commit_callbacks,
    ):
        pedidos = []

        def receptor(sender, tramite, **kwargs):
            pedidos.append(tramite.pk)

        documento_requerido.connect(receptor)
        try:
            with django_capture_on_commit_callbacks(execute=True):
                tramite = nuevo(cliente, sucursal)
        finally:
            documento_requerido.disconnect(receptor)

        assert pedidos == [tramite.pk]

    def test_a_person_client_cannot_file_it_online(self, sucursal):
        cliente = CuentaClienteFactory.create().cliente

        with pytest.raises(TramiteNoDisponibleError):
            iniciar_domicilio(cliente, {})

    def test_incomplete_configuration_blocks_it(self, cliente):
        sucursal = preparar_domicilio("LF")
        from crm_easyoffice.configuracion.models import ConfigEmpresa  # noqa: PLC0415

        ConfigEmpresa.objects.update(representante=None)

        with pytest.raises(TramiteNoDisponibleError):
            nuevo(cliente, sucursal)

    def test_an_incomplete_branch_is_refused(self, cliente, sucursal):
        from crm_easyoffice.inmuebles.models import Oficina  # noqa: PLC0415

        vl = Oficina.objects.get(codigo_sucursal="VL")

        with pytest.raises(ValidationError) as error:
            nuevo(cliente, vl)

        assert set(error.value.message_dict) == {"sucursal"}
        assert not Tramite.objects.exists()

    @pytest.mark.parametrize("dias", [-1, 31])
    def test_the_start_date_must_be_within_the_window(self, cliente, sucursal, dias):
        with pytest.raises(ValidationError) as error:
            nuevo(
                cliente,
                sucursal,
                fecha_inicio=timezone.localdate() + timedelta(days=dias),
            )

        assert set(error.value.message_dict) == {"fecha_inicio"}

    def test_an_unknown_plan_is_refused(self, cliente, sucursal):
        with pytest.raises(ValidationError) as error:
            nuevo(cliente, sucursal, plan="mensual")

        assert set(error.value.message_dict) == {"plan"}

    def test_someone_elses_rut_creates_nothing(self, cliente, sucursal):
        ajena = PersonaFactory.create()
        datos = datos_domicilio(cliente, sucursal)
        datos["representante"]["rut"] = ajena.rut

        with pytest.raises(RepresentanteNoDisponibleError):
            iniciar_domicilio(cliente, datos)

        assert not Contrato.objects.exists()
        assert not Tramite.objects.exists()


class TestFlujo:
    def test_a_generated_document_waits_for_review(self, cliente, sucursal):
        tramite = en_revision(cliente, sucursal)

        assert situacion(tramite) == ("pendiente", REVISION_BORRADOR)

    def test_a_failed_document_waits_for_information(self, cliente, sucursal):
        tramite = documento_fallido(nuevo(cliente, sucursal), "Falta el reverso.")

        assert situacion(tramite) == ("pendiente", FALTA_INFORMACION)
        assert tramite.detalle_pendiente == "Falta el reverso."

    def test_confirming_the_annual_plan_charges_one_line(self, cliente, sucursal):
        tramite = confirmar_borrador(en_revision(cliente, sucursal, plan="anual"))

        assert situacion(tramite) == ("pendiente", PAGO)
        items = list(tramite.venta.items.values_list("servicio__codigo", "subtotal"))
        assert items == [("domicilio-tributario", Decimal(59990))]

    def test_confirming_the_half_yearly_plan_adds_the_signature(
        self,
        cliente,
        sucursal,
    ):
        tramite = confirmar_borrador(en_revision(cliente, sucursal, plan="semestral"))

        assert tramite.venta.total == Decimal(44990)
        assert tramite.venta.items.count() == 2  # noqa: PLR2004

    def test_a_past_start_date_cannot_be_confirmed(self, cliente, sucursal):
        tramite = en_revision(cliente, sucursal)
        vencer(tramite)

        with pytest.raises(FechaInicioVencidaError):
            confirmar_borrador(tramite)
        assert not Venta.objects.exists()

    def test_payment_moves_the_case_to_signing(
        self,
        cliente,
        sucursal,
        django_capture_on_commit_callbacks,
    ):
        tramite = confirmar_borrador(en_revision(cliente, sucursal))

        pagar(tramite.venta, django_capture_on_commit_callbacks)

        tramite.refresh_from_db()
        assert situacion(tramite) == ("pendiente", FIRMA)

    def test_a_payment_after_the_start_date_asks_for_a_new_one(
        self,
        cliente,
        sucursal,
        django_capture_on_commit_callbacks,
    ):
        tramite = confirmar_borrador(en_revision(cliente, sucursal))
        vencer(tramite)

        pagar(tramite.venta, django_capture_on_commit_callbacks)

        tramite.refresh_from_db()
        assert situacion(tramite) == ("pendiente", FALTA_INFORMACION)
        assert tramite.detalle_pendiente == NUEVA_FECHA

        manana = timezone.localdate() + timedelta(days=1)
        tramite = cambiar_fecha_inicio(tramite, manana)
        assert situacion(tramite) == ("iniciado", None)
        assert tramite.contrato.fecha_inicio == manana

        tramite = documento_listo(tramite)
        assert situacion(tramite) == ("pendiente", FIRMA)

    def test_signing_with_a_past_date_asks_for_a_new_one(
        self,
        cliente,
        sucursal,
        django_capture_on_commit_callbacks,
    ):
        tramite = confirmar_borrador(en_revision(cliente, sucursal))
        pagar(tramite.venta, django_capture_on_commit_callbacks)
        vencer(tramite)

        with pytest.raises(FechaInicioVencidaError):
            verificar_para_firma(tramite)

        tramite.refresh_from_db()
        assert situacion(tramite) == ("pendiente", FALTA_INFORMACION)

    def test_completing_puts_the_contract_in_force(
        self,
        cliente,
        sucursal,
        django_capture_on_commit_callbacks,
    ):
        tramite = confirmar_borrador(en_revision(cliente, sucursal))
        pagar(tramite.venta, django_capture_on_commit_callbacks)

        tramite = completar(tramite)

        assert situacion(tramite) == ("completado", None)
        tramite.contrato.refresh_from_db()
        assert tramite.contrato.estado == Contrato.Estado.VIGENTE

    def test_a_case_cannot_skip_steps(self, cliente, sucursal):
        tramite = en_revision(cliente, sucursal)

        with pytest.raises(TransicionInvalidaError):
            completar(tramite)


class TestEditar:
    def test_editing_before_payment_cancels_the_sale(self, cliente, sucursal):
        tramite = confirmar_borrador(en_revision(cliente, sucursal, plan="anual"))
        venta = tramite.venta
        folio = tramite.contrato.folio

        tramite = actualizar_domicilio(
            tramite,
            datos_domicilio(cliente, sucursal, plan="semestral"),
        )

        venta.refresh_from_db()
        assert venta.estado == Venta.Estado.ANULADA
        assert tramite.venta is None
        assert situacion(tramite) == ("iniciado", None)
        assert tramite.datos["plan"] == "semestral"
        assert tramite.contrato.folio == folio
        assert tramite.contrato.duracion_meses == 6  # noqa: PLR2004

    def test_a_paid_case_cannot_be_edited(
        self,
        cliente,
        sucursal,
        django_capture_on_commit_callbacks,
    ):
        tramite = confirmar_borrador(en_revision(cliente, sucursal))
        pagar(tramite.venta, django_capture_on_commit_callbacks)
        tramite.refresh_from_db()

        with pytest.raises(TransicionInvalidaError):
            actualizar_domicilio(tramite, datos_domicilio(cliente, sucursal))

    def test_the_date_alone_changes_only_when_asked(self, cliente, sucursal):
        tramite = en_revision(cliente, sucursal)

        with pytest.raises(TransicionInvalidaError):
            cambiar_fecha_inicio(tramite, timezone.localdate())


class TestHistorial:
    def test_every_move_is_recorded(self, cliente, sucursal):
        tramite = confirmar_borrador(en_revision(cliente, sucursal))

        assert list(
            tramite.eventos.values_list("estado_nuevo", "motivo_nuevo"),
        ) == [
            ("iniciado", ""),
            ("pendiente", REVISION_BORRADOR),
            ("pendiente", PAGO),
        ]

    def test_the_history_is_append_only(self, cliente, sucursal):
        evento = nuevo(cliente, sucursal).eventos.get()

        with pytest.raises(EventoTramiteError):
            evento.save()
        with pytest.raises(EventoTramiteError):
            evento.delete()
        assert EventoTramite.objects.count() == 1

    def test_a_reason_exists_only_while_pending(self, cliente, sucursal):
        tramite = en_revision(cliente, sucursal)

        with pytest.raises(IntegrityError):
            Tramite.objects.filter(pk=tramite.pk).update(estado="completado")


class TestFormulario:
    def test_prefills_from_the_clients_records_only(self, cliente, sucursal):
        nuevo(cliente, sucursal)

        formulario = formulario_domicilio(cliente)

        assert formulario["disponible"] is True
        assert formulario["sucursales"] == [sucursal]
        assert [p.codigo for p in formulario["planes"]] == ["anual", "semestral"]
        datos = formulario["datos"]
        assert datos["empresa"]["razon_social"] == "Comercial Ficticia del Sur SpA"
        assert datos["representante"]["rut"] == RUT_REPRESENTANTE
        assert datos["contacto"] == {
            "email_aviso": "contacto@empresa-ficticia.example",
            "movil_aviso": "912345678",
        }

    def test_a_new_client_gets_blanks(self, cliente, sucursal):
        datos = formulario_domicilio(cliente)["datos"]

        assert datos["empresa"]["rut"] == cliente.empresa.rut
        assert set(datos["representante"].values()) == {""}
        assert datos["personeria"]["fecha_instrumento"] is None

    def test_a_person_client_is_told_to_contact_us(self, sucursal):
        formulario = formulario_domicilio(CuentaClienteFactory.create().cliente)

        assert formulario["disponible"] is False
        assert "para empresas" in formulario["motivo_no_disponible"]
        assert formulario["datos"] is None

    def test_without_a_ready_branch_the_form_is_unavailable(self, cliente):
        preparar_domicilio("LF")
        from crm_easyoffice.inmuebles.models import Autorizante  # noqa: PLC0415

        Autorizante.objects.update(vigente_hasta=date(2026, 6, 30))

        formulario = formulario_domicilio(cliente)

        assert formulario["disponible"] is False
        assert formulario["motivo_no_disponible"] == NO_DISPONIBLE
        assert formulario["sucursales"] == []

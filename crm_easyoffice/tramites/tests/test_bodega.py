"""The warehouse case (PLT-02), started by an executive. Synthetic data only."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.clientes.tests.factories import synthetic_rut
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.inmuebles.models import Oficina
from crm_easyoffice.inmuebles.tests.factories import preparar_bodega
from crm_easyoffice.tramites.models import TipoTramite
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.services import FALTA_INFORMACION
from crm_easyoffice.tramites.services import FIRMA
from crm_easyoffice.tramites.services import NUEVA_FECHA
from crm_easyoffice.tramites.services import REVISION_BORRADOR
from crm_easyoffice.tramites.services import TIPO_DOMICILIO
from crm_easyoffice.tramites.services import FechaInicioVencidaError
from crm_easyoffice.tramites.services import TramiteNoDisponibleError
from crm_easyoffice.tramites.services import TransicionInvalidaError
from crm_easyoffice.tramites.services import actualizar_domicilio
from crm_easyoffice.tramites.services import actualizar_tramite
from crm_easyoffice.tramites.services import cambiar_fecha_inicio
from crm_easyoffice.tramites.services import completar
from crm_easyoffice.tramites.services import confirmar_borrador
from crm_easyoffice.tramites.services import documento_listo
from crm_easyoffice.tramites.services import formulario_tramite
from crm_easyoffice.tramites.services import iniciar_tramite
from crm_easyoffice.tramites.services import situacion
from crm_easyoffice.tramites.services import tipo_tramite
from crm_easyoffice.tramites.services import tipos_iniciables
from crm_easyoffice.tramites.services import verificar_para_firma
from crm_easyoffice.tramites.tests.factories import TIPO_BODEGA
from crm_easyoffice.tramites.tests.factories import cliente_empresa
from crm_easyoffice.tramites.tests.factories import datos_bodega
from crm_easyoffice.tramites.tests.factories import preparar_bodega_caso
from crm_easyoffice.users.tests.factories import UserFactory
from crm_easyoffice.ventas.models import Venta

pytestmark = pytest.mark.django_db

BACKOFFICE = Tramite.Canal.BACKOFFICE


@pytest.fixture
def inmuebles():
    return preparar_bodega_caso("LF")


@pytest.fixture
def cliente():
    return cliente_empresa()


@pytest.fixture
def ejecutivo():
    return UserFactory.create()


def tipo() -> TipoTramite:
    return tipo_tramite(TIPO_BODEGA)


def nuevo(cliente, inmuebles, usuario=None, **extra) -> Tramite:
    sucursal, bodega = inmuebles
    return iniciar_tramite(
        tipo(),
        cliente,
        datos_bodega(cliente, sucursal, bodega, **extra),
        canal=BACKOFFICE,
        usuario=usuario,
    )


def exclusivo(*, valor: bool) -> None:
    registro = tipo()
    for linea in registro.configuracion["lineas"]:
        if linea["inmueble"] == "bodega":
            linea["inmueble_exclusivo"] = valor
    registro.save()


def test_the_seed_explains_both_types():
    domicilio = TipoTramite.objects.get(codigo=TIPO_DOMICILIO).configuracion
    bodega = tipo().configuracion

    assert (domicilio["planes"], domicilio["canal"]) == (True, "portal")
    assert (bodega["planes"], bodega["canal"]) == (False, "backoffice")
    assert bodega["requiere_pago"] is False
    assert [linea["inmueble"] for linea in bodega["lineas"]] == ["sucursal", "bodega"]
    assert [t.codigo for t in tipos_iniciables(BACKOFFICE)] == [TIPO_BODEGA]


class TestIniciar:
    def test_records_both_lines_on_a_draft_with_the_branch_folio(
        self,
        cliente,
        inmuebles,
        ejecutivo,
    ):
        sucursal, bodega = inmuebles
        tramite = nuevo(cliente, inmuebles, ejecutivo)

        assert (tramite.canal, situacion(tramite)) == (BACKOFFICE, ("iniciado", None))
        contrato = tramite.contrato
        assert contrato.estado == Contrato.Estado.BORRADOR
        assert contrato.folio.startswith("LF-")
        assert contrato.duracion_meses == 12  # noqa: PLR2004
        assert contrato.ejecutivo_responsable == ejecutivo
        lineas = list(contrato.servicios.order_by("orden"))
        assert [(s.servicio.codigo, s.inmueble) for s in lineas] == [
            ("domicilio-tributario", sucursal),
            ("bodega", bodega),
        ]
        assert lineas[1].precio == Decimal(20000)
        assert lineas[1].ciclo_pago.codigo == "anual"
        assert tramite.datos["bodega"] == bodega.pk
        assert "plan" not in tramite.datos

    def test_a_person_client_is_refused(self, cliente, inmuebles):
        sucursal, bodega = inmuebles
        with pytest.raises(TramiteNoDisponibleError):
            iniciar_tramite(
                tipo(),
                ClienteFactory.create(),
                datos_bodega(cliente, sucursal, bodega),
                canal=BACKOFFICE,
            )

    def test_the_portal_cannot_start_it(self, cliente, inmuebles):
        sucursal, bodega = inmuebles
        with pytest.raises(TramiteNoDisponibleError):
            iniciar_tramite(
                tipo(),
                cliente,
                datos_bodega(cliente, sucursal, bodega),
                canal=Tramite.Canal.PORTAL,
            )

    def test_the_warehouse_needs_its_agreed_price(self, cliente, inmuebles):
        with pytest.raises(ValidationError) as error:
            nuevo(cliente, inmuebles, lineas=[{"servicio": "bodega"}])

        assert set(error.value.message_dict) == {"servicios"}
        assert not Tramite.objects.exists()

    def test_the_domicile_keeps_its_list_price(self, cliente, inmuebles):
        lineas = [
            {"servicio": "domicilio-tributario", "precio": "1000"},
            {"servicio": "bodega", "ciclo_pago": "anual", "precio": "20000"},
        ]
        with pytest.raises(ValidationError) as error:
            nuevo(cliente, inmuebles, lineas=lineas)

        assert set(error.value.message_dict) == {"servicios"}

    def test_an_incomplete_warehouse_is_refused(self, cliente, inmuebles):
        _, bodega = inmuebles
        Oficina.objects.filter(pk=bodega.pk).update(rol_avaluo="PENDIENTE-B")

        with pytest.raises(ValidationError) as error:
            nuevo(cliente, inmuebles)

        assert set(error.value.message_dict) == {"bodega"}

    def test_a_branch_is_not_a_warehouse(self, cliente, inmuebles):
        sucursal, _ = inmuebles

        with pytest.raises(ValidationError) as error:
            nuevo(cliente, (sucursal, sucursal))

        assert set(error.value.message_dict) == {"bodega"}

    def test_the_branch_needs_only_its_location(self, cliente):
        preparar_bodega_caso("LF")
        vl = Oficina.objects.get(codigo_sucursal="VL")
        vl.calle, vl.numero = "Calle de Prueba", "200"
        vl.save()
        bodega = preparar_bodega().inmueble

        tramite = nuevo(cliente, (vl, bodega))

        assert tramite.contrato.folio.startswith("VL-")


class TestDisponibilidad:
    def test_a_shared_warehouse_takes_several_clients(self, inmuebles):
        nuevo(cliente_empresa(), inmuebles)
        otro = cliente_empresa()
        sucursal, bodega = inmuebles
        datos = datos_bodega(otro, sucursal, bodega)
        datos["representante"]["rut"] = synthetic_rut(33_444_555)
        iniciar_tramite(tipo(), otro, datos, canal=BACKOFFICE)

        assert Tramite.objects.count() == 2  # noqa: PLR2004

    def test_an_exclusive_warehouse_takes_one_client_at_a_time(self, inmuebles):
        exclusivo(valor=True)
        nuevo(cliente_empresa(), inmuebles)

        with pytest.raises(ValidationError) as error:
            nuevo(cliente_empresa(), inmuebles)

        assert set(error.value.message_dict) == {"bodega"}

    def test_an_exclusive_warehouse_is_not_offered_while_held(self, inmuebles):
        exclusivo(valor=True)
        _, bodega = inmuebles
        assert formulario_tramite(tipo(), cliente_empresa())["inmuebles"]["bodega"] == [
            bodega,
        ]

        nuevo(cliente_empresa(), inmuebles)

        formulario = formulario_tramite(tipo(), cliente_empresa())
        assert formulario["disponible"] is False
        assert formulario["inmuebles"]["bodega"] == []

    def test_editing_its_own_request_keeps_an_exclusive_warehouse(
        self,
        cliente,
        inmuebles,
    ):
        exclusivo(valor=True)
        sucursal, bodega = inmuebles
        tramite = documento_listo(nuevo(cliente, inmuebles))

        actualizar_tramite(
            tramite,
            datos_bodega(cliente, sucursal, bodega, duracion_meses=6),
            canal=BACKOFFICE,
        )

        tramite.contrato.refresh_from_db()
        assert tramite.contrato.duracion_meses == 6  # noqa: PLR2004


class TestFormulario:
    def test_offers_ready_branches_warehouses_and_the_lines(self, cliente, inmuebles):
        sucursal, bodega = inmuebles

        formulario = formulario_tramite(tipo(), cliente)

        assert formulario["disponible"] is True
        assert formulario["planes"] == []
        assert 12 in formulario["duraciones"]  # noqa: PLR2004
        assert formulario["duracion_por_defecto"] == 12  # noqa: PLR2004
        assert formulario["inmuebles"] == {"sucursal": [sucursal], "bodega": [bodega]}
        assert [linea["servicio"].codigo for linea in formulario["lineas"]] == [
            "domicilio-tributario",
            "bodega",
        ]
        assert formulario["datos"]["empresa"]["rut"] == cliente.empresa.rut

    def test_without_a_ready_warehouse_staff_see_why(self, cliente):
        preparar_bodega_caso("LF")
        Oficina.objects.filter(tipo="bodega").update(activa=False)

        formulario = formulario_tramite(tipo(), cliente)

        assert formulario["disponible"] is False
        assert any("«bodega»" in problema for problema in formulario["problemas"])

    def test_a_person_client_gets_the_staff_reason(self, inmuebles):
        formulario = formulario_tramite(tipo(), ClienteFactory.create())

        assert formulario["problemas"] == [
            "«Bodega virtual» no es para este tipo de cliente.",
        ]
        assert formulario["datos"] is None


class TestCiclo:
    def test_confirming_goes_straight_to_signing_without_a_sale(
        self,
        cliente,
        inmuebles,
        ejecutivo,
    ):
        tramite = documento_listo(nuevo(cliente, inmuebles, ejecutivo))
        assert situacion(tramite) == ("pendiente", REVISION_BORRADOR)

        tramite = confirmar_borrador(tramite, ejecutivo, canal=BACKOFFICE)

        assert situacion(tramite) == ("pendiente", FIRMA)
        assert tramite.venta is None
        assert not Venta.objects.exists()
        evento = tramite.eventos.order_by("-pk").first()
        assert (evento.usuario, evento.detalle) == (
            ejecutivo,
            "El ejecutivo registró la confirmación del cliente.",
        )

    def test_signing_completes_and_puts_the_contract_in_force(
        self,
        cliente,
        inmuebles,
        ejecutivo,
    ):
        tramite = documento_listo(nuevo(cliente, inmuebles))
        tramite = confirmar_borrador(tramite, ejecutivo, canal=BACKOFFICE)
        verificar_para_firma(tramite, ejecutivo)

        tramite = completar(tramite, ejecutivo)

        assert situacion(tramite) == ("completado", None)
        tramite.contrato.refresh_from_db()
        assert tramite.contrato.estado == Contrato.Estado.VIGENTE
        assert [e.motivo_nuevo for e in tramite.eventos.all()] == [
            "",
            REVISION_BORRADOR,
            FIRMA,
            "",
        ]

    def test_a_passed_date_is_set_again_by_the_executive(self, cliente, inmuebles):
        tramite = documento_listo(nuevo(cliente, inmuebles))
        tramite = confirmar_borrador(tramite, canal=BACKOFFICE)
        Contrato.objects.filter(pk=tramite.contrato_id).update(
            fecha_inicio=timezone.localdate() - timedelta(days=1),
        )
        with pytest.raises(FechaInicioVencidaError):
            verificar_para_firma(tramite)
        tramite.refresh_from_db()
        assert tramite.detalle_pendiente == NUEVA_FECHA

        manana = timezone.localdate() + timedelta(days=1)
        tramite = cambiar_fecha_inicio(tramite, manana, canal=BACKOFFICE)

        assert situacion(tramite) == ("iniciado", None)
        tramite.contrato.refresh_from_db()
        assert tramite.contrato.fecha_inicio == manana
        assert tramite.contrato.servicios.count() == 2  # noqa: PLR2004
        # No sale: the new draft is reviewed again before signing.
        assert situacion(documento_listo(tramite)) == ("pendiente", REVISION_BORRADOR)

    def test_the_client_side_cannot_move_a_backoffice_case(self, cliente, inmuebles):
        sucursal, bodega = inmuebles
        tramite = documento_listo(nuevo(cliente, inmuebles))

        with pytest.raises(TransicionInvalidaError):
            confirmar_borrador(tramite)
        with pytest.raises(TransicionInvalidaError):
            actualizar_domicilio(tramite, datos_bodega(cliente, sucursal, bodega))
        assert situacion(tramite) == ("pendiente", REVISION_BORRADOR)

    def test_a_waiting_case_keeps_its_reason(self, cliente, inmuebles):
        tramite = documento_listo(nuevo(cliente, inmuebles))
        tramite = confirmar_borrador(tramite, canal=BACKOFFICE)
        Contrato.objects.filter(pk=tramite.contrato_id).update(
            fecha_inicio=timezone.localdate() - timedelta(days=1),
        )
        with pytest.raises(FechaInicioVencidaError):
            verificar_para_firma(tramite)

        tramite.refresh_from_db()
        assert situacion(tramite) == ("pendiente", FALTA_INFORMACION)

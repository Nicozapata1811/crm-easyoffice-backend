"""Creating contracts and reading occupancy. Every value here is synthetic."""

from __future__ import annotations

import importlib
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError

from crm_easyoffice.clientes.tests.factories import ClienteFactory
from crm_easyoffice.clientes.tests.factories import RepresentanteLegalFactory
from crm_easyoffice.configuracion.tests.factories import CuentaPagoFactory
from crm_easyoffice.configuracion.tests.factories import MarcaFactory
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.contratos.services import LineaContrato
from crm_easyoffice.contratos.services import ocupantes
from crm_easyoffice.contratos.services import opciones_contrato
from crm_easyoffice.contratos.tests.factories import INICIO
from crm_easyoffice.contratos.tests.factories import domicilio_en
from crm_easyoffice.contratos.tests.factories import marca
from crm_easyoffice.contratos.tests.factories import nuevo_contrato
from crm_easyoffice.contratos.tests.factories import servicio
from crm_easyoffice.contratos.tests.factories import sucursal
from crm_easyoffice.ventas.models import CicloPago
from crm_easyoffice.ventas.models import Servicio

pytestmark = pytest.mark.django_db


def errores(error: pytest.ExceptionInfo[ValidationError]) -> set[str]:
    return set(error.value.message_dict)


class TestCrearContrato:
    def test_contract_records_term_and_expiry(self):
        contrato = nuevo_contrato()

        assert contrato.fecha_vencimiento == date(2027, 10, 1)
        assert contrato.renovacion_automatica is True
        assert contrato.dias_aviso_termino == 30  # noqa: PLR2004
        assert contrato.estado == Contrato.Estado.VIGENTE

    def test_prices_and_descriptions_are_copied_at_contracting_time(self):
        contrato = nuevo_contrato()
        Servicio.objects.filter(codigo="domicilio-tributario").update(
            nombre="Nombre nuevo",
            descripcion="Descripción nueva",
            precio_base=Decimal(99990),
        )

        [linea] = contrato.servicios.all()
        assert linea.nombre == "Domicilio tributario"
        assert linea.descripcion.startswith("*Domicilio. Tributario")
        assert linea.precio == Decimal(59990)
        assert linea.precio_incluye_iva is True
        assert linea.ciclo_pago.codigo == "anual"
        assert linea.inmueble == sucursal("LF")

    def test_services_keep_their_order_and_have_no_fixed_limit(self):
        lineas = [
            domicilio_en("LF"),
            LineaContrato(servicio=servicio("web-mail-dominio")),
            LineaContrato(servicio=servicio("creacion-empresas")),
            LineaContrato(
                servicio=servicio("firma-electronica-avanzada"),
                ciclo_pago=CicloPago.objects.get(codigo="unico"),
            ),
        ]

        contrato = nuevo_contrato(lineas=lineas)

        assert [linea.servicio.codigo for linea in contrato.servicios.all()] == [
            linea.servicio.codigo for linea in lineas
        ]

    def test_service_without_default_cycle_needs_one(self):
        # Firma electrónica avanzada predates the form and has no default.
        linea = LineaContrato(servicio=servicio("firma-electronica-avanzada"))

        with pytest.raises(ValidationError) as error:
            nuevo_contrato(lineas=[domicilio_en(), linea])

        assert errores(error) == {"servicios"}

    def test_cycle_may_differ_from_the_default(self):
        mensual = CicloPago.objects.get(codigo="mensual")
        linea = LineaContrato(
            servicio=servicio(),
            inmueble=sucursal(),
            ciclo_pago=mensual,
        )

        contrato = nuevo_contrato(lineas=[linea])

        assert contrato.servicios.get().ciclo_pago == mensual

    def test_price_override_rejected_for_fixed_price_service(self):
        linea = LineaContrato(
            servicio=servicio(),
            inmueble=sucursal(),
            precio=Decimal(1),
        )

        with pytest.raises(ValidationError) as error:
            nuevo_contrato(lineas=[linea])

        assert errores(error) == {"servicios"}

    def test_price_required_for_service_without_fixed_price(self):
        Servicio.objects.filter(codigo="contabilidad").update(activo=True)
        mensual = CicloPago.objects.get(codigo="mensual")
        sin_precio = LineaContrato(
            servicio=servicio("contabilidad"),
            ciclo_pago=mensual,
        )

        with pytest.raises(ValidationError):
            nuevo_contrato(lineas=[domicilio_en(), sin_precio])

        acordado = LineaContrato(
            servicio=servicio("contabilidad"),
            ciclo_pago=mensual,
            precio=Decimal(25000),
        )
        contrato = nuevo_contrato(lineas=[domicilio_en(), acordado])
        assert contrato.servicios.get(orden=2).precio == Decimal(25000)

    def test_rejects_inactive_service(self):
        # Contabilidad is seeded inactive until Easy Office gives its price.
        linea = LineaContrato(
            servicio=servicio("contabilidad"),
            ciclo_pago=CicloPago.objects.get(codigo="mensual"),
            precio=Decimal(25000),
        )

        with pytest.raises(ValidationError) as error:
            nuevo_contrato(lineas=[domicilio_en(), linea])

        assert errores(error) == {"servicios"}

    def test_rejects_a_service_twice_and_no_service(self):
        with pytest.raises(ValidationError):
            nuevo_contrato(lineas=[domicilio_en("LF"), domicilio_en("VL")])
        with pytest.raises(ValidationError):
            nuevo_contrato(lineas=[])

    def test_rejects_duration_outside_catalogue(self):
        with pytest.raises(ValidationError) as error:
            nuevo_contrato(duracion_meses=5)

        assert errores(error) == {"duracion_meses"}

    def test_rejects_inactive_brand(self):
        with pytest.raises(ValidationError) as error:
            nuevo_contrato(marca=MarcaFactory.create(activa=False))

        assert errores(error) == {"marca"}

    def test_payment_account_defaults_to_brand_account(self):
        contrato = nuevo_contrato(marca=marca("INOFFICE"))

        assert contrato.cuenta_pago == marca("INOFFICE").cuenta_pago_default

    def test_explicit_payment_account_is_kept(self):
        cuenta = CuentaPagoFactory.create()

        assert nuevo_contrato(cuenta_pago=cuenta).cuenta_pago == cuenta

    def test_inactive_payment_account_is_rejected(self):
        with pytest.raises(ValidationError) as error:
            nuevo_contrato(cuenta_pago=CuentaPagoFactory.create(activa=False))

        assert errores(error) == {"cuenta_pago"}

    def test_representative_must_represent_client_company(self):
        representacion = RepresentanteLegalFactory.create()
        cliente = ClienteFactory.create(persona=None, empresa=representacion.empresa)
        ajena = RepresentanteLegalFactory.create()

        with pytest.raises(ValidationError) as error:
            nuevo_contrato(cliente=cliente, representante=ajena)
        assert errores(error) == {"representante"}

        contrato = nuevo_contrato(cliente=cliente, representante=representacion)
        assert contrato.representante == representacion

    def test_representation_must_cover_the_start_date(self):
        representacion = RepresentanteLegalFactory.create(
            vigente_desde=date(2025, 1, 1),
            vigente_hasta=date(2026, 6, 30),
        )
        cliente = ClienteFactory.create(persona=None, empresa=representacion.empresa)

        with pytest.raises(ValidationError):
            nuevo_contrato(cliente=cliente, representante=representacion)

    def test_natural_person_client_needs_no_representative(self):
        contrato = nuevo_contrato()

        assert contrato.representante is None
        with pytest.raises(ValidationError):
            nuevo_contrato(representante=RepresentanteLegalFactory.create())

    def test_notice_contact_is_validated(self):
        with pytest.raises(ValidationError) as error:
            nuevo_contrato(email_aviso="no es un correo")

        assert "email_aviso" in errores(error)


class TestOcupantes:
    def test_ocupantes_lists_clients_with_active_domicile(self):
        contrato = nuevo_contrato()
        nuevo_contrato(lineas=[domicilio_en("VL")])

        assert ocupantes(sucursal("LF"), date(2026, 12, 1)) == [contrato.cliente]

    def test_not_an_occupant_before_the_start(self):
        nuevo_contrato()

        assert ocupantes(sucursal("LF"), INICIO.replace(day=1)) == []

    def test_ocupantes_excludes_terminated_contracts(self):
        contrato = nuevo_contrato()
        Contrato.objects.filter(pk=contrato.pk).update(
            estado=Contrato.Estado.TERMINADO,
            terminado_en=date(2026, 11, 30),
        )

        assert ocupantes(sucursal("LF"), date(2026, 12, 1)) == []

    def test_auto_renewal_keeps_the_domicile_after_expiry(self):
        renueva = nuevo_contrato()
        nuevo_contrato(renovacion_automatica=False)

        assert ocupantes(sucursal("LF"), date(2028, 1, 1)) == [renueva.cliente]

    def test_a_client_with_two_contracts_appears_once(self):
        contrato = nuevo_contrato()
        nuevo_contrato(cliente=contrato.cliente)

        assert ocupantes(sucursal("LF"), date(2026, 12, 1)) == [contrato.cliente]


def test_opciones_lists_catalogues():
    opciones = opciones_contrato()

    assert [m["nombre"] for m in opciones["marcas"]] == ["EASY OFFICE", "INOFFICE"]
    assert opciones["duraciones"] == [1, 3, 4, 6, 12]
    assert opciones["ciclos_pago"][0]["codigo"] == "unico"
    assert [s["codigo"] for s in opciones["sucursales"]] == ["LF", "SA", "VL"]
    codigos = {s["codigo"] for s in opciones["servicios"]}
    assert "creacion-empresas" in codigos
    assert "contabilidad" not in codigos  # inactive


def test_delete_asignaciondomicilio_aborts_when_rows_exist():
    migracion = importlib.import_module(
        "crm_easyoffice.inmuebles.migrations.0005_delete_asignaciondomicilio",
    )

    def apps_con(*, existe: bool):
        modelo = SimpleNamespace(objects=SimpleNamespace(exists=lambda: existe))
        return SimpleNamespace(get_model=lambda *_: modelo)

    migracion.ensure_no_assignments(apps_con(existe=False), None)
    with pytest.raises(RuntimeError):
        migracion.ensure_no_assignments(apps_con(existe=True), None)

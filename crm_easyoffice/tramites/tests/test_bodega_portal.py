"""The warehouse case (PLT-02) bought in the portal by plan. Synthetic data.

ASSUMPTION: pending validation with Easy Office (TA-15). Every bodega plan
costs the placeholder 59.990 with the signature included.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from crm_easyoffice.clientes.tests.factories import CuentaClienteFactory
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.contratos.services import calcular_vencimiento
from crm_easyoffice.integrations.payment.base import PaymentResult
from crm_easyoffice.integrations.payment.base import PaymentStatus
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.services import FIRMA
from crm_easyoffice.tramites.services import PAGO
from crm_easyoffice.tramites.services import REVISION_BORRADOR
from crm_easyoffice.tramites.services import SOLO_EMPRESAS
from crm_easyoffice.tramites.services import TramiteNoDisponibleError
from crm_easyoffice.tramites.services import completar
from crm_easyoffice.tramites.services import confirmar_borrador
from crm_easyoffice.tramites.services import documento_listo
from crm_easyoffice.tramites.services import formulario_portal
from crm_easyoffice.tramites.services import iniciar_tramite
from crm_easyoffice.tramites.services import situacion
from crm_easyoffice.tramites.services import tipo_tramite
from crm_easyoffice.tramites.tests.factories import TIPO_BODEGA
from crm_easyoffice.tramites.tests.factories import cuenta_empresa
from crm_easyoffice.tramites.tests.factories import datos_bodega
from crm_easyoffice.tramites.tests.factories import preparar_bodega_caso
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.services import aplicar_resultado

pytestmark = pytest.mark.django_db

PORTAL = Tramite.Canal.PORTAL
PLANES = [
    ("anual", 12, "anual"),
    ("semestral", 6, "semestral"),
    ("trimestral", 3, "trimestral"),
]


@pytest.fixture
def inmuebles():
    return preparar_bodega_caso("LF")


@pytest.fixture
def cuenta():
    return cuenta_empresa()


def pedir(cuenta, inmuebles, **extra) -> Tramite:
    sucursal, bodega = inmuebles
    return iniciar_tramite(
        tipo_tramite(TIPO_BODEGA),
        cuenta.cliente,
        datos_bodega(cuenta.cliente, sucursal, bodega, **extra),
        canal=PORTAL,
        usuario=cuenta.user,
    )


def pagar(tramite: Tramite, django_capture_on_commit_callbacks) -> None:
    venta = tramite.venta
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


@pytest.mark.parametrize(("plan", "meses", "ciclo"), PLANES)
def test_a_client_buys_each_plan_end_to_end(  # noqa: PLR0913, PLR0917 - parametrized
    plan,
    meses,
    ciclo,
    cuenta,
    inmuebles,
    django_capture_on_commit_callbacks,
):
    tramite = pedir(cuenta, inmuebles, plan=plan)
    contrato = tramite.contrato
    hoy = timezone.localdate()
    assert (tramite.canal, contrato.duracion_meses) == (PORTAL, meses)
    assert contrato.fecha_vencimiento == calcular_vencimiento(hoy, meses)
    assert contrato.ejecutivo_responsable is None
    assert [(s.precio, s.ciclo_pago.codigo) for s in contrato.servicios.all()] == [
        (Decimal(0), ciclo),
        (Decimal(59990), ciclo),
    ]

    tramite = documento_listo(tramite)
    assert situacion(tramite) == ("pendiente", REVISION_BORRADOR)
    tramite = confirmar_borrador(tramite, cuenta.user)

    assert situacion(tramite) == ("pendiente", PAGO)
    venta = tramite.venta
    assert venta.total == Decimal(59990)
    assert [(i.nombre, i.subtotal) for i in venta.items.all()] == [
        (f"Bodega · Plan {plan}", Decimal(59990)),
    ]

    pagar(tramite, django_capture_on_commit_callbacks)
    tramite.refresh_from_db()
    assert situacion(tramite) == ("pendiente", FIRMA)

    tramite = completar(tramite)
    contrato.refresh_from_db()
    assert contrato.estado == Contrato.Estado.VIGENTE


def test_a_person_client_cannot_buy_it(inmuebles):
    persona = CuentaClienteFactory.create()

    with pytest.raises(TramiteNoDisponibleError) as error:
        iniciar_tramite(tipo_tramite(TIPO_BODEGA), persona.cliente, {}, canal=PORTAL)

    assert error.value.detalle == [
        SOLO_EMPRESAS.format(nombre="Bodega virtual"),
    ]


def test_the_portal_form_offers_plans_and_warehouses(cuenta, inmuebles):
    sucursal, bodega = inmuebles

    formulario = formulario_portal(tipo_tramite(TIPO_BODEGA), cuenta.cliente)

    assert (formulario["nombre"], formulario["disponible"]) == ("Bodega virtual", True)
    assert formulario["motivo_no_disponible"] == ""
    assert [p.codigo for p in formulario["planes"]] == [
        "anual",
        "semestral",
        "trimestral",
    ]
    assert all(p.firma_incluida for p in formulario["planes"])
    assert formulario["inmuebles"] == {"sucursal": [sucursal], "bodega": [bodega]}
    assert "problemas" not in formulario


def test_a_person_client_reads_a_plain_reason(inmuebles):
    formulario = formulario_portal(
        tipo_tramite(TIPO_BODEGA),
        CuentaClienteFactory.create().cliente,
    )

    assert formulario["disponible"] is False
    assert "para empresas" in formulario["motivo_no_disponible"]
    assert formulario["datos"] is None

"""Completing a case leaves its contract in force, with its dates (HU-55). Synthetic.

The domicile has only a portal channel; the warehouse has both. The other tests
check the state after completion, and these add the term that RF-30 and RF-32
need to start following the service.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.contratos.services import calcular_vencimiento
from crm_easyoffice.contratos.services import contratos_vigentes
from crm_easyoffice.integrations.payment.base import PaymentResult
from crm_easyoffice.integrations.payment.base import PaymentStatus
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.tramites.services import FechaInicioVencidaError
from crm_easyoffice.tramites.services import cambiar_fecha_inicio
from crm_easyoffice.tramites.services import completar
from crm_easyoffice.tramites.services import confirmar_borrador
from crm_easyoffice.tramites.services import documento_listo
from crm_easyoffice.tramites.services import iniciar_domicilio
from crm_easyoffice.tramites.services import iniciar_tramite
from crm_easyoffice.tramites.services import situacion
from crm_easyoffice.tramites.services import tipo_tramite
from crm_easyoffice.tramites.services import verificar_para_firma
from crm_easyoffice.tramites.tests.factories import TIPO_BODEGA
from crm_easyoffice.tramites.tests.factories import cliente_empresa
from crm_easyoffice.tramites.tests.factories import cuenta_empresa
from crm_easyoffice.tramites.tests.factories import datos_bodega
from crm_easyoffice.tramites.tests.factories import datos_domicilio
from crm_easyoffice.tramites.tests.factories import preparar_bodega_caso
from crm_easyoffice.tramites.tests.factories import preparar_domicilio
from crm_easyoffice.users.tests.factories import UserFactory
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.services import aplicar_resultado

pytestmark = pytest.mark.django_db

PORTAL = Tramite.Canal.PORTAL
BACKOFFICE = Tramite.Canal.BACKOFFICE


def domicilio_portal(fecha_inicio) -> Tramite:
    sucursal = preparar_domicilio("LF")
    cliente = cuenta_empresa().cliente
    return iniciar_domicilio(
        cliente,
        datos_domicilio(cliente, sucursal, fecha_inicio=fecha_inicio),
    )


def bodega_portal(fecha_inicio) -> Tramite:
    sucursal, bodega = preparar_bodega_caso("LF")
    cuenta = cuenta_empresa()
    return iniciar_tramite(
        tipo_tramite(TIPO_BODEGA),
        cuenta.cliente,
        datos_bodega(cuenta.cliente, sucursal, bodega, fecha_inicio=fecha_inicio),
        canal=PORTAL,
        usuario=cuenta.user,
    )


def bodega_backoffice(fecha_inicio) -> Tramite:
    sucursal, bodega = preparar_bodega_caso("LF")
    cliente = cliente_empresa()
    return iniciar_tramite(
        tipo_tramite(TIPO_BODEGA),
        cliente,
        datos_bodega(cliente, sucursal, bodega, fecha_inicio=fecha_inicio),
        canal=BACKOFFICE,
        usuario=UserFactory.create(),
    )


def hasta_la_firma(tramite: Tramite, capturar) -> Tramite:
    """Take a case from its draft to waiting for the signature."""
    if tramite.canal == BACKOFFICE:
        return confirmar_borrador(documento_listo(tramite), canal=BACKOFFICE)
    tramite = confirmar_borrador(documento_listo(tramite))
    venta = tramite.venta
    orden = OrdenPago.objects.create(
        venta=venta,
        proveedor="simulated",
        monto=venta.total,
    )
    with capturar(execute=True):
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
    tramite.refresh_from_db()
    return tramite


CASOS = [
    pytest.param(domicilio_portal, id="domicilio-portal"),
    pytest.param(bodega_portal, id="bodega-portal"),
    pytest.param(bodega_backoffice, id="bodega-backoffice"),
]


@pytest.mark.parametrize("iniciar", CASOS)
def test_completing_leaves_the_contract_in_force_with_its_term(
    iniciar,
    django_capture_on_commit_callbacks,
):
    hoy = timezone.localdate()
    tramite = hasta_la_firma(iniciar(hoy), django_capture_on_commit_callbacks)
    contrato = tramite.contrato
    assert contrato.estado == Contrato.Estado.BORRADOR
    assert contratos_vigentes(hoy).filter(pk=contrato.pk).exists() is False
    verificar_para_firma(tramite)

    tramite = completar(tramite)

    assert situacion(tramite) == ("completado", None)
    contrato.refresh_from_db()
    assert contrato.estado == Contrato.Estado.VIGENTE
    assert contrato.fecha_inicio == hoy
    assert contrato.duracion_meses == 12  # noqa: PLR2004
    assert contrato.fecha_vencimiento == calcular_vencimiento(hoy, 12)
    assert contratos_vigentes(hoy).filter(pk=contrato.pk).exists() is True


@pytest.mark.parametrize("iniciar", CASOS)
def test_a_future_start_is_in_force_only_from_that_day(
    iniciar,
    django_capture_on_commit_callbacks,
):
    hoy = timezone.localdate()
    inicio = hoy + timedelta(days=10)
    tramite = hasta_la_firma(iniciar(inicio), django_capture_on_commit_callbacks)

    completar(tramite)

    contrato = tramite.contrato
    contrato.refresh_from_db()
    assert contrato.estado == Contrato.Estado.VIGENTE
    assert contrato.fecha_vencimiento == calcular_vencimiento(inicio, 12)
    assert contratos_vigentes(hoy).filter(pk=contrato.pk).exists() is False
    assert contratos_vigentes(inicio).filter(pk=contrato.pk).exists() is True


def test_a_start_date_changed_before_signing_moves_the_expiry():
    hoy = timezone.localdate()
    tramite = bodega_backoffice(hoy)
    tramite = confirmar_borrador(documento_listo(tramite), canal=BACKOFFICE)
    Contrato.objects.filter(pk=tramite.contrato_id).update(
        fecha_inicio=hoy - timedelta(days=1),
    )
    with pytest.raises(FechaInicioVencidaError):
        verificar_para_firma(tramite)
    tramite.refresh_from_db()
    nueva = hoy + timedelta(days=3)

    tramite = cambiar_fecha_inicio(tramite, nueva, canal=BACKOFFICE)
    tramite = confirmar_borrador(documento_listo(tramite), canal=BACKOFFICE)
    completar(tramite)

    contrato = tramite.contrato
    contrato.refresh_from_db()
    assert contrato.estado == Contrato.Estado.VIGENTE
    assert contrato.fecha_inicio == nueva
    assert contrato.fecha_vencimiento == calcular_vencimiento(nueva, 12)

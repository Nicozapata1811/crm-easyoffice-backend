"""Daily expiry detection (HU-53, RF-12, RF-13, RN-09). All data is synthetic."""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from typing import Any

import pytest
from celery import current_app
from django.conf import settings as django_settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction
from django.utils import timezone

from crm_easyoffice.contratos.models import AlertaVencimiento
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.contratos.services import LineaContrato
from crm_easyoffice.contratos.services import calcular_vencimiento
from crm_easyoffice.contratos.services import detectar_vencimientos
from crm_easyoffice.contratos.services import resumen_vencimientos
from crm_easyoffice.contratos.services import umbral_a_alertar
from crm_easyoffice.contratos.tasks import detectar_vencimientos_diarios
from crm_easyoffice.contratos.tests.factories import domicilio_en
from crm_easyoffice.contratos.tests.factories import nuevo_contrato
from crm_easyoffice.contratos.tests.factories import servicio
from crm_easyoffice.users.tests.factories import UserFactory
from crm_easyoffice.ventas.models import Servicio

pytestmark = pytest.mark.django_db

HOY = date(2027, 3, 1)


def dias(n: int) -> date:
    return HOY + timedelta(days=n)


def que_vence(vencimiento: date, *, renueva: bool = False, **datos: Any) -> Contrato:
    """A contract started in October 2026 whose term ends on ``vencimiento``."""
    contrato = nuevo_contrato(renovacion_automatica=renueva, **datos)
    Contrato.objects.filter(pk=contrato.pk).update(fecha_vencimiento=vencimiento)
    contrato.refresh_from_db()
    return contrato


def umbrales(contrato: Contrato) -> list[int]:
    return sorted(
        contrato.alertas.values_list("umbral_dias", flat=True),
        reverse=True,
    )


class TestUmbrales:
    def test_every_seeded_service_starts_with_the_four_thresholds(self):
        assert Servicio.objects.exists()
        assert not Servicio.objects.exclude(
            umbrales_aviso_dias=[60, 30, 15, 7],
        ).exists()

    def test_a_new_service_gets_them_too(self):
        assert Servicio(codigo="nuevo").umbrales_aviso_dias == [60, 30, 15, 7]

    @pytest.mark.parametrize("invalidos", [[30, 30], [0], [-1]])
    def test_a_threshold_list_is_validated(self, invalidos):
        nuevo = servicio()
        nuevo.umbrales_aviso_dias = invalidos

        with pytest.raises(ValidationError) as error:
            nuevo.full_clean()

        assert "umbrales_aviso_dias" in error.value.message_dict


class TestUmbralAAlertar:
    @pytest.mark.parametrize(
        ("restantes", "existentes", "esperado"),
        [
            (61, [], None),
            (60, [], 60),
            (31, [], 60),
            (20, [], 30),
            (20, [60], 30),
            (20, [60, 30], None),
            (6, [30], 7),
            (0, [], 7),
            (10, [15], None),
        ],
    )
    def test_only_the_most_urgent_new_threshold(self, restantes, existentes, esperado):
        assert umbral_a_alertar(restantes, [60, 30, 15, 7], existentes) == esperado

    def test_a_threshold_removed_later_never_brings_a_less_urgent_alert(self):
        assert umbral_a_alertar(10, [60, 30], [15]) is None

    def test_no_threshold_no_alert(self):
        assert umbral_a_alertar(0, [], []) is None


class TestLimites:
    @pytest.mark.parametrize(
        ("restantes", "esperados"),
        [
            (61, []),
            (60, [60]),
            (30, [30]),
            (15, [15]),
            (7, [7]),
            (0, [7]),
            (-1, []),
        ],
    )
    def test_the_last_day_of_the_term_still_counts(self, restantes, esperados):
        contrato = que_vence(dias(restantes))

        detectar_vencimientos(HOY)

        assert umbrales(contrato) == esperados

    def test_rn37_the_term_ends_one_day_before_the_start_date(self):
        contrato = nuevo_contrato(fecha_inicio=date(2026, 10, 2), duracion_meses=12)
        assert contrato.fecha_vencimiento == date(2027, 10, 1)

        detectar_vencimientos(date(2027, 8, 1))
        assert umbrales(contrato) == []

        detectar_vencimientos(date(2027, 8, 2))
        assert umbrales(contrato) == [60]

    def test_rn37_end_of_month(self):
        contrato = nuevo_contrato(fecha_inicio=date(2027, 1, 31), duracion_meses=1)
        assert contrato.fecha_vencimiento == calcular_vencimiento(date(2027, 1, 31), 1)
        assert contrato.fecha_vencimiento == date(2027, 2, 28)

        detectar_vencimientos(date(2027, 1, 31))
        assert umbrales(contrato) == [30]

        detectar_vencimientos(date(2027, 2, 13))
        assert umbrales(contrato) == [30, 15]

        detectar_vencimientos(date(2027, 2, 21))
        assert umbrales(contrato) == [30, 15, 7]

        assert detectar_vencimientos(date(2027, 2, 28)) == 0
        assert detectar_vencimientos(date(2027, 3, 1)) == 0

    def test_day_by_day_it_alerts_once_per_threshold(self):
        contrato = que_vence(dias(70))

        for dia in range(75):
            detectar_vencimientos(dias(dia))

        assert umbrales(contrato) == [60, 30, 15, 7]


class TestDeteccion:
    def test_running_twice_the_same_day_creates_nothing_new(self):
        contrato = que_vence(dias(10))

        assert detectar_vencimientos(HOY) == 1
        assert detectar_vencimientos(HOY) == 0

        assert umbrales(contrato) == [15]

    def test_a_contract_first_seen_late_gets_only_the_most_urgent(self):
        contrato = que_vence(dias(20))

        detectar_vencimientos(HOY)
        assert umbrales(contrato) == [30]

        detectar_vencimientos(dias(5))
        assert umbrales(contrato) == [30, 15]

    def test_a_task_down_for_days_does_not_fill_the_gap(self):
        contrato = que_vence(dias(25))
        detectar_vencimientos(HOY)

        detectar_vencimientos(dias(19))

        assert umbrales(contrato) == [30, 7]

    def test_a_handled_alert_is_not_created_again(self):
        contrato = que_vence(dias(10))
        detectar_vencimientos(HOY)
        AlertaVencimiento.objects.update(
            estado=AlertaVencimiento.Estado.GESTIONADA,
            gestionada_por=UserFactory.create(),
            gestionada_en=timezone.now(),
        )

        assert detectar_vencimientos(dias(1)) == 0
        assert umbrales(contrato) == [15]

    def test_it_records_the_expiry_it_refers_to(self):
        contrato = que_vence(dias(10))

        detectar_vencimientos(HOY)

        alerta = contrato.alertas.get()
        assert alerta.fecha_vencimiento == contrato.fecha_vencimiento
        assert alerta.estado == AlertaVencimiento.Estado.PENDIENTE

    def test_a_new_expiry_can_alert_the_same_threshold_again(self):
        contrato = que_vence(dias(10))
        detectar_vencimientos(HOY)
        Contrato.objects.filter(pk=contrato.pk).update(fecha_vencimiento=dias(400))

        detectar_vencimientos(dias(395))

        assert umbrales(contrato) == [15, 7]

    def test_one_alert_per_contract_not_per_line(self):
        contrato = nuevo_contrato(
            lineas=[
                domicilio_en("LF"),
                LineaContrato(servicio=servicio("web-mail-dominio")),
            ],
        )
        Contrato.objects.filter(pk=contrato.pk).update(fecha_vencimiento=dias(10))

        assert detectar_vencimientos(HOY) == 1

    def test_a_contract_uses_the_union_of_its_services_thresholds(self):
        Servicio.objects.filter(codigo="domicilio-tributario").update(
            umbrales_aviso_dias=[20],
        )
        Servicio.objects.filter(codigo="web-mail-dominio").update(
            umbrales_aviso_dias=[45],
        )
        contrato = nuevo_contrato(
            lineas=[
                domicilio_en("LF"),
                LineaContrato(servicio=servicio("web-mail-dominio")),
            ],
        )
        Contrato.objects.filter(pk=contrato.pk).update(fecha_vencimiento=dias(40))

        detectar_vencimientos(HOY)
        assert umbrales(contrato) == [45]

        detectar_vencimientos(dias(25))
        assert umbrales(contrato) == [45, 20]

    def test_a_service_without_thresholds_does_not_alert(self):
        Servicio.objects.filter(codigo="domicilio-tributario").update(
            umbrales_aviso_dias=[],
        )
        contrato = que_vence(dias(5))

        detectar_vencimientos(HOY)

        assert umbrales(contrato) == []


class TestLosQueNuncaAlertan:
    @pytest.mark.parametrize(
        "estado",
        [Contrato.Estado.BORRADOR, Contrato.Estado.ANULADO, Contrato.Estado.TERMINADO],
    )
    def test_drafts_annulled_and_terminated(self, estado):
        contrato = que_vence(dias(5))
        Contrato.objects.filter(pk=contrato.pk).update(estado=estado)

        assert detectar_vencimientos(HOY) == 0

    def test_a_term_ended_early(self):
        contrato = que_vence(dias(5))
        Contrato.objects.filter(pk=contrato.pk).update(terminado_en=dias(-1))

        assert detectar_vencimientos(HOY) == 0

    @pytest.mark.parametrize("renueva", [True, False])
    def test_past_its_expiry(self, renueva):
        que_vence(dias(-1), renueva=renueva)

        assert detectar_vencimientos(HOY) == 0

    def test_not_started_yet(self):
        nuevo_contrato(fecha_inicio=dias(1), duracion_meses=1)

        assert detectar_vencimientos(HOY) == 0

    def test_renewed(self):
        anterior = que_vence(dias(5))
        renovacion = que_vence(dias(400))
        Contrato.objects.filter(pk=renovacion.pk).update(contrato_anterior=anterior)

        detectar_vencimientos(HOY)

        assert umbrales(anterior) == []

    def test_an_annulled_renewal_does_not_stop_it(self):
        anterior = que_vence(dias(5))
        renovacion = que_vence(dias(400))
        Contrato.objects.filter(pk=renovacion.pk).update(
            contrato_anterior=anterior,
            estado=Contrato.Estado.ANULADO,
        )

        detectar_vencimientos(HOY)

        assert umbrales(anterior) == [7]


class TestRenovacionAutomatica:
    def test_it_alerts_too(self):
        contrato = que_vence(dias(10), renueva=True)

        detectar_vencimientos(HOY)

        assert umbrales(contrato) == [15]

    def test_the_dashboard_counts_exactly_what_alerts(self):
        que_vence(dias(0))
        que_vence(dias(10), renueva=True)
        que_vence(dias(60), renueva=True)
        que_vence(dias(61))
        que_vence(dias(-1), renueva=True)
        que_vence(dias(-1))
        anulado = que_vence(dias(5))
        Contrato.objects.filter(pk=anulado.pk).update(estado=Contrato.Estado.ANULADO)
        renovado = que_vence(dias(5))
        Contrato.objects.filter(pk=que_vence(dias(400)).pk).update(
            contrato_anterior=renovado,
        )

        por_vencer = resumen_vencimientos(HOY, 60)["por_vencer"]

        assert por_vencer == 3  # noqa: PLR2004
        assert detectar_vencimientos(HOY) == por_vencer


class TestRestricciones:
    def test_one_alert_per_contract_expiry_and_threshold(self):
        contrato = que_vence(dias(10))
        datos = {
            "contrato": contrato,
            "umbral_dias": 15,
            "fecha_vencimiento": contrato.fecha_vencimiento,
        }
        AlertaVencimiento.objects.create(**datos)

        with pytest.raises(IntegrityError), transaction.atomic():
            AlertaVencimiento.objects.create(**datos)

    def test_a_handled_alert_says_who_and_when(self):
        contrato = que_vence(dias(10))

        with pytest.raises(IntegrityError), transaction.atomic():
            AlertaVencimiento.objects.create(
                contrato=contrato,
                umbral_dias=15,
                fecha_vencimiento=contrato.fecha_vencimiento,
                estado=AlertaVencimiento.Estado.GESTIONADA,
            )


class TestTarea:
    def test_it_runs_detection_for_today(self):
        contrato = nuevo_contrato()
        Contrato.objects.filter(pk=contrato.pk).update(
            fecha_inicio=timezone.localdate() - timedelta(days=30),
            fecha_vencimiento=timezone.localdate() + timedelta(days=5),
        )

        assert detectar_vencimientos_diarios() == 1
        assert detectar_vencimientos_diarios() == 0
        assert umbrales(contrato) == [7]

    def test_beat_runs_it_every_day_at_eight_chile_time(self):
        entrada = django_settings.CELERY_BEAT_SCHEDULE[
            "detectar-vencimientos-contratos"
        ]

        assert entrada["task"] == detectar_vencimientos_diarios.name
        assert entrada["task"] in current_app.tasks
        assert entrada["schedule"].hour == {8}
        assert entrada["schedule"].minute == {0}
        assert django_settings.CELERY_TIMEZONE == "America/Santiago"

"""Contract expiry (RN-37): start plus duration minus one day."""

from __future__ import annotations

from datetime import date

import pytest

from crm_easyoffice.contratos.services import calcular_vencimiento


def test_expiry_is_start_plus_duration_minus_one_day():
    # The example in RN-37.
    assert calcular_vencimiento(date(2026, 10, 2), 12) == date(2027, 10, 1)


@pytest.mark.parametrize(
    ("inicio", "meses", "vencimiento"),
    [
        (date(2026, 1, 1), 1, date(2026, 1, 31)),
        (date(2026, 3, 1), 12, date(2027, 2, 28)),
        (date(2026, 11, 15), 3, date(2027, 2, 14)),
        (date(2026, 6, 30), 4, date(2026, 10, 29)),
        (date(2026, 8, 10), 6, date(2027, 2, 9)),
    ],
)
def test_expiry_for_each_offered_duration(inicio, meses, vencimiento):
    assert calcular_vencimiento(inicio, meses) == vencimiento


def test_expiry_for_month_end_start():
    # 31 January plus one month: February has no 31st, so the term runs to
    # its last day instead of falling short.
    assert calcular_vencimiento(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_expiry_in_leap_year():
    assert calcular_vencimiento(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert calcular_vencimiento(date(2028, 2, 29), 12) == date(2029, 2, 28)

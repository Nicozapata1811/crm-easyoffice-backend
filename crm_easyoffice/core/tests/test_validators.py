"""Tests for the shared domain validators.

Every RUT here is synthetic. No real identifier belongs in this repository.
"""

import pytest
from django.core.exceptions import ValidationError

from crm_easyoffice.core.validators import compute_rut_check_digit
from crm_easyoffice.core.validators import validate_rut


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("11111111", "1"),
        ("11111112", "K"),
        ("11111117", "0"),
        ("12345678", "5"),
    ],
)
def test_compute_rut_check_digit(number: str, expected: str) -> None:
    assert compute_rut_check_digit(number) == expected


@pytest.mark.parametrize(
    "rut",
    ["11111111-1", "11111112-K", "11111112-k", "11111117-0", "12345678-5"],
)
def test_validate_rut_accepts_valid(rut: str) -> None:
    validate_rut(rut)


@pytest.mark.parametrize(
    ("rut", "code"),
    [
        ("11111111-2", "invalid_rut_check_digit"),
        ("12345678-K", "invalid_rut_check_digit"),
        ("11.111.111-1", "invalid_rut_format"),
        ("111111111", "invalid_rut_format"),
        ("11111111-X", "invalid_rut_format"),
        ("", "invalid_rut_format"),
    ],
)
def test_validate_rut_rejects_invalid(rut: str, code: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        validate_rut(rut)
    assert excinfo.value.code == code

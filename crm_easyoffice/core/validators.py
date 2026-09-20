"""Validators shared across the domain."""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

RUT_PATTERN = re.compile(r"^(\d{7,8})-([\dkK])$")

MODULUS = 11
MIN_FACTOR = 2
MAX_FACTOR = 7


def compute_rut_check_digit(number: str) -> str:
    """Return the check digit for the numeric part of a RUT.

    Uses the modulo 11 algorithm with factors cycling from 2 to 7.

    Args:
        number: Numeric part of the RUT, without dots or check digit.

    Returns:
        The check digit as a single character: "0"-"9" or "K".
    """
    total = 0
    factor = MIN_FACTOR
    for digit in reversed(number):
        total += int(digit) * factor
        factor = MIN_FACTOR if factor == MAX_FACTOR else factor + 1

    remainder = MODULUS - (total % MODULUS)
    if remainder == MODULUS:
        return "0"
    if remainder == MODULUS - 1:
        return "K"
    return str(remainder)


def validate_rut(value: str) -> None:
    """Validate a Chilean RUT and its check digit.

    Expects the normalised storage form: no dots, a hyphen before the check
    digit, for example ``12345678-5``.

    Args:
        value: The RUT to validate.

    Raises:
        ValidationError: If the format or the check digit is invalid.
    """
    match = RUT_PATTERN.match(value or "")
    if not match:
        raise ValidationError(
            _("Enter a RUT without dots and with a hyphen, for example 12345678-5."),
            code="invalid_rut_format",
        )

    number, check_digit = match.groups()
    if check_digit.upper() != compute_rut_check_digit(number):
        raise ValidationError(
            _("The RUT check digit is incorrect."),
            code="invalid_rut_check_digit",
        )

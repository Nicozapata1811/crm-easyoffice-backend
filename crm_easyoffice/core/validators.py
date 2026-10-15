"""Validators shared across the domain."""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

MAX_UPLOAD_BYTES = 5 * 1024 * 1024

# Leading bytes of each accepted document format.
FILE_SIGNATURES = {
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "pdf": (b"%PDF-",),
}

RUT_PATTERN = re.compile(r"^(\d{7,8})-([\dkK])$")
RUT_SEPARATORS = re.compile(r"[.\s]")

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


def normalize_rut(value: str) -> str:
    """Return a RUT in storage form: no dots or spaces, upper-case K.

    Args:
        value: A RUT as typed, for example ``12.345.678-k``.

    Returns:
        The normalised RUT. It is not validated.
    """
    return RUT_SEPARATORS.sub("", value).upper()


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


def validate_max_file_size(file) -> None:
    """Reject uploads larger than ``MAX_UPLOAD_BYTES``.

    ASSUMPTION: pending validation with Easy Office. 5 MB is ample for a
    scanned identity card; no limit has been agreed.
    """
    if file.size > MAX_UPLOAD_BYTES:
        raise ValidationError(
            _("The file is larger than %(limit)s MB."),
            code="file_too_large",
            params={"limit": MAX_UPLOAD_BYTES // (1024 * 1024)},
        )


def validate_file_signature(file) -> None:
    """Check that the content matches the extension, not just the file name.

    A renamed executable or script with a ``.jpg`` name is rejected. Only the
    formats in ``FILE_SIGNATURES`` are known; pair this validator with a
    ``FileExtensionValidator`` restricted to them.
    """
    extension = file.name.rsplit(".", 1)[-1].lower() if "." in file.name else ""
    signatures = FILE_SIGNATURES.get(extension, ())
    position = file.tell() if hasattr(file, "tell") else 0
    file.seek(0)
    head = file.read(16)
    file.seek(position)
    if not any(head.startswith(signature) for signature in signatures):
        raise ValidationError(
            _("The file content does not match its format."),
            code="file_signature_mismatch",
        )

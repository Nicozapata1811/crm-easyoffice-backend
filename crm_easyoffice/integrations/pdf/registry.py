"""The Word-to-PDF converter in use (``PDF_CONVERTER``)."""

from __future__ import annotations

from django.conf import settings

from .base import PdfConverter
from .base import PdfError
from .gotenberg import GotenbergPdfConverter
from .simulated import SimulatedPdfConverter

GOTENBERG = "gotenberg"
SIMULATED = "simulated"


def get_pdf_converter() -> PdfConverter:
    if settings.PDF_CONVERTER == GOTENBERG:
        return GotenbergPdfConverter(
            settings.GOTENBERG_URL,
            timeout=settings.PDF_CONVERSION_TIMEOUT_SECONDS,
        )
    if settings.PDF_CONVERTER == SIMULATED:
        return SimulatedPdfConverter()
    msg = f"Unknown PDF converter: {settings.PDF_CONVERTER!r}"
    raise PdfError(msg)

"""Gotenberg adapter: LibreOffice behind an HTTP API, in its own container.

https://gotenberg.dev/docs/routes#convert-with-libreoffice

ASSUMPTION: pending validation with Easy Office. LibreOffice replaces Times
New Roman with the metric-compatible Liberation Serif, so line breaks match
Word's but glyphs differ slightly; whether that is acceptable is open.
"""

from __future__ import annotations

import httpx

from .base import PDF_MAGIC
from .base import PdfConverter
from .base import PdfError

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class GotenbergPdfConverter(PdfConverter):
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 60,
        client: httpx.Client | None = None,
    ) -> None:
        if not base_url:
            msg = "GOTENBERG_URL is not configured."
            raise PdfError(msg)
        self.client = client or httpx.Client(base_url=base_url, timeout=timeout)

    def docx_a_pdf(self, docx: bytes, *, nombre: str = "documento.docx") -> bytes:
        try:
            respuesta = self.client.post(
                "/forms/libreoffice/convert",
                files={"files": (nombre, docx, DOCX)},
            )
        except httpx.HTTPError as exc:
            msg = f"Gotenberg is unreachable: {exc}"
            raise PdfError(msg) from exc
        if respuesta.status_code != httpx.codes.OK:
            msg = f"Gotenberg answered {respuesta.status_code}: {respuesta.text[:200]}"
            raise PdfError(msg)
        if not respuesta.content.startswith(PDF_MAGIC):
            msg = "Gotenberg did not return a PDF."
            raise PdfError(msg)
        return respuesta.content

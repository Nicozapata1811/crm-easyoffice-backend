"""PDF converter tests. No request leaves the process."""

from __future__ import annotations

import httpx
import pytest

from crm_easyoffice.integrations.pdf.base import PDF_MAGIC
from crm_easyoffice.integrations.pdf.base import PdfError
from crm_easyoffice.integrations.pdf.gotenberg import GotenbergPdfConverter
from crm_easyoffice.integrations.pdf.registry import get_pdf_converter
from crm_easyoffice.integrations.pdf.simulated import SimulatedPdfConverter

BASE_URL = "http://gotenberg.invalid"
PDF = b"%PDF-1.7\nsynthetic\n%%EOF"


def converter_answering(handler) -> tuple[GotenbergPdfConverter, list[httpx.Request]]:
    enviados: list[httpx.Request] = []

    def registrar(request: httpx.Request) -> httpx.Response:
        enviados.append(request)
        return handler(request)

    client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(registrar))
    return GotenbergPdfConverter(BASE_URL, client=client), enviados


def test_posts_the_docx_to_the_libreoffice_route():
    converter, enviados = converter_answering(
        lambda _: httpx.Response(200, content=PDF),
    )

    assert converter.docx_a_pdf(b"docx-bytes", nombre="contrato.docx") == PDF
    (request,) = enviados
    assert request.url.path == "/forms/libreoffice/convert"
    cuerpo = request.read()
    assert b'filename="contrato.docx"' in cuerpo
    assert b"docx-bytes" in cuerpo


def test_an_error_status_raises():
    converter, _ = converter_answering(lambda _: httpx.Response(503, text="busy"))

    with pytest.raises(PdfError, match="503"):
        converter.docx_a_pdf(b"docx")


def test_a_non_pdf_answer_raises():
    converter, _ = converter_answering(lambda _: httpx.Response(200, content=b"<html>"))

    with pytest.raises(PdfError, match="did not return a PDF"):
        converter.docx_a_pdf(b"docx")


def test_an_unreachable_service_raises():
    def caido(request: httpx.Request) -> httpx.Response:
        msg = "refused"
        raise httpx.ConnectError(msg, request=request)

    converter, _ = converter_answering(caido)

    with pytest.raises(PdfError, match="unreachable"):
        converter.docx_a_pdf(b"docx")


def test_requires_a_url():
    with pytest.raises(PdfError, match="GOTENBERG_URL"):
        GotenbergPdfConverter("")


def test_simulated_returns_a_distinct_pdf_per_document():
    converter = SimulatedPdfConverter()

    uno, otro = converter.docx_a_pdf(b"uno"), converter.docx_a_pdf(b"otro")

    assert uno.startswith(PDF_MAGIC)
    assert uno != otro


def test_tests_use_the_simulated_converter():
    assert isinstance(get_pdf_converter(), SimulatedPdfConverter)

"""A simulated converter for tests: a valid one-page PDF, whatever the input.

It does not render the document. Tests check the Word file, which carries the
content; the PDF only has to be a PDF.
"""

from __future__ import annotations

import hashlib

from .base import PdfConverter


def _pdf_vacio(marca: str) -> bytes:
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
    ]
    cuerpo = b"%PDF-1.4\n"
    offsets = []
    for numero, objeto in enumerate(objetos, start=1):
        offsets.append(len(cuerpo))
        cuerpo += f"{numero} 0 obj\n".encode() + objeto + b"\nendobj\n"
    xref = len(cuerpo)
    cuerpo += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    cuerpo += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    cuerpo += (
        f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n% {marca}\n"
    ).encode()
    return cuerpo


class SimulatedPdfConverter(PdfConverter):
    def docx_a_pdf(self, docx: bytes, *, nombre: str = "documento.docx") -> bytes:
        # The input's hash makes each PDF depend on its document, so two
        # versions never share a file hash.
        return _pdf_vacio(hashlib.sha256(docx).hexdigest())

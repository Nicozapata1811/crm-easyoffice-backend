"""The Word-to-PDF conversion contract.

Generated contracts are Word files; the client previews them and the signer
signs them as PDF. The conversion runs in Celery, never in a request.
"""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod

PDF_MAGIC = b"%PDF-"


class PdfError(Exception):
    """The document could not be converted."""


class PdfConverter(ABC):
    @abstractmethod
    def docx_a_pdf(self, docx: bytes, *, nombre: str = "documento.docx") -> bytes:
        """Convert a .docx file to PDF.

        Raises:
            PdfError: The converter is unreachable or rejected the file.
        """

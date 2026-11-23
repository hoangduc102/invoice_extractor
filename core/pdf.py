"""
Render PDF pages to PIL images with pypdfium2.

pypdfium2 ships Google's PDFium inside the wheel, so `pip install` is all it takes:
no Poppler, no system packages, no PATH setup (Windows, macOS, Linux and Docker alike).
"""

from __future__ import annotations

from collections.abc import Iterator

import pypdfium2 as pdfium
from PIL import Image

DEFAULT_DPI = 200  # balances legibility for vision models against image (token) size
_PDF_POINTS_PER_INCH = 72


class InvalidDocumentError(ValueError):
    """The bytes are not a readable PDF (corrupt, truncated, encrypted, or not a PDF)."""


def _open(data: bytes) -> pdfium.PdfDocument:
    try:
        return pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise InvalidDocumentError(f"Could not open PDF: {exc}") from exc


def page_count(data: bytes) -> int:
    doc = _open(data)
    try:
        return len(doc)
    finally:
        doc.close()


def iter_pdf_pages(
    data: bytes, dpi: int = DEFAULT_DPI, first: int = 1, last: int | None = None
) -> Iterator[Image.Image]:
    """Yield pages `first..last` (1-based, inclusive) as RGB images."""
    doc = _open(data)
    try:
        if len(doc) == 0:
            raise InvalidDocumentError("PDF has no pages")
        stop = len(doc) if last is None else min(last, len(doc))
        for index in range(first - 1, stop):
            page = doc[index]
            try:
                yield page.render(scale=dpi / _PDF_POINTS_PER_INCH).to_pil().convert("RGB")
            finally:
                page.close()
    finally:
        doc.close()


def render_pdf_pages(data: bytes, dpi: int = DEFAULT_DPI, max_pages: int | None = None) -> list[Image.Image]:
    return list(iter_pdf_pages(data, dpi=dpi, last=max_pages))


def render_first_page(data: bytes, dpi: int = DEFAULT_DPI) -> Image.Image:
    return render_pdf_pages(data, dpi=dpi, max_pages=1)[0]  # list() runs the generator to the end: doc closed

"""PDF rendering with pypdfium2 (core/pdf.py), on the real sample documents."""

from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from core.invoice_pipeline import file_bytes_to_base64_png
from core.pdf import InvalidDocumentError, page_count, render_first_page, render_pdf_pages

DOCS = Path(__file__).resolve().parent.parent / "example_docs"


def read(name: str) -> bytes:
    return (DOCS / name).read_bytes()


@pytest.mark.parametrize(
    "name, pages",
    [("invoice-1-3.pdf", 2), ("invoice-7-0.pdf", 3), ("wordpress-pdf-invoice-plugin-sample.pdf", 1)],
)
def test_page_count(name, pages):
    assert page_count(read(name)) == pages


def test_first_page_size_follows_dpi():
    data = read("invoice-1-3.pdf")  # US Letter: 8.5 x 11 in
    assert render_first_page(data, dpi=200).size == (1700, 2200)
    assert render_first_page(data, dpi=100).size == (850, 1100)
    assert render_first_page(data).mode == "RGB"


def test_render_all_pages_and_limit():
    data = read("invoice-7-0.pdf")
    assert len(render_pdf_pages(data, dpi=50)) == 3
    assert len(render_pdf_pages(data, dpi=50, max_pages=2)) == 2


def test_first_page_is_not_blank():
    image = render_first_page(read("wordpress-pdf-invoice-plugin-sample.pdf"), dpi=50).convert("L")
    low, high = image.getextrema()
    assert low < 100 < high  # dark text on a light page


@pytest.mark.parametrize("data", [b"", b"not a pdf", b"%PDF-1.4 truncated"])
def test_invalid_pdf_raises(data):
    with pytest.raises(InvalidDocumentError):
        render_first_page(data)
    assert issubclass(InvalidDocumentError, ValueError)


def test_pipeline_turns_pdf_into_png():
    encoded = file_bytes_to_base64_png(read("invoice-3-0.pdf"), "application/pdf")
    image = Image.open(io.BytesIO(base64.b64decode(encoded)))
    assert image.format == "PNG"
    assert image.size == (1700, 2200)

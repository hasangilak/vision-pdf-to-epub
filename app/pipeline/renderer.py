"""PDF page renderer using PyMuPDF."""

from __future__ import annotations

import asyncio
import io
from collections.abc import AsyncIterator
from pathlib import Path

import fitz
from PIL import Image

from app.config import settings


async def render_pages(
    pdf_path: Path,
    dpi: int = settings.render_dpi,
    jpeg_quality: int = settings.jpeg_quality,
    max_image_dimension: int = settings.max_image_dimension,
) -> AsyncIterator[tuple[int, bytes]]:
    """Yield (page_number, jpeg_bytes) for each page in the PDF.

    Page numbers are 0-based. Rendering runs in a thread to avoid blocking
    the event loop.
    """
    loop = asyncio.get_running_loop()

    doc = await loop.run_in_executor(None, fitz.open, str(pdf_path))
    try:
        total = doc.page_count
        for page_num in range(total):
            jpeg_bytes = await loop.run_in_executor(
                None, _render_page, doc, page_num, dpi, jpeg_quality, max_image_dimension
            )
            yield page_num, jpeg_bytes
    finally:
        doc.close()


def get_page_count(pdf_path: Path) -> int:
    """Return the number of pages in a PDF."""
    doc = fitz.open(str(pdf_path))
    count = doc.page_count
    doc.close()
    return count


def _render_page(
    doc: fitz.Document, page_num: int, dpi: int, quality: int, max_dim: int
) -> bytes:
    """Render a single page to JPEG bytes (runs in thread pool)."""
    page = doc.load_page(page_num)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)

    if max_dim > 0 and (pix.width > max_dim or pix.height > max_dim):
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()

    return pix.tobytes(output="jpeg", jpg_quality=quality)

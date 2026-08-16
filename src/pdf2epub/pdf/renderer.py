from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

import pymupdf

from pdf2epub.domain.errors import PageRenderError
from pdf2epub.domain.models import BBox

RENDERER_VERSION = "pymupdf-raster-v1"


class PdfRenderer:
    def render_page(
        self,
        source_path: Path,
        source_sha256: str,
        page_index: int,
        cache_directory: Path,
        *,
        dpi: int = 120,
        max_pixels: int = 40_000_000,
    ) -> Path:
        cache_key = hashlib.sha256(
            f"{source_sha256}:{page_index}:{dpi}:{max_pixels}:{RENDERER_VERSION}".encode()
        ).hexdigest()[:24]
        output = cache_directory / f"page-{page_index:06d}-{cache_key}.png"
        if output.is_file():
            return output
        try:
            with pymupdf.open(source_path) as document:
                page = document.load_page(page_index)
                scale = dpi / 72
                estimated_pixels = int(page.rect.width * scale * page.rect.height * scale)
                if estimated_pixels > max_pixels:
                    raise PageRenderError("Page preview exceeds the configured pixel limit")
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                data = pixmap.tobytes("png")
            cache_directory.mkdir(parents=True, exist_ok=True)
            temporary: Path | None = None
            with tempfile.NamedTemporaryFile(dir=cache_directory, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, output)
            return output
        except PageRenderError:
            raise
        except Exception as exc:
            raise PageRenderError(
                f"Could not render page {page_index + 1}: {type(exc).__name__}"
            ) from exc

    def render_region(
        self,
        source_path: Path,
        source_sha256: str,
        page_index: int,
        region: BBox,
        cache_directory: Path,
        *,
        dpi: int = 200,
        max_pixels: int = 25_000_000,
    ) -> Path:
        quantized = ",".join(f"{value:.2f}" for value in region.as_tuple())
        cache_key = hashlib.sha256(
            f"{source_sha256}:{page_index}:{quantized}:{dpi}:{max_pixels}:"
            f"{RENDERER_VERSION}:region-v1".encode()
        ).hexdigest()[:24]
        output = cache_directory / f"region-{page_index:06d}-{cache_key}.png"
        if output.is_file():
            return output
        try:
            with pymupdf.open(source_path) as document:
                page = document.load_page(page_index)
                clip = pymupdf.Rect(*region.as_tuple()) & page.rect
                if clip.is_empty or clip.width <= 0 or clip.height <= 0:
                    raise PageRenderError("Selected OCR region is outside the page")
                scale = dpi / 72
                estimated_pixels = int(clip.width * scale * clip.height * scale)
                if estimated_pixels > max_pixels:
                    raise PageRenderError("Selected OCR region exceeds the pixel limit")
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(scale, scale), clip=clip, alpha=False
                )
                data = pixmap.tobytes("png")
            cache_directory.mkdir(parents=True, exist_ok=True)
            temporary: Path | None = None
            with tempfile.NamedTemporaryFile(dir=cache_directory, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, output)
            return output
        except PageRenderError:
            raise
        except Exception as exc:
            raise PageRenderError(
                f"Could not render page region {page_index + 1}: {type(exc).__name__}"
            ) from exc

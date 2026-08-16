from __future__ import annotations

import math
import unicodedata
from pathlib import Path
from typing import Literal

import pymupdf
from pydantic import BaseModel, ConfigDict, Field

from pdf2epub.domain.errors import SourceOpenError
from pdf2epub.domain.models import NativeTextQuality

MAX_PAGES = 5_000
MAX_PAGE_DIMENSION_POINTS = 20_000


class PageInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    page_index: int
    width: float
    height: float
    rotation: int
    quality: NativeTextQuality


class PdfInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    page_count: int = Field(ge=0)
    title: str | None = None
    pages: list[PageInspection]


def native_text_quality(text: str, image_area: float, page_area: float) -> NativeTextQuality:
    characters = [character for character in text if not character.isspace()]
    count = len(characters)
    replacement_ratio = text.count("\ufffd") / max(count, 1)
    controls = sum(
        1
        for character in characters
        if unicodedata.category(character) == "Cc" and character not in "\n\r\t"
    )
    control_ratio = controls / max(count, 1)
    image_ratio = min(max(image_area / max(page_area, 1), 0), 1)
    reasons: list[str] = []
    if count == 0:
        status: Literal["usable", "suspect", "no_text"] = "no_text"
        reasons.append("No native text objects were extracted")
    elif count < 20 or replacement_ratio > 0.02 or control_ratio > 0.02:
        status = "suspect"
        if count < 20:
            reasons.append("Very little native text was extracted")
        if replacement_ratio > 0.02:
            reasons.append("Replacement-character ratio is high")
        if control_ratio > 0.02:
            reasons.append("Control-character ratio is high")
    else:
        status = "usable"
    if image_ratio > 0.85:
        reasons.append("Images cover most of the page")
        if status == "usable":
            status = "suspect"
    return NativeTextQuality(
        status=status,
        character_count=count,
        replacement_character_ratio=replacement_ratio,
        control_character_ratio=control_ratio,
        image_coverage_ratio=image_ratio,
        reasons=reasons,
    )


class PdfAnalyzer:
    def inspect_document(self, path: Path) -> PdfInspection:
        try:
            with pymupdf.open(path) as document:
                if document.needs_pass:
                    raise SourceOpenError("Password-protected PDFs are not supported in M1")
                if document.page_count > MAX_PAGES:
                    raise SourceOpenError(f"PDF exceeds the M1 limit of {MAX_PAGES} pages")
                pages = [self._inspect_page(page, index) for index, page in enumerate(document)]
                title = document.metadata.get("title") or None
        except SourceOpenError:
            raise
        except Exception as exc:
            raise SourceOpenError(f"Could not inspect PDF: {type(exc).__name__}") from exc
        return PdfInspection(page_count=len(pages), title=title, pages=pages)

    @staticmethod
    def _inspect_page(page: pymupdf.Page, page_index: int) -> PageInspection:
        payload = page.get_text("dict", sort=False)
        text = "".join(
            str(span.get("text", ""))
            for block in payload.get("blocks", [])
            if block.get("type") == 0
            for line in block.get("lines", [])
            for span in line.get("spans", [])
        )
        image_area = sum(
            max(0.0, float(block["bbox"][2]) - float(block["bbox"][0]))
            * max(0.0, float(block["bbox"][3]) - float(block["bbox"][1]))
            for block in payload.get("blocks", [])
            if block.get("type") == 1 and block.get("bbox")
        )
        rect = page.rect
        if (
            not math.isfinite(rect.width)
            or not math.isfinite(rect.height)
            or rect.width <= 0
            or rect.height <= 0
            or rect.width > MAX_PAGE_DIMENSION_POINTS
            or rect.height > MAX_PAGE_DIMENSION_POINTS
        ):
            raise SourceOpenError("PDF page dimensions exceed the M1 safety limits")
        return PageInspection(
            page_index=page_index,
            width=rect.width,
            height=rect.height,
            rotation=page.rotation,
            quality=native_text_quality(text, image_area, rect.width * rect.height),
        )

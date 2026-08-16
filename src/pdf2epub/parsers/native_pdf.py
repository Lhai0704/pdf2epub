from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import pymupdf

from pdf2epub.domain.errors import NativeTextExtractionError
from pdf2epub.domain.identifiers import stable_asset_id, stable_span_id
from pdf2epub.domain.models import (
    Asset,
    BBox,
    Block,
    ImageBlock,
    Page,
    ProcessingProvenance,
    TextStyle,
)
from pdf2epub.parsers.base import PageContext, PageParseResult, ParseOptions
from pdf2epub.pdf.analyzer import native_text_quality
from pdf2epub.pdf.classifier import classify_page
from pdf2epub.persistence.project_store import atomic_write_json
from pdf2epub.structure.layout import LayoutItem, order_layout_items
from pdf2epub.structure.paragraphs import ExtractedLine, build_text_blocks


@dataclass(frozen=True, slots=True)
class _ImagePayload:
    bbox: BBox
    data: bytes
    extension: str


def _bbox_tuple(value: object) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise NativeTextExtractionError("PyMuPDF returned an invalid bbox")
    return float(value[0]), float(value[1]), float(value[2]), float(value[3])


class NativePdfParser:
    parser_id = "pymupdf_native"
    parser_version = pymupdf.VersionBind
    capabilities: tuple[str, ...] = ("pdf", "native_text", "embedded_images")
    cancellation_boundary: Literal["page"] = "page"

    def can_parse(self, context: PageContext) -> bool:
        return context.source_path.suffix.casefold() == ".pdf" and context.source_path.is_file()

    def fingerprint(self, context: PageContext, options: ParseOptions) -> tuple[str, str]:
        options_json = options.model_dump_json()
        options_hash = hashlib.sha256(options_json.encode()).hexdigest()
        fingerprint = hashlib.sha256(
            f"{context.source_sha256}:{context.page_index}:{self.parser_id}:{self.parser_version}:{options_hash}".encode()
        ).hexdigest()
        return fingerprint, options_hash

    def parse_page(self, context: PageContext, options: ParseOptions) -> PageParseResult:
        fingerprint, options_hash = self.fingerprint(context, options)
        cache_relative = PurePosixPath("cache") / "parse" / f"{fingerprint}.json"
        cache_path = context.project_root.joinpath(*cache_relative.parts)
        try:
            with pymupdf.open(context.source_path) as document:
                if document.needs_pass:
                    raise NativeTextExtractionError(
                        "Password-protected PDFs are not supported in M1"
                    )
                page = document.load_page(context.page_index)
                rect = page.rect
                rotation = page.rotation
                payload = page.get_text("dict", sort=False)
        except NativeTextExtractionError:
            raise
        except Exception as exc:
            raise NativeTextExtractionError(
                f"Native extraction failed on page {context.page_index + 1}: {type(exc).__name__}"
            ) from exc

        atomic_write_json(
            cache_path, json.dumps(self._sanitize(payload), ensure_ascii=False, indent=2)
        )
        layout_items: list[LayoutItem[ExtractedLine | _ImagePayload]] = []
        all_text: list[str] = []
        image_area = 0.0
        for block in payload.get("blocks", []):
            if block.get("type") == 0:
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    raw_text = "".join(str(span.get("text", "")) for span in spans).strip()
                    if not raw_text:
                        continue
                    line_bbox = BBox.from_tuple(_bbox_tuple(line["bbox"]))
                    span_ids = tuple(
                        stable_span_id(
                            context.source_sha256,
                            context.page_index,
                            _bbox_tuple(span["bbox"]),
                            str(span.get("text", "")),
                        )
                        for span in spans
                    )
                    flags = int(spans[0].get("flags", 0)) if spans else 0
                    style = TextStyle(
                        font_name=str(spans[0].get("font", "")) or None if spans else None,
                        font_size=float(spans[0].get("size", 0)) or None if spans else None,
                        italic=bool(flags & 2),
                        bold=bool(flags & 16),
                    )
                    extracted = ExtractedLine(span_ids, line_bbox, raw_text, style)
                    layout_items.append(LayoutItem(line_bbox.as_tuple(), extracted, True))
                    all_text.append(raw_text)
            elif block.get("type") == 1 and options.include_images:
                image_data = block.get("image")
                if not isinstance(image_data, bytes):
                    continue
                bbox = BBox.from_tuple(_bbox_tuple(block["bbox"]))
                image_area = max(image_area, (bbox.x1 - bbox.x0) * (bbox.y1 - bbox.y0))
                image = _ImagePayload(
                    bbox=bbox,
                    data=image_data,
                    extension=str(block.get("ext", "png")).casefold(),
                )
                layout_items.append(LayoutItem(bbox.as_tuple(), image, False))

        ordered = order_layout_items(layout_items, rect.width)
        blocks: list[Block] = []
        assets: dict[str, Asset] = {}
        line_group: list[ExtractedLine] = []

        def flush_lines() -> None:
            nonlocal line_group
            if not line_group:
                return
            blocks.extend(
                build_text_blocks(
                    line_group,
                    source_sha256=context.source_sha256,
                    parser_id=self.parser_id,
                    parser_version=self.parser_version,
                    options_hash=options_hash,
                    raw_cache_path=cache_relative.as_posix(),
                )
            )
            line_group = []

        for item in ordered:
            if isinstance(item.payload, ExtractedLine):
                line_group.append(item.payload)
                continue
            flush_lines()
            image = item.payload
            content_hash = hashlib.sha256(image.data).hexdigest()
            asset_id = stable_asset_id(content_hash)
            extension = (
                image.extension if image.extension in {"png", "jpg", "jpeg", "gif"} else "png"
            )
            relative_path = PurePosixPath("assets") / "images" / f"{asset_id}.{extension}"
            target = context.project_root.joinpath(*relative_path.parts)
            self._write_asset(target, image.data)
            mime_extension = "jpeg" if extension in {"jpg", "jpeg"} else extension
            assets[asset_id] = Asset(
                id=asset_id,
                sha256=content_hash,
                mime_type=f"image/{mime_extension}",
                relative_path=relative_path.as_posix(),
                source_page_index=context.page_index,
                bbox=image.bbox,
                extraction_method="embedded",
            )
            provenance = ProcessingProvenance(
                source_sha256=context.source_sha256,
                parser_id=self.parser_id,
                parser_version=self.parser_version,
                options_hash=options_hash,
                source_span_ids=[f"image-{content_hash[:20]}"],
                raw_cache_path=cache_relative.as_posix(),
            )
            blocks.append(
                ImageBlock(
                    id=f"img-{content_hash[:20]}-{context.page_index}",
                    bbox=image.bbox,
                    reading_order=len(blocks),
                    provenance=provenance,
                    asset_id=asset_id,
                )
            )
        flush_lines()
        blocks = [
            block.model_copy(update={"reading_order": index}) for index, block in enumerate(blocks)
        ]
        quality = native_text_quality(" ".join(all_text), image_area, rect.width * rect.height)
        classification = classify_page(quality, rotation)
        warnings = (
            ["native_content_may_be_incomplete"]
            if classification.recommended_parser == "paddle_ppstructure_v3"
            else []
        )
        result_page = Page(
            page_index=context.page_index,
            width=rect.width,
            height=rect.height,
            rotation=rotation,
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            parser_options=options.model_dump(),
            parse_status="parsed",
            parse_fingerprint=fingerprint,
            parse_warnings=warnings,
            quality=quality,
            classification=classification,
            blocks=blocks,
        )
        return PageParseResult(result_page, tuple(assets.values()), fingerprint)

    @staticmethod
    def _sanitize(value: Any) -> Any:
        if isinstance(value, bytes):
            return {"byte_length": len(value), "sha256": hashlib.sha256(value).hexdigest()}
        if isinstance(value, dict):
            return {str(key): NativePdfParser._sanitize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [NativePdfParser._sanitize(item) for item in value]
        return value

    @staticmethod
    def _write_asset(path: Path, data: bytes) -> None:
        if (
            path.is_file()
            and hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(data).digest()
        ):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

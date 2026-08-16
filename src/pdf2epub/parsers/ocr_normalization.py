from __future__ import annotations

import hashlib
import math
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import pymupdf

from pdf2epub.domain.errors import OcrPayloadError
from pdf2epub.domain.identifiers import stable_asset_id, stable_ocr_block_id
from pdf2epub.domain.models import (
    Asset,
    BBox,
    Block,
    CaptionBlock,
    HeadingBlock,
    ImageBlock,
    NativeTextQuality,
    Page,
    PageClassification,
    ParagraphBlock,
    ProcessingProvenance,
)
from pdf2epub.parsers.base import OcrParseOptions, PageContext

NORMALIZATION_SCHEMA = "ppstructure-v3-normalization-v1"
TEXT_LABELS = {"text", "content", "abstract", "paragraph", "reference"}
HEADING_LABELS = {"title", "document_title", "paragraph_title", "section_title"}
CAPTION_LABELS = {"figure_title", "table_title", "chart_title", "caption"}
IMAGE_LABELS = {"image", "figure"}
UNSUPPORTED_CROP_LABELS = {"table", "formula", "chart", "seal", "region"}


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    page: Page
    assets: tuple[Asset, ...]
    warnings: tuple[str, ...]


def normalize_ocr_text(text: str) -> str:
    value = text.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", value)
    return " ".join(part.strip() for part in value.splitlines() if part.strip())


def _bbox(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in result):
        return None
    if result[2] <= result[0] or result[3] <= result[1]:
        return None
    return result  # type: ignore[return-value]


def _intersection_ratio(
    left: tuple[float, float, float, float], right: tuple[float, float, float, float]
) -> float:
    x0, y0 = max(left[0], right[0]), max(left[1], right[1])
    x1, y1 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    area = max(1.0, (right[2] - right[0]) * (right[3] - right[1]))
    return intersection / area


def _page_bbox(
    raw_bbox: tuple[float, float, float, float],
    *,
    image_width: float,
    image_height: float,
    page_width: float,
    page_height: float,
) -> BBox | None:
    if image_width <= 0 or image_height <= 0:
        return None
    x0 = min(max(raw_bbox[0] * page_width / image_width, 0), page_width)
    y0 = min(max(raw_bbox[1] * page_height / image_height, 0), page_height)
    x1 = min(max(raw_bbox[2] * page_width / image_width, 0), page_width)
    y1 = min(max(raw_bbox[3] * page_height / image_height, 0), page_height)
    if x1 <= x0 or y1 <= y0:
        return None
    return BBox(x0=x0, y0=y0, x1=x1, y1=y1)


def _confidence(res: dict[str, Any], raw_bbox: tuple[float, float, float, float]) -> float | None:
    ocr = res.get("overall_ocr_res")
    if isinstance(ocr, dict):
        boxes = ocr.get("rec_boxes") or []
        scores = ocr.get("rec_scores") or []
        matches = [
            float(score)
            for box, score in zip(boxes, scores, strict=False)
            if (parsed := _bbox(box)) is not None and _intersection_ratio(raw_bbox, parsed) > 0.3
        ]
        if matches:
            return min(max(sum(matches) / len(matches), 0.0), 1.0)
    layout = res.get("layout_det_res")
    if isinstance(layout, dict):
        candidates: list[tuple[float, float]] = []
        for item in layout.get("boxes", []):
            if not isinstance(item, dict) or (parsed := _bbox(item.get("coordinate"))) is None:
                continue
            candidates.append((_intersection_ratio(raw_bbox, parsed), float(item.get("score", 0))))
        if candidates:
            overlap, score = max(candidates)
            if overlap > 0.3:
                return min(max(score, 0.0), 1.0)
    return None


def _write_rendered_crop(
    context: PageContext, bbox: BBox, options: OcrParseOptions
) -> tuple[Asset, bytes]:
    try:
        with pymupdf.open(context.source_path) as document:
            page = document.load_page(context.page_index)
            pixmap = page.get_pixmap(
                clip=pymupdf.Rect(*bbox.as_tuple()), dpi=options.dpi, alpha=False
            )
            data = pixmap.tobytes("png")
    except Exception as exc:
        raise OcrPayloadError(
            f"Could not render OCR fallback crop on page {context.page_index + 1}",
            code="ocr_crop_failed",
        ) from exc
    content_hash = hashlib.sha256(data).hexdigest()
    asset_id = stable_asset_id(content_hash)
    relative = PurePosixPath("assets") / "images" / f"{asset_id}.png"
    asset = Asset(
        id=asset_id,
        sha256=content_hash,
        mime_type="image/png",
        relative_path=relative.as_posix(),
        source_page_index=context.page_index,
        bbox=bbox,
        extraction_method="rendered_crop",
    )
    return asset, data


def _save_asset(project_root: Path, asset: Asset, data: bytes) -> None:
    path = project_root.joinpath(*PurePosixPath(asset.relative_path).parts)
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == asset.sha256:
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


def normalize_ppstructure_payload(
    payload: dict[str, Any],
    *,
    context: PageContext,
    options: OcrParseOptions,
    page_width: float,
    page_height: float,
    rotation: int,
    quality: NativeTextQuality,
    classification: PageClassification,
    parser_version: str,
    options_hash: str,
    parse_fingerprint: str,
    raw_cache_path: str,
    package_versions: dict[str, str],
    model_versions: dict[str, str],
) -> NormalizationResult:
    res = payload.get("res")
    if not isinstance(res, dict):
        raise OcrPayloadError("PP-StructureV3 payload has no result object", code="ocr_schema")
    elements = res.get("parsing_res_list")
    width, height = res.get("width"), res.get("height")
    if (
        not isinstance(elements, list)
        or not isinstance(width, (int, float))
        or not isinstance(height, (int, float))
    ):
        raise OcrPayloadError(
            "PP-StructureV3 payload is incompatible with the supported schema",
            code="ocr_schema",
        )

    parsed: list[tuple[dict[str, Any], tuple[float, float, float, float], BBox]] = []
    warnings: list[str] = []
    for index, element in enumerate(elements):
        if not isinstance(element, dict) or (raw_bbox := _bbox(element.get("block_bbox"))) is None:
            warnings.append(f"invalid_bbox_skipped:{index}")
            continue
        bbox = _page_bbox(
            raw_bbox,
            image_width=float(width),
            image_height=float(height),
            page_width=page_width,
            page_height=page_height,
        )
        if bbox is None:
            warnings.append(f"invalid_bbox_skipped:{index}")
            continue
        parsed.append((element, raw_bbox, bbox))

    model_identity = ";".join(f"{key}={value}" for key, value in sorted(model_versions.items()))
    assets: dict[str, Asset] = {}
    asset_data: dict[str, bytes] = {}
    asset_boxes: list[tuple[BBox, str]] = []
    crop_indexes: set[int] = set()
    for index, (element, _raw_bbox, bbox) in enumerate(parsed):
        label = str(element.get("block_label", "unknown")).casefold()
        content = str(element.get("block_content", "")).strip()
        if label in IMAGE_LABELS or (label in UNSUPPORTED_CROP_LABELS and not content):
            asset, data = _write_rendered_crop(context, bbox, options)
            assets[asset.id] = asset
            asset_data[asset.id] = data
            asset_boxes.append((bbox, asset.id))
            crop_indexes.add(index)

    blocks: list[Block] = []
    for index, (element, raw_bbox, bbox) in enumerate(parsed):
        label = str(element.get("block_label", "unknown")).casefold()
        raw_text = str(element.get("block_content", "")).strip()
        normalized_text = normalize_ocr_text(raw_text)
        raw_element_id = f"{element.get('block_id', index)}:{element.get('block_order', index)}"
        block_id = stable_ocr_block_id(
            context.source_sha256,
            context.page_index,
            "paddle_ppstructure_v3",
            model_identity,
            bbox.as_tuple(),
            raw_element_id,
        )
        confidence = _confidence(res, raw_bbox)
        block_warnings: list[str] = []
        if confidence is not None and confidence < 0.5:
            block_warnings.append("low_ocr_confidence")
            warnings.append(f"low_ocr_confidence:{block_id}")
        provenance = ProcessingProvenance(
            source_sha256=context.source_sha256,
            parser_id="paddle_ppstructure_v3",
            parser_version=parser_version,
            options_hash=options_hash,
            raw_cache_path=raw_cache_path,
            warnings=block_warnings,
            provider_id="paddleocr",
            engine="paddle_inference",
            device=options.device,
            precision=options.precision,
            model_versions={**package_versions, **model_versions},
            raw_payload_schema="ppstructure-v3-result-json",
            raw_element_ids=[raw_element_id],
        )

        if index in crop_indexes:
            asset_id = next(
                candidate_id
                for candidate_bbox, candidate_id in asset_boxes
                if candidate_bbox == bbox
            )
            blocks.append(
                ImageBlock(
                    id=block_id,
                    bbox=bbox,
                    reading_order=len(blocks),
                    provenance=provenance,
                    confidence=confidence,
                    asset_id=asset_id,
                    alt_text=normalized_text,
                )
            )
            if label in UNSUPPORTED_CROP_LABELS:
                warnings.append(f"unsupported_structure_rendered:{label}:{block_id}")
            continue
        if not normalized_text:
            warnings.append(f"empty_ocr_block_skipped:{raw_element_id}")
            continue
        common = {
            "id": block_id,
            "bbox": bbox,
            "reading_order": len(blocks),
            "provenance": provenance,
            "confidence": confidence,
            "source_text_raw": raw_text,
            "source_text_normalized": normalized_text,
        }
        if label in HEADING_LABELS:
            level = 1 if label in {"title", "document_title"} else 2
            blocks.append(HeadingBlock(**common, level=level))  # type: ignore[arg-type]
        elif label in CAPTION_LABELS and asset_boxes:
            center_y = (bbox.y0 + bbox.y1) / 2
            asset_id = min(
                asset_boxes,
                key=lambda item: abs(((item[0].y0 + item[0].y1) / 2) - center_y),
            )[1]
            blocks.append(CaptionBlock(**common, for_asset_id=asset_id))  # type: ignore[arg-type]
        else:
            if label not in TEXT_LABELS:
                warnings.append(f"unknown_structure_as_text:{label}:{block_id}")
            blocks.append(ParagraphBlock(**common))  # type: ignore[arg-type]

    for asset_id, data in asset_data.items():
        _save_asset(context.project_root, assets[asset_id], data)
    page = Page(
        page_index=context.page_index,
        width=page_width,
        height=page_height,
        rotation=rotation,
        parser_id="paddle_ppstructure_v3",
        parser_version=parser_version,
        parser_options=options.model_dump(exclude={"allow_model_download", "bypass_cache"}),
        model_versions={**package_versions, **model_versions},
        classification=classification,
        parse_status="parsed",
        parse_fingerprint=parse_fingerprint,
        parse_warnings=warnings,
        quality=quality,
        blocks=blocks,
    )
    return NormalizationResult(page=page, assets=tuple(assets.values()), warnings=tuple(warnings))

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from pdf2epub.domain.identifiers import stable_block_id
from pdf2epub.domain.models import (
    BBox,
    HeadingBlock,
    ParagraphBlock,
    ProcessingProvenance,
    TextBlock,
    TextStyle,
)


@dataclass(frozen=True, slots=True)
class ExtractedLine:
    span_ids: tuple[str, ...]
    bbox: BBox
    raw_text: str
    style: TextStyle


def _normalized_join(left: str, right: str) -> str:
    left = left.rstrip()
    right = right.lstrip()
    if left.endswith("-") and right[:1].islower():
        return left[:-1] + right
    return f"{left} {right}".strip()


def _can_merge(left: ExtractedLine, right: ExtractedLine) -> bool:
    left_size = left.style.font_size or 11.0
    right_size = right.style.font_size or left_size
    vertical_gap = right.bbox.y0 - left.bbox.y1
    return (
        -2 <= vertical_gap <= max(left_size, right_size) * 0.85
        and abs(left.bbox.x0 - right.bbox.x0) <= max(left_size, right_size) * 1.2
        and abs(left_size - right_size) <= 0.75
        and left.style.bold == right.style.bold
    )


def build_text_blocks(
    lines: list[ExtractedLine],
    *,
    source_sha256: str,
    parser_id: str,
    parser_version: str,
    options_hash: str,
    raw_cache_path: str,
) -> list[TextBlock]:
    if not lines:
        return []
    groups: list[list[ExtractedLine]] = []
    for line in lines:
        if groups and _can_merge(groups[-1][-1], line):
            groups[-1].append(line)
        else:
            groups.append([line])

    body_sizes = [line.style.font_size for line in lines if line.style.font_size]
    body_size = median(body_sizes) if body_sizes else 11.0
    blocks: list[TextBlock] = []
    for reading_order, group in enumerate(groups):
        span_ids = [span_id for line in group for span_id in line.span_ids]
        raw = "\n".join(line.raw_text for line in group)
        normalized = group[0].raw_text.strip()
        for line in group[1:]:
            normalized = _normalized_join(normalized, line.raw_text)
        style = group[0].style
        is_heading = len(normalized) <= 120 and (
            (style.font_size or 0) >= body_size * 1.30
            or (style.bold and (style.font_size or body_size) >= body_size)
        )
        provenance = ProcessingProvenance(
            source_sha256=source_sha256,
            parser_id=parser_id,
            parser_version=parser_version,
            options_hash=options_hash,
            source_span_ids=span_ids,
            raw_cache_path=raw_cache_path,
        )
        block_id = stable_block_id(span_ids)
        bbox = BBox.union([line.bbox for line in group])
        if is_heading:
            ratio = (style.font_size or body_size) / body_size
            level = 1 if ratio >= 1.7 else 2 if ratio >= 1.4 else 3
            blocks.append(
                HeadingBlock(
                    id=block_id,
                    bbox=bbox,
                    reading_order=reading_order,
                    provenance=provenance,
                    source_text_raw=raw,
                    source_text_normalized=normalized,
                    style=style,
                    level=level,
                )
            )
        else:
            blocks.append(
                ParagraphBlock(
                    id=block_id,
                    bbox=bbox,
                    reading_order=reading_order,
                    provenance=provenance,
                    source_text_raw=raw,
                    source_text_normalized=normalized,
                    style=style,
                )
            )
    return blocks

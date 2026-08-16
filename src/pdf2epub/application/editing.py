from __future__ import annotations

from datetime import UTC, datetime

from pdf2epub.domain.identifiers import merged_block_id, split_block_id
from pdf2epub.domain.models import (
    BBox,
    BookDocument,
    HeadingBlock,
    Page,
    ParagraphBlock,
    ProcessingProvenance,
    TextBlock,
    TextStyle,
)


def _join_text(left: str, right: str) -> str:
    left = left.rstrip()
    right = right.lstrip()
    if left.endswith("-") and right[:1].islower():
        return left[:-1] + right
    return f"{left} {right}".strip()


def _make_text_block(
    template: TextBlock,
    *,
    heading: bool,
    block_id: str,
    bbox: BBox,
    reading_order: int,
    provenance: ProcessingProvenance,
    raw_text: str,
    normalized_text: str,
    user_text: str | None,
    style: TextStyle,
) -> TextBlock:
    common = {
        "id": block_id,
        "bbox": bbox,
        "reading_order": reading_order,
        "provenance": provenance,
        "source_text_raw": raw_text,
        "source_text_normalized": normalized_text,
        "source_text_user": user_text,
        "style": style,
    }
    if heading:
        level = template.level if isinstance(template, HeadingBlock) else 1
        return HeadingBlock(**common, level=level)  # type: ignore[arg-type]
    return ParagraphBlock(**common)  # type: ignore[arg-type]


class DocumentEditor:
    """Small M1 editor. Every operation returns a newly validated document."""

    def edit_text(
        self, document: BookDocument, page_index: int, block_id: str, text: str
    ) -> BookDocument:
        page = self._page(document, page_index)
        blocks = []
        found = False
        for block in page.blocks:
            if block.id == block_id and isinstance(block, (ParagraphBlock, HeadingBlock)):
                provenance = block.provenance.model_copy(update={"user_edited": True})
                block = block.model_copy(
                    update={"source_text_user": text, "provenance": provenance}
                )
                found = True
            blocks.append(block)
        if not found:
            raise KeyError(f"Editable block not found: {block_id}")
        return self._replace_page(document, page.model_copy(update={"blocks": blocks}))

    def change_type(
        self,
        document: BookDocument,
        page_index: int,
        block_id: str,
        block_type: str,
        heading_level: int = 1,
    ) -> BookDocument:
        page = self._page(document, page_index)
        blocks = []
        found = False
        for block in page.blocks:
            if block.id == block_id and isinstance(block, (ParagraphBlock, HeadingBlock)):
                provenance = block.provenance.model_copy(update={"user_edited": True})
                if block_type == "heading":
                    block = HeadingBlock(
                        id=block.id,
                        bbox=block.bbox,
                        reading_order=block.reading_order,
                        provenance=provenance,
                        source_text_raw=block.source_text_raw,
                        source_text_normalized=block.source_text_normalized,
                        source_text_user=block.source_text_user,
                        style=block.style,
                        level=heading_level,
                    )
                elif block_type == "paragraph":
                    block = ParagraphBlock(
                        id=block.id,
                        bbox=block.bbox,
                        reading_order=block.reading_order,
                        provenance=provenance,
                        source_text_raw=block.source_text_raw,
                        source_text_normalized=block.source_text_normalized,
                        source_text_user=block.source_text_user,
                        style=block.style,
                    )
                else:
                    raise ValueError("M1 supports only paragraph and heading types")
                found = True
            blocks.append(block)
        if not found:
            raise KeyError(f"Text block not found: {block_id}")
        return self._replace_page(document, page.model_copy(update={"blocks": blocks}))

    def merge_adjacent(
        self, document: BookDocument, page_index: int, first_block_id: str
    ) -> BookDocument:
        page = self._page(document, page_index)
        index = next((i for i, block in enumerate(page.blocks) if block.id == first_block_id), -1)
        if index < 0 or index + 1 >= len(page.blocks):
            raise ValueError("A following block is required for merge")
        left = page.blocks[index]
        right = page.blocks[index + 1]
        if not isinstance(left, (ParagraphBlock, HeadingBlock)) or not isinstance(
            right, (ParagraphBlock, HeadingBlock)
        ):
            raise ValueError("Only adjacent text blocks can be merged")
        provenance = ProcessingProvenance(
            source_sha256=left.provenance.source_sha256,
            parser_id=left.provenance.parser_id,
            parser_version=left.provenance.parser_version,
            options_hash=left.provenance.options_hash,
            source_span_ids=left.provenance.source_span_ids + right.provenance.source_span_ids,
            raw_cache_path=left.provenance.raw_cache_path,
            warnings=left.provenance.warnings + right.provenance.warnings,
            user_edited=True,
        )
        merged = _make_text_block(
            left,
            heading=isinstance(left, HeadingBlock) and isinstance(right, HeadingBlock),
            block_id=merged_block_id((left.id, right.id)),
            bbox=BBox.union([left.bbox, right.bbox]),
            reading_order=left.reading_order,
            provenance=provenance,
            raw_text=_join_text(left.source_text_raw, right.source_text_raw),
            normalized_text=_join_text(left.source_text_normalized, right.source_text_normalized),
            user_text=_join_text(left.effective_text, right.effective_text),
            style=left.style,
        )
        blocks = [*page.blocks[:index], merged, *page.blocks[index + 2 :]]
        blocks = [
            block.model_copy(update={"reading_order": order}) for order, block in enumerate(blocks)
        ]
        return self._replace_page(document, page.model_copy(update={"blocks": blocks}))

    def split_block(
        self, document: BookDocument, page_index: int, block_id: str, offset: int
    ) -> BookDocument:
        page = self._page(document, page_index)
        index = next((i for i, block in enumerate(page.blocks) if block.id == block_id), -1)
        if index < 0:
            raise KeyError(f"Text block not found: {block_id}")
        block = page.blocks[index]
        if not isinstance(block, (ParagraphBlock, HeadingBlock)):
            raise ValueError("Only text blocks can be split")
        text = block.effective_text
        if offset <= 0 or offset >= len(text):
            raise ValueError("Split offset must be inside the effective text")
        left_text, right_text = text[:offset].rstrip(), text[offset:].lstrip()
        if not left_text or not right_text:
            raise ValueError("Split must produce two non-empty blocks")
        raw_offset = min(offset, len(block.source_text_raw))
        normalized_offset = min(offset, len(block.source_text_normalized))
        mid_y = (block.bbox.y0 + block.bbox.y1) / 2
        provenance = block.provenance.model_copy(update={"user_edited": True})
        left = _make_text_block(
            block,
            heading=isinstance(block, HeadingBlock),
            block_id=split_block_id(block.id, offset, "left"),
            bbox=BBox(x0=block.bbox.x0, y0=block.bbox.y0, x1=block.bbox.x1, y1=mid_y),
            reading_order=block.reading_order,
            provenance=provenance,
            raw_text=block.source_text_raw[:raw_offset],
            normalized_text=block.source_text_normalized[:normalized_offset],
            user_text=left_text,
            style=block.style,
        )
        right = _make_text_block(
            block,
            heading=isinstance(block, HeadingBlock),
            block_id=split_block_id(block.id, offset, "right"),
            bbox=BBox(x0=block.bbox.x0, y0=mid_y, x1=block.bbox.x1, y1=block.bbox.y1),
            reading_order=block.reading_order + 1,
            provenance=provenance,
            raw_text=block.source_text_raw[raw_offset:],
            normalized_text=block.source_text_normalized[normalized_offset:],
            user_text=right_text,
            style=block.style,
        )
        blocks = [*page.blocks[:index], left, right, *page.blocks[index + 1 :]]
        blocks = [
            candidate.model_copy(update={"reading_order": order})
            for order, candidate in enumerate(blocks)
        ]
        return self._replace_page(document, page.model_copy(update={"blocks": blocks}))

    @staticmethod
    def _page(document: BookDocument, page_index: int) -> Page:
        try:
            return next(page for page in document.pages if page.page_index == page_index)
        except StopIteration as exc:
            raise KeyError(f"Page not found: {page_index}") from exc

    @staticmethod
    def _replace_page(document: BookDocument, page: Page) -> BookDocument:
        pages = [
            page if current.page_index == page.page_index else current for current in document.pages
        ]
        return document.model_copy(update={"pages": pages, "updated_at": datetime.now(UTC)})

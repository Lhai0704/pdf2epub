from __future__ import annotations

from datetime import UTC, datetime

from pdf2epub.domain.identifiers import merged_block_id, split_block_id
from pdf2epub.domain.models import (
    BBox,
    BookDocument,
    CaptionBlock,
    HeadingBlock,
    Page,
    PageFooterBlock,
    PageHeaderBlock,
    ParagraphBlock,
    ProcessingProvenance,
    TextBlock,
    TextStyle,
    TranslationProvenance,
    TranslationRecord,
    TranslationSettings,
)
from pdf2epub.translation.cache import source_fingerprint


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
        "confidence": template.confidence,
    }
    if heading:
        level = template.level if isinstance(template, HeadingBlock) else 1
        return HeadingBlock(**common, level=level)  # type: ignore[arg-type]
    if isinstance(template, PageHeaderBlock):
        return PageHeaderBlock(**common)  # type: ignore[arg-type]
    if isinstance(template, PageFooterBlock):
        return PageFooterBlock(**common)  # type: ignore[arg-type]
    if isinstance(template, CaptionBlock):
        return CaptionBlock(**common, for_asset_id=template.for_asset_id)  # type: ignore[arg-type]
    return ParagraphBlock(**common)  # type: ignore[arg-type]


class DocumentEditor:
    """Auditable source/translation editor returning newly validated documents."""

    def edit_text(
        self,
        document: BookDocument,
        page_index: int,
        block_id: str,
        text: str,
        *,
        operation_id: str | None = None,
    ) -> BookDocument:
        page = self._page(document, page_index)
        blocks = []
        found = False
        for block in page.blocks:
            if block.id == block_id and isinstance(
                block,
                (ParagraphBlock, HeadingBlock, CaptionBlock, PageHeaderBlock, PageFooterBlock),
            ):
                previous_fingerprint = source_fingerprint(block.effective_text)
                operation_ids = list(block.provenance.edit_operation_ids)
                if operation_id is not None and operation_id not in operation_ids:
                    operation_ids.append(operation_id)
                provenance = block.provenance.model_copy(
                    update={"user_edited": True, "edit_operation_ids": operation_ids}
                )
                block = block.model_copy(
                    update={"source_text_user": text, "provenance": provenance}
                )
                if (
                    isinstance(block, ParagraphBlock)
                    and block.translation is not None
                    and source_fingerprint(block.effective_text) != previous_fingerprint
                ):
                    block = block.model_copy(
                        update={
                            "translation": block.translation.model_copy(
                                update={"status": "stale", "updated_at": datetime.now(UTC)}
                            )
                        }
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
        *,
        operation_id: str | None = None,
    ) -> BookDocument:
        page = self._page(document, page_index)
        blocks = []
        found = False
        for block in page.blocks:
            if block.id == block_id and isinstance(
                block, (ParagraphBlock, HeadingBlock, PageHeaderBlock, PageFooterBlock)
            ):
                operation_ids = list(block.provenance.edit_operation_ids)
                if operation_id is not None and operation_id not in operation_ids:
                    operation_ids.append(operation_id)
                provenance = block.provenance.model_copy(
                    update={"user_edited": True, "edit_operation_ids": operation_ids}
                )
                common = {
                    "id": block.id,
                    "bbox": block.bbox,
                    "reading_order": block.reading_order,
                    "provenance": provenance,
                    "source_text_raw": block.source_text_raw,
                    "source_text_normalized": block.source_text_normalized,
                    "source_text_user": block.source_text_user,
                    "style": block.style,
                    "confidence": block.confidence,
                }
                if block_type == "heading":
                    block = HeadingBlock(**common, level=heading_level)  # type: ignore[arg-type]
                elif block_type == "paragraph":
                    block = ParagraphBlock(
                        **common,  # type: ignore[arg-type]
                        translation=block.translation
                        if isinstance(block, ParagraphBlock)
                        else None,
                    )
                elif block_type == "page_header":
                    block = PageHeaderBlock(**common)  # type: ignore[arg-type]
                elif block_type == "page_footer":
                    block = PageFooterBlock(**common)  # type: ignore[arg-type]
                else:
                    raise ValueError(
                        "Structure editing supports paragraph, heading, page_header, "
                        "and page_footer"
                    )
                found = True
            blocks.append(block)
        if not found:
            raise KeyError(f"Text block not found: {block_id}")
        return self._replace_page(document, page.model_copy(update={"blocks": blocks}))

    def edit_translation(
        self, document: BookDocument, paragraph_id: str, text: str
    ) -> BookDocument:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Translation text cannot be empty")
        settings = document.translation_settings
        pages = []
        found = False
        for page in document.pages:
            blocks = []
            page_changed = False
            for block in page.blocks:
                if block.id == paragraph_id and isinstance(block, ParagraphBlock):
                    previous = block.translation
                    previous_provenance = previous.provenance if previous else None
                    record = TranslationRecord(
                        text=clean_text,
                        status="user_edited",
                        source_fingerprint=source_fingerprint(block.effective_text),
                        provenance=TranslationProvenance(
                            origin="manual",
                            provider_id=(
                                previous_provenance.provider_id
                                if previous_provenance
                                else settings.provider_id
                            ),
                            model=(
                                previous_provenance.model if previous_provenance else settings.model
                            ),
                            prompt_version=(
                                previous_provenance.prompt_version
                                if previous_provenance
                                else settings.prompt_version
                            ),
                            glossary_version=(
                                previous_provenance.glossary_version
                                if previous_provenance
                                else settings.glossary_version
                            ),
                            request_id=(previous.provenance.request_id if previous else None),
                        ),
                        created_at=previous.created_at if previous else datetime.now(UTC),
                    )
                    block = block.model_copy(update={"translation": record})
                    found = True
                    page_changed = True
                blocks.append(block)
            pages.append(page.model_copy(update={"blocks": blocks}) if page_changed else page)
        if not found:
            raise KeyError(f"Paragraph not found: {paragraph_id}")
        return document.model_copy(update={"pages": pages, "updated_at": datetime.now(UTC)})

    def update_translation_settings(
        self,
        document: BookDocument,
        *,
        source_language: str,
        settings: TranslationSettings,
    ) -> BookDocument:
        source_language = source_language.strip()
        if not source_language or not settings.target_language.strip():
            raise ValueError("Source and target languages are required")
        previous = document.translation_settings
        affecting_previous = previous.model_dump(exclude={"remote_consent_at"})
        affecting_next = settings.model_dump(exclude={"remote_consent_at"})
        should_stale = document.metadata.language != source_language or (
            affecting_previous != affecting_next
        )
        metadata = document.metadata.model_copy(update={"language": source_language})
        pages = document.pages
        if should_stale:
            pages = []
            for page in document.pages:
                blocks = [
                    block.model_copy(
                        update={
                            "translation": block.translation.model_copy(
                                update={"status": "stale", "updated_at": datetime.now(UTC)}
                            )
                        }
                    )
                    if isinstance(block, ParagraphBlock) and block.translation is not None
                    else block
                    for block in page.blocks
                ]
                pages.append(page.model_copy(update={"blocks": blocks}))
        return document.model_copy(
            update={
                "metadata": metadata,
                "translation_settings": settings,
                "pages": pages,
                "updated_at": datetime.now(UTC),
            }
        )

    def merge_adjacent(
        self,
        document: BookDocument,
        page_index: int,
        first_block_id: str,
        *,
        operation_id: str | None = None,
    ) -> BookDocument:
        page = self._page(document, page_index)
        index = next((i for i, block in enumerate(page.blocks) if block.id == first_block_id), -1)
        if index < 0 or index + 1 >= len(page.blocks):
            raise ValueError("A following block is required for merge")
        left = page.blocks[index]
        right = page.blocks[index + 1]
        mergeable = (ParagraphBlock, HeadingBlock, PageHeaderBlock, PageFooterBlock)
        if not isinstance(left, mergeable) or not isinstance(right, mergeable):
            raise ValueError("Only adjacent structure text blocks can be merged")
        if type(left) is not type(right):
            raise ValueError("Merged blocks must have the same structure type")
        if isinstance(left, HeadingBlock) and (
            not isinstance(right, HeadingBlock) or left.level != right.level
        ):
            raise ValueError("Merged headings must have the same level")
        operation_ids = left.provenance.edit_operation_ids + right.provenance.edit_operation_ids
        if operation_id is not None and operation_id not in operation_ids:
            operation_ids.append(operation_id)
        provenance = left.provenance.model_copy(
            update={
                "source_span_ids": (
                    left.provenance.source_span_ids + right.provenance.source_span_ids
                ),
                "warnings": left.provenance.warnings + right.provenance.warnings,
                "user_edited": True,
                "derived_from_block_ids": [left.id, right.id],
                "edit_operation_ids": operation_ids,
            }
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
        self,
        document: BookDocument,
        page_index: int,
        block_id: str,
        offset: int,
        *,
        operation_id: str | None = None,
    ) -> BookDocument:
        page = self._page(document, page_index)
        index = next((i for i, block in enumerate(page.blocks) if block.id == block_id), -1)
        if index < 0:
            raise KeyError(f"Text block not found: {block_id}")
        block = page.blocks[index]
        if not isinstance(block, (ParagraphBlock, HeadingBlock, PageHeaderBlock, PageFooterBlock)):
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
        operation_ids = list(block.provenance.edit_operation_ids)
        if operation_id is not None and operation_id not in operation_ids:
            operation_ids.append(operation_id)
        provenance = block.provenance.model_copy(
            update={
                "user_edited": True,
                "derived_from_block_ids": [block.id],
                "edit_operation_ids": operation_ids,
            }
        )
        fingerprint = source_fingerprint(text)
        left = _make_text_block(
            block,
            heading=isinstance(block, HeadingBlock),
            block_id=split_block_id(block.id, offset, "left", fingerprint),
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
            block_id=split_block_id(block.id, offset, "right", fingerprint),
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

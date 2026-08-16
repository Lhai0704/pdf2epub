from __future__ import annotations

from dataclasses import dataclass

from pdf2epub.domain.models import Page, ParagraphBlock


@dataclass(frozen=True, slots=True)
class ParseProgress:
    current: int
    total: int
    page_index: int
    stage: str


@dataclass(frozen=True, slots=True)
class ReparseConflict:
    page_index: int
    user_edited_blocks: int
    derived_blocks: int
    translations: int

    @property
    def has_conflicts(self) -> bool:
        return bool(self.user_edited_blocks or self.derived_blocks or self.translations)


@dataclass(frozen=True, slots=True)
class BatchParseSummary:
    parsed_count: int
    cache_hits: int
    failed_pages: tuple[int, ...]
    cancelled: bool


def reparse_conflict(page: Page) -> ReparseConflict:
    return ReparseConflict(
        page_index=page.page_index,
        user_edited_blocks=sum(block.provenance.user_edited for block in page.blocks),
        derived_blocks=sum(
            bool(
                block.id.startswith(("merge-", "split-"))
                or block.provenance.derived_from_block_ids
                or block.provenance.edit_operation_ids
            )
            for block in page.blocks
        ),
        translations=sum(
            isinstance(block, ParagraphBlock) and block.translation is not None
            for block in page.blocks
        ),
    )

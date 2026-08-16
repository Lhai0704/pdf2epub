from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pdf2epub.application.warnings import synchronize_page_parser_warnings
from pdf2epub.domain.errors import OcrError, ParserUnavailableError
from pdf2epub.domain.models import (
    BBox,
    Block,
    BookDocument,
    CaptionBlock,
    ImageBlock,
    LoadedProject,
    Page,
)
from pdf2epub.parsers.base import (
    OcrParseOptions,
    PageContext,
    ParseOptions,
    RegionDocumentParser,
    RegionParseRequest,
)
from pdf2epub.parsers.registry import ParserRegistry
from pdf2epub.persistence.project_store import ProjectStore

CancelCallback = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class RegionCandidate:
    command_id: str
    page_index: int
    region: BBox
    replaced_block_ids: tuple[str, ...]
    candidate_block_ids: tuple[str, ...]
    document: BookDocument
    warnings: tuple[str, ...]
    cache_hit: bool


class RegionReparseService:
    def __init__(self, registry: ParserRegistry, *, store: ProjectStore | None = None) -> None:
        self.registry = registry
        self.store = store or ProjectStore()

    def capability_error(self, page: Page) -> str | None:
        if page.parse_status != "parsed":
            return "Region reparse requires a parsed, non-stale page"
        if page.parser_id is None:
            return "Region reparse requires an actual page parser"
        try:
            parser = self.registry.get(page.parser_id)
        except ParserUnavailableError as exc:
            return str(exc)
        if "region_ocr" not in parser.capabilities or not hasattr(parser, "parse_region"):
            return "M4 region reparse is available only for Paddle OCR pages"
        return None

    def build_candidate(
        self,
        project: LoadedProject,
        page_index: int,
        region: BBox,
        *,
        options: ParseOptions | None = None,
        cancelled: CancelCallback | None = None,
    ) -> RegionCandidate:
        page = self._page(project.document, page_index)
        if error := self.capability_error(page):
            raise ParserUnavailableError(error)
        parser = cast(RegionDocumentParser, self.registry.get(page.parser_id or ""))
        selected = self._selected_blocks(page, region)
        if not selected:
            raise ValueError("Region must cover at least half of one existing block")
        selected = self._expand_asset_groups(page, selected)
        selected_ids = {block.id for block in selected}
        expanded_region = BBox.union([region, *(block.bbox for block in selected)])
        command_id = f"cmd-{uuid.uuid4()}"
        context = PageContext(
            source_path=self.store.source_path(project),
            project_root=Path(project.root),
            source_sha256=project.document.source.sha256,
            page_index=page_index,
            language=project.document.metadata.language,
        )
        parse_options = options or OcrParseOptions()
        result = parser.parse_region(
            context,
            RegionParseRequest(region=expanded_region, command_id=command_id),
            parse_options,
        )
        if cancelled is not None and cancelled():
            raise OcrError(
                "Region OCR completed after cancellation; candidate was discarded",
                code="ocr_region_cancelled",
            )
        if not result.blocks:
            raise OcrError("Region OCR produced no blocks", code="ocr_region_empty_result")

        first_index = min(
            index for index, block in enumerate(page.blocks) if block.id in selected_ids
        )
        remaining = [block for block in page.blocks if block.id not in selected_ids]
        before = [block for block in remaining if page.blocks.index(block) < first_index]
        after = [block for block in remaining if page.blocks.index(block) >= first_index]
        combined = [*before, *result.blocks, *after]
        combined = [
            block.model_copy(update={"reading_order": index})
            for index, block in enumerate(combined)
        ]
        retained_warnings = [
            warning
            for warning in page.parse_warnings
            if not any(block_id in warning for block_id in selected_ids)
        ]
        replacement = page.model_copy(
            update={
                "blocks": combined,
                "parse_warnings": list(dict.fromkeys([*retained_warnings, *result.warnings])),
                "parse_error": None,
            }
        )
        pages = [
            replacement if item.page_index == page_index else item
            for item in project.document.pages
        ]
        assets = project.document.assets.copy()
        assets.update({asset.id: asset for asset in result.assets})
        document = project.document.model_copy(update={"pages": pages, "assets": assets})
        document = synchronize_page_parser_warnings(document, page_index)
        document = BookDocument.model_validate(document.model_dump(exclude_computed_fields=True))
        return RegionCandidate(
            command_id=command_id,
            page_index=page_index,
            region=expanded_region,
            replaced_block_ids=tuple(block.id for block in selected),
            candidate_block_ids=tuple(block.id for block in result.blocks),
            document=document,
            warnings=result.warnings,
            cache_hit=result.cache_hit,
        )

    @staticmethod
    def _selected_blocks(page: Page, region: BBox) -> list[Block]:
        selected = []
        for block in page.blocks:
            width = max(block.bbox.x1 - block.bbox.x0, 0.0)
            height = max(block.bbox.y1 - block.bbox.y0, 0.0)
            area = width * height
            if area <= 0:
                continue
            x0 = max(block.bbox.x0, region.x0)
            y0 = max(block.bbox.y0, region.y0)
            x1 = min(block.bbox.x1, region.x1)
            y1 = min(block.bbox.y1, region.y1)
            overlap = max(x1 - x0, 0.0) * max(y1 - y0, 0.0)
            if overlap / area >= 0.5:
                selected.append(block)
        return selected

    @staticmethod
    def _expand_asset_groups(page: Page, selected: list[Block]) -> list[Block]:
        asset_ids = {block.asset_id for block in selected if isinstance(block, ImageBlock)} | {
            block.for_asset_id for block in selected if isinstance(block, CaptionBlock)
        }
        selected_ids = {block.id for block in selected}
        for block in page.blocks:
            linked = (isinstance(block, ImageBlock) and block.asset_id in asset_ids) or (
                isinstance(block, CaptionBlock) and block.for_asset_id in asset_ids
            )
            if linked:
                selected_ids.add(block.id)
        return [block for block in page.blocks if block.id in selected_ids]

    @staticmethod
    def _page(document: BookDocument, page_index: int) -> Page:
        try:
            return next(page for page in document.pages if page.page_index == page_index)
        except StopIteration as exc:
            raise KeyError(f"Page not found: {page_index}") from exc

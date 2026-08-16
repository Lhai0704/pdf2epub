from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import pymupdf

from pdf2epub.application.commands import StructureCommandService
from pdf2epub.application.region_reparse import RegionReparseService
from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.domain.models import BBox, Page, ParagraphBlock, ProcessingProvenance
from pdf2epub.parsers.base import (
    PageContext,
    PageParseResult,
    ParseOptions,
    RegionParseRequest,
    RegionParseResult,
)
from pdf2epub.parsers.native_pdf import NativePdfParser
from pdf2epub.parsers.registry import OCR_PARSER_ID, ParserRegistry


class FakeRegionOcr:
    parser_id = OCR_PARSER_ID
    parser_version = "fake-region-1"
    capabilities: tuple[str, ...] = ("pdf", "ocr", "region_ocr")
    cancellation_boundary: Literal["page"] = "page"

    def can_parse(self, context: PageContext) -> bool:
        return context.source_path.is_file()

    def fingerprint(self, context: PageContext, options: ParseOptions) -> tuple[str, str]:
        options_hash = hashlib.sha256(options.model_dump_json().encode()).hexdigest()
        fingerprint = hashlib.sha256(f"{context.page_index}:{options_hash}".encode()).hexdigest()
        return fingerprint, options_hash

    def parse_page(self, context: PageContext, options: ParseOptions) -> PageParseResult:
        fingerprint, options_hash = self.fingerprint(context, options)
        with pymupdf.open(context.source_path) as document:  # type: ignore[no-untyped-call]
            source = document[context.page_index]
            width, height = source.rect.width, source.rect.height
        block = self._block(
            "whole-region-source",
            BBox(x0=20, y0=20, x1=min(width - 20, 300), y1=100),
            options_hash,
        )
        page = Page(
            page_index=context.page_index,
            width=width,
            height=height,
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            parse_status="parsed",
            parse_fingerprint=fingerprint,
            blocks=[block],
        )
        return PageParseResult(page=page, assets=(), parse_fingerprint=fingerprint)

    def parse_region(
        self,
        context: PageContext,
        request: RegionParseRequest,
        options: ParseOptions,
    ) -> RegionParseResult:
        _, options_hash = self.fingerprint(context, options)
        block = self._block("region-replacement", request.region, options_hash)
        provenance = block.provenance.model_copy(
            update={
                "edit_operation_ids": [request.command_id],
                "source_region": request.region,
            }
        )
        block = block.model_copy(update={"provenance": provenance})
        return RegionParseResult(
            blocks=(block,),
            assets=(),
            warnings=(),
            parse_fingerprint="r" * 64,
        )

    def _block(self, block_id: str, bbox: BBox, options_hash: str) -> ParagraphBlock:
        return ParagraphBlock(
            id=block_id,
            bbox=bbox,
            reading_order=0,
            provenance=ProcessingProvenance(
                source_sha256="a" * 64,
                parser_id=self.parser_id,
                parser_version=self.parser_version,
                options_hash=options_hash,
                provider_id="fake",
            ),
            source_text_raw=block_id,
            source_text_normalized=block_id,
        )


def test_region_candidate_is_atomic_and_undoable(fixture_corpus: Path, tmp_path: Path) -> None:
    native = NativePdfParser()
    ocr = FakeRegionOcr()
    registry = ParserRegistry()
    registry.register(native.parser_id, lambda: native)
    registry.register(ocr.parser_id, lambda: ocr)
    workflow = BookWorkflow(registry=registry)
    project = workflow.create_project(
        tmp_path / "region.bepub-project", fixture_corpus / "mixed.pdf"
    )
    project, _ = workflow.parse_page(project, 1)
    original = project.document
    service = RegionReparseService(registry, store=workflow.store)
    region = BBox(x0=20, y0=20, x1=300, y1=100)
    candidate = service.build_candidate(project, 1, region, options=ParseOptions())
    assert project.document == original
    assert candidate.replaced_block_ids == ("whole-region-source",)
    assert candidate.candidate_block_ids == ("region-replacement",)

    commands = StructureCommandService(store=workflow.store)
    committed = commands.commit_region_candidate(
        project,
        candidate.document,
        page_index=1,
        command_id=candidate.command_id,
        region=candidate.region,
        selected_block_id="region-replacement",
    )
    assert committed.project.document.pages[1].parser_id == OCR_PARSER_ID
    assert (
        committed.project.document.pages[1].parse_fingerprint == original.pages[1].parse_fingerprint
    )
    assert committed.project.document.edit_audit[-1].kind == "region_replace"
    assert committed.project.document.edit_audit[-1].region == candidate.region
    undone = commands.undo(committed.project)
    assert undone.project.document.pages[1].blocks[0].id == "whole-region-source"


def test_native_page_reports_region_capability_error(fixture_corpus: Path, tmp_path: Path) -> None:
    workflow = BookWorkflow()
    project = workflow.create_project(
        tmp_path / "native-region.bepub-project",
        fixture_corpus / "digital_single_column.pdf",
    )
    project, _ = workflow.parse_page(project, 0)
    service = RegionReparseService(workflow.registry, store=workflow.store)
    assert service.capability_error(project.document.pages[0]) == (
        "M4 region reparse is available only for Paddle OCR pages"
    )

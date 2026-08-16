from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

import pymupdf

from pdf2epub.application.commands import StructureCommandService
from pdf2epub.application.region_reparse import RegionReparseService
from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.domain.models import (
    BBox,
    Page,
    ParagraphBlock,
    ProcessingProvenance,
    ProjectWarning,
)
from pdf2epub.epub.builder import EpubBuilder, EpubBuildOptions
from pdf2epub.epub.validator import EpubValidator
from pdf2epub.fixtures import generate_fixture_corpus
from pdf2epub.parsers.base import (
    PageContext,
    PageParseResult,
    ParseOptions,
    RegionParseRequest,
    RegionParseResult,
)
from pdf2epub.parsers.native_pdf import NativePdfParser
from pdf2epub.parsers.registry import OCR_PARSER_ID, ParserRegistry


class _FakeRegionOcr:
    parser_id = OCR_PARSER_ID
    parser_version = "verify-region-1"
    capabilities: tuple[str, ...] = ("pdf", "ocr", "region_ocr")
    cancellation_boundary: Literal["page"] = "page"

    def can_parse(self, context: PageContext) -> bool:
        return context.source_path.is_file()

    def fingerprint(self, context: PageContext, options: ParseOptions) -> tuple[str, str]:
        options_hash = hashlib.sha256(options.model_dump_json().encode()).hexdigest()
        fingerprint = hashlib.sha256(
            f"{context.source_sha256}:{context.page_index}:{options_hash}:m4".encode()
        ).hexdigest()
        return fingerprint, options_hash

    def parse_page(self, context: PageContext, options: ParseOptions) -> PageParseResult:
        fingerprint, options_hash = self.fingerprint(context, options)
        with pymupdf.open(context.source_path) as source:  # type: ignore[no-untyped-call]
            page = source[context.page_index]
            width, height = page.rect.width, page.rect.height
        block = self._block(
            "verify-region-source", BBox(x0=20, y0=20, x1=300, y1=100), options_hash
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
        block = self._block("verify-region-result", request.region, options_hash)
        provenance = block.provenance.model_copy(
            update={
                "edit_operation_ids": [request.command_id],
                "source_region": request.region,
            }
        )
        return RegionParseResult(
            blocks=(block.model_copy(update={"provenance": provenance}),),
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
                provider_id="verify-fake",
            ),
            source_text_raw="Generated M4 verification text.",
            source_text_normalized="Generated M4 verification text.",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the deterministic M4 workbench slice")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--epubcheck-jar", type=Path)
    arguments = parser.parse_args()
    root = arguments.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    fixtures = root / "fixtures"
    generate_fixture_corpus(fixtures)

    workflow = BookWorkflow()
    project = workflow.create_project(
        root / "structure.bepub-project", fixtures / "digital_single_column.pdf"
    )
    project, _ = workflow.parse_page(project, 0)
    paragraphs = [
        block for block in project.document.pages[0].blocks if isinstance(block, ParagraphBlock)
    ]
    commands = StructureCommandService(store=workflow.store)
    merged = commands.execute_merge(project, 0, paragraphs[0].id)
    undone = commands.undo(merged.project)
    redone = commands.redo(undone.project)
    merged_block = next(
        block
        for block in redone.project.document.pages[0].blocks
        if block.id == merged.selected_block_id
    )
    assert isinstance(merged_block, ParagraphBlock)
    split = commands.execute_split(
        redone.project, 0, merged_block.id, len(merged_block.effective_text) // 2
    )
    split_block = next(
        block for block in split.project.document.pages[0].blocks if block.id.startswith("split-")
    )
    header = commands.execute_edit(
        split.project,
        0,
        split_block.id,
        text=split_block.effective_text,
        block_type="page_header",
    )

    complete_output = root / "exports" / "m4-complete.epub"
    complete_build = EpubBuilder().build(
        header.project.document, Path(header.project.root), complete_output
    )
    warning = ProjectWarning(
        id="warn-m4-verify",
        code="m4_review_required",
        source="structure",
        message="Generated M4 review warning",
        page_index=0,
        affects_export=True,
    )
    incomplete_document = header.project.document.model_copy(update={"warnings": [warning]})
    incomplete_output = root / "exports" / "m4-incomplete.epub"
    incomplete_build = EpubBuilder().build(
        incomplete_document,
        Path(header.project.root),
        incomplete_output,
        options=EpubBuildOptions(include_incomplete_notice=True),
    )

    native = NativePdfParser()
    fake = _FakeRegionOcr()
    registry = ParserRegistry()
    registry.register(native.parser_id, lambda: native)
    registry.register(fake.parser_id, lambda: fake)
    region_workflow = BookWorkflow(registry=registry)
    region_project = region_workflow.create_project(
        root / "region.bepub-project", fixtures / "mixed.pdf"
    )
    region_project, _ = region_workflow.parse_page(region_project, 1)
    candidate = RegionReparseService(registry, store=region_workflow.store).build_candidate(
        region_project,
        1,
        BBox(x0=20, y0=20, x1=300, y1=100),
        options=ParseOptions(),
    )
    region_commit = StructureCommandService(store=region_workflow.store).commit_region_candidate(
        region_project,
        candidate.document,
        page_index=1,
        command_id=candidate.command_id,
        region=candidate.region,
        selected_block_id=candidate.candidate_block_ids[0],
    )

    jar = arguments.epubcheck_jar or Path(".tools/epubcheck-5.3.0/epubcheck.jar")
    complete_validation = EpubValidator(jar).validate(complete_output)
    incomplete_validation = EpubValidator(jar).validate(incomplete_output)
    result = {
        "schema_version": header.project.document.schema_version,
        "audit_events": len(header.project.document.edit_audit),
        "region_audit": region_commit.project.document.edit_audit[-1].kind,
        "complete_build": complete_build.model_dump(),
        "complete_validation": complete_validation.model_dump(),
        "incomplete_build": incomplete_build.model_dump(),
        "incomplete_validation": incomplete_validation.model_dump(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if complete_validation.passed and incomplete_validation.passed else 3


if __name__ == "__main__":
    raise SystemExit(main())

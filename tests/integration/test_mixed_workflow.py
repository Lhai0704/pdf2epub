from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Literal

import pymupdf
import pytest

from pdf2epub.application.editing import DocumentEditor
from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.domain.errors import EpubBuildError, ReparseConflictError
from pdf2epub.domain.models import (
    BBox,
    Page,
    ParagraphBlock,
    ProcessingProvenance,
)
from pdf2epub.epub.builder import EpubBuilder, EpubBuildOptions
from pdf2epub.parsers.base import PageContext, PageParseResult, ParseOptions
from pdf2epub.parsers.native_pdf import NativePdfParser
from pdf2epub.parsers.registry import OCR_PARSER_ID, ParserRegistry


class CountingNativeParser(NativePdfParser):
    def __init__(self) -> None:
        self.calls: list[int] = []

    def parse_page(self, context: PageContext, options: ParseOptions) -> PageParseResult:
        self.calls.append(context.page_index)
        return super().parse_page(context, options)


class FakeOcrParser:
    parser_id = OCR_PARSER_ID
    parser_version = "fake-1"
    capabilities: tuple[str, ...] = ("pdf", "ocr")
    cancellation_boundary: Literal["page"] = "page"

    def __init__(self) -> None:
        self.calls: list[int] = []

    def can_parse(self, context: PageContext) -> bool:
        return context.source_path.is_file()

    def fingerprint(self, context: PageContext, options: ParseOptions) -> tuple[str, str]:
        options_hash = hashlib.sha256(options.model_dump_json().encode()).hexdigest()
        fingerprint = hashlib.sha256(
            f"{context.source_sha256}:{context.page_index}:{options_hash}:fake".encode()
        ).hexdigest()
        return fingerprint, options_hash

    def parse_page(self, context: PageContext, options: ParseOptions) -> PageParseResult:
        self.calls.append(context.page_index)
        fingerprint, options_hash = self.fingerprint(context, options)
        with pymupdf.open(context.source_path) as document:  # type: ignore[no-untyped-call]
            source_page = document[context.page_index]
            width, height, rotation = (
                source_page.rect.width,
                source_page.rect.height,
                source_page.rotation,
            )
        block = ParagraphBlock(
            id=f"ocr-fake-{context.page_index}",
            bbox=BBox(x0=20, y0=20, x1=min(width - 20, 300), y1=80),
            reading_order=0,
            confidence=0.98,
            provenance=ProcessingProvenance(
                source_sha256=context.source_sha256,
                parser_id=self.parser_id,
                parser_version=self.parser_version,
                options_hash=options_hash,
                raw_cache_path="cache/parse/fake.json",
                provider_id="fake",
            ),
            source_text_raw="Fake OCR text",
            source_text_normalized="Fake OCR text",
        )
        page = Page(
            page_index=context.page_index,
            width=width,
            height=height,
            rotation=rotation,
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            parser_options=options.model_dump(),
            parse_status="parsed",
            parse_fingerprint=fingerprint,
            blocks=[block],
        )
        return PageParseResult(page=page, assets=(), parse_fingerprint=fingerprint)


def mixed_workflow() -> tuple[BookWorkflow, CountingNativeParser, FakeOcrParser]:
    native = CountingNativeParser()
    ocr = FakeOcrParser()
    registry = ParserRegistry()
    registry.register(native.parser_id, lambda: native)
    registry.register(ocr.parser_id, lambda: ocr)
    return BookWorkflow(registry=registry), native, ocr


def test_mixed_document_routes_each_page_once_and_supports_override_reparse(
    fixture_corpus: Path, tmp_path: Path
) -> None:
    workflow, native, ocr = mixed_workflow()
    project = workflow.create_project(
        tmp_path / "mixed.bepub-project", fixture_corpus / "mixed.pdf"
    )
    assert project.document.pages[0].classification is not None
    assert project.document.pages[0].classification.recommended_parser == "native"
    assert project.document.pages[1].classification is not None
    assert project.document.pages[1].classification.recommended_parser == OCR_PARSER_ID

    project, summary = workflow.parse_pages(project, [0, 1])
    assert summary.parsed_count == 2
    assert summary.failed_pages == ()
    assert native.calls == [0]
    assert ocr.calls == [1]
    assert project.document.pages[0].parser_id == native.parser_id
    assert project.document.pages[1].parser_id == OCR_PARSER_ID

    project = workflow.set_page_override(project, [0], "paddle_ppstructure_v3")
    assert project.document.pages[0].parse_status == "stale"
    project, _ = workflow.parse_page(project, 0)
    assert ocr.calls == [1, 0]

    block_id = project.document.pages[0].blocks[0].id
    document = DocumentEditor().edit_text(project.document, 0, block_id, "Manual source edit")
    project = workflow.store.save(project.model_copy(update={"document": document}))
    with pytest.raises(ReparseConflictError):
        workflow.parse_page(project, 0, reparse=True)
    reparsed, _ = workflow.parse_page(project, 0, reparse=True, confirm_conflicts=True)
    assert reparsed.document.pages[0].blocks[0].provenance.user_edited is False


def test_incomplete_export_requires_explicit_notice(fixture_corpus: Path, tmp_path: Path) -> None:
    workflow = BookWorkflow()
    project = workflow.create_project(
        tmp_path / "incomplete.bepub-project", fixture_corpus / "mixed.pdf"
    )
    project, _ = workflow.parse_page(project, 0)
    output = tmp_path / "incomplete.epub"
    with pytest.raises(EpubBuildError, match="explicit incomplete export confirmation"):
        EpubBuilder().build(project.document, Path(project.root), output)
    EpubBuilder().build(
        project.document,
        Path(project.root),
        output,
        options=EpubBuildOptions(include_incomplete_notice=True),
    )
    with zipfile.ZipFile(output) as archive:
        notice = archive.read("EPUB/text/incomplete-content.xhtml").decode("utf-8")
    assert "Incomplete content notice" in notice
    assert "Page 2" in notice

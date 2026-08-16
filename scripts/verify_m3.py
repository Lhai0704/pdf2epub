from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

import pymupdf

from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.domain.models import BBox, Page, ParagraphBlock, ProcessingProvenance
from pdf2epub.epub.builder import EpubBuilder, EpubBuildOptions
from pdf2epub.epub.validator import EpubValidator
from pdf2epub.fixtures import generate_fixture_corpus
from pdf2epub.parsers.base import PageContext, PageParseResult, ParseOptions
from pdf2epub.parsers.native_pdf import NativePdfParser
from pdf2epub.parsers.registry import OCR_PARSER_ID, ParserRegistry


class _CountingNative(NativePdfParser):
    def __init__(self) -> None:
        self.calls: list[int] = []

    def parse_page(self, context: PageContext, options: ParseOptions) -> PageParseResult:
        self.calls.append(context.page_index)
        return super().parse_page(context, options)


class _FakeOcr:
    parser_id = OCR_PARSER_ID
    parser_version = "verify-fake-1"
    capabilities: tuple[str, ...] = ("pdf", "ocr")
    cancellation_boundary: Literal["page"] = "page"

    def __init__(self) -> None:
        self.calls: list[int] = []

    def can_parse(self, context: PageContext) -> bool:
        return context.source_path.is_file()

    def fingerprint(self, context: PageContext, options: ParseOptions) -> tuple[str, str]:
        options_hash = hashlib.sha256(options.model_dump_json().encode()).hexdigest()
        fingerprint = hashlib.sha256(
            f"{context.source_sha256}:{context.page_index}:{options_hash}:m3-fake".encode()
        ).hexdigest()
        return fingerprint, options_hash

    def parse_page(self, context: PageContext, options: ParseOptions) -> PageParseResult:
        self.calls.append(context.page_index)
        fingerprint, options_hash = self.fingerprint(context, options)
        with pymupdf.open(context.source_path) as document:  # type: ignore[no-untyped-call]
            source = document[context.page_index]
            width, height, rotation = source.rect.width, source.rect.height, source.rotation
        block = ParagraphBlock(
            id=f"verify-ocr-{context.page_index}",
            bbox=BBox(x0=20, y0=20, x1=min(width - 20, 400), y1=80),
            reading_order=0,
            confidence=0.98,
            provenance=ProcessingProvenance(
                source_sha256=context.source_sha256,
                parser_id=self.parser_id,
                parser_version=self.parser_version,
                options_hash=options_hash,
                provider_id="fake-ocr",
                raw_payload_schema="verify-fake-v1",
            ),
            source_text_raw="Generated fake OCR verification text.",
            source_text_normalized="Generated fake OCR verification text.",
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the deterministic M3 mixed-PDF slice")
    parser.add_argument("--output-dir", "--workspace", dest="workspace", type=Path, required=True)
    parser.add_argument("--epubcheck-jar", type=Path)
    arguments = parser.parse_args()
    workspace = arguments.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    fixture_root = workspace / "fixtures"
    generate_fixture_corpus(fixture_root)

    native = _CountingNative()
    fake = _FakeOcr()
    registry = ParserRegistry()
    registry.register(native.parser_id, lambda: native)
    registry.register(fake.parser_id, lambda: fake)
    workflow = BookWorkflow(registry=registry)
    project_root = workspace / "mixed.bepub-project"
    if project_root.exists():
        raise SystemExit(f"Verification project already exists: {project_root}")
    project = workflow.create_project(project_root, fixture_root / "mixed.pdf")
    project, summary = workflow.parse_pages(project, [0, 1])
    if summary.failed_pages or native.calls != [0] or fake.calls != [1]:
        raise RuntimeError("Mixed parser routing verification failed")

    output = workspace / "exports" / "m3-mixed.epub"
    build = EpubBuilder().build(
        project.document,
        project_root,
        output,
        options=EpubBuildOptions(mode="source_translation"),
    )
    incomplete_root = workspace / "incomplete.bepub-project"
    incomplete = workflow.create_project(incomplete_root, fixture_root / "mixed.pdf")
    incomplete, _ = workflow.parse_page(incomplete, 0)
    incomplete_output = workspace / "exports" / "m3-mixed-incomplete.epub"
    incomplete_build = EpubBuilder().build(
        incomplete.document,
        incomplete_root,
        incomplete_output,
        options=EpubBuildOptions(include_incomplete_notice=True),
    )

    jar = arguments.epubcheck_jar or Path(".tools/epubcheck-5.3.0/epubcheck.jar")
    validation = EpubValidator(jar).validate(output)
    incomplete_validation = EpubValidator(jar).validate(incomplete_output)
    result = {
        "project": str(project_root),
        "native_calls": native.calls,
        "fake_ocr_calls": fake.calls,
        "summary": {
            "parsed": summary.parsed_count,
            "cache_hits": summary.cache_hits,
            "failed_pages": summary.failed_pages,
        },
        "build": build.model_dump(),
        "validation": validation.model_dump(),
        "incomplete_build": incomplete_build.model_dump(),
        "incomplete_validation": incomplete_validation.model_dump(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if validation.passed and incomplete_validation.passed else 3


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.domain.errors import SourceOpenError
from pdf2epub.domain.models import HeadingBlock, ImageBlock, ParagraphBlock
from pdf2epub.pdf.analyzer import PdfAnalyzer

GOLDEN_ROOT = Path(__file__).parents[1] / "fixtures" / "golden"


def test_fixture_corpus_shape(fixture_corpus: Path) -> None:
    expected_pages = {
        "digital_single_column.pdf": 1,
        "digital_two_column.pdf": 1,
        "digital_image_caption.pdf": 1,
        "digital_structure_edges.pdf": 3,
        "digital_100_pages.pdf": 100,
    }
    for name, count in expected_pages.items():
        with pymupdf.open(fixture_corpus / name) as document:  # type: ignore[no-untyped-call]
            assert document.page_count == count
    assert "No third-party book text" in (fixture_corpus / "LICENSE.txt").read_text(
        encoding="utf-8"
    )


def test_m3_fixture_classification_boundaries(fixture_corpus: Path) -> None:
    analyzer = PdfAnalyzer()
    expected = {
        "scanned_only.pdf": ("scanned", "paddle_ppstructure_v3"),
        "image_hidden_text_layer.pdf": ("image_text_layer", "native"),
        "suspect_native_layer.pdf": ("suspect", "paddle_ppstructure_v3"),
        "blank.pdf": ("blank", "native"),
        "rotated_scanned.pdf": ("scanned", "paddle_ppstructure_v3"),
        "large_boundary.pdf": ("digital", "native"),
    }
    for name, classification in expected.items():
        page = analyzer.inspect_document(fixture_corpus / name).pages[0]
        assert (page.classification.kind, page.classification.recommended_parser) == classification


def test_single_column_parser_golden_and_cache(fixture_corpus: Path, tmp_path: Path) -> None:
    workflow = BookWorkflow()
    project = workflow.create_project(
        tmp_path / "single.bepub-project", fixture_corpus / "digital_single_column.pdf"
    )
    project, cache_hit = workflow.parse_page(project, 0)
    assert not cache_hit
    page = project.document.pages[0]
    assert page.quality is not None and page.quality.status == "usable"
    assert isinstance(page.blocks[0], HeadingBlock)
    assert page.blocks[0].effective_text == "Chapter 1"
    assert isinstance(page.blocks[-1], ParagraphBlock)
    assert page.blocks[-1].effective_text.startswith("A second paragraph")
    assert any(
        "repeatable line break" in block.effective_text
        for block in page.blocks
        if isinstance(block, (ParagraphBlock, HeadingBlock))
    )
    project, cache_hit = workflow.parse_page(project, 0)
    assert cache_hit

    cache_files = list((Path(project.root) / "cache" / "parse").glob("*.json"))
    assert len(cache_files) == 1
    payload = json.loads(cache_files[0].read_text(encoding="utf-8"))
    assert "blocks" in payload


def test_image_extraction_and_preview_render(fixture_corpus: Path, tmp_path: Path) -> None:
    workflow = BookWorkflow()
    project = workflow.create_project(
        tmp_path / "image.bepub-project", fixture_corpus / "digital_image_caption.pdf"
    )
    project, _ = workflow.parse_page(project, 0)
    images = [block for block in project.document.pages[0].blocks if isinstance(block, ImageBlock)]
    assert len(images) == 1
    asset = project.document.assets[images[0].asset_id]
    assert (Path(project.root) / Path(asset.relative_path)).is_file()
    preview = workflow.render_page(project, 0)
    assert preview.suffix == ".png" and preview.is_file()
    assert workflow.render_page(project, 0) == preview


def test_two_column_order(fixture_corpus: Path, tmp_path: Path) -> None:
    workflow = BookWorkflow()
    project = workflow.create_project(
        tmp_path / "columns.bepub-project", fixture_corpus / "digital_two_column.pdf"
    )
    project, _ = workflow.parse_page(project, 0)
    text = [
        block.effective_text
        for block in project.document.pages[0].blocks
        if isinstance(block, (ParagraphBlock, HeadingBlock))
    ]
    assert next(index for index, value in enumerate(text) if "Left column begins" in value) < next(
        index for index, value in enumerate(text) if "Right column begins" in value
    )


def test_invalid_pdf_is_reported_without_content(fixture_corpus: Path, tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.pdf"
    invalid.write_bytes(b"not a pdf")
    with pytest.raises(SourceOpenError, match="Could not inspect PDF"):
        PdfAnalyzer().inspect_document(invalid)


@pytest.mark.parametrize(
    "name",
    [
        "digital_single_column",
        "digital_two_column",
        "digital_image_caption",
        "digital_structure_edges",
    ],
)
def test_parser_matches_golden(name: str, fixture_corpus: Path, tmp_path: Path) -> None:
    workflow = BookWorkflow()
    project = workflow.create_project(
        tmp_path / f"{name}.bepub-project", fixture_corpus / f"{name}.pdf"
    )
    project, _ = workflow.parse_all(project)
    text_blocks = [
        block
        for page in project.document.pages
        for block in page.blocks
        if isinstance(block, (ParagraphBlock, HeadingBlock))
    ]
    actual = {
        "headings": [
            block.effective_text for block in text_blocks if isinstance(block, HeadingBlock)
        ],
        "paragraph_count": sum(isinstance(block, ParagraphBlock) for block in text_blocks),
        "image_count": sum(
            isinstance(block, ImageBlock)
            for page in project.document.pages
            for block in page.blocks
        ),
        "first_text": text_blocks[0].effective_text,
        "last_text": text_blocks[-1].effective_text,
    }
    expected = json.loads((GOLDEN_ROOT / f"{name}.json").read_text(encoding="utf-8"))
    assert actual == expected

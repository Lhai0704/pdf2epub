from __future__ import annotations

import pytest
from pydantic import ValidationError

from pdf2epub.application.editing import DocumentEditor
from pdf2epub.domain.identifiers import stable_block_id, stable_span_id
from pdf2epub.domain.models import (
    BBox,
    Block,
    BookDocument,
    BookMetadata,
    Page,
    ParagraphBlock,
    ProcessingProvenance,
    ProjectSource,
    SourceDocument,
)

HASH = "a" * 64


def paragraph(block_id: str = "blk-one") -> ParagraphBlock:
    return ParagraphBlock(
        id=block_id,
        bbox=BBox(x0=10, y0=10, x1=100, y1=30),
        reading_order=0,
        provenance=ProcessingProvenance(
            source_sha256=HASH,
            parser_id="test",
            parser_version="1",
            options_hash="options",
            source_span_ids=["span-one"],
        ),
        source_text_raw="raw text",
        source_text_normalized="normalized text",
    )


def document(blocks: list[Block] | None = None) -> BookDocument:
    return BookDocument(
        document_id="doc-test",
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(original_name="test.pdf", sha256=HASH, size_bytes=10),
        pages=[Page(page_index=0, width=200, height=300, blocks=blocks or [])],
    )


def test_bbox_rejects_invalid_coordinates() -> None:
    with pytest.raises(ValidationError):
        BBox(x0=20, y0=0, x1=10, y1=20)


def test_document_round_trip_and_unknown_schema() -> None:
    original = document([paragraph()])
    payload = original.model_dump_json(exclude_computed_fields=True)
    assert BookDocument.model_validate_json(payload) == original
    with pytest.raises(ValidationError):
        BookDocument.model_validate({**original.model_dump(), "schema_version": "2.0"})


def test_duplicate_block_ids_are_rejected() -> None:
    with pytest.raises(ValidationError):
        BookDocument(
            document_id="doc-test",
            metadata=BookMetadata(title="Test"),
            source=SourceDocument(original_name="test.pdf", sha256=HASH, size_bytes=10),
            pages=[
                Page(page_index=0, width=200, height=300, blocks=[paragraph("same")]),
                Page(page_index=1, width=200, height=300, blocks=[paragraph("same")]),
            ],
        )


def test_stable_ids_and_edit_preserves_raw() -> None:
    bbox = (1.111, 2.222, 3.333, 4.444)
    span_id = stable_span_id(HASH, 0, bbox, "text")
    assert span_id == stable_span_id(HASH, 0, bbox, "text")
    assert stable_block_id([span_id]) == stable_block_id([span_id])
    original = document([paragraph()])
    edited = DocumentEditor().edit_text(original, 0, "blk-one", "user text")
    block = edited.pages[0].blocks[0]
    assert isinstance(block, ParagraphBlock)
    assert block.source_text_raw == "raw text"
    assert block.effective_text == "user text"
    assert block.id == "blk-one"


def test_project_source_rejects_traversal() -> None:
    with pytest.raises(ValidationError):
        ProjectSource(
            original_name="test.pdf",
            sha256=HASH,
            size_bytes=1,
            relative_path="../test.pdf",
        )

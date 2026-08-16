from __future__ import annotations

from pdf2epub.application.editing import DocumentEditor
from pdf2epub.domain.models import (
    BBox,
    BookDocument,
    BookMetadata,
    Page,
    ParagraphBlock,
    ProcessingProvenance,
    SourceDocument,
)


def _block(block_id: str, order: int, text: str, y: float) -> ParagraphBlock:
    return ParagraphBlock(
        id=block_id,
        bbox=BBox(x0=10, y0=y, x1=100, y1=y + 10),
        reading_order=order,
        provenance=ProcessingProvenance(
            source_sha256="a" * 64,
            parser_id="test",
            parser_version="1",
            options_hash="test",
            source_span_ids=[f"span-{block_id}"],
        ),
        source_text_raw=text,
        source_text_normalized=text,
    )


def _document() -> BookDocument:
    return BookDocument(
        document_id="doc",
        metadata=BookMetadata(title="Book"),
        source=SourceDocument(original_name="book.pdf", sha256="a" * 64, size_bytes=1),
        pages=[
            Page(
                page_index=0,
                width=200,
                height=300,
                blocks=[_block("one", 0, "repeat-", 10), _block("two", 1, "able text", 30)],
            )
        ],
    )


def test_merge_and_split_have_stable_new_ids() -> None:
    editor = DocumentEditor()
    merged = editor.merge_adjacent(_document(), 0, "one")
    merged_block = merged.pages[0].blocks[0]
    assert isinstance(merged_block, ParagraphBlock)
    assert merged_block.effective_text == "repeatable text"
    assert merged_block.source_text_raw == "repeatable text"
    split = editor.split_block(merged, 0, merged_block.id, 6)
    assert len(split.pages[0].blocks) == 2
    assert [block.reading_order for block in split.pages[0].blocks] == [0, 1]
    assert split.pages[0].blocks[0].id != split.pages[0].blocks[1].id

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
    TranslationProvenance,
    TranslationRecord,
)
from pdf2epub.translation.cache import source_fingerprint


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


def test_source_and_translation_edits_follow_stale_rules() -> None:
    document = _document()
    block = document.pages[0].blocks[0]
    assert isinstance(block, ParagraphBlock)
    translation = TranslationRecord(
        text="translated",
        status="translated",
        source_fingerprint=source_fingerprint(block.effective_text),
        provenance=TranslationProvenance(
            origin="provider",
            provider_id="fake",
            model="fake",
            prompt_version="translate-v1",
            glossary_version=document.translation_settings.glossary_version,
        ),
    )
    page = document.pages[0].model_copy(
        update={
            "blocks": [
                block.model_copy(update={"translation": translation}),
                document.pages[0].blocks[1],
            ]
        }
    )
    document = document.model_copy(update={"pages": [page]})
    editor = DocumentEditor()
    unchanged = editor.edit_text(document, 0, "one", block.effective_text)
    unchanged_block = unchanged.pages[0].blocks[0]
    assert isinstance(unchanged_block, ParagraphBlock)
    assert unchanged_block.translation is not None
    assert unchanged_block.translation.status == "translated"

    changed = editor.edit_text(document, 0, "one", "new source")
    changed_block = changed.pages[0].blocks[0]
    assert isinstance(changed_block, ParagraphBlock)
    assert changed_block.translation is not None
    assert changed_block.translation.status == "stale"
    manual = editor.edit_translation(changed, "one", "manual translation")
    manual_block = manual.pages[0].blocks[0]
    assert isinstance(manual_block, ParagraphBlock)
    assert manual_block.translation is not None
    assert manual_block.translation.status == "user_edited"
    assert manual_block.translation.source_fingerprint == source_fingerprint("new source")


def test_merge_split_and_type_changes_do_not_guess_translations() -> None:
    document = _document()
    editor = DocumentEditor()
    translated = editor.edit_translation(document, "one", "manual")
    merged = editor.merge_adjacent(translated, 0, "one")
    merged_block = merged.pages[0].blocks[0]
    assert isinstance(merged_block, ParagraphBlock)
    assert merged_block.translation is None
    split = editor.split_block(translated, 0, "one", 3)
    assert all(
        isinstance(block, ParagraphBlock) and block.translation is None
        for block in split.pages[0].blocks[:2]
    )
    heading = editor.change_type(translated, 0, "one", "heading")
    restored = editor.change_type(heading, 0, "one", "paragraph")
    restored_block = restored.pages[0].blocks[0]
    assert isinstance(restored_block, ParagraphBlock)
    assert restored_block.translation is None


def test_language_change_stales_all_existing_translations() -> None:
    editor = DocumentEditor()
    document = editor.edit_translation(_document(), "one", "first manual")
    document = editor.edit_translation(document, "two", "second manual")
    settings = document.translation_settings.model_copy(update={"target_language": "ja"})
    changed = editor.update_translation_settings(document, source_language="en", settings=settings)
    assert all(
        isinstance(block, ParagraphBlock)
        and block.translation is not None
        and block.translation.status == "stale"
        for block in changed.pages[0].blocks
    )

from __future__ import annotations

import pytest

from pdf2epub.domain.models import (
    BBox,
    BookDocument,
    BookMetadata,
    GlossaryEntry,
    HeadingBlock,
    Page,
    ParagraphBlock,
    ProcessingProvenance,
    SourceDocument,
    TranslationSettings,
)
from pdf2epub.translation.cache import source_fingerprint, translation_cache_key
from pdf2epub.translation.context import build_translation_request

HASH = "a" * 64


def _provenance(name: str) -> ProcessingProvenance:
    return ProcessingProvenance(
        source_sha256=HASH,
        parser_id="test",
        parser_version="1",
        options_hash="options",
        source_span_ids=[name],
    )


def _document() -> BookDocument:
    bbox = BBox(x0=1, y0=1, x1=50, y1=20)
    return BookDocument(
        document_id="doc",
        metadata=BookMetadata(title="Book", language="en"),
        source=SourceDocument(original_name="book.pdf", sha256=HASH, size_bytes=1),
        translation_settings=TranslationSettings(target_language="zh-CN"),
        pages=[
            Page(
                page_index=0,
                width=100,
                height=100,
                blocks=[
                    HeadingBlock(
                        id="heading",
                        reading_order=0,
                        provenance=_provenance("heading"),
                        source_text_raw="Chapter",
                        source_text_normalized="Chapter",
                        level=1,
                        bbox=bbox,
                    ),
                    ParagraphBlock(
                        id="one",
                        reading_order=1,
                        provenance=_provenance("one"),
                        source_text_raw="First",
                        source_text_normalized="First",
                        bbox=bbox,
                    ),
                    ParagraphBlock(
                        id="two",
                        reading_order=2,
                        provenance=_provenance("two"),
                        source_text_raw="Second",
                        source_text_normalized="Second",
                        bbox=bbox,
                    ),
                ],
            )
        ],
    )


def test_context_and_cache_key_include_surroundings_and_settings() -> None:
    document = _document()
    request = build_translation_request(document, "two")
    assert request.chapter_heading == "Chapter"
    assert request.previous_paragraph == "First"
    assert request.next_paragraph is None
    first_key = translation_cache_key(request)
    changed = request.model_copy(update={"previous_paragraph": "Changed"})
    assert translation_cache_key(changed) != first_key
    changed = request.model_copy(update={"target_language": "ja"})
    assert translation_cache_key(changed) != first_key


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_text", "Changed source"),
        ("source_language", "fr"),
        ("provider_id", "another-provider"),
        ("model", "another-model"),
        ("prompt_version", "translate-v2"),
        ("chapter_heading", "Another chapter"),
        ("previous_paragraph", "Another previous paragraph"),
        ("next_paragraph", "Another next paragraph"),
        ("style_instructions", "Use a formal style"),
    ],
)
def test_cache_key_changes_for_every_translation_input(field: str, value: str) -> None:
    request = build_translation_request(_document(), "two")
    assert translation_cache_key(
        request.model_copy(update={field: value})
    ) != translation_cache_key(request)


def test_cache_key_changes_with_glossary_version() -> None:
    document = _document()
    request = build_translation_request(document, "two")
    settings = document.translation_settings.model_copy(
        update={"glossary": [GlossaryEntry(source="book", target="书")]}
    )
    changed = request.model_copy(
        update={"glossary": settings.glossary, "glossary_version": settings.glossary_version}
    )
    assert translation_cache_key(changed) != translation_cache_key(request)


def test_source_fingerprint_normalizes_unicode_and_newlines_only() -> None:
    assert source_fingerprint(" e\u0301\r\n") == source_fingerprint("é\n")
    assert source_fingerprint("a  b") != source_fingerprint("a b")

from __future__ import annotations

from pdf2epub.domain.models import BookDocument, HeadingBlock, ParagraphBlock
from pdf2epub.translation.base import TranslationRequest


def build_translation_request(document: BookDocument, paragraph_id: str) -> TranslationRequest:
    paragraphs: list[ParagraphBlock] = []
    chapter_by_paragraph: dict[str, str | None] = {}
    chapter_heading: str | None = None
    for page in sorted(document.pages, key=lambda value: value.page_index):
        for block in page.blocks:
            if isinstance(block, HeadingBlock):
                chapter_heading = block.effective_text
            elif isinstance(block, ParagraphBlock):
                paragraphs.append(block)
                chapter_by_paragraph[block.id] = chapter_heading

    try:
        index = next(i for i, block in enumerate(paragraphs) if block.id == paragraph_id)
    except StopIteration as exc:
        raise KeyError(f"Paragraph not found: {paragraph_id}") from exc
    paragraph = paragraphs[index]
    settings = document.translation_settings
    return TranslationRequest(
        paragraph_id=paragraph.id,
        source_text=paragraph.effective_text,
        source_language=document.metadata.language,
        target_language=settings.target_language,
        provider_id=settings.provider_id,
        model=settings.model,
        prompt_version=settings.prompt_version,
        chapter_heading=chapter_by_paragraph[paragraph.id],
        previous_paragraph=paragraphs[index - 1].effective_text if index else None,
        next_paragraph=(
            paragraphs[index + 1].effective_text if index + 1 < len(paragraphs) else None
        ),
        glossary=settings.glossary,
        glossary_version=settings.glossary_version,
        style_instructions=settings.style_instructions,
    )

from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from pdf2epub.application.warnings import active_export_warnings
from pdf2epub.domain.models import (
    BookDocument,
    CaptionBlock,
    HeadingBlock,
    ImageBlock,
    ParagraphBlock,
)

BOOK_CSS = """body {
  font-family: serif;
  line-height: 1.55;
  margin: 5%;
}
h1, h2, h3 { line-height: 1.25; margin: 1.4em 0 0.7em; }
p.source { margin: 0 0 0.9em; text-indent: 1.5em; }
p.translation { margin: 0 0 1.2em; text-indent: 1.5em; }
.para { margin: 0; }
img { display: block; max-width: 100%; height: auto; margin: 1em auto; }
figure { margin: 1em 0; }
.caption { font-size: 0.9em; font-style: italic; margin: 0.3em 0 1em; }
.incomplete-notice { border: 0.15em solid #9a6700; padding: 1em; }
"""


@dataclass(frozen=True, slots=True)
class Chapter:
    title: str
    file_name: str
    body_html: str


def build_chapters(
    document: BookDocument,
    *,
    image_href: Callable[[str], str] | None = None,
    mode: str = "original",
) -> list[Chapter]:
    if mode not in {"original", "source_translation"}:
        raise ValueError(f"Unsupported EPUB mode: {mode}")
    image_href = image_href or (lambda path: f"../images/{PurePosixPath(path).name}")
    chapters: list[Chapter] = []
    title = document.metadata.title
    body: list[str] = []

    def finish() -> None:
        if not body:
            return
        chapters.append(
            Chapter(
                title=title or f"Chapter {len(chapters) + 1}",
                file_name=f"chapter-{len(chapters) + 1:03d}.xhtml",
                body_html="\n".join(body),
            )
        )

    for page in sorted(document.pages, key=lambda value: value.page_index):
        for block in page.blocks:
            if isinstance(block, HeadingBlock):
                if block.level == 1 and body:
                    finish()
                    body = []
                if block.level == 1:
                    title = block.effective_text
                escaped = html.escape(block.effective_text, quote=False)
                body.append(f'<h{block.level} id="{block.id}">{escaped}</h{block.level}>')
            elif isinstance(block, ParagraphBlock):
                escaped = html.escape(block.effective_text, quote=False)
                source_language = html.escape(document.metadata.language, quote=True)
                paragraph = [
                    f'<div class="para" id="{block.id}">',
                    f'<p class="source" lang="{source_language}">{escaped}</p>',
                ]
                if (
                    mode == "source_translation"
                    and block.translation is not None
                    and block.translation.status in {"translated", "user_edited"}
                    and block.translation.text
                ):
                    target_language = html.escape(
                        document.translation_settings.target_language, quote=True
                    )
                    translation = html.escape(block.translation.text, quote=False)
                    paragraph.append(
                        f'<p class="translation" lang="{target_language}">{translation}</p>'
                    )
                paragraph.append("</div>")
                body.append("\n".join(paragraph))
            elif isinstance(block, ImageBlock):
                asset = document.assets[block.asset_id]
                source = html.escape(image_href(asset.relative_path), quote=True)
                alt = html.escape(block.alt_text, quote=True)
                body.append(f'<figure id="{block.id}"><img src="{source}" alt="{alt}" /></figure>')
            elif isinstance(block, CaptionBlock):
                escaped = html.escape(block.effective_text, quote=False)
                target = html.escape(block.for_asset_id, quote=True)
                body.append(
                    f'<p class="caption" id="{block.id}" data-for-asset="{target}">{escaped}</p>'
                )
    finish()
    if not chapters:
        chapters.append(
            Chapter(
                title=document.metadata.title,
                file_name="chapter-001.xhtml",
                body_html='<p class="source">This document contains no parsed text.</p>',
            )
        )
    return chapters


def incomplete_notice_chapter(document: BookDocument) -> Chapter | None:
    incomplete = [
        page
        for page in sorted(document.pages, key=lambda value: value.page_index)
        if page.parse_status != "parsed" or page.parse_warnings
    ]
    structured = active_export_warnings(document)
    if not incomplete and not structured:
        return None
    items = []
    for page in incomplete:
        details = [page.parse_status, *page.parse_warnings]
        escaped = html.escape(", ".join(details), quote=False)
        items.append(f"<li>Page {page.page_index + 1}: {escaped}</li>")
    existing = {
        (page.page_index, warning) for page in incomplete for warning in page.parse_warnings
    }
    for warning in structured:
        if (warning.page_index, warning.message) in existing:
            continue
        location = (
            f"Page {warning.page_index + 1}: " if warning.page_index is not None else "Document: "
        )
        warning_details = html.escape(f"{warning.code} ({warning.severity})", quote=False)
        items.append(f"<li>{location}{warning_details}</li>")
    body = (
        '<section class="incomplete-notice"><h1>Incomplete content notice</h1>'
        "<p>Some source pages were not completely parsed.</p><ul>"
        + "".join(items)
        + "</ul></section>"
    )
    return Chapter(
        title="Incomplete content notice",
        file_name="incomplete-content.xhtml",
        body_html=body,
    )


def chapter_xhtml(chapter: Chapter, language: str) -> str:
    escaped_title = html.escape(chapter.title, quote=False)
    escaped_language = html.escape(language, quote=True)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{escaped_language}" lang="{escaped_language}">
  <head>
    <meta charset="utf-8" />
    <title>{escaped_title}</title>
    <link rel="stylesheet" type="text/css" href="../styles/book.css" />
  </head>
  <body>
    <section class="chapter">
{chapter.body_html}
    </section>
  </body>
</html>
"""


def preview_html(
    document: BookDocument, project_root_uri: str, *, mode: str = "source_translation"
) -> str:
    def preview_image(path: str) -> str:
        relative = "/".join(PurePosixPath(path).parts)
        return f"{project_root_uri.rstrip('/')}/{relative}"

    chapters = build_chapters(document, image_href=preview_image, mode=mode)
    body = "\n".join(chapter.body_html for chapter in chapters)
    language = html.escape(document.metadata.language, quote=True)
    return f"""<!DOCTYPE html>
<html lang="{language}"><head><meta charset="utf-8" />
<style>{BOOK_CSS}</style></head><body>{body}</body></html>"""

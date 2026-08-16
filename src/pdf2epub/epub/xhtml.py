from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from pdf2epub.domain.models import BookDocument, HeadingBlock, ImageBlock, ParagraphBlock

BOOK_CSS = """body {
  font-family: serif;
  line-height: 1.55;
  margin: 5%;
}
h1, h2, h3 { line-height: 1.25; margin: 1.4em 0 0.7em; }
p.source { margin: 0 0 0.9em; text-indent: 1.5em; }
img { display: block; max-width: 100%; height: auto; margin: 1em auto; }
figure { margin: 1em 0; }
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
) -> list[Chapter]:
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
                body.append(f'<p class="source" id="{block.id}">{escaped}</p>')
            elif isinstance(block, ImageBlock):
                asset = document.assets[block.asset_id]
                source = html.escape(image_href(asset.relative_path), quote=True)
                alt = html.escape(block.alt_text, quote=True)
                body.append(f'<figure id="{block.id}"><img src="{source}" alt="{alt}" /></figure>')
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


def preview_html(document: BookDocument, project_root_uri: str) -> str:
    def preview_image(path: str) -> str:
        relative = "/".join(PurePosixPath(path).parts)
        return f"{project_root_uri.rstrip('/')}/{relative}"

    chapters = build_chapters(document, image_href=preview_image)
    body = "\n".join(chapter.body_html for chapter in chapters)
    language = html.escape(document.metadata.language, quote=True)
    return f"""<!DOCTYPE html>
<html lang="{language}"><head><meta charset="utf-8" />
<style>{BOOK_CSS}</style></head><body>{body}</body></html>"""

from __future__ import annotations

import html
import os
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict

from pdf2epub.domain.errors import EpubBuildError
from pdf2epub.domain.models import BookDocument, HeadingBlock, ParagraphBlock
from pdf2epub.epub.xhtml import BOOK_CSS, Chapter, build_chapters, chapter_xhtml


class EpubBuildResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    output_path: str
    chapter_count: int
    warnings: list[str]


def _container_xml() -> str:
    return """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml" />
  </rootfiles>
</container>
"""


def _nav_xhtml(title: str, language: str, chapters: list[tuple[str, str]]) -> str:
    escaped_language = html.escape(language, quote=True)
    links = "\n".join(
        "        <li><a "
        f'href="text/{html.escape(file_name, quote=True)}">'
        f"{html.escape(chapter_title)}</a></li>"
        for chapter_title, file_name in chapters
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops"
      xml:lang="{escaped_language}" lang="{escaped_language}">
  <head><meta charset="utf-8" /><title>{html.escape(title)}</title></head>
  <body><nav epub:type="toc" id="toc"><h1>Contents</h1><ol>
{links}
  </ol></nav></body>
</html>
"""


def _package_opf(document: BookDocument, chapter_files: list[str]) -> str:
    creator = (
        f"    <dc:creator>{html.escape(document.metadata.creator)}</dc:creator>\n"
        if document.metadata.creator
        else ""
    )
    chapter_manifest = "\n".join(
        f'    <item id="chapter-{index:03d}" href="text/{file_name}" '
        'media-type="application/xhtml+xml" />'
        for index, file_name in enumerate(chapter_files, start=1)
    )
    image_manifest = "\n".join(
        f'    <item id="{asset.id}" '
        f'href="images/{PurePosixPath(asset.relative_path).name}" '
        f'media-type="{html.escape(asset.mime_type, quote=True)}" />'
        for asset in document.assets.values()
    )
    spine = "\n".join(
        f'    <itemref idref="chapter-{index:03d}" />' for index in range(1, len(chapter_files) + 1)
    )
    modified = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    escaped_language = html.escape(document.metadata.language, quote=True)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0"
         unique-identifier="book-id" xml:lang="{escaped_language}">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">{html.escape(document.document_id)}</dc:identifier>
    <dc:title>{html.escape(document.metadata.title)}</dc:title>
    <dc:language>{html.escape(document.metadata.language)}</dc:language>
{creator}    <meta property="dcterms:modified">{modified}</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav" />
    <item id="css" href="styles/book.css" media-type="text/css" />
{chapter_manifest}
{image_manifest}
  </manifest>
  <spine>
{spine}
  </spine>
</package>
"""


class EpubBuilder:
    def build(self, document: BookDocument, project_root: Path, output: Path) -> EpubBuildResult:
        chapters = build_chapters(document)
        warnings = self._content_warnings(document, chapters)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", delete=False
            ) as handle:
                temporary = Path(handle.name)
            with zipfile.ZipFile(temporary, "w") as archive:
                archive.writestr(
                    zipfile.ZipInfo("mimetype"),
                    b"application/epub+zip",
                    compress_type=zipfile.ZIP_STORED,
                )
                archive.writestr("META-INF/container.xml", _container_xml())
                archive.writestr(
                    "EPUB/package.opf",
                    _package_opf(document, [chapter.file_name for chapter in chapters]),
                )
                archive.writestr(
                    "EPUB/nav.xhtml",
                    _nav_xhtml(
                        document.metadata.title,
                        document.metadata.language,
                        [(chapter.title, chapter.file_name) for chapter in chapters],
                    ),
                )
                archive.writestr("EPUB/styles/book.css", BOOK_CSS)
                for chapter in chapters:
                    archive.writestr(
                        f"EPUB/text/{chapter.file_name}",
                        chapter_xhtml(chapter, document.metadata.language),
                    )
                for asset in document.assets.values():
                    source = project_root.joinpath(*PurePosixPath(asset.relative_path).parts)
                    if not source.is_file():
                        raise EpubBuildError(f"Missing project asset: {asset.id}")
                    archive.write(source, f"EPUB/images/{PurePosixPath(asset.relative_path).name}")
            os.replace(temporary, output)
        except EpubBuildError:
            raise
        except Exception as exc:
            raise EpubBuildError(f"Could not build EPUB: {type(exc).__name__}: {exc}") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return EpubBuildResult(
            output_path=str(output.resolve()), chapter_count=len(chapters), warnings=warnings
        )

    @staticmethod
    def _content_warnings(document: BookDocument, chapters: list[Chapter]) -> list[str]:
        warnings: list[str] = []
        ids = [
            block.id
            for page in document.pages
            for block in page.blocks
            if isinstance(block, (ParagraphBlock, HeadingBlock))
        ]
        if len(ids) != len(set(ids)):
            warnings.append("Duplicate source block IDs were detected")
        combined = "\n".join(chapter.body_html for chapter in chapters)
        for page in document.pages:
            for block in page.blocks:
                if (
                    isinstance(block, (ParagraphBlock, HeadingBlock))
                    and combined.count(f'id="{block.id}"') != 1
                ):
                    warnings.append(f"Block {block.id} was not serialized exactly once")
        return warnings

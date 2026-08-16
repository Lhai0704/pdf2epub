from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree

from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.epub.builder import EpubBuilder
from pdf2epub.epub.validator import EpubValidator


def test_epub_structure_and_epubcheck(fixture_corpus: Path, tmp_path: Path) -> None:
    workflow = BookWorkflow()
    project = workflow.create_project(
        tmp_path / "epub.bepub-project", fixture_corpus / "digital_image_caption.pdf"
    )
    project, _ = workflow.parse_all(project)
    output = tmp_path / "book.epub"
    result = EpubBuilder().build(project.document, Path(project.root), output)
    assert result.warnings == []
    with zipfile.ZipFile(output) as archive:
        entries = archive.infolist()
        assert entries[0].filename == "mimetype"
        assert entries[0].compress_type == zipfile.ZIP_STORED
        assert archive.read("mimetype") == b"application/epub+zip"
        ElementTree.fromstring(archive.read("META-INF/container.xml"))
        ElementTree.fromstring(archive.read("EPUB/package.opf"))
        ElementTree.fromstring(archive.read("EPUB/nav.xhtml"))
        chapter = ElementTree.fromstring(archive.read("EPUB/text/chapter-001.xhtml"))
        assert chapter.tag.endswith("html")
        image_names = [name for name in archive.namelist() if name.startswith("EPUB/images/")]
        assert len(image_names) == 1

    jar = Path(__file__).parents[2] / ".tools" / "epubcheck-5.3.0" / "epubcheck.jar"
    report = EpubValidator(jar).validate(output)
    assert report.passed, report.output
    assert report.errors == 0

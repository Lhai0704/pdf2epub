from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.domain.models import ParagraphBlock
from pdf2epub.epub.builder import EpubBuilder, EpubBuildOptions
from pdf2epub.epub.validator import EpubValidator
from pdf2epub.translation.fake import FakeTranslator
from pdf2epub.translation.service import TranslationService

XHTML = "{http://www.w3.org/1999/xhtml}"


def test_source_translation_epub_order_languages_and_epubcheck(
    fixture_corpus: Path, tmp_path: Path
) -> None:
    workflow = BookWorkflow()
    project = workflow.create_project(
        tmp_path / "bilingual.bepub-project",
        fixture_corpus / "digital_single_column.pdf",
    )
    project, _ = workflow.parse_all(project)
    paragraph_ids = [
        block.id
        for page in project.document.pages
        for block in page.blocks
        if isinstance(block, ParagraphBlock)
    ]
    fake = FakeTranslator()
    translated = asyncio.run(
        TranslationService(fake, store=workflow.store).translate_selection(project, paragraph_ids)
    )
    calls = fake.call_count
    output = tmp_path / "bilingual.epub"
    build = EpubBuilder().build(
        translated.project.document,
        Path(translated.project.root),
        output,
        options=EpubBuildOptions(mode="source_translation"),
    )
    assert build.warnings == []
    assert fake.call_count == calls

    with zipfile.ZipFile(output) as archive:
        chapter = ElementTree.fromstring(archive.read("EPUB/text/chapter-001.xhtml"))
        wrappers = chapter.findall(f".//{XHTML}div[@class='para']")
        assert len(wrappers) == len(paragraph_ids)
        assert len({wrapper.attrib["id"] for wrapper in wrappers}) == len(wrappers)
        for wrapper in wrappers:
            children = list(wrapper)
            assert children[0].attrib == {"class": "source", "lang": "en"}
            assert children[1].attrib == {"class": "translation", "lang": "zh-CN"}
        package = archive.read("EPUB/package.opf").decode("utf-8")
        assert "<dc:language>en</dc:language>" in package
        assert "<dc:language>zh-CN</dc:language>" in package

    jar = Path(__file__).parents[2] / ".tools" / "epubcheck-5.3.0" / "epubcheck.jar"
    report = EpubValidator(jar).validate(output)
    assert report.passed, report.output
    assert report.errors == 0


def test_incomplete_bilingual_export_omits_invalid_translation_and_warns(
    fixture_corpus: Path, tmp_path: Path
) -> None:
    workflow = BookWorkflow()
    project = workflow.create_project(
        tmp_path / "incomplete.bepub-project",
        fixture_corpus / "digital_single_column.pdf",
    )
    project, _ = workflow.parse_all(project)
    output = tmp_path / "incomplete.epub"
    build = EpubBuilder().build(
        project.document,
        Path(project.root),
        output,
        options=EpubBuildOptions(mode="source_translation"),
    )
    assert len(build.warnings) == 1
    assert "Bilingual content incomplete" in build.warnings[0]
    with zipfile.ZipFile(output) as archive:
        chapter = ElementTree.fromstring(archive.read("EPUB/text/chapter-001.xhtml"))
        assert chapter.findall(f".//{XHTML}p[@class='translation']") == []

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.domain.models import HeadingBlock, ParagraphBlock
from pdf2epub.gui.main_window import MainWindow


@pytest.mark.gui
def test_gui_open_edit_preview_and_export(
    qtbot: QtBot, fixture_corpus: Path, tmp_path: Path
) -> None:
    workflow = BookWorkflow()
    project = workflow.create_project(
        tmp_path / "gui.bepub-project", fixture_corpus / "digital_single_column.pdf"
    )
    project, _ = workflow.parse_page(project, 0)
    jar = Path(__file__).parents[2] / ".tools" / "epubcheck-5.3.0" / "epubcheck.jar"
    window = MainWindow(project, workflow=workflow, epubcheck_jar=jar)
    qtbot.addWidget(window)
    window.show()

    qtbot.waitUntil(lambda: window.block_list.count() >= 2, timeout=5000)
    assert window.page_list.count() == 1
    assert window.block_list.count() >= 2

    text_row = next(
        row
        for row, block in enumerate(window._current_page().blocks)
        if isinstance(block, (ParagraphBlock, HeadingBlock))
    )
    window.block_list.setCurrentRow(text_row)
    original = window.text_editor.toPlainText()
    window.text_editor.setPlainText(f"{original} GUI edit")
    with qtbot.waitSignal(window.document_changed, timeout=2000):
        window.apply_edit()
    assert "GUI edit" in window.preview.toPlainText()

    output = tmp_path / "gui.epub"
    with qtbot.waitSignal(window.export_finished, timeout=15000) as blocker:
        window.export_to(output)
    assert blocker.args[0] is True
    assert output.is_file()


@pytest.mark.gui
def test_hundred_page_project_is_lazy(qtbot: QtBot, fixture_corpus: Path, tmp_path: Path) -> None:
    workflow = BookWorkflow()
    project = workflow.create_project(
        tmp_path / "hundred.bepub-project", fixture_corpus / "digital_100_pages.pdf"
    )
    window = MainWindow(project, workflow=workflow)
    qtbot.addWidget(window)
    window.show()
    assert window.page_list.count() == 100
    qtbot.waitUntil(lambda: window.status_label.text() == "Page 1 ready", timeout=5000)
    assert sum(page.parse_status == "parsed" for page in window.project.document.pages) <= 1
    with qtbot.waitSignal(window.page_loaded, timeout=5000):
        window.page_list.setCurrentRow(50)
    assert window.current_page_index == 50
    assert sum(page.parse_status == "parsed" for page in window.project.document.pages) <= 2

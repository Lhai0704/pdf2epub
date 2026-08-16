from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.domain.errors import Pdf2EpubError
from pdf2epub.gui.main_window import MainWindow


def run_gui(project_path: Path, source_path: Path | None, epubcheck_jar: Path | None) -> int:
    application = QApplication.instance() or QApplication(sys.argv)
    workflow = BookWorkflow()
    try:
        if (project_path / "project.json").is_file():
            project = workflow.load_project(project_path)
        elif source_path is not None:
            project = workflow.create_project(project_path, source_path)
        else:
            raise ValueError("A new project requires --source")
    except (Pdf2EpubError, ValueError) as exc:
        QMessageBox.critical(None, "pdf2epub", str(exc))
        return 2
    window = MainWindow(project, workflow=workflow, epubcheck_jar=epubcheck_jar)
    window.show()
    return application.exec()

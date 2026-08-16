from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pdf2epub.application.editing import DocumentEditor
from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.domain.models import (
    BookDocument,
    HeadingBlock,
    ImageBlock,
    LoadedProject,
    Page,
    ParagraphBlock,
)
from pdf2epub.epub.builder import EpubBuilder, EpubBuildOptions
from pdf2epub.epub.validator import EpubValidator
from pdf2epub.epub.xhtml import preview_html
from pdf2epub.gui.page_view import PdfPageView
from pdf2epub.gui.translation_view import TranslationView
from pdf2epub.gui.workers import AsyncProgressWorker, FunctionWorker
from pdf2epub.translation.base import BatchItemResult, BatchTranslationResult, Translator
from pdf2epub.translation.providers.longcat import LONGCAT_ENDPOINT, LongCatProvider
from pdf2epub.translation.service import TranslationService


@dataclass(frozen=True, slots=True)
class PageLoadResult:
    project: LoadedProject
    image_path: str
    page_index: int


@dataclass(frozen=True, slots=True)
class ExportResult:
    project: LoadedProject
    passed: bool
    message: str


class MainWindow(QMainWindow):
    page_loaded = Signal(int)
    document_changed = Signal()
    export_finished = Signal(bool, str)

    def __init__(
        self,
        project: LoadedProject,
        *,
        workflow: BookWorkflow | None = None,
        epubcheck_jar: Path | None = None,
        translator_factory: Callable[[], Translator] | None = None,
        require_translation_consent: bool = True,
        confirm_incomplete_export: bool = True,
    ) -> None:
        super().__init__()
        self.project = project
        self.workflow = workflow or BookWorkflow()
        self.editor_service = DocumentEditor()
        self.epubcheck_jar = epubcheck_jar
        self.translator_factory = translator_factory or LongCatProvider
        self.require_translation_consent = require_translation_consent
        self.confirm_incomplete_export = confirm_incomplete_export
        self.thread_pool = QThreadPool.globalInstance()
        self.cancel_event = threading.Event()
        self.current_page_index = 0
        self.current_block_id: str | None = None
        self._page_loading = False
        self._pending_page_index: int | None = None
        self._active_workers: set[FunctionWorker | AsyncProgressWorker] = set()
        self.setWindowTitle(f"pdf2epub — {project.document.metadata.title}")
        self.resize(1280, 800)
        self._build_ui()
        self._refresh_page_list()
        self.translation_view.refresh(self.project.document)
        self._refresh_preview()
        if self.project.document.pages:
            self.page_list.setCurrentRow(0)

    def _build_ui(self) -> None:
        central = QWidget()
        root_layout = QVBoxLayout(central)
        splitter = QSplitter()
        self.page_list = QListWidget()
        self.page_list.setObjectName("pageList")
        self.page_list.currentRowChanged.connect(self.load_page)
        splitter.addWidget(self.page_list)

        self.page_view = PdfPageView()
        self.page_view.setObjectName("pdfPageView")
        self.page_view.block_clicked.connect(self._select_block_by_id)
        splitter.addWidget(self.page_view)

        self.tabs = QTabWidget()
        self.structure_widget = self._structure_tab()
        self.tabs.addTab(self.structure_widget, "Structure")
        self.translation_view = TranslationView()
        self.translation_view.translate_requested.connect(self.translate_paragraphs)
        self.translation_view.retry_requested.connect(self.translate_paragraphs)
        self.translation_view.translation_edit_requested.connect(self.apply_translation_edit)
        self.translation_view.languages_changed.connect(self.apply_languages)
        self.tabs.addTab(self.translation_view, "Translation")
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.preview.setObjectName("epubPreview")
        self.tabs.addTab(self.preview, "EPUB Preview")
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setObjectName("logs")
        self.tabs.addTab(self.logs, "Logs")
        splitter.addWidget(self.tabs)
        splitter.setSizes([190, 590, 500])
        root_layout.addWidget(splitter)

        status_row = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_event.set)
        self.export_button = QPushButton("Export EPUB…")
        self.export_button.clicked.connect(self._choose_export)
        self.save_button = QPushButton("Save Project")
        self.save_button.clicked.connect(self.save_project)
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.progress)
        status_row.addWidget(self.cancel_button)
        status_row.addWidget(self.save_button)
        status_row.addWidget(self.export_button)
        root_layout.addLayout(status_row)
        self.setCentralWidget(central)

    def _structure_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.block_list = QListWidget()
        self.block_list.setObjectName("blockList")
        self.block_list.currentRowChanged.connect(self._block_selected)
        layout.addWidget(self.block_list, 2)
        self.text_editor = QTextEdit()
        self.text_editor.setObjectName("textEditor")
        layout.addWidget(self.text_editor, 1)
        form = QFormLayout()
        self.type_combo = QComboBox()
        self.type_combo.addItems(["paragraph", "heading"])
        self.heading_level = QSpinBox()
        self.heading_level.setRange(1, 6)
        form.addRow("Block type", self.type_combo)
        form.addRow("Heading level", self.heading_level)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        apply_button = QPushButton("Apply Edit")
        apply_button.clicked.connect(self.apply_edit)
        merge_button = QPushButton("Merge Next")
        merge_button.clicked.connect(self.merge_next)
        split_button = QPushButton("Split at Cursor")
        split_button.clicked.connect(self.split_at_cursor)
        buttons.addWidget(apply_button)
        buttons.addWidget(merge_button)
        buttons.addWidget(split_button)
        layout.addLayout(buttons)
        return widget

    def _refresh_page_list(self) -> None:
        selected = self.page_list.currentRow()
        self.page_list.blockSignals(True)
        self.page_list.clear()
        for page in self.project.document.pages:
            quality = page.quality.status if page.quality else "unknown"
            status = "Native" if quality == "usable" else "Suspect/Unsupported"
            marker = "✓" if page.parse_status == "parsed" else "…"
            item = QListWidgetItem(f"{page.page_index + 1:4d}  {status} {marker}")
            item.setData(256, page.page_index)
            self.page_list.addItem(item)
        if 0 <= selected < self.page_list.count():
            self.page_list.setCurrentRow(selected)
        self.page_list.blockSignals(False)

    def load_page(self, row: int) -> None:
        if row < 0 or row >= len(self.project.document.pages):
            return
        page_index = self.project.document.pages[row].page_index
        self.current_page_index = page_index
        if self._page_loading:
            self._pending_page_index = page_index
            self.status_label.setText(f"Page {page_index + 1} queued…")
            return
        self._begin_page_load(page_index)

    def _begin_page_load(self, page_index: int) -> None:
        self._page_loading = True
        self.status_label.setText(f"Loading page {page_index + 1}…")
        self.progress.setRange(0, 0)

        def task() -> PageLoadResult:
            project, _ = self.workflow.parse_page(self.project, page_index)
            image = self.workflow.render_page(project, page_index)
            return PageLoadResult(project, str(image), page_index)

        self._start_worker(task, self._page_ready)

    def _page_ready(self, result: object) -> None:
        if not isinstance(result, PageLoadResult):
            raise TypeError("Unexpected page worker result")
        self.project = result.project
        self._page_loading = False
        if self._pending_page_index is not None:
            pending = self._pending_page_index
            self._pending_page_index = None
            self._begin_page_load(pending)
            return
        if result.page_index != self.current_page_index:
            return
        page = next(
            page for page in result.project.document.pages if page.page_index == result.page_index
        )
        self.page_view.show_page(result.image_path, page)
        self._refresh_blocks()
        self._refresh_page_list()
        self.translation_view.refresh(self.project.document)
        self._refresh_preview()
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.status_label.setText(f"Page {result.page_index + 1} ready")
        self.page_loaded.emit(result.page_index)

    def _refresh_blocks(self) -> None:
        page = self._current_page()
        self.block_list.blockSignals(True)
        self.block_list.clear()
        for block in page.blocks:
            if isinstance(block, ImageBlock):
                label = f"[image] {block.asset_id}"
            else:
                label = f"[{block.type}] {block.effective_text[:70]}"
            item = QListWidgetItem(label)
            item.setData(256, block.id)
            self.block_list.addItem(item)
        self.block_list.blockSignals(False)
        if self.block_list.count():
            self.block_list.setCurrentRow(0)

    def _block_selected(self, row: int) -> None:
        if row < 0:
            return
        item = self.block_list.item(row)
        if item is None:
            return
        self.current_block_id = str(item.data(256))
        block = next(
            block for block in self._current_page().blocks if block.id == self.current_block_id
        )
        self.page_view.select_block(block.id)
        if isinstance(block, ImageBlock):
            self.text_editor.setPlainText("")
            self.text_editor.setEnabled(False)
            return
        self.text_editor.setEnabled(True)
        self.text_editor.setPlainText(block.effective_text)
        self.type_combo.setCurrentText(block.type)
        self.heading_level.setValue(block.level if isinstance(block, HeadingBlock) else 1)

    def _select_block_by_id(self, block_id: str) -> None:
        for row in range(self.block_list.count()):
            if str(self.block_list.item(row).data(256)) == block_id:
                self.block_list.setCurrentRow(row)
                break

    def apply_edit(self) -> None:
        if self.current_block_id is None:
            return
        document = self.editor_service.edit_text(
            self.project.document,
            self.current_page_index,
            self.current_block_id,
            self.text_editor.toPlainText(),
        )
        document = self.editor_service.change_type(
            document,
            self.current_page_index,
            self.current_block_id,
            self.type_combo.currentText(),
            self.heading_level.value(),
        )
        self._commit_document(document, self.current_block_id)

    def merge_next(self) -> None:
        if self.current_block_id is None:
            return
        document = self.editor_service.merge_adjacent(
            self.project.document, self.current_page_index, self.current_block_id
        )
        previous_ids = {block.id for block in self._current_page().blocks}
        new_page = next(
            page for page in document.pages if page.page_index == self.current_page_index
        )
        merged_id = next(block.id for block in new_page.blocks if block.id not in previous_ids)
        self._commit_document(document, merged_id)

    def split_at_cursor(self) -> None:
        if self.current_block_id is None:
            return
        offset = self.text_editor.textCursor().position()
        document = self.editor_service.split_block(
            self.project.document, self.current_page_index, self.current_block_id, offset
        )
        previous_ids = {block.id for block in self._current_page().blocks}
        new_page = next(
            page for page in document.pages if page.page_index == self.current_page_index
        )
        first_new = next(block.id for block in new_page.blocks if block.id not in previous_ids)
        self._commit_document(document, first_new)

    def _commit_document(self, document: BookDocument, select_id: str) -> None:
        project = self.project.model_copy(update={"document": document})
        self.project = self.workflow.store.save(project)
        self._refresh_blocks()
        self._select_block_by_id(select_id)
        self._refresh_preview()
        self.translation_view.refresh(self.project.document)
        self.document_changed.emit()
        self.status_label.setText("Project saved")

    def save_project(self) -> None:
        self.project = self.workflow.store.save(self.project)
        self.status_label.setText("Project saved")

    def apply_translation_edit(self, paragraph_id: str, text: str) -> None:
        try:
            document = self.editor_service.edit_translation(
                self.project.document, paragraph_id, text
            )
        except (KeyError, ValueError) as exc:
            QMessageBox.warning(self, "pdf2epub", str(exc))
            return
        self._commit_document(document, self.current_block_id or paragraph_id)

    def apply_languages(self, source_language: str, target_language: str) -> None:
        settings = self.project.document.translation_settings.model_copy(
            update={"target_language": target_language}
        )
        try:
            document = self.editor_service.update_translation_settings(
                self.project.document,
                source_language=source_language,
                settings=settings,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "pdf2epub", str(exc))
            return
        self._commit_document(document, self.current_block_id or "")

    def translate_paragraphs(self, paragraph_ids: list[str]) -> None:
        if not paragraph_ids:
            return
        if self._page_loading:
            self.status_label.setText("Wait for the current page to finish loading")
            return
        settings = self.project.document.translation_settings
        if self.require_translation_consent and settings.remote_consent_at is None:
            answer = QMessageBox.question(
                self,
                "Send text to LongCat?",
                "The selected paragraph, its adjacent paragraphs, chapter heading, glossary, "
                f"and style instructions will be sent to {LONGCAT_ENDPOINT}. "
                "Network retries may cause duplicate billing. Continue?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            settings = settings.model_copy(update={"remote_consent_at": datetime.now(UTC)})
            document = self.project.document.model_copy(update={"translation_settings": settings})
            self.project = self.workflow.store.save(
                self.project.model_copy(update={"document": document})
            )

        self.cancel_event.clear()
        self.cancel_button.setEnabled(True)
        self.translation_view.set_busy(True)
        self.structure_widget.setEnabled(False)
        self.save_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.page_list.setEnabled(False)
        self.progress.setRange(0, len(paragraph_ids))
        self.progress.setValue(0)
        self.status_label.setText("Translating selected paragraphs…")
        for paragraph_id in paragraph_ids:
            self.translation_view.set_task_status(paragraph_id, "queued")

        batch_project = self.project

        async def task(
            progress: Callable[[int, int, object], None],
        ) -> BatchTranslationResult:
            translator = self.translator_factory()
            service = TranslationService(translator, store=self.workflow.store)
            try:
                return await service.translate_selection(
                    batch_project,
                    paragraph_ids,
                    progress=lambda current, total, item: progress(current, total, item),
                    cancelled=self.cancel_event.is_set,
                )
            finally:
                if isinstance(translator, LongCatProvider):
                    await translator.aclose()

        worker = AsyncProgressWorker(task)
        self._active_workers.add(worker)
        worker.signals.progress.connect(self._translation_progress)

        def finished(result: object) -> None:
            self._active_workers.discard(worker)
            self._translation_ready(result)

        def failed(message: str) -> None:
            self._active_workers.discard(worker)
            self._operation_failed(message)

        worker.signals.finished.connect(finished)
        worker.signals.error.connect(failed)
        self.thread_pool.start(worker)

    def _translation_progress(self, current: int, total: int, item: object) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(current)
        if isinstance(item, BatchItemResult):
            if item.status in {"queued", "translating"}:
                self.translation_view.set_task_status(item.paragraph_id, item.status)
            self.status_label.setText(
                f"Translation {current}/{total}: {item.status} ({item.paragraph_id})"
            )

    def _translation_ready(self, result: object) -> None:
        if not isinstance(result, BatchTranslationResult):
            raise TypeError("Unexpected translation worker result")
        self.project = result.project
        self.translation_view.clear_task_statuses()
        self.cancel_button.setEnabled(False)
        self.translation_view.set_busy(False)
        self.structure_widget.setEnabled(True)
        self.save_button.setEnabled(True)
        self.export_button.setEnabled(True)
        self.page_list.setEnabled(True)
        self.translation_view.refresh(self.project.document)
        self._refresh_preview()
        message = (
            f"Translation finished: {result.translated_count} translated, "
            f"{result.cache_hit_count} cache hits, {result.failed_count} failed"
        )
        if result.cancelled:
            message += "; cancelled"
        if result.fatal_error:
            message += f"; {result.fatal_error}"
        self.status_label.setText(message)
        self.logs.appendPlainText(message)
        self.document_changed.emit()

    def _refresh_preview(self) -> None:
        project_uri = Path(self.project.root).resolve().as_uri()
        self.preview.setHtml(preview_html(self.project.document, project_uri))

    def _choose_export(self) -> None:
        safe_title = re.sub(r"[^A-Za-z0-9._-]+", "-", self.project.document.metadata.title).strip(
            "-"
        )
        default = Path(self.project.root) / "exports" / f"{safe_title or 'book'}.epub"
        selected, _ = QFileDialog.getSaveFileName(
            self, "Export EPUB", str(default), "EPUB (*.epub)"
        )
        if selected:
            self.export_to(Path(selected))

    def export_to(self, output: Path) -> None:
        incomplete = sum(
            isinstance(block, ParagraphBlock)
            and (
                block.translation is None
                or block.translation.status not in {"translated", "user_edited"}
            )
            for page in self.project.document.pages
            for block in page.blocks
        )
        unparsed_pages = sum(page.parse_status != "parsed" for page in self.project.document.pages)
        if (incomplete or unparsed_pages) and self.confirm_incomplete_export:
            answer = QMessageBox.question(
                self,
                "Incomplete bilingual content",
                f"{incomplete} paragraphs do not have a valid translation. "
                f"{unparsed_pages} pages are not parsed and may add untranslated paragraphs. "
                "Export a valid but incomplete bilingual EPUB anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.cancel_event.clear()
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 0)
        self.status_label.setText("Parsing remaining pages and exporting…")

        def task() -> ExportResult:
            project, _ = self.workflow.parse_all(self.project, cancelled=self.cancel_event.is_set)
            if self.cancel_event.is_set():
                return ExportResult(project, False, "Export cancelled")
            build = EpubBuilder().build(
                project.document,
                Path(project.root),
                output,
                options=EpubBuildOptions(mode="source_translation"),
            )
            report = EpubValidator(self.epubcheck_jar).validate(output)
            message = (
                f"EPUB validation: {'PASS' if report.passed else 'FAILED'} — "
                f"{report.errors} errors, {report.warnings} warnings"
            )
            if build.warnings:
                message += f"; {len(build.warnings)} content warnings"
            return ExportResult(project, report.passed, message)

        self._start_worker(task, self._export_ready)

    def _export_ready(self, result: object) -> None:
        if not isinstance(result, ExportResult):
            raise TypeError("Unexpected export worker result")
        self.project = result.project
        self.cancel_button.setEnabled(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self._refresh_page_list()
        self.translation_view.refresh(self.project.document)
        self._refresh_preview()
        self.status_label.setText(result.message)
        self.logs.appendPlainText(result.message)
        self.export_finished.emit(result.passed, result.message)

    def _start_worker(self, task: Callable[[], object], callback: Callable[[object], None]) -> None:
        worker = FunctionWorker(task)
        self._active_workers.add(worker)

        def finished(result: object) -> None:
            self._active_workers.discard(worker)
            callback(result)

        def failed(message: str) -> None:
            self._active_workers.discard(worker)
            self._operation_failed(message)

        worker.signals.finished.connect(finished)
        worker.signals.error.connect(failed)
        self.thread_pool.start(worker)

    def _operation_failed(self, message: str) -> None:
        self._page_loading = False
        self._pending_page_index = None
        self.translation_view.clear_task_statuses()
        self.progress.setRange(0, 1)
        self.cancel_button.setEnabled(False)
        self.translation_view.set_busy(False)
        self.structure_widget.setEnabled(True)
        self.save_button.setEnabled(True)
        self.export_button.setEnabled(True)
        self.page_list.setEnabled(True)
        self.status_label.setText("Operation failed")
        self.logs.appendPlainText(message)
        QMessageBox.critical(self, "pdf2epub", message)

    def _current_page(self) -> Page:
        return next(
            page
            for page in self.project.document.pages
            if page.page_index == self.current_page_index
        )

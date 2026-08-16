from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from pdf2epub.application.commands import CommandResult, StructureCommandService
from pdf2epub.application.editing import DocumentEditor
from pdf2epub.application.parsing import BatchParseSummary, ParseProgress, reparse_conflict
from pdf2epub.application.region_reparse import RegionCandidate, RegionReparseService
from pdf2epub.application.warnings import (
    acknowledge_warning,
    active_export_warnings,
    provenance_view,
)
from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.domain.errors import TranslationConflictError
from pdf2epub.domain.models import (
    BBox,
    BookDocument,
    CaptionBlock,
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
from pdf2epub.gui.provenance_inspector import ProvenanceInspector
from pdf2epub.gui.structure_workbench import StructureWorkbench
from pdf2epub.gui.translation_view import TranslationView
from pdf2epub.gui.warning_center import WarningCenter
from pdf2epub.gui.workers import AsyncProgressWorker, FunctionWorker, ProgressWorker
from pdf2epub.parsers.base import OcrParseOptions, ParseOptions
from pdf2epub.parsers.paddle_structure import (
    DETECTION_MODEL,
    LAYOUT_MODEL,
    RECOGNITION_MODELS,
    default_model_cache_root,
)
from pdf2epub.parsers.registry import OCR_PARSER_ID, ParserRouter
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


@dataclass(frozen=True, slots=True)
class PageBatchResult:
    project: LoadedProject
    summary: BatchParseSummary


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
        self.command_service = StructureCommandService(
            store=self.workflow.store,
            editor=self.editor_service,
        )
        self.region_service = RegionReparseService(
            self.workflow.registry,
            store=self.workflow.store,
        )
        self.epubcheck_jar = epubcheck_jar
        self.translator_factory = translator_factory or LongCatProvider
        self.require_translation_consent = require_translation_consent
        self.confirm_incomplete_export = confirm_incomplete_export
        self.thread_pool = QThreadPool.globalInstance()
        self.cancel_event = threading.Event()
        self.current_page_index = 0
        self.current_block_id: str | None = None
        self._current_image_path: str | None = None
        self._page_loading = False
        self._pending_page_index: int | None = None
        self._pending_block_selection: str | None = None
        self._active_workers: set[FunctionWorker | ProgressWorker | AsyncProgressWorker] = set()
        self.setWindowTitle(f"pdf2epub — {project.document.metadata.title}")
        self.resize(1280, 800)
        self._build_ui()
        self._refresh_page_list()
        self.translation_view.refresh(self.project.document)
        self.warning_center.refresh(self.project.document)
        self._refresh_preview()
        if self.project.document.pages:
            self.page_list.setCurrentRow(0)

    def _build_ui(self) -> None:
        central = QWidget()
        root_layout = QVBoxLayout(central)
        parser_row = QHBoxLayout()
        self.override_combo = QComboBox()
        self.override_combo.addItem("Auto", "auto")
        self.override_combo.addItem("Force Native", "native")
        self.override_combo.addItem("Force OCR", "paddle_ppstructure_v3")
        self.override_button = QPushButton("Apply Override")
        self.override_button.clicked.connect(self.apply_page_override)
        self.analyze_button = QPushButton("Analyze")
        self.analyze_button.clicked.connect(self.analyze_document)
        self.parse_button = QPushButton("Parse Selected")
        self.parse_button.clicked.connect(self.parse_selected_pages)
        self.reparse_button = QPushButton("Reparse")
        self.reparse_button.clicked.connect(self.reparse_selected_pages)
        self.retry_button = QPushButton("Retry Failed")
        self.retry_button.clicked.connect(self.retry_failed_pages)
        parser_row.addWidget(self.override_combo)
        parser_row.addWidget(self.override_button)
        parser_row.addWidget(self.analyze_button)
        parser_row.addWidget(self.parse_button)
        parser_row.addWidget(self.reparse_button)
        parser_row.addWidget(self.retry_button)
        parser_row.addStretch(1)
        root_layout.addLayout(parser_row)
        splitter = QSplitter()
        self.page_list = QListWidget()
        self.page_list.setObjectName("pageList")
        self.page_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.page_list.currentRowChanged.connect(self.load_page)
        splitter.addWidget(self.page_list)

        self.page_view = PdfPageView()
        self.page_view.setObjectName("pdfPageView")
        self.page_view.block_clicked.connect(self._select_block_by_id)
        self.page_view.region_selected.connect(self._region_selected)
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
        self.provenance_inspector = ProvenanceInspector()
        self.tabs.addTab(self.provenance_inspector, "Provenance")
        self.warning_center = WarningCenter()
        self.warning_center.navigate_requested.connect(self._navigate_warning)
        self.warning_center.acknowledge_requested.connect(self._acknowledge_warning)
        self.tabs.addTab(self.warning_center, "Warnings")
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

    def _structure_tab(self) -> StructureWorkbench:
        widget = StructureWorkbench()
        self.block_list = widget.block_list
        self.text_editor = widget.text_editor
        self.type_combo = widget.type_combo
        self.heading_level = widget.heading_level
        self.block_list.currentRowChanged.connect(self._block_selected)
        widget.apply_requested.connect(self.apply_edit)
        widget.merge_requested.connect(self.merge_next)
        widget.split_requested.connect(self.split_at_cursor)
        widget.undo_requested.connect(self.undo_structure)
        widget.redo_requested.connect(self.redo_structure)
        widget.region_requested.connect(self.begin_region_selection)
        return widget

    def _selected_page_indexes(self) -> list[int]:
        selected = [
            int(item.data(Qt.ItemDataRole.UserRole)) for item in self.page_list.selectedItems()
        ]
        if selected:
            return selected
        return [self.current_page_index] if self.project.document.pages else []

    def analyze_document(self) -> None:
        if self._active_workers:
            return
        self._set_parsing_busy(True, "Analyzing page signals…")

        def task() -> LoadedProject:
            return self.workflow.analyze_project(self.project)

        self._start_worker(task, self._analysis_ready)

    def _analysis_ready(self, result: object) -> None:
        if not isinstance(result, LoadedProject):
            raise TypeError("Unexpected analysis result")
        self.project = result
        self._clear_structure_history()
        self._set_parsing_busy(False, "Page classification updated")
        self._refresh_page_list()
        self.document_changed.emit()

    def apply_page_override(self) -> None:
        indexes = self._selected_page_indexes()
        if not indexes:
            return
        override = str(self.override_combo.currentData())
        if override not in {"auto", "native", "paddle_ppstructure_v3"}:
            raise ValueError(f"Unexpected parser override: {override}")
        self.project = self.workflow.set_page_override(
            self.project,
            indexes,
            override,  # type: ignore[arg-type]
        )
        self._clear_structure_history()
        self._refresh_page_list()
        self.status_label.setText(f"Updated parser override for {len(indexes)} page(s)")
        self.document_changed.emit()

    def parse_selected_pages(self) -> None:
        self._start_page_parse(self._selected_page_indexes(), reparse=False)

    def reparse_selected_pages(self) -> None:
        self._start_page_parse(self._selected_page_indexes(), reparse=True)

    def retry_failed_pages(self) -> None:
        indexes = [
            page.page_index
            for page in self.project.document.pages
            if page.parse_status == "failed" or page.parse_error is not None
        ]
        self._start_page_parse(indexes, reparse=False)

    def _parse_options_for(self, indexes: list[int]) -> ParseOptions | None:
        pages = {
            page.page_index: page
            for page in self.project.document.pages
            if page.page_index in indexes
        }
        needs_ocr = any(
            ParserRouter.parser_id_for_page(page) == OCR_PARSER_ID for page in pages.values()
        )
        if not needs_ocr:
            return ParseOptions()
        language = self.project.document.metadata.language.casefold()
        recognition = (
            RECOGNITION_MODELS["zh"] if language.startswith("zh") else RECOGNITION_MODELS["en"]
        )
        root = default_model_cache_root()
        models = [LAYOUT_MODEL, DETECTION_MODEL, recognition]
        missing = [model for model in models if not (root / "official_models" / model).is_dir()]
        allow_download = False
        if missing:
            answer = QMessageBox.question(
                self,
                "Download local OCR models?",
                "The selected pages require PaddleOCR models. The first run will download "
                f"approximately 218 MB of model weights to {root}. PDF content remains local. "
                f"Missing models: {', '.join(missing)}. Continue?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return None
            allow_download = True
        return OcrParseOptions(device="gpu:0", allow_model_download=allow_download)

    def _start_page_parse(
        self,
        indexes: list[int],
        *,
        reparse: bool,
        options: ParseOptions | None = None,
        conflicts_confirmed: bool = False,
    ) -> None:
        if not indexes or self._active_workers:
            return
        if reparse and not conflicts_confirmed:
            conflicts = [
                reparse_conflict(page)
                for page in self.project.document.pages
                if page.page_index in indexes
            ]
            edited = sum(item.user_edited_blocks for item in conflicts)
            derived = sum(item.derived_blocks for item in conflicts)
            translated = sum(item.translations for item in conflicts)
            if edited or derived or translated:
                answer = QMessageBox.question(
                    self,
                    "Replace parsed page content?",
                    f"Reparse will replace {edited} edited blocks, {derived} merged/split blocks, "
                    f"and remove {translated} active translations. Old raw/cache data is retained, "
                    "but translations are not inherited. Continue?",
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
                conflicts_confirmed = True
        options = options or self._parse_options_for(indexes)
        if options is None:
            return
        self.cancel_event.clear()
        self._set_parsing_busy(True, f"Parsing {len(indexes)} selected page(s)…")
        batch_project = self.project

        def task(report: Callable[[int, int, object], None]) -> PageBatchResult:
            project, summary = self.workflow.parse_pages(
                batch_project,
                indexes,
                options=options,
                progress=lambda event: report(event.current, event.total, event),
                cancelled=self.cancel_event.is_set,
                reparse=reparse,
                confirm_conflicts=conflicts_confirmed,
            )
            return PageBatchResult(project, summary)

        worker = ProgressWorker(task)
        self._active_workers.add(worker)
        worker.signals.progress.connect(self._page_parse_progress)

        def finished(result: object) -> None:
            self._active_workers.discard(worker)
            self._page_parse_ready(result)

        def failed(message: str) -> None:
            self._active_workers.discard(worker)
            self._operation_failed(message)

        worker.signals.finished.connect(finished)
        worker.signals.error.connect(failed)
        self.thread_pool.start(worker)

    def _page_parse_progress(self, current: int, total: int, item: object) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(max(current - 1, 0))
        if isinstance(item, ParseProgress):
            self.status_label.setText(
                f"Page {item.page_index + 1}: {item.stage} ({current}/{total})"
            )

    def _page_parse_ready(self, result: object) -> None:
        if not isinstance(result, PageBatchResult):
            raise TypeError("Unexpected page parse result")
        self.project = result.project
        self._clear_structure_history()
        summary = result.summary
        self._set_parsing_busy(False, "Page parsing finished")
        self._refresh_page_list()
        self.translation_view.refresh(self.project.document)
        self._refresh_preview()
        self._reload_current_page_view()
        self.document_changed.emit()
        message = (
            f"Parsing finished: {summary.parsed_count} parsed, {summary.cache_hits} cache hits, "
            f"{len(summary.failed_pages)} failed"
        )
        if summary.cancelled:
            message += "; cancelled after the current page"
        self.status_label.setText(message)
        self.logs.appendPlainText(message)
        oom_pages = [
            page.page_index
            for page in self.project.document.pages
            if page.page_index in summary.failed_pages
            and page.parse_error is not None
            and page.parse_error.code == "ocr_gpu_oom"
        ]
        if oom_pages:
            answer = QMessageBox.question(
                self,
                "GPU memory exhausted",
                "GPU OCR ran out of memory. Retry the affected pages on CPU? "
                "This can be much slower.",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._start_page_parse(
                    oom_pages,
                    reparse=False,
                    options=OcrParseOptions(device="cpu"),
                )

    def _set_parsing_busy(self, busy: bool, message: str) -> None:
        self.cancel_button.setEnabled(busy)
        self.override_button.setEnabled(not busy)
        self.analyze_button.setEnabled(not busy)
        self.parse_button.setEnabled(not busy)
        self.reparse_button.setEnabled(not busy)
        self.retry_button.setEnabled(not busy)
        self.override_combo.setEnabled(not busy)
        self.structure_widget.setEnabled(not busy)
        self.translation_view.set_busy(busy)
        self.save_button.setEnabled(not busy)
        self.export_button.setEnabled(not busy)
        self.page_list.setEnabled(not busy)
        if busy:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
        self.status_label.setText(message)

    def _refresh_page_list(self) -> None:
        selected = self.page_list.currentRow()
        self.page_list.blockSignals(True)
        self.page_list.clear()
        for page in self.project.document.pages:
            classification = page.classification
            kind = classification.kind if classification else "unknown"
            recommended = classification.recommended_parser if classification else "native"
            actual = page.parser_id or "none"
            warning_marker = f" warnings={len(page.parse_warnings)}" if page.parse_warnings else ""
            item = QListWidgetItem(
                f"{page.page_index + 1:4d} {kind} rec={recommended} "
                f"override={page.parser_override} actual={actual} "
                f"status={page.parse_status}{warning_marker}"
            )
            details = list(classification.reasons if classification else [])
            if page.parse_error is not None:
                details.append(f"{page.parse_error.code}: {page.parse_error.message}")
            details.extend(page.parse_warnings)
            item.setToolTip("\n".join(details))
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
            image = self.workflow.render_page(self.project, page_index)
            return PageLoadResult(self.project, str(image), page_index)

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
        self._current_image_path = result.image_path
        self.page_view.show_page(result.image_path, page)
        self._refresh_blocks()
        if self._pending_block_selection is not None:
            block_id = self._pending_block_selection
            self._pending_block_selection = None
            self._select_block_by_id(block_id)
        self._refresh_page_list()
        self.translation_view.refresh(self.project.document)
        self._refresh_preview()
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.status_label.setText(f"Page {result.page_index + 1} ready")
        self.page_loaded.emit(result.page_index)

    def _reload_current_page_view(self) -> None:
        if not self.project.document.pages:
            return
        if self._current_image_path is not None:
            self.page_view.show_page(self._current_image_path, self._current_page())
        self._refresh_blocks()

    def _refresh_blocks(self) -> None:
        page = self._current_page()
        self.block_list.blockSignals(True)
        self.block_list.clear()
        for block in page.blocks:
            if isinstance(block, ImageBlock):
                label = f"[image] {block.asset_id}"
            else:
                confidence = f" {block.confidence:.2f}" if block.confidence is not None else ""
                label = f"[{block.type}{confidence}] {block.effective_text[:70]}"
            item = QListWidgetItem(label)
            item.setData(256, block.id)
            self.block_list.addItem(item)
        self.block_list.blockSignals(False)
        self.warning_center.refresh(self.project.document)
        error = self.region_service.capability_error(page)
        self.structure_widget.region_button.setEnabled(error is None and not self._active_workers)
        self.structure_widget.region_button.setToolTip(error or "Reparse a selected OCR region")
        self._refresh_history_buttons()
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
        self.type_combo.setEnabled(not isinstance(block, CaptionBlock))
        self.heading_level.setEnabled(isinstance(block, HeadingBlock))
        self.heading_level.setValue(block.level if isinstance(block, HeadingBlock) else 1)
        self.provenance_inspector.show_provenance(provenance_view(self.project.document, block.id))

    def _select_block_by_id(self, block_id: str) -> None:
        for row in range(self.block_list.count()):
            if str(self.block_list.item(row).data(256)) == block_id:
                self.block_list.setCurrentRow(row)
                break

    def apply_edit(self) -> None:
        if self.current_block_id is None:
            return
        kwargs = {
            "text": self.text_editor.toPlainText(),
            "block_type": self.type_combo.currentText(),
            "heading_level": self.heading_level.value(),
        }
        try:
            result = self.command_service.execute_edit(
                self.project,
                self.current_page_index,
                self.current_block_id,
                **kwargs,  # type: ignore[arg-type]
            )
        except TranslationConflictError as exc:
            if not self._confirm_translation_loss(str(exc)):
                return
            result = self.command_service.execute_edit(
                self.project,
                self.current_page_index,
                self.current_block_id,
                **kwargs,  # type: ignore[arg-type]
                confirm_translation_loss=True,
            )
        self._accept_command_result(result)

    def merge_next(self) -> None:
        if self.current_block_id is None:
            return
        try:
            result = self.command_service.execute_merge(
                self.project, self.current_page_index, self.current_block_id
            )
        except TranslationConflictError as exc:
            if not self._confirm_translation_loss(str(exc)):
                return
            result = self.command_service.execute_merge(
                self.project,
                self.current_page_index,
                self.current_block_id,
                confirm_translation_loss=True,
            )
        self._accept_command_result(result)

    def split_at_cursor(self) -> None:
        if self.current_block_id is None:
            return
        offset = self.text_editor.textCursor().position()
        try:
            result = self.command_service.execute_split(
                self.project, self.current_page_index, self.current_block_id, offset
            )
        except TranslationConflictError as exc:
            if not self._confirm_translation_loss(str(exc)):
                return
            result = self.command_service.execute_split(
                self.project,
                self.current_page_index,
                self.current_block_id,
                offset,
                confirm_translation_loss=True,
            )
        self._accept_command_result(result)

    def undo_structure(self) -> None:
        try:
            result = self.command_service.undo(self.project)
        except (KeyError, ValueError) as exc:
            QMessageBox.warning(self, "pdf2epub", str(exc))
            self._clear_structure_history()
            return
        self._accept_command_result(result)

    def redo_structure(self) -> None:
        try:
            result = self.command_service.redo(self.project)
        except (KeyError, ValueError) as exc:
            QMessageBox.warning(self, "pdf2epub", str(exc))
            self._clear_structure_history()
            return
        self._accept_command_result(result)

    def _accept_command_result(self, result: CommandResult) -> None:
        self.project = result.project
        self._reload_current_page_view()
        if result.selected_block_id is not None:
            self._select_block_by_id(result.selected_block_id)
        self._refresh_preview()
        self.translation_view.refresh(self.project.document)
        self.warning_center.refresh(self.project.document)
        self._refresh_page_list()
        self.document_changed.emit()
        self.status_label.setText(f"Structure command saved ({result.translation_disposition})")

    def begin_region_selection(self) -> None:
        page = self._current_page()
        if error := self.region_service.capability_error(page):
            QMessageBox.information(self, "Region OCR unavailable", error)
            return
        self.page_view.set_region_selection_enabled(True)
        self.status_label.setText("Drag a rectangle covering at least half of an existing block")

    def _region_selected(self, x0: float, y0: float, x1: float, y1: float) -> None:
        if self._active_workers:
            return
        region = BBox(x0=x0, y0=y0, x1=x1, y1=y1)
        options = self._parse_options_for([self.current_page_index])
        if options is None:
            return
        batch_project = self.project
        page_index = self.current_page_index
        self.cancel_event.clear()
        self._set_parsing_busy(True, "Parsing selected OCR region…")

        def task() -> RegionCandidate:
            return self.region_service.build_candidate(
                batch_project,
                page_index,
                region,
                options=options,
                cancelled=self.cancel_event.is_set,
            )

        self._start_worker(task, self._region_candidate_ready)

    def _region_candidate_ready(self, result: object) -> None:
        if not isinstance(result, RegionCandidate):
            raise TypeError("Unexpected region candidate")
        self._set_parsing_busy(False, "Region OCR candidate ready")
        warning_text = f", {len(result.warnings)} warning(s)" if result.warnings else ""
        cache_text = "cache hit" if result.cache_hit else "new inference"
        current_page = self._current_page()
        candidate_page = next(
            page for page in result.document.pages if page.page_index == result.page_index
        )
        replaced = [block for block in current_page.blocks if block.id in result.replaced_block_ids]
        candidates = [
            block for block in candidate_page.blocks if block.id in result.candidate_block_ids
        ]
        diff = (
            "\n\nCurrent blocks:\n"
            + "\n".join(f"  - {self._region_block_summary(block)}" for block in replaced)
            + "\n\nCandidate blocks:\n"
            + "\n".join(f"  + {self._region_block_summary(block)}" for block in candidates)
        )
        answer = QMessageBox.question(
            self,
            "Replace selected region?",
            f"Replace {len(result.replaced_block_ids)} block(s) with "
            f"{len(result.candidate_block_ids)} candidate block(s) "
            f"({cache_text}{warning_text})? Existing translations are never matched automatically."
            f"{diff}",
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.status_label.setText("Region candidate discarded; project content unchanged")
            return
        try:
            committed = self.command_service.commit_region_candidate(
                self.project,
                result.document,
                page_index=result.page_index,
                command_id=result.command_id,
                region=result.region,
                selected_block_id=(
                    result.candidate_block_ids[0] if result.candidate_block_ids else None
                ),
            )
        except TranslationConflictError as exc:
            if not self._confirm_translation_loss(str(exc)):
                self.status_label.setText("Region candidate discarded; translations preserved")
                return
            committed = self.command_service.commit_region_candidate(
                self.project,
                result.document,
                page_index=result.page_index,
                command_id=result.command_id,
                region=result.region,
                selected_block_id=(
                    result.candidate_block_ids[0] if result.candidate_block_ids else None
                ),
                confirm_translation_loss=True,
            )
        self._accept_command_result(committed)

    @staticmethod
    def _region_block_summary(block: object) -> str:
        block_id = str(getattr(block, "id", "unknown"))
        block_type = str(getattr(block, "type", type(block).__name__))
        text = str(getattr(block, "effective_text", "")).replace("\n", " ").strip()
        if len(text) > 80:
            text = f"{text[:77]}..."
        detail = f': "{text}"' if text else ""
        return f"{block_type} {block_id}{detail}"

    def _navigate_warning(self, page_index: int, block_id: object) -> None:
        selected = str(block_id) if isinstance(block_id, str) else None
        self._pending_block_selection = selected
        for row in range(self.page_list.count()):
            if int(self.page_list.item(row).data(Qt.ItemDataRole.UserRole)) == page_index:
                if row == self.page_list.currentRow() and selected is not None:
                    self._select_block_by_id(selected)
                    self._pending_block_selection = None
                else:
                    self.page_list.setCurrentRow(row)
                break

    def _acknowledge_warning(self, warning_id: str) -> None:
        document = acknowledge_warning(self.project.document, warning_id)
        self.project = self.workflow.store.save(
            self.project.model_copy(update={"document": document})
        )
        self._clear_structure_history()
        self.warning_center.refresh(self.project.document)
        self._refresh_page_list()
        self.document_changed.emit()
        self.status_label.setText("Warning acknowledged; export semantics are unchanged")

    def _confirm_translation_loss(self, message: str) -> bool:
        answer = QMessageBox.question(
            self,
            "Detach translations?",
            f"{message}. Translation cache remains available and Undo restores the active "
            "record during this session. Continue?",
        )
        return answer == QMessageBox.StandardButton.Yes

    def _refresh_history_buttons(self) -> None:
        self.structure_widget.set_history_state(
            self.command_service.stack.can_undo,
            self.command_service.stack.can_redo,
        )

    def _clear_structure_history(self) -> None:
        self.command_service.clear()
        self._refresh_history_buttons()

    def _commit_document(self, document: BookDocument, select_id: str) -> None:
        project = self.project.model_copy(update={"document": document})
        self.project = self.workflow.store.save(project)
        self._clear_structure_history()
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
        self.override_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self.parse_button.setEnabled(False)
        self.reparse_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.override_combo.setEnabled(False)
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
        self._clear_structure_history()
        self.translation_view.clear_task_statuses()
        self.cancel_button.setEnabled(False)
        self.translation_view.set_busy(False)
        self.structure_widget.setEnabled(True)
        self.override_button.setEnabled(True)
        self.analyze_button.setEnabled(True)
        self.parse_button.setEnabled(True)
        self.reparse_button.setEnabled(True)
        self.retry_button.setEnabled(True)
        self.override_combo.setEnabled(True)
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
        incomplete_pages = [
            page
            for page in self.project.document.pages
            if page.parse_status != "parsed" or page.parse_warnings
        ]
        export_warnings = active_export_warnings(self.project.document)
        if (incomplete or incomplete_pages or export_warnings) and self.confirm_incomplete_export:
            answer = QMessageBox.question(
                self,
                "Incomplete bilingual content",
                f"{incomplete} paragraphs do not have a valid translation. "
                f"{len(incomplete_pages)} pages are unparsed, stale, failed, or have warnings. "
                f"{len(export_warnings)} active structured warnings affect export. "
                "Export a valid but incomplete bilingual EPUB anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.cancel_event.clear()
        self._set_parsing_busy(True, "Exporting current project content…")

        def task() -> ExportResult:
            project = self.project
            if self.cancel_event.is_set():
                return ExportResult(project, False, "Export cancelled")
            build = EpubBuilder().build(
                project.document,
                Path(project.root),
                output,
                options=EpubBuildOptions(
                    mode="source_translation",
                    include_incomplete_notice=bool(incomplete_pages or export_warnings),
                ),
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
        self._set_parsing_busy(False, result.message)
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
        self.override_button.setEnabled(True)
        self.analyze_button.setEnabled(True)
        self.parse_button.setEnabled(True)
        self.reparse_button.setEnabled(True)
        self.retry_button.setEnabled(True)
        self.override_combo.setEnabled(True)
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

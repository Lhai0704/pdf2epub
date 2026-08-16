from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pdf2epub.domain.models import BookDocument, ParagraphBlock


def _status(block: ParagraphBlock) -> str:
    return block.translation.status if block.translation is not None else "untranslated"


class TranslationView(QWidget):
    translate_requested = Signal(list)
    retry_requested = Signal(list)
    translation_edit_requested = Signal(str, str)
    languages_changed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.document: BookDocument | None = None
        self.current_paragraph_id: str | None = None
        self.task_statuses: dict[str, str] = {}
        layout = QVBoxLayout(self)

        language_form = QFormLayout()
        self.source_language = QLineEdit()
        self.source_language.setObjectName("sourceLanguage")
        self.target_language = QLineEdit()
        self.target_language.setObjectName("targetLanguage")
        language_form.addRow("Source language", self.source_language)
        language_form.addRow("Target language", self.target_language)
        layout.addLayout(language_form)
        language_row = QHBoxLayout()
        self.apply_languages_button = QPushButton("Apply Languages")
        self.apply_languages_button.clicked.connect(self._apply_languages)
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["all", "untranslated", "stale", "failed"])
        self.filter_combo.currentTextChanged.connect(self._populate)
        language_row.addWidget(self.apply_languages_button)
        language_row.addWidget(QLabel("Filter"))
        language_row.addWidget(self.filter_combo)
        layout.addLayout(language_row)

        self.paragraph_list = QListWidget()
        self.paragraph_list.setObjectName("translationParagraphList")
        self.paragraph_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.paragraph_list.currentItemChanged.connect(self._selection_changed)
        layout.addWidget(self.paragraph_list, 2)

        self.original_text = QPlainTextEdit()
        self.original_text.setObjectName("translationOriginal")
        self.original_text.setReadOnly(True)
        self.translation_text = QPlainTextEdit()
        self.translation_text.setObjectName("translationEditor")
        layout.addWidget(QLabel("Original"))
        layout.addWidget(self.original_text, 1)
        layout.addWidget(QLabel("Translation"))
        layout.addWidget(self.translation_text, 1)
        self.details = QLabel("Status: untranslated")
        self.details.setObjectName("translationDetails")
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.details)

        buttons = QHBoxLayout()
        self.translate_button = QPushButton("Translate Selected")
        self.translate_button.setObjectName("translateSelected")
        self.translate_button.clicked.connect(self._translate_selected)
        self.retry_button = QPushButton("Retry Failed/Stale")
        self.retry_button.clicked.connect(self._retry)
        self.apply_translation_button = QPushButton("Apply Translation Edit")
        self.apply_translation_button.clicked.connect(self._apply_translation)
        buttons.addWidget(self.translate_button)
        buttons.addWidget(self.retry_button)
        buttons.addWidget(self.apply_translation_button)
        layout.addLayout(buttons)

    def refresh(self, document: BookDocument) -> None:
        selected = self.current_paragraph_id
        self.document = document
        self.source_language.setText(document.metadata.language)
        self.target_language.setText(document.translation_settings.target_language)
        self._populate()
        if selected is not None:
            for row in range(self.paragraph_list.count()):
                item = self.paragraph_list.item(row)
                if str(item.data(Qt.ItemDataRole.UserRole)) == selected:
                    self.paragraph_list.setCurrentRow(row)
                    break

    def set_busy(self, busy: bool) -> None:
        for widget in (
            self.source_language,
            self.target_language,
            self.apply_languages_button,
            self.translate_button,
            self.retry_button,
            self.apply_translation_button,
        ):
            widget.setEnabled(not busy)

    def set_task_status(self, paragraph_id: str, status: str) -> None:
        self.task_statuses[paragraph_id] = status
        self._populate()

    def clear_task_statuses(self) -> None:
        self.task_statuses.clear()
        self._populate()

    def _paragraphs(self) -> list[tuple[int, ParagraphBlock]]:
        if self.document is None:
            return []
        return [
            (page.page_index, block)
            for page in sorted(self.document.pages, key=lambda value: value.page_index)
            for block in page.blocks
            if isinstance(block, ParagraphBlock)
        ]

    def _populate(self) -> None:
        selected_ids = {
            str(item.data(Qt.ItemDataRole.UserRole)) for item in self.paragraph_list.selectedItems()
        }
        current_filter = self.filter_combo.currentText()
        self.paragraph_list.blockSignals(True)
        self.paragraph_list.clear()
        for page_index, block in self._paragraphs():
            status = self.task_statuses.get(block.id, _status(block))
            if current_filter != "all" and status != current_filter:
                continue
            summary = " ".join(block.effective_text.split())[:70]
            item = QListWidgetItem(f"p.{page_index + 1} [{status}] {summary}")
            item.setData(Qt.ItemDataRole.UserRole, block.id)
            item.setSelected(block.id in selected_ids)
            self.paragraph_list.addItem(item)
        self.paragraph_list.blockSignals(False)
        if self.paragraph_list.count() and self.paragraph_list.currentRow() < 0:
            self.paragraph_list.setCurrentRow(0)

    def _selection_changed(self, current: QListWidgetItem | None) -> None:
        if current is None or self.document is None:
            return
        paragraph_id = str(current.data(Qt.ItemDataRole.UserRole))
        block = next(block for _, block in self._paragraphs() if block.id == paragraph_id)
        self.current_paragraph_id = paragraph_id
        self.original_text.setPlainText(block.effective_text)
        self.translation_text.setPlainText(
            (block.translation.text or "") if block.translation else ""
        )
        if block.translation is None:
            self.details.setText("Status: untranslated")
        else:
            error = (
                f" — {block.translation.error_message}" if block.translation.error_message else ""
            )
            self.details.setText(
                f"Status: {block.translation.status} — "
                f"{block.translation.provenance.provider_id}/"
                f"{block.translation.provenance.model}{error}"
            )

    def _selected_ids(self) -> list[str]:
        return [
            str(item.data(Qt.ItemDataRole.UserRole)) for item in self.paragraph_list.selectedItems()
        ]

    def _translate_selected(self) -> None:
        ids = self._selected_ids()
        if ids:
            self.translate_requested.emit(ids)

    def _retry(self) -> None:
        ids = [
            block.id
            for _, block in self._paragraphs()
            if block.translation is not None and block.translation.status in {"failed", "stale"}
        ]
        if ids:
            self.retry_requested.emit(ids)

    def _apply_translation(self) -> None:
        if self.current_paragraph_id is not None:
            self.translation_edit_requested.emit(
                self.current_paragraph_id, self.translation_text.toPlainText()
            )

    def _apply_languages(self) -> None:
        self.languages_changed.emit(
            self.source_language.text().strip(), self.target_language.text().strip()
        )

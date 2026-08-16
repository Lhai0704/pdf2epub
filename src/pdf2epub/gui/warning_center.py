from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pdf2epub.domain.models import BookDocument, ProjectWarning


class WarningCenter(QWidget):
    navigate_requested = Signal(int, object)
    acknowledge_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._document: BookDocument | None = None
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.state_filter = QComboBox()
        self.state_filter.addItems(["Active", "All"])
        self.severity_filter = QComboBox()
        self.severity_filter.addItems(["All severities", "info", "warning", "error"])
        self.source_filter = QComboBox()
        self.source_filter.addItems(
            ["All sources", "parser", "structure", "translation", "export", "region"]
        )
        self.state_filter.currentIndexChanged.connect(self._apply_filters)
        self.severity_filter.currentIndexChanged.connect(self._apply_filters)
        self.source_filter.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self.state_filter)
        filters.addWidget(self.severity_filter)
        filters.addWidget(self.source_filter)
        layout.addLayout(filters)
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("warningCenter")
        self.list_widget.itemDoubleClicked.connect(self._navigate)
        layout.addWidget(self.list_widget)
        row = QHBoxLayout()
        self.acknowledge_button = QPushButton("Acknowledge")
        self.acknowledge_button.clicked.connect(self._acknowledge)
        row.addWidget(self.acknowledge_button)
        row.addStretch(1)
        layout.addLayout(row)

    def refresh(self, document: BookDocument) -> None:
        self._document = document
        self._apply_filters()

    def _apply_filters(self) -> None:
        self.list_widget.clear()
        if self._document is None:
            return
        show_all = self.state_filter.currentText() == "All"
        severity = self.severity_filter.currentText()
        source = self.source_filter.currentText()
        for warning in sorted(
            self._document.warnings,
            key=lambda item: (not item.active, item.page_index or -1, item.created_at),
        ):
            if not show_all and not warning.active:
                continue
            if severity != "All severities" and warning.severity != severity:
                continue
            if source != "All sources" and warning.source != source:
                continue
            state = "active" if warning.active else "resolved"
            acknowledged = " acknowledged" if warning.acknowledged_at else ""
            page = (
                f"page {warning.page_index + 1}" if warning.page_index is not None else "document"
            )
            marker = " export" if warning.affects_export else ""
            item = QListWidgetItem(
                f"[{warning.severity}/{state}{acknowledged}{marker}] {page}: {warning.code}"
            )
            item.setToolTip(warning.message)
            item.setData(Qt.ItemDataRole.UserRole, warning)
            self.list_widget.addItem(item)

    def _selected(self) -> ProjectWarning | None:
        item = self.list_widget.currentItem()
        value = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return value if isinstance(value, ProjectWarning) else None

    def _navigate(self, item: QListWidgetItem) -> None:
        value = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(value, ProjectWarning) and value.page_index is not None:
            self.navigate_requested.emit(value.page_index, value.block_id)

    def _acknowledge(self) -> None:
        if (warning := self._selected()) is not None:
            self.acknowledge_requested.emit(warning.id)

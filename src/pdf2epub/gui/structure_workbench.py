from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QListWidget,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class StructureWorkbench(QWidget):
    apply_requested = Signal()
    merge_requested = Signal()
    split_requested = Signal()
    undo_requested = Signal()
    redo_requested = Signal()
    region_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.block_list = QListWidget()
        self.block_list.setObjectName("blockList")
        layout.addWidget(self.block_list, 2)
        self.text_editor = QTextEdit()
        self.text_editor.setObjectName("textEditor")
        layout.addWidget(self.text_editor, 1)
        form = QFormLayout()
        self.type_combo = QComboBox()
        self.type_combo.addItems(["paragraph", "heading", "page_header", "page_footer", "caption"])
        self.heading_level = QSpinBox()
        self.heading_level.setRange(1, 6)
        form.addRow("Block type", self.type_combo)
        form.addRow("Heading level", self.heading_level)
        layout.addLayout(form)

        row = QHBoxLayout()
        self.apply_button = QPushButton("Apply Edit")
        self.merge_button = QPushButton("Merge Next")
        self.split_button = QPushButton("Split at Cursor")
        self.apply_button.clicked.connect(self.apply_requested)
        self.merge_button.clicked.connect(self.merge_requested)
        self.split_button.clicked.connect(self.split_requested)
        row.addWidget(self.apply_button)
        row.addWidget(self.merge_button)
        row.addWidget(self.split_button)
        layout.addLayout(row)

        history = QHBoxLayout()
        self.undo_button = QPushButton("Undo")
        self.redo_button = QPushButton("Redo")
        self.region_button = QPushButton("Select OCR Region")
        self.undo_button.clicked.connect(self.undo_requested)
        self.redo_button.clicked.connect(self.redo_requested)
        self.region_button.clicked.connect(self.region_requested)
        history.addWidget(self.undo_button)
        history.addWidget(self.redo_button)
        history.addWidget(self.region_button)
        layout.addLayout(history)
        self.set_history_state(False, False)

    def set_history_state(self, can_undo: bool, can_redo: bool) -> None:
        self.undo_button.setEnabled(can_undo)
        self.redo_button.setEnabled(can_redo)

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QMouseEvent, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView

from pdf2epub.domain.models import Page


class PdfPageView(QGraphicsView):
    block_clicked = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHints(self.renderHints())
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._rectangles: dict[str, QGraphicsRectItem] = {}

    def show_page(self, image_path: str, page: Page) -> None:
        scene = self.scene()
        scene.clear()
        self._rectangles.clear()
        pixmap = QPixmap(image_path)
        self._pixmap_item = scene.addPixmap(pixmap)
        scale_x = pixmap.width() / page.width
        scale_y = pixmap.height() / page.height
        pen = QPen(QColor(35, 110, 220, 190), 1.5)
        brush = QBrush(QColor(35, 110, 220, 25))
        for block in page.blocks:
            rect = QGraphicsRectItem(
                block.bbox.x0 * scale_x,
                block.bbox.y0 * scale_y,
                (block.bbox.x1 - block.bbox.x0) * scale_x,
                (block.bbox.y1 - block.bbox.y0) * scale_y,
            )
            rect.setPen(pen)
            rect.setBrush(brush)
            rect.setData(0, block.id)
            rect.setZValue(2)
            scene.addItem(rect)
            self._rectangles[block.id] = rect
        scene.setSceneRect(scene.itemsBoundingRect())
        self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def select_block(self, block_id: str) -> None:
        for current_id, rectangle in self._rectangles.items():
            selected = current_id == block_id
            rectangle.setPen(
                QPen(
                    QColor(220, 60, 40, 230) if selected else QColor(35, 110, 220, 190),
                    3 if selected else 1.5,
                )
            )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        item = self.itemAt(event.position().toPoint())
        if item is not None and item.data(0):
            self.block_clicked.emit(str(item.data(0)))
        super().mousePressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
        self.scale(factor, factor)

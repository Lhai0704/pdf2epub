from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QMouseEvent, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView

from pdf2epub.domain.models import Page


class PdfPageView(QGraphicsView):
    block_clicked = Signal(str)
    region_selected = Signal(float, float, float, float)

    def __init__(self) -> None:
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHints(self.renderHints())
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._rectangles: dict[str, QGraphicsRectItem] = {}
        self._region_mode = False
        self._region_start: QPointF | None = None
        self._region_item: QGraphicsRectItem | None = None
        self._page_width = 1.0
        self._page_height = 1.0
        self._scale_x = 1.0
        self._scale_y = 1.0

    def show_page(self, image_path: str, page: Page) -> None:
        scene = self.scene()
        scene.clear()
        self._rectangles.clear()
        self._region_item = None
        pixmap = QPixmap(image_path)
        self._pixmap_item = scene.addPixmap(pixmap)
        scale_x = pixmap.width() / page.width
        scale_y = pixmap.height() / page.height
        self._page_width = page.width
        self._page_height = page.height
        self._scale_x = scale_x
        self._scale_y = scale_y
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
            confidence = (
                f"; confidence={block.confidence:.2f}" if block.confidence is not None else ""
            )
            warning = (
                "; low confidence"
                if block.confidence is not None and block.confidence < 0.5
                else ""
            )
            rect.setToolTip(f"{block.type}{confidence}{warning}")
            if block.confidence is not None and block.confidence < 0.5:
                rect.setPen(QPen(QColor(210, 130, 20, 220), 2))
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

    def set_region_selection_enabled(self, enabled: bool) -> None:
        self._region_mode = enabled
        self._region_start = None
        self.setDragMode(
            QGraphicsView.DragMode.NoDrag if enabled else QGraphicsView.DragMode.ScrollHandDrag
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._region_mode and event.button() == Qt.MouseButton.LeftButton:
            self._region_start = self.mapToScene(event.position().toPoint())
            if self._region_item is not None:
                self.scene().removeItem(self._region_item)
            self._region_item = QGraphicsRectItem()
            self._region_item.setPen(QPen(QColor(160, 50, 210, 230), 2, Qt.PenStyle.DashLine))
            self._region_item.setBrush(QBrush(QColor(160, 50, 210, 30)))
            self._region_item.setZValue(5)
            self.scene().addItem(self._region_item)
            event.accept()
            return
        item = self.itemAt(event.position().toPoint())
        if item is not None and item.data(0):
            self.block_clicked.emit(str(item.data(0)))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._region_mode and self._region_start is not None and self._region_item is not None:
            current = self.mapToScene(event.position().toPoint())
            self._region_item.setRect(
                min(self._region_start.x(), current.x()),
                min(self._region_start.y(), current.y()),
                abs(current.x() - self._region_start.x()),
                abs(current.y() - self._region_start.y()),
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._region_mode and self._region_start is not None:
            end = self.mapToScene(event.position().toPoint())
            x0 = max(0.0, min(self._region_start.x(), end.x()) / self._scale_x)
            y0 = max(0.0, min(self._region_start.y(), end.y()) / self._scale_y)
            x1 = min(self._page_width, max(self._region_start.x(), end.x()) / self._scale_x)
            y1 = min(self._page_height, max(self._region_start.y(), end.y()) / self._scale_y)
            self.set_region_selection_enabled(False)
            self._region_start = None
            if x1 > x0 and y1 > y0:
                self.region_selected.emit(x0, y0, x1, y1)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
        self.scale(factor, factor)

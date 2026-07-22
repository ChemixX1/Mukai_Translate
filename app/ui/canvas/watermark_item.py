from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsItem
from PySide6.QtGui import QPixmap, QCursor, QPainter, QPen, QColor, QBrush
from PySide6.QtCore import Qt, QPointF, QRectF, QLineF

from ..dayu_widgets.menu import MMenu


class WatermarkItem(QGraphicsPixmapItem):
    """A movable watermark image the user can place manually on a comic page.

    The item is freely draggable, selectable and can be removed with the
    Delete/Backspace key while selected. It keeps a reference to the source
    image path so the placement can be serialized into the viewer state and
    re-rendered on export.
    """

    # High z-value so the watermark always sits above the page and text items.
    Z_VALUE = 1000
    HANDLE_SIZE = 14.0
    MIN_SCALE = 0.03
    MAX_SCALE = 5.0

    def __init__(self, pixmap: QPixmap, source_path: str = "", parent=None):
        super().__init__(pixmap, parent)
        self.source_path = source_path
        self._drag_start_pos = None
        self._resize_start_scale = 1.0
        self._resize_start_distance = 1.0
        self._resize_center_scene = QPointF()

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        self.setTransformOriginPoint(self.boundingRect().center())
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)
        self.setZValue(self.Z_VALUE)

    def paint(self, painter: QPainter, option, widget=None):
        super().paint(painter, option, widget)
        if not self.isSelected():
            return

        painter.save()
        outline = QPen(QColor(41, 151, 255), 0)
        outline.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(outline)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.boundingRect())

        painter.setPen(QPen(QColor(255, 255, 255), 0))
        painter.setBrush(QBrush(QColor(41, 151, 255)))
        painter.drawRect(self._resize_handle_rect())
        painter.restore()

    def _notify_changed(self):
        scene = self.scene()
        if scene is None:
            return
        for view in scene.views():
            signal = getattr(view, "watermark_changed", None)
            if signal is not None:
                signal.emit()

    def _resize_handle_rect(self) -> QRectF:
        rect = self.boundingRect()
        size = min(self.HANDLE_SIZE, max(6.0, min(rect.width(), rect.height()) * 0.2))
        return QRectF(rect.right() - size, rect.bottom() - size, size, size)

    def is_resize_handle_at(self, scene_pos: QPointF) -> bool:
        if not self.isSelected():
            return False
        return self._resize_handle_rect().contains(self.mapFromScene(scene_pos))

    def init_resize(self, scene_pos: QPointF):
        self._resize_start_scale = self.scale()
        self._resize_center_scene = self.mapToScene(self.boundingRect().center())
        self._resize_start_distance = max(1.0, QLineF(self._resize_center_scene, scene_pos).length())

    def resize_from_scene(self, scene_pos: QPointF):
        distance = max(1.0, QLineF(self._resize_center_scene, scene_pos).length())
        factor = distance / self._resize_start_distance
        self.set_watermark_scale(self._resize_start_scale * factor, notify=False)

    def set_watermark_scale(self, scale: float, notify: bool = True):
        scale = max(self.MIN_SCALE, min(self.MAX_SCALE, float(scale)))
        if abs(self.scale() - scale) < 0.0001:
            return
        self.setScale(scale)
        self.update()
        if notify:
            self._notify_changed()

    def move_by_scene_delta(self, delta: QPointF):
        if delta.isNull():
            return

        scene = self.scene()
        new_pos = self.pos() + delta
        if scene is not None:
            scene_rect = scene.sceneRect()
            current_rect = self.mapToScene(self.boundingRect()).boundingRect()
            if current_rect.left() + delta.x() < scene_rect.left():
                new_pos.setX(self.pos().x() + scene_rect.left() - current_rect.left())
            elif current_rect.right() + delta.x() > scene_rect.right():
                new_pos.setX(self.pos().x() + scene_rect.right() - current_rect.right())

            if current_rect.top() + delta.y() < scene_rect.top():
                new_pos.setY(self.pos().y() + scene_rect.top() - current_rect.top())
            elif current_rect.bottom() + delta.y() > scene_rect.bottom():
                new_pos.setY(self.pos().y() + scene_rect.bottom() - current_rect.bottom())

        self.setPos(new_pos)

    def remove_from_scene(self):
        scene = self.scene()
        views = scene.views() if scene is not None else []
        if scene is not None:
            scene.removeItem(self)
        for view in views:
            watermarks = getattr(view, "watermark_items", None)
            if watermarks is not None and self in watermarks:
                watermarks.remove(self)
            signal = getattr(view, "watermark_changed", None)
            if signal is not None:
                signal.emit()

    def show_context_menu(self, global_pos, parent=None):
        view = parent
        self.setSelected(True)
        self.setFocus()
        menu = MMenu(parent=view)
        increase = menu.addAction(view.tr("Increase Size") if view is not None else "Increase Size")
        decrease = menu.addAction(view.tr("Decrease Size") if view is not None else "Decrease Size")
        reset = menu.addAction(view.tr("Reset Size") if view is not None else "Reset Size")
        delete = menu.addAction(view.tr("Delete") if view is not None else "Delete")

        increase.triggered.connect(lambda: self.set_watermark_scale(self.scale() * 1.15))
        decrease.triggered.connect(lambda: self.set_watermark_scale(self.scale() / 1.15))
        reset.triggered.connect(lambda: self.set_watermark_scale(1.0))
        delete.triggered.connect(self.remove_from_scene)
        menu.exec_(global_pos)

    def contextMenuEvent(self, event):
        views = self.scene().views() if self.scene() is not None else []
        parent = views[0] if views else None
        self.show_context_menu(event.screenPos(), parent)
        event.accept()

    def mousePressEvent(self, event):
        self._drag_start_pos = self.pos()
        self.setSelected(True)
        self.setFocus()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self._drag_start_pos is not None and self.pos() != self._drag_start_pos:
            self._notify_changed()
        self._drag_start_pos = None

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.remove_from_scene()
            event.accept()
            return
        super().keyPressEvent(event)

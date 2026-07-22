import os
import numpy as np
from typing import List, Dict, Tuple

from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtWidgets import QGraphicsView, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene
from PySide6.QtCore import Signal, Qt, QRectF, QPointF

from app.ui.dayu_widgets import dayu_theme
from .text_item import TextBlockItem
from .text.text_item_properties import TextItemProperties
from .rectangle import MoveableRectItem
from .watermark_item import WatermarkItem
from .rotate_cursor import RotateHandleCursors
from .drawing_manager import DrawingManager
from .webtoons.webtoon_manager import LazyWebtoonManager
from .interaction_manager import InteractionManager
from .event_handler import EventHandler


class ImageViewer(QGraphicsView):
    # Signals
    rectangle_created = Signal(MoveableRectItem)
    rectangle_selected = Signal(QRectF)
    rectangle_deleted = Signal(QRectF)
    command_emitted = Signal(QtGui.QUndoCommand)
    connect_rect_item = Signal(MoveableRectItem)
    connect_text_item =  Signal(TextBlockItem)
    page_changed = Signal(int)
    clear_text_edits = Signal()
    watermark_stamped = Signal()
    watermark_changed = Signal()
    watermark_cleanup_region_selected = Signal(QRectF)
    watermark_cleanup_cancelled = Signal()
    style_paint_target_requested = Signal(object)
    style_paint_cancelled = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        
        # Core Setup
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.photo = QGraphicsPixmapItem()
        self.photo.setShapeMode(QGraphicsPixmapItem.BoundingRectShape)
        self._scene.addItem(self.photo)

        # Managers using Composition
        self.drawing_manager = DrawingManager(self)
        self.webtoon_manager = LazyWebtoonManager(self)
        self.interaction_manager = InteractionManager(self)
        self.event_handler = EventHandler(self)

        # Viewer Properties
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._is_dark_theme = True
        self.apply_theme(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.viewport().grabGesture(Qt.GestureType.PanGesture)
        # Default to NoDrag; only enable ScrollHandDrag when explicit 'pan' tool is active
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        
        # State
        self.empty = True
        self.zoom = 0
        self.current_tool = None
        self.panning = False
        self.pan_start_pos = None
        self.last_pan_pos = QtCore.QPoint()
        self.total_scale_factor = 0.2 
        self.rotate_cursors = RotateHandleCursors()
        self.webtoon_view_state = {}
        self.magic_eraser_refine_with_sam = False
        self.style_paint_active = False
        self._style_paint_previous_cursor = None

        # Page detection state (used by webtoon and event handlers)
        self._programmatic_scroll = False
        
        # Item lists
        self.rectangles: list[MoveableRectItem] = []
        self.text_items: list[TextBlockItem] = []
        self.watermark_items: list[WatermarkItem] = []
        self.watermark_pending: WatermarkItem = None
        self.watermark_cleanup_active = False
        self._watermark_cleanup_start: QPointF | None = None
        self._watermark_cleanup_item: QGraphicsRectItem | None = None
        self.selected_rect: MoveableRectItem = None
        
        # Box drawing state
        self.start_point: QPointF = None
        self.current_rect: MoveableRectItem = None

    def apply_theme(self, is_dark: bool) -> None:
        """Update only the editor surround; image pixels remain untouched."""
        self._is_dark_theme = bool(is_dark)
        is_black = bool(is_dark) and dayu_theme.background_color.lower() == "#000000"
        background = QtGui.QColor(
            "#000000" if is_black else ("#131925" if is_dark else "#ffffff")
        )
        self.setBackgroundBrush(QtGui.QBrush(background))
        palette = self.viewport().palette()
        palette.setColor(QtGui.QPalette.ColorRole.Base, background)
        palette.setColor(QtGui.QPalette.ColorRole.Window, background)
        self.viewport().setPalette(palette)
        self.viewport().setAutoFillBackground(True)
        self.viewport().update()

    # Properties to maintain public API
    @property
    def webtoon_mode(self):
        """Read-only proxy to check if webtoon mode is active."""
        return self.webtoon_manager.is_active()

    # Public API
    def hasPhoto(self) -> bool:
        if self.webtoon_mode:
            return not self.empty and len(self.webtoon_manager.loaded_pages) > 0
        return not self.empty

    def start_style_paint(self, cursor: QtGui.QCursor) -> None:
        """Arm the one-click style painter without changing canvas tools."""
        if not self.style_paint_active:
            self._style_paint_previous_cursor = QtGui.QCursor(
                self.viewport().cursor()
            )
        self.style_paint_active = True
        self.viewport().setCursor(cursor)

    def cancel_style_paint(self, notify: bool = True) -> None:
        was_active = self.style_paint_active
        self.style_paint_active = False
        previous = self._style_paint_previous_cursor
        self._style_paint_previous_cursor = None
        if previous is not None:
            self.viewport().setCursor(previous)
        else:
            self.viewport().unsetCursor()
        if was_active and notify:
            self.style_paint_cancelled.emit()
    
    def load_images_webtoon(self, file_paths: List[str], current_page: int = 0) -> bool:
        """Load images using lazy loading strategy."""
        return self.webtoon_manager.load_images_lazy(file_paths, current_page)

    def scroll_to_page(self, page_index: int, position='top'):
        if self.webtoon_mode:
            self.webtoon_manager.scroll_to_page(page_index, position)

    def fitInView(self):
        # Handle lazy webtoon manager
        if self.webtoon_mode:
            if not self.empty and self.webtoon_manager.image_items:
                # Use first loaded image or fallback to first position
                first_item = None
                for i in range(len(self.webtoon_manager.image_file_paths)):
                    if i in self.webtoon_manager.image_items:
                        first_item = self.webtoon_manager.image_items[i]
                        break
                
                if first_item:
                    image_rect = QRectF(first_item.pos(), first_item.boundingRect().size())
                else:
                    # Fallback to estimated first page bounds
                    y_pos = self.webtoon_manager.image_positions[0] if self.webtoon_manager.image_positions else 100
                    height = self.webtoon_manager.image_heights[0] if self.webtoon_manager.image_heights else 1000
                    width = self.webtoon_manager.webtoon_width
                    image_rect = QRectF(0, y_pos, width, height)
                
                if not image_rect.isNull():
                    padding = 20
                    padded_rect = image_rect.adjusted(-padding, -padding, padding, padding)
                    
                    self.setSceneRect(padded_rect)
                    unity = self.transform().mapRect(QRectF(0, 0, 1, 1))
                    self.scale(1 / unity.width(), 1 / unity.height())
                    viewrect = self.viewport().rect()
                    scenerect = self.transform().mapRect(padded_rect)
                    factor = min(viewrect.width() / scenerect.width(),
                                 viewrect.height() / scenerect.height())
                    self.scale(factor, factor)
                    self.centerOn(image_rect.center())
                    
                    # Set the full scene rect for scrolling
                    self.setSceneRect(0, 0, self.webtoon_manager.webtoon_width, self.webtoon_manager.total_height)

        elif self.hasPhoto():
            rect = self.photo.boundingRect()
            if not rect.isNull():
                self.setSceneRect(rect)
                unity = self.transform().mapRect(QRectF(0, 0, 1, 1))
                self.scale(1 / unity.width(), 1 / unity.height())
                viewrect = self.viewport().rect()
                scenerect = self.transform().mapRect(rect)
                factor = min(viewrect.width() / scenerect.width(),
                             viewrect.height() / scenerect.height())
                self.scale(factor, factor)
                self.centerOn(rect.center())

    def set_tool(self, tool: str):
        self.current_tool = tool
        if tool == 'pan':
            self.setDragMode(QGraphicsView.ScrollHandDrag)
        elif tool in ['brush', 'eraser']:
            self.setDragMode(QGraphicsView.NoDrag)
            if tool == 'brush':
                cursor = self.drawing_manager.brush_cursor
            else:
                cursor =  self.drawing_manager.eraser_cursor
            self.setCursor(cursor)
        else:
            self.setDragMode(QGraphicsView.NoDrag)

    def set_magic_eraser_refinement(self, enabled: bool) -> None:
        """Mark the current brush operation for optional SAM mask refinement."""
        self.magic_eraser_refine_with_sam = bool(enabled)

    @property
    def brush_size(self):
        return self.drawing_manager.brush_size

    @brush_size.setter
    def brush_size(self, size: int):
        try:
            self.drawing_manager.set_brush_size(size, size)
        except Exception:
            self.drawing_manager.brush_size = size

    @property
    def eraser_size(self):
        return self.drawing_manager.eraser_size

    @eraser_size.setter
    def eraser_size(self, size: int):
        try:
            self.drawing_manager.set_eraser_size(size, size)
        except Exception:
            self.drawing_manager.eraser_size = size

    # Event Handler Methods (Delegated to EventHandler)
    def mousePressEvent(self, event):
        self.event_handler.handle_mouse_press(event)

    def mouseMoveEvent(self, event):
        self.event_handler.handle_mouse_move(event)

    def mouseReleaseEvent(self, event):
        self.event_handler.handle_mouse_release(event)

    def wheelEvent(self, event):
        self.event_handler.handle_wheel(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            selected_watermarks = self.get_selected_watermark_items()
            if selected_watermarks:
                for item in list(selected_watermarks):
                    item.remove_from_scene()
                event.accept()
                return
        super().keyPressEvent(event)

    def viewportEvent(self, event):
        return self.event_handler.handle_viewport_event(event)

    def set_br_er_size(self, size, scaled_size):
        if self.current_tool == 'brush':
            self.drawing_manager.set_brush_size(size, scaled_size)
            self.setCursor(self.drawing_manager.brush_cursor)
        elif self.current_tool == 'eraser':
            self.drawing_manager.set_eraser_size(size, scaled_size)
            self.setCursor(self.drawing_manager.eraser_cursor)

    def constrain_point(self, point: QPointF) -> QPointF:
        if self.webtoon_mode:
            return QPointF(
                max(0, min(point.x(), self.webtoon_manager.webtoon_width)),
                max(0, min(point.y(), self.webtoon_manager.total_height))
            )

        elif self.hasPhoto():
            return QPointF(
                max(0, min(point.x(), self.photo.pixmap().width())),
                max(0, min(point.y(), self.photo.pixmap().height()))
            )
        return point

    def get_image_array(self, paint_all=False, include_patches=True):
        """
        Get image array data. In webtoon mode, returns the visible area image.
        In regular mode, returns the single photo image with optional patches/scene items.
        """
        if not self.hasPhoto():
            return None

        # Handle webtoon mode using the webtoon manager's specialized logic
        if self.webtoon_mode:
            result, _ = self.webtoon_manager.get_visible_area_image(paint_all, include_patches)
            return result

        # Handle regular single image mode
        if self.photo.pixmap() is None:
            return None

        qimage = None
        if paint_all:
            # Create a high-resolution QImage
            scale_factor = 2 # Increase this for higher resolution
            pixmap = self.photo.pixmap()
            original_size = pixmap.size()
            scaled_size = original_size * scale_factor

            qimage = QtGui.QImage(scaled_size, QtGui.QImage.Format_ARGB32)
            qimage.fill(Qt.transparent)

            # Create a QPainter with antialiasing
            painter = QtGui.QPainter(qimage)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
            

            original_transform = self.transform()
            self._scene.views()[0].resetTransform()
            self._scene.setSceneRect(0, 0, original_size.width(), original_size.height())
            self._scene.render(painter)
            painter.end()


            # Scale down the image to the original size
            qimage = qimage.scaled(
                original_size, 
                QtCore.Qt.AspectRatioMode.KeepAspectRatio, 
                QtCore.Qt.TransformationMode.SmoothTransformation
            )

            # Restore the original transformation
            self._scene.views()[0].setTransform(original_transform)
        
        elif include_patches:
            pixmap = self.photo.pixmap()
            qimage = QtGui.QImage(pixmap.size(), QtGui.QImage.Format_ARGB32)
            qimage.fill(Qt.transparent)
            painter = QtGui.QPainter(qimage)
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawPixmap(0, 0, pixmap)
            
            # Updated patch detection logic - patches are now added directly to scene
            for item in self._scene.items():
                if isinstance(item, QGraphicsPixmapItem) and item != self.photo:
                    # Check if this is a patch item (has the hash key data)
                    if item.data(0) is not None:  # HASH_KEY = 0 from PatchCommandBase
                        pos = item.pos()
                        painter.drawPixmap(int(pos.x()), int(pos.y()), item.pixmap())
            painter.end()
        else:
            qimage = self.photo.pixmap().toImage()

        # Convert QImage to image
        qimage = qimage.convertToFormat(QtGui.QImage.Format.Format_RGB888)
        width = qimage.width()
        height = qimage.height()
        bytes_per_line = qimage.bytesPerLine()

        byte_count = qimage.sizeInBytes()
        expected_size = height * bytes_per_line  # bytes per line can include padding

        if byte_count != expected_size:
            print(f"QImage sizeInBytes: {byte_count}, Expected size: {expected_size}")
            print(f"Image dimensions: ({width}, {height}), Format: {qimage.format()}")
            raise ValueError(f"Byte count mismatch: got {byte_count} but expected {expected_size}")

        ptr = qimage.bits()

        # Convert memoryview to a numpy array considering the complete data with padding
        arr = np.array(ptr).reshape((height, bytes_per_line))
        # Exclude the padding bytes, keeping only the relevant image data
        arr = arr[:, :width * 3]
        # Reshape to the correct dimensions without the padding bytes
        arr = arr.reshape((height, width, 3))

        return arr
    
    def qimage_from_array(self, img_array: np.ndarray):
        height, width, channel = img_array.shape
        bytes_per_line = 3 * width
        qimage = QtGui.QImage(img_array.data, width, height, bytes_per_line, QtGui.QImage.Format.Format_RGB888)
        return qimage

    def display_image_array(self, img_array: np.ndarray, fit: bool = True):
        qimage = self.qimage_from_array(img_array)
        pixmap = QtGui.QPixmap.fromImage(qimage)
        self.clear_scene()
        self.setPhoto(pixmap, fit=fit)

    def clear_scene(self):
        self.cancel_watermark_cleanup_selection(notify=False)
        self.webtoon_manager.clear()
        self._scene.clear()
        self.rectangles.clear()
        self.text_items.clear()
        self._reset_watermark_tracking()
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.selected_rect = None
        self.photo = QGraphicsPixmapItem()
        self.photo.setShapeMode(QGraphicsPixmapItem.BoundingRectShape)
        self._scene.addItem(self.photo)

    def _reset_watermark_tracking(self):
        self.watermark_items.clear()
        self.watermark_pending = None

    def clear_watermarks(self):
        self.cancel_watermark_cleanup_selection(notify=False)
        if self.watermark_pending is not None and self.watermark_pending.scene() is not None:
            self._scene.removeItem(self.watermark_pending)
        for item in list(self.watermark_items):
            if item.scene() is not None:
                self._scene.removeItem(item)
        self._reset_watermark_tracking()
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

    # --- Region-based watermark removal ---------------------------------

    def is_selecting_watermark_cleanup(self) -> bool:
        return self.watermark_cleanup_active

    def start_watermark_cleanup_selection(self) -> None:
        """Enable one rectangular selection for watermark inpainting."""
        self.cancel_watermark_cleanup_selection(notify=False)
        self.watermark_cleanup_active = True
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)

    def begin_watermark_cleanup_selection(self, scene_pos: QPointF) -> None:
        if not self.watermark_cleanup_active:
            return
        self._watermark_cleanup_start = self.constrain_point(scene_pos)
        if self._watermark_cleanup_item is None:
            item = QGraphicsRectItem()
            pen = QtGui.QPen(QtGui.QColor('#28d7ff'), 2, Qt.PenStyle.DashLine)
            item.setPen(pen)
            item.setBrush(QtGui.QBrush(QtGui.QColor(40, 215, 255, 48)))
            item.setZValue(5000)
            self._scene.addItem(item)
            self._watermark_cleanup_item = item
        self.update_watermark_cleanup_selection(scene_pos)

    def update_watermark_cleanup_selection(self, scene_pos: QPointF) -> None:
        if self._watermark_cleanup_start is None or self._watermark_cleanup_item is None:
            return
        end = self.constrain_point(scene_pos)
        self._watermark_cleanup_item.setRect(QRectF(self._watermark_cleanup_start, end).normalized())

    def finish_watermark_cleanup_selection(self) -> QRectF | None:
        if self._watermark_cleanup_start is None or self._watermark_cleanup_item is None:
            return None
        rect = self._watermark_cleanup_item.rect().normalized()
        self._remove_watermark_cleanup_item()
        self.watermark_cleanup_active = False
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        if rect.width() < 4 or rect.height() < 4:
            self.watermark_cleanup_cancelled.emit()
            return None
        self.watermark_cleanup_region_selected.emit(rect)
        return rect

    def cancel_watermark_cleanup_selection(self, notify: bool = True) -> None:
        was_active = self.watermark_cleanup_active or self._watermark_cleanup_item is not None
        self._remove_watermark_cleanup_item()
        self.watermark_cleanup_active = False
        if was_active:
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            if notify:
                self.watermark_cleanup_cancelled.emit()

    def _remove_watermark_cleanup_item(self) -> None:
        if self._watermark_cleanup_item is not None and self._watermark_cleanup_item.scene() is not None:
            self._scene.removeItem(self._watermark_cleanup_item)
        self._watermark_cleanup_item = None
        self._watermark_cleanup_start = None

    def setPhoto(self, pixmap: QtGui.QPixmap = None, fit: bool = True):
        if pixmap and not pixmap.isNull():
            self.empty = False
            self.photo.setPixmap(pixmap)
            if fit:
                self.fitInView()
        else:
            self.empty = True
            self.photo.setPixmap(QtGui.QPixmap())
        self.zoom = 0

    def get_mask_for_inpainting(self):
        mask = self.drawing_manager.generate_mask_from_strokes()
        return mask
    
    def create_rect_item(self, rect: QRectF, scene_pos: QPointF = None) -> MoveableRectItem:
        rect_item = MoveableRectItem(rect, None)
        self._scene.addItem(rect_item)
        return rect_item

    def add_rectangle(self, rect: QRectF, position: QPointF, rotation: float = 0, origin: QPointF = None) -> MoveableRectItem:
        rect_item = self.create_rect_item(rect)
        rect_item.setPos(position)
        rect_item.setRotation(rotation)
        if origin:
            rect_item.setTransformOriginPoint(origin)
        self.connect_rect_item.emit(rect_item)
        self.rectangles.append(rect_item)
        return rect_item
    
    def add_text_item(self, properties) -> TextBlockItem:
        """
        Create and add a TextBlockItem to the scene using TextItemProperties.
        
        Args:
            properties: TextItemProperties dataclass containing all text item settings
            
        Returns:
            TextBlockItem: The created text item
        """
        
        # If properties is a dict, convert to TextItemProperties
        if isinstance(properties, dict):
            properties = TextItemProperties.from_dict(properties)
        
        # Create the TextBlockItem with the most up-to-date construction logic
        # Based on the load_state function which has the most complete setup
        item = TextBlockItem(
            text=properties.text, 
            font_family=properties.font_family,
            font_size=properties.font_size, 
            render_color=properties.text_color,
            alignment=properties.alignment, 
            line_spacing=properties.line_spacing,
            letter_spacing=properties.letter_spacing,
            outline_color=properties.outline_color, 
            outline_width=properties.outline_width,
            bold=properties.bold,
            font_weight=properties.font_weight,
            italic=properties.italic, 
            underline=properties.underline,
            opacity=properties.opacity,
            direction=properties.direction,
        )
        
        # Apply width if specified
        if properties.width is not None:
            item.set_text(properties.text, properties.width)
        
        # Set direction if specified
        item.set_direction(properties.direction)
        
        # Set transform origin if specified
        if properties.transform_origin:
            item.setTransformOriginPoint(QPointF(*properties.transform_origin))
        
        # Set position, rotation, and scale
        item.setPos(QPointF(*properties.position))
        item.setRotation(properties.rotation)
        item.setScale(properties.scale)

        item.set_vertical(bool(properties.vertical))
        item.set_letter_spacing(properties.letter_spacing)
        item.set_line_spacing(properties.line_spacing)
        item.set_color(properties.text_color)
        if properties.fill_style:
            item.set_fill_style(properties.fill_style)
        item.set_text_warp(
            properties.warp
            or (
                properties.fill_style.get('warp', {})
                if isinstance(properties.fill_style, dict) else {}
            )
        )
            
        # Set selection outlines
        item.selection_outlines = properties.selection_outlines.copy()

        # Re-flowable auto-generated text keeps a pinned wrap width.
        if getattr(properties, 'fixed_wrap_width', None):
            item.set_fixed_wrap_width(properties.fixed_wrap_width)

        # Update the item
        item.update()

        # Add to scene and track
        self._scene.addItem(item)
        self.text_items.append(item)
        
        # Emit the connect signal for the text item
        self.connect_text_item.emit(item)
        
        return item

    def _default_watermark_scale(self, pixmap: QtGui.QPixmap) -> float:
        """Scale so the watermark width is about a third of the page width."""
        if pixmap.width() <= 0 or not self.hasPhoto():
            return 1.0
        target_width = self.photo.boundingRect().width() / 3.0
        return max(0.05, min(1.0, target_width / pixmap.width()))

    def _resolve_watermark_path(self, source_path: str) -> str:
        if source_path and os.path.exists(source_path):
            return source_path

        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        candidates = [
            os.path.join(project_root, "resources", "static", "watermark.png"),
            os.path.join(project_root, "resources", "static", "marca de agua.png"),
            os.path.join(project_root, "marca de agua.png"),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return source_path

    def add_watermark(self, source_path: str, position: QPointF = None,
                      scale: float = None, rotation: float = 0.0) -> WatermarkItem:
        """Add a movable watermark image to the current page.

        Args:
            source_path: Path to the watermark image (PNG with alpha).
            position: Top-left scene position. If None, the watermark is
                placed centred near the bottom of the page (a common spot).
            scale: Item scale. If None, the watermark is scaled so its width
                is about a third of the page width.
            rotation: Rotation in degrees.

        Returns:
            The created WatermarkItem, or None if the image could not be loaded
            or there is no page displayed.
        """
        if not self.hasPhoto():
            return None

        source_path = self._resolve_watermark_path(source_path)
        pixmap = QtGui.QPixmap(source_path)
        if pixmap.isNull():
            return None

        item = WatermarkItem(pixmap, source_path)

        page_rect = self.photo.boundingRect()

        if scale is None:
            scale = self._default_watermark_scale(pixmap)
        item.setScale(scale)

        if position is None:
            scaled_w = pixmap.width() * scale
            scaled_h = pixmap.height() * scale
            # Centred horizontally, near the bottom with a small margin.
            x = (page_rect.width() - scaled_w) / 2.0
            y = page_rect.height() - scaled_h - page_rect.height() * 0.03
            position = QPointF(max(0.0, x), max(0.0, y))
        item.setPos(position)
        item.setRotation(rotation)

        self._scene.addItem(item)
        self.watermark_items.append(item)
        return item

    # --- Interactive watermark placement (click-to-stamp) -----------------

    @property
    def is_placing_watermark(self) -> bool:
        return self.watermark_pending is not None

    def start_watermark_placement(self, source_path: str) -> bool:
        """Begin click-to-stamp placement: a preview follows the cursor until
        the user clicks on the page to drop the watermark."""
        if not self.hasPhoto():
            return False

        # Replace any in-progress placement.
        self.cancel_watermark_placement()

        source_path = self._resolve_watermark_path(source_path)
        pixmap = QtGui.QPixmap(source_path)
        if pixmap.isNull():
            return False

        item = WatermarkItem(pixmap, source_path)
        item.setScale(self._default_watermark_scale(pixmap))
        item.setOpacity(0.6)
        # The preview should not intercept clicks or be movable while placing.
        item.setFlag(item.GraphicsItemFlag.ItemIsMovable, False)
        item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, False)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        item.setCursor(Qt.CursorShape.CrossCursor)

        self._scene.addItem(item)
        self.watermark_pending = item
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)

        # Centre the preview on the current cursor position if available.
        cursor_pos = self.viewport().mapFromGlobal(QtGui.QCursor.pos())
        if self.viewport().rect().contains(cursor_pos):
            self.update_watermark_placement(self.mapToScene(cursor_pos))
        return True

    def _center_pending_on(self, scene_pos: QPointF):
        item = self.watermark_pending
        pixmap = item.pixmap()
        # With the transform origin at the pixmap centre, the visual centre sits
        # at pos + (w/2, h/2), so offset by half the unscaled size.
        item.setPos(QPointF(scene_pos.x() - pixmap.width() / 2.0,
                            scene_pos.y() - pixmap.height() / 2.0))

    def update_watermark_placement(self, scene_pos: QPointF):
        if self.watermark_pending is None:
            return
        self._center_pending_on(scene_pos)

    def finalize_watermark_placement(self, scene_pos: QPointF) -> WatermarkItem:
        """Stamp the pending watermark at scene_pos and make it movable."""
        item = self.watermark_pending
        if item is None:
            return None

        self._center_pending_on(scene_pos)
        item.setOpacity(1.0)
        item.setFlag(item.GraphicsItemFlag.ItemIsMovable, True)
        item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, True)
        item.setAcceptedMouseButtons(Qt.MouseButton.AllButtons)
        item.setCursor(Qt.CursorShape.OpenHandCursor)
        self.select_watermark(item)

        self.watermark_pending = None
        self.watermark_items.append(item)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        return item

    def cancel_watermark_placement(self):
        if self.watermark_pending is not None:
            self._scene.removeItem(self.watermark_pending)
            self.watermark_pending = None
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

    def get_selected_text_items(self) -> list[TextBlockItem]:
        return [item for item in self.text_items if item.selected]

    def get_selected_rectangles(self) -> list[MoveableRectItem]:
        return [item for item in self.rectangles if item.selected]

    def get_selected_watermark_items(self) -> list[WatermarkItem]:
        return [item for item in self.watermark_items if item.isSelected()]

    def deselect_watermarks(self, except_item: WatermarkItem = None):
        for item in self.watermark_items:
            if item is not except_item:
                item.setSelected(False)

    def select_watermark(self, item: WatermarkItem):
        self.deselect_watermarks(except_item=item)
        self.clear_text_edits.emit()
        self.deselect_all()
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        item.setSelected(True)
        item.setFocus(Qt.FocusReason.MouseFocusReason)
    
    # InteractionManager proxy methods
    def sel_rot_item(self):
        return self.interaction_manager.sel_rot_item()
    
    def select_rectangle(self, rect: MoveableRectItem):
        return self.interaction_manager.select_rectangle(rect)
    
    def deselect_rect(self, rect: MoveableRectItem):
        return self.interaction_manager.deselect_rect(rect)
    
    def deselect_all(self):
        return self.interaction_manager.deselect_all()
    
    def clear_rectangles(self, page_switch=False):
        return self.interaction_manager.clear_rectangles(page_switch)
        
    def clear_rectangles_in_visible_area(self):
        """Clear rectangles that are within the currently visible viewport area."""
        return self.interaction_manager.clear_rectangles_in_visible_area()
    
    def clear_text_items(self, delete=True):
        return self.interaction_manager.clear_text_items(delete)
    
    # DrawingManager proxy methods
    def clear_brush_strokes(self, page_switch=False):
        self.drawing_manager.clear_brush_strokes(page_switch)

    def load_brush_strokes(self, strokes: List[Dict]):
        self.drawing_manager.load_brush_strokes(strokes)

    def save_brush_strokes(self) -> List[Dict]:
        return self.drawing_manager.save_brush_strokes()

    def draw_segmentation_lines(self, bboxes):
        self.drawing_manager.draw_segmentation_lines(bboxes)

    def has_drawn_elements(self) -> bool:
        return self.drawing_manager.has_drawn_elements()

    def scene_to_page_coordinates(self, scene_pos: QPointF) -> Tuple[int, QPointF]:
        if self.webtoon_mode:
            return self.webtoon_manager.layout_manager.scene_to_page_coordinates(scene_pos)

    def page_to_scene_coordinates(self, page_index: int, local_pos: QPointF) -> QPointF:
        if self.webtoon_mode:
            return self.webtoon_manager.layout_manager.page_to_scene_coordinates(page_index, local_pos)

    def get_visible_area_image(self, paint_all=False, include_patches=True) -> Tuple[np.ndarray, list]:
        if self.webtoon_mode:
            return self.webtoon_manager.get_visible_area_image(paint_all, include_patches)
        
    # State Management
    def save_state(self) -> Dict:
        transform = self.transform()
        center = self.mapToScene(self.viewport().rect().center())
        
        rectangles_state = []
        for item in self._scene.items():
            if isinstance(item, MoveableRectItem):
                rectangles_state.append({
                    'rect': (item.pos().x(), item.pos().y(), item.boundingRect().width(), item.boundingRect().height()),
                    'rotation': item.rotation(),
                    'transform_origin': (item.transformOriginPoint().x(), item.transformOriginPoint().y())
                })
            
        text_items_state = []
        for item in self._scene.items():
            if isinstance(item, TextBlockItem):
                # Use TextItemProperties for consistent serialization
                text_props = TextItemProperties.from_text_item(item)
                text_items_state.append(text_props.to_dict())

        watermark_items_state = []
        for item in self._scene.items():
            if isinstance(item, WatermarkItem) and item is not self.watermark_pending:
                watermark_items_state.append({
                    'source_path': item.source_path,
                    'position': (item.pos().x(), item.pos().y()),
                    'scale': item.scale(),
                    'rotation': item.rotation(),
                })

        return {
            'rectangles': rectangles_state,
            'transform': (transform.m11(), transform.m12(), transform.m13(),
                          transform.m21(), transform.m22(), transform.m23(),
                          transform.m31(), transform.m32(), transform.m33()),
            'center': (center.x(), center.y()),
            'scene_rect': (self.sceneRect().x(), self.sceneRect().y(),
                           self.sceneRect().width(), self.sceneRect().height()),
            'text_items_state': text_items_state,
            'watermark_items_state': watermark_items_state
        }

    def load_state(self, state: Dict):
        self.clear_watermarks()

        scene_rect = state.get('scene_rect')
        if scene_rect:
            self.setSceneRect(QRectF(*scene_rect))

        transform = state.get('transform')
        if transform:
            self.setTransform(QtGui.QTransform(*transform))

        center = state.get('center')
        if center:
            self.centerOn(QPointF(*center))

        for data in state['rectangles']:
            x, y, w, h = data['rect']
            origin = QPointF(*data.get('transform_origin', (0,0))) if 'transform_origin' in data else None
            self.add_rectangle(QRectF(0,0,w,h), QPointF(x,y), data.get('rotation', 0), origin)

        for data in state.get('text_items_state', []):
            # Use the new add_text_item function for consistency
            self.add_text_item(data)

        for data in state.get('watermark_items_state', []):
            pos = data.get('position', (0, 0))
            self.add_watermark(
                data.get('source_path', ''),
                position=QPointF(*pos),
                scale=data.get('scale'),
                rotation=data.get('rotation', 0.0),
            )

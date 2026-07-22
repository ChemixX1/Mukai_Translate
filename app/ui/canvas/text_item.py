from PySide6.QtWidgets import QGraphicsTextItem, QGraphicsItem, \
     QApplication, QWidget, QStyle, QStyleOptionGraphicsItem
from PySide6.QtGui import QFont, QCursor, QColor, QBrush, QGradient, \
     QLinearGradient, QRadialGradient, QTextCharFormat, QTextBlockFormat, QTextCursor, QPainter, QImage, QPen
from PySide6.QtCore import Qt, QRectF, Signal, QPointF, QTimer
from app.ui.dayu_widgets import dayu_theme
from PIL import Image
import math, copy, re
import numpy as np
from dataclasses import dataclass
from enum import Enum
from .layer_effects import (
    effect_margin,
    pil_rgba_to_qimage,
    qimage_alpha_to_pil,
    render_layer_effects,
    scaled_effect_style,
)
from .text.vertical_layout import VerticalTextDocumentLayout
from .text_warp import (
    normalise_text_warp,
    qimage_to_rgba_array,
    rgba_array_to_qimage,
    warp_padding,
    warp_rgba_array,
)
from .text_3d import (
    alpha_composite_rgba,
    has_text_3d,
    normalise_text_3d,
    render_text_3d,
    scaled_text_3d,
    text_3d_padding,
)


@dataclass
class TextBlockState:
    rect: tuple  
    rotation: float
    transform_origin: QPointF

    @classmethod
    def from_item(cls, item: QGraphicsTextItem):
        """Create TextBlockState from a TextBlockItem"""
        rect = QRectF(item.pos(), item.boundingRect().size()).getCoords()
        return cls(
            rect=rect,
            rotation=item.rotation(),
            transform_origin=item.transformOriginPoint()
        )
    
class OutlineType(Enum):
    Full_Document = 'full_document'
    Selection = 'selection'
    
@dataclass
class OutlineInfo:
    start: int
    end: int
    color: QColor
    width: float
    type: OutlineType

class TextBlockItem(QGraphicsTextItem):
    text_changed = Signal(str)
    item_selected = Signal(object)
    item_deselected = Signal()
    text_highlighted = Signal(dict)
    change_undo = Signal(TextBlockState, TextBlockState)
    delete_requested = Signal(object)
    
    def __init__(self, 
             text = "", 
             font_family = "", 
             font_size = 20, 
             render_color = QColor(0, 0, 0), 
             alignment = Qt.AlignmentFlag.AlignCenter, 
             line_spacing = 1.2, 
             letter_spacing = 0.0,
             outline_color = QColor(255, 255, 255), 
             outline_width = 1,
             bold=False,
             font_weight=None,
             italic=False, 
             underline=False,
             opacity=1.0,
             direction=Qt.LayoutDirection.LeftToRight):

        super().__init__(text)
        self.text_color = render_color
        self.fill_style = self._normalise_fill_style({
            'mode': 'solid',
            'color': self._colour_name(render_color),
        })
        self.text_warp = normalise_text_warp({})
        self._layer_effect_cache = None
        self._applying_word_gradient = False
        self._gradient_refresh_pending = False
        self.outline = True if outline_color else False
        self.outline_color = outline_color
        self.outline_width = outline_width
        self.font_weight = self._normalise_font_weight(
            font_weight if font_weight is not None else (700 if bold else 400)
        )
        self.bold = self.font_weight >= 600
        self.italic = italic
        self.underline = underline
        self.font_family = font_family
        self.font_size = font_size
        self.alignment = alignment
        self.line_spacing = line_spacing
        self.letter_spacing = self._normalise_letter_spacing(letter_spacing)
        self.direction = direction
        raw_opacity = float(opacity)
        if raw_opacity > 1.0:
            raw_opacity /= 100.0
        self.setOpacity(max(0.0, min(1.0, raw_opacity)))

        self.layout = None
        self.vertical = False

        # When set, the box keeps this wrap width instead of shrinking to fit the
        # text, so auto-generated content re-flows when the box is resized.
        self._fixed_wrap_width = None

        self.selected = False
        self.resizing = False
        self.resize_handle = None
        self.resize_start = None
        self.editing_mode = False
        self.last_selection = None 
        self._drag_selecting = False
        self._drag_select_anchor = None

        # Rotation properties
        self.rot_handle = None
        self.rotating = False
        self.last_rotation_angle = 0
        self.rotation_smoothing = 1.0  # rotation sensitivity
        self.center_scene_pos = None  

        self.old_state = None

        self.selection_outlines = []

        self.setAcceptHoverEvents(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.document().contentsChanged.connect(self._on_text_changed)
        self.setTransformOriginPoint(self.boundingRect().center())
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.setZValue(1)

        # Set the initial text direction
        self._apply_text_direction()

    def set_vertical(self, vertical: bool):
        doc = self.document()
        is_already_vertical = isinstance(doc.documentLayout(), VerticalTextDocumentLayout)

        if vertical == is_already_vertical:
            return

        self.vertical = vertical
        self._invalidate_layer_effect_cache()

        # Disconnect signals from the old layout if it's our custom one
        if is_already_vertical:
            old_layout = doc.documentLayout()
            if old_layout:
                try:
                    old_layout.size_enlarged.disconnect(self.on_document_enlarged)
                    old_layout.documentSizeChanged.disconnect(self.setCenterTransform)
                except (TypeError, RuntimeError): # Already disconnected
                    pass
        
        # Inform the graphics system that the geometry will change
        self.prepareGeometryChange()
        current_rect = self.boundingRect()

        # Disable text interaction while changing layout
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        
        if doc.documentLayout():
            doc.documentLayout().blockSignals(True)

        if vertical:
            layout = VerticalTextDocumentLayout(
                document=doc,
                line_spacing=self.line_spacing,
                letter_spacing=1.15 + (self.letter_spacing / 100.0),
            )
            self.layout = layout
            doc.setDocumentLayout(layout)
            
            # Connect signals for the new layout
            layout.size_enlarged.connect(self.on_document_enlarged)
            layout.documentSizeChanged.connect(self.setCenterTransform)
            
            # Initialize layout with the item's current size.
            # set_max_size enforces the dimensions, but a text item with no 
            # set text has negligible size, so this can collapse the layout.
            # Only uncomment if set_vertical runs after plain text is set.
            # layout.set_max_size(current_rect.width(), current_rect.height())
            # layout.update_layout()

        else:  # Switching back to horizontal
            self.layout = None
            doc.setDocumentLayout(None)  # Qt will restore the default layout.
            self.setTextWidth(current_rect.width())
            self.set_letter_spacing(self.letter_spacing)
            self.set_line_spacing(self.line_spacing)
        
        # After setting the new layout, update the item's state
        self.setCenterTransform()
        self.update()

    def setCenterTransform(self):
        center = self.boundingRect().center()
        self.setTransformOriginPoint(center)

    def on_document_enlarged(self):
        self.prepareGeometryChange()
        self.setCenterTransform()

    def _apply_text_direction(self):
        text_option = self.document().defaultTextOption()
        text_option.setTextDirection(self.direction)
        self.document().setDefaultTextOption(text_option)

    def set_direction(self, direction):
        if self.direction != direction:
            self.direction = direction
            self._apply_text_direction()
            self._invalidate_layer_effect_cache()
            self.update()

    def set_text(self, text, width):
        if self.is_html(text):
            self.setHtml(text)
            self.setTextWidth(width)
            self.set_outline(self.outline_color, self.outline_width)
        else:
            self.set_plain_text(text)

    def set_plain_text(self, text):
        self.setPlainText(text)
        self.apply_all_attributes()

    def set_fixed_wrap_width(self, width):
        """Pin the wrap width so the box re-flows (instead of shrinking to fit).

        Used for auto-generated translation text: the content is stored as a
        single paragraph and Qt soft-wraps it at this width, so changing the box
        width re-arranges the text in both directions."""
        if not width or width <= 0 or self.vertical:
            return
        self._fixed_wrap_width = float(width)
        self.setTextWidth(self._fixed_wrap_width)
        self._schedule_word_gradient_refresh()

    def set_rendered_text(self, wrapped_text):
        """Set auto-wrapped text while keeping it re-flowable.

        The auto-wrapper bakes hard line breaks sized to the current box width.
        We keep that exact on-screen layout, but store the text as one paragraph
        with a fixed wrap width so widening or narrowing the box re-wraps it."""
        self.set_plain_text(wrapped_text)
        if self.vertical:
            return
        reflowed = " ".join(part for part in wrapped_text.split("\n") if part != "")
        if not reflowed or reflowed == wrapped_text:
            return
        width = self.textWidth()
        if width <= 0:
            width = self.document().size().width()
        # A small margin keeps a line that fit exactly from wrapping early.
        self._fixed_wrap_width = float(width) + 1.0
        self.set_plain_text(reflowed)

    def is_html(self, text):
        import re
        # Simple check for HTML tags
        return bool(re.search(r'<[^>]+>', text))

    def set_font(self, font_family, font_size):
        if not self.textCursor().hasSelection():
            self.font_family = font_family
            self.font_size = font_size

        # Ensure minimum font size.
        font_size = max(1, font_size)

        # Fallback to application default font family if none provided
        effective_family = font_family.strip() if isinstance(font_family, str) and font_family.strip() else QApplication.font().family()
        font = QFont(effective_family, font_size)
        font.setWeight(QFont.Weight(self._normalise_font_weight(self.font_weight)))
        font.setItalic(bool(self.italic))
        font.setUnderline(bool(self.underline))
        font.setLetterSpacing(
            QFont.SpacingType.PercentageSpacing,
            100.0 + self.letter_spacing,
        )
        self.update_text_format('font', font)

    def set_font_size(self, font_size):
        font_size = max(1, font_size)
        if not self.textCursor().hasSelection():
            self.font_size = font_size
        self.update_text_format('size', font_size)

    def update_text_width(self):
        fixed = getattr(self, "_fixed_wrap_width", None)
        if fixed and not self.vertical:
            self.setTextWidth(fixed)
            self._schedule_word_gradient_refresh()
            return
        width = self.document().size().width()
        self.setTextWidth(width)
        self._schedule_word_gradient_refresh()

    def set_alignment(self, alignment):
        if not self.textCursor().hasSelection():
            self.alignment = alignment
        self.update_alignment(alignment)

    def update_alignment(self, alignment):
        cursor = self.textCursor()
        has_selection = cursor.hasSelection()
        block_format = cursor.blockFormat()
        block_format.setAlignment(alignment)

        if has_selection:
            cursor.beginEditBlock()
            start, end = cursor.selectionStart(), cursor.selectionEnd()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            cursor.mergeBlockFormat(block_format)
            cursor.endEditBlock()
        else:
            doc = self.document()
            cursor = QTextCursor(doc)
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.mergeBlockFormat(block_format)

        self.update()

    def update_text_format(self, attribute, value):
        cursor = self.textCursor()
        has_selection = cursor.hasSelection()

        format_operations = {
            'color': lambda cf, v: cf.setForeground(v),
            'font': lambda cf, v: cf.setFont(v),
            'size': lambda cf, v: cf.setFontPointSize(v),
            'bold': lambda cf, v: cf.setFontWeight(QFont.Bold if v else QFont.Normal),
            'weight': lambda cf, v: cf.setFontWeight(int(v)),
            'italic': lambda cf, v: cf.setFontItalic(v),
            'underline': lambda cf, v: cf.setFontUnderline(v),
        }

        if attribute not in format_operations:
            print(f"Unsupported attribute: {attribute}")
            return

        char_format = QTextCharFormat()
        format_operations[attribute](char_format, value)

        if not has_selection:
            cursor.select(QTextCursor.SelectionType.Document)    
  
        cursor.mergeCharFormat(char_format)

        # Update the document's default format
        doc_format = self.document().defaultTextOption()
        if attribute == 'color' and isinstance(value, QColor):
            self.setDefaultTextColor(value)
        elif attribute == 'font':
            self.document().setDefaultFont(value)
        elif attribute == 'size':
            font = self.document().defaultFont()
            font.setPointSize(value)
            self.document().setDefaultFont(font)
        
        # Clear the selection by moving the cursor to the end of the document
        cursor.clearSelection()
        cursor.movePosition(QTextCursor.End)

        self.setTextCursor(cursor)
        self.document().setDefaultTextOption(doc_format)
        self.update()

    def set_line_spacing(self, spacing):
        self.line_spacing = spacing
        if self.vertical and self.layout:
            self.layout.set_line_spacing(float(spacing))
            self.update()
            return
        doc = self.document()
        cursor = QTextCursor(doc)
        cursor.select(QTextCursor.SelectionType.Document)
        block_format = QTextBlockFormat()
        spacing = spacing * 100
        spacing = float(spacing)
        block_format.setLineHeight(spacing, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cursor.mergeBlockFormat(block_format)

    @staticmethod
    def _normalise_letter_spacing(spacing) -> float:
        try:
            spacing = float(spacing)
        except (TypeError, ValueError):
            spacing = 0.0
        return max(-50.0, min(200.0, spacing))

    def set_letter_spacing(self, spacing) -> None:
        """Set tracking as a percentage offset while preserving vertical defaults."""
        spacing = self._normalise_letter_spacing(spacing)
        self.letter_spacing = spacing
        if self.vertical and self.layout:
            self.layout.set_letter_spacing(1.15 + (spacing / 100.0))
            self.update()
            return

        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.SelectionType.Document)
        char_format = QTextCharFormat()
        char_format.setFontLetterSpacingType(QFont.SpacingType.PercentageSpacing)
        char_format.setFontLetterSpacing(100.0 + spacing)
        cursor.mergeCharFormat(char_format)

        default_font = self.document().defaultFont()
        default_font.setLetterSpacing(
            QFont.SpacingType.PercentageSpacing,
            100.0 + spacing,
        )
        self.document().setDefaultFont(default_font)
        self._invalidate_layer_effect_cache()
        self.update()

    @staticmethod
    def _colour_name(colour: QColor) -> str:
        if not isinstance(colour, QColor) or not colour.isValid():
            colour = QColor('#000000')
        return colour.name(QColor.NameFormat.HexArgb)

    @staticmethod
    def _colour_from_value(value, fallback='#ff000000') -> QColor:
        colour = value if isinstance(value, QColor) else QColor(value or fallback)
        return colour if colour.isValid() else QColor(fallback)

    def _normalise_fill_style(self, style) -> dict:
        """Make saved styles safe to paint and safe to serialise again."""
        style = copy.deepcopy(style) if isinstance(style, dict) else {}
        mode = style.get('mode', 'solid')
        if mode not in {'solid', 'gradient'}:
            mode = 'solid'
        colour = self._colour_from_value(style.get('color', self.text_color))
        raw_gradient = style.get('gradient', {}) if isinstance(style.get('gradient'), dict) else {}
        raw_stops = raw_gradient.get('stops', [])
        stops = []
        for raw_stop in raw_stops:
            if not isinstance(raw_stop, dict):
                continue
            stop_colour = self._colour_from_value(raw_stop.get('color', colour))
            stops.append({
                'position': max(0, min(100, int(raw_stop.get('position', 0)))),
                'color': self._colour_name(stop_colour),
                'alpha': max(0, min(255, int(raw_stop.get('alpha', stop_colour.alpha())))),
            })
        if len(stops) < 2:
            stops = [
                {'position': 0, 'color': self._colour_name(colour), 'alpha': colour.alpha()},
                {'position': 100, 'color': '#ffffffff', 'alpha': 255},
            ]
        glow = style.get('glow', {}) if isinstance(style.get('glow'), dict) else {}
        drop_shadow = style.get('drop_shadow', {}) if isinstance(style.get('drop_shadow'), dict) else {}
        inner_glow = style.get('inner_glow', {}) if isinstance(style.get('inner_glow'), dict) else {}
        inner_shadow = style.get('inner_shadow', {}) if isinstance(style.get('inner_shadow'), dict) else {}
        stroke = style.get('stroke', {}) if isinstance(style.get('stroke'), dict) else {}
        three_d = normalise_text_3d(style.get('three_d', {}))
        gradient_style = raw_gradient.get('style', 'linear_90')
        if gradient_style not in {'linear_90', 'linear_180', 'linear_135', 'radial_center', 'radial_origin'}:
            gradient_style = 'linear_90'
        return {
            'mode': mode,
            'color': self._colour_name(colour),
            'gradient': {
                'style': gradient_style,
                'stops': sorted(stops, key=lambda item: item['position']),
            },
            'glow': {
                'enabled': bool(glow.get('enabled', False)),
                'color': self._colour_name(self._colour_from_value(glow.get('color', '#ff00e5ff'))),
                'opacity': max(0, min(100, int(glow.get('opacity', 85)))),
                'spread': max(0, min(100, int(glow.get('spread', 35)))),
                'size': max(1, min(80, int(glow.get('size', 12)))),
            },
            'drop_shadow': {
                'enabled': bool(drop_shadow.get('enabled', False)),
                'color': self._colour_name(self._colour_from_value(drop_shadow.get('color', '#ff000000'))),
                'opacity': max(0, min(100, int(drop_shadow.get('opacity', 55)))),
                'angle': max(0, min(360, int(drop_shadow.get('angle', 120)))),
                'distance': max(0, min(80, int(drop_shadow.get('distance', 8)))),
                'spread': max(0, min(100, int(drop_shadow.get('spread', 10)))),
                'size': max(0, min(80, int(drop_shadow.get('size', 12)))),
            },
            'inner_glow': {
                'enabled': bool(inner_glow.get('enabled', False)),
                'color': self._colour_name(self._colour_from_value(inner_glow.get('color', '#ffffffff'))),
                'opacity': max(0, min(100, int(inner_glow.get('opacity', 65)))),
                'choke': max(0, min(100, int(inner_glow.get('choke', 10)))),
                'size': max(1, min(60, int(inner_glow.get('size', 8)))),
            },
            'inner_shadow': {
                'enabled': bool(inner_shadow.get('enabled', False)),
                'color': self._colour_name(self._colour_from_value(inner_shadow.get('color', '#ff000000'))),
                'opacity': max(0, min(100, int(inner_shadow.get('opacity', 45)))),
                'angle': max(0, min(360, int(inner_shadow.get('angle', 120)))),
                'distance': max(0, min(40, int(inner_shadow.get('distance', 4)))),
                'choke': max(0, min(100, int(inner_shadow.get('choke', 5)))),
                'size': max(0, min(60, int(inner_shadow.get('size', 8)))),
            },
            'stroke': {
                'enabled': bool(stroke.get('enabled', False)),
                'color': self._colour_name(self._colour_from_value(stroke.get('color', '#ffffffff'))),
                'opacity': max(0, min(100, int(stroke.get('opacity', 100)))),
                'size': max(1, min(40, int(stroke.get('size', 3)))),
                'position': stroke.get('position', 'outside')
                if stroke.get('position') in {'outside', 'center', 'inside'} else 'outside',
            },
            'three_d': three_d,
        }

    def get_fill_style(self) -> dict:
        return copy.deepcopy(self.fill_style)

    def get_text_warp(self) -> dict:
        return copy.deepcopy(self.text_warp)

    def get_visual_style(self) -> dict:
        style = self.get_fill_style()
        style['warp'] = self.get_text_warp()
        return style

    def set_visual_style(self, style: dict):
        style = copy.deepcopy(style) if isinstance(style, dict) else {}
        warp = style.pop('warp', self.text_warp)
        self.set_fill_style(style)
        self.set_text_warp(warp)

    def set_text_warp(self, warp: dict):
        normalised = normalise_text_warp(warp)
        if normalised == getattr(self, 'text_warp', None):
            return
        self.prepareGeometryChange()
        self.text_warp = normalised
        self._invalidate_layer_effect_cache()
        self.setTransformOriginPoint(self.boundingRect().center())
        self.update()

    def _has_text_warp(self) -> bool:
        warp = getattr(self, 'text_warp', {})
        return bool(
            warp.get('enabled', False)
            and any(int(warp.get(field, 0)) for field in ('bend', 'horizontal', 'vertical'))
        )

    def _warp_margins(self) -> tuple[float, float]:
        if not self._has_text_warp():
            return 0.0, 0.0
        rect = self._content_bounding_rect()
        pad_x, pad_y = warp_padding(rect.width(), rect.height(), self.text_warp)
        return float(pad_x), float(pad_y)

    def _has_text_3d(self) -> bool:
        return has_text_3d(getattr(self, 'fill_style', {}).get('three_d', {}))

    def _three_d_margins(self, style: dict | None = None) -> tuple[float, float]:
        target_style = style if isinstance(style, dict) else getattr(self, 'fill_style', {})
        effect = target_style.get('three_d', {}) if isinstance(target_style, dict) else {}
        if not has_text_3d(effect):
            return 0.0, 0.0
        rect = self._content_bounding_rect()
        warp_x, warp_y = self._warp_margins()
        pad_x, pad_y = text_3d_padding(
            rect.width() + (2.0 * warp_x),
            rect.height() + (2.0 * warp_y),
            effect,
        )
        return float(pad_x), float(pad_y)

    def _gradient_brush_for_rect(self, rect: QRectF) -> QBrush:
        """Build the configured gradient inside one logical text fragment."""
        rect = QRectF(rect)
        width = max(1.0, rect.width())
        height = max(1.0, rect.height())
        left = rect.left()
        top = rect.top()
        right = left + width
        bottom = top + height
        gradient_data = self.fill_style.get('gradient', {})
        gradient_style = gradient_data.get('style', 'linear_90')

        if gradient_style == 'linear_180':
            gradient = QLinearGradient(
                left + (width / 2.0), top,
                left + (width / 2.0), bottom,
            )
        elif gradient_style == 'linear_135':
            gradient = QLinearGradient(left, top, right, bottom)
        elif gradient_style == 'radial_center':
            gradient = QRadialGradient(
                left + (width / 2.0),
                top + (height / 2.0),
                max(width, height) / 1.45,
            )
        elif gradient_style == 'radial_origin':
            gradient = QRadialGradient(left, top, max(width, height))
        else:  # CSS-like 90 degrees: left to right.
            gradient = QLinearGradient(
                left, top + (height / 2.0),
                right, top + (height / 2.0),
            )

        gradient.setCoordinateMode(QGradient.CoordinateMode.LogicalMode)
        for stop in gradient_data.get('stops', []):
            colour = self._colour_from_value(stop.get('color'))
            colour.setAlpha(max(0, min(255, int(stop.get('alpha', colour.alpha())))))
            gradient.setColorAt(max(0.0, min(1.0, float(stop.get('position', 0)) / 100.0)), colour)
        return QBrush(gradient)

    def _gradient_brush(self) -> QBrush:
        return self._gradient_brush_for_rect(self._content_bounding_rect())

    def _word_gradient_segments(self):
        """Yield document ranges and visual rectangles for every visible word.

        QTextDocument stores soft-wrapped text as one paragraph. Using each
        QTextLine's actual geometry lets a word on a second row start its own
        complete gradient instead of inheriting the first row's progress.
        """
        document = self.document()
        block = document.begin()
        while block.isValid():
            text = block.text()
            layout = block.layout()
            if layout is not None and text:
                layout_position = layout.position()
                for line_index in range(layout.lineCount()):
                    line = layout.lineAt(line_index)
                    line_start = line.textStart()
                    line_end = line_start + line.textLength()
                    for match in re.finditer(r'\S+', text):
                        start = max(match.start(), line_start)
                        end = min(match.end(), line_end)
                        if start >= end:
                            continue
                        start_x = line.cursorToX(start)[0]
                        end_x = line.cursorToX(end)[0]
                        left = layout_position.x() + min(start_x, end_x)
                        width = max(1.0, abs(end_x - start_x))
                        top = layout_position.y() + line.y()
                        height = max(1.0, line.height())
                        yield (
                            block.position() + start,
                            block.position() + end,
                            QRectF(left, top, width, height),
                        )
            block = block.next()

    def _apply_gradient_to_words(self) -> None:
        """Repeat the complete configured gradient independently per word."""
        if (
            self._applying_word_gradient
            or self.vertical
            or getattr(self, 'fill_style', {}).get('mode') != 'gradient'
        ):
            return

        segments = list(self._word_gradient_segments())
        if not segments:
            return

        self._applying_word_gradient = True
        cursor = QTextCursor(self.document())
        try:
            cursor.beginEditBlock()
            for start, end, rect in segments:
                cursor.setPosition(start)
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                char_format = QTextCharFormat()
                char_format.setForeground(self._gradient_brush_for_rect(rect))
                cursor.mergeCharFormat(char_format)
            cursor.endEditBlock()
        finally:
            self._applying_word_gradient = False
        self._invalidate_layer_effect_cache()
        self.update()

    def _schedule_word_gradient_refresh(self) -> None:
        if (
            self._gradient_refresh_pending
            or self._applying_word_gradient
            or getattr(self, 'fill_style', {}).get('mode') != 'gradient'
        ):
            return
        self._gradient_refresh_pending = True
        QTimer.singleShot(0, self._refresh_word_gradient)

    def _refresh_word_gradient(self) -> None:
        self._gradient_refresh_pending = False
        self._apply_gradient_to_words()

    def set_fill_style(self, style: dict):
        """Apply a serialisable solid or gradient fill to this text item."""
        old_margin = self._layer_effect_margin()
        old_three_d = self._three_d_margins()
        normalised_style = self._normalise_fill_style(style)
        new_three_d = self._three_d_margins(normalised_style)
        if old_margin != effect_margin(normalised_style) or old_three_d != new_three_d:
            self.prepareGeometryChange()
        self.fill_style = normalised_style
        self._invalidate_layer_effect_cache()
        colour = self._colour_from_value(self.fill_style['color'])
        if self.fill_style['mode'] == 'gradient':
            first_stop = self.fill_style['gradient']['stops'][0]
            colour = self._colour_from_value(first_stop['color'])
            colour.setAlpha(first_stop['alpha'])
            self.text_color = colour
            self.update_text_format('color', self._gradient_brush())
            self._apply_gradient_to_words()
        else:
            self.text_color = colour
            self.update_text_format('color', colour)
        self.update()

    def _content_bounding_rect(self) -> QRectF:
        """The text rectangle without the extra painting area for its glow."""
        return super().boundingRect()

    def interaction_rect(self) -> QRectF:
        """The editable text box, excluding non-interactive effect padding."""
        return QRectF(self._content_bounding_rect())

    def _layer_effect_margin(self) -> float:
        return float(effect_margin(getattr(self, 'fill_style', {})))

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt API name
        rect = self._content_bounding_rect()
        margin = self._layer_effect_margin()
        warp_x, warp_y = self._warp_margins()
        three_d_x, three_d_y = self._three_d_margins()
        return rect.adjusted(
            -(margin + warp_x + three_d_x),
            -(margin + warp_y + three_d_y),
            margin + warp_x + three_d_x,
            margin + warp_y + three_d_y,
        ) if margin or warp_x or warp_y or three_d_x or three_d_y else rect

    def set_color(self, color):
        """Set a solid fill, preserving the current glow settings."""
        colour = self._colour_from_value(color)
        if not self.textCursor().hasSelection():
            self.text_color = colour
            style = copy.deepcopy(getattr(self, 'fill_style', {}))
            style.update({'mode': 'solid', 'color': self._colour_name(colour)})
            self.fill_style = self._normalise_fill_style(style)
            self._invalidate_layer_effect_cache()
        self.update_text_format('color', colour)

    def update_outlines(self):
        """Update the selection outlines when text changes"""
        if self.outline:
            # Create an outline for the entire document
            doc = self.document()
            char_count = doc.characterCount()
            
            # Create an outline info for the entire document
            new_outline = OutlineInfo(  
                start = 0,
                end = max(0, char_count - 1),
                color = self.outline_color,  
                width = self.outline_width,
                type = OutlineType.Full_Document
            )
            
            # Remove any existing full document outline
            self.selection_outlines = [outline for outline in self.selection_outlines 
                                     if outline.type != OutlineType.Full_Document]
            # Add the new one
            self.selection_outlines.append(new_outline)
        else:
            # Remove only the full document outline
            self.selection_outlines = [outline for outline in self.selection_outlines 
                                     if outline.type != OutlineType.Full_Document]

        self.update() 

    def set_outline(self, outline_color, outline_width):
        # Initialize start and end variables
        start = 0
        end = 0

        if self.textCursor().hasSelection():
            # Store outline properties for the current selection
            start = self.textCursor().selectionStart()
            end = self.textCursor().selectionEnd()
        else:
            # Set global outline properties only when there's no selection
            self.outline = True if outline_color else False

            if self.outline:
                # enabling global outline: store color/width and target whole document
                self.outline_color = outline_color
                self.outline_width = outline_width

                char_count = self.document().characterCount()
                start = 0
                end = max(0, char_count - 1)

        # When disabling outlines (outline_color is falsy), remove the relevant outlines
        if not outline_color:
            if self.textCursor().hasSelection():
                # Remove any outlines that contain the current selection range
                self.selection_outlines = [
                    outline for outline in self.selection_outlines
                    if not (outline.start <= start and outline.end >= end)
                ]
            else:
                # No selection: remove only full-document outlines
                self.selection_outlines = [
                    outline for outline in self.selection_outlines
                    if outline.type != OutlineType.Full_Document
                ]
        else:
            # Adding/updating an outline for the selection or whole document
            type = OutlineType.Selection if self.textCursor().hasSelection() else OutlineType.Full_Document

            # Remove any existing outline for this exact selection range
            self.selection_outlines = [
                outline for outline in self.selection_outlines 
                if not (outline.start == start and outline.end == end)
            ]

            # Add new outline info
            self.selection_outlines.append(
                OutlineInfo(start, end, outline_color, outline_width, type)
            )
        
        self.update()

    def _clone_document_for_effects(self):
        """Clone the document while retaining the custom vertical layout."""
        doc = self.document().clone()
        if self.vertical and self.layout:
            vertical_layout = VerticalTextDocumentLayout(
                document=doc,
                line_spacing=self.layout.line_spacing,
            )
            doc.setDocumentLayout(vertical_layout)
            vertical_layout.set_max_size(self.layout.max_width, self.layout.max_height)
        return doc

    def _invalidate_layer_effect_cache(self):
        self._layer_effect_cache = None

    def _has_layer_effects(self) -> bool:
        style = getattr(self, 'fill_style', {})
        return any(
            isinstance(style.get(name), dict) and style[name].get('enabled', False)
            for name in ('glow', 'drop_shadow', 'inner_glow', 'inner_shadow', 'stroke')
        )

    def _layer_effect_images(self):
        if not self._has_layer_effects():
            return None

        content_rect = self._content_bounding_rect()
        margin = self._layer_effect_margin()
        target_rect = content_rect.adjusted(-margin, -margin, margin, margin)
        scale = 2.0
        pixel_width = max(1, int(math.ceil(target_rect.width() * scale)))
        pixel_height = max(1, int(math.ceil(target_rect.height() * scale)))
        cache_key = (
            self.document().revision(),
            round(content_rect.x(), 3), round(content_rect.y(), 3),
            round(content_rect.width(), 3), round(content_rect.height(), 3),
            repr(self.fill_style),
            bool(self.vertical),
            pixel_width, pixel_height,
        )
        if self._layer_effect_cache and self._layer_effect_cache[0] == cache_key:
            return self._layer_effect_cache[1:]

        mask_image = QImage(pixel_width, pixel_height, QImage.Format.Format_ARGB32_Premultiplied)
        mask_image.fill(Qt.GlobalColor.transparent)
        mask_painter = QPainter(mask_image)
        mask_painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        mask_painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        mask_painter.scale(scale, scale)
        mask_painter.translate(-target_rect.left(), -target_rect.top())
        doc = self._clone_document_for_effects()
        cursor = QTextCursor(doc)
        cursor.select(QTextCursor.SelectionType.Document)
        opaque_format = cursor.charFormat()
        opaque_format.setForeground(QColor(255, 255, 255, 255))
        cursor.mergeCharFormat(opaque_format)
        doc.drawContents(mask_painter)
        mask_painter.end()

        source_mask = qimage_alpha_to_pil(mask_image)
        behind_pil, overlay_pil = render_layer_effects(
            source_mask,
            scaled_effect_style(self.fill_style, scale),
        )
        behind = pil_rgba_to_qimage(behind_pil)
        overlay = pil_rgba_to_qimage(overlay_pil)
        self._layer_effect_cache = (cache_key, behind, overlay, target_rect)
        return behind, overlay, target_rect

    def _paint_selection_outlines(self, painter: QPainter) -> None:
        if not self.selection_outlines:
            return

        doc = self._clone_document_for_effects()
        painter.save()
        cursor = QTextCursor(doc)
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = cursor.charFormat()
        fmt.setForeground(QColor(0, 0, 0, 0))
        cursor.mergeCharFormat(fmt)

        for outline_info in self.selection_outlines:
            cursor.setPosition(outline_info.start)
            cursor.setPosition(outline_info.end, QTextCursor.KeepAnchor)
            fmt = cursor.charFormat()
            fmt.setForeground(outline_info.color)
            cursor.mergeCharFormat(fmt)
            offsets = [
                (dx, dy)
                for dx in (-outline_info.width, 0, outline_info.width)
                for dy in (-outline_info.width, 0, outline_info.width)
                if dx != 0 or dy != 0
            ]
            for dx, dy in offsets:
                painter.save()
                painter.translate(dx, dy)
                doc.drawContents(painter)
                painter.restore()
        painter.restore()

    def _warp_render_scale(self, painter: QPainter | None = None) -> float:
        """Choose a stable supersampling level for screen and final output.

        Four source pixels per logical pixel keep glyph edges crisp at normal
        zoom.  Higher zoom levels get more detail, while a pixel budget avoids
        pathological allocations for very large text boxes.
        """
        lod = 1.0
        if painter is not None:
            try:
                lod = QStyleOptionGraphicsItem.levelOfDetailFromTransform(
                    painter.worldTransform()
                )
            except (AttributeError, TypeError):
                lod = 1.0

        desired = max(4.0, min(8.0, math.ceil(max(1.0, lod) * 2.0)))
        content_rect = self._content_bounding_rect()
        logical_pixels = max(1.0, content_rect.width() * content_rect.height())
        budget_scale = math.sqrt(6_000_000.0 / logical_pixels)
        selected = min(desired, budget_scale)
        # Quantising prevents tiny view-transform changes from invalidating the
        # expensive raster cache on every repaint.
        return max(1.5, math.floor(selected * 2.0) / 2.0)

    def _warped_composite_images(self, render_scale: float | None = None):
        """Render deformation, 3D perspective and layer effects as one cache."""
        if not (self._has_text_warp() or self._has_text_3d()) or self.editing_mode:
            return None

        content_rect = self._content_bounding_rect()
        scale = float(render_scale or self._warp_render_scale())
        pixel_width = max(1, int(math.ceil(content_rect.width() * scale)))
        pixel_height = max(1, int(math.ceil(content_rect.height() * scale)))
        cache_key = (
            'warp',
            self.document().revision(),
            round(content_rect.x(), 3), round(content_rect.y(), 3),
            round(content_rect.width(), 3), round(content_rect.height(), 3),
            repr(self.fill_style), repr(self.text_warp), bool(self.vertical),
            pixel_width, pixel_height,
        )
        if self._layer_effect_cache and self._layer_effect_cache[0] == cache_key:
            return self._layer_effect_cache[1:]

        content_image = QImage(
            pixel_width,
            pixel_height,
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        content_image.fill(Qt.GlobalColor.transparent)
        content_painter = QPainter(content_image)
        content_painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        content_painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        content_painter.scale(scale, scale)
        content_painter.translate(-content_rect.left(), -content_rect.top())
        self._paint_selection_outlines(content_painter)
        self.document().drawContents(content_painter)
        content_painter.end()

        mask_image = QImage(
            pixel_width,
            pixel_height,
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        mask_image.fill(Qt.GlobalColor.transparent)
        mask_painter = QPainter(mask_image)
        mask_painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        mask_painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        mask_painter.scale(scale, scale)
        mask_painter.translate(-content_rect.left(), -content_rect.top())
        mask_doc = self._clone_document_for_effects()
        mask_cursor = QTextCursor(mask_doc)
        mask_cursor.select(QTextCursor.SelectionType.Document)
        mask_format = mask_cursor.charFormat()
        mask_format.setForeground(QColor(255, 255, 255, 255))
        mask_cursor.mergeCharFormat(mask_format)
        mask_doc.drawContents(mask_painter)
        mask_painter.end()

        warped_content, pad_x, pad_y = warp_rgba_array(
            qimage_to_rgba_array(content_image),
            self.text_warp,
        )
        warped_mask, _mask_pad_x, _mask_pad_y = warp_rgba_array(
            qimage_to_rgba_array(mask_image),
            self.text_warp,
        )

        three_d_behind = np.zeros_like(warped_content)
        three_d_overlay = np.zeros_like(warped_content)
        three_d_pad_x = 0
        three_d_pad_y = 0
        if self._has_text_3d():
            (
                warped_content,
                warped_mask,
                three_d_behind,
                three_d_overlay,
                three_d_pad_x,
                three_d_pad_y,
            ) = render_text_3d(
                warped_content,
                warped_mask,
                scaled_text_3d(self.fill_style.get('three_d', {}), scale),
            )
            pad_x += three_d_pad_x
            pad_y += three_d_pad_y

        effect_px = int(math.ceil(self._layer_effect_margin() * scale))
        if effect_px:
            padding = ((effect_px, effect_px), (effect_px, effect_px), (0, 0))
            warped_content = np.pad(warped_content, padding, mode='constant')
            warped_mask = np.pad(warped_mask, padding, mode='constant')
            three_d_behind = np.pad(three_d_behind, padding, mode='constant')
            three_d_overlay = np.pad(three_d_overlay, padding, mode='constant')

        content_qimage = rgba_array_to_qimage(warped_content)
        if self._has_layer_effects():
            source_mask = Image.fromarray(warped_mask[:, :, 3], mode='L')
            behind_pil, overlay_pil = render_layer_effects(
                source_mask,
                scaled_effect_style(self.fill_style, scale),
            )
            behind_array = alpha_composite_rgba(
                np.asarray(behind_pil.convert('RGBA'), dtype=np.uint8),
                three_d_behind,
            )
            overlay_array = alpha_composite_rgba(
                np.asarray(overlay_pil.convert('RGBA'), dtype=np.uint8),
                three_d_overlay,
            )
            behind = rgba_array_to_qimage(behind_array)
            overlay = rgba_array_to_qimage(overlay_array)
        else:
            behind = rgba_array_to_qimage(three_d_behind)
            overlay = rgba_array_to_qimage(three_d_overlay)

        target_rect = QRectF(
            content_rect.left() - ((pad_x + effect_px) / scale),
            content_rect.top() - ((pad_y + effect_px) / scale),
            content_qimage.width() / scale,
            content_qimage.height() / scale,
        )
        self._layer_effect_cache = (
            cache_key,
            behind,
            content_qimage,
            overlay,
            target_rect,
        )
        return behind, content_qimage, overlay, target_rect

    def paint(   
        self, 
        painter: QPainter, 
        option: QStyleOptionGraphicsItem, 
        widget: QWidget = None
    ):

        warped_images = self._warped_composite_images(self._warp_render_scale(painter))
        if warped_images:
            behind, content, overlay, warped_rect = warped_images
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(warped_rect, behind)
            painter.drawImage(warped_rect, content)
            painter.drawImage(warped_rect, overlay)
            painter.restore()
            self._paint_selection_frame(painter)
            return

        effect_images = self._layer_effect_images()
        if effect_images:
            behind, _overlay, effect_rect = effect_images
            painter.drawImage(effect_rect, behind)

        # Then handle any selection outlines
        self._paint_selection_outlines(painter)

        # Draw the normal text on top. Suppress Qt's dashed item-selection
        # frame; the solid frame and explicit resize handles are painted below.
        clean_option = QStyleOptionGraphicsItem(option)
        clean_option.state &= ~QStyle.StateFlag.State_Selected
        super().paint(painter, clean_option, widget)
        if effect_images:
            _behind, overlay, effect_rect = effect_images
            painter.drawImage(effect_rect, overlay)
        self._paint_selection_frame(painter)

    def _paint_selection_frame(self, painter: QPainter) -> None:
        """Paint a Canva-like solid selection frame with six visible handles."""
        if not self.selected:
            return

        rect = self.interaction_rect()
        transform = painter.worldTransform()
        view_scale = max(
            0.001,
            math.hypot(transform.m11(), transform.m12()),
            math.hypot(transform.m21(), transform.m22()),
        )
        corner_radius = 4.0 / view_scale
        side_half_width = 2.2 / view_scale
        side_half_height = 7.0 / view_scale
        selection_colour = QColor(dayu_theme.primary_color)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        selection_pen = QPen(selection_colour, 1.5)
        selection_pen.setCosmetic(True)
        selection_pen.setStyle(Qt.PenStyle.SolidLine)
        painter.setPen(selection_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

        painter.setBrush(selection_colour)
        for point in (
            rect.topLeft(),
            rect.topRight(),
            rect.bottomLeft(),
            rect.bottomRight(),
        ):
            painter.drawEllipse(point, corner_radius, corner_radius)

        for center in (
            QPointF(rect.left(), rect.center().y()),
            QPointF(rect.right(), rect.center().y()),
        ):
            handle_rect = QRectF(
                center.x() - side_half_width,
                center.y() - side_half_height,
                side_half_width * 2.0,
                side_half_height * 2.0,
            )
            painter.drawRoundedRect(
                handle_rect,
                side_half_width,
                side_half_width,
            )
        painter.restore()

    @staticmethod
    def _normalise_font_weight(weight) -> int:
        weights = (100, 200, 300, 400, 500, 600, 700, 800, 900)
        try:
            numeric = int(weight)
        except (TypeError, ValueError):
            numeric = 400
        return min(weights, key=lambda candidate: abs(candidate - numeric))

    def set_font_weight(self, weight) -> None:
        weight = self._normalise_font_weight(weight)
        if not self.textCursor().hasSelection():
            self.font_weight = weight
            self.bold = weight >= 600
        self.update_text_format('weight', weight)

    def set_bold(self, state):
        self.set_font_weight(700 if state else 400)

    def set_text_opacity(self, percent) -> None:
        try:
            percent = float(percent)
        except (TypeError, ValueError):
            percent = 100.0
        self.setOpacity(max(0.0, min(100.0, percent)) / 100.0)
        self.update()

    def set_italic(self, state):
        if not self.textCursor().hasSelection():
            self.italic = state
        self.update_text_format('italic', state)

    def set_underline(self, state):
        if not self.textCursor().hasSelection():
            self.underline = state
        self.update_text_format('underline', state)

    def apply_all_attributes(self):
        self.set_font(self.font_family, self.font_size)
        # Keep a saved gradient after text edits/reloads instead of silently
        # flattening it to the first stop.
        if getattr(self, 'fill_style', {}).get('mode') == 'gradient':
            self.set_fill_style(self.fill_style)
        else:
            self.set_color(self.text_color)
        self.set_outline(self.outline_color, self.outline_width)
        self.set_font_weight(self.font_weight)
        self.set_italic(self.italic)
        self.set_underline(self.underline)
        self.set_letter_spacing(self.letter_spacing)
        self.set_line_spacing(self.line_spacing)
        self.update_text_width()
        self.set_alignment(self.alignment)

    def mouseDoubleClickEvent(self, event):
        if not self.editing_mode:
            self.enter_editing_mode()
            if self.layout:
                hit = self.layout.hitTest(event.pos(), None)
                cursor = self.textCursor()
                cursor.setPosition(hit)
                self.setTextCursor(cursor)
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        # Handle single clicks in editing mode for vertical text
        if self.editing_mode and self.layout and event.button() == Qt.MouseButton.LeftButton:
            hit = self.layout.hitTest(event.pos(), None)
            cursor = self.textCursor()
            
            # Check if shift is pressed for selection
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._drag_select_anchor = cursor.anchor()
                cursor.setPosition(hit, QTextCursor.MoveMode.KeepAnchor)
            else:
                cursor.setPosition(hit)
                self._drag_select_anchor = hit
            
            self._drag_selecting = True
            self.setTextCursor(cursor)
            self.setFocus()
            event.accept()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event):

        if (
            not self.editing_mode
            and event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
        ):
            self.delete_requested.emit(self)
            event.accept()
            return

        if self.editing_mode and self.vertical:
            key = event.key()
            modifiers = event.modifiers()
            
            if key == Qt.Key.Key_Down:
                # Down arrow in vertical text = move to next character
                cursor = self.textCursor()
                move_mode = QTextCursor.MoveMode.KeepAnchor if (modifiers & Qt.KeyboardModifier.ShiftModifier) else QTextCursor.MoveMode.MoveAnchor
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, move_mode)
                self.setTextCursor(cursor)
                event.accept()
                return
            elif key == Qt.Key.Key_Up:
                # Up arrow in vertical text = move to previous character
                cursor = self.textCursor()
                move_mode = QTextCursor.MoveMode.KeepAnchor if (modifiers & Qt.KeyboardModifier.ShiftModifier) else QTextCursor.MoveMode.MoveAnchor
                cursor.movePosition(QTextCursor.MoveOperation.PreviousCharacter, move_mode)
                self.setTextCursor(cursor)
                event.accept()
                return
            elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and not (
                modifiers & (
                    Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.AltModifier
                    | Qt.KeyboardModifier.MetaModifier
                )
            ):
                # Left/Right arrow in vertical text = move between paragraphs (visual columns),
                # keeping the same in-block offset when possible.
                cursor = self.textCursor()
                move_mode = QTextCursor.MoveMode.KeepAnchor if (modifiers & Qt.KeyboardModifier.ShiftModifier) else QTextCursor.MoveMode.MoveAnchor

                # Prefer layout-aware movement (handles wrapped columns).
                if self.layout and hasattr(self.layout, "move_cursor_between_columns"):
                    column_delta = 1 if key == Qt.Key.Key_Left else -1
                    new_pos = self.layout.move_cursor_between_columns(cursor.position(), column_delta)
                    if new_pos is not None and new_pos != cursor.position():
                        cursor.setPosition(new_pos, move_mode)
                        self.setTextCursor(cursor)
                        event.accept()
                        return

                # Fallback: treat each QTextBlock as a vertical "line" and move between them.
                block = cursor.block()
                target_block = block.next() if key == Qt.Key.Key_Left else block.previous()
                if target_block.isValid():
                    offset_in_block = cursor.position() - block.position()
                    target_offset = min(offset_in_block, max(0, target_block.length() - 1))
                    new_pos = target_block.position() + target_offset
                    if new_pos != cursor.position():
                        cursor.setPosition(new_pos, move_mode)
                        self.setTextCursor(cursor)
                        event.accept()
                        return
            
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                # Use the current character format as the new block's char format so empty paragraphs
                # keep the same font metrics (Qt can otherwise fall back to a tiny default).
                # Currently only necessary for vertical text layouts.
                cursor = self.textCursor()
                inherited_char_format = QTextCharFormat(cursor.charFormat())
                inherited_block_format = cursor.blockFormat()
                inherited_block_char_format = QTextCharFormat(inherited_char_format)

                # Ensure we always carry a valid point size/font for layout metrics.
                if inherited_block_char_format.fontPointSize() <= 0:
                    inherited_block_char_format.setFontPointSize(max(1, float(self.font_size)))
                font = inherited_block_char_format.font()
                if font.pointSizeF() <= 0:
                    font = self.document().defaultFont()
                    if font.pointSizeF() <= 0:
                        font.setPointSizeF(max(1.0, float(self.font_size)))
                    inherited_block_char_format.setFont(font)

                cursor.beginEditBlock()
                if cursor.hasSelection():
                    cursor.removeSelectedText()

                # Create a new paragraph that keeps the current paragraph + char formatting.
                cursor.insertBlock(inherited_block_format, inherited_block_char_format)
                cursor.setCharFormat(inherited_char_format)

                cursor.endEditBlock()
                self.setTextCursor(cursor)
                event.accept()
                return
        
        # Default handling for all other cases
        super().keyPressEvent(event)

    def enter_editing_mode(self):
        self.editing_mode = True
        self._invalidate_layer_effect_cache()
        self.setCacheMode(QGraphicsItem.CacheMode.NoCache)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setCursor(QCursor(Qt.CursorShape.IBeamCursor))
        self.setFocus()

    def exit_editing_mode(self):
        self.editing_mode = False
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.setPosition(
                cursor.position(),
                QTextCursor.MoveMode.MoveAnchor,
            )
            self.setTextCursor(cursor)
        self.last_selection = None
        self._drag_selecting = False
        self._drag_select_anchor = None
        self._invalidate_layer_effect_cache()
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setFlag(QGraphicsTextItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.clearFocus()
        self.update()

    def _on_text_changed(self):
        self._invalidate_layer_effect_cache()
        if self._applying_word_gradient:
            self.update()
            return
        new_text = self.toPlainText()
        self.text_changed.emit(new_text)
        self.update_outlines()
        self._schedule_word_gradient_refresh()

    def mouseMoveEvent(self, event):
        # Resize/rotate/move logic is now handled by EventHandler and QGraphicsView
        if self.editing_mode and self.layout and (event.buttons() & Qt.MouseButton.LeftButton) and self._drag_selecting:
            hit = self.layout.hitTest(event.pos(), None)
            anchor = self._drag_select_anchor
            if anchor is None:
                anchor = self.textCursor().anchor()

            cursor = self.textCursor()
            cursor.setPosition(anchor)
            cursor.setPosition(hit, QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)
            event.accept()
            return

        if self.editing_mode:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.editing_mode and self.layout and event.button() == Qt.MouseButton.LeftButton:
            self._drag_selecting = False
            self._drag_select_anchor = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        super().contextMenuEvent(event)
        if self.editing_mode:
            self.enter_editing_mode()
    
    def handleDeselection(self):
        if self.editing_mode:
            self.exit_editing_mode()
        if self.selected:
            self.setSelected(False)
            self.selected = False
            self.item_deselected.emit()
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.update()

    def init_resize(self, scene_pos: QPointF):
        self.resizing = True
        self.resize_start = scene_pos
        self._schedule_word_gradient_refresh()

    def init_rotation(self, scene_pos):
        self.rotating = True
        center = self.boundingRect().center()
        self.center_scene_pos = self.mapToScene(center)
        self.last_rotation_angle = math.degrees(math.atan2(
            scene_pos.y() - self.center_scene_pos.y(),
            scene_pos.x() - self.center_scene_pos.x()
        ))

    def move_item(self, local_pos: QPointF, last_local_pos: QPointF):
        delta = self.mapToParent(local_pos) - self.mapToParent(last_local_pos)
        new_pos = self.pos() + delta
        
        # Calculate the bounding rect of the rotated rectangle in scene coordinates
        scene_rect = self.mapToScene(self.boundingRect())
        bounding_rect = scene_rect.boundingRect()
        
        # Get constraint bounds
        parent_rect = None
        
        # Check if we're in webtoon mode by looking for the lazy webtoon manager
        scene = self.scene()
        if scene and scene.views():
            parent_rect = scene.sceneRect()
        
        # Constrain the movement
        if bounding_rect.left() + delta.x() < parent_rect.left():
            new_pos.setX(self.pos().x() - (bounding_rect.left() - parent_rect.left()))
        elif bounding_rect.right() + delta.x() > parent_rect.right():
            new_pos.setX(self.pos().x() + parent_rect.right() - bounding_rect.right())
        
        if bounding_rect.top() + delta.y() < parent_rect.top():
            new_pos.setY(self.pos().y() - (bounding_rect.top() - parent_rect.top()))
        elif bounding_rect.bottom() + delta.y() > parent_rect.bottom():
            new_pos.setY(self.pos().y() + parent_rect.bottom() - bounding_rect.bottom())
        
        self.setPos(new_pos)

    def rotate_item(self, scene_pos):
        self.setTransformOriginPoint(self.boundingRect().center())
        current_angle = math.degrees(math.atan2(
            scene_pos.y() - self.center_scene_pos.y(),
            scene_pos.x() - self.center_scene_pos.x()
        ))
        
        angle_diff = current_angle - self.last_rotation_angle
        
        if angle_diff > 180:
            angle_diff -= 360
        elif angle_diff < -180:
            angle_diff += 360
        
        smoothed_angle = angle_diff / self.rotation_smoothing
        
        new_rotation = self.rotation() + smoothed_angle
        self.setRotation(new_rotation)
        self.last_rotation_angle = current_angle

    def resize_item(self, scene_pos: QPointF):
        if not self.resize_start:
            return

        # Calculate delta from start position in scene coordinates
        scene_start = self.resize_start
        scene_delta = scene_pos - scene_start

        # Counter-rotate the delta to align it with the item's unrotated coordinate system
        angle_rad = math.radians(-self.rotation())
        rotated_delta_x = scene_delta.x() * math.cos(angle_rad) - scene_delta.y() * math.sin(angle_rad)
        rotated_delta_y = scene_delta.x() * math.sin(angle_rad) + scene_delta.y() * math.cos(angle_rad)
        rotated_delta = QPointF(rotated_delta_x, rotated_delta_y)

        # Get the current rect and create a new one to modify
        rect = self.interaction_rect()
        new_rect = QRectF(rect)
        original_height = rect.height()

        # Apply the delta based on which handle is being dragged
        if self.resize_handle in ['left', 'top_left', 'bottom_left']:
            new_rect.setLeft(rect.left() + rotated_delta.x())
        if self.resize_handle in ['right', 'top_right', 'bottom_right']:
            new_rect.setRight(rect.right() + rotated_delta.x())
        if self.resize_handle in ['top', 'top_left', 'top_right']:
            new_rect.setTop(rect.top() + rotated_delta.y())
        if self.resize_handle in ['bottom', 'bottom_left', 'bottom_right']:
            new_rect.setBottom(rect.bottom() + rotated_delta.y())

        # Ensure minimum size
        min_size = 10
        if new_rect.width() < min_size:
            if 'left' in self.resize_handle: new_rect.setLeft(new_rect.right() - min_size)
            else: new_rect.setRight(new_rect.left() + min_size)
        if new_rect.height() < min_size:
            if 'top' in self.resize_handle: new_rect.setTop(new_rect.bottom() - min_size)
            else: new_rect.setBottom(new_rect.top() + min_size)

        # Determine constraint bounds
        constraint_rect = None
        scene = self.scene()
        
        if scene and scene.views():
            constraint_rect = scene.sceneRect()
        
        if constraint_rect:
            # Map the proposed new local rect to the scene to get its final footprint
            prospective_scene_rect = self.mapRectToScene(new_rect)

            # Check if the resize would push the item outside the constraint bounds
            if (prospective_scene_rect.left() < constraint_rect.left() or
                prospective_scene_rect.right() > constraint_rect.right() or
                prospective_scene_rect.top() < constraint_rect.top() or
                prospective_scene_rect.bottom() > constraint_rect.bottom()):
                return  # Abort the resize operation

        # Calculate the required shift in the parent's coordinate system.
        pos_delta = self.mapToParent(new_rect.topLeft()) - self.mapToParent(rect.topLeft())
        new_pos = self.pos() + pos_delta

        self.setPos(new_pos)

        if self.vertical:
            if self.layout:
                self.layout.set_max_size(new_rect.width(), new_rect.height())
        else: # Horizontal logic
            self.setTextWidth(new_rect.width())
            # Keep re-flowable boxes pinned to the new width so later relayouts
            # (e.g. while editing) don't snap back to the old wrap width.
            if getattr(self, "_fixed_wrap_width", None) is not None:
                self._fixed_wrap_width = new_rect.width()
            if original_height > 0:
                height_ratio = new_rect.height() / original_height
                if height_ratio > 0:
                    new_font_size = self.font_size * height_ratio
                    # Ensure minimum font size of 1pt.
                    if new_font_size >= 1:
                        self.font_size = new_font_size
                        self.set_font_size(new_font_size)
                    else:
                        # If font would become invalid, stop the resize.
                        return

        self.resize_start = scene_pos

    def on_selection_changed(self):
        cursor = self.textCursor()
        properties = self.get_selected_text_properties(cursor)
        if self.editing_mode:
            self.text_highlighted.emit(properties)

    def get_selected_text_properties(self, cursor: QTextCursor):
        if not cursor.hasSelection():
            return {
                'font_family': self.font_family,
                'font_size': self.font_size,
                'bold': self.bold,
                'font_weight': self.font_weight,
                'italic': self.italic,
                'underline': self.underline,
                'opacity': round(self.opacity() * 100),
                'text_color': self.text_color.name(),
                'alignment': self.alignment,
                'outline': self.outline,
                'outline_color': self.outline_color.name() if self.outline_color else None,
                'outline_width': self.outline_width,
            }

        start = cursor.selectionStart()
        end = cursor.selectionEnd()

        # Find all selections that completely contain the current selection
        containing_outlines = [
            outline for outline in self.selection_outlines
            if outline.start <= start and outline.end >= end
        ]

        # Get outline properties from the last (most recent) containing selection
        outline_properties = None
        if containing_outlines:
            latest_outline = containing_outlines[-1]  # Get the last one from the list
            outline_properties = {
                'outline': True,
                'outline_color': latest_outline.color.name(),
                'outline_width': latest_outline.width
            }
        else:
            outline_properties = {
                'outline': False,
                'outline_color': None,
                'outline_width': None
            }

        # Create a new cursor for traversing the selection
        format_cursor = QTextCursor(cursor)

        # Initialize properties with default values
        properties = {
            'font_family': set(),
            'font_size': set(),
            'font_weight': set(),
            'bold': True,
            'italic': True,
            'underline': True,
            'text_color': set(),
            'alignment': None,
        }

        # Get initial block format for alignment
        format_cursor.setPosition(start)
        properties['alignment'] = format_cursor.blockFormat().alignment()

        # Iterate through the selection one character at a time
        for pos in range(start, end):
            format_cursor.setPosition(pos)
            format_cursor.setPosition(pos + 1, QTextCursor.KeepAnchor)
            char_format = format_cursor.charFormat()

            # Update properties
            properties['font_family'].add(char_format.font().family())
            properties['font_size'].add(char_format.fontPointSize())
            properties['font_weight'].add(char_format.fontWeight())
            properties['bold'] &= char_format.font().bold()
            properties['italic'] &= char_format.font().italic()
            properties['underline'] &= char_format.font().underline()
            properties['text_color'].add(char_format.foreground().color().name())

        # Convert sets to single values if all elements are the same, otherwise set to None
        for key, value in properties.items():
            if isinstance(value, set):
                properties[key] = list(value)[0] if len(value) == 1 else None

        # Merge outline properties with other properties
        properties.update(outline_properties)
        properties['opacity'] = round(self.opacity() * 100)
        properties['letter_spacing'] = self.letter_spacing
        properties['line_spacing'] = self.line_spacing

        return properties
    
    def __copy__(self):
        cls = self.__class__
        new_instance = cls(
            text=self.toHtml(),
            font_family=self.font_family,
            font_size=self.font_size,
            render_color=self.text_color,
            alignment=self.alignment,
            line_spacing=self.line_spacing,
            letter_spacing=self.letter_spacing,
            outline_color=self.outline_color,
            outline_width=self.outline_width,
            bold=self.bold,
            font_weight=self.font_weight,
            italic=self.italic,
            underline=self.underline,
            opacity=self.opacity(),
        )
        
        new_instance.set_text(self.toHtml(), self.boundingRect().width())
        new_instance.setTransformOriginPoint(self.transformOriginPoint())
        new_instance.setPos(self.pos())
        new_instance.setRotation(self.rotation())
        new_instance.setScale(self.scale())
        new_instance.__dict__.update(copy.copy(self.__dict__))
        return new_instance


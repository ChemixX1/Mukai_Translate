from dataclasses import dataclass, field
from typing import Optional, List, Any
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt
from app.ui.canvas.text_item import OutlineType

@dataclass
class TextItemProperties:
    """Dataclass for TextBlockItem properties to reduce duplication in construction"""
    text: str = ""
    font_family: str = ""
    font_size: float = 20
    text_color: QColor = None
    alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter
    line_spacing: float = 1.2
    letter_spacing: float = 0.0
    outline_color: Optional[QColor] = None
    outline_width: float = 1
    outline: bool = False
    bold: bool = False
    font_weight: Optional[int] = None
    italic: bool = False
    underline: bool = False
    opacity: float = 1.0
    direction: Qt.LayoutDirection = Qt.LayoutDirection.LeftToRight
    
    # Position and transformation properties
    position: tuple = (0, 0)  # (x, y)
    rotation: float = 0
    scale: float = 1.0
    transform_origin: Optional[tuple] = None  # (x, y)
    
    # Layout properties
    width: Optional[float] = None
    height: Optional[float] = None
    vertical: bool = False
    # When set, the box keeps this wrap width so auto-generated text re-flows
    # when the box is resized instead of staying on baked-in line breaks.
    fixed_wrap_width: Optional[float] = None
    
    # Advanced properties
    selection_outlines: list = field(default_factory=list)
    fill_style: dict = field(default_factory=dict)
    warp: dict = field(default_factory=dict)
            
    @classmethod
    def from_dict(cls, data: dict) -> 'TextItemProperties':
        """Create TextItemProperties from dictionary state"""
        props = cls()
        
        # Basic text properties
        props.text = data.get('text', '')
        props.font_family = data.get('font_family', '')
        props.font_size = data.get('font_size', 20)
        props.line_spacing = data.get('line_spacing', 1.2)
        props.letter_spacing = data.get('letter_spacing', 0.0)
        props.bold = data.get('bold', False)
        raw_weight = data.get('font_weight')
        props.font_weight = int(
            raw_weight if raw_weight is not None else (700 if props.bold else 400)
        )
        props.italic = data.get('italic', False)
        props.underline = data.get('underline', False)
        raw_opacity = float(data.get('opacity', 1.0))
        props.opacity = max(0.0, min(1.0, raw_opacity / 100.0 if raw_opacity > 1.0 else raw_opacity))
        
        # Color properties
        if 'text_color' in data:
            if isinstance(data['text_color'], QColor):
                props.text_color = data['text_color']
            elif data['text_color'] is not None:
                props.text_color = QColor(data['text_color'])
        
        if 'outline_color' in data:
            if isinstance(data['outline_color'], QColor):
                props.outline_color = data['outline_color']
            elif data['outline_color']:
                props.outline_color = QColor(data['outline_color'])
                
        props.outline_width = data.get('outline_width', 1)
        if 'outline' in data:
            props.outline = bool(data.get('outline', False))
        else:
            props.outline = _has_full_document_outline(data.get('selection_outlines', []))
        
        # Alignment
        if 'alignment' in data:
            if isinstance(data['alignment'], int):
                props.alignment = Qt.AlignmentFlag(data['alignment'])
            else:
                props.alignment = data['alignment']
                
        # Direction – stored as Qt.LayoutDirection enum but may arrive as a plain
        # integer after JSON round-trips (RightToLeft=1, LeftToRight=0).
        if 'direction' in data:
            dir_val = data['direction']
            if isinstance(dir_val, int):
                try:
                    props.direction = Qt.LayoutDirection(dir_val)
                except (ValueError, KeyError):
                    props.direction = Qt.LayoutDirection.LeftToRight
            else:
                props.direction = dir_val
            
        # Position and transformation
        props.position = data.get('position', (0, 0))
        props.rotation = data.get('rotation', 0)
        props.scale = data.get('scale', 1.0)
        props.transform_origin = data.get('transform_origin')
        
        # Layout
        props.width = data.get('width')
        props.height = data.get('height')
        props.vertical = data.get('vertical', False)
        props.fixed_wrap_width = data.get('fixed_wrap_width')
        
        # Advanced
        props.selection_outlines = data.get('selection_outlines', [])
        props.fill_style = data.get('fill_style', {}) if isinstance(data.get('fill_style', {}), dict) else {}
        raw_warp = data.get('warp')
        if not isinstance(raw_warp, dict):
            # Early development builds stored the deformation next to the
            # color definition.  Migrate that shape transparently.
            raw_warp = props.fill_style.get('warp', {})
        props.warp = raw_warp if isinstance(raw_warp, dict) else {}
        
        return props
    
    @classmethod
    def from_text_item(cls, item) -> 'TextItemProperties':
        """Create TextItemProperties from an existing TextBlockItem"""
        props = cls()
        
        # Basic text properties
        props.text = item.toHtml()
        props.font_family = item.font_family
        props.font_size = item.font_size
        props.text_color = item.text_color
        props.alignment = item.alignment
        props.line_spacing = item.line_spacing
        props.letter_spacing = getattr(item, 'letter_spacing', 0.0)
        props.outline_color = item.outline_color
        props.outline_width = item.outline_width
        props.outline = bool(getattr(item, 'outline', False))
        props.bold = item.bold
        props.font_weight = int(getattr(item, 'font_weight', 700 if item.bold else 400))
        props.italic = item.italic
        props.underline = item.underline
        props.opacity = float(item.opacity())
        props.direction = item.direction
        
        # Position and transformation
        props.position = (item.pos().x(), item.pos().y())
        props.rotation = item.rotation()
        props.scale = item.scale()
        if hasattr(item, 'transformOriginPoint'):
            origin = item.transformOriginPoint()
            props.transform_origin = (origin.x(), origin.y())
        
        # Layout properties
        # Do not serialise visual layer-effect margins as part of the editable
        # text area. They are paint effects, not a resize of the text box.
        props.width = item.textWidth() if item.textWidth() > 0 else item.document().size().width()
        props.height = item.document().size().height()
        props.vertical = getattr(item, 'vertical', False)
        props.fixed_wrap_width = getattr(item, '_fixed_wrap_width', None)
        
        # Advanced properties
        props.selection_outlines = getattr(item, 'selection_outlines', []).copy()
        props.fill_style = item.get_fill_style() if hasattr(item, 'get_fill_style') else {}
        props.warp = item.get_text_warp() if hasattr(item, 'get_text_warp') else {}
        
        return props
    
    def to_dict(self) -> dict:
        """Convert TextItemProperties to dictionary"""
        return {
            'text': self.text,
            'font_family': self.font_family,
            'font_size': self.font_size,
            'text_color': self.text_color,
            'alignment': self.alignment,
            'line_spacing': self.line_spacing,
            'letter_spacing': self.letter_spacing,
            'outline_color': self.outline_color,
            'outline_width': self.outline_width,
            'outline': self.outline,
            'bold': self.bold,
            'font_weight': self.font_weight if self.font_weight is not None else (700 if self.bold else 400),
            'italic': self.italic,
            'underline': self.underline,
            'opacity': self.opacity,
            'direction': self.direction,
            'position': self.position,
            'rotation': self.rotation,
            'scale': self.scale,
            'transform_origin': self.transform_origin,
            'width': self.width,
            'height': self.height,
            'vertical': self.vertical,
            'fixed_wrap_width': self.fixed_wrap_width,
            'selection_outlines': self.selection_outlines,
            'fill_style': self.fill_style,
            'warp': self.warp,
        }


def _has_full_document_outline(selection_outlines: list) -> bool:
    for outline in selection_outlines or []:
        outline_type = outline.get('type') if isinstance(outline, dict) else getattr(outline, 'type', None)
        if outline_type == OutlineType.Full_Document:
            return True
        if isinstance(outline_type, str) and outline_type.lower() == "full_document":
            return True
    return False

import weakref

from PySide6.QtGui import QUndoCommand
from .base import RectCommandBase

class TextFormatCommand(QUndoCommand, RectCommandBase):
    def __init__(self, viewer, old_item, new_item):
        super().__init__()
        self.scene = viewer._scene
        self.old_dict = old_item.__dict__.copy()
        self.new_dict = new_item.__dict__.copy()
        self.new_item_prp = self.save_txt_item_properties(new_item)
        self.old_item_prp = self.save_txt_item_properties(old_item)
        self.old_html = old_item.toHtml()
        self.new_html = new_item.toHtml()
        self._item_ref = weakref.ref(new_item)

    def _target_item(self, fallback_properties):
        """Prefer the original live item; geometry matching is a recovery path."""
        item = self._item_ref()
        if item is not None:
            try:
                if item.scene() is self.scene:
                    return item
            except RuntimeError:
                pass
        return self.find_matching_txt_item(self.scene, fallback_properties)

    def redo(self):
        matching_item = self._target_item(self.old_item_prp)
        if matching_item:
            matching_item.prepareGeometryChange()
            matching_item.set_text(self.new_html, self.new_item_prp.width)
            matching_item.__dict__.update(self.new_dict)
            matching_item.set_letter_spacing(self.new_item_prp.letter_spacing)
            matching_item.set_line_spacing(self.new_item_prp.line_spacing)
            matching_item.setOpacity(self.new_item_prp.opacity)
            matching_item._invalidate_layer_effect_cache()
            matching_item.setTransformOriginPoint(matching_item.boundingRect().center())
            matching_item.update()

    def undo(self):
        matching_item = self._target_item(self.new_item_prp)
        if matching_item:
            matching_item.prepareGeometryChange()
            matching_item.set_text(self.old_html, self.old_item_prp.width)
            matching_item.__dict__.update(self.old_dict)
            matching_item.set_letter_spacing(self.old_item_prp.letter_spacing)
            matching_item.set_line_spacing(self.old_item_prp.line_spacing)
            matching_item.setOpacity(self.old_item_prp.opacity)
            matching_item._invalidate_layer_effect_cache()
            matching_item.setTransformOriginPoint(matching_item.boundingRect().center())
            matching_item.update()

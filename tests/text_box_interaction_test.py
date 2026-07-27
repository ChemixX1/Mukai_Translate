import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.canvas.image_viewer import ImageViewer
from app.ui.canvas.text.text_item_properties import TextItemProperties


class TextBoxInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.host = QtWidgets.QWidget()
        self.viewer = ImageViewer(self.host)
        page = QtGui.QPixmap(800, 1200)
        page.fill(QtGui.QColor("white"))
        self.viewer.setPhoto(page, fit=False)

    def _styled_item(self):
        properties = TextItemProperties(
            text="Prueba",
            font_family="Arial",
            font_size=24,
            text_color=QtGui.QColor("#123456"),
            position=(100, 100),
            rotation=17,
            width=220,
            fill_style={
                "mode": "solid",
                "color": "#ff123456",
                "glow": {"enabled": True},
            },
        )
        item = self.viewer.add_text_item(properties)
        item.setSelected(True)
        return item

    def test_copy_and_paste_duplicates_the_complete_box_state(self):
        self._styled_item()
        emitted = []
        self.viewer.command_emitted.connect(emitted.append)

        copy_event = QtGui.QKeyEvent(
            QtCore.QEvent.Type.KeyPress,
            QtCore.Qt.Key.Key_C,
            QtCore.Qt.KeyboardModifier.ControlModifier,
        )
        paste_event = QtGui.QKeyEvent(
            QtCore.QEvent.Type.KeyPress,
            QtCore.Qt.Key.Key_V,
            QtCore.Qt.KeyboardModifier.ControlModifier,
        )
        self.viewer.keyPressEvent(copy_event)
        self.viewer.keyPressEvent(paste_event)

        self.assertTrue(copy_event.isAccepted())
        self.assertTrue(paste_event.isAccepted())
        self.assertEqual(len(emitted), 1)
        emitted[0].redo()

        self.assertEqual(len(self.viewer.text_items), 2)
        pasted = self.viewer.get_selected_text_items()[0]
        self.assertEqual(pasted.toPlainText(), "Prueba")
        self.assertEqual(pasted.rotation(), 17)
        self.assertTrue(pasted.get_fill_style()["glow"]["enabled"])
        self.assertEqual(pasted.pos(), QtCore.QPointF(112, 112))

        emitted[0].undo()
        self.assertEqual(len(self.viewer.text_items), 1)

    def test_rotation_control_is_visible_below_and_has_a_precise_hit_area(self):
        item = self._styled_item()
        self.viewer.setTransform(QtGui.QTransform.fromScale(0.1, 0.1))
        view_scale = self.viewer.interaction_manager._text_item_view_scale(item)
        center = item.rotation_handle_center(view_scale)

        self.assertGreater(center.y(), item.interaction_rect().bottom())
        self.assertGreater(item.boundingRect().bottom(), center.y())
        self.assertFalse(item.shape().contains(center))
        self.assertTrue(
            self.viewer.interaction_manager._in_rotate_ring(
                item,
                item.mapToScene(center),
            )
        )
        outside = center + QtCore.QPointF(40.0 / view_scale, 0)
        self.assertFalse(
            self.viewer.interaction_manager._in_rotate_ring(
                item,
                item.mapToScene(outside),
            )
        )


if __name__ == "__main__":
    unittest.main()

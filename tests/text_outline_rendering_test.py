import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.canvas.text_item import TextBlockItem


class TextOutlineRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        font_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "resources",
            "fonts",
            "NotoSansJP-Black.otf",
        )
        font_id = QtGui.QFontDatabase.addApplicationFont(font_path)
        families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
        cls.font_family = families[0] if families else ""

    def _render_alpha(self, outline_width: float) -> np.ndarray:
        scene = QtWidgets.QGraphicsScene()
        outline_color = QtGui.QColor("black") if outline_width else None
        item = TextBlockItem(
            text="T,Y ty,",
            font_family=self.font_family,
            font_size=92,
            render_color=QtGui.QColor("white"),
            outline_color=outline_color,
            outline_width=outline_width,
            bold=True,
        )
        item.set_text("T,Y ty,", 620)
        item.set_outline(outline_color, outline_width)
        item.setPos(55, 35)
        scene.addItem(item)
        scene.setSceneRect(0, 0, 760, 260)

        image = QtGui.QImage(
            760,
            260,
            QtGui.QImage.Format.Format_RGBA8888,
        )
        image.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
        scene.render(painter)
        painter.end()
        rgba = np.frombuffer(bytes(image.bits()), dtype=np.uint8).reshape(
            image.height(), image.bytesPerLine() // 4, 4
        )
        return rgba[:, :image.width(), 3].copy()

    def test_thick_outline_has_no_diagonally_displaced_glyph_copies(self):
        width = 12.0
        fill = self._render_alpha(0) > 16
        outlined = self._render_alpha(width) > 16
        outside = outlined & ~fill
        distance_from_fill = cv2.distanceTransform(
            (~fill).astype(np.uint8),
            cv2.DIST_L2,
            5,
        )

        self.assertTrue(np.any(outside))
        # A single vector stroke extends about `width` pixels from the glyph.
        # The former eight-copy method reached sqrt(2) * width at diagonals,
        # which is the visible forked-comma/T/Y defect this guards against.
        self.assertLessEqual(
            float(np.quantile(distance_from_fill[outside], 0.999)),
            width + 2.0,
        )


if __name__ == "__main__":
    unittest.main()

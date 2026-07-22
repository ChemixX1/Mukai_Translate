"""Deterministic verification for editable 3D and perspective text effects."""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.canvas.save_renderer import ImageSaveRenderer
from app.ui.canvas.text.text_item_properties import TextItemProperties
from app.ui.canvas.text_3d import (
    SUPPORTED_TEXT_3D_STYLES,
    alpha_composite_rgba,
    render_text_3d,
)
from app.ui.canvas.text_item import TextBlockItem
from app.ui.canvas.text_warp import qimage_to_rgba_array, rgba_array_to_qimage
from app.ui.text_effects_panel import TextEffectsPanel
from app.ui.text_fill_dialog import TextFillDialog


OUTPUT = ROOT / "build" / "text-3d-verification.png"
PANEL_OUTPUT = ROOT / "build" / "text-3d-panel-verification.png"


def _load_font() -> str:
    for path in (ROOT / "resources" / "fonts").glob("*"):
        if path.suffix.lower() not in {".ttf", ".ttc", ".otf"}:
            continue
        font_id = QtGui.QFontDatabase.addApplicationFont(str(path))
        families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
        if families:
            return families[0]
    return QtWidgets.QApplication.font().family()


def _source(font_family: str) -> tuple[np.ndarray, np.ndarray]:
    size = QtCore.QSize(700, 230)
    content = QtGui.QImage(size, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    mask = QtGui.QImage(size, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    content.fill(QtCore.Qt.GlobalColor.transparent)
    mask.fill(QtCore.Qt.GlobalColor.transparent)
    font = QtGui.QFont(font_family)
    font.setPixelSize(126)
    font.setWeight(QtGui.QFont.Weight.Black)
    path = QtGui.QPainterPath()
    path.addText(QtCore.QPointF(0, 0), font, "MUKAI")
    bounds = path.boundingRect()
    path.translate(
        (size.width() - bounds.width()) / 2.0 - bounds.left(),
        (size.height() - bounds.height()) / 2.0 - bounds.top(),
    )
    painter = QtGui.QPainter(content)
    gradient = QtGui.QLinearGradient(0, 0, size.width(), size.height())
    gradient.setColorAt(0.0, QtGui.QColor("#ff315e"))
    gradient.setColorAt(0.55, QtGui.QColor("#a441ff"))
    gradient.setColorAt(1.0, QtGui.QColor("#43d9ff"))
    painter.fillPath(path, gradient)
    painter.end()
    painter = QtGui.QPainter(mask)
    painter.fillPath(path, QtCore.Qt.GlobalColor.white)
    painter.end()
    return qimage_to_rgba_array(content), qimage_to_rgba_array(mask)


def _visual(font_family: str) -> None:
    source, mask = _source(font_family)
    labels = {
        "extrude": "Extrusión 3D",
        "perspective_left": "Perspectiva izquierda",
        "perspective_right": "Perspectiva derecha",
        "perspective_up": "Perspectiva superior",
        "perspective_down": "Perspectiva inferior",
        "flare_left": "Expandir extremo izquierdo",
        "flare_right": "Expandir extremo derecho",
        "skew_left": "Diagonal izquierda",
        "skew_right": "Diagonal derecha",
        "trapezoid": "Trapecio",
    }
    tile_w, tile_h = 480, 250
    rows = math.ceil(len(SUPPORTED_TEXT_3D_STYLES) / 2)
    canvas = QtGui.QImage(tile_w * 2, tile_h * rows, QtGui.QImage.Format.Format_ARGB32)
    canvas.fill(QtGui.QColor("#15151a"))
    painter = QtGui.QPainter(canvas)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
    font = QtGui.QFont(font_family)
    font.setPixelSize(17)
    font.setWeight(QtGui.QFont.Weight.Bold)
    painter.setFont(font)

    for index, style in enumerate(SUPPORTED_TEXT_3D_STYLES):
        effect = {
            "enabled": True,
            "style": style,
            "strength": 68,
            "extrude": True,
            "depth": 24,
            "angle": 45,
            "color": "#ff722b45",
            "bevel": 42,
        }
        transformed, _mask, extrusion, bevel, _px, _py = render_text_3d(source, mask, effect)
        composite = alpha_composite_rgba(extrusion, transformed)
        composite = alpha_composite_rgba(composite, bevel)
        assert composite.shape[0] >= source.shape[0]
        assert np.count_nonzero(composite[..., 3]) > 0
        image = rgba_array_to_qimage(composite)

        col, row = index % 2, index // 2
        tile = QtCore.QRectF(col * tile_w + 10, row * tile_h + 10, tile_w - 20, tile_h - 20)
        painter.setPen(QtGui.QPen(QtGui.QColor("#35353e"), 1))
        painter.setBrush(QtGui.QColor("#202027"))
        painter.drawRoundedRect(tile, 10, 10)
        painter.setPen(QtGui.QColor("#f2f2f5"))
        painter.drawText(tile.adjusted(12, 8, -12, -8), labels[style])
        target_area = tile.adjusted(12, 36, -12, -10)
        fitted = QtCore.QSizeF(image.size())
        fitted.scale(target_area.size(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        target = QtCore.QRectF(QtCore.QPointF(), fitted)
        target.moveCenter(target_area.center())
        painter.drawImage(target, image)
    painter.end()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    assert canvas.save(str(OUTPUT))


def _state_dialog_and_save(font_family: str) -> None:
    three_d = {
        "enabled": True,
        "style": "flare_left",
        "strength": 62,
        "extrude": True,
        "depth": 19,
        "angle": 38,
        "color": "#ff722b45",
        "bevel": 35,
    }
    style = {
        "mode": "solid",
        "color": "#ffffffff",
        "three_d": three_d,
        "warp": {
            "enabled": True,
            "style": "arc",
            "bend": 28,
            "horizontal": 0,
            "vertical": 0,
            "orientation": "horizontal",
        },
        "glow": {
            "enabled": True,
            "color": "#ff00e5ff",
            "opacity": 65,
            "spread": 20,
            "size": 8,
        },
    }
    dialog = TextFillDialog(style)
    result = dialog.fill_style()
    assert result["three_d"] == three_d
    assert not hasattr(dialog, "three_d_style")
    dialog.close()

    panel = TextEffectsPanel()
    panel.set_selection("MUKAI", result)
    assert len(panel.three_d_preset_buttons) == len(SUPPORTED_TEXT_3D_STYLES)
    assert panel.three_d_preset_buttons["flare_left"].isChecked()
    panel.resize(320, 800)
    panel.pages.setCurrentIndex(2)
    panel.category_buttons[2].setChecked(True)
    panel.show()
    QtWidgets.QApplication.processEvents()
    assert panel.grab().save(str(PANEL_OUTPUT))
    panel.hide()

    item = TextBlockItem("MUKAI", font_family, 40, QtGui.QColor("white"), outline_color=None)
    item.set_text("MUKAI", 280)
    item.set_visual_style(result)
    assert item._has_text_3d()
    composite = item._warped_composite_images(4.0)
    assert composite is not None and composite[1].width() > 0
    state = TextItemProperties.from_text_item(item).to_dict()
    restored = TextItemProperties.from_dict(state)
    assert restored.fill_style["three_d"] == three_d

    state["position"] = (90, 80)
    base = np.full((320, 560, 3), 25, dtype=np.uint8)
    renderer = ImageSaveRenderer(base)
    renderer.add_state_to_image({"text_items_state": [state]})
    output = renderer.render_to_image()
    assert output.shape == base.shape and np.any(output != base)


def main() -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    font_family = _load_font()
    _visual(font_family)
    _state_dialog_and_save(font_family)
    app.processEvents()
    print(
        f"text_3d=ok\nstyles={len(SUPPORTED_TEXT_3D_STYLES)}"
        f"\nvisual={OUTPUT}\npanel={PANEL_OUTPUT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

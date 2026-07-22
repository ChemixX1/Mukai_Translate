"""Focused smoke test for editable text deformation and manual box deletion."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from app.controllers.psd_exporter import _build_text_layer
from app.controllers.psd_importer import _text_warp
from app.ui.canvas.save_renderer import ImageSaveRenderer
from app.ui.canvas.text.text_item_properties import TextItemProperties
from app.ui.canvas.text_item import TextBlockItem
from app.ui.canvas.text_warp import (
    SUPPORTED_WARP_STYLES,
    text_warp_backend,
    warp_qimage,
)
from app.ui.commands.box import DeleteBoxesCommand
from app.ui.text_effects_panel import TextEffectsPanel
from app.ui.text_fill_dialog import TextFillDialog


OUTPUT = ROOT / "build" / "text-warp-verification.png"


def _load_font() -> str:
    for path in (ROOT / "resources" / "fonts").glob("*"):
        if path.suffix.lower() not in {".ttf", ".ttc", ".otf"}:
            continue
        font_id = QtGui.QFontDatabase.addApplicationFont(str(path))
        families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
        if families:
            return families[0]
    return QtWidgets.QApplication.font().family()


def _source_image(font_family: str) -> QtGui.QImage:
    image = QtGui.QImage(720, 240, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
    font = QtGui.QFont(font_family)
    font.setPixelSize(128)
    font.setWeight(QtGui.QFont.Weight.Black)
    path = QtGui.QPainterPath()
    path.addText(QtCore.QPointF(0, 0), font, "MUKAI")
    bounds = path.boundingRect()
    path.translate(
        (image.width() - bounds.width()) / 2.0 - bounds.left(),
        (image.height() - bounds.height()) / 2.0 - bounds.top(),
    )
    gradient = QtGui.QLinearGradient(0, 0, image.width(), image.height())
    gradient.setColorAt(0.0, QtGui.QColor("#ff315e"))
    gradient.setColorAt(0.5, QtGui.QColor("#9a42ff"))
    gradient.setColorAt(1.0, QtGui.QColor("#43d9ff"))
    painter.fillPath(path, gradient)
    painter.end()
    return image


def _visual(font_family: str) -> None:
    source = _source_image(font_family)
    tile_w, tile_h = 450, 220
    rows = (len(SUPPORTED_WARP_STYLES) + 1) // 2
    canvas = QtGui.QImage(tile_w * 2, tile_h * rows, QtGui.QImage.Format.Format_ARGB32)
    canvas.fill(QtGui.QColor("#15151a"))
    painter = QtGui.QPainter(canvas)
    painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
    label_font = QtGui.QFont(font_family)
    label_font.setPixelSize(17)
    painter.setFont(label_font)
    labels = {
        "arc": "Arco",
        "arch": "Arco completo",
        "bulge": "Abombado",
        "shell_lower": "Concha inferior",
        "flag": "Bandera",
        "arc_upper": "Arco superior",
        "arc_lower": "Arco inferior",
        "wave": "Onda",
        "shell_upper": "Concha superior",
        "fish": "Pez",
        "rise": "Elevación",
        "fish_eye": "Ojo de pez",
        "inflate": "Inflar",
        "twist": "Giro",
        "squeeze": "Compresión",
    }
    for index, style in enumerate(SUPPORTED_WARP_STYLES):
        warped, _pad_x, _pad_y = warp_qimage(
            source,
            {
                "enabled": True,
                "style": style,
                "bend": 65,
                "horizontal": 0,
                "vertical": 0,
                "orientation": "horizontal",
            },
        )
        col, row = index % 2, index // 2
        tile = QtCore.QRectF(col * tile_w + 10, row * tile_h + 10, tile_w - 20, tile_h - 20)
        painter.setPen(QtGui.QPen(QtGui.QColor("#35353e"), 1))
        painter.setBrush(QtGui.QColor("#202027"))
        painter.drawRoundedRect(tile, 10, 10)
        painter.setPen(QtGui.QColor("#f2f2f5"))
        painter.drawText(tile.adjusted(12, 8, -12, -8), labels[style])
        target_area = tile.adjusted(14, 34, -14, -12)
        fitted = QtCore.QSizeF(warped.size())
        fitted.scale(target_area.size(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        target = QtCore.QRectF(QtCore.QPointF(), fitted)
        target.moveCenter(target_area.center())
        painter.drawImage(target, warped)
    painter.end()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    assert canvas.save(str(OUTPUT))


def _state_and_export(font_family: str) -> None:
    warp = {
        "enabled": True,
        "style": "wave",
        "bend": 42,
        "horizontal": 7,
        "vertical": -3,
        "orientation": "horizontal",
    }
    item = TextBlockItem("MUKAI", font_family, 34, QtGui.QColor("#ffffff"), outline_color=None)
    item.set_text("MUKAI", 260)
    item.set_text_warp(warp)
    state = TextItemProperties.from_text_item(item).to_dict()
    restored = TextItemProperties.from_dict(state)
    assert restored.warp == warp

    base = np.full((220, 420, 3), 30, dtype=np.uint8)
    state["position"] = (75, 70)
    renderer = ImageSaveRenderer(base)
    renderer.add_state_to_image({"text_items_state": [state]})
    rendered = renderer.render_to_image()
    assert rendered.shape == base.shape
    assert np.any(rendered != base)

    layer = _build_text_layer(state, 1)
    assert layer is not None and layer.has_warp
    assert _text_warp(layer) == warp

    for index, style_name in enumerate(SUPPORTED_WARP_STYLES, start=2):
        native_warp = {
            "enabled": True,
            "style": style_name,
            "bend": 36,
            "horizontal": 4,
            "vertical": -2,
            "orientation": "horizontal",
        }
        state["warp"] = native_warp
        native_layer = _build_text_layer(state, index)
        assert native_layer is not None and native_layer.has_warp
        assert _text_warp(native_layer) == native_warp

    # The live renderer now starts at 4x instead of the old fixed 2x source.
    item.set_text_warp(warp)
    low_quality = item._warped_composite_images(2.0)
    high_quality = item._warped_composite_images(4.0)
    assert low_quality is not None and high_quality is not None
    assert high_quality[1].width() > low_quality[1].width()


def _editor_roundtrip() -> None:
    style = {
        "mode": "solid",
        "color": "#ffffffff",
        "warp": {
            "enabled": True,
            "style": "arc_upper",
            "bend": 65,
            "horizontal": 0,
            "vertical": 0,
            "orientation": "horizontal",
        },
    }
    dialog = TextFillDialog(style)
    assert dialog.fill_style()["warp"] == style["warp"]
    assert not hasattr(dialog, "warp_style")
    dialog.close()

    panel = TextEffectsPanel()
    panel.set_selection("MUKAI", style)
    assert len(panel.warp_preset_buttons) == len(SUPPORTED_WARP_STYLES)
    assert panel.warp_preset_buttons["arc_upper"].isChecked()
    assert panel._style["warp"] == style["warp"]
    panel.close()


def _standalone_delete_undo(font_family: str) -> None:
    class Viewer:
        def __init__(self):
            self._scene = QtWidgets.QGraphicsScene()
            self.text_items = []
            self.rectangles = []
            self.selected_rect = None

        def add_text_item(self, properties):
            if isinstance(properties, dict):
                properties = TextItemProperties.from_dict(properties)
            text_item = TextBlockItem(
                properties.text,
                properties.font_family,
                properties.font_size,
                properties.text_color,
                properties.alignment,
                properties.line_spacing,
                properties.outline_color,
                properties.outline_width,
                properties.bold,
                properties.italic,
                properties.underline,
                properties.direction,
            )
            text_item.set_text(properties.text, properties.width)
            text_item.setPos(*properties.position)
            text_item.set_text_warp(properties.warp)
            self._scene.addItem(text_item)
            self.text_items.append(text_item)
            return text_item

    viewer = Viewer()
    item = TextBlockItem("Escribe algo", font_family, 20, QtGui.QColor("black"), outline_color=None)
    item.set_text("Escribe algo", 180)
    item.set_text_warp({"enabled": True, "style": "flag", "bend": 24})
    viewer._scene.addItem(item)
    viewer.text_items.append(item)
    main = SimpleNamespace(image_viewer=viewer, curr_tblock=None, curr_tblock_item=item)
    command = DeleteBoxesCommand(main, None, item, None, [])
    command.redo()
    assert item not in viewer.text_items and item.scene() is None
    command.undo()
    assert len(viewer.text_items) == 1 and viewer.text_items[0].scene() is viewer._scene


def main() -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    assert text_warp_backend() == "opencv-lanczos4"
    font_family = _load_font()
    _visual(font_family)
    _state_and_export(font_family)
    _editor_roundtrip()
    _standalone_delete_undo(font_family)
    app.processEvents()
    print(
        f"text_warp=ok\nbackend={text_warp_backend()}"
        f"\nstyles={len(SUPPORTED_WARP_STYLES)}\nvisual={OUTPUT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Deterministic smoke test for editable Photoshop-style text effects."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image, ImageChops, ImageDraw
from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.canvas.layer_effects import render_layer_effects
from app.ui.canvas.save_renderer import ImageSaveRenderer
from app.ui.canvas.text.text_item_properties import TextItemProperties
from app.ui.canvas.text_item import TextBlockItem
from app.ui.text_effects_panel import TextEffectsPanel
from app.ui.text_fill_dialog import TextFillDialog


STYLE = {
    "mode": "solid",
    "color": "#ffffffff",
    "glow": {
        "enabled": True,
        "color": "#ff00e5ff",
        "opacity": 88,
        "spread": 32,
        "size": 16,
    },
    "drop_shadow": {
        "enabled": True,
        "color": "#ff000000",
        "opacity": 55,
        "angle": 120,
        "distance": 8,
        "spread": 10,
        "size": 10,
    },
    "inner_glow": {
        "enabled": True,
        "color": "#ffffffff",
        "opacity": 35,
        "choke": 8,
        "size": 5,
    },
    "inner_shadow": {
        "enabled": True,
        "color": "#ff00111f",
        "opacity": 30,
        "angle": 120,
        "distance": 2,
        "choke": 5,
        "size": 4,
    },
    "stroke": {
        "enabled": True,
        "color": "#ff00ffff",
        "opacity": 80,
        "size": 2,
        "position": "outside",
    },
}


def _verify_mask_math() -> None:
    source = Image.new("L", (220, 140), 0)
    ImageDraw.Draw(source).rounded_rectangle((75, 42, 145, 98), 9, fill=255)
    glow_only = {"glow": STYLE["glow"]}
    behind, overlay = render_layer_effects(source, glow_only)
    alpha = behind.getchannel("A")
    overlap = ImageChops.multiply(alpha, source)
    if overlap.getextrema()[1] != 0:
        raise AssertionError("Outer glow painted a duplicate inside the source silhouette.")
    alpha_levels = sum(1 for count in alpha.histogram() if count)
    if alpha.getbbox() is None or alpha_levels < 40:
        raise AssertionError("Outer glow is not a continuous blurred alpha gradient.")
    if overlay.getbbox() is not None:
        raise AssertionError("Outer glow unexpectedly generated an inner overlay.")

    for effect_name in ("drop_shadow", "inner_glow", "inner_shadow"):
        behind, overlay = render_layer_effects(source, {effect_name: STYLE[effect_name]})
        rendered = behind if effect_name == "drop_shadow" else overlay
        if rendered.getchannel("A").getbbox() is None:
            raise AssertionError(f"Effect generated an empty mask: {effect_name}")
        if effect_name.startswith("inner_"):
            outside = ImageChops.multiply(rendered.getchannel("A"), ImageChops.invert(source))
            if outside.getextrema()[1] != 0:
                raise AssertionError(f"Inner effect escaped the text silhouette: {effect_name}")

    outside_stroke = dict(STYLE["stroke"], position="outside")
    behind, overlay = render_layer_effects(source, {"stroke": outside_stroke})
    if behind.getchannel("A").getbbox() is None or overlay.getbbox() is not None:
        raise AssertionError("Outside stroke was not isolated behind the text.")
    inside_overlap = ImageChops.multiply(behind.getchannel("A"), source)
    if inside_overlap.getextrema()[1] != 0:
        raise AssertionError("Outside stroke painted inside the text silhouette.")

    inside_stroke = dict(STYLE["stroke"], position="inside")
    behind, overlay = render_layer_effects(source, {"stroke": inside_stroke})
    if behind.getbbox() is not None or overlay.getchannel("A").getbbox() is None:
        raise AssertionError("Inside stroke was not isolated as an overlay.")


def _load_test_font(app: QtWidgets.QApplication) -> str:
    path = ROOT / "resources" / "fonts" / "NotoSansJP-Black.otf"
    font_id = QtGui.QFontDatabase.addApplicationFont(str(path))
    families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        raise RuntimeError(f"Could not load test font: {path}")
    app.setFont(QtGui.QFont(families[0], 10))
    return families[0]


def _make_item(font_family: str) -> TextBlockItem:
    item = TextBlockItem(
        text="",
        font_family=font_family,
        font_size=48,
        render_color=QtGui.QColor("#ffffff"),
        outline_color=None,
    )
    item.set_plain_text("MUKAI")
    item.set_fill_style(STYLE)
    return item


def _verify_editor_round_trip() -> None:
    dialog = TextFillDialog(STYLE)
    try:
        returned = dialog.fill_style()
        for effect in ("glow", "drop_shadow", "inner_glow", "inner_shadow", "stroke"):
            if not returned[effect]["enabled"]:
                raise AssertionError(f"Fill dialog discarded an incoming effect: {effect}")
        if hasattr(dialog, "effect_controls"):
            raise AssertionError("Layer effects are still exposed in the fill dialog.")
    finally:
        dialog.close()

    panel = TextEffectsPanel()
    try:
        changes = []
        panel.effectChanged.connect(
            lambda key, value, macro: changes.append((key, value, macro))
        )
        panel.set_selection("MUKAI", STYLE)
        panel.layer_controls["drop_shadow"]["angle"].setValue(205)
        panel._commit_effect("drop_shadow", "verify_layer_effect")
        panel.layer_controls["stroke"]["position"].setCurrentIndex(1)
        if (
            panel._style["drop_shadow"]["angle"] != 205
            or panel._style["stroke"]["position"] != "center"
            or not changes
        ):
            raise AssertionError("Contextual layer-effect controls were not serialized.")
    finally:
        panel.close()


def _render_scene(item: TextBlockItem, output: Path) -> None:
    scene = QtWidgets.QGraphicsScene()
    scene.addItem(item)
    rect = item.boundingRect()
    scene.setSceneRect(rect)
    image = QtGui.QImage(
        max(1, int(np.ceil(rect.width()))),
        max(1, int(np.ceil(rect.height()))),
        QtGui.QImage.Format.Format_ARGB32,
    )
    image.fill(QtGui.QColor("#202027"))
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
    scene.render(painter, QtCore.QRectF(image.rect()), rect)
    painter.end()
    if not image.save(str(output)):
        raise RuntimeError(f"Could not save visual verification image: {output}")
    if item._layer_effect_cache is None:
        raise AssertionError("The canvas did not render/cache its layer effects.")
    scene.removeItem(item)


def _verify_round_trip_and_export(item: TextBlockItem) -> None:
    props = TextItemProperties.from_text_item(item)
    state = props.to_dict()
    restored = TextItemProperties.from_dict(state)
    for effect in ("glow", "drop_shadow", "inner_glow", "inner_shadow", "stroke"):
        if restored.fill_style.get(effect) != item.get_fill_style().get(effect):
            raise AssertionError(f"Effect did not survive state round-trip: {effect}")

    state["position"] = (70, 70)
    base = np.full((260, 620, 3), 32, dtype=np.uint8)
    renderer = ImageSaveRenderer(base)
    renderer.add_state_to_image({"text_items_state": [state]})
    output = renderer.render_to_image()
    if output.shape != base.shape:
        raise AssertionError(f"Unexpected export shape: {output.shape}")
    if np.array_equal(output, base):
        raise AssertionError("Raster export did not paint the styled text.")


def main() -> int:
    _verify_mask_math()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    font_family = _load_test_font(app)
    _verify_editor_round_trip()
    item = _make_item(font_family)
    output = ROOT / "build" / "text-layer-effects-verification.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    _render_scene(item, output)
    _verify_round_trip_and_export(item)
    print(f"text_layer_effects=ok\nvisual={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Raster layer effects for editable text masks.

The mask expansion/erosion + Gaussian blur pipeline is adapted from the MIT
licensed ``chflame163/ComfyUI_LayerStyle`` project.  Mukai keeps only the
small Pillow-based layer-style core; it does not install ComfyUI or Torch.
See ``docs/THIRD_PARTY_NOTICES.md``.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

import mahotas
import numpy as np
from PIL import Image, ImageChops, ImageFilter


_MORPHOLOGY_CROSS = np.array(
    ((False, True, False), (True, True, True), (False, True, False)),
    dtype=bool,
)


def _clamp(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    return max(minimum, min(maximum, number))


def _colour_rgba(value: Any) -> tuple[int, int, int, int]:
    text = str(value or "#ff000000").strip().lstrip("#")
    try:
        if len(text) == 8:  # Qt serialises colors as AARRGGBB.
            alpha, red, green, blue = (
                int(text[0:2], 16),
                int(text[2:4], 16),
                int(text[4:6], 16),
                int(text[6:8], 16),
            )
        elif len(text) == 6:
            alpha = 255
            red, green, blue = int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
        else:
            raise ValueError
    except ValueError:
        return 0, 0, 0, 255
    return red, green, blue, alpha


def _dilate(mask: Image.Image, radius: int) -> Image.Image:
    radius = max(0, int(radius))
    if radius == 0:
        return mask.copy()
    output = np.asarray(mask.convert("L"), dtype=np.uint8)
    for _ in range(radius):
        output = mahotas.dilate(output, _MORPHOLOGY_CROSS)
    return Image.fromarray(output)


def _erode(mask: Image.Image, radius: int) -> Image.Image:
    radius = max(0, int(radius))
    if radius == 0:
        return mask.copy()
    output = np.asarray(mask.convert("L"), dtype=np.uint8)
    for _ in range(radius):
        output = mahotas.erode(output, _MORPHOLOGY_CROSS)
    return Image.fromarray(output)


def _blur(mask: Image.Image, radius: float) -> Image.Image:
    radius = max(0.0, float(radius))
    return mask.filter(ImageFilter.GaussianBlur(radius)) if radius > 0 else mask.copy()


def _shift(mask: Image.Image, offset_x: int, offset_y: int) -> Image.Image:
    shifted = Image.new("L", mask.size, 0)
    shifted.paste(mask, (int(offset_x), int(offset_y)))
    return shifted


def _effect_layer(mask: Image.Image, color: Any, opacity: Any) -> Image.Image:
    red, green, blue, color_alpha = _colour_rgba(color)
    opacity_factor = _clamp(opacity, 0, 100, 100) / 100.0
    alpha_factor = opacity_factor * color_alpha / 255.0
    if alpha_factor < 1.0:
        mask = mask.point(lambda value: round(value * alpha_factor))
    layer = Image.new("RGBA", mask.size, (red, green, blue, 0))
    layer.putalpha(mask)
    return layer


def shadow_offset(angle: Any, distance: Any) -> tuple[int, int]:
    """Convert Photoshop-style light angle/distance to a shadow offset."""
    radians = math.radians(_clamp(angle, 0, 360, 120))
    distance = _clamp(distance, 0, 200, 8)
    return round(-math.cos(radians) * distance), round(math.sin(radians) * distance)


def effect_margin(style: dict) -> int:
    """Return enough logical pixels to avoid clipping enabled outer effects."""
    margin = 0.0
    glow = style.get("glow", {}) if isinstance(style.get("glow"), dict) else {}
    if glow.get("enabled"):
        size = _clamp(glow.get("size"), 1, 80, 12)
        spread = _clamp(glow.get("spread"), 0, 100, 25)
        margin = max(margin, size * 1.6 + size * spread / 200.0 + 4)

    shadow = style.get("drop_shadow", {}) if isinstance(style.get("drop_shadow"), dict) else {}
    if shadow.get("enabled"):
        size = _clamp(shadow.get("size"), 0, 80, 12)
        spread = _clamp(shadow.get("spread"), 0, 100, 10)
        offset_x, offset_y = shadow_offset(shadow.get("angle"), shadow.get("distance"))
        margin = max(
            margin,
            max(abs(offset_x), abs(offset_y)) + size * 1.6 + size * spread / 200.0 + 4,
        )

    stroke = style.get("stroke", {}) if isinstance(style.get("stroke"), dict) else {}
    if stroke.get("enabled") and stroke.get("position", "outside") in {"outside", "center"}:
        margin = max(margin, _clamp(stroke.get("size"), 1, 40, 3) + 3)
    return int(math.ceil(margin))


def scaled_effect_style(style: dict, factor: float) -> dict:
    """Scale pixel-based controls for supersampled mask rendering."""
    scaled = deepcopy(style)
    factor = max(0.01, float(factor))
    for effect_name in ("glow", "drop_shadow", "inner_glow", "inner_shadow", "stroke"):
        effect = scaled.get(effect_name)
        if not isinstance(effect, dict):
            continue
        for field in ("size", "distance"):
            if field in effect:
                effect[field] = float(effect[field]) * factor
    return scaled


def _outer_glow_mask(source: Image.Image, effect: dict) -> Image.Image:
    size = _clamp(effect.get("size"), 1, 160, 12)
    spread = _clamp(effect.get("spread"), 0, 100, 25)
    spread_pixels = round(size * spread / 200.0)
    expanded = _dilate(source, spread_pixels)
    softened = _blur(expanded, max(0.6, size / 2.0))
    # Keeping only pixels outside the source silhouette is what prevents the
    # repeated-letter look of the previous multi-offset implementation.
    return ImageChops.subtract(softened, source)


def _drop_shadow_mask(source: Image.Image, effect: dict) -> Image.Image:
    size = _clamp(effect.get("size"), 0, 160, 12)
    spread = _clamp(effect.get("spread"), 0, 100, 10)
    spread_pixels = round(size * spread / 200.0)
    expanded = _dilate(source, spread_pixels)
    softened = _blur(expanded, size / 2.0)
    offset_x, offset_y = shadow_offset(effect.get("angle"), effect.get("distance"))
    return _shift(softened, offset_x, offset_y)


def _inner_glow_mask(source: Image.Image, effect: dict) -> Image.Image:
    size = _clamp(effect.get("size"), 1, 120, 8)
    choke = _clamp(effect.get("choke"), 0, 100, 10)
    outside = ImageChops.invert(source)
    expanded_outside = _dilate(outside, round(size * choke / 200.0))
    return ImageChops.multiply(source, _blur(expanded_outside, max(0.6, size / 2.0)))


def _inner_shadow_mask(source: Image.Image, effect: dict) -> Image.Image:
    size = _clamp(effect.get("size"), 0, 120, 8)
    choke = _clamp(effect.get("choke"), 0, 100, 5)
    outside = ImageChops.invert(source)
    outside = _dilate(outside, round(size * choke / 200.0))
    offset_x, offset_y = shadow_offset(effect.get("angle"), effect.get("distance"))
    outside = _shift(outside, -offset_x, -offset_y)
    return ImageChops.multiply(source, _blur(outside, size / 2.0))


def _stroke_masks(source: Image.Image, effect: dict) -> tuple[Image.Image, Image.Image]:
    size = round(_clamp(effect.get("size"), 1, 80, 3))
    position = effect.get("position", "outside")
    empty = Image.new("L", source.size, 0)
    if position == "inside":
        return empty, ImageChops.subtract(source, _erode(source, size))
    if position == "center":
        outside_radius = max(1, math.ceil(size / 2))
        inside_radius = max(1, math.floor(size / 2))
        return (
            ImageChops.subtract(_dilate(source, outside_radius), source),
            ImageChops.subtract(source, _erode(source, inside_radius)),
        )
    return ImageChops.subtract(_dilate(source, size), source), empty


def render_layer_effects(source_mask: Image.Image, style: dict) -> tuple[Image.Image, Image.Image]:
    """Render effects behind and inside/on top of the original text layer."""
    source = source_mask.convert("L")
    behind = Image.new("RGBA", source.size, (0, 0, 0, 0))
    overlay = Image.new("RGBA", source.size, (0, 0, 0, 0))

    shadow = style.get("drop_shadow", {}) if isinstance(style.get("drop_shadow"), dict) else {}
    if shadow.get("enabled"):
        behind = Image.alpha_composite(
            behind,
            _effect_layer(_drop_shadow_mask(source, shadow), shadow.get("color"), shadow.get("opacity")),
        )

    glow = style.get("glow", {}) if isinstance(style.get("glow"), dict) else {}
    if glow.get("enabled"):
        behind = Image.alpha_composite(
            behind,
            _effect_layer(_outer_glow_mask(source, glow), glow.get("color"), glow.get("opacity")),
        )

    stroke = style.get("stroke", {}) if isinstance(style.get("stroke"), dict) else {}
    if stroke.get("enabled"):
        outer_stroke, inner_stroke = _stroke_masks(source, stroke)
        behind = Image.alpha_composite(
            behind,
            _effect_layer(outer_stroke, stroke.get("color"), stroke.get("opacity")),
        )
        overlay = Image.alpha_composite(
            overlay,
            _effect_layer(inner_stroke, stroke.get("color"), stroke.get("opacity")),
        )

    inner_glow = style.get("inner_glow", {}) if isinstance(style.get("inner_glow"), dict) else {}
    if inner_glow.get("enabled"):
        overlay = Image.alpha_composite(
            overlay,
            _effect_layer(
                _inner_glow_mask(source, inner_glow),
                inner_glow.get("color"),
                inner_glow.get("opacity"),
            ),
        )

    inner_shadow = style.get("inner_shadow", {}) if isinstance(style.get("inner_shadow"), dict) else {}
    if inner_shadow.get("enabled"):
        overlay = Image.alpha_composite(
            overlay,
            _effect_layer(
                _inner_shadow_mask(source, inner_shadow),
                inner_shadow.get("color"),
                inner_shadow.get("opacity"),
            ),
        )

    return behind, overlay


def pil_rgba_to_qimage(image: Image.Image):
    """Convert a Pillow RGBA image without leaving it backed by temporary data."""
    from PySide6 import QtGui

    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    return QtGui.QImage(
        data,
        rgba.width,
        rgba.height,
        rgba.width * 4,
        QtGui.QImage.Format.Format_RGBA8888,
    ).copy()


def qimage_alpha_to_pil(image) -> Image.Image:
    """Extract a QImage alpha channel as an owned Pillow image."""
    from PySide6 import QtGui

    rgba = image.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    data = bytes(rgba.bits())
    pil = Image.frombuffer(
        "RGBA",
        (rgba.width(), rgba.height()),
        data,
        "raw",
        "RGBA",
        rgba.bytesPerLine(),
        1,
    )
    return pil.getchannel("A").copy()

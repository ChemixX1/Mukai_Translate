"""Editable 3D extrusion and four-corner perspective for text composites.

The implementation follows the established graphics workflow of mapping the
four corners through a projective homography, then building an extrusion from
successive displaced copies of the transformed alpha mask.  The original text
document is never flattened in project state; this module only renders its
display and export composite.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from PySide6 import QtGui

from .text_warp import resample_rgba


SUPPORTED_TEXT_3D_STYLES = (
    "extrude",
    "perspective_left",
    "perspective_right",
    "perspective_up",
    "perspective_down",
    "flare_left",
    "flare_right",
    "skew_left",
    "skew_right",
    "trapezoid",
)


def _colour_name(value: Any, fallback: str = "#ff722b45") -> str:
    colour = value if isinstance(value, QtGui.QColor) else QtGui.QColor(str(value or fallback))
    if not colour.isValid():
        colour = QtGui.QColor(fallback)
    return colour.name(QtGui.QColor.NameFormat.HexArgb)


def normalise_text_3d(value: Any) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    style = str(value.get("style", "perspective_left"))
    if style not in SUPPORTED_TEXT_3D_STYLES:
        style = "perspective_left"
    return {
        "enabled": bool(value.get("enabled", False)),
        "style": style,
        "strength": max(0, min(100, int(round(float(value.get("strength", 48)))))),
        "extrude": bool(value.get("extrude", True)),
        "depth": max(1, min(80, int(round(float(value.get("depth", 16)))))),
        "angle": int(round(float(value.get("angle", 45)))) % 360,
        "color": _colour_name(value.get("color", "#ff722b45")),
        "bevel": max(0, min(100, int(round(float(value.get("bevel", 28)))))),
    }


def scaled_text_3d(value: Any, scale: float) -> dict[str, Any]:
    effect = normalise_text_3d(value)
    effect["sample_scale"] = max(0.1, float(scale))
    return effect


def has_text_3d(value: Any) -> bool:
    effect = normalise_text_3d(value)
    if not effect["enabled"]:
        return False
    geometry = effect["style"] != "extrude" and effect["strength"] > 0
    return bool(geometry or effect["extrude"] or effect["bevel"] > 0)


def text_3d_padding(
    width: int | float,
    height: int | float,
    value: Any,
) -> tuple[int, int]:
    effect = normalise_text_3d(value)
    if not has_text_3d(effect):
        return 0, 0

    width = max(1.0, float(width))
    height = max(1.0, float(height))
    strength = effect["strength"] / 100.0
    style = effect["style"]
    pad_x = 0.0
    pad_y = 0.0
    if style in {"perspective_up", "perspective_down", "skew_left", "skew_right", "trapezoid"}:
        pad_x += width * 0.36 * strength
    if style in {"perspective_left", "perspective_right", "flare_left", "flare_right"}:
        pad_y += height * 0.36 * strength
    if style in {"flare_left", "flare_right", "trapezoid"}:
        pad_x += width * 0.10 * strength

    sample_scale = (
        max(0.1, float(value.get("sample_scale", 1.0)))
        if isinstance(value, dict)
        else 1.0
    )
    if effect["extrude"]:
        pad_x += effect["depth"] * sample_scale
        pad_y += effect["depth"] * sample_scale
    if effect["bevel"]:
        bevel_pad = (1.0 + (effect["bevel"] / 100.0) * 4.0) * sample_scale
        pad_x += bevel_pad
        pad_y += bevel_pad
    return int(math.ceil(pad_x)), int(math.ceil(pad_y))


def _target_quad(
    width: int,
    height: int,
    pad_x: int,
    pad_y: int,
    effect: dict[str, Any],
) -> np.ndarray:
    x0 = float(pad_x)
    y0 = float(pad_y)
    x1 = x0 + max(1.0, width - 1.0)
    y1 = y0 + max(1.0, height - 1.0)
    points = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float64)
    strength = effect["strength"] / 100.0
    style = effect["style"]
    dx = (width - 1.0) * 0.32 * strength
    dy = (height - 1.0) * 0.32 * strength

    if style == "perspective_left":
        points[0, 1] += dy
        points[3, 1] -= dy
    elif style == "perspective_right":
        points[1, 1] += dy
        points[2, 1] -= dy
    elif style == "perspective_up":
        points[0, 0] += dx
        points[1, 0] -= dx
    elif style == "perspective_down":
        points[3, 0] += dx
        points[2, 0] -= dx
    elif style == "flare_left":
        points[0, 1] -= dy
        points[3, 1] += dy
        points[0, 0] -= dx * 0.24
        points[3, 0] -= dx * 0.24
    elif style == "flare_right":
        points[1, 1] -= dy
        points[2, 1] += dy
        points[1, 0] += dx * 0.24
        points[2, 0] += dx * 0.24
    elif style == "skew_left":
        points[[0, 1], 0] -= dx
        points[[2, 3], 0] += dx
    elif style == "skew_right":
        points[[0, 1], 0] += dx
        points[[2, 3], 0] -= dx
    elif style == "trapezoid":
        points[0, 0] += dx
        points[1, 0] -= dx
        points[3, 0] -= dx * 0.45
        points[2, 0] += dx * 0.45
    return points


def _homography(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    rows: list[list[float]] = []
    values: list[float] = []
    for (x, y), (u, v) in zip(source, target):
        rows.append([x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y])
        values.append(u)
        rows.append([0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y])
        values.append(v)
    coefficients = np.linalg.solve(np.asarray(rows, dtype=np.float64), np.asarray(values))
    return np.append(coefficients, 1.0).reshape(3, 3)


def _perspective_rgba(
    source: np.ndarray,
    effect: dict[str, Any],
    pad_x: int,
    pad_y: int,
) -> np.ndarray:
    height, width, _channels = source.shape
    output_h = height + (2 * pad_y)
    output_w = width + (2 * pad_x)
    if width < 2 or height < 2:
        return np.pad(source, ((pad_y, pad_y), (pad_x, pad_x), (0, 0)), mode="constant")
    source_quad = np.array(
        [[0.0, 0.0], [width - 1.0, 0.0], [width - 1.0, height - 1.0], [0.0, height - 1.0]],
        dtype=np.float64,
    )
    target_quad = _target_quad(width, height, pad_x, pad_y, effect)
    try:
        inverse = np.linalg.inv(_homography(source_quad, target_quad))
    except np.linalg.LinAlgError:
        return np.pad(source, ((pad_y, pad_y), (pad_x, pad_x), (0, 0)), mode="constant")
    grid_y, grid_x = np.mgrid[0:output_h, 0:output_w].astype(np.float64)
    denominator = inverse[2, 0] * grid_x + inverse[2, 1] * grid_y + inverse[2, 2]
    safe = np.abs(denominator) > 1e-9
    map_x = np.full(grid_x.shape, -1.0, dtype=np.float32)
    map_y = np.full(grid_y.shape, -1.0, dtype=np.float32)
    map_x[safe] = (
        (inverse[0, 0] * grid_x[safe] + inverse[0, 1] * grid_y[safe] + inverse[0, 2])
        / denominator[safe]
    )
    map_y[safe] = (
        (inverse[1, 0] * grid_x[safe] + inverse[1, 1] * grid_y[safe] + inverse[1, 2])
        / denominator[safe]
    )
    return resample_rgba(source, map_x, map_y)


def _shift_plane(source: np.ndarray, dx: int, dy: int) -> np.ndarray:
    height, width = source.shape
    result = np.zeros_like(source)
    src_x0 = max(0, -dx)
    src_y0 = max(0, -dy)
    dst_x0 = max(0, dx)
    dst_y0 = max(0, dy)
    count_x = min(width - src_x0, width - dst_x0)
    count_y = min(height - src_y0, height - dst_y0)
    if count_x > 0 and count_y > 0:
        result[dst_y0:dst_y0 + count_y, dst_x0:dst_x0 + count_x] = source[
            src_y0:src_y0 + count_y,
            src_x0:src_x0 + count_x,
        ]
    return result


def _extrusion(alpha: np.ndarray, effect: dict[str, Any]) -> np.ndarray:
    output = np.zeros((*alpha.shape, 4), dtype=np.uint8)
    if not effect["extrude"]:
        return output
    depth = max(1, int(effect["depth"]))
    angle = math.radians(effect["angle"])
    end_x = math.cos(angle) * depth
    end_y = math.sin(angle) * depth
    steps = max(2, min(128, int(math.ceil(max(abs(end_x), abs(end_y)))) + 1))
    union = np.zeros_like(alpha, dtype=np.float32)
    for progress in np.linspace(0.0, 1.0, steps):
        shifted = _shift_plane(alpha, int(round(end_x * progress)), int(round(end_y * progress)))
        np.maximum(union, shifted, out=union)

    colour = QtGui.QColor(effect["color"])
    output[..., 0] = colour.red()
    output[..., 1] = colour.green()
    output[..., 2] = colour.blue()
    output[..., 3] = np.clip(union * (colour.alpha() / 255.0), 0.0, 255.0).astype(np.uint8)
    return output


def _bevel(alpha: np.ndarray, effect: dict[str, Any]) -> np.ndarray:
    output = np.zeros((*alpha.shape, 4), dtype=np.uint8)
    amount = effect["bevel"] / 100.0
    if amount <= 0.0:
        return output
    distance = max(1, int(round((1.0 + 3.0 * amount) * effect.get("sample_scale", 1.0))))
    alpha_f = alpha.astype(np.float32) / 255.0
    northwest = _shift_plane(alpha_f, -distance, -distance)
    southeast = _shift_plane(alpha_f, distance, distance)
    highlight = np.clip(alpha_f - southeast, 0.0, 1.0) * (0.68 * amount)
    shadow = np.clip(alpha_f - northwest, 0.0, 1.0) * (0.62 * amount)
    output[..., :3] = 255
    output[..., 3] = np.clip(highlight * 255.0, 0.0, 255.0).astype(np.uint8)
    shadow_rgba = np.zeros_like(output)
    shadow_rgba[..., 3] = np.clip(shadow * 255.0, 0.0, 255.0).astype(np.uint8)
    return alpha_composite_rgba(shadow_rgba, output)


def alpha_composite_rgba(base: np.ndarray, overlay: np.ndarray) -> np.ndarray:
    base_f = base.astype(np.float32) / 255.0
    over_f = overlay.astype(np.float32) / 255.0
    base_a = base_f[..., 3:4]
    over_a = over_f[..., 3:4]
    out_a = over_a + base_a * (1.0 - over_a)
    premul = over_f[..., :3] * over_a + base_f[..., :3] * base_a * (1.0 - over_a)
    rgb = np.divide(premul, out_a, out=np.zeros_like(premul), where=out_a > 1e-6)
    result = np.concatenate((rgb, out_a), axis=2)
    return np.ascontiguousarray(np.clip(result * 255.0, 0.0, 255.0).astype(np.uint8))


def render_text_3d(
    content_rgba: np.ndarray,
    mask_rgba: np.ndarray,
    value: Any,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int, int]:
    """Return transformed content/mask, extrusion, bevel and added padding."""
    effect = normalise_text_3d(value)
    sample_scale = float(value.get("sample_scale", 1.0)) if isinstance(value, dict) else 1.0
    effect["sample_scale"] = sample_scale
    if not has_text_3d(effect):
        empty = np.zeros_like(content_rgba)
        return content_rgba.copy(), mask_rgba.copy(), empty, empty.copy(), 0, 0
    padded_effect = dict(effect)
    padded_effect["sample_scale"] = sample_scale
    pad_x, pad_y = text_3d_padding(content_rgba.shape[1], content_rgba.shape[0], padded_effect)
    transformed_content = _perspective_rgba(content_rgba, effect, pad_x, pad_y)
    transformed_mask = _perspective_rgba(mask_rgba, effect, pad_x, pad_y)
    alpha = transformed_mask[..., 3]
    return (
        transformed_content,
        transformed_mask,
        _extrusion(alpha, {**effect, "depth": max(1, int(round(effect["depth"] * sample_scale)))}),
        _bevel(alpha, effect),
        pad_x,
        pad_y,
    )

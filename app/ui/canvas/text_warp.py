"""Editable Photoshop-style text envelope deformations.

The source remains an editable ``QTextDocument``.  Only its display composite
is rasterised, supersampled and remapped.  OpenCV's Lanczos interpolator is used
when available; the NumPy implementation remains a safe fallback for machines
where the optional native module cannot be loaded.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from PySide6 import QtGui

try:
    import cv2
except (ImportError, OSError):  # Windows N/KN can lack OpenCV's media DLLs.
    cv2 = None


SUPPORTED_WARP_STYLES = (
    "arc",
    "arc_lower",
    "arc_upper",
    "arch",
    "bulge",
    "shell_lower",
    "shell_upper",
    "flag",
    "wave",
    "fish",
    "rise",
    "fish_eye",
    "inflate",
    "squeeze",
    "twist",
)


def text_warp_backend() -> str:
    """Return the active sampling backend, useful for diagnostics."""
    return "opencv-lanczos4" if cv2 is not None else "numpy-bilinear"


def normalise_text_warp(value: Any) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    style = str(value.get("style", "flag"))
    if style not in SUPPORTED_WARP_STYLES:
        style = "flag"
    orientation = str(value.get("orientation", "horizontal"))
    if orientation not in {"horizontal", "vertical"}:
        orientation = "horizontal"
    return {
        "enabled": bool(value.get("enabled", False)),
        "style": style,
        "bend": max(-100, min(100, int(round(float(value.get("bend", 24)))))),
        "horizontal": max(-100, min(100, int(round(float(value.get("horizontal", 0)))))),
        "vertical": max(-100, min(100, int(round(float(value.get("vertical", 0)))))),
        "orientation": orientation,
    }


def warp_padding(width: int | float, height: int | float, value: Any) -> tuple[int, int]:
    """Return transparent padding needed to avoid clipping a deformation."""
    warp = normalise_text_warp(value)
    if not warp["enabled"]:
        return 0, 0

    width = max(1.0, float(width))
    height = max(1.0, float(height))
    bend = abs(warp["bend"]) / 100.0
    horizontal = abs(warp["horizontal"]) / 100.0
    vertical = abs(warp["vertical"]) / 100.0

    style = warp["style"]
    pad_x = width * (0.16 * horizontal)
    pad_y = height * (0.16 * vertical)
    if style in {"arc", "arc_upper", "arc_lower", "rise"}:
        pad_y += height * 0.42 * bend
    elif style in {"arch", "shell_upper", "shell_lower"}:
        pad_y += height * 0.38 * bend
    elif style == "bulge":
        pad_x += width * 0.16 * bend
        pad_y += height * 0.40 * bend
    elif style == "fish":
        pad_x += width * 0.12 * bend
        pad_y += height * 0.32 * bend
    elif style in {"fish_eye", "inflate"}:
        pad_x += width * 0.28 * bend
        pad_y += height * 0.32 * bend
    elif style == "twist":
        pad_x += width * 0.12 * bend
        pad_y += height * 0.20 * bend
    elif style == "squeeze":
        pad_x += width * 0.30 * bend
        pad_y += height * 0.05 * bend
    elif style == "wave":
        pad_x += width * 0.06 * bend
        pad_y += height * 0.20 * bend

    if warp["orientation"] == "vertical":
        pad_x, pad_y = pad_y, pad_x
    return int(math.ceil(pad_x)), int(math.ceil(pad_y))


def qimage_to_rgba_array(image: QtGui.QImage) -> np.ndarray:
    converted = image.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    height = converted.height()
    width = converted.width()
    stride = converted.bytesPerLine()
    raw = np.frombuffer(converted.constBits(), dtype=np.uint8, count=height * stride)
    rows = raw.reshape(height, stride)
    # ``converted`` owns the memory exposed by constBits(); copy before the
    # temporary QImage leaves scope or NumPy would retain a dangling view.
    return np.ascontiguousarray(
        rows[:, : width * 4].reshape(height, width, 4)
    ).copy()


def rgba_array_to_qimage(array: np.ndarray) -> QtGui.QImage:
    rgba = np.ascontiguousarray(np.clip(array, 0, 255).astype(np.uint8))
    height, width, _channels = rgba.shape
    image = QtGui.QImage(
        rgba.data,
        width,
        height,
        rgba.strides[0],
        QtGui.QImage.Format.Format_RGBA8888,
    )
    return image.copy()


def warp_qimage(image: QtGui.QImage, value: Any) -> tuple[QtGui.QImage, int, int]:
    warped, pad_x, pad_y = warp_rgba_array(qimage_to_rgba_array(image), value)
    return rgba_array_to_qimage(warped), pad_x, pad_y


def warp_rgba_array(source: np.ndarray, value: Any) -> tuple[np.ndarray, int, int]:
    """Warp an RGBA image and return ``(image, horizontal_pad, vertical_pad)``."""
    warp = normalise_text_warp(value)
    if not warp["enabled"] or not any(
        (warp["bend"], warp["horizontal"], warp["vertical"])
    ):
        return np.ascontiguousarray(source.copy()), 0, 0

    source = np.ascontiguousarray(source)
    if source.ndim != 3 or source.shape[2] != 4:
        raise ValueError("Text warp expects an RGBA image.")

    if warp["orientation"] == "vertical":
        rotated = np.ascontiguousarray(np.rot90(source, 1))
        rotated_warp = dict(warp)
        rotated_warp["orientation"] = "horizontal"
        rotated_warp["horizontal"], rotated_warp["vertical"] = (
            warp["vertical"],
            warp["horizontal"],
        )
        result, rotated_pad_x, rotated_pad_y = _warp_horizontal(rotated, rotated_warp)
        return (
            np.ascontiguousarray(np.rot90(result, -1)),
            rotated_pad_y,
            rotated_pad_x,
        )

    return _warp_horizontal(source, warp)


def _warp_horizontal(source: np.ndarray, warp: dict[str, Any]) -> tuple[np.ndarray, int, int]:
    source_h, source_w, _channels = source.shape
    pad_x, pad_y = warp_padding(source_w, source_h, warp)
    canvas_h = source_h + 2 * pad_y
    canvas_w = source_w + 2 * pad_x

    grid_y, grid_x = np.mgrid[0:canvas_h, 0:canvas_w].astype(np.float32)
    width_scale = float(max(1, source_w - 1))
    height_scale = float(max(1, source_h - 1))
    u = (grid_x - pad_x) / width_scale
    v = (grid_y - pad_y) / height_scale

    bend = float(warp["bend"]) / 100.0
    horizontal = float(warp["horizontal"]) / 100.0
    vertical = float(warp["vertical"]) / 100.0
    source_u = u.copy()
    source_v = v.copy()
    style = warp["style"]

    if style == "arc":
        arch = np.clip(1.0 - np.square((2.0 * u) - 1.0), 0.0, 1.0)
        source_v = v + (0.38 * bend * arch)
    elif style == "arc_upper":
        arch = np.clip(1.0 - np.square((2.0 * u) - 1.0), 0.0, 1.0)
        top = -0.42 * bend * arch
        source_v = (v - top) / np.maximum(0.15, 1.0 - top)
    elif style == "arc_lower":
        arch = np.clip(1.0 - np.square((2.0 * u) - 1.0), 0.0, 1.0)
        bottom = 0.42 * bend * arch
        source_v = v / np.maximum(0.15, 1.0 + bottom)
    elif style == "arch":
        arch = np.clip(1.0 - np.square((2.0 * u) - 1.0), 0.0, 1.0)
        scale = np.maximum(0.2, 1.0 + (0.72 * bend * arch))
        source_v = 0.5 + ((v - 0.5) / scale)
    elif style == "bulge":
        crown_x = np.clip(1.0 - np.square((2.0 * u) - 1.0), 0.0, 1.0)
        crown_y = np.clip(1.0 - np.square((2.0 * v) - 1.0), 0.0, 1.0)
        scale_x = np.maximum(0.25, 1.0 + (0.24 * bend * crown_y))
        scale_y = np.maximum(0.25, 1.0 + (0.72 * bend * crown_x))
        source_u = 0.5 + ((u - 0.5) / scale_x)
        source_v = 0.5 + ((v - 0.5) / scale_y)
    elif style == "shell_lower":
        crown = np.clip(1.0 - np.square((2.0 * u) - 1.0), 0.0, 1.0)
        scale = np.maximum(0.2, 1.0 + (0.72 * bend * crown))
        source_v = v / scale
    elif style == "flag":
        source_v = v - (0.25 * bend * np.sin(2.0 * np.pi * u))
    elif style == "wave":
        source_v = v - (0.18 * bend * np.sin(4.0 * np.pi * u))
        source_u = u - (0.05 * bend * np.sin(2.0 * np.pi * v))
    elif style == "shell_upper":
        crown = np.clip(1.0 - np.square((2.0 * u) - 1.0), 0.0, 1.0)
        scale = np.maximum(0.2, 1.0 + (0.72 * bend * crown))
        source_v = 1.0 - ((1.0 - v) / scale)
    elif style == "fish":
        body = np.clip(np.sin(np.pi * u), 0.0, 1.0)
        scale = np.maximum(0.25, 1.0 + (0.62 * bend * body))
        source_v = 0.5 + ((v - 0.5) / scale)
        source_u = u - (0.10 * bend * body * np.sin(2.0 * np.pi * v))
    elif style == "rise":
        source_v = v + (0.38 * bend * (u - 0.5))
    elif style == "fish_eye":
        dx = u - 0.5
        dy = (v - 0.5) * (height_scale / width_scale)
        radius = np.sqrt(np.square(dx) + np.square(dy))
        falloff = np.exp(-5.0 * np.square(radius))
        scale = np.maximum(0.25, 1.0 + (0.95 * bend * falloff))
        source_u = 0.5 + (dx / scale)
        source_v = 0.5 + ((dy / scale) * (width_scale / height_scale))
    elif style == "inflate":
        crown_x = np.clip(1.0 - np.square((2.0 * u) - 1.0), 0.0, 1.0)
        crown_y = np.clip(1.0 - np.square((2.0 * v) - 1.0), 0.0, 1.0)
        scale_x = np.maximum(0.25, 1.0 + (0.58 * bend * crown_y))
        scale_y = np.maximum(0.25, 1.0 + (0.58 * bend * crown_x))
        source_u = 0.5 + ((u - 0.5) / scale_x)
        source_v = 0.5 + ((v - 0.5) / scale_y)
    elif style == "squeeze":
        middle = np.clip(1.0 - np.abs((2.0 * v) - 1.0), 0.0, 1.0)
        scale = np.maximum(0.2, 1.0 - (0.58 * bend * middle))
        source_u = 0.5 + ((u - 0.5) / scale)
    elif style == "twist":
        dx = u - 0.5
        dy = (v - 0.5) * (height_scale / width_scale)
        radius = np.sqrt(np.square(dx) + np.square(dy))
        angle = -1.25 * bend * np.clip(1.0 - (radius / 0.72), 0.0, 1.0)
        cosine = np.cos(angle)
        sine = np.sin(angle)
        source_u = 0.5 + (dx * cosine) - (dy * sine)
        source_v = 0.5 + (((dx * sine) + (dy * cosine)) * (width_scale / height_scale))

    # Photoshop's horizontal/vertical distortion controls behave like an
    # envelope skew.  Apply them after the named warp, matching that workflow.
    source_u -= horizontal * (v - 0.5) * 0.32
    source_v -= vertical * (u - 0.5) * 0.32

    map_x = source_u * width_scale
    map_y = source_v * height_scale
    result = resample_rgba(source, map_x, map_y)
    return result, pad_x, pad_y


def resample_rgba(source: np.ndarray, map_x: np.ndarray, map_y: np.ndarray) -> np.ndarray:
    """Sample an RGBA image with premultiplied-alpha edge protection."""
    if cv2 is not None and max(source.shape[:2] + map_x.shape[:2]) < 32767:
        return _opencv_lanczos_rgba(source, map_x, map_y)
    return _bilinear_rgba(source, map_x, map_y)


def _opencv_lanczos_rgba(
    source: np.ndarray,
    map_x: np.ndarray,
    map_y: np.ndarray,
) -> np.ndarray:
    pixels = source.astype(np.float32) / 255.0
    pixels[..., :3] *= pixels[..., 3:4]
    sampled = cv2.remap(
        pixels,
        np.ascontiguousarray(map_x, dtype=np.float32),
        np.ascontiguousarray(map_y, dtype=np.float32),
        interpolation=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0.0, 0.0, 0.0, 0.0),
    )
    # Lanczos can ring a few floating-point units beyond the valid range.
    sampled = np.clip(sampled, 0.0, 1.0)
    alpha = sampled[..., 3:4]
    sampled[..., :3] = np.divide(
        sampled[..., :3],
        alpha,
        out=np.zeros_like(sampled[..., :3]),
        where=alpha > 1e-6,
    )
    return np.ascontiguousarray(np.clip(sampled * 255.0, 0.0, 255.0).astype(np.uint8))


def _bilinear_rgba(source: np.ndarray, map_x: np.ndarray, map_y: np.ndarray) -> np.ndarray:
    height, width, _channels = source.shape
    valid = (
        (map_x >= 0.0)
        & (map_y >= 0.0)
        & (map_x <= width - 1)
        & (map_y <= height - 1)
    )

    x0 = np.floor(map_x).astype(np.int32)
    y0 = np.floor(map_y).astype(np.int32)
    x1 = x0 + 1
    y1 = y0 + 1
    x0c = np.clip(x0, 0, width - 1)
    x1c = np.clip(x1, 0, width - 1)
    y0c = np.clip(y0, 0, height - 1)
    y1c = np.clip(y1, 0, height - 1)

    pixels = source.astype(np.float32) / 255.0
    pixels[..., :3] *= pixels[..., 3:4]
    wx = (map_x - x0)[..., None]
    wy = (map_y - y0)[..., None]
    top = pixels[y0c, x0c] * (1.0 - wx) + pixels[y0c, x1c] * wx
    bottom = pixels[y1c, x0c] * (1.0 - wx) + pixels[y1c, x1c] * wx
    sampled = top * (1.0 - wy) + bottom * wy
    sampled[~valid] = 0.0

    alpha = sampled[..., 3:4]
    sampled[..., :3] = np.divide(
        sampled[..., :3],
        alpha,
        out=np.zeros_like(sampled[..., :3]),
        where=alpha > 1e-6,
    )
    return np.ascontiguousarray(np.clip(sampled * 255.0, 0.0, 255.0).astype(np.uint8))

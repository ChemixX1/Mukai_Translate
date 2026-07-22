"""Editor de color sólido y degradado para los textos del lienzo.

Los efectos visuales se editan desde el panel contextual derecho para que este
diálogo se concentre únicamente en el relleno del texto.
"""

from __future__ import annotations

from copy import deepcopy

from PySide6 import QtCore, QtGui, QtWidgets
from app.ui.dayu_widgets import dayu_theme
from app.ui.canvas.layer_effects import (
    pil_rgba_to_qimage,
    qimage_alpha_to_pil,
    render_layer_effects,
    scaled_effect_style,
)
from app.ui.canvas.text_warp import (
    normalise_text_warp,
    qimage_to_rgba_array,
    rgba_array_to_qimage,
    warp_qimage,
)
from app.ui.canvas.text_3d import (
    alpha_composite_rgba,
    normalise_text_3d,
    render_text_3d,
    scaled_text_3d,
)


def _colour_name(colour: QtGui.QColor) -> str:
    """Return a serialisable colour string that also preserves alpha."""
    return colour.name(QtGui.QColor.NameFormat.HexArgb)


def _as_colour(value, fallback: str = "#ff000000") -> QtGui.QColor:
    colour = value if isinstance(value, QtGui.QColor) else QtGui.QColor(value or fallback)
    return colour if colour.isValid() else QtGui.QColor(fallback)


def _paint_preview_background(
    painter: QtGui.QPainter,
    rect: QtCore.QRectF,
    is_dark: bool,
) -> None:
    path = QtGui.QPainterPath()
    path.addRoundedRect(rect, 9, 9)
    is_black = bool(is_dark) and dayu_theme.background_color.lower() == "#000000"
    background = QtGui.QColor(
        "#080808" if is_black else ("#131925" if is_dark else "#eef0f4")
    )
    border = QtGui.QColor(
        "#262626" if is_black else ("#1D2430" if is_dark else "#cfd3da")
    )
    painter.fillPath(path, background)
    if not is_dark:
        painter.save()
        painter.setClipPath(path)
        square = 12
        alternate = QtGui.QColor("#e1e4e9")
        for y in range(int(rect.top()), int(rect.bottom()) + 1, square):
            for x in range(int(rect.left()), int(rect.right()) + 1, square):
                if ((x // square) + (y // square)) % 2:
                    painter.fillRect(x, y, square, square, alternate)
        painter.restore()
    painter.setPen(QtGui.QPen(border, 1))
    painter.drawPath(path)


def _gradient_for_rect(
    rect: QtCore.QRectF,
    stops: list[dict],
    style: str,
) -> QtGui.QGradient:
    """Build the same gradient used by thumbnails and the live preview."""
    if style == "linear_180":
        gradient = QtGui.QLinearGradient(rect.center().x(), rect.top(), rect.center().x(), rect.bottom())
    elif style == "linear_135":
        gradient = QtGui.QLinearGradient(rect.topLeft(), rect.bottomRight())
    elif style == "radial_center":
        gradient = QtGui.QRadialGradient(rect.center(), max(rect.width(), rect.height()) / 1.45)
    elif style == "radial_origin":
        gradient = QtGui.QRadialGradient(rect.topLeft(), max(rect.width(), rect.height()))
    else:
        gradient = QtGui.QLinearGradient(rect.topLeft(), rect.topRight())

    for stop in sorted(stops, key=lambda value: value.get("position", 0)):
        colour = _as_colour(stop.get("color"))
        colour.setAlpha(int(stop.get("alpha", 255)))
        gradient.setColorAt(float(stop.get("position", 0)) / 100.0, colour)
    return gradient


class GradientStopBar(QtWidgets.QWidget):
    """Horizontal stop editor matching the compact bar in the HTML mockup."""

    stopActivated = QtCore.Signal(int)
    stopAddRequested = QtCore.Signal(int)
    stopMoved = QtCore.Signal(int, int)
    stopMoveFinished = QtCore.Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stops: list[dict] = []
        self._selected = -1
        self._dragging_stop = -1
        self._is_dark_theme = True
        self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
        self.setFixedHeight(58)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark_theme = bool(is_dark)
        self.update()

    def set_stops(self, stops: list[dict], selected: int = -1) -> None:
        self._stops = deepcopy(stops)
        self._selected = selected
        self.update()

    def set_selected_stop(self, selected: int) -> None:
        self._selected = selected
        self.update()

    def _bar_rect(self) -> QtCore.QRectF:
        return QtCore.QRectF(9, 1, max(1, self.width() - 18), 38)

    def _marker_rect(self, index: int) -> QtCore.QRectF:
        bar_rect = self._bar_rect()
        position = float(self._stops[index].get("position", 0)) / 100.0
        center_x = bar_rect.left() + (bar_rect.width() * position)
        return QtCore.QRectF(center_x - 8, 34, 16, 16)

    def paintEvent(self, event):  # noqa: N802 - Qt API name
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        bar_rect = self._bar_rect()
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(bar_rect, 7, 7)
        painter.save()
        painter.setClipPath(clip)

        square = 8
        for y in range(int(bar_rect.top()), int(bar_rect.bottom()) + 1, square):
            for x in range(int(bar_rect.left()), int(bar_rect.right()) + 1, square):
                light = ((x // square) + (y // square)) % 2 == 0
                painter.fillRect(x, y, square, square, QtGui.QColor("#eeeeee" if light else "#b8b8b8"))

        horizontal = QtGui.QLinearGradient(bar_rect.topLeft(), bar_rect.topRight())
        for stop in sorted(self._stops, key=lambda value: value.get("position", 0)):
            colour = _as_colour(stop.get("color"))
            colour.setAlpha(int(stop.get("alpha", 255)))
            horizontal.setColorAt(float(stop.get("position", 0)) / 100.0, colour)
        painter.fillPath(clip, horizontal)
        painter.restore()

        painter.setPen(
            QtGui.QPen(QtGui.QColor("#1D2430" if self._is_dark_theme else "#aeb2ba"), 1)
        )
        painter.drawRoundedRect(bar_rect, 7, 7)
        for index, stop in enumerate(self._stops):
            marker = self._marker_rect(index)
            colour = _as_colour(stop.get("color"))
            colour.setAlpha(int(stop.get("alpha", 255)))
            painter.setBrush(colour)
            border = QtGui.QColor(
                dayu_theme.primary_color
                if index == self._selected
                else ("#4C5D70" if self._is_dark_theme else "#8a8d96")
            )
            painter.setPen(QtGui.QPen(border, 2 if index == self._selected else 1))
            painter.drawRoundedRect(marker, 4, 4)
        painter.end()

    def mousePressEvent(self, event):  # noqa: N802 - Qt API name
        point = event.position()
        for index in range(len(self._stops) - 1, -1, -1):
            if self._marker_rect(index).adjusted(-4, -4, 4, 4).contains(point):
                self._dragging_stop = index
                self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
                self.stopActivated.emit(index)
                event.accept()
                return

        bar_rect = self._bar_rect()
        if bar_rect.contains(point):
            position = round(((point.x() - bar_rect.left()) / max(1.0, bar_rect.width())) * 100)
            self.stopAddRequested.emit(max(0, min(100, position)))
            event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt API name
        if (
            self._dragging_stop < 0
            or not (event.buttons() & QtCore.Qt.MouseButton.LeftButton)
        ):
            return super().mouseMoveEvent(event)
        bar_rect = self._bar_rect()
        position = round(
            ((event.position().x() - bar_rect.left()) / max(1.0, bar_rect.width()))
            * 100
        )
        position = max(0, min(100, position))
        self._stops[self._dragging_stop]["position"] = position
        self.stopMoved.emit(self._dragging_stop, position)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt API name
        if (
            self._dragging_stop >= 0
            and event.button() == QtCore.Qt.MouseButton.LeftButton
        ):
            index = self._dragging_stop
            position = int(self._stops[index].get("position", 0))
            self._dragging_stop = -1
            self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
            self.stopMoveFinished.emit(index, position)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class GradientTextSample(QtWidgets.QWidget):
    """Compact gradient-filled Aa sample shown in the dialog footer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stops: list[dict] = []
        self._style = "linear_90"
        self.setFixedSize(82, 48)

    def set_gradient(self, stops: list[dict], style: str) -> None:
        self._stops = deepcopy(stops)
        self._style = style
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt API name
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        font = QtGui.QFont(self.font())
        font.setPixelSize(34)
        font.setWeight(QtGui.QFont.Weight.Black)
        path = QtGui.QPainterPath()
        path.addText(QtCore.QPointF(2, 37), font, "Aa")
        bounds = path.boundingRect()
        painter.fillPath(path, QtGui.QBrush(_gradient_for_rect(bounds, self._stops, self._style)))
        painter.end()


class LayerEffectsTextSample(QtWidgets.QWidget):
    """Small live preview rendered by the same mask engine as canvas text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._style: dict = {}
        self._is_dark_theme = True
        self.setMinimumHeight(104)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark_theme = bool(is_dark)
        self.update()

    def set_style(self, style: dict) -> None:
        self._style = deepcopy(style)
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt API name
        del event
        if self.width() <= 0 or self.height() <= 0:
            return

        scale = 2
        pixel_width = self.width() * scale
        pixel_height = self.height() * scale
        mask_image = QtGui.QImage(
            pixel_width,
            pixel_height,
            QtGui.QImage.Format.Format_ARGB32_Premultiplied,
        )
        mask_image.fill(QtCore.Qt.GlobalColor.transparent)

        font = QtGui.QFont(self.font())
        font.setPixelSize(50)
        font.setWeight(QtGui.QFont.Weight.Black)
        path = QtGui.QPainterPath()
        path.addText(QtCore.QPointF(0, 0), font, "Aa")
        bounds = path.boundingRect()
        path.translate(
            (self.width() - bounds.width()) / 2.0 - bounds.left(),
            (self.height() - bounds.height()) / 2.0 - bounds.top(),
        )

        mask_painter = QtGui.QPainter(mask_image)
        mask_painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        mask_painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
        mask_painter.scale(scale, scale)
        mask_painter.fillPath(path, QtCore.Qt.GlobalColor.white)
        mask_painter.end()

        source_mask = qimage_alpha_to_pil(mask_image)
        behind, overlay = render_layer_effects(
            source_mask,
            scaled_effect_style(self._style, scale),
        )
        behind_image = pil_rgba_to_qimage(behind)
        overlay_image = pil_rgba_to_qimage(overlay)

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        _paint_preview_background(
            painter,
            QtCore.QRectF(self.rect().adjusted(0, 0, -1, -1)),
            self._is_dark_theme,
        )
        target = QtCore.QRectF(self.rect())
        painter.drawImage(target, behind_image)
        painter.fillPath(path, _as_colour(self._style.get("color", "#ffffffff")))
        painter.drawImage(target, overlay_image)
        painter.end()


class WarpTextSample(QtWidgets.QWidget):
    """Live preview for the editable text-envelope deformation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._warp = normalise_text_warp({})
        self._is_dark_theme = True
        self.setMinimumSize(240, 118)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark_theme = bool(is_dark)
        self.update()

    def set_warp(self, warp: dict) -> None:
        self._warp = normalise_text_warp(warp)
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt API name
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        _paint_preview_background(
            painter,
            QtCore.QRectF(self.rect().adjusted(0, 0, -1, -1)),
            self._is_dark_theme,
        )

        scale = 2
        source = QtGui.QImage(
            max(1, (self.width() - 38) * scale),
            max(1, (self.height() - 30) * scale),
            QtGui.QImage.Format.Format_ARGB32_Premultiplied,
        )
        source.fill(QtCore.Qt.GlobalColor.transparent)
        source_painter = QtGui.QPainter(source)
        source_painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        source_painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
        font = QtGui.QFont(self.font())
        font.setPixelSize(42 * scale)
        font.setWeight(QtGui.QFont.Weight.Black)
        path = QtGui.QPainterPath()
        path.addText(QtCore.QPointF(0, 0), font, "MUKAI")
        bounds = path.boundingRect()
        path.translate(
            (source.width() - bounds.width()) / 2.0 - bounds.left(),
            (source.height() - bounds.height()) / 2.0 - bounds.top(),
        )
        source_painter.fillPath(
            path,
            QtGui.QColor("#fff7fa" if self._is_dark_theme else "#343640"),
        )
        source_painter.end()

        warped, _pad_x, _pad_y = warp_qimage(source, self._warp)
        available = QtCore.QRectF(self.rect()).adjusted(12, 9, -12, -9)
        size = QtCore.QSizeF(warped.size())
        size.scale(available.size(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        target = QtCore.QRectF(QtCore.QPointF(), size)
        target.moveCenter(available.center())
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(target, warped)
        painter.end()


class Text3DSample(QtWidgets.QWidget):
    """Live preview for four-corner perspective, extrusion and bevel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._effect = normalise_text_3d({})
        self._is_dark_theme = True
        self.setMinimumSize(240, 138)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark_theme = bool(is_dark)
        self.update()

    def set_effect(self, effect: dict) -> None:
        self._effect = normalise_text_3d(effect)
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt API name
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        _paint_preview_background(
            painter,
            QtCore.QRectF(self.rect().adjusted(0, 0, -1, -1)),
            self._is_dark_theme,
        )

        scale = 2
        pixel_width = max(1, (self.width() - 24) * scale)
        pixel_height = max(1, (self.height() - 20) * scale)
        content = QtGui.QImage(
            pixel_width,
            pixel_height,
            QtGui.QImage.Format.Format_ARGB32_Premultiplied,
        )
        mask = QtGui.QImage(content.size(), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        content.fill(QtCore.Qt.GlobalColor.transparent)
        mask.fill(QtCore.Qt.GlobalColor.transparent)
        font = QtGui.QFont(self.font())
        font.setPixelSize(42 * scale)
        font.setWeight(QtGui.QFont.Weight.Black)
        path = QtGui.QPainterPath()
        path.addText(QtCore.QPointF(0, 0), font, "MUKAI")
        bounds = path.boundingRect()
        path.translate(
            (pixel_width - bounds.width()) / 2.0 - bounds.left(),
            (pixel_height - bounds.height()) / 2.0 - bounds.top(),
        )
        content_painter = QtGui.QPainter(content)
        gradient = QtGui.QLinearGradient(0, 0, pixel_width, pixel_height)
        gradient.setColorAt(0.0, QtGui.QColor("#ff315e"))
        gradient.setColorAt(0.55, QtGui.QColor("#a441ff"))
        gradient.setColorAt(1.0, QtGui.QColor("#43d9ff"))
        content_painter.fillPath(path, gradient)
        content_painter.end()
        mask_painter = QtGui.QPainter(mask)
        mask_painter.fillPath(path, QtCore.Qt.GlobalColor.white)
        mask_painter.end()

        transformed, _mask, extrusion, bevel, _pad_x, _pad_y = render_text_3d(
            qimage_to_rgba_array(content),
            qimage_to_rgba_array(mask),
            scaled_text_3d(self._effect, scale),
        )
        composite = alpha_composite_rgba(extrusion, transformed)
        composite = alpha_composite_rgba(composite, bevel)
        image = rgba_array_to_qimage(composite)
        available = QtCore.QRectF(self.rect()).adjusted(8, 7, -8, -7)
        size = QtCore.QSizeF(image.size())
        size.scale(available.size(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        target = QtCore.QRectF(QtCore.QPointF(), size)
        target.moveCenter(available.center())
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(target, image)
        painter.end()


class TextFillDialog(QtWidgets.QDialog):
    """Configure solid and multi-stop gradient text fills."""

    _STYLE_LABELS = (
        ("linear_90", "Lineal 90°"),
        ("linear_180", "Lineal 180°"),
        ("linear_135", "Lineal 135°"),
        ("radial_center", "Circular 50% / 50%"),
        ("radial_origin", "Circular 0% / 0%"),
    )
    _WARP_LABELS = (
        ("arc", "Arc"),
        ("arc_lower", "Arc lower"),
        ("arc_upper", "Arc upper"),
        ("arch", "Arch"),
        ("bulge", "Bulge"),
        ("shell_lower", "Shell lower"),
        ("shell_upper", "Shell upper"),
        ("flag", "Flag"),
        ("wave", "Wave"),
        ("fish", "Fish"),
        ("rise", "Rise"),
        ("fish_eye", "Fish eye"),
        ("inflate", "Inflate"),
        ("squeeze", "Squeeze"),
        ("twist", "Twist"),
    )
    _TEXT_3D_LABELS = (
        ("extrude", "3D extrusion"),
        ("perspective_left", "Perspective left"),
        ("perspective_right", "Perspective right"),
        ("perspective_up", "Perspective up"),
        ("perspective_down", "Perspective down"),
        ("flare_left", "Expand left end"),
        ("flare_right", "Expand right end"),
        ("skew_left", "Diagonal left"),
        ("skew_right", "Diagonal right"),
        ("trapezoid", "Trapezoid"),
    )

    def __init__(self, initial_style: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Text fill"))
        self.setModal(True)
        self._solid_dialog_size = QtCore.QSize(760, 650)
        self._gradient_dialog_size = QtCore.QSize(1080, 780)
        self.resize(self._solid_dialog_size)
        parent_theme = getattr(parent, "_is_dark_theme", None)
        self._is_dark_theme = (
            bool(parent_theme)
            if parent_theme is not None
            else dayu_theme.background_color.lower() != "#f8f8f9"
        )
        self._style = self._normalise_style(initial_style)
        # Widget setup emits valueChanged; keep it from overwriting the
        # incoming fill until both pages have been constructed.
        self._syncing = True

        self._build_ui()
        self._load_style()
        self.apply_theme(self._is_dark_theme)

    @staticmethod
    def _normalise_style(style: dict | None) -> dict:
        style = deepcopy(style or {})
        mode = style.get("mode", "solid")
        if mode not in {"solid", "gradient"}:
            mode = "solid"
        colour = _as_colour(style.get("color", "#ff000000"))
        raw_gradient = style.get("gradient", {}) if isinstance(style.get("gradient"), dict) else {}
        raw_stops = raw_gradient.get("stops", [])
        stops: list[dict] = []
        for raw_stop in raw_stops:
            if not isinstance(raw_stop, dict):
                continue
            stop_colour = _as_colour(raw_stop.get("color", "#ff000000"))
            stops.append({
                "position": max(0, min(100, int(raw_stop.get("position", 0)))),
                "color": _colour_name(stop_colour),
                "alpha": max(0, min(255, int(raw_stop.get("alpha", stop_colour.alpha())))),
            })
        if len(stops) < 2:
            stops = [
                {"position": 0, "color": _colour_name(colour), "alpha": colour.alpha()},
                {"position": 100, "color": "#ffffffff", "alpha": 255},
            ]
        glow = style.get("glow", {}) if isinstance(style.get("glow"), dict) else {}
        drop_shadow = style.get("drop_shadow", {}) if isinstance(style.get("drop_shadow"), dict) else {}
        inner_glow = style.get("inner_glow", {}) if isinstance(style.get("inner_glow"), dict) else {}
        inner_shadow = style.get("inner_shadow", {}) if isinstance(style.get("inner_shadow"), dict) else {}
        stroke = style.get("stroke", {}) if isinstance(style.get("stroke"), dict) else {}
        warp = normalise_text_warp(style.get("warp", {}))
        three_d = normalise_text_3d(style.get("three_d", {}))
        return {
            "mode": mode,
            "color": _colour_name(colour),
            "gradient": {
                "style": raw_gradient.get("style", "linear_90") if raw_gradient.get("style") in {
                    key for key, _label in TextFillDialog._STYLE_LABELS
                } else "linear_90",
                "stops": sorted(stops, key=lambda item: item["position"]),
            },
            "glow": {
                "enabled": bool(glow.get("enabled", False)),
                "color": _colour_name(_as_colour(glow.get("color", "#ff00e5ff"))),
                "opacity": max(0, min(100, int(glow.get("opacity", 85)))),
                "spread": max(0, min(100, int(glow.get("spread", 35)))),
                "size": max(1, min(80, int(glow.get("size", 12)))),
            },
            "drop_shadow": {
                "enabled": bool(drop_shadow.get("enabled", False)),
                "color": _colour_name(_as_colour(drop_shadow.get("color", "#ff000000"))),
                "opacity": max(0, min(100, int(drop_shadow.get("opacity", 55)))),
                "angle": max(0, min(360, int(drop_shadow.get("angle", 120)))),
                "distance": max(0, min(80, int(drop_shadow.get("distance", 8)))),
                "spread": max(0, min(100, int(drop_shadow.get("spread", 10)))),
                "size": max(0, min(80, int(drop_shadow.get("size", 12)))),
            },
            "inner_glow": {
                "enabled": bool(inner_glow.get("enabled", False)),
                "color": _colour_name(_as_colour(inner_glow.get("color", "#ffffffff"))),
                "opacity": max(0, min(100, int(inner_glow.get("opacity", 65)))),
                "choke": max(0, min(100, int(inner_glow.get("choke", 10)))),
                "size": max(1, min(60, int(inner_glow.get("size", 8)))),
            },
            "inner_shadow": {
                "enabled": bool(inner_shadow.get("enabled", False)),
                "color": _colour_name(_as_colour(inner_shadow.get("color", "#ff000000"))),
                "opacity": max(0, min(100, int(inner_shadow.get("opacity", 45)))),
                "angle": max(0, min(360, int(inner_shadow.get("angle", 120)))),
                "distance": max(0, min(40, int(inner_shadow.get("distance", 4)))),
                "choke": max(0, min(100, int(inner_shadow.get("choke", 5)))),
                "size": max(0, min(60, int(inner_shadow.get("size", 8)))),
            },
            "stroke": {
                "enabled": bool(stroke.get("enabled", False)),
                "color": _colour_name(_as_colour(stroke.get("color", "#ffffffff"))),
                "opacity": max(0, min(100, int(stroke.get("opacity", 100)))),
                "size": max(1, min(40, int(stroke.get("size", 3)))),
                "position": stroke.get("position", "outside")
                if stroke.get("position") in {"outside", "center", "inside"} else "outside",
            },
            "warp": warp,
            "three_d": three_d,
        }

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        mode_layout = QtWidgets.QHBoxLayout()
        self.solid_button = QtWidgets.QToolButton()
        self.solid_button.setText(self.tr("Solid color"))
        self.solid_button.setCheckable(True)
        self.gradient_button = QtWidgets.QToolButton()
        self.gradient_button.setText(self.tr("Gradient"))
        self.gradient_button.setCheckable(True)
        mode_button_style = """
            QToolButton { border: 1px solid #777; border-radius: 5px; padding: 7px 18px; }
            QToolButton:checked { background: #c63f63; color: #ffffff; border: 2px solid #ff9bb4; font-weight: bold; }
        """
        self.solid_button.setStyleSheet(mode_button_style)
        self.gradient_button.setStyleSheet(mode_button_style)
        self.mode_group = QtWidgets.QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.solid_button, 0)
        self.mode_group.addButton(self.gradient_button, 1)
        mode_layout.addWidget(self.solid_button)
        mode_layout.addWidget(self.gradient_button)
        mode_layout.addStretch()

        # Confirmation buttons live next to the mode toggles (to the right of the
        # "Gradient" button) so they stay visible in both solid and gradient modes.
        self.header_cancel_button = QtWidgets.QPushButton(self.tr("Cancel"))
        self.header_cancel_button.setObjectName("headerCancelButton")
        self.header_cancel_button.clicked.connect(self.reject)
        self.header_accept_button = QtWidgets.QPushButton(self.tr("Accept"))
        self.header_accept_button.setObjectName("headerAcceptButton")
        self.header_accept_button.setDefault(True)
        self.header_accept_button.clicked.connect(self.accept)
        self.header_cancel_button.setStyleSheet("""
            QPushButton#headerCancelButton {
                background: #2a2a31; border: 1px solid #3d3d46; color: #dcdce2;
                border-radius: 7px; padding: 7px 18px; font-weight: 600;
            }
            QPushButton#headerCancelButton:hover { background: #32323b; }
        """)
        self.header_accept_button.setStyleSheet("""
            QPushButton#headerAcceptButton {
                background: #d13655; border: 1px solid #ef6d88; color: white;
                border-radius: 7px; padding: 7px 20px; font-weight: 600;
            }
            QPushButton#headerAcceptButton:hover { background: #e24665; }
        """)
        mode_layout.addWidget(self.header_cancel_button)
        mode_layout.addWidget(self.header_accept_button)
        root.addLayout(mode_layout)

        self.pages = QtWidgets.QStackedWidget()
        self.solid_page = self._build_solid_page()
        self.gradient_page = self._build_gradient_page()
        self.pages.addWidget(self._make_scrollable_page(self.solid_page))
        self.pages.addWidget(self._make_scrollable_page(self.gradient_page))
        root.addWidget(self.pages)

        # The confirmation buttons now sit in the header row; the footer only
        # carries the gradient preview and is shown in gradient mode.
        self.gradient_footer = self._build_gradient_footer()
        self.gradient_footer.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.gradient_footer.hide()
        root.addWidget(self.gradient_footer)

        self.mode_group.idClicked.connect(self._set_mode)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark_theme = bool(is_dark)
        is_black = bool(is_dark) and dayu_theme.background_color.lower() == "#000000"
        if is_dark:
            cancel_bg = "#111111" if is_black else "#161C27"
            cancel_hover = "#242424" if is_black else "#1A314F"
            cancel_border = "#262626" if is_black else "#1D2430"
            cancel_fg = "#FFFFFF" if is_black else "#F5F7FA"
            footer_bg = "#080808" if is_black else "#111722"
            footer_border = cancel_border
            muted = "#B8B8B8" if is_black else "#AAB4C1"
            accent = dayu_theme.primary_color
            accent_border = dayu_theme.primary_color
            accent_hover = dayu_theme.primary_5
        else:
            cancel_bg = "#f7f7f9"
            cancel_hover = "#eceef2"
            cancel_border = "#cfd1d8"
            cancel_fg = "#383941"
            footer_bg = "#ffffff"
            footer_border = "#d9dbe2"
            muted = "#666873"
            accent = "#D13655"
            accent_border = "#EF6D88"
            accent_hover = "#E24665"

        mode_style = f"""
            QToolButton {{
                background: transparent; border: 1px solid {cancel_border};
                border-radius: 5px; padding: 7px 18px;
            }}
            QToolButton:checked {{
                background: {accent}; color: #ffffff;
                border: 2px solid {accent_border}; font-weight: bold;
            }}
        """
        self.solid_button.setStyleSheet(mode_style)
        self.gradient_button.setStyleSheet(mode_style)
        self.header_cancel_button.setStyleSheet(f"""
            QPushButton#headerCancelButton {{
                background: {cancel_bg}; border: 1px solid {cancel_border};
                color: {cancel_fg}; border-radius: 7px;
                padding: 7px 18px; font-weight: 600;
            }}
            QPushButton#headerCancelButton:hover {{ background: {cancel_hover}; }}
        """)
        self.header_accept_button.setStyleSheet(f"""
            QPushButton#headerAcceptButton {{
                background: {accent}; border: 1px solid {accent_border}; color: white;
                border-radius: 7px; padding: 7px 20px; font-weight: 600;
            }}
            QPushButton#headerAcceptButton:hover {{ background: {accent_hover}; }}
        """)
        self.gradient_footer.setStyleSheet(f"""
            QFrame#gradientFooter {{
                background: {footer_bg}; border: 1px solid {footer_border};
                border-radius: 9px;
            }}
            QLabel#gradientSectionTitle {{
                color: {muted}; font-size: 11px; font-weight: 700;
            }}
        """)
        self.gradient_page.setStyleSheet(self._gradient_page_stylesheet(is_dark))
        self._refresh_stop_list(max(0, self.stop_list.currentRow()))
        self.gradient_preview.apply_theme(is_dark)
        for preview in (
            getattr(self, "effects_preview", None),
            getattr(self, "warp_preview", None),
            getattr(self, "three_d_preview", None),
        ):
            if preview is not None and hasattr(preview, "apply_theme"):
                preview.apply_theme(is_dark)

    def _build_gradient_footer(self) -> QtWidgets.QWidget:
        footer = QtWidgets.QFrame()
        footer.setObjectName("gradientFooter")
        footer.setFixedHeight(64)
        layout = QtWidgets.QHBoxLayout(footer)
        layout.setContentsMargins(14, 8, 10, 8)
        layout.setSpacing(10)

        preview_label = QtWidgets.QLabel(self.tr("Preview"))
        preview_label.setObjectName("gradientSectionTitle")
        layout.addWidget(preview_label)
        self.gradient_text_preview = GradientTextSample(footer)
        layout.addWidget(self.gradient_text_preview)
        layout.addStretch()

        footer.setStyleSheet("""
            QFrame#gradientFooter {
                background: #1a1a1f;
                border: 1px solid #2b2b33;
                border-radius: 9px;
            }
            QLabel#gradientSectionTitle {
                color: #8f8f9a;
                font-size: 11px;
                font-weight: 700;
            }
            QPushButton#gradientCancelButton {
                background: #2a2a31;
                border: 1px solid #3d3d46;
                color: #dcdce2;
                border-radius: 7px;
                padding: 8px 20px;
                font-weight: 600;
            }
            QPushButton#gradientCancelButton:hover { background: #32323b; }
            QPushButton#gradientAcceptButton {
                background: #d13655;
                border: 1px solid #ef6d88;
                color: white;
                border-radius: 7px;
                padding: 8px 22px;
                font-weight: 600;
            }
            QPushButton#gradientAcceptButton:hover { background: #e24665; }
        """)
        return footer

    def _build_warp_panel(self) -> QtWidgets.QFrame:
        panel = QtWidgets.QFrame()
        panel.setObjectName("warpPanel")
        outer = QtWidgets.QHBoxLayout(panel)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(14)

        self.warp_preview = WarpTextSample(panel)
        outer.addWidget(self.warp_preview, stretch=1)

        controls = QtWidgets.QGridLayout()
        controls.setHorizontalSpacing(9)
        controls.setVerticalSpacing(6)
        self.warp_enabled = QtWidgets.QCheckBox(self.tr("Enabled"), panel)
        self.warp_enabled.toggled.connect(self._refresh_warp_preview)
        controls.addWidget(self.warp_enabled, 0, 0, 1, 3)

        self.warp_style = QtWidgets.QComboBox(panel)
        for key, label in self._WARP_LABELS:
            self.warp_style.addItem(self.tr(label), key)
        self.warp_style.currentIndexChanged.connect(self._refresh_warp_preview)
        controls.addWidget(QtWidgets.QLabel(self.tr("Style")), 1, 0)
        controls.addWidget(self.warp_style, 1, 1, 1, 2)

        self.warp_orientation = QtWidgets.QComboBox(panel)
        self.warp_orientation.addItem(self.tr("Horizontal"), "horizontal")
        self.warp_orientation.addItem(self.tr("Vertical"), "vertical")
        self.warp_orientation.currentIndexChanged.connect(self._refresh_warp_preview)
        controls.addWidget(QtWidgets.QLabel(self.tr("Orientation")), 2, 0)
        controls.addWidget(self.warp_orientation, 2, 1, 1, 2)

        self.warp_sliders: dict[str, QtWidgets.QSlider] = {}
        self.warp_value_labels: dict[str, QtWidgets.QLabel] = {}
        slider_definitions = (
            ("bend", self.tr("Bend")),
            ("horizontal", self.tr("Horizontal distortion")),
            ("vertical", self.tr("Vertical distortion")),
        )
        for row, (key, label) in enumerate(slider_definitions, start=3):
            slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal, panel)
            slider.setRange(-100, 100)
            value_label = QtWidgets.QLabel("0 %", panel)
            value_label.setFixedWidth(46)
            value_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            slider.valueChanged.connect(
                lambda value, target=value_label: target.setText(f"{value} %")
            )
            slider.valueChanged.connect(self._refresh_warp_preview)
            self.warp_sliders[key] = slider
            self.warp_value_labels[key] = value_label
            controls.addWidget(QtWidgets.QLabel(label), row, 0)
            controls.addWidget(slider, row, 1)
            controls.addWidget(value_label, row, 2)

        reset = QtWidgets.QPushButton(self.tr("Reset deformation"), panel)
        reset.clicked.connect(self._reset_warp_controls)
        controls.addWidget(reset, 6, 1, 1, 2)
        controls.setColumnStretch(1, 1)
        outer.addLayout(controls, stretch=2)
        panel.setStyleSheet("""
            QFrame#warpPanel {
                background: #202027;
                border: 1px solid #34343d;
                border-radius: 9px;
            }
            QFrame#warpPanel QLabel, QFrame#warpPanel QCheckBox {
                color: #dedee5;
                border: none;
            }
        """)
        return panel

    def _toggle_warp_panel(self, expanded: bool) -> None:
        self.warp_section_button.setArrowType(
            QtCore.Qt.ArrowType.DownArrow if expanded else QtCore.Qt.ArrowType.RightArrow
        )
        self.warp_panel.setVisible(expanded)

    def _sync_warp_controls(self) -> None:
        warp = self._style["warp"]
        warp["enabled"] = self.warp_enabled.isChecked()
        warp["style"] = self.warp_style.currentData() or "flag"
        warp["orientation"] = self.warp_orientation.currentData() or "horizontal"
        for key, slider in self.warp_sliders.items():
            warp[key] = slider.value()

    def _refresh_warp_preview(self, *_args) -> None:
        if self._syncing or not hasattr(self, "warp_preview"):
            return
        self._sync_warp_controls()
        enabled = self.warp_enabled.isChecked()
        self.warp_style.setEnabled(enabled)
        self.warp_orientation.setEnabled(enabled)
        for slider in self.warp_sliders.values():
            slider.setEnabled(enabled)
        self.warp_preview.set_warp(self._style["warp"])

    def _reset_warp_controls(self) -> None:
        self.warp_enabled.setChecked(False)
        self.warp_style.setCurrentIndex(0)
        self.warp_orientation.setCurrentIndex(0)
        self.warp_sliders["bend"].setValue(24)
        self.warp_sliders["horizontal"].setValue(0)
        self.warp_sliders["vertical"].setValue(0)
        self._refresh_warp_preview()

    def _build_three_d_panel(self) -> QtWidgets.QFrame:
        panel = QtWidgets.QFrame()
        panel.setObjectName("threeDPanel")
        outer = QtWidgets.QHBoxLayout(panel)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(14)

        self.three_d_preview = Text3DSample(panel)
        outer.addWidget(self.three_d_preview, stretch=1)
        controls = QtWidgets.QGridLayout()
        controls.setHorizontalSpacing(9)
        controls.setVerticalSpacing(5)

        self.three_d_enabled = QtWidgets.QCheckBox(self.tr("Enabled"), panel)
        self.three_d_enabled.toggled.connect(self._refresh_three_d_preview)
        controls.addWidget(self.three_d_enabled, 0, 0, 1, 3)

        self.three_d_style = QtWidgets.QComboBox(panel)
        for key, label in self._TEXT_3D_LABELS:
            self.three_d_style.addItem(self.tr(label), key)
        self.three_d_style.currentIndexChanged.connect(self._refresh_three_d_preview)
        controls.addWidget(QtWidgets.QLabel(self.tr("Effect")), 1, 0)
        controls.addWidget(self.three_d_style, 1, 1, 1, 2)

        self.three_d_extrude = QtWidgets.QCheckBox(self.tr("Extrusion"), panel)
        self.three_d_extrude.toggled.connect(self._refresh_three_d_preview)
        controls.addWidget(self.three_d_extrude, 2, 0)
        self.three_d_colour = QtWidgets.QPushButton(panel)
        self.three_d_colour.clicked.connect(self._choose_three_d_colour)
        controls.addWidget(self.three_d_colour, 2, 1, 1, 2)

        self.three_d_sliders: dict[str, QtWidgets.QSlider] = {}
        self.three_d_value_labels: dict[str, QtWidgets.QLabel] = {}
        definitions = (
            ("strength", self.tr("Perspective strength"), 0, 100, " %"),
            ("depth", self.tr("Depth"), 1, 80, " px"),
            ("angle", self.tr("Extrusion angle"), 0, 359, "°"),
            ("bevel", self.tr("Bevel"), 0, 100, " %"),
        )
        for row, (key, label, minimum, maximum, suffix) in enumerate(definitions, start=3):
            slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal, panel)
            slider.setRange(minimum, maximum)
            value_label = QtWidgets.QLabel(panel)
            value_label.setFixedWidth(56)
            value_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            slider.valueChanged.connect(
                lambda value, target=value_label, unit=suffix: target.setText(f"{value}{unit}")
            )
            slider.valueChanged.connect(self._refresh_three_d_preview)
            self.three_d_sliders[key] = slider
            self.three_d_value_labels[key] = value_label
            controls.addWidget(QtWidgets.QLabel(label), row, 0)
            controls.addWidget(slider, row, 1)
            controls.addWidget(value_label, row, 2)

        reset = QtWidgets.QPushButton(self.tr("Reset 3D effect"), panel)
        reset.clicked.connect(self._reset_three_d_controls)
        controls.addWidget(reset, 7, 1, 1, 2)
        controls.setColumnStretch(1, 1)
        outer.addLayout(controls, stretch=2)
        panel.setStyleSheet("""
            QFrame#threeDPanel {
                background: #202027;
                border: 1px solid #34343d;
                border-radius: 9px;
            }
            QFrame#threeDPanel QLabel, QFrame#threeDPanel QCheckBox {
                color: #dedee5;
                border: none;
            }
        """)
        return panel

    def _toggle_three_d_panel(self, expanded: bool) -> None:
        self.three_d_section_button.setArrowType(
            QtCore.Qt.ArrowType.DownArrow if expanded else QtCore.Qt.ArrowType.RightArrow
        )
        self.three_d_panel.setVisible(expanded)

    def _sync_three_d_controls(self) -> None:
        effect = self._style["three_d"]
        effect["enabled"] = self.three_d_enabled.isChecked()
        effect["style"] = self.three_d_style.currentData() or "perspective_left"
        effect["extrude"] = self.three_d_extrude.isChecked()
        for key, slider in self.three_d_sliders.items():
            effect[key] = slider.value()

    def _refresh_three_d_preview(self, *_args) -> None:
        if self._syncing or not hasattr(self, "three_d_preview"):
            return
        self._sync_three_d_controls()
        enabled = self.three_d_enabled.isChecked()
        self.three_d_style.setEnabled(enabled)
        self.three_d_extrude.setEnabled(enabled)
        self.three_d_colour.setEnabled(enabled and self.three_d_extrude.isChecked())
        for key, slider in self.three_d_sliders.items():
            slider.setEnabled(enabled and (key not in {"depth", "angle"} or self.three_d_extrude.isChecked()))
        self._set_colour_button(self.three_d_colour, _as_colour(self._style["three_d"]["color"]))
        self.three_d_preview.set_effect(self._style["three_d"])

    def _choose_three_d_colour(self) -> None:
        colour = QtWidgets.QColorDialog.getColor(
            _as_colour(self._style["three_d"]["color"]),
            self,
            self.tr("Extrusion color"),
            QtWidgets.QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if colour.isValid():
            self._style["three_d"]["color"] = _colour_name(colour)
            self._refresh_three_d_preview()

    def _reset_three_d_controls(self) -> None:
        defaults = normalise_text_3d({})
        self.three_d_enabled.setChecked(False)
        self.three_d_style.setCurrentIndex(
            max(0, self.three_d_style.findData(defaults["style"]))
        )
        self.three_d_extrude.setChecked(defaults["extrude"])
        for key, slider in self.three_d_sliders.items():
            slider.setValue(defaults[key])
        self._style["three_d"]["color"] = defaults["color"]
        self._refresh_three_d_preview()

    @staticmethod
    def _make_scrollable_page(content: QtWidgets.QWidget) -> QtWidgets.QScrollArea:
        """Keep the full colour box accessible on shorter screens."""
        scroll = QtWidgets.QScrollArea()
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _build_solid_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        self.solid_picker_label = QtWidgets.QLabel()
        self.solid_picker_label.hide()

        self.solid_picker = QtWidgets.QColorDialog(page)
        self.solid_picker.setOption(QtWidgets.QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        self.solid_picker.setOption(QtWidgets.QColorDialog.ColorDialogOption.NoButtons, True)
        self.solid_picker.setOption(QtWidgets.QColorDialog.ColorDialogOption.ShowAlphaChannel, True)
        self._prepare_inline_colour_picker(self.solid_picker)
        self.solid_picker.currentColorChanged.connect(self._on_solid_colour_changed)
        layout.addWidget(self.solid_picker)

        self.add_custom_colour_button = QtWidgets.QPushButton(self.tr("Add to custom colors"))
        self.add_custom_colour_button.clicked.connect(self._add_current_to_custom_colours)
        layout.addWidget(self.add_custom_colour_button, alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        return page

    def _build_gradient_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        page.setObjectName("gradientPage")
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        stops_card = self._gradient_card(page)
        stops_layout = QtWidgets.QVBoxLayout(stops_card)
        stops_layout.setContentsMargins(16, 14, 16, 16)
        stops_layout.setSpacing(10)

        stops_heading = QtWidgets.QHBoxLayout()
        stops_heading.setSpacing(10)
        stops_heading.addWidget(self._gradient_section_title(self.tr("Gradient stops")))
        hint = QtWidgets.QLabel(self.tr("Click the bar to add a stop where you want it"))
        hint.setObjectName("gradientHint")
        stops_heading.addWidget(hint)
        stops_heading.addStretch()
        stops_layout.addLayout(stops_heading)

        self.gradient_preview = GradientStopBar(stops_card)
        self.gradient_preview.stopActivated.connect(self._select_stop_from_bar)
        self.gradient_preview.stopAddRequested.connect(self._add_stop_at)
        self.gradient_preview.stopMoved.connect(self._move_stop_from_bar)
        self.gradient_preview.stopMoveFinished.connect(
            self._finish_stop_move_from_bar
        )
        stops_layout.addWidget(self.gradient_preview)

        editor = QtWidgets.QHBoxLayout()
        editor.setSpacing(14)
        list_host = QtWidgets.QWidget(stops_card)
        list_layout = QtWidgets.QVBoxLayout(list_host)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(5)

        list_header = QtWidgets.QHBoxLayout()
        list_header.setContentsMargins(10, 0, 10, 0)
        colour_header = QtWidgets.QLabel(self.tr("Color"))
        colour_header.setObjectName("gradientColumnHeader")
        position_header = QtWidgets.QLabel(self.tr("Pos"))
        position_header.setObjectName("gradientColumnHeader")
        position_header.setFixedWidth(48)
        position_header.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        opacity_header = QtWidgets.QLabel(self.tr("Opacity"))
        opacity_header.setObjectName("gradientColumnHeader")
        opacity_header.setFixedWidth(62)
        opacity_header.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        list_header.addSpacing(28)
        list_header.addWidget(colour_header)
        list_header.addStretch()
        list_header.addWidget(position_header)
        list_header.addWidget(opacity_header)
        list_layout.addLayout(list_header)

        self.stop_list = QtWidgets.QListWidget()
        self.stop_list.setObjectName("gradientStopList")
        self.stop_list.setMinimumHeight(128)
        self.stop_list.setMaximumHeight(148)
        self.stop_list.setSpacing(4)
        self.stop_list.currentRowChanged.connect(self._load_selected_stop)
        list_layout.addWidget(self.stop_list)

        list_actions = QtWidgets.QHBoxLayout()
        list_actions.setSpacing(8)
        self.add_stop_button = QtWidgets.QPushButton(self.tr("+ Add stop"))
        self.add_stop_button.setObjectName("gradientSecondaryButton")
        self.add_stop_button.clicked.connect(self._add_stop)
        self.remove_stop_button = QtWidgets.QPushButton(self.tr("− Remove stop"))
        self.remove_stop_button.setObjectName("gradientSecondaryButton")
        self.remove_stop_button.clicked.connect(self._remove_stop)
        list_actions.addWidget(self.add_stop_button)
        list_actions.addWidget(self.remove_stop_button)
        list_actions.addStretch()
        list_layout.addLayout(list_actions)
        editor.addWidget(list_host, stretch=1)

        selected_card = QtWidgets.QFrame(stops_card)
        selected_card.setObjectName("selectedStopCard")
        selected_card.setFixedWidth(290)
        selected_layout = QtWidgets.QVBoxLayout(selected_card)
        selected_layout.setContentsMargins(14, 12, 14, 13)
        selected_layout.setSpacing(9)
        selected_layout.addWidget(self._gradient_section_title(self.tr("Selected stop")))

        colour_row = QtWidgets.QHBoxLayout()
        colour_row.setSpacing(10)
        colour_label = QtWidgets.QLabel(self.tr("Color"))
        colour_label.setObjectName("selectedStopLabel")
        colour_label.setFixedWidth(58)
        self.stop_colour_button = QtWidgets.QPushButton()
        self.stop_colour_button.setObjectName("selectedStopSwatch")
        self.stop_colour_button.setFixedSize(28, 28)
        self.stop_colour_button.setToolTip(self.tr("Edit this color in the color box below."))
        self.stop_colour_button.clicked.connect(self._activate_gradient_colour_picker)
        self.selected_stop_hex_label = QtWidgets.QLabel("#000000")
        self.selected_stop_hex_label.setObjectName("selectedStopHex")
        colour_row.addWidget(colour_label)
        colour_row.addWidget(self.stop_colour_button)
        colour_row.addWidget(self.selected_stop_hex_label)
        colour_row.addStretch()
        selected_layout.addLayout(colour_row)

        position_row = QtWidgets.QHBoxLayout()
        position_row.setSpacing(10)
        position_label = QtWidgets.QLabel(self.tr("Position"))
        position_label.setObjectName("selectedStopLabel")
        position_label.setFixedWidth(58)
        self.stop_position = QtWidgets.QSpinBox()
        self.stop_position.setObjectName("selectedStopSpin")
        self.stop_position.setRange(0, 100)
        self.stop_position.setFixedWidth(70)
        self.stop_position.valueChanged.connect(self._update_selected_stop)
        position_row.addWidget(position_label)
        position_row.addWidget(self.stop_position)
        position_row.addWidget(QtWidgets.QLabel("%"))
        position_row.addStretch()
        selected_layout.addLayout(position_row)

        opacity_row = QtWidgets.QHBoxLayout()
        opacity_row.setSpacing(9)
        opacity_label = QtWidgets.QLabel(self.tr("Opacity"))
        opacity_label.setObjectName("selectedStopLabel")
        opacity_label.setFixedWidth(58)
        self.stop_alpha = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.stop_alpha.setObjectName("selectedStopOpacity")
        self.stop_alpha.setRange(0, 255)
        self.stop_alpha.setTickInterval(25)
        self.stop_alpha.valueChanged.connect(self._update_selected_stop)
        self.alpha_label = QtWidgets.QLabel("100 %")
        self.alpha_label.setObjectName("selectedStopValue")
        self.alpha_label.setFixedWidth(42)
        self.alpha_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        opacity_row.addWidget(opacity_label)
        opacity_row.addWidget(self.stop_alpha, stretch=1)
        opacity_row.addWidget(self.alpha_label)
        selected_layout.addLayout(opacity_row)
        selected_layout.addStretch()
        editor.addWidget(selected_card)
        stops_layout.addLayout(editor)
        layout.addWidget(stops_card)

        color_card = self._gradient_card(page)
        color_layout = QtWidgets.QVBoxLayout(color_card)
        color_layout.setContentsMargins(16, 14, 16, 14)
        color_layout.setSpacing(10)

        color_and_styles = QtWidgets.QHBoxLayout()
        color_and_styles.setSpacing(16)

        picker_column = QtWidgets.QVBoxLayout()
        picker_column.setContentsMargins(0, 0, 0, 0)
        picker_column.setSpacing(10)
        picker_column.addWidget(self._gradient_section_title(self.tr("Color")))
        self.gradient_picker = QtWidgets.QColorDialog(color_card)
        self.gradient_picker.setOption(QtWidgets.QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        self.gradient_picker.setOption(QtWidgets.QColorDialog.ColorDialogOption.NoButtons, True)
        self.gradient_picker.setOption(QtWidgets.QColorDialog.ColorDialogOption.ShowAlphaChannel, True)
        self._prepare_inline_colour_picker(self.gradient_picker)
        self.gradient_picker.currentColorChanged.connect(self._on_gradient_colour_changed)
        picker_column.addWidget(self.gradient_picker)
        color_and_styles.addLayout(picker_column, stretch=1)

        styles_column = QtWidgets.QVBoxLayout()
        styles_column.setContentsMargins(0, 0, 0, 0)
        styles_column.setSpacing(8)
        styles_column.addWidget(self._gradient_section_title(self.tr("Gradient style")))
        self.gradient_style_group = QtWidgets.QButtonGroup(self)
        self.gradient_style_group.setExclusive(True)
        self.gradient_style_buttons: dict[str, QtWidgets.QToolButton] = {}
        for index, (key, label) in enumerate(self._STYLE_LABELS):
            button = QtWidgets.QToolButton()
            button.setText(self.tr(label))
            button.setCheckable(True)
            button.setObjectName("gradientStyleButton")
            button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setIcon(self._gradient_style_icon(key))
            button.setIconSize(QtCore.QSize(26, 26))
            button.setMinimumWidth(188)
            button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
            self.gradient_style_group.addButton(button, index)
            self.gradient_style_buttons[key] = button
            styles_column.addWidget(button)
        self.gradient_style_group.idClicked.connect(self._on_gradient_style_selected)
        styles_column.addStretch()

        add_gradient_custom = QtWidgets.QPushButton(self.tr("Add to custom colors"))
        add_gradient_custom.setObjectName("gradientSecondaryButton")
        add_gradient_custom.clicked.connect(self._add_gradient_to_custom_colours)
        styles_column.addWidget(add_gradient_custom)
        color_and_styles.addLayout(styles_column)

        color_layout.addLayout(color_and_styles)
        layout.addWidget(color_card)
        layout.addStretch()
        page.setStyleSheet(self._gradient_page_stylesheet(self._is_dark_theme))
        return page

    @staticmethod
    def _gradient_card(parent: QtWidgets.QWidget) -> QtWidgets.QFrame:
        card = QtWidgets.QFrame(parent)
        card.setObjectName("gradientCard")
        return card

    @staticmethod
    def _gradient_section_title(text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text.upper())
        label.setObjectName("gradientSectionTitle")
        return label

    def _gradient_style_icon(self, style: str) -> QtGui.QIcon:
        pixmap = QtGui.QPixmap(28, 28)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        rect = QtCore.QRectF(1, 1, 26, 26)
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, 5, 5)
        sample_stops = [
            {"position": 0, "color": "#ff7e001b", "alpha": 255},
            {"position": 100, "color": "#ffffffff", "alpha": 255},
        ]
        painter.fillPath(path, QtGui.QBrush(_gradient_for_rect(rect, sample_stops, style)))
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor("#5a5a64" if self._is_dark_theme else "#aeb2ba")
            )
        )
        painter.drawPath(path)
        painter.end()
        return QtGui.QIcon(pixmap)

    @staticmethod
    def _gradient_page_stylesheet(is_dark: bool = True) -> str:
        is_black = bool(is_dark) and dayu_theme.background_color.lower() == "#000000"
        if is_dark:
            page_fg = "#FFFFFF" if is_black else "#F5F7FA"
            card_bg = "#080808" if is_black else "#111722"
            card_border = "#262626" if is_black else "#1D2430"
            selected_card_bg = "#111111" if is_black else "#141A25"
            selected_card_border = card_border
            section = "#B8B8B8" if is_black else "#AAB4C1"
            hint = "#606060" if is_black else "#667386"
            column = section
            item_bg = "#111111" if is_black else "#161C27"
            item_border = card_border
            selected_bg = "#FFFFFF" if is_black else "#1A314F"
            control_bg = item_bg
            control_border = card_border
            control_fg = page_fg
            control_hover = "#242424" if is_black else "#1A314F"
            disabled_fg = hint
            disabled_bg = "#0A0A0A" if is_black else "#111722"
            label_fg = section
            value_fg = page_fg
            groove = card_border
            checked_bg = "#FFFFFF" if is_black else "#1462A9"
            checked_fg = "#000000" if is_black else "#F5F7FA"
            swatch_border = "rgba(255,255,255,55)"
            accent = dayu_theme.primary_color
        else:
            page_fg = "#34353d"
            card_bg = "#ffffff"
            card_border = "#d9dbe2"
            selected_card_bg = "#f7f7f9"
            selected_card_border = "#d9dbe2"
            section = "#646670"
            hint = "#7a7c86"
            column = "#777984"
            item_bg = "#f7f7f9"
            item_border = "#dde0e6"
            selected_bg = "#fff0f4"
            control_bg = "#f7f7f9"
            control_border = "#cfd1d8"
            control_fg = "#383941"
            control_hover = "#eceef2"
            disabled_fg = "#a5a7af"
            disabled_bg = "#f0f1f4"
            label_fg = "#61636c"
            value_fg = "#34353d"
            groove = "#d7d9df"
            checked_bg = "#f9dfe6"
            checked_fg = "#7d2139"
            swatch_border = "rgba(0,0,0,55)"
            accent = "#D13655"

        return f"""
            QWidget#gradientPage {{ background: transparent; color: {page_fg}; }}
            QFrame#gradientCard {{
                background: {card_bg}; border: 1px solid {card_border};
                border-radius: 10px;
            }}
            QFrame#selectedStopCard {{
                background: {selected_card_bg}; border: 1px solid {selected_card_border};
                border-radius: 8px;
            }}
            QLabel#gradientSectionTitle {{
                color: {section}; font-size: 11px; font-weight: 700;
            }}
            QLabel#gradientHint {{ color: {hint}; font-size: 12px; }}
            QLabel#gradientColumnHeader {{
                color: {column}; font-size: 10px; font-weight: 700;
            }}
            QListWidget#gradientStopList {{
                background: transparent; border: none; outline: none;
            }}
            QListWidget#gradientStopList::item {{
                background: {item_bg}; border: 1px solid {item_border};
                border-radius: 7px;
            }}
            QListWidget#gradientStopList::item:selected {{
                background: {selected_bg}; border: 1px solid {accent};
            }}
            QPushButton#gradientSecondaryButton {{
                background: {control_bg}; border: 1px solid {control_border};
                color: {control_fg}; border-radius: 7px; padding: 7px 14px;
                font-size: 12px; font-weight: 600;
            }}
            QPushButton#gradientSecondaryButton:hover {{ background: {control_hover}; }}
            QPushButton#gradientSecondaryButton:disabled {{
                color: {disabled_fg}; background: {disabled_bg};
            }}
            QLabel#selectedStopLabel {{ color: {label_fg}; font-size: 12px; }}
            QLabel#selectedStopHex {{
                color: {value_fg}; font-family: Consolas; font-size: 12px;
            }}
            QLabel#selectedStopValue {{ color: {value_fg}; font-size: 12px; }}
            QPushButton#selectedStopSwatch {{
                border: 1px solid {swatch_border}; border-radius: 6px; padding: 0;
            }}
            QSpinBox#selectedStopSpin {{
                background: {control_bg}; border: 1px solid {control_border};
                border-radius: 6px; color: {value_fg}; padding: 5px 7px;
            }}
            QSlider#selectedStopOpacity::groove:horizontal {{
                height: 5px; border-radius: 2px; background: {groove};
            }}
            QSlider#selectedStopOpacity::sub-page:horizontal {{
                background: {accent}; border-radius: 2px;
            }}
            QSlider#selectedStopOpacity::handle:horizontal {{
                width: 14px; margin: -5px 0; border-radius: 7px;
                background: white; border: 1px solid #a0a0aa;
            }}
            QToolButton#gradientStyleButton {{
                background: {control_bg}; border: 1px solid {control_border};
                border-radius: 8px; color: {control_fg}; padding: 7px 10px;
                font-size: 12px; font-weight: 600;
            }}
            QToolButton#gradientStyleButton:hover {{ background: {control_hover}; }}
            QToolButton#gradientStyleButton:checked {{
                background: {checked_bg}; border: 2px solid {accent};
                color: {checked_fg};
            }}
        """

    @staticmethod
    def _prepare_inline_colour_picker(picker: QtWidgets.QColorDialog) -> None:
        """Make QColorDialog behave as a visible child widget, not a popup."""
        picker.setWindowFlags(QtCore.Qt.WindowType.Widget)
        picker.setMinimumSize(picker.sizeHint())
        picker.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        picker.show()

    def _build_glow_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox(self.tr("Layer effects"))
        layout = QtWidgets.QVBoxLayout(group)
        layout.setSpacing(9)

        description = QtWidgets.QLabel(
            self.tr("Effects are generated from one blurred text mask, like a Photoshop layer style.")
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #8f8f9a;")
        layout.addWidget(description)

        self.effects_preview = LayerEffectsTextSample(group)
        layout.addWidget(self.effects_preview)

        self.effect_controls: dict[str, dict[str, QtWidgets.QWidget]] = {}
        tabs = QtWidgets.QTabWidget(group)
        tabs.setDocumentMode(True)
        tabs.setMinimumHeight(250)
        definitions = (
            ("glow", self.tr("Outer glow"), (
                ("opacity", self.tr("Opacity"), 0, 100, " %"),
                ("spread", self.tr("Spread"), 0, 100, " %"),
                ("size", self.tr("Size"), 1, 80, " px"),
            )),
            ("drop_shadow", self.tr("Drop shadow"), (
                ("opacity", self.tr("Opacity"), 0, 100, " %"),
                ("angle", self.tr("Angle"), 0, 360, "°"),
                ("distance", self.tr("Distance"), 0, 80, " px"),
                ("spread", self.tr("Spread"), 0, 100, " %"),
                ("size", self.tr("Size"), 0, 80, " px"),
            )),
            ("inner_glow", self.tr("Inner glow"), (
                ("opacity", self.tr("Opacity"), 0, 100, " %"),
                ("choke", self.tr("Choke"), 0, 100, " %"),
                ("size", self.tr("Size"), 1, 60, " px"),
            )),
            ("inner_shadow", self.tr("Inner shadow"), (
                ("opacity", self.tr("Opacity"), 0, 100, " %"),
                ("angle", self.tr("Angle"), 0, 360, "°"),
                ("distance", self.tr("Distance"), 0, 40, " px"),
                ("choke", self.tr("Choke"), 0, 100, " %"),
                ("size", self.tr("Size"), 0, 60, " px"),
            )),
            ("stroke", self.tr("Stroke"), (
                ("opacity", self.tr("Opacity"), 0, 100, " %"),
                ("size", self.tr("Size"), 1, 40, " px"),
            )),
        )
        for effect_key, tab_label, sliders in definitions:
            tabs.addTab(self._build_effect_page(effect_key, sliders, tabs), tab_label)
        layout.addWidget(tabs)
        return group

    def _build_effect_page(self, effect_key: str, sliders: tuple, parent) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(parent)
        layout = QtWidgets.QGridLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(7)
        controls: dict[str, QtWidgets.QWidget] = {}

        enabled = QtWidgets.QCheckBox(self.tr("Enabled"), page)
        enabled.toggled.connect(self._refresh_effect_preview)
        controls["enabled"] = enabled
        layout.addWidget(enabled, 0, 0, 1, 3)

        colour_button = QtWidgets.QPushButton(page)
        colour_button.setToolTip(self.tr("Select this effect color in the color box above."))
        colour_button.clicked.connect(
            lambda _checked=False, key=effect_key: self._activate_effect_colour_picker(key)
        )
        controls["color"] = colour_button
        layout.addWidget(QtWidgets.QLabel(self.tr("Color")), 1, 0)
        layout.addWidget(colour_button, 1, 1, 1, 2)

        row = 2
        for field, label_text, minimum, maximum, suffix in sliders:
            slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal, page)
            slider.setRange(minimum, maximum)
            value_label = QtWidgets.QLabel(page)
            value_label.setFixedWidth(58)
            value_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            slider.valueChanged.connect(
                lambda value, target=value_label, unit=suffix: target.setText(f"{value}{unit}")
            )
            slider.valueChanged.connect(self._refresh_effect_preview)
            controls[field] = slider
            controls[f"{field}_label"] = value_label
            layout.addWidget(QtWidgets.QLabel(label_text), row, 0)
            layout.addWidget(slider, row, 1)
            layout.addWidget(value_label, row, 2)
            row += 1

        if effect_key == "stroke":
            position = QtWidgets.QComboBox(page)
            position.addItem(self.tr("Outside"), "outside")
            position.addItem(self.tr("Center"), "center")
            position.addItem(self.tr("Inside"), "inside")
            position.currentIndexChanged.connect(self._refresh_effect_preview)
            controls["position"] = position
            layout.addWidget(QtWidgets.QLabel(self.tr("Position")), row, 0)
            layout.addWidget(position, row, 1, 1, 2)

        layout.setColumnStretch(1, 1)
        self.effect_controls[effect_key] = controls
        return page

    def _load_style(self) -> None:
        self._syncing = True
        try:
            mode_index = 0 if self._style["mode"] == "solid" else 1
            self.solid_button.setChecked(mode_index == 0)
            self.gradient_button.setChecked(mode_index == 1)
            self.pages.setCurrentIndex(mode_index)
            self.gradient_footer.setVisible(mode_index == 1)
            self._refresh_stop_list()
            self.gradient_style_buttons[self._style["gradient"]["style"]].setChecked(True)
            self.solid_picker.setCurrentColor(_as_colour(self._style["color"]))
        finally:
            self._syncing = False
        self.resize(self._solid_dialog_size if mode_index == 0 else self._gradient_dialog_size)

    def _set_mode(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.gradient_footer.setVisible(index == 1)
        self._style["mode"] = "solid" if index == 0 else "gradient"
        self.resize(self._solid_dialog_size if index == 0 else self._gradient_dialog_size)
        if index == 1:
            self._refresh_gradient_previews()

    def _on_solid_colour_changed(self, colour: QtGui.QColor) -> None:
        if not colour.isValid() or self._syncing:
            return
        self._style["color"] = _colour_name(colour)

    def _add_current_to_custom_colours(self) -> None:
        colour = self.solid_picker.currentColor()
        self._add_to_custom_colours(colour)

    @staticmethod
    def _add_to_custom_colours(colour: QtGui.QColor) -> None:
        for index in range(QtWidgets.QColorDialog.customCount()):
            if QtWidgets.QColorDialog.customColor(index) == colour.rgba():
                return
        for index in range(QtWidgets.QColorDialog.customCount()):
            if QtWidgets.QColorDialog.customColor(index) == 0:
                QtWidgets.QColorDialog.setCustomColor(index, colour.rgba())
                return
        QtWidgets.QColorDialog.setCustomColor(QtWidgets.QColorDialog.customCount() - 1, colour.rgba())

    def _set_solid_picker_target(self, target: str) -> None:
        """Reuse the inline picker for the fill and every layer-effect color."""
        self._solid_picker_target = target
        colour_value = (
            self._style[target]["color"]
            if target in self.effect_controls
            else self._style["color"]
        )
        previous_sync = self._syncing
        self._syncing = True
        try:
            self.solid_picker.setCurrentColor(_as_colour(colour_value))
        finally:
            self._syncing = previous_sync
        for effect_key, controls in self.effect_controls.items():
            self._set_colour_button(controls["color"], _as_colour(self._style[effect_key]["color"]))
        if target in self.effect_controls:
            self.solid_picker_label.setText(
                self.tr("Effect color — edit it directly in the color box above.")
            )
            self._highlight_active_effect_colour(target)
        else:
            self.solid_picker_label.setText(
                self.tr("Solid fill color — choose it directly in the color box below.")
            )

    def _highlight_active_effect_colour(self, effect_key: str) -> None:
        button = self.effect_controls[effect_key]["color"]
        button.setStyleSheet(
            button.styleSheet() + f"border: 2px solid {dayu_theme.primary_color};"
        )

    def _activate_effect_colour_picker(self, effect_key: str) -> None:
        self._set_solid_picker_target(effect_key)
        self.solid_picker.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)

    def _sync_effect_controls(self) -> None:
        for effect_key, controls in self.effect_controls.items():
            effect = self._style[effect_key]
            effect["enabled"] = controls["enabled"].isChecked()
            for field, control in controls.items():
                if isinstance(control, QtWidgets.QSlider):
                    effect[field] = control.value()
            position = controls.get("position")
            if isinstance(position, QtWidgets.QComboBox):
                effect["position"] = position.currentData()

    def _refresh_effect_preview(self, *_args) -> None:
        if self._syncing or not hasattr(self, "effects_preview"):
            return
        self._sync_effect_controls()
        self.effects_preview.set_style(self._style)

    def _refresh_stop_list(self, selected: int = 0) -> None:
        self.stop_list.blockSignals(True)
        self.stop_list.clear()
        for stop in self._style["gradient"]["stops"]:
            colour = _as_colour(stop["color"])
            colour.setAlpha(stop["alpha"])
            item = QtWidgets.QListWidgetItem()
            item.setData(QtCore.Qt.ItemDataRole.UserRole, stop)
            item.setSizeHint(QtCore.QSize(0, 34))
            self.stop_list.addItem(item)
            self.stop_list.setItemWidget(item, self._build_stop_row(stop, colour))
        self.stop_list.blockSignals(False)
        if self.stop_list.count():
            selected = max(0, min(selected, self.stop_list.count() - 1))
            self.stop_list.setCurrentRow(selected)
        self.remove_stop_button.setEnabled(len(self._style["gradient"]["stops"]) > 2)
        self._refresh_gradient_previews(selected)

    def _build_stop_row(self, stop: dict, colour: QtGui.QColor) -> QtWidgets.QWidget:
        row = QtWidgets.QWidget()
        row.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.setStyleSheet("background: transparent; border: none;")
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(10)

        swatch = QtWidgets.QLabel()
        swatch.setFixedSize(18, 18)
        swatch.setStyleSheet(
            f"background-color: {colour.name(QtGui.QColor.NameFormat.HexArgb)}; "
            f"border: 1px solid {'rgba(255,255,255,70)' if self._is_dark_theme else 'rgba(0,0,0,55)'}; "
            "border-radius: 5px;"
        )
        colour_text = QtWidgets.QLabel(colour.name(QtGui.QColor.NameFormat.HexRgb).upper())
        primary = "#e6e6ec" if self._is_dark_theme else "#34353d"
        secondary = "#9a9aa5" if self._is_dark_theme else "#73757f"
        colour_text.setStyleSheet(
            f"color: {primary}; font-family: Consolas; font-size: 12px;"
        )
        position_text = QtWidgets.QLabel(f"{stop['position']} %")
        position_text.setFixedWidth(48)
        position_text.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        position_text.setStyleSheet(f"color: {secondary}; font-size: 12px;")
        opacity_text = QtWidgets.QLabel(f"{round(stop['alpha'] / 255 * 100)} %")
        opacity_text.setFixedWidth(62)
        opacity_text.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        opacity_text.setStyleSheet(f"color: {secondary}; font-size: 12px;")
        layout.addWidget(swatch)
        layout.addWidget(colour_text)
        layout.addStretch()
        layout.addWidget(position_text)
        layout.addWidget(opacity_text)
        return row

    def _refresh_gradient_previews(self, selected: int | None = None) -> None:
        if selected is None:
            selected = self.stop_list.currentRow()
        stops = self._style["gradient"]["stops"]
        style = self._style["gradient"].get("style", "linear_90")
        self.gradient_preview.set_stops(stops, selected)
        self.gradient_text_preview.set_gradient(stops, style)

    def _on_gradient_style_selected(self, index: int) -> None:
        if index < 0 or index >= len(self._STYLE_LABELS):
            return
        self._style["gradient"]["style"] = self._STYLE_LABELS[index][0]
        self._refresh_gradient_previews()

    def _select_stop_from_bar(self, index: int) -> None:
        if 0 <= index < self.stop_list.count():
            self.stop_list.setCurrentRow(index)

    def _move_stop_from_bar(self, index: int, position: int) -> None:
        stops = self._style["gradient"]["stops"]
        if index < 0 or index >= len(stops):
            return
        stops[index]["position"] = max(0, min(100, int(position)))
        if self.stop_list.currentRow() != index:
            self.stop_list.setCurrentRow(index)
        previous_sync = self._syncing
        self._syncing = True
        try:
            self.stop_position.setValue(stops[index]["position"])
        finally:
            self._syncing = previous_sync
        self.gradient_text_preview.set_gradient(
            stops,
            self._style["gradient"].get("style", "linear_90"),
        )

    def _finish_stop_move_from_bar(self, index: int, position: int) -> None:
        stops = self._style["gradient"]["stops"]
        if index < 0 or index >= len(stops):
            return
        stop = stops[index]
        stop["position"] = max(0, min(100, int(position)))
        stops.sort(key=lambda value: value["position"])
        self._refresh_stop_list(stops.index(stop))

    def _load_selected_stop(self, row: int) -> None:
        if row < 0 or row >= len(self._style["gradient"]["stops"]):
            return
        stop = self._style["gradient"]["stops"][row]
        previous_sync = self._syncing
        self._syncing = True
        try:
            self.stop_position.setValue(stop["position"])
            self.stop_alpha.setValue(stop["alpha"])
            self.alpha_label.setText(f"{round(stop['alpha'] / 255 * 100)} %")
            colour = _as_colour(stop["color"])
            colour.setAlpha(stop["alpha"])
            self._set_selected_stop_colour(colour)
            self.gradient_picker.setCurrentColor(colour)
            self.gradient_preview.set_selected_stop(row)
        finally:
            self._syncing = previous_sync

    def _update_selected_stop(self, _value: int) -> None:
        if self._syncing:
            return
        row = self.stop_list.currentRow()
        if row < 0 or row >= len(self._style["gradient"]["stops"]):
            return
        stop = self._style["gradient"]["stops"][row]
        stop["position"] = self.stop_position.value()
        stop["alpha"] = self.stop_alpha.value()
        self.alpha_label.setText(f"{round(stop['alpha'] / 255 * 100)} %")
        self._style["gradient"]["stops"].sort(key=lambda value: value["position"])
        self._refresh_stop_list(self._style["gradient"]["stops"].index(stop))

    def _on_gradient_colour_changed(self, colour: QtGui.QColor) -> None:
        if self._syncing or not colour.isValid():
            return
        row = self.stop_list.currentRow()
        if row < 0:
            return
        stop = self._style["gradient"]["stops"][row]
        stop["color"] = _colour_name(colour)
        stop["alpha"] = colour.alpha()
        previous_sync = self._syncing
        self._syncing = True
        try:
            self.stop_alpha.setValue(colour.alpha())
            self.alpha_label.setText(f"{round(colour.alpha() / 255 * 100)} %")
            self._set_selected_stop_colour(colour)
        finally:
            self._syncing = previous_sync
        self._refresh_stop_list(row)

    def _set_selected_stop_colour(self, colour: QtGui.QColor) -> None:
        self.stop_colour_button.setText("")
        self.stop_colour_button.setStyleSheet(
            f"background-color: {colour.name(QtGui.QColor.NameFormat.HexArgb)}; "
            f"border: 1px solid {'rgba(255,255,255,70)' if self._is_dark_theme else 'rgba(0,0,0,55)'}; "
            "border-radius: 6px; padding: 0;"
        )
        self.selected_stop_hex_label.setText(colour.name(QtGui.QColor.NameFormat.HexRgb).upper())

    def _activate_gradient_colour_picker(self) -> None:
        self.gradient_picker.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)

    def _add_gradient_to_custom_colours(self) -> None:
        self._add_to_custom_colours(self.gradient_picker.currentColor())

    def _add_stop(self) -> None:
        self._add_stop_at(50)

    def _add_stop_at(self, position: int) -> None:
        stops = self._style["gradient"]["stops"]
        used_positions = {stop["position"] for stop in stops}
        position = max(0, min(100, int(position)))
        if position in used_positions:
            alternatives = (
                candidate
                for distance in range(1, 101)
                for candidate in (position + distance, position - distance)
                if 0 <= candidate <= 100
            )
            position = next((candidate for candidate in alternatives if candidate not in used_positions), position)
        if position in used_positions:
            return

        row = self.stop_list.currentRow()
        if 0 <= row < len(stops):
            previous = stops[row]
            colour = _as_colour(previous["color"])
            alpha = previous["alpha"]
        elif stops:
            previous = min(stops, key=lambda stop: abs(stop["position"] - position))
            colour = _as_colour(previous["color"])
            alpha = previous["alpha"]
        else:
            colour = QtGui.QColor("#ffffff")
            alpha = 255
        stop = {"position": position, "color": _colour_name(colour), "alpha": alpha}
        stops.append(stop)
        stops.sort(key=lambda value: value["position"])
        self._refresh_stop_list(stops.index(stop))

    def _remove_stop(self) -> None:
        stops = self._style["gradient"]["stops"]
        row = self.stop_list.currentRow()
        if len(stops) <= 2 or row < 0:
            return
        stops.pop(row)
        self._refresh_stop_list(max(0, row - 1))

    @staticmethod
    def _set_colour_button(button: QtWidgets.QPushButton, colour: QtGui.QColor) -> None:
        button.setText(_colour_name(colour).upper())
        text_colour = "#000" if colour.lightness() > 150 else "#fff"
        button.setStyleSheet(
            f"background-color: {_colour_name(colour)}; color: {text_colour}; border: 1px solid #777; padding: 4px;"
        )

    def fill_style(self) -> dict:
        """Return the final, serialisable text fill definition."""
        self._style["mode"] = "solid" if self.solid_button.isChecked() else "gradient"
        self._style["gradient"]["style"] = next(
            (key for key, button in self.gradient_style_buttons.items() if button.isChecked()),
            "linear_90",
        )
        self._style["gradient"]["stops"].sort(key=lambda value: value["position"])
        return deepcopy(self._style)

"""Contextual text-effects editor for the workspace right sidebar.

The colour dialog intentionally owns only solid and gradient fills.  Layer
styles, editable envelope deformation and the native 3D/perspective renderer
live here so they are available only while one or more text boxes are selected.
"""

from __future__ import annotations

from copy import deepcopy

from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.canvas.text_3d import normalise_text_3d
from app.ui.canvas.text_warp import normalise_text_warp
from app.ui.dayu_widgets import dayu_theme
from app.ui.text_fill_dialog import (
    LayerEffectsTextSample,
    Text3DSample,
    WarpTextSample,
)


def _colour_name(value, fallback: str) -> str:
    colour = value if isinstance(value, QtGui.QColor) else QtGui.QColor(value or fallback)
    if not colour.isValid():
        colour = QtGui.QColor(fallback)
    return colour.name(QtGui.QColor.NameFormat.HexArgb)


class _CompactToolButton(QtWidgets.QToolButton):
    """Tool button whose translated label may shrink inside a narrow sidebar."""

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802 - Qt API name
        hint = super().sizeHint()
        hint.setWidth(min(hint.width(), 128))
        return hint

    def minimumSizeHint(self) -> QtCore.QSize:  # noqa: N802 - Qt API name
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint


class _EffectPresetButton(_CompactToolButton):
    """Preset button with a reliable double-click gesture."""

    doubleClicked = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._suppress_double_click_release = False

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._suppress_double_click_release = True
            self.doubleClicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if (
            self._suppress_double_click_release
            and event.button() == QtCore.Qt.MouseButton.LeftButton
        ):
            self._suppress_double_click_release = False
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _EffectGalleryButton(_EffectPresetButton):
    """Large visual effect tile inspired by Canva's text-effect gallery."""

    def __init__(self, label: str, preview_kind: str, parent=None):
        super().__init__(parent)
        self._preview_kind = preview_kind
        self._is_dark_theme = True
        self._is_black_theme = False
        self.setText(label)
        self.setObjectName("effectsGalleryButton")
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(0)
        self.setFixedHeight(108)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )

    def apply_theme(self, is_dark: bool, is_black: bool = False) -> None:
        self._is_dark_theme = bool(is_dark)
        self._is_black_theme = bool(is_black)
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)

        tile = QtCore.QRectF(self.rect()).adjusted(2, 2, -2, -27)
        if self._is_black_theme:
            tile_bg = QtGui.QColor("#0A0A0A")
            border = QtGui.QColor("#2A2A2A")
            label_color = QtGui.QColor("#F5F5F5")
        elif self._is_dark_theme:
            tile_bg = QtGui.QColor("#111722")
            border = QtGui.QColor("#1D2430")
            label_color = QtGui.QColor("#F5F7FA")
        else:
            tile_bg = QtGui.QColor("#FFFFFF")
            border = QtGui.QColor("#D9DBE2")
            label_color = QtGui.QColor("#34353D")

        if self.isChecked():
            border = QtGui.QColor(dayu_theme.primary_color)
            border_width = 2.2
        elif self.underMouse():
            border = QtGui.QColor(dayu_theme.primary_5)
            border_width = 1.6
        else:
            border_width = 1.0

        painter.setPen(QtGui.QPen(border, border_width))
        painter.setBrush(tile_bg)
        painter.drawRoundedRect(tile, 10, 10)

        font = QtGui.QFont(self.font())
        font.setPixelSize(max(23, min(31, int(tile.width() * 0.36))))
        font.setWeight(QtGui.QFont.Weight.Bold)
        path = QtGui.QPainterPath()
        path.addText(QtCore.QPointF(0, 0), font, "Ag")
        bounds = path.boundingRect()
        path.translate(
            tile.center().x() - bounds.center().x(),
            tile.center().y() - bounds.center().y() + 2,
        )

        purple = QtGui.QColor("#833DFF")
        magenta = QtGui.QColor("#FF00D9")
        cyan = QtGui.QColor("#00BFEF")

        def shifted(dx: float, dy: float) -> QtGui.QPainterPath:
            result = QtGui.QPainterPath(path)
            result.translate(dx, dy)
            return result

        kind = self._preview_kind
        if kind == "parallel":
            shadow = QtGui.QColor(purple)
            shadow.setAlpha(95)
            painter.fillPath(shifted(5, 6), shadow)
            painter.fillPath(path, purple)
        elif kind == "glow":
            for width, alpha in ((13, 30), (8, 45), (4, 70)):
                glow = QtGui.QColor(purple)
                glow.setAlpha(alpha)
                painter.strokePath(path, QtGui.QPen(glow, width))
            painter.fillPath(path, purple)
        elif kind == "echo":
            for offset, alpha in ((8, 55), (5, 90), (2, 135)):
                echo = QtGui.QColor(purple)
                echo.setAlpha(alpha)
                painter.fillPath(shifted(offset, offset), echo)
            painter.fillPath(path, purple)
        elif kind == "outline":
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.strokePath(path, QtGui.QPen(purple, 2.3))
        elif kind == "background":
            background = QtGui.QColor("#CDAEFF")
            background.setAlpha(210)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(background)
            painter.drawRoundedRect(path.boundingRect().adjusted(-8, -6, 8, 6), 9, 9)
            painter.fillPath(path, purple)
        elif kind == "offset":
            painter.fillPath(shifted(4, 5), QtGui.QColor("#B292FF"))
            painter.strokePath(path, QtGui.QPen(purple, 2.0))
        elif kind == "hollow":
            painter.strokePath(path, QtGui.QPen(purple, 2.4))
        elif kind == "neon":
            for width, alpha in ((12, 35), (7, 70), (3, 125)):
                glow = QtGui.QColor(purple)
                glow.setAlpha(alpha)
                painter.strokePath(path, QtGui.QPen(glow, width))
            painter.strokePath(path, QtGui.QPen(purple, 2.0))
            painter.fillPath(path, QtGui.QColor("#F9F2FF"))
        else:
            painter.fillPath(shifted(-3, 0), cyan)
            painter.fillPath(shifted(3, 0), magenta)
            painter.fillPath(path, purple)

        label_rect = QtCore.QRectF(0, self.height() - 24, self.width(), 21)
        painter.setPen(label_color)
        label_font = QtGui.QFont(self.font())
        label_font.setPixelSize(11)
        painter.setFont(label_font)
        painter.drawText(
            label_rect,
            QtCore.Qt.AlignmentFlag.AlignCenter,
            self.text(),
        )
        painter.end()


class _CompactFrame(QtWidgets.QFrame):
    def minimumSizeHint(self) -> QtCore.QSize:  # noqa: N802 - Qt API name
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint


class _CompactGroupBox(QtWidgets.QGroupBox):
    def minimumSizeHint(self) -> QtCore.QSize:  # noqa: N802 - Qt API name
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint


class TextEffectsPanel(QtWidgets.QWidget):
    """Canva-like contextual editor backed by the existing native renderers."""

    backRequested = QtCore.Signal()
    effectChanged = QtCore.Signal(str, dict, str)

    _LAYER_DEFAULTS = {
        "glow": {
            "enabled": False,
            "color": "#ff00e5ff",
            "opacity": 85,
            "spread": 35,
            "size": 12,
        },
        "drop_shadow": {
            "enabled": False,
            "color": "#ff000000",
            "opacity": 55,
            "angle": 120,
            "distance": 8,
            "spread": 10,
            "size": 12,
        },
        "inner_glow": {
            "enabled": False,
            "color": "#ffffffff",
            "opacity": 65,
            "choke": 10,
            "size": 8,
        },
        "inner_shadow": {
            "enabled": False,
            "color": "#ff000000",
            "opacity": 45,
            "angle": 120,
            "distance": 4,
            "choke": 5,
            "size": 8,
        },
        "stroke": {
            "enabled": False,
            "color": "#ffffffff",
            "opacity": 100,
            "size": 3,
            "position": "outside",
        },
    }
    _LAYER_DEFINITIONS = (
        ("glow", "Outer glow", (
            ("opacity", "Opacity", 0, 100, " %"),
            ("spread", "Spread", 0, 100, " %"),
            ("size", "Size", 1, 80, " px"),
        )),
        ("drop_shadow", "Drop shadow", (
            ("opacity", "Opacity", 0, 100, " %"),
            ("angle", "Angle", 0, 360, "°"),
            ("distance", "Distance", 0, 80, " px"),
            ("spread", "Spread", 0, 100, " %"),
            ("size", "Size", 0, 80, " px"),
        )),
        ("inner_glow", "Inner glow", (
            ("opacity", "Opacity", 0, 100, " %"),
            ("choke", "Choke", 0, 100, " %"),
            ("size", "Size", 1, 60, " px"),
        )),
        ("inner_shadow", "Inner shadow", (
            ("opacity", "Opacity", 0, 100, " %"),
            ("angle", "Angle", 0, 360, "°"),
            ("distance", "Distance", 0, 40, " px"),
            ("choke", "Choke", 0, 100, " %"),
            ("size", "Size", 0, 60, " px"),
        )),
        ("stroke", "Stroke", (
            ("opacity", "Opacity", 0, 100, " %"),
            ("size", "Size", 1, 40, " px"),
        )),
    )
    _WARP_PRESETS = (
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
    _THREE_D_PRESETS = (
        ("extrude", "Extrusion"),
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("textEffectsPanel")
        self._style = self._normalise_style({})
        self._syncing = False
        self._last_emitted: dict[str, dict] = {}
        self._pending_commit: tuple[str, str] | None = None
        self._commit_timer = QtCore.QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(280)
        self._commit_timer.timeout.connect(self._flush_pending_commit)
        self._build_ui()
        self.set_style(self._style)

    @classmethod
    def _normalise_style(cls, style: dict | None) -> dict:
        result = deepcopy(style or {})
        for key, defaults in cls._LAYER_DEFAULTS.items():
            incoming = result.get(key, {})
            incoming = incoming if isinstance(incoming, dict) else {}
            effect = deepcopy(defaults)
            effect.update(incoming)
            effect["enabled"] = bool(effect.get("enabled", False))
            effect["color"] = _colour_name(effect.get("color"), defaults["color"])
            result[key] = effect
        result["warp"] = normalise_text_warp(result.get("warp", {}))
        result["three_d"] = normalise_text_3d(result.get("three_d", {}))
        return result

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(10)

        header = QtWidgets.QHBoxLayout()
        self.back_button = QtWidgets.QToolButton(self)
        self.back_button.setObjectName("effectsBackButton")
        self.back_button.setText("‹")
        self.back_button.setFixedSize(32, 32)
        self.back_button.setToolTip(self.tr("Back"))
        self.back_button.clicked.connect(self.backRequested.emit)
        title = QtWidgets.QLabel(self.tr("Text effects"), self)
        title.setObjectName("effectsTitle")
        title.setMinimumWidth(0)
        title.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        self.reset_button = QtWidgets.QPushButton(self.tr("Reset"), self)
        self.reset_button.setObjectName("effectsResetButton")
        self.reset_button.setMinimumWidth(0)
        self.reset_button.setMaximumWidth(98)
        self.reset_button.clicked.connect(self._reset_all)
        header.addWidget(self.back_button)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.reset_button)
        root.addLayout(header)

        self.selection_label = QtWidgets.QLabel(
            self.tr("Select a text box to edit its effects."),
            self,
        )
        self.selection_label.setObjectName("effectsSelection")
        self.selection_label.setWordWrap(True)
        self.selection_label.setMinimumWidth(0)
        self.selection_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        root.addWidget(self.selection_label)

        tabs = QtWidgets.QHBoxLayout()
        tabs.setSpacing(6)
        self.category_group = QtWidgets.QButtonGroup(self)
        self.category_group.setExclusive(True)
        self.category_buttons: list[QtWidgets.QToolButton] = []
        for index, label in enumerate((
            self.tr("Style"),
            self.tr("Deform"),
            self.tr("3D"),
        )):
            button = _CompactToolButton(self)
            button.setObjectName("effectsCategoryButton")
            button.setText(label)
            button.setCheckable(True)
            button.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
            button.clicked.connect(
                lambda _checked=False, page_index=index: self.pages.setCurrentIndex(page_index)
            )
            self.category_group.addButton(button, index)
            self.category_buttons.append(button)
            tabs.addWidget(button)
        root.addLayout(tabs)

        self.pages = QtWidgets.QStackedWidget(self)
        self.pages.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self.pages.addWidget(self._scroll_page(self._build_layer_page()))
        self.pages.addWidget(self._scroll_page(self._build_warp_page()))
        self.pages.addWidget(self._scroll_page(self._build_three_d_page()))
        root.addWidget(self.pages, 1)
        self.category_buttons[0].setChecked(True)

        self.apply_theme(True)

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark_theme = bool(is_dark)
        is_black = bool(is_dark) and dayu_theme.background_color.lower() == "#000000"
        if is_dark:
            panel_bg = "#000000" if is_black else "#0B0F19"
            selection_fg = "#B8B8B8" if is_black else "#AAB4C1"
            selection_bg = "#0A0A0A" if is_black else "#111722"
            border = "#262626" if is_black else "#1D2430"
            subtle_border = "#262626" if is_black else "#1D2430"
            back_hover = "#242424" if is_black else "#1A314F"
            category_hover = "#171717" if is_black else "#141A25"
            selected_bg = "#FFFFFF" if is_black else "#1462A9"
            selected_fg = "#000000" if is_black else "#F5F7FA"
            card_bg = "#0A0A0A" if is_black else "#111722"
            preset_bg = "#111111" if is_black else "#161C27"
            preset_border = "#262626" if is_black else "#1D2430"
            preset_hover = "#242424" if is_black else "#1A314F"
            section_fg = "#FFFFFF" if is_black else "#F5F7FA"
            value_fg = "#B8B8B8" if is_black else "#AAB4C1"
            colour_border = "rgba(255,255,255,70)"
            accent = "#FFFFFF" if is_black else "#168FF7"
            accent_hover = "#D8D8D8" if is_black else "#005DF5"
        else:
            panel_bg = "#ffffff"
            selection_fg = "#5f606a"
            selection_bg = "#ffffff"
            border = "#cfd1d8"
            subtle_border = "#d9dbe2"
            back_hover = "#eceef2"
            category_hover = "#f2f3f6"
            selected_bg = "#f9dfe6"
            selected_fg = "#7d2139"
            card_bg = "#ffffff"
            preset_bg = "#f7f7f9"
            preset_border = "#d7d9e0"
            preset_hover = "#fff0f4"
            section_fg = "#4f5059"
            value_fg = "#6d6e77"
            colour_border = "rgba(0,0,0,55)"
            accent = "#D13655"
            accent_hover = "#b54a65"
        indicator_border = "#606060" if is_black else ("#4C5D70" if is_dark else "#111111")
        indicator_bg = "#111111" if is_black else ("#161C27" if is_dark else "#ffffff")
        check_icon = str(dayu_theme.icon_check).replace("\\", "/")

        self.setStyleSheet(f"""
            QWidget#textEffectsPanel {{ background: {panel_bg}; }}
            QWidget#effectsPage {{ background: {panel_bg}; }}
            QWidget#textEffectsPanel QLabel {{
                background: transparent;
                border: none;
            }}
            QLabel#effectsTitle {{
                background: transparent; border: none;
                font-size: 16px; font-weight: 700;
            }}
            QLabel#effectsSelection {{
                color: {selection_fg}; background: {selection_bg};
                border: 1px solid {subtle_border};
                border-radius: 7px; padding: 7px 9px;
            }}
            QToolButton#effectsBackButton {{
                border: none; border-radius: 7px; font-size: 25px; min-width: 32px;
                min-height: 30px; padding: 0;
            }}
            QToolButton#effectsBackButton:hover {{ background: {back_hover}; }}
            QPushButton#effectsResetButton {{
                background: transparent; border: 1px solid {border};
                border-radius: 7px; padding: 5px 10px;
            }}
            QPushButton#effectsResetButton:hover {{
                border-color: {accent}; color: {accent};
            }}
            QToolButton#effectsCategoryButton {{
                background: transparent; border: 1px solid {border};
                border-radius: 8px; padding: 7px 5px;
                font-weight: 600;
            }}
            QToolButton#effectsCategoryButton:hover {{ background: {category_hover}; }}
            QToolButton#effectsCategoryButton:checked {{
                background: {selected_bg}; border: 2px solid {accent};
                color: {selected_fg};
            }}
            QFrame#effectsCard {{
                background: {card_bg}; border: 1px solid {subtle_border};
                border-radius: 9px;
            }}
            QGroupBox#effectsGroup {{
                background: {card_bg}; border: 1px solid {subtle_border};
                border-radius: 9px;
                margin-top: 12px; padding-top: 7px; font-weight: 600;
            }}
            QGroupBox#effectsGroup::title {{
                subcontrol-origin: margin; left: 11px; padding: 0 5px;
            }}
            QGroupBox#effectsGroup::indicator {{ width: 16px; height: 16px; }}
            QCheckBox::indicator,
            QGroupBox#effectsGroup::indicator {{
                width: 15px; height: 15px; border-radius: 3px;
                border: 1px solid {indicator_border};
                background: {indicator_bg};
            }}
            QCheckBox::indicator:hover,
            QGroupBox#effectsGroup::indicator:hover {{
                border: 1px solid {accent};
            }}
            QCheckBox::indicator:checked,
            QGroupBox#effectsGroup::indicator:checked {{
                border: 1px solid {indicator_border};
                background: {accent};
                image: url({check_icon});
            }}
            QToolButton#effectsPreset {{
                background: {preset_bg}; border: 1px solid {preset_border};
                border-radius: 8px;
                padding: 8px 5px; min-height: 27px;
            }}
            QToolButton#effectsPreset:hover {{
                border-color: {accent_hover}; background: {preset_hover};
            }}
            QToolButton#effectsPreset:checked {{
                background: {selected_bg}; border: 2px solid {accent};
                color: {selected_fg};
            }}
            QLabel#effectsSectionTitle {{
                background: transparent; border: none;
                font-size: 12px; font-weight: 700; color: {section_fg};
            }}
            QLabel#effectsValue {{ color: {value_fg}; }}
            QPushButton#effectsColour {{
                border: 1px solid {colour_border}; border-radius: 7px;
                min-height: 25px; padding: 2px 7px;
            }}
        """)
        for preview in (
            getattr(self, "layer_preview", None),
            getattr(self, "warp_preview", None),
            getattr(self, "three_d_preview", None),
        ):
            if preview is not None and hasattr(preview, "apply_theme"):
                preview.apply_theme(is_dark)
        for button in getattr(self, "layer_gallery_buttons", {}).values():
            if hasattr(button, "apply_theme"):
                button.apply_theme(is_dark, is_black)

    @staticmethod
    def _scroll_page(content: QtWidgets.QWidget) -> QtWidgets.QScrollArea:
        content.setObjectName("effectsPage")
        scroll = QtWidgets.QScrollArea()
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; } "
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        scroll.setWidget(content)
        return scroll

    def _section_label(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setObjectName("effectsSectionTitle")
        return label

    def _build_layer_gallery_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 2, 0, 4)
        layout.setSpacing(10)

        self.layer_preview = LayerEffectsTextSample(page)
        self.layer_preview.hide()

        gallery = QtWidgets.QGridLayout()
        gallery.setContentsMargins(0, 0, 0, 0)
        gallery.setHorizontalSpacing(6)
        gallery.setVerticalSpacing(7)
        self.layer_gallery_group = QtWidgets.QButtonGroup(self)
        self.layer_gallery_group.setExclusive(True)
        self.layer_gallery_buttons: dict[str, _EffectGalleryButton] = {}
        self._layer_gallery_specs: dict[str, tuple[str, dict]] = {}
        gallery_specs = (
            ("parallel", self.tr("Parallel"), "parallel", "drop_shadow", {
                "enabled": True, "color": "#99000000", "opacity": 62,
                "angle": 0, "distance": 8, "spread": 0, "size": 2,
            }),
            ("glow", self.tr("Glow"), "glow", "glow", {
                "enabled": True, "color": "#ff833dff", "opacity": 86,
                "spread": 35, "size": 14,
            }),
            ("echo", self.tr("Echo"), "echo", "inner_shadow", {
                "enabled": True, "color": "#aa833dff", "opacity": 62,
                "angle": 135, "distance": 5, "choke": 8, "size": 3,
            }),
            ("outline", self.tr("Outline"), "outline", "stroke", {
                "enabled": True, "color": "#ff833dff", "opacity": 100,
                "size": 3, "position": "outside",
            }),
            ("background", self.tr("Background"), "background", "inner_glow", {
                "enabled": True, "color": "#ffb88cff", "opacity": 82,
                "choke": 75, "size": 16,
            }),
            ("offset", self.tr("Offset"), "offset", "drop_shadow", {
                "enabled": True, "color": "#ff9d78ff", "opacity": 100,
                "angle": 135, "distance": 6, "spread": 0, "size": 0,
            }),
            ("hollow", self.tr("Hollow"), "hollow", "stroke", {
                "enabled": True, "color": "#ff833dff", "opacity": 100,
                "size": 4, "position": "inside",
            }),
            ("neon", self.tr("Neon"), "neon", "glow", {
                "enabled": True, "color": "#ff8a3dff", "opacity": 96,
                "spread": 48, "size": 20,
            }),
            ("distortion", self.tr("Distortion"), "distortion", "warp", {
                "enabled": True, "style": "twist", "bend": 38,
                "horizontal": 12, "vertical": -8,
            }),
        )
        for index, (card_key, label, preview_kind, effect_key, values) in enumerate(gallery_specs):
            button = _EffectGalleryButton(label, preview_kind, page)
            button.clicked.connect(
                lambda _checked=False, gallery_key=card_key:
                    self._select_layer_gallery(gallery_key)
            )
            button.doubleClicked.connect(
                lambda gallery_key=card_key:
                    self._disable_layer_gallery(gallery_key)
            )
            self.layer_gallery_group.addButton(button, index)
            self.layer_gallery_buttons[card_key] = button
            self._layer_gallery_specs[card_key] = (effect_key, deepcopy(values))
            gallery.addWidget(button, index // 3, index % 3)
        for column in range(3):
            gallery.setColumnStretch(column, 1)
        layout.addLayout(gallery)

        self.layer_controls: dict[str, dict[str, QtWidgets.QWidget]] = {}
        self.layer_group_widgets: dict[str, QtWidgets.QGroupBox] = {}
        for effect_key, title, slider_defs in self._LAYER_DEFINITIONS:
            group = _CompactGroupBox(self.tr(title), page)
            group.setObjectName("effectsGroup")
            group.setCheckable(True)
            group_layout = QtWidgets.QGridLayout(group)
            group_layout.setContentsMargins(10, 12, 10, 10)
            group_layout.setHorizontalSpacing(7)
            group_layout.setVerticalSpacing(7)
            controls: dict[str, QtWidgets.QWidget] = {"enabled": group}

            colour_button = QtWidgets.QPushButton(group)
            colour_button.setObjectName("effectsColour")
            colour_button.setMinimumWidth(0)
            colour_button.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
            colour_button.clicked.connect(
                lambda _checked=False, key=effect_key: self._choose_effect_colour(key)
            )
            controls["color"] = colour_button
            group_layout.addWidget(QtWidgets.QLabel(self.tr("Color")), 0, 0)
            group_layout.addWidget(colour_button, 0, 1, 1, 2)

            row = 1
            for field, label_text, minimum, maximum, suffix in slider_defs:
                slider, value_label = self._slider(
                    minimum,
                    maximum,
                    suffix,
                    lambda value, key=effect_key, name=field: self._change_layer_value(
                        key, name, value
                    ),
                    lambda key=effect_key: self._commit_effect(key, "change_text_layer_effect"),
                )
                controls[field] = slider
                controls[f"{field}_label"] = value_label
                group_layout.addWidget(QtWidgets.QLabel(self.tr(label_text)), row, 0)
                group_layout.addWidget(slider, row, 1)
                group_layout.addWidget(value_label, row, 2)
                row += 1

            if effect_key == "stroke":
                position = QtWidgets.QComboBox(group)
                position.addItem(self.tr("Outside"), "outside")
                position.addItem(self.tr("Center"), "center")
                position.addItem(self.tr("Inside"), "inside")
                position.currentIndexChanged.connect(
                    lambda _index, key=effect_key, combo=position: self._change_layer_position(
                        key, combo.currentData()
                    )
                )
                controls["position"] = position
                group_layout.addWidget(QtWidgets.QLabel(self.tr("Position")), row, 0)
                group_layout.addWidget(position, row, 1, 1, 2)

            group.toggled.connect(
                lambda checked, key=effect_key: self._toggle_effect(key, checked)
            )
            group_layout.setColumnStretch(1, 1)
            self.layer_controls[effect_key] = controls
            self.layer_group_widgets[effect_key] = group
            layout.addWidget(group)
            group.hide()
        layout.addStretch()
        return page

    def _build_layer_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 2, 0, 4)
        layout.setSpacing(10)

        self.layer_preview = LayerEffectsTextSample(page)
        self.layer_preview.setMinimumSize(200, 104)
        layout.addWidget(self.layer_preview)
        layout.addWidget(self._section_label(self.tr("Quick styles")))

        presets = QtWidgets.QHBoxLayout()
        presets.setContentsMargins(0, 0, 0, 0)
        presets.setSpacing(6)
        self.layer_preset_buttons: dict[str, _EffectPresetButton] = {}
        preset_specs = (
            (
                "glow",
                self.tr("Neon glow"),
                {
                    "enabled": True,
                    "color": "#ff168ff7",
                    "opacity": 92,
                    "spread": 40,
                    "size": 18,
                },
            ),
            (
                "drop_shadow",
                self.tr("Lift"),
                {
                    "enabled": True,
                    "color": "#99000000",
                    "opacity": 62,
                    "angle": 135,
                    "distance": 7,
                    "spread": 4,
                    "size": 8,
                },
            ),
            (
                "stroke",
                self.tr("Outline"),
                {
                    "enabled": True,
                    "color": "#ff000000",
                    "opacity": 100,
                    "size": 3,
                    "position": "outside",
                },
            ),
            (
                "inner_shadow",
                self.tr("Inset"),
                {
                    "enabled": True,
                    "color": "#99000000",
                    "opacity": 58,
                    "angle": 135,
                    "distance": 4,
                    "choke": 12,
                    "size": 5,
                },
            ),
        )
        for effect_key, label, values in preset_specs:
            button = _EffectPresetButton(page)
            button.setObjectName("effectsPreset")
            button.setText(label)
            button.setCheckable(True)
            button.setMinimumWidth(0)
            button.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
            button.clicked.connect(
                lambda _checked=False, key=effect_key, patch=deepcopy(values),
                target=button: self._apply_layer_preset(key, patch, target)
            )
            button.doubleClicked.connect(
                lambda key=effect_key, target=button:
                    self._disable_layer_preset(key, target)
            )
            self.layer_preset_buttons[effect_key] = button
            presets.addWidget(button, 1)
        layout.addLayout(presets)
        layout.addWidget(self._section_label(self.tr("Layer effects")))

        self.layer_controls: dict[str, dict[str, QtWidgets.QWidget]] = {}
        self.layer_group_widgets: dict[str, QtWidgets.QGroupBox] = {}
        for effect_key, title, slider_defs in self._LAYER_DEFINITIONS:
            group = _CompactGroupBox(self.tr(title), page)
            group.setObjectName("effectsGroup")
            group.setCheckable(True)
            group_layout = QtWidgets.QGridLayout(group)
            group_layout.setContentsMargins(10, 12, 10, 10)
            group_layout.setHorizontalSpacing(7)
            group_layout.setVerticalSpacing(7)
            controls: dict[str, QtWidgets.QWidget] = {"enabled": group}

            colour_button = QtWidgets.QPushButton(group)
            colour_button.setObjectName("effectsColour")
            colour_button.setMinimumWidth(0)
            colour_button.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
            colour_button.clicked.connect(
                lambda _checked=False, key=effect_key:
                    self._choose_effect_colour(key)
            )
            controls["color"] = colour_button
            group_layout.addWidget(QtWidgets.QLabel(self.tr("Color")), 0, 0)
            group_layout.addWidget(colour_button, 0, 1, 1, 2)

            row = 1
            for field, label_text, minimum, maximum, suffix in slider_defs:
                slider, value_label = self._slider(
                    minimum,
                    maximum,
                    suffix,
                    lambda value, key=effect_key, name=field:
                        self._change_layer_value(key, name, value),
                    lambda key=effect_key:
                        self._commit_effect(key, "change_text_layer_effect"),
                )
                controls[field] = slider
                controls[f"{field}_label"] = value_label
                group_layout.addWidget(QtWidgets.QLabel(self.tr(label_text)), row, 0)
                group_layout.addWidget(slider, row, 1)
                group_layout.addWidget(value_label, row, 2)
                row += 1

            if effect_key == "stroke":
                position = QtWidgets.QComboBox(group)
                position.addItem(self.tr("Outside"), "outside")
                position.addItem(self.tr("Center"), "center")
                position.addItem(self.tr("Inside"), "inside")
                position.currentIndexChanged.connect(
                    lambda _index, key=effect_key, combo=position:
                        self._change_layer_position(key, combo.currentData())
                )
                controls["position"] = position
                group_layout.addWidget(QtWidgets.QLabel(self.tr("Position")), row, 0)
                group_layout.addWidget(position, row, 1, 1, 2)

            group.toggled.connect(
                lambda checked, key=effect_key:
                    self._toggle_effect(key, checked)
            )
            group_layout.setColumnStretch(1, 1)
            self.layer_controls[effect_key] = controls
            self.layer_group_widgets[effect_key] = group
            layout.addWidget(group)
        layout.addStretch()
        return page

    def _build_warp_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 2, 0, 4)
        layout.setSpacing(10)

        self.warp_preview = WarpTextSample(page)
        self.warp_preview.setMinimumSize(200, 112)
        layout.addWidget(self.warp_preview)
        self.warp_enabled = QtWidgets.QCheckBox(self.tr("Enable deformation"), page)
        self.warp_enabled.setMinimumWidth(0)
        self.warp_enabled.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.warp_enabled.toggled.connect(self._toggle_warp)
        layout.addWidget(self.warp_enabled)
        layout.addWidget(self._section_label(self.tr("Shape")))

        preset_grid = QtWidgets.QGridLayout()
        preset_grid.setSpacing(6)
        self.warp_preset_group = QtWidgets.QButtonGroup(self)
        self.warp_preset_group.setExclusive(True)
        self.warp_preset_buttons: dict[str, QtWidgets.QToolButton] = {}
        for index, (key, label) in enumerate(self._WARP_PRESETS):
            button = _EffectPresetButton(page)
            button.setObjectName("effectsPreset")
            button.setText(self.tr(label))
            button.setCheckable(True)
            button.setMinimumWidth(0)
            button.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
            button.clicked.connect(
                lambda _checked=False, style_key=key: self._select_warp_preset(style_key)
            )
            button.doubleClicked.connect(
                lambda style_key=key: self._disable_warp_preset(style_key)
            )
            self.warp_preset_group.addButton(button)
            self.warp_preset_buttons[key] = button
            preset_grid.addWidget(button, index // 2, index % 2)
        preset_grid.setColumnStretch(0, 1)
        preset_grid.setColumnStretch(1, 1)
        layout.addLayout(preset_grid)

        controls = _CompactFrame(page)
        controls.setObjectName("effectsCard")
        controls_layout = QtWidgets.QGridLayout(controls)
        controls_layout.setContentsMargins(10, 10, 10, 10)
        controls_layout.setVerticalSpacing(8)
        self.warp_sliders: dict[str, QtWidgets.QSlider] = {}
        for row, (field, label, minimum, maximum) in enumerate((
            ("bend", self.tr("Bend"), -100, 100),
            ("horizontal", self.tr("Horizontal"), -100, 100),
            ("vertical", self.tr("Vertical"), -100, 100),
        )):
            slider, value_label = self._slider(
                minimum,
                maximum,
                " %",
                lambda value, name=field: self._change_warp_value(name, value),
                lambda: self._commit_effect("warp", "change_text_deformation"),
            )
            self.warp_sliders[field] = slider
            controls_layout.addWidget(QtWidgets.QLabel(label), row, 0)
            controls_layout.addWidget(slider, row, 1)
            controls_layout.addWidget(value_label, row, 2)

        self.warp_orientation = QtWidgets.QComboBox(controls)
        self.warp_orientation.addItem(self.tr("Horizontal"), "horizontal")
        self.warp_orientation.addItem(self.tr("Vertical"), "vertical")
        self.warp_orientation.currentIndexChanged.connect(self._change_warp_orientation)
        controls_layout.addWidget(QtWidgets.QLabel(self.tr("Orientation")), 3, 0)
        controls_layout.addWidget(self.warp_orientation, 3, 1, 1, 2)
        controls_layout.setColumnStretch(1, 1)
        layout.addWidget(controls)
        layout.addStretch()
        return page

    def _build_three_d_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 2, 0, 4)
        layout.setSpacing(10)

        self.three_d_preview = Text3DSample(page)
        self.three_d_preview.setMinimumSize(200, 125)
        layout.addWidget(self.three_d_preview)
        self.three_d_enabled = QtWidgets.QCheckBox(self.tr("Enable 3D and perspective"), page)
        self.three_d_enabled.setMinimumWidth(0)
        self.three_d_enabled.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.three_d_enabled.toggled.connect(self._toggle_three_d)
        layout.addWidget(self.three_d_enabled)
        layout.addWidget(self._section_label(self.tr("3D style")))

        preset_grid = QtWidgets.QGridLayout()
        preset_grid.setSpacing(6)
        self.three_d_preset_group = QtWidgets.QButtonGroup(self)
        self.three_d_preset_group.setExclusive(True)
        self.three_d_preset_buttons: dict[str, QtWidgets.QToolButton] = {}
        for index, (key, label) in enumerate(self._THREE_D_PRESETS):
            button = _EffectPresetButton(page)
            button.setObjectName("effectsPreset")
            button.setText(self.tr(label))
            button.setCheckable(True)
            button.setMinimumWidth(0)
            button.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
            button.clicked.connect(
                lambda _checked=False, style_key=key: self._select_three_d_preset(style_key)
            )
            button.doubleClicked.connect(
                lambda style_key=key: self._disable_three_d_preset(style_key)
            )
            self.three_d_preset_group.addButton(button)
            self.three_d_preset_buttons[key] = button
            preset_grid.addWidget(button, index // 2, index % 2)
        preset_grid.setColumnStretch(0, 1)
        preset_grid.setColumnStretch(1, 1)
        layout.addLayout(preset_grid)

        controls = _CompactFrame(page)
        controls.setObjectName("effectsCard")
        controls_layout = QtWidgets.QGridLayout(controls)
        controls_layout.setContentsMargins(10, 10, 10, 10)
        controls_layout.setVerticalSpacing(8)
        self.three_d_sliders: dict[str, QtWidgets.QSlider] = {}
        definitions = (
            ("strength", self.tr("Intensity"), 0, 100, " %"),
            ("depth", self.tr("Depth"), 1, 80, " px"),
            ("angle", self.tr("Angle"), 0, 359, "°"),
            ("bevel", self.tr("Bevel"), 0, 100, " %"),
        )
        for row, (field, label, minimum, maximum, suffix) in enumerate(definitions):
            slider, value_label = self._slider(
                minimum,
                maximum,
                suffix,
                lambda value, name=field: self._change_three_d_value(name, value),
                lambda: self._commit_effect("three_d", "change_text_3d"),
            )
            self.three_d_sliders[field] = slider
            controls_layout.addWidget(QtWidgets.QLabel(label), row, 0)
            controls_layout.addWidget(slider, row, 1)
            controls_layout.addWidget(value_label, row, 2)

        self.three_d_extrude = QtWidgets.QCheckBox(self.tr("Extrusion"), controls)
        self.three_d_extrude.setMinimumWidth(0)
        self.three_d_extrude.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.three_d_extrude.toggled.connect(self._change_three_d_extrusion)
        controls_layout.addWidget(self.three_d_extrude, 4, 0, 1, 3)
        self.three_d_colour = QtWidgets.QPushButton(controls)
        self.three_d_colour.setObjectName("effectsColour")
        self.three_d_colour.setMinimumWidth(0)
        self.three_d_colour.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.three_d_colour.clicked.connect(self._choose_three_d_colour)
        controls_layout.addWidget(QtWidgets.QLabel(self.tr("Color")), 5, 0)
        controls_layout.addWidget(self.three_d_colour, 5, 1, 1, 2)
        controls_layout.setColumnStretch(1, 1)
        layout.addWidget(controls)
        layout.addStretch()
        return page

    def _slider(
        self,
        minimum: int,
        maximum: int,
        suffix: str,
        changed,
        committed,
    ) -> tuple[QtWidgets.QSlider, QtWidgets.QLabel]:
        slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        label = QtWidgets.QLabel()
        label.setObjectName("effectsValue")
        label.setFixedWidth(48)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        slider.valueChanged.connect(
            lambda value, target=label, unit=suffix: target.setText(f"{value}{unit}")
        )
        slider.valueChanged.connect(changed)
        slider.sliderReleased.connect(committed)
        return slider, label

    def set_selection(self, text: str, style: dict, count: int = 1) -> None:
        clean_text = " ".join((text or "").split())
        if len(clean_text) > 72:
            clean_text = clean_text[:69] + "…"
        if count > 1:
            self.selection_label.setText(
                self.tr("Selected text boxes: %1").replace("%1", str(count))
            )
        else:
            self.selection_label.setText(clean_text or self.tr("Selected text box"))
        self.set_style(style)

    def clear_selection(self) -> None:
        self.selection_label.setText(self.tr("Select a text box to edit its effects."))

    def set_style(self, style: dict | None) -> None:
        self._commit_timer.stop()
        self._pending_commit = None
        self._style = self._normalise_style(style)
        self._last_emitted = {
            key: deepcopy(self._style[key])
            for key in (*self._LAYER_DEFAULTS.keys(), "warp", "three_d")
        }
        self._syncing = True
        try:
            for effect_key, controls in self.layer_controls.items():
                effect = self._style[effect_key]
                controls["enabled"].setChecked(effect["enabled"])
                preset = self.layer_preset_buttons.get(effect_key)
                if preset is not None:
                    preset.setChecked(effect["enabled"])
                self._set_colour_button(controls["color"], effect["color"])
                for field, widget in controls.items():
                    if isinstance(widget, QtWidgets.QSlider) and field in effect:
                        widget.setValue(int(effect[field]))
                position = controls.get("position")
                if isinstance(position, QtWidgets.QComboBox):
                    position.setCurrentIndex(max(0, position.findData(effect.get("position"))))

            warp = self._style["warp"]
            self.warp_enabled.setChecked(warp["enabled"])
            self._set_exclusive_preset(
                self.warp_preset_group,
                self.warp_preset_buttons,
                warp["style"] if warp["enabled"] else None,
            )
            for field, slider in self.warp_sliders.items():
                slider.setValue(int(warp[field]))
            self.warp_orientation.setCurrentIndex(
                max(0, self.warp_orientation.findData(warp["orientation"]))
            )

            three_d = self._style["three_d"]
            self.three_d_enabled.setChecked(three_d["enabled"])
            self._set_exclusive_preset(
                self.three_d_preset_group,
                self.three_d_preset_buttons,
                three_d["style"] if three_d["enabled"] else None,
            )
            for field, slider in self.three_d_sliders.items():
                slider.setValue(int(three_d[field]))
            self.three_d_extrude.setChecked(three_d["extrude"])
            self._set_colour_button(self.three_d_colour, three_d["color"])
        finally:
            self._syncing = False
        self._refresh_previews()

    def _refresh_previews(self) -> None:
        self.layer_preview.set_style(self._style)
        self.warp_preview.set_warp(self._style["warp"])
        self.three_d_preview.set_effect(self._style["three_d"])

    def _apply_layer_preset(
        self,
        effect_key: str,
        patch: dict,
        button: QtWidgets.QToolButton | None = None,
    ) -> None:
        self._style[effect_key].update(deepcopy(patch))
        if button is not None:
            button.setChecked(True)
        self._sync_layer_controls(effect_key)
        self._refresh_previews()
        self._commit_effect(effect_key, "apply_text_effect_preset")

    def _select_layer_gallery(self, gallery_key: str) -> None:
        """Apply a visual preset and reveal only its relevant controls."""
        spec = self._layer_gallery_specs.get(gallery_key)
        if spec is None:
            return
        effect_key, patch = spec
        self._set_layer_gallery_selection(gallery_key)

        if effect_key == "warp":
            self._style["warp"].update(deepcopy(patch))
            self._syncing = True
            try:
                self.warp_enabled.setChecked(True)
                self._set_exclusive_preset(
                    self.warp_preset_group,
                    self.warp_preset_buttons,
                    self._style["warp"]["style"],
                )
                for field, slider in self.warp_sliders.items():
                    slider.setValue(int(self._style["warp"][field]))
                self.category_buttons[1].setChecked(True)
                self.pages.setCurrentIndex(1)
            finally:
                self._syncing = False
            self._refresh_previews()
            self._commit_effect("warp", "apply_text_effect_preset")
            return

        self._style[effect_key].update(deepcopy(patch))
        self._show_layer_controls(effect_key)
        self._sync_layer_controls(effect_key)
        self._refresh_previews()
        self._commit_effect(effect_key, "apply_text_effect_preset")

    def _disable_layer_gallery(self, gallery_key: str) -> None:
        """Double-clicking the selected tile removes that effect."""
        spec = self._layer_gallery_specs.get(gallery_key)
        if spec is None:
            return
        effect_key, _patch = spec
        if effect_key == "warp":
            self._style["warp"]["enabled"] = False
            self._syncing = True
            try:
                self.warp_enabled.setChecked(False)
                self._set_exclusive_preset(
                    self.warp_preset_group,
                    self.warp_preset_buttons,
                    None,
                )
            finally:
                self._syncing = False
            self._commit_effect("warp", "toggle_text_deformation")
        else:
            self._style[effect_key]["enabled"] = False
            self._sync_layer_controls(effect_key)
            self._commit_effect(effect_key, "toggle_text_layer_effect")
        self._set_layer_gallery_selection(None)
        self._show_layer_controls(None)
        self._refresh_previews()

    def _set_layer_gallery_selection(self, active_key: str | None) -> None:
        self.layer_gallery_group.setExclusive(False)
        try:
            for key, button in self.layer_gallery_buttons.items():
                with QtCore.QSignalBlocker(button):
                    button.setChecked(key == active_key)
        finally:
            self.layer_gallery_group.setExclusive(True)

    def _show_layer_controls(self, effect_key: str | None) -> None:
        for key, group in self.layer_group_widgets.items():
            group.setVisible(key == effect_key)

    def _sync_layer_gallery_from_style(self) -> None:
        active_key = None
        for gallery_key, (effect_key, _patch) in self._layer_gallery_specs.items():
            effect = self._style.get(effect_key, {})
            if isinstance(effect, dict) and effect.get("enabled"):
                active_key = gallery_key
                break
        self._set_layer_gallery_selection(active_key)
        effect_key = (
            self._layer_gallery_specs[active_key][0]
            if active_key is not None
            else None
        )
        self._show_layer_controls(
            effect_key if effect_key in self.layer_group_widgets else None
        )

    def _disable_layer_preset(
        self,
        effect_key: str,
        button: QtWidgets.QToolButton,
    ) -> None:
        """A double click removes the preset without hunting for its check box."""
        self._style[effect_key]["enabled"] = False
        button.setChecked(False)
        self._sync_layer_controls(effect_key)
        self._refresh_previews()
        self._commit_effect(effect_key, "toggle_text_layer_effect")

    def _sync_layer_controls(self, effect_key: str) -> None:
        controls = self.layer_controls[effect_key]
        effect = self._style[effect_key]
        self._syncing = True
        try:
            controls["enabled"].setChecked(effect["enabled"])
            self._set_colour_button(controls["color"], effect["color"])
            for field, widget in controls.items():
                if isinstance(widget, QtWidgets.QSlider) and field in effect:
                    widget.setValue(int(effect[field]))
            position = controls.get("position")
            if isinstance(position, QtWidgets.QComboBox):
                position.setCurrentIndex(max(0, position.findData(effect.get("position"))))
        finally:
            self._syncing = False

    def _toggle_effect(self, effect_key: str, checked: bool) -> None:
        if self._syncing:
            return
        self._style[effect_key]["enabled"] = checked
        preset = self.layer_preset_buttons.get(effect_key)
        if preset is not None and preset.isChecked() != checked:
            with QtCore.QSignalBlocker(preset):
                preset.setChecked(checked)
        self._refresh_previews()
        self._commit_effect(effect_key, "toggle_text_layer_effect")

    def _change_layer_value(self, effect_key: str, field: str, value: int) -> None:
        if self._syncing:
            return
        self._style[effect_key][field] = value
        self._refresh_previews()
        self._queue_commit(effect_key, "change_text_layer_effect")

    def _change_layer_position(self, effect_key: str, position: str) -> None:
        if self._syncing or not position:
            return
        self._style[effect_key]["position"] = position
        self._refresh_previews()
        self._commit_effect(effect_key, "change_text_layer_effect")

    def _choose_effect_colour(self, effect_key: str) -> None:
        current = QtGui.QColor(self._style[effect_key]["color"])
        colour = QtWidgets.QColorDialog.getColor(
            current,
            self,
            self.tr("Effect color"),
            QtWidgets.QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if not colour.isValid():
            return
        self._style[effect_key]["color"] = colour.name(QtGui.QColor.NameFormat.HexArgb)
        self._set_colour_button(self.layer_controls[effect_key]["color"], colour)
        self._refresh_previews()
        self._commit_effect(effect_key, "change_text_effect_color")

    def _toggle_warp(self, checked: bool) -> None:
        if self._syncing:
            return
        self._style["warp"]["enabled"] = checked
        self._set_exclusive_preset(
            self.warp_preset_group,
            self.warp_preset_buttons,
            self._style["warp"]["style"] if checked else None,
        )
        self._refresh_previews()
        self._commit_effect("warp", "toggle_text_deformation")

    def _select_warp_preset(self, style_key: str) -> None:
        self._style["warp"]["enabled"] = True
        self._style["warp"]["style"] = style_key
        self._syncing = True
        try:
            self.warp_enabled.setChecked(True)
        finally:
            self._syncing = False
        self._refresh_previews()
        self._commit_effect("warp", "change_text_deformation")

    def _disable_warp_preset(self, style_key: str) -> None:
        if self._style["warp"]["style"] != style_key:
            return
        self._style["warp"]["enabled"] = False
        self._syncing = True
        try:
            self.warp_enabled.setChecked(False)
            self._set_exclusive_preset(
                self.warp_preset_group,
                self.warp_preset_buttons,
                None,
            )
        finally:
            self._syncing = False
        self._refresh_previews()
        self._commit_effect("warp", "toggle_text_deformation")

    def _change_warp_value(self, field: str, value: int) -> None:
        if self._syncing:
            return
        self._style["warp"][field] = value
        self._refresh_previews()
        self._queue_commit("warp", "change_text_deformation")

    def _change_warp_orientation(self, _index: int) -> None:
        if self._syncing:
            return
        self._style["warp"]["orientation"] = self.warp_orientation.currentData()
        self._refresh_previews()
        self._commit_effect("warp", "change_text_deformation")

    def _toggle_three_d(self, checked: bool) -> None:
        if self._syncing:
            return
        self._style["three_d"]["enabled"] = checked
        self._set_exclusive_preset(
            self.three_d_preset_group,
            self.three_d_preset_buttons,
            self._style["three_d"]["style"] if checked else None,
        )
        self._refresh_previews()
        self._commit_effect("three_d", "toggle_text_3d")

    def _select_three_d_preset(self, style_key: str) -> None:
        self._style["three_d"]["enabled"] = True
        self._style["three_d"]["style"] = style_key
        if style_key == "extrude":
            self._style["three_d"]["extrude"] = True
        self._syncing = True
        try:
            self.three_d_enabled.setChecked(True)
            self.three_d_extrude.setChecked(self._style["three_d"]["extrude"])
        finally:
            self._syncing = False
        self._refresh_previews()
        self._commit_effect("three_d", "change_text_3d")

    def _disable_three_d_preset(self, style_key: str) -> None:
        if self._style["three_d"]["style"] != style_key:
            return
        self._style["three_d"]["enabled"] = False
        self._syncing = True
        try:
            self.three_d_enabled.setChecked(False)
            self._set_exclusive_preset(
                self.three_d_preset_group,
                self.three_d_preset_buttons,
                None,
            )
        finally:
            self._syncing = False
        self._refresh_previews()
        self._commit_effect("three_d", "toggle_text_3d")

    def _change_three_d_value(self, field: str, value: int) -> None:
        if self._syncing:
            return
        self._style["three_d"][field] = value
        self._refresh_previews()
        self._queue_commit("three_d", "change_text_3d")

    def _change_three_d_extrusion(self, checked: bool) -> None:
        if self._syncing:
            return
        self._style["three_d"]["extrude"] = checked
        self._refresh_previews()
        self._commit_effect("three_d", "change_text_3d")

    def _choose_three_d_colour(self) -> None:
        current = QtGui.QColor(self._style["three_d"]["color"])
        colour = QtWidgets.QColorDialog.getColor(
            current,
            self,
            self.tr("Extrusion color"),
            QtWidgets.QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if not colour.isValid():
            return
        self._style["three_d"]["color"] = colour.name(QtGui.QColor.NameFormat.HexArgb)
        self._set_colour_button(self.three_d_colour, colour)
        self._refresh_previews()
        self._commit_effect("three_d", "change_text_3d")

    def _queue_commit(self, effect_key: str, macro_name: str) -> None:
        self._pending_commit = (effect_key, macro_name)
        self._commit_timer.start()

    def _flush_pending_commit(self) -> None:
        if self._pending_commit is None:
            return
        effect_key, macro_name = self._pending_commit
        self._pending_commit = None
        self._commit_effect(effect_key, macro_name)

    def _commit_effect(self, effect_key: str, macro_name: str) -> None:
        self._commit_timer.stop()
        self._pending_commit = None
        value = deepcopy(self._style[effect_key])
        if value == self._last_emitted.get(effect_key):
            return
        self._last_emitted[effect_key] = deepcopy(value)
        self.effectChanged.emit(effect_key, value, macro_name)

    def _reset_all(self) -> None:
        for effect_key in self._LAYER_DEFAULTS:
            self._style[effect_key]["enabled"] = False
        self._style["warp"]["enabled"] = False
        self._style["three_d"]["enabled"] = False
        self.set_style(self._style)
        self.effectChanged.emit("__reset__", {}, "reset_text_effects")

    @staticmethod
    def _set_exclusive_preset(
        group: QtWidgets.QButtonGroup,
        buttons: dict[str, QtWidgets.QAbstractButton],
        active_key: str | None,
    ) -> None:
        """Allow an exclusive button group to represent 'no active effect'."""
        group.setExclusive(False)
        try:
            for key, button in buttons.items():
                button.setChecked(key == active_key)
        finally:
            group.setExclusive(True)

    @staticmethod
    def _set_colour_button(button: QtWidgets.QPushButton, value) -> None:
        colour = value if isinstance(value, QtGui.QColor) else QtGui.QColor(value)
        if not colour.isValid():
            colour = QtGui.QColor("#ffffff")
        text_colour = "#16161b" if colour.lightness() > 150 else "#ffffff"
        button.setText(
            f"{colour.name(QtGui.QColor.NameFormat.HexRgb).upper()}  "
            f"{round(colour.alphaF() * 100)}%"
        )
        button.setStyleSheet(
            f"background-color: {colour.name(QtGui.QColor.NameFormat.HexRgb)}; "
            f"color: {text_colour};"
        )

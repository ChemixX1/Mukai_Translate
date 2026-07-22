import copy
import math

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QIntValidator

from app.ui.dayu_widgets import dayu_theme
from app.ui.dayu_widgets.browser import MDragFileButton
from app.ui.dayu_widgets.button_group import MPushButtonGroup, MToolButtonGroup
from app.ui.dayu_widgets.check_box import MCheckBox
from app.ui.dayu_widgets.combo_box import MComboBox, MFontComboBox
from app.ui.dayu_widgets.divider import MDivider
from app.ui.dayu_widgets.line_edit import MLineEdit
from app.ui.dayu_widgets.loading import MLoading
from app.ui.dayu_widgets.progress_bar import MProgressBar
from app.ui.dayu_widgets.push_button import MPushButton
from app.ui.dayu_widgets.radio_button import MRadioButton
from app.ui.dayu_widgets.slider import MSlider
from app.ui.dayu_widgets.text_edit import MTextEdit
from app.ui.dayu_widgets.tool_button import MToolButton
from app.ui.search_replace_panel import SearchReplacePanel
from app.ui.text_effects_panel import TextEffectsPanel
from app.ui.music_player import MusicPlayerWidget
from app.ui.compact_color_picker import CompactColorPicker
from app.ui.main_window.constants import supported_source_languages, supported_target_languages


class _FontSizeComboBox(MComboBox):
    """Editable size field whose number remains directly typeable."""

    def eventFilter(self, widget, event):  # noqa: N802 - Qt API name
        if (
            widget is self.lineEdit()
            and event.type() == QtCore.QEvent.Type.MouseButtonPress
            and event.button() == QtCore.Qt.MouseButton.LeftButton
        ):
            self.lineEdit().setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
            QtCore.QTimer.singleShot(0, self.lineEdit().selectAll)
            return False
        if (
            widget is self.lineEdit()
            and event.type() == QtCore.QEvent.Type.MouseButtonRelease
            and event.button() == QtCore.Qt.MouseButton.LeftButton
        ):
            QtCore.QTimer.singleShot(0, self._show_choices_keep_editor)
            return True
        return super().eventFilter(widget, event)

    def _show_choices_keep_editor(self) -> None:
        self.showPopup()
        self.lineEdit().setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        self.lineEdit().selectAll()


class _ScrollBarProximityFilter(QtCore.QObject):
    """Expand the painted handle while the pointer is inside its slim hit area."""

    def eventFilter(self, widget, event):  # noqa: N802 - Qt API name
        if isinstance(widget, QtWidgets.QScrollBar):
            if event.type() == QtCore.QEvent.Type.Enter:
                self._set_expanded(widget, True)
            elif event.type() == QtCore.QEvent.Type.Leave:
                self._set_expanded(widget, False)
        return super().eventFilter(widget, event)

    @staticmethod
    def _set_expanded(scrollbar: QtWidgets.QScrollBar, expanded: bool) -> None:
        if scrollbar.property("expanded") == expanded:
            return
        scrollbar.setProperty("expanded", expanded)
        scrollbar.style().unpolish(scrollbar)
        scrollbar.style().polish(scrollbar)
        scrollbar.update()


class _GradientStylePreviewButton(QtWidgets.QToolButton):
    """Live, icon-only preview for one gradient direction."""

    def __init__(self, style_key: str, parent=None):
        super().__init__(parent)
        self.style_key = style_key
        self._stops: list[dict] = []
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(38, 38)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )

    def set_gradient_stops(self, stops: list[dict]) -> None:
        self._stops = copy.deepcopy(stops)
        self.update()

    def _gradient(self, rect: QtCore.QRectF) -> QtGui.QGradient:
        if self.style_key == "linear_180":
            gradient = QtGui.QLinearGradient(
                rect.center().x(), rect.top(), rect.center().x(), rect.bottom()
            )
        elif self.style_key == "linear_135":
            gradient = QtGui.QLinearGradient(rect.topLeft(), rect.bottomRight())
        elif self.style_key == "radial_center":
            gradient = QtGui.QRadialGradient(
                rect.center(), max(rect.width(), rect.height()) / 1.4
            )
        elif self.style_key == "radial_origin":
            gradient = QtGui.QRadialGradient(
                rect.topLeft(), max(rect.width(), rect.height())
            )
        else:
            gradient = QtGui.QLinearGradient(rect.topLeft(), rect.topRight())

        for stop in sorted(
            self._stops, key=lambda value: int(value.get("position", 0))
        ):
            colour = QColor(stop.get("color", "#ff000000"))
            if not colour.isValid():
                colour = QColor("#000000")
            colour.setAlpha(int(stop.get("alpha", colour.alpha())))
            position = max(0.0, min(1.0, float(stop.get("position", 0)) / 100.0))
            gradient.setColorAt(position, colour)
        return gradient

    def paintEvent(self, event):  # noqa: N802 - Qt API name
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        rect = QtCore.QRectF(self.rect()).adjusted(2.0, 2.0, -2.0, -2.0)
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, 6, 6)

        painter.save()
        painter.setClipPath(path)
        square = 6
        for y in range(int(rect.top()), int(rect.bottom()) + 1, square):
            for x in range(int(rect.left()), int(rect.right()) + 1, square):
                light = ((x // square) + (y // square)) % 2 == 0
                painter.fillRect(
                    x,
                    y,
                    square,
                    square,
                    QColor("#f0f0f0" if light else "#c8c8c8"),
                )
        if self._stops:
            painter.fillPath(path, QtGui.QBrush(self._gradient(rect)))
        painter.restore()

        if self.isChecked():
            border = QColor(dayu_theme.primary_color)
            width = 2.5
        elif self.underMouse():
            border = QColor(dayu_theme.primary_5)
            width = 1.7
        else:
            border = self.palette().color(QtGui.QPalette.ColorRole.Mid)
            width = 1.0
        painter.setPen(QtGui.QPen(border, width))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()


class _GradientStopRow(QtWidgets.QWidget):
    """Compact editable row: position, color, opacity and remove."""

    activated = QtCore.Signal()
    positionChanged = QtCore.Signal(int)
    colourChanged = QtCore.Signal(QColor)
    opacityChanged = QtCore.Signal(int)
    editingFinished = QtCore.Signal()
    removeRequested = QtCore.Signal()

    def __init__(self, stop: dict, parent=None):
        super().__init__(parent)
        self._syncing = False
        self.setObjectName("gradientStopRow")
        self.setProperty("selected", False)
        self.setFixedHeight(36)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(3, 2, 3, 2)
        layout.setSpacing(4)

        self.position = QtWidgets.QSpinBox(self)
        self.position.setObjectName("gradientStopField")
        self.position.setRange(0, 100)
        self.position.setSuffix("%")
        self.position.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.position.setButtonSymbols(
            QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons
        )
        self.position.setFixedWidth(48)
        self.position.setToolTip(self.tr("Position"))
        layout.addWidget(self.position)

        colour_field = QtWidgets.QFrame(self)
        colour_field.setObjectName("gradientStopColourField")
        colour_layout = QtWidgets.QHBoxLayout(colour_field)
        colour_layout.setContentsMargins(4, 2, 4, 2)
        colour_layout.setSpacing(4)
        self.swatch = QtWidgets.QPushButton(colour_field)
        self.swatch.setObjectName("gradientStopSwatch")
        self.swatch.setFixedSize(18, 18)
        self.swatch.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.hex_edit = QtWidgets.QLineEdit(colour_field)
        self.hex_edit.setObjectName("gradientStopHex")
        self.hex_edit.setMaxLength(7)
        self.hex_edit.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.hex_edit.setToolTip(self.tr("Color"))
        colour_layout.addWidget(self.swatch)
        colour_layout.addWidget(self.hex_edit, 1)
        layout.addWidget(colour_field, 1)

        self.opacity = QtWidgets.QSpinBox(self)
        self.opacity.setObjectName("gradientStopField")
        self.opacity.setRange(0, 100)
        self.opacity.setSuffix("%")
        self.opacity.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.opacity.setButtonSymbols(
            QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons
        )
        self.opacity.setFixedWidth(50)
        self.opacity.setToolTip(self.tr("Opacity"))
        layout.addWidget(self.opacity)

        self.remove_button = QtWidgets.QToolButton(self)
        self.remove_button.setObjectName("gradientStopRemove")
        self.remove_button.setText("−")
        self.remove_button.setFixedSize(24, 28)
        self.remove_button.setToolTip(self.tr("Remove stop"))
        layout.addWidget(self.remove_button)

        for widget in (
            self,
            self.position,
            colour_field,
            self.swatch,
            self.hex_edit,
            self.opacity,
        ):
            widget.installEventFilter(self)

        self.position.valueChanged.connect(self._position_changed)
        self.hex_edit.textEdited.connect(self._colour_edited)
        self.opacity.valueChanged.connect(self._opacity_changed)
        self.position.editingFinished.connect(self.editingFinished)
        self.hex_edit.editingFinished.connect(self._finish_colour_edit)
        self.opacity.editingFinished.connect(self.editingFinished)
        self.swatch.clicked.connect(self.activated)
        self.remove_button.clicked.connect(self.removeRequested)
        self.set_stop(stop)

    def eventFilter(self, watched, event):  # noqa: N802 - Qt API name
        if event.type() in (
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QEvent.Type.FocusIn,
        ):
            self.activated.emit()
        return super().eventFilter(watched, event)

    def set_stop(self, stop: dict) -> None:
        colour = QColor(stop.get("color", "#ff000000"))
        if not colour.isValid():
            colour = QColor("#000000")
        colour.setAlpha(int(stop.get("alpha", colour.alpha())))
        self._syncing = True
        try:
            self.position.setValue(int(stop.get("position", 0)))
            self.hex_edit.setText(colour.name(QColor.NameFormat.HexRgb).upper())
            self.opacity.setValue(round(colour.alphaF() * 100))
            self._update_swatch(colour)
        finally:
            self._syncing = False

    def set_selected(self, selected: bool) -> None:
        selected = bool(selected)
        if self.property("selected") == selected:
            return
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _update_swatch(self, colour: QColor) -> None:
        self.swatch.setStyleSheet(
            f"background: {colour.name(QColor.NameFormat.HexArgb)};"
            " border: 1px solid rgba(127,127,127,150); border-radius: 4px;"
        )

    def _position_changed(self, value: int) -> None:
        if not self._syncing:
            self.positionChanged.emit(int(value))

    def _opacity_changed(self, value: int) -> None:
        if not self._syncing:
            self.opacityChanged.emit(int(value))

    def _colour_edited(self, text: str) -> None:
        if self._syncing:
            return
        text = text.strip()
        if text and not text.startswith("#"):
            text = f"#{text}"
        colour = QColor(text)
        if colour.isValid():
            colour.setAlpha(round(self.opacity.value() * 2.55))
            self._update_swatch(colour)
            self.colourChanged.emit(colour)

    def _finish_colour_edit(self) -> None:
        colour = QColor(self.hex_edit.text().strip())
        if colour.isValid():
            self.hex_edit.setText(
                colour.name(QColor.NameFormat.HexRgb).upper()
            )
        self.editingFinished.emit()


class WorkspaceMixin:
    def _create_main_content(self):
        content_widget = QtWidgets.QWidget()

        header_layout = QtWidgets.QHBoxLayout()

        self.undo_tool_group = MToolButtonGroup(orientation=QtCore.Qt.Horizontal, exclusive=True)
        undo_tools = [
            {"svg": "undo.svg", "checkable": False, "tooltip": self.tr("Undo")},
            {"svg": "redo.svg", "checkable": False, "tooltip": self.tr("Redo")},
        ]
        self.undo_tool_group.set_button_list(undo_tools)

        button_config_list = [
            {"text": self.tr("Detect"), "dayu_type": MPushButton.DefaultType, "enabled": False},
            {"text": self.tr("Recognize"), "dayu_type": MPushButton.DefaultType, "enabled": False},
            {"text": self.tr("Translate"), "dayu_type": MPushButton.DefaultType, "enabled": False},
            {"text": self.tr("Segment"), "dayu_type": MPushButton.DefaultType, "enabled": False},
            {"text": self.tr("Clean"), "dayu_type": MPushButton.DefaultType, "enabled": False},
            {"text": self.tr("Render"), "dayu_type": MPushButton.DefaultType, "enabled": False},
        ]

        self.hbutton_group = MPushButtonGroup()
        self.hbutton_group.set_dayu_size(dayu_theme.small)
        self.hbutton_group.set_button_list(button_config_list)
        self.hbutton_group.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        for button in self.hbutton_group.get_button_group().buttons():
            button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

        self.progress_bar = MProgressBar().auto_color()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)

        self.loading = MLoading().small()
        self.loading.setVisible(False)

        self.manual_radio = MRadioButton(self.tr("Manual"))
        self.manual_radio.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

        self.automatic_radio = MRadioButton(self.tr("Automatic"))
        self.automatic_radio.setChecked(True)
        self.automatic_radio.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

        self.webtoon_toggle = MToolButton()
        self.webtoon_toggle.set_dayu_svg("webtoon-toggle.svg")
        self.webtoon_toggle.huge()
        self.webtoon_toggle.setCheckable(True)
        self.webtoon_toggle.setToolTip(
            self.tr("Toggle Webtoon Mode. " "For comics that are read in long vertical strips")
        )
        self.webtoon_toggle.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

        workflow_settings = QSettings("ComicLabs", "ComicTranslate")
        workflow_settings.beginGroup("workflow")
        onomatopoeia_enabled = workflow_settings.value(
            "onomatopoeia_mode", False, type=bool
        )
        workflow_settings.endGroup()
        self.onomatopoeia_mode_enabled = bool(onomatopoeia_enabled)
        self.onomatopoeia_toggle = (
            MToolButton().svg("onomatopoeia.svg").small().icon_only()
        )
        self.onomatopoeia_toggle.setObjectName("onomatopoeiaToggle")
        self.onomatopoeia_toggle.setFixedSize(36, 30)
        self.onomatopoeia_toggle.setIconSize(QtCore.QSize(22, 22))
        self.onomatopoeia_toggle.setCheckable(True)
        self.onomatopoeia_toggle.setChecked(onomatopoeia_enabled)
        self.onomatopoeia_toggle.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.onomatopoeia_toggle.toggled.connect(
            self.set_onomatopoeia_mode_enabled
        )
        self._refresh_onomatopoeia_toggle()

        self.translate_button = MPushButton(self.tr("Translate All"))
        self.translate_button.setEnabled(True)
        self.translate_button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.cancel_button = MPushButton(self.tr("Cancel"))
        self.cancel_button.setEnabled(True)
        self.cancel_button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.batch_report_button = MPushButton(self.tr("Report"))
        self.batch_report_button.setEnabled(False)
        self.batch_report_button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

        header_layout.addWidget(self.hbutton_group)
        header_layout.addWidget(self.loading)
        header_layout.addStretch()
        header_layout.addWidget(self.webtoon_toggle)
        header_layout.addWidget(self.onomatopoeia_toggle)
        header_layout.addWidget(self.manual_radio)
        header_layout.addWidget(self.automatic_radio)
        header_layout.addWidget(self.translate_button)
        header_layout.addWidget(self.cancel_button)
        header_layout.addWidget(self.batch_report_button)

        self.search_panel = SearchReplacePanel(self)
        self.search_panel.setVisible(False)

        left_layout = QtWidgets.QVBoxLayout()
        left_layout.addWidget(MDivider())

        # Compact page actions row: new page-level actions can share this
        # space without taking vertical room away from the thumbnail list.
        self.page_actions_layout = QtWidgets.QHBoxLayout()
        self.page_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.page_actions_layout.setSpacing(4)

        self.replace_all_images_button = MToolButton().svg("replace-all.svg").small().icon_only()
        self.replace_all_images_button.setToolTip(
            self.tr("Replace all pages in natural filename order while keeping translated text boxes")
        )
        self.replace_all_images_button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.page_actions_layout.addWidget(self.replace_all_images_button)
        self.page_actions_layout.addStretch()
        left_layout.addLayout(self.page_actions_layout)

        self.image_card_layout = QtWidgets.QVBoxLayout()
        self.image_card_layout.addStretch(1)

        self.page_list.setLayout(self.image_card_layout)
        left_layout.addWidget(self.page_list)
        left_layout.addWidget(self.search_panel)
        left_widget = QtWidgets.QWidget()
        left_widget.setObjectName("leftPagesPanel")
        self.left_widget = left_widget
        left_widget.setLayout(left_layout)

        self.central_stack = QtWidgets.QStackedWidget()
        self.central_stack.setObjectName("editorCanvasStack")

        self.drag_browser = MDragFileButton(text=self.tr("Click or drag files here"), multiple=True)
        self.drag_browser.set_dayu_svg("attachment_line.svg")
        self.drag_browser.set_dayu_filters(
            [
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
                ".bmp",
                ".zip",
                ".cbz",
                ".cbr",
                ".cb7",
                ".cbt",
                ".pdf",
                ".epub",
                ".mtpr",
                ".ctpr",
                ".psd",
            ]
        )
        self.drag_browser.setToolTip(
            self.tr("Import Images, PDFs, Epubs or Comic Book Archive Files(cbr, cbz, etc)")
        )
        self.central_stack.addWidget(self.drag_browser)
        self.central_stack.addWidget(self.image_viewer)

        central_widget = QtWidgets.QWidget()
        central_widget.setObjectName("editorCenterColumn")
        central_layout = QtWidgets.QVBoxLayout(central_widget)
        central_layout.setContentsMargins(10, 10, 10, 10)
        central_layout.setSpacing(7)

        # Canva-like contextual formatting bar. It occupies space only while
        # one or more text boxes are selected, lowering just the manga canvas.
        self.text_options_bar = QtWidgets.QFrame()
        self.text_options_bar.setObjectName("textOptionsBar")
        self.text_options_bar.setMinimumHeight(42)
        self.text_options_bar.setMaximumHeight(48)
        self.text_options_bar.setVisible(True)
        self.text_options_bar.setEnabled(True)
        self.text_options_layout = QtWidgets.QHBoxLayout(self.text_options_bar)
        self.text_options_layout.setContentsMargins(7, 5, 7, 5)
        self.text_options_layout.setSpacing(4)
        central_layout.addWidget(self.text_options_bar)
        central_layout.addWidget(self.central_stack, 1)

        right_layout = QtWidgets.QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(MDivider())
        normal_right_widget = QtWidgets.QWidget()
        normal_right_widget.setObjectName("normalRightPanel")
        self.normal_right_widget = normal_right_widget
        normal_right_layout = QtWidgets.QVBoxLayout(normal_right_widget)
        normal_right_layout.setContentsMargins(9, 8, 9, 9)

        input_layout = QtWidgets.QHBoxLayout()

        s_combo_text_layout = QtWidgets.QVBoxLayout()
        self.s_combo = MComboBox().medium()
        self.s_combo.addItems([self.tr(lang) for lang in supported_source_languages])
        self.s_combo.setToolTip(self.tr("Source Language"))
        s_combo_text_layout.addWidget(self.s_combo)
        self.s_text_edit = MTextEdit()
        self.s_text_edit.setFixedHeight(120)
        s_combo_text_layout.addWidget(self.s_text_edit)
        input_layout.addLayout(s_combo_text_layout)

        t_combo_text_layout = QtWidgets.QVBoxLayout()
        self.t_combo = MComboBox().medium()
        self.t_combo.addItems([self.tr(lang) for lang in supported_target_languages])
        self.t_combo.setToolTip(self.tr("Target Language"))
        t_combo_text_layout.addWidget(self.t_combo)
        self.t_text_edit = MTextEdit()
        self.t_text_edit.setFixedHeight(120)
        t_combo_text_layout.addWidget(self.t_text_edit)
        input_layout.addLayout(t_combo_text_layout)

        text_render_layout = QtWidgets.QVBoxLayout()

        self.font_dropdown = MFontComboBox().small()
        self.font_dropdown.setToolTip(self.tr("Font"))
        self.font_dropdown.setMinimumWidth(170)
        self.font_dropdown.setMaximumWidth(240)
        self.font_family_button = QtWidgets.QToolButton()
        self.font_family_button.setObjectName("textBarFramedButton")
        self.font_family_button.setText(self.font_dropdown.currentText() or self.tr("Font"))
        self.font_family_button.setToolTip(self.tr("Font"))
        self.font_family_button.setMinimumWidth(118)
        self.font_family_button.setMaximumWidth(180)
        self.font_family_button.setFixedHeight(30)
        self.font_size_dropdown = _FontSizeComboBox().small()
        self.font_size_dropdown.setToolTip(self.tr("Font Size"))
        self.font_size_dropdown.addItems(
            [
                "4", "6", "8", "10", "12", "14", "16", "18", "20", "22",
                "24", "26", "28", "30", "32", "36", "40", "48", "56", "64",
                "72", "80", "96", "120", "144",
            ]
        )
        self.font_size_dropdown.setCurrentText("12")
        self.font_size_dropdown.setFixedWidth(36)
        self.font_size_dropdown.set_editable(True)
        self.font_size_dropdown.lineEdit().setValidator(QIntValidator(1, 999, self))
        self.font_size_dropdown.lineEdit().setAlignment(
            QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.font_size_dropdown.setStyleSheet("""
            QComboBox { border: none; background: transparent; padding: 0; }
            QComboBox::drop-down { border: none; width: 0px; }
            QComboBox::down-arrow { image: none; width: 0px; height: 0px; }
            QLineEdit { border: none; background: transparent; padding: 0; }
        """)
        self.font_size_control = QtWidgets.QFrame()
        self.font_size_control.setObjectName("textSizeControl")
        self.font_size_control.setFixedWidth(86)
        self.font_size_control.setFixedHeight(30)
        self.font_size_control.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        font_size_layout = QtWidgets.QHBoxLayout(self.font_size_control)
        font_size_layout.setContentsMargins(0, 0, 0, 0)
        font_size_layout.setSpacing(0)
        self.font_size_decrease_button = QtWidgets.QToolButton()
        self.font_size_decrease_button.setObjectName("fontSizeStepButton")
        self.font_size_decrease_button.setText("−")
        self.font_size_decrease_button.setToolTip(self.tr("Decrease font size by 2"))
        self.font_size_decrease_button.setFixedWidth(25)
        self.font_size_increase_button = QtWidgets.QToolButton()
        self.font_size_increase_button.setObjectName("fontSizeStepButton")
        self.font_size_increase_button.setText("+")
        self.font_size_increase_button.setToolTip(self.tr("Increase font size by 2"))
        self.font_size_increase_button.setFixedWidth(25)
        self.font_size_decrease_button.clicked.connect(
            lambda: self.adjust_font_size(-2)
        )
        self.font_size_increase_button.clicked.connect(
            lambda: self.adjust_font_size(2)
        )
        font_size_layout.addWidget(self.font_size_decrease_button)
        font_size_layout.addWidget(self.font_size_dropdown)
        font_size_layout.addWidget(self.font_size_increase_button)

        self.line_spacing_dropdown = MComboBox().small()
        self.line_spacing_dropdown.setToolTip(self.tr("Line Spacing"))
        self.line_spacing_dropdown.addItems(["1.0", "1.1", "1.2", "1.3", "1.4", "1.5"])
        self.line_spacing_dropdown.setFixedWidth(60)
        self.line_spacing_dropdown.set_editable(True)
        self.line_spacing_dropdown.hide()

        settings = QSettings("ComicLabs", "ComicTranslate")
        settings.beginGroup("text_rendering")
        dflt_clr = settings.value("color", "#000000")
        # The outline is an opt-in effect. Always start a new application
        # session with it disabled; selecting an outlined text box will still
        # reflect that box's own state in the toolbar.
        dflt_outline_check = False
        settings.setValue("outline", False)
        dflt_outline_color = settings.value("outline_color", "#000000")
        if not settings.value("outline_default_black_v3", False, type=bool):
            if QColor(dflt_outline_color) == QColor("#ffffff"):
                dflt_outline_color = "#000000"
                settings.setValue("outline_color", dflt_outline_color)
            settings.setValue("outline_default_black_v3", True)
        settings.endGroup()

        self.block_font_color_button = QtWidgets.QPushButton()
        self.block_font_color_button.setToolTip(self.tr("Font Color"))
        self.block_font_color_button.setFixedSize(30, 30)
        self.block_font_color_button.setStyleSheet(f"background-color: {dflt_clr}; border: none; border-radius: 5px;")
        self.block_font_color_button.setProperty("selected_color", dflt_clr)
        self.block_font_color_button.setProperty(
            "fill_style",
            {"mode": "solid", "color": QColor(dflt_clr).name(QColor.NameFormat.HexArgb)},
        )

        self.alignment_tool_group = MToolButtonGroup(orientation=QtCore.Qt.Horizontal, exclusive=True)
        alignment_tools = [
            {"svg": "tabler--align-left.svg", "checkable": True, "tooltip": "Align Left"},
            {"svg": "tabler--align-center.svg", "checkable": True, "tooltip": "Align Center"},
            {"svg": "tabler--align-right.svg", "checkable": True, "tooltip": "Align Right"},
            {"svg": "tabler--align-justified.svg", "checkable": True, "tooltip": "Justify"},
        ]
        self.alignment_tool_group.set_button_list(alignment_tools)
        self.alignment_tool_group.set_dayu_checked(1)
        self.alignment_tool_group.hide()

        # Keep the original button group as the controller's alignment state,
        # but expose one compact icon-only popup directly from the toolbar.
        self.alignment_menu_button = self.create_tool_button(svg="tabler--align-center.svg")
        self.alignment_menu_button.setObjectName("textBarMenuButton")
        self.alignment_menu_button.setFixedSize(32, 30)
        self.alignment_menu_button.setIconSize(QtCore.QSize(20, 20))
        self.alignment_menu_button.setToolTip(self.tr("Text Alignment"))
        self.alignment_menu_button.setPopupMode(
            QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.alignment_menu = QtWidgets.QMenu(self.alignment_menu_button)
        self.alignment_menu.setObjectName("textAlignmentPopup")
        self.alignment_menu_group = QtGui.QActionGroup(self.alignment_menu)
        self.alignment_menu_group.setExclusive(True)
        self.alignment_menu_actions = []
        self.alignment_popup_buttons = []
        self._alignment_menu_icons = [
            "tabler--align-left.svg",
            "tabler--align-center.svg",
            "tabler--align-right.svg",
            "tabler--align-justified.svg",
        ]
        alignment_popup_host = QtWidgets.QWidget(self.alignment_menu)
        alignment_popup_host.setObjectName("alignmentPopupHost")
        alignment_popup_layout = QtWidgets.QHBoxLayout(alignment_popup_host)
        alignment_popup_layout.setContentsMargins(5, 5, 5, 5)
        alignment_popup_layout.setSpacing(3)
        for index, label in enumerate((
            self.tr("Align Left"),
            self.tr("Align Center"),
            self.tr("Align Right"),
            self.tr("Justify"),
        )):
            action = QtGui.QAction(label, self.alignment_menu)
            action.setCheckable(True)
            self.alignment_menu_group.addAction(action)
            action.triggered.connect(
                lambda _checked=False, alignment_index=index: self.set_alignment_menu_value(
                    alignment_index, trigger=True
                )
            )
            self.alignment_menu_actions.append(action)
            choice = self.create_tool_button(svg=self._alignment_menu_icons[index])
            choice.setObjectName("alignmentIconChoice")
            choice.setCheckable(True)
            choice.setAutoExclusive(True)
            choice.setFixedSize(28, 28)
            choice.setIconSize(QtCore.QSize(18, 18))
            choice.setToolTip(label)
            choice.clicked.connect(
                lambda _checked=False, alignment_index=index:
                    self._select_alignment_from_popup(alignment_index)
            )
            action.toggled.connect(choice.setChecked)
            self.alignment_popup_buttons.append(choice)
            alignment_popup_layout.addWidget(choice)
        alignment_popup_host.setFixedWidth(135)
        alignment_popup_action = QtWidgets.QWidgetAction(self.alignment_menu)
        alignment_popup_action.setDefaultWidget(alignment_popup_host)
        self.alignment_menu.addAction(alignment_popup_action)
        self.alignment_menu_button.setMenu(self.alignment_menu)
        self.alignment_menu_button.setStyleSheet(
            "QToolButton::menu-indicator { image: none; width: 0px; height: 0px; }"
        )
        self.set_alignment_menu_value(1)

        self.uppercase_button = QtWidgets.QToolButton()
        self.uppercase_button.setObjectName("textFormatGlyphButton")
        self.uppercase_button.setText("aA")
        self.uppercase_button.setCheckable(True)
        self.uppercase_button.setFixedSize(32, 30)
        self.uppercase_button.setToolTip(self.tr("Uppercase / lowercase"))

        self.quick_text_button = QtWidgets.QPushButton(self.tr("Text+"))
        self.quick_text_button.setObjectName("textOptionsButton")
        self.quick_text_button.setFixedSize(64, 30)
        self.quick_text_button.setToolTip(self.tr("Add text box"))

        self.glossary_button = self.create_tool_button(svg="book-open.svg")
        self.glossary_button.setObjectName("textBarActionButton")
        self.glossary_button.setFixedSize(32, 30)
        self.glossary_button.setIconSize(QtCore.QSize(21, 21))
        self.glossary_button.setToolTip("Editar glosario de traducción")
        self.glossary_button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

        self.bold_button = self.create_tool_button(svg="bold.svg", checkable=True)
        self.bold_button.setToolTip(self.tr("Bold"))
        self.bold_button.hide()

        self.font_weight_button = QtWidgets.QToolButton()
        self.font_weight_button.setObjectName("textFormatGlyphButton")
        self.font_weight_button.setProperty("weightGlyph", True)
        self.font_weight_button.setProperty("weightActive", False)
        self.font_weight_button.setText("B")
        self.font_weight_button.setFixedSize(32, 30)
        self.font_weight_button.setToolTip(self.tr("Font weight"))
        bold_glyph_font = self.font_weight_button.font()
        bold_glyph_font.setBold(True)
        self.font_weight_button.setFont(bold_glyph_font)
        self.font_weight_menu = QtWidgets.QMenu(self.font_weight_button)
        self.font_weight_action_group = QtGui.QActionGroup(self.font_weight_menu)
        self.font_weight_action_group.setExclusive(True)
        self.font_weight_actions: dict[int, QtGui.QAction] = {}
        for weight, label in (
            (400, self.tr("Regular")),
            (600, self.tr("Semi Bold")),
            (700, self.tr("Bold")),
            (800, self.tr("Extra Bold")),
        ):
            action = self.font_weight_menu.addAction(label)
            action.setCheckable(True)
            action.setData(weight)
            self.font_weight_action_group.addAction(action)
            self.font_weight_actions[weight] = action
        self.set_font_weight_menu_value(400)

        self.italic_button = QtWidgets.QToolButton()
        self.italic_button.setObjectName("textFormatGlyphButton")
        self.italic_button.setProperty("italicGlyph", True)
        self.italic_button.setText("𝐼")
        self.italic_button.setCheckable(True)
        self.italic_button.setFixedSize(32, 30)
        self.italic_button.setToolTip(self.tr("Italic"))

        self.underline_button = QtWidgets.QToolButton()
        self.underline_button.setObjectName("textFormatGlyphButton")
        self.underline_button.setText("U")
        self.underline_button.setCheckable(True)
        self.underline_button.setFixedSize(32, 30)
        self.underline_button.setToolTip(self.tr("Underline"))
        underline_glyph_font = self.underline_button.font()
        underline_glyph_font.setUnderline(True)
        self.underline_button.setFont(underline_glyph_font)

        self.magic_eraser_button = self.create_tool_button(svg="eraser_fill.svg")
        self.magic_eraser_button.setObjectName("textBarMenuButton")
        self.magic_eraser_button.setFixedSize(32, 30)
        self.magic_eraser_button.setIconSize(QtCore.QSize(20, 20))
        self.magic_eraser_button.setToolTip(self.tr("Magic Eraser"))
        self.magic_eraser_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        self.magic_eraser_menu = QtWidgets.QMenu(self.magic_eraser_button)
        magic_widget = QtWidgets.QWidget(self.magic_eraser_menu)
        magic_layout = QtWidgets.QVBoxLayout(magic_widget)
        magic_layout.setContentsMargins(12, 10, 12, 10)
        magic_layout.setSpacing(6)
        magic_layout.addWidget(QtWidgets.QLabel(self.tr("Magic Eraser brush size")))
        self.magic_eraser_size_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.magic_eraser_size_slider.setRange(1, 100)
        self.magic_eraser_size_slider.setValue(25)
        self.magic_eraser_size_label = QtWidgets.QLabel("25 px")
        magic_layout.addWidget(self.magic_eraser_size_slider)
        magic_layout.addWidget(self.magic_eraser_size_label, alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        self.magic_eraser_sam_checkbox = QtWidgets.QCheckBox(self.tr("Refine mask with SAM (AI)"))
        self.magic_eraser_sam_checkbox.setChecked(True)
        self.magic_eraser_sam_checkbox.setToolTip(
            self.tr("Uses AI to fit the painted mask to the unwanted object before cleaning.")
        )
        magic_layout.addWidget(self.magic_eraser_sam_checkbox)
        magic_hint = QtWidgets.QLabel(
            self.tr("Paint the unwanted area, then press Clean. SAM is downloaded only on first use.")
        )
        magic_hint.setWordWrap(True)
        magic_layout.addWidget(magic_hint)
        magic_apply = QtWidgets.QPushButton(self.tr("Activate Magic Eraser"))
        magic_apply.clicked.connect(self.activate_magic_eraser)
        magic_layout.addWidget(magic_apply)
        magic_action = QtWidgets.QWidgetAction(self.magic_eraser_menu)
        magic_action.setDefaultWidget(magic_widget)
        self.magic_eraser_menu.addAction(magic_action)
        self.magic_eraser_size_slider.valueChanged.connect(
            lambda value: self.magic_eraser_size_label.setText(f"{value} px")
        )
        self.magic_eraser_button.setMenu(self.magic_eraser_menu)
        self.magic_eraser_button.setStyleSheet(
            "QToolButton::menu-indicator { image: none; width: 0px; height: 0px; }"
        )

        self.text_effects_button = QtWidgets.QPushButton(self.tr("Effects"))
        self.text_effects_button.setToolTip(
            self.tr("Edit glow, shadows, deformation and 3D for the selected text")
        )
        self.text_effects_button.setObjectName("textOptionsButton")
        self.text_effects_button.setFixedSize(72, 30)
        self.text_effects_button.setEnabled(False)
        self.text_effects_button.clicked.connect(self.show_text_effects_panel)

        self.line_spacing_button = self.create_tool_button(svg="text-spacing.svg")
        self.line_spacing_button.setObjectName("textBarMenuButton")
        self.line_spacing_button.setFixedSize(32, 30)
        self.line_spacing_button.setIconSize(QtCore.QSize(20, 20))
        self.line_spacing_button.setToolTip(self.tr("Letter and line spacing"))
        self.line_spacing_button.setPopupMode(
            QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.line_spacing_menu = QtWidgets.QMenu(self.line_spacing_button)
        typography_spacing_widget = QtWidgets.QWidget(self.line_spacing_menu)
        typography_spacing_widget.setObjectName("typographySpacingPopup")
        typography_spacing_layout = QtWidgets.QVBoxLayout(
            typography_spacing_widget
        )
        typography_spacing_layout.setContentsMargins(9, 8, 9, 9)
        typography_spacing_layout.setSpacing(6)

        typography_spacing_layout.addWidget(
            QtWidgets.QLabel(
                self.tr("Letter spacing"),
                typography_spacing_widget,
            )
        )
        letter_spacing_row = QtWidgets.QHBoxLayout()
        letter_spacing_row.setSpacing(6)
        self.letter_spacing_slider = QtWidgets.QSlider(
            QtCore.Qt.Orientation.Horizontal
        )
        self.letter_spacing_slider.setRange(-50, 200)
        self.letter_spacing_slider.setValue(0)
        self.letter_spacing_slider.setMinimumWidth(128)
        self.letter_spacing_spinbox = QtWidgets.QDoubleSpinBox()
        self.letter_spacing_spinbox.setObjectName("typographySpacingValue")
        self.letter_spacing_spinbox.setRange(-50.0, 200.0)
        self.letter_spacing_spinbox.setDecimals(1)
        self.letter_spacing_spinbox.setSingleStep(1.0)
        self.letter_spacing_spinbox.setSuffix("%")
        self.letter_spacing_spinbox.setFixedWidth(66)
        letter_spacing_row.addWidget(self.letter_spacing_slider, 1)
        letter_spacing_row.addWidget(self.letter_spacing_spinbox)
        typography_spacing_layout.addLayout(letter_spacing_row)

        typography_spacing_layout.addWidget(
            QtWidgets.QLabel(
                self.tr("Line spacing"),
                typography_spacing_widget,
            )
        )
        line_spacing_row = QtWidgets.QHBoxLayout()
        line_spacing_row.setSpacing(6)
        self.line_spacing_slider = QtWidgets.QSlider(
            QtCore.Qt.Orientation.Horizontal
        )
        self.line_spacing_slider.setRange(50, 300)
        self.line_spacing_slider.setValue(100)
        self.line_spacing_slider.setMinimumWidth(128)
        self.line_spacing_spinbox = QtWidgets.QDoubleSpinBox()
        self.line_spacing_spinbox.setObjectName("typographySpacingValue")
        self.line_spacing_spinbox.setRange(0.5, 3.0)
        self.line_spacing_spinbox.setDecimals(2)
        self.line_spacing_spinbox.setSingleStep(0.05)
        self.line_spacing_spinbox.setValue(1.0)
        self.line_spacing_spinbox.setFixedWidth(66)
        line_spacing_row.addWidget(self.line_spacing_slider, 1)
        line_spacing_row.addWidget(self.line_spacing_spinbox)
        typography_spacing_layout.addLayout(line_spacing_row)

        typography_spacing_action = QtWidgets.QWidgetAction(
            self.line_spacing_menu
        )
        typography_spacing_action.setDefaultWidget(typography_spacing_widget)
        self.line_spacing_menu.addAction(typography_spacing_action)
        self.line_spacing_button.setMenu(self.line_spacing_menu)
        self.line_spacing_button.setStyleSheet(
            "QToolButton::menu-indicator { image: none; width: 0px; height: 0px; }"
        )

        self.letter_spacing_slider.valueChanged.connect(
            lambda value: self.letter_spacing_spinbox.setValue(float(value))
        )
        self.letter_spacing_spinbox.valueChanged.connect(
            self._sync_letter_spacing_slider
        )
        self.line_spacing_slider.valueChanged.connect(
            lambda value: self.line_spacing_spinbox.setValue(value / 100.0)
        )
        self.line_spacing_spinbox.valueChanged.connect(
            self._sync_line_spacing_controls
        )
        self.line_spacing_dropdown.currentTextChanged.connect(
            self.set_line_spacing_menu_value
        )
        self.set_letter_spacing_control_value(0.0)
        self.set_line_spacing_menu_value("1.0")

        self.text_opacity_button = self.create_tool_button(
            svg="transparency-diagonal-fade.svg"
        )
        self.text_opacity_button.setObjectName("textBarMenuButton")
        self.text_opacity_button.setFixedSize(32, 30)
        self.text_opacity_button.setIconSize(QtCore.QSize(20, 20))
        self.text_opacity_button.setToolTip(self.tr("Transparency"))
        self.text_opacity_button.setPopupMode(
            QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.text_opacity_menu = QtWidgets.QMenu(self.text_opacity_button)
        opacity_widget = QtWidgets.QWidget(self.text_opacity_menu)
        opacity_widget.setObjectName("textOpacityPopup")
        opacity_layout = QtWidgets.QVBoxLayout(opacity_widget)
        opacity_layout.setContentsMargins(9, 8, 9, 8)
        opacity_layout.setSpacing(6)
        opacity_header = QtWidgets.QHBoxLayout()
        opacity_header.addWidget(QtWidgets.QLabel(self.tr("Transparency")))
        opacity_header.addStretch()
        self.text_opacity_value_label = QtWidgets.QLabel("100%")
        opacity_header.addWidget(self.text_opacity_value_label)
        opacity_layout.addLayout(opacity_header)
        self.text_opacity_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.text_opacity_slider.setRange(0, 100)
        self.text_opacity_slider.setValue(100)
        self.text_opacity_slider.setMinimumWidth(145)
        opacity_layout.addWidget(self.text_opacity_slider)
        opacity_action = QtWidgets.QWidgetAction(self.text_opacity_menu)
        opacity_action.setDefaultWidget(opacity_widget)
        self.text_opacity_menu.addAction(opacity_action)
        self.text_opacity_button.setMenu(self.text_opacity_menu)
        self.text_opacity_button.setStyleSheet(
            "QToolButton::menu-indicator { image: none; width: 0px; height: 0px; }"
        )
        self.text_opacity_slider.valueChanged.connect(self.set_text_opacity_preview)
        self.set_text_opacity_preview(100)

        self.style_copy_button = self.create_tool_button(
            svg="paint-roller.svg"
        )
        self.style_copy_button.setObjectName("textBarActionButton")
        self.style_copy_button.setCheckable(True)
        self.style_copy_button.setFixedSize(32, 30)
        self.style_copy_button.setIconSize(QtCore.QSize(20, 20))
        self.style_copy_button.setToolTip(
            self.tr("Paint the selected text style onto another text box")
        )
        self.style_copy_menu = QtWidgets.QMenu(self.style_copy_button)
        self.apply_style_action = self.style_copy_menu.addAction(self.tr("Apply copied style"))
        self.apply_style_action.setEnabled(False)

        self.outline_checkbox = MCheckBox(self.tr("Outline"))
        self.outline_checkbox.setChecked(dflt_outline_check)
        self.outline_checkbox.setParent(normal_right_widget)
        self.outline_checkbox.hide()

        self.outline_font_color_button = QtWidgets.QPushButton(normal_right_widget)
        self.outline_font_color_button.setToolTip(self.tr("Outline Color"))
        self.outline_font_color_button.setFixedSize(30, 30)
        self.outline_font_color_button.setStyleSheet(
            f"background-color: {dflt_outline_color}; border: none; border-radius: 5px;"
        )
        self.outline_font_color_button.setProperty(
            "selected_color", QColor(dflt_outline_color).name()
        )
        self.outline_font_color_button.hide()

        self.outline_toolbar_button = QtWidgets.QToolButton()
        self.outline_toolbar_button.setObjectName("textFormatGlyphButton")
        self.outline_toolbar_button.setCheckable(True)
        self.outline_toolbar_button.setChecked(dflt_outline_check)
        self.outline_toolbar_button.setFixedSize(32, 30)
        self.outline_toolbar_button.setIconSize(QtCore.QSize(26, 26))
        self.outline_toolbar_button.setToolTip(self.tr("Toggle text outline"))
        self.outline_toolbar_button.toggled.connect(
            self.outline_checkbox.setChecked
        )
        self.outline_checkbox.toggled.connect(self._sync_outline_toolbar_button)
        self.refresh_outline_toolbar_button()

        self.outline_width_dropdown = MComboBox().small()
        self.outline_width_dropdown.setParent(normal_right_widget)
        self.outline_width_dropdown.setFixedWidth(60)
        self.outline_width_dropdown.setToolTip(self.tr("Outline Width"))
        self.outline_width_dropdown.addItems(["1.0", "1.15", "1.3", "1.4", "1.5"])
        self.outline_width_dropdown.set_editable(True)
        self.outline_width_dropdown.hide()

        self.watermark_button = self.create_tool_button(svg="water-drop.svg")
        self.watermark_button.setObjectName("textBarActionButton")
        self.watermark_button.setFixedSize(32, 30)
        self.watermark_button.setIconSize(QtCore.QSize(20, 20))
        self.watermark_button.setToolTip(self.tr("Watermark"))
        self.clean_watermark_button = self.create_tool_button(
            svg="broom.svg", checkable=True
        )
        self.clean_watermark_button.setObjectName("textBarActionButton")
        self.clean_watermark_button.setFixedSize(32, 30)
        self.clean_watermark_button.setIconSize(QtCore.QSize(24, 24))
        self.clean_watermark_button.setToolTip(self.tr("Select area to clean watermark"))

        # Populate the contextual bar only after every quick control exists.
        self.text_options_layout.addWidget(self.font_family_button, 1)
        self.text_options_layout.addWidget(self.font_size_control)
        self.text_options_layout.addWidget(self.block_font_color_button)
        self._add_text_bar_separator()
        glyph_alignment = QtCore.Qt.AlignmentFlag.AlignVCenter
        self.text_options_layout.addWidget(
            self.font_weight_button, alignment=glyph_alignment
        )
        self.text_options_layout.addWidget(
            self.italic_button, alignment=glyph_alignment
        )
        self.text_options_layout.addWidget(
            self.underline_button, alignment=glyph_alignment
        )
        self.text_options_layout.addWidget(
            self.uppercase_button, alignment=glyph_alignment
        )
        self._add_text_bar_separator()
        self.text_options_layout.addWidget(self.alignment_menu_button)
        self.text_options_layout.addWidget(self.line_spacing_button)
        self.text_options_layout.addWidget(self.outline_toolbar_button)
        self.text_options_layout.addWidget(self.watermark_button)
        self.text_options_layout.addWidget(self.text_opacity_button)
        self._add_text_bar_separator()
        self.text_creation_group = QtWidgets.QWidget(self.text_options_bar)
        self.text_creation_group.setObjectName("textCreationGroup")
        self.text_creation_group.setFixedSize(170, 30)
        text_creation_layout = QtWidgets.QHBoxLayout(self.text_creation_group)
        text_creation_layout.setContentsMargins(0, 0, 0, 0)
        text_creation_layout.setSpacing(1)
        text_creation_layout.addWidget(self.text_effects_button)
        text_creation_layout.addWidget(self.quick_text_button)
        text_creation_layout.addWidget(self.glossary_button)
        self.text_options_layout.addWidget(self.text_creation_group)
        self.text_options_layout.addWidget(self.style_copy_button)
        self.text_options_layout.addWidget(self.magic_eraser_button)
        self.text_options_layout.addWidget(self.clean_watermark_button)
        self._selection_only_text_controls = [
            self.font_family_button,
            self.font_size_control,
            self.block_font_color_button,
            self.font_weight_button,
            self.italic_button,
            self.underline_button,
            self.uppercase_button,
            self.alignment_menu_button,
            self.line_spacing_button,
            self.outline_toolbar_button,
            self.text_opacity_button,
            self.text_effects_button,
            self.style_copy_button,
        ]
        self.set_text_selection_controls_enabled(False)

        tools_widget = QtWidgets.QWidget()
        tools_widget.setObjectName("inpaintingToolsHost")
        tools_layout = QtWidgets.QVBoxLayout()

        misc_lay = QtWidgets.QHBoxLayout()

        self.pan_button = self.create_tool_button(svg="pan_tool.svg", checkable=True)
        self.pan_button.setToolTip(self.tr("Pan Image"))
        self.pan_button.clicked.connect(self.toggle_pan_tool)
        self.tool_buttons["pan"] = self.pan_button

        self.set_all_button = MPushButton(self.tr("Set for all"))
        self.set_all_button.setToolTip(
            self.tr("Sets the Source and Target Language on the current page for all pages")
        )

        self.japanese_ocr_button = MToolButton().text_only().small()
        self.japanese_ocr_button.setText("JP OCR")
        self.japanese_ocr_button.setCheckable(True)
        self.japanese_ocr_button.setToolTip("Forzar OCR japones")
        self.japanese_ocr_button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

        misc_lay.addWidget(self.pan_button)
        misc_lay.addWidget(self.japanese_ocr_button)
        misc_lay.addWidget(self.set_all_button)
        misc_lay.addStretch()

        box_tools_lay = QtWidgets.QHBoxLayout()

        self.box_button = self.create_tool_button(svg="select.svg", checkable=True)
        self.box_button.setToolTip(self.tr("Draw or Select Text Boxes"))
        self.box_button.clicked.connect(self.toggle_box_tool)
        self.tool_buttons["box"] = self.box_button

        self.delete_button = self.create_tool_button(svg="trash_line.svg", checkable=False)
        self.delete_button.setToolTip(self.tr("Delete Selected Box"))

        self.clear_rectangles_button = self.create_tool_button(svg="clear-outlined.svg")
        self.clear_rectangles_button.setToolTip(self.tr("Remove all the Boxes on the Image"))

        self.draw_blklist_blks = self.create_tool_button(svg="gridicons--create.svg")
        self.draw_blklist_blks.setToolTip(
            self.tr(
                "Draws all the Text Blocks in the existing Text Block List\n"
                "back on the Image (for further editing)"
            )
        )

        box_tools_lay.addWidget(self.box_button)
        box_tools_lay.addWidget(self.delete_button)
        box_tools_lay.addWidget(self.clear_rectangles_button)
        box_tools_lay.addWidget(self.draw_blklist_blks)

        self.change_all_blocks_size_dec = self.create_tool_button(svg="minus_line.svg")
        self.change_all_blocks_size_dec.setToolTip(self.tr("Reduce the size of all blocks"))

        self.change_all_blocks_size_diff = MLineEdit()
        self.change_all_blocks_size_diff.setFixedWidth(30)
        self.change_all_blocks_size_diff.setText("3")

        int_validator = QIntValidator()
        self.change_all_blocks_size_diff.setValidator(int_validator)
        self.change_all_blocks_size_diff.setAlignment(QtCore.Qt.AlignCenter)

        self.change_all_blocks_size_inc = self.create_tool_button(svg="add_line.svg")
        self.change_all_blocks_size_inc.setToolTip(self.tr("Increase the size of all blocks"))

        box_tools_lay.addStretch()
        box_tools_lay.addWidget(self.change_all_blocks_size_dec)
        box_tools_lay.addWidget(self.change_all_blocks_size_diff)
        box_tools_lay.addWidget(self.change_all_blocks_size_inc)
        box_tools_lay.addStretch()

        inp_tools_lay = QtWidgets.QHBoxLayout()

        self.brush_button = self.create_tool_button(svg="brush-fill.svg", checkable=True)
        self.brush_button.setToolTip(self.tr("Draw Brush Strokes for Cleaning Image"))
        self.brush_button.clicked.connect(self.toggle_brush_tool)
        self.tool_buttons["brush"] = self.brush_button

        self.eraser_button = self.create_tool_button(svg="eraser_fill.svg", checkable=True)
        self.eraser_button.setToolTip(self.tr("Erase Brush Strokes"))
        self.eraser_button.clicked.connect(self.toggle_eraser_tool)
        self.tool_buttons["eraser"] = self.eraser_button

        self.clear_brush_strokes_button = self.create_tool_button(svg="clear-outlined.svg")
        self.clear_brush_strokes_button.setToolTip(self.tr("Remove all the brush strokes on the Image"))

        inp_tools_lay.addWidget(self.brush_button)
        inp_tools_lay.addWidget(self.eraser_button)
        inp_tools_lay.addWidget(self.clear_brush_strokes_button)
        inp_tools_lay.addStretch()

        self.brush_eraser_slider = MSlider()
        self.brush_eraser_slider.setMinimum(1)
        self.brush_eraser_slider.setMaximum(100)
        self.brush_eraser_slider.setValue(10)
        self.brush_eraser_slider.setToolTip(self.tr("Brush/Eraser Size Slider"))
        self.brush_eraser_slider.valueChanged.connect(self.set_brush_eraser_size)

        tools_layout.addLayout(misc_lay)
        box_title = QtWidgets.QLabel(self.tr("Box Drawing"), tools_widget)
        box_title.setObjectName("rightPanelSectionTitle")
        tools_layout.addWidget(box_title)
        tools_layout.addLayout(box_tools_lay)

        inp_title = QtWidgets.QLabel(self.tr("Inpainting"), tools_widget)
        inp_title.setObjectName("rightPanelSectionTitle")
        tools_layout.addWidget(inp_title)
        tools_layout.addLayout(inp_tools_lay)
        tools_layout.addWidget(self.brush_eraser_slider)
        tools_layout.addStretch()
        tools_widget.setLayout(tools_layout)

        tools_scroll = QtWidgets.QScrollArea()
        tools_scroll.setObjectName("inpaintingToolsScroll")
        tools_scroll.setWidgetResizable(True)
        tools_scroll.setWidget(tools_widget)
        tools_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tools_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        tools_scroll.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

        normal_right_layout.addLayout(input_layout)

        default_right_widget = QtWidgets.QWidget()
        default_right_widget.setObjectName("defaultRightPanel")
        default_right_layout = QtWidgets.QVBoxLayout(default_right_widget)
        default_right_layout.setContentsMargins(0, 0, 0, 0)
        default_right_layout.setSpacing(0)
        default_right_layout.addLayout(text_render_layout)
        default_right_layout.addWidget(tools_scroll, 1)
        self.music_player = MusicPlayerWidget(default_right_widget)
        default_right_layout.addWidget(self.music_player)

        self.text_format_panel = self._build_text_format_panel()
        self.text_effects_panel = TextEffectsPanel()
        self.text_effects_panel.backRequested.connect(self.show_main_right_panel)
        self.right_panel_stack = QtWidgets.QStackedWidget()
        self.right_panel_stack.setObjectName("rightPanelStack")
        self.right_panel_stack.addWidget(default_right_widget)
        self.right_panel_stack.addWidget(self.text_format_panel)
        self.right_panel_stack.addWidget(self.text_effects_panel)
        self.right_panel_stack.setCurrentWidget(default_right_widget)
        normal_right_layout.addWidget(self.right_panel_stack, 1)
        right_layout.addWidget(normal_right_widget, 1)

        self.block_font_color_button.clicked.connect(
            lambda: self.show_text_format_section("fill")
        )
        self.outline_toolbar_button.clicked.connect(
            self.handle_outline_toolbar_clicked
        )
        self.font_family_button.clicked.connect(
            lambda: self.show_text_format_section("font")
        )
        self.font_weight_button.clicked.connect(
            self._handle_font_weight_toolbar_clicked
        )
        right_widget = QtWidgets.QWidget()
        right_widget.setObjectName("rightPanelColumn")
        self.right_widget = right_widget
        right_widget.setLayout(right_layout)

        splitter = QtWidgets.QSplitter()
        splitter.setObjectName("workspaceSplitter")
        splitter.addWidget(left_widget)
        splitter.addWidget(central_widget)
        splitter.addWidget(right_widget)

        right_widget.setMinimumWidth(280)

        splitter.setStretchFactor(0, 40)
        splitter.setStretchFactor(1, 80)
        splitter.setStretchFactor(2, 10)

        workflow_toolbar = QtWidgets.QWidget(content_widget)
        workflow_toolbar.setObjectName("workflowToolbar")
        workflow_toolbar.setLayout(header_layout)
        self.workflow_toolbar = workflow_toolbar

        content_layout = QtWidgets.QVBoxLayout()
        content_layout.addWidget(workflow_toolbar)
        content_layout.addWidget(self.progress_bar)
        content_layout.addWidget(splitter)

        content_layout.setStretchFactor(workflow_toolbar, 0)
        content_layout.setStretchFactor(splitter, 1)

        content_widget.setLayout(content_layout)
        content_widget.setObjectName("workspaceRoot")
        self.workspace_content_widget = content_widget
        self._configure_workspace_scrollbars(content_widget, self._is_dark_theme)

        return content_widget

    def _build_text_format_panel(self) -> QtWidgets.QWidget:
        """Build the detailed text inspector shown below the translation boxes."""
        panel = QtWidgets.QWidget()
        panel.setObjectName("textFormatPanel")
        root = QtWidgets.QVBoxLayout(panel)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        header = QtWidgets.QHBoxLayout()
        back = QtWidgets.QToolButton(panel)
        back.setObjectName("formatBackButton")
        back.setText("‹")
        back.setFixedSize(30, 30)
        back.setToolTip(self.tr("Back"))
        back.clicked.connect(self.show_main_right_panel)
        self.text_format_title = QtWidgets.QLabel(self.tr("Text format"), panel)
        self.text_format_title.setObjectName("textFormatTitle")
        header.addWidget(back)
        header.addWidget(self.text_format_title)
        header.addStretch()
        root.addLayout(header)

        self.text_format_stack = QtWidgets.QStackedWidget(panel)
        self.text_format_stack.setObjectName("textFormatStack")
        self.text_format_sections: dict[str, QtWidgets.QWidget] = {}
        self.text_format_section_titles = {
            "fill": self.tr("Text color"),
            "outline": self.tr("Outline"),
            "font": self.tr("Font"),
        }

        fill_page = self._build_fill_inspector_page()
        self._add_text_format_section("fill", fill_page)

        outline_page = self._build_outline_inspector_page()
        self._add_text_format_section("outline", outline_page)

        font_page = self._build_font_inspector_page()
        self._add_text_format_section("font", font_page)

        root.addWidget(self.text_format_stack, 1)
        self.show_text_format_section("fill", require_selection=False)
        return panel

    def _new_text_format_page(self, description: str = "") -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        page.setObjectName("textFormatPage")
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(9)
        if description:
            label = QtWidgets.QLabel(description, page)
            label.setObjectName("formatDescription")
            label.setWordWrap(True)
            layout.addWidget(label)
        return page

    def _add_text_format_section(self, name: str, page: QtWidgets.QWidget) -> None:
        self.text_format_sections[name] = page
        self.text_format_stack.addWidget(page)

    def _build_font_inspector_page(self) -> QtWidgets.QWidget:
        """Build a Canva-like searchable font browser with useful groups."""
        page = self._new_text_format_page()
        layout = page.layout()

        # Keep the existing combo as the application-wide font state and signal
        # source, but replace its extra popup click with the visible browser.
        self.font_dropdown.setParent(page)
        self.font_dropdown.hide()

        self.font_search_input = QtWidgets.QLineEdit(page)
        self.font_search_input.setObjectName("fontSearchInput")
        self.font_search_input.setClearButtonEnabled(True)
        self.font_search_input.setPlaceholderText(
            self.tr('Try "Arial" or "Aleo"')
        )
        search_icon = self.create_tool_button(svg="search_line.svg").icon()
        self.font_search_input.addAction(
            search_icon,
            QtWidgets.QLineEdit.ActionPosition.LeadingPosition,
        )
        self.font_search_input.textChanged.connect(self.refresh_font_inspector)
        layout.addWidget(self.font_search_input)

        self.font_browser_scroll = QtWidgets.QScrollArea(page)
        self.font_browser_scroll.setObjectName("fontBrowserScroll")
        self.font_browser_scroll.setWidgetResizable(True)
        self.font_browser_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.font_browser_scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.font_browser_host = QtWidgets.QWidget()
        self.font_browser_host.setObjectName("fontBrowserHost")
        self.font_browser_layout = QtWidgets.QVBoxLayout(self.font_browser_host)
        self.font_browser_layout.setContentsMargins(0, 0, 0, 0)
        self.font_browser_layout.setSpacing(4)
        self.font_browser_scroll.setWidget(self.font_browser_host)
        layout.addWidget(self.font_browser_scroll, 1)

        self._favorite_fonts = self._load_favorite_fonts()
        self.refresh_font_inspector()
        return page

    @staticmethod
    def _font_name_list(value) -> list[str]:
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [part.strip() for part in value.split(",") if part.strip()]
        return []

    def _load_favorite_fonts(self) -> list[str]:
        settings = QSettings("ComicLabs", "ComicTranslate")
        settings.beginGroup("text_rendering")
        favorites = self._font_name_list(settings.value("favorite_fonts", []))
        settings.endGroup()
        return list(dict.fromkeys(favorites))

    def _save_favorite_fonts(self) -> None:
        settings = QSettings("ComicLabs", "ComicTranslate")
        settings.beginGroup("text_rendering")
        settings.setValue("favorite_fonts", list(self._favorite_fonts))
        settings.endGroup()

    def _manga_font_families(self) -> list[str]:
        """Return every font already used by editable manga text boxes."""
        families: set[str] = set()
        viewer = getattr(self, "image_viewer", None)
        for item in getattr(viewer, "text_items", []) if viewer is not None else []:
            family = str(getattr(item, "font_family", "") or "").strip()
            if family:
                families.add(family)

        for state in getattr(self, "image_states", {}).values():
            if not isinstance(state, dict):
                continue
            viewer_state = state.get("viewer_state", state)
            if not isinstance(viewer_state, dict):
                continue
            for text_state in viewer_state.get("text_items_state", []) or []:
                if not isinstance(text_state, dict):
                    continue
                family = str(text_state.get("font_family", "") or "").strip()
                if family:
                    families.add(family)
        return sorted(families, key=str.casefold)

    def _all_font_families(self) -> list[str]:
        families = set(QtGui.QFontDatabase.families())
        for index in range(self.font_dropdown.count()):
            family = self.font_dropdown.itemText(index).strip()
            if family:
                families.add(family)
        families.update(self._favorite_fonts)
        families.update(self._manga_font_families())
        current = self.font_dropdown.currentText().strip()
        if current:
            families.add(current)
        return sorted(families, key=str.casefold)

    def _clear_font_browser(self) -> None:
        while self.font_browser_layout.count():
            item = self.font_browser_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def refresh_font_inspector(self, *_args) -> None:
        if not hasattr(self, "font_browser_layout"):
            return
        query = self.font_search_input.text().strip().casefold()
        current = self.font_dropdown.currentText().strip()
        favorites = [
            family for family in self._favorite_fonts
            if not query or query in family.casefold()
        ]
        favorite_names = set(self._favorite_fonts)
        manga = [
            family for family in self._manga_font_families()
            if family not in favorite_names
            and (not query or query in family.casefold())
        ]
        promoted = favorite_names | set(manga)
        all_fonts = [
            family for family in self._all_font_families()
            if family not in promoted
            and (not query or query in family.casefold())
        ]

        self._clear_font_browser()
        self._font_inspector_choice_buttons = []
        self._add_font_browser_section(
            self.tr("Favorite fonts").upper(),
            favorites,
            current,
            self.tr("Mark a font with the star to place it here."),
            "favorites",
        )
        self._add_font_browser_section(
            self.tr("Manga fonts").upper(),
            manga,
            current,
            self.tr("Fonts used by the manga will appear here."),
            "document",
        )
        self._add_font_browser_section(
            self.tr("All fonts").upper(),
            all_fonts,
            current,
            self.tr("No fonts match this search."),
            "all",
        )
        self.font_browser_layout.addStretch()

    def _add_font_browser_section(
        self,
        title: str,
        families: list[str],
        current: str,
        empty_text: str,
        icon_kind: str,
    ) -> None:
        header = QtWidgets.QWidget(self.font_browser_host)
        header.setObjectName("fontSectionHeader")
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(3, 7, 3, 1)
        header_layout.setSpacing(6)
        icon = QtWidgets.QLabel(header)
        icon.setObjectName("fontSectionIcon")
        icon.setFixedSize(18, 18)
        icon.setPixmap(self._font_section_icon_pixmap(icon_kind))
        heading = QtWidgets.QLabel(title, header)
        heading.setObjectName("fontSectionTitle")
        header_layout.addWidget(icon)
        header_layout.addWidget(heading)
        header_layout.addStretch()
        self.font_browser_layout.addWidget(header)
        if not families:
            empty = QtWidgets.QLabel(empty_text, self.font_browser_host)
            empty.setObjectName("fontSectionEmpty")
            empty.setWordWrap(True)
            self.font_browser_layout.addWidget(empty)
            return
        for family in families:
            self.font_browser_layout.addWidget(
                self._create_font_browser_row(family, family == current)
            )

    def _font_section_icon_pixmap(self, kind: str) -> QtGui.QPixmap:
        pixmap = QtGui.QPixmap(18, 18)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        colour = QColor(
            "#ffffff" if getattr(self, "_is_dark_theme", True) else "#111111"
        )
        painter.setPen(
            QtGui.QPen(
                colour,
                1.45,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
                QtCore.Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

        if kind == "document":
            path = QtGui.QPainterPath()
            path.moveTo(4, 2)
            path.lineTo(11.5, 2)
            path.lineTo(15, 5.5)
            path.lineTo(15, 16)
            path.lineTo(4, 16)
            path.closeSubpath()
            path.moveTo(11.5, 2)
            path.lineTo(11.5, 5.5)
            path.lineTo(15, 5.5)
            painter.drawPath(path)
            painter.drawLine(QtCore.QPointF(6.2, 9), QtCore.QPointF(12.8, 9))
            painter.drawLine(QtCore.QPointF(6.2, 12), QtCore.QPointF(11.5, 12))
        elif kind == "favorites":
            star = QtGui.QPainterPath()
            for index in range(10):
                angle = math.radians(-90 + index * 36)
                radius = 6.5 if index % 2 == 0 else 2.75
                point = QtCore.QPointF(
                    9 + math.cos(angle) * radius,
                    9 + math.sin(angle) * radius,
                )
                star.moveTo(point) if index == 0 else star.lineTo(point)
            star.closeSubpath()
            painter.drawPath(star)
        else:
            self._draw_font_sparkle(painter, 8.0, 9.0, 5.2)
            self._draw_font_sparkle(painter, 14.5, 4.3, 2.1)
            self._draw_font_sparkle(painter, 14.3, 14.2, 1.6)
        painter.end()
        return pixmap

    @staticmethod
    def _draw_font_sparkle(
        painter: QtGui.QPainter,
        center_x: float,
        center_y: float,
        radius: float,
    ) -> None:
        inner = radius * 0.24
        path = QtGui.QPainterPath()
        points = (
            (center_x, center_y - radius),
            (center_x + inner, center_y - inner),
            (center_x + radius, center_y),
            (center_x + inner, center_y + inner),
            (center_x, center_y + radius),
            (center_x - inner, center_y + inner),
            (center_x - radius, center_y),
            (center_x - inner, center_y - inner),
        )
        for index, point in enumerate(points):
            qpoint = QtCore.QPointF(*point)
            path.moveTo(qpoint) if index == 0 else path.lineTo(qpoint)
        path.closeSubpath()
        painter.drawPath(path)

    def _create_font_browser_row(
        self,
        family: str,
        selected: bool,
    ) -> QtWidgets.QWidget:
        row = QtWidgets.QFrame(self.font_browser_host)
        row.setObjectName("fontFamilyRow")
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(4, 2, 56, 2)
        row_layout.setSpacing(4)

        family_button = QtWidgets.QPushButton(family, row)
        family_button.setObjectName("fontFamilyChoice")
        family_button.setProperty("fontFamily", family)
        family_button.setProperty("selected", selected)
        family_button.setFlat(True)
        family_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        family_button.setStyleSheet(
            f"font-family: \"{family.replace(chr(34), '')}\";"
        )
        family_button.clicked.connect(
            lambda _checked=False, name=family: self._select_font_from_inspector(name)
        )
        row_layout.addWidget(family_button, 1)
        self._font_inspector_choice_buttons.append(family_button)

        favorite = family in self._favorite_fonts
        star = MToolButton().svg(
            "tabler--star-filled.svg" if favorite else "tabler--star.svg"
        ).small().icon_only()
        star.setFixedWidth(24)
        star.setToolTip(
            self.tr("Remove from favorites")
            if favorite else self.tr("Add to favorites")
        )
        star.clicked.connect(
            lambda _checked=False, name=family: self._toggle_favorite_font(name)
        )
        row_layout.addWidget(star)
        return row

    def _update_font_inspector_selection(self, family: str) -> None:
        """Update the highlighted font without rebuilding or moving any row."""
        for button in getattr(self, "_font_inspector_choice_buttons", []):
            selected = button.property("fontFamily") == family
            if bool(button.property("selected")) == selected:
                continue
            button.setProperty("selected", selected)
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

    def _select_font_from_inspector(self, family: str) -> None:
        family = (family or "").strip()
        if not family:
            return
        previous = self.font_dropdown.currentText()
        self.set_font(family)
        if (
            self.font_dropdown.currentText() == previous
            and hasattr(self, "text_ctrl")
        ):
            self.text_ctrl.on_font_dropdown_change(family)
        if hasattr(self, "text_ctrl"):
            self.text_ctrl.record_font_used(family, reorder=False)
        selected_family = self.font_dropdown.currentText().strip() or family
        self.font_family_button.setText(selected_family)
        self._update_font_inspector_selection(selected_family)

    def _toggle_favorite_font(self, family: str) -> None:
        if family in self._favorite_fonts:
            self._favorite_fonts.remove(family)
        else:
            self._favorite_fonts.append(family)
        self._save_favorite_fonts()
        self.refresh_font_inspector()

    def _build_outline_inspector_page(self) -> QtWidgets.QWidget:
        page = self._new_text_format_page(
            self.tr("Choose the outline color and thickness for the selected text.")
        )
        layout = page.layout()
        self._outline_inspector_syncing = False
        outline_colour = QColor(
            self.outline_font_color_button.property("selected_color") or "#000000"
        )
        self.outline_inspector_picker = CompactColorPicker(outline_colour, page)
        self.outline_inspector_picker.currentColorChanged.connect(
            self._preview_outline_inspector_colour
        )
        self.outline_inspector_picker.editingFinished.connect(
            self._commit_outline_inspector
        )
        layout.addWidget(self.outline_inspector_picker)

        width_header = QtWidgets.QHBoxLayout()
        width_header.addWidget(QtWidgets.QLabel(self.tr("Outline Width"), page))
        width_header.addStretch()
        self.outline_inspector_width_spinbox = QtWidgets.QDoubleSpinBox(page)
        self.outline_inspector_width_spinbox.setRange(0.5, 10.0)
        self.outline_inspector_width_spinbox.setDecimals(1)
        self.outline_inspector_width_spinbox.setSingleStep(0.1)
        self.outline_inspector_width_spinbox.setFixedWidth(70)
        width_header.addWidget(self.outline_inspector_width_spinbox)
        layout.addLayout(width_header)

        self.outline_inspector_width_slider = QtWidgets.QSlider(
            QtCore.Qt.Orientation.Horizontal,
            page,
        )
        self.outline_inspector_width_slider.setRange(5, 100)
        layout.addWidget(self.outline_inspector_width_slider)
        self.outline_inspector_width_slider.valueChanged.connect(
            self._sync_outline_width_from_slider
        )
        self.outline_inspector_width_slider.sliderReleased.connect(
            self._commit_outline_inspector
        )
        self.outline_inspector_width_spinbox.valueChanged.connect(
            self._sync_outline_width_from_spinbox
        )
        self.outline_inspector_width_spinbox.editingFinished.connect(
            self._commit_outline_inspector
        )

        preset_label = QtWidgets.QLabel(self.tr("Preset colors"), page)
        layout.addWidget(preset_label)
        outline_preset_grid = QtWidgets.QGridLayout()
        outline_preset_grid.setContentsMargins(0, 0, 0, 0)
        outline_preset_grid.setHorizontalSpacing(6)
        outline_preset_grid.setVerticalSpacing(6)
        self.outline_preset_color_buttons = []
        outline_preset_colors = (
            "#000000", "#ffffff", "#5f6368", "#9aa0a6", "#d13655", "#ff3b30", "#ff9500",
            "#ffcc00", "#34c759", "#00b894", "#00c7be", "#007aff", "#5856d6", "#af52de",
            "#ff2d55", "#8b4513", "#f5deb3", "#7f8c8d", "#2c3e50", "#f1c40f", "#e67e22",
        )
        for index, colour_name in enumerate(outline_preset_colors):
            preset = QtWidgets.QToolButton(page)
            preset.setObjectName("outlinePresetColor")
            preset.setFixedSize(28, 24)
            preset.setToolTip(colour_name.upper())
            preset.setStyleSheet(
                f"QToolButton {{ background: {colour_name};"
                " border: 1px solid rgba(127,127,127,150); border-radius: 5px; }}"
            )
            preset.clicked.connect(
                lambda _checked=False, value=colour_name:
                    self._set_outline_preset_colour(value)
            )
            self.outline_preset_color_buttons.append(preset)
            outline_preset_grid.addWidget(preset, index // 7, index % 7)
        layout.addLayout(outline_preset_grid)
        layout.addStretch()

        try:
            width = float(self.outline_width_dropdown.currentText())
        except (TypeError, ValueError):
            width = 1.0
        self.set_outline_inspector_values(outline_colour, width)
        return page

    def _set_outline_preset_colour(self, colour_name: str) -> None:
        colour = QColor(colour_name)
        if not colour.isValid():
            return
        self.outline_inspector_picker.setCurrentColor(colour)
        self._preview_outline_inspector_colour(colour)
        self._commit_outline_inspector()

    def set_outline_inspector_values(self, colour, width) -> None:
        if not hasattr(self, "outline_inspector_picker"):
            return
        colour = QColor(colour or "#000000")
        if not colour.isValid():
            colour = QColor("#000000")
        try:
            width = max(0.5, min(10.0, float(width)))
        except (TypeError, ValueError):
            width = 1.0
        self._outline_inspector_syncing = True
        try:
            self.outline_inspector_picker.setCurrentColor(colour)
            self.outline_inspector_width_spinbox.setValue(width)
            self.outline_inspector_width_slider.setValue(round(width * 10))
        finally:
            self._outline_inspector_syncing = False

    def _preview_outline_inspector_colour(self, colour: QColor) -> None:
        if self._outline_inspector_syncing or not colour.isValid():
            return
        self.outline_font_color_button.setProperty(
            "selected_color",
            colour.name(QColor.NameFormat.HexRgb),
        )
        self.outline_font_color_button.setStyleSheet(
            f"background-color: {colour.name()}; border: none; border-radius: 5px;"
        )
        self.refresh_outline_toolbar_button()

    def _sync_outline_width_from_slider(self, value: int) -> None:
        if self._outline_inspector_syncing:
            return
        with QtCore.QSignalBlocker(self.outline_inspector_width_spinbox):
            self.outline_inspector_width_spinbox.setValue(value / 10.0)

    def _sync_outline_width_from_spinbox(self, value: float) -> None:
        if self._outline_inspector_syncing:
            return
        with QtCore.QSignalBlocker(self.outline_inspector_width_slider):
            self.outline_inspector_width_slider.setValue(round(value * 10.0))

    def _commit_outline_inspector(self) -> None:
        if self._outline_inspector_syncing:
            return
        colour = self.outline_inspector_picker.currentColor()
        width = self.outline_inspector_width_spinbox.value()
        self._preview_outline_inspector_colour(colour)
        with QtCore.QSignalBlocker(self.outline_width_dropdown):
            self.outline_width_dropdown.setCurrentText(f"{width:g}")
        if (
            hasattr(self, "text_ctrl")
            and self.outline_checkbox.isChecked()
            and self.image_viewer.get_selected_text_items()
        ):
            self.text_ctrl.apply_outline_style(colour, width)

    def handle_outline_toolbar_clicked(self, checked: bool) -> None:
        if checked:
            self.set_outline_inspector_values(
                self.outline_font_color_button.property("selected_color"),
                self.outline_width_dropdown.currentText(),
            )
            self.show_text_format_section("outline")
        else:
            self.show_main_right_panel()

    def _build_fill_inspector_page(self) -> QtWidgets.QWidget:
        from app.ui.text_fill_dialog import GradientStopBar, TextFillDialog

        page = self._new_text_format_page()
        layout = page.layout()
        self._fill_inspector_syncing = False
        self._fill_inspector_applying = False
        self._fill_inspector_style = TextFillDialog._normalise_style(
            self.block_font_color_button.property("fill_style")
        )

        modes = QtWidgets.QHBoxLayout()
        self.inspector_solid_button = QtWidgets.QToolButton(page)
        self.inspector_solid_button.setText(self.tr("Solid color"))
        self.inspector_solid_button.setCheckable(True)
        self.inspector_gradient_button = QtWidgets.QToolButton(page)
        self.inspector_gradient_button.setText(self.tr("Gradient"))
        self.inspector_gradient_button.setCheckable(True)
        self.inspector_fill_mode_group = QtWidgets.QButtonGroup(page)
        self.inspector_fill_mode_group.setExclusive(True)
        self.inspector_fill_mode_group.addButton(self.inspector_solid_button, 0)
        self.inspector_fill_mode_group.addButton(self.inspector_gradient_button, 1)
        for button in (self.inspector_solid_button, self.inspector_gradient_button):
            button.setObjectName("formatModeButton")
            button.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
            modes.addWidget(button)
        layout.addLayout(modes)

        self.inspector_colour_picker = CompactColorPicker(
            self._fill_inspector_style.get("color", "#ff000000"),
            page,
        )
        self.inspector_colour_picker.currentColorChanged.connect(
            self._on_fill_picker_changed
        )
        self.inspector_colour_picker.editingFinished.connect(
            self._commit_fill_inspector
        )
        layout.addWidget(self.inspector_colour_picker)

        self.inspector_fill_stack = QtWidgets.QStackedWidget(page)

        solid_page = QtWidgets.QWidget()
        solid_page.setObjectName("textFormatSubPage")
        solid_layout = QtWidgets.QVBoxLayout(solid_page)
        solid_layout.setContentsMargins(0, 4, 0, 4)
        solid_layout.setSpacing(9)
        solid_row = QtWidgets.QHBoxLayout()
        solid_row.addWidget(QtWidgets.QLabel(self.tr("Color")))
        self.inspector_solid_swatch = QtWidgets.QPushButton(solid_page)
        self.inspector_solid_swatch.setObjectName("formatColorSwatch")
        self.inspector_solid_swatch.setFixedSize(42, 32)
        self.inspector_solid_swatch.clicked.connect(
            lambda: self._choose_inspector_colour("solid")
        )
        self.inspector_solid_hex = QtWidgets.QLineEdit(solid_page)
        self.inspector_solid_hex.setPlaceholderText("#RRGGBB")
        self.inspector_solid_hex.editingFinished.connect(
            self._update_solid_from_inspector
        )
        solid_row.addWidget(self.inspector_solid_swatch)
        solid_row.addWidget(self.inspector_solid_hex, 1)
        solid_layout.addLayout(solid_row)
        solid_alpha_header = QtWidgets.QHBoxLayout()
        solid_alpha_header.addWidget(QtWidgets.QLabel(self.tr("Opacity")))
        self.inspector_solid_alpha_label = QtWidgets.QLabel("100%")
        solid_alpha_header.addStretch()
        solid_alpha_header.addWidget(self.inspector_solid_alpha_label)
        solid_layout.addLayout(solid_alpha_header)
        self.inspector_solid_alpha = QtWidgets.QSlider(
            QtCore.Qt.Orientation.Horizontal, solid_page
        )
        self.inspector_solid_alpha.setRange(0, 100)
        self.inspector_solid_alpha.valueChanged.connect(
            lambda value: self.inspector_solid_alpha_label.setText(f"{value}%")
        )
        self.inspector_solid_alpha.valueChanged.connect(
            self._update_solid_alpha_live
        )
        self.inspector_solid_alpha.sliderReleased.connect(
            self._commit_fill_inspector
        )
        solid_layout.addWidget(self.inspector_solid_alpha)
        solid_layout.addStretch()
        self.inspector_fill_stack.addWidget(solid_page)

        gradient_page = QtWidgets.QWidget()
        gradient_page.setObjectName("textFormatSubPage")
        gradient_layout = QtWidgets.QVBoxLayout(gradient_page)
        gradient_layout.setContentsMargins(0, 4, 0, 4)
        gradient_layout.setSpacing(8)
        gradient_layout.addWidget(QtWidgets.QLabel(self.tr("Gradient style")))
        gradient_style_row = QtWidgets.QHBoxLayout()
        gradient_style_row.setContentsMargins(0, 0, 0, 0)
        gradient_style_row.setSpacing(5)
        self.inspector_gradient_style_group = QtWidgets.QButtonGroup(gradient_page)
        self.inspector_gradient_style_group.setExclusive(True)
        self.inspector_gradient_style_buttons: dict[
            str, _GradientStylePreviewButton
        ] = {}
        self._inspector_gradient_style_keys = []
        for index, (key, label) in enumerate(TextFillDialog._STYLE_LABELS):
            preview = _GradientStylePreviewButton(key, gradient_page)
            preview.setToolTip(self.tr(label))
            preview.setAccessibleName(self.tr(label))
            self.inspector_gradient_style_group.addButton(preview, index)
            self.inspector_gradient_style_buttons[key] = preview
            self._inspector_gradient_style_keys.append(key)
            gradient_style_row.addWidget(preview, 1)
        self.inspector_gradient_style_group.idClicked.connect(
            self._select_gradient_style_from_inspector
        )
        gradient_layout.addLayout(gradient_style_row)
        self.inspector_gradient_bar = GradientStopBar(gradient_page)
        self.inspector_gradient_bar.stopActivated.connect(
            self._select_inspector_gradient_stop
        )
        self.inspector_gradient_bar.stopAddRequested.connect(
            self._add_inspector_gradient_stop_at
        )
        self.inspector_gradient_bar.stopMoved.connect(
            self._move_inspector_gradient_stop
        )
        self.inspector_gradient_bar.stopMoveFinished.connect(
            self._finish_inspector_gradient_stop_move
        )
        gradient_layout.addWidget(self.inspector_gradient_bar)
        stop_header = QtWidgets.QHBoxLayout()
        stop_header.addWidget(QtWidgets.QLabel(self.tr("Gradient stops")))
        stop_header.addStretch()
        add_stop = QtWidgets.QToolButton(gradient_page)
        add_stop.setObjectName("gradientStopAdd")
        add_stop.setText("+")
        add_stop.setFixedSize(26, 26)
        add_stop.setToolTip(self.tr("Add stop"))
        add_stop.clicked.connect(self._add_inspector_gradient_stop)
        stop_header.addWidget(add_stop)
        gradient_layout.addLayout(stop_header)
        self.inspector_gradient_stops = QtWidgets.QListWidget(gradient_page)
        self.inspector_gradient_stops.setObjectName("gradientStopList")
        self.inspector_gradient_stops.setMinimumHeight(86)
        self.inspector_gradient_stops.setMaximumHeight(158)
        self.inspector_gradient_stops.setSpacing(3)
        self.inspector_gradient_stops.currentRowChanged.connect(
            self._load_inspector_gradient_stop
        )
        gradient_layout.addWidget(self.inspector_gradient_stops)
        gradient_layout.addStretch()
        self.inspector_fill_stack.addWidget(gradient_page)
        layout.addWidget(self.inspector_fill_stack, 1)

        apply_button = QtWidgets.QPushButton(self.tr("Apply fill"), page)
        apply_button.setObjectName("formatApplyButton")
        apply_button.clicked.connect(self._commit_fill_inspector)
        layout.addWidget(apply_button)

        self.inspector_fill_mode_group.idClicked.connect(
            self._set_inspector_fill_mode
        )
        self.set_fill_inspector_style(self._fill_inspector_style)
        return page

    def show_text_format_section(
        self,
        section: str,
        require_selection: bool = True,
    ) -> None:
        page = getattr(self, "text_format_sections", {}).get(section)
        if page is None:
            return
        if require_selection and not self.image_viewer.get_selected_text_items():
            return
        if section == "font":
            self.refresh_font_inspector()
        self.text_format_title.setText(
            self.text_format_section_titles.get(section, self.tr("Text format"))
        )
        self.text_format_stack.setCurrentWidget(page)
        if hasattr(self, "right_panel_stack"):
            self.right_panel_stack.setCurrentWidget(self.text_format_panel)

    def set_fill_inspector_style(self, style: dict | None) -> None:
        if not hasattr(self, "inspector_fill_stack"):
            return
        from app.ui.text_fill_dialog import TextFillDialog

        self._fill_inspector_style = TextFillDialog._normalise_style(style)
        self._fill_inspector_syncing = True
        try:
            mode = self._fill_inspector_style.get("mode", "solid")
            self.inspector_solid_button.setChecked(mode == "solid")
            self.inspector_gradient_button.setChecked(mode == "gradient")
            self.inspector_fill_stack.setCurrentIndex(0 if mode == "solid" else 1)

            solid = QColor(self._fill_inspector_style.get("color", "#ff000000"))
            self._set_inspector_swatch(self.inspector_solid_swatch, solid)
            self.inspector_solid_hex.setText(solid.name().upper())
            self.inspector_solid_alpha.setValue(round(solid.alphaF() * 100))
            self.inspector_colour_picker.setCurrentColor(solid)

            gradient = self._fill_inspector_style.get("gradient", {})
            style_key = gradient.get("style", "linear_90")
            style_button = self.inspector_gradient_style_buttons.get(style_key)
            if style_button is None:
                style_button = self.inspector_gradient_style_buttons["linear_90"]
            style_button.setChecked(True)
            self._refresh_inspector_gradient_stops(0)
            self._refresh_gradient_style_previews()
        finally:
            self._fill_inspector_syncing = False

    @staticmethod
    def _set_inspector_swatch(button: QtWidgets.QPushButton, colour: QColor) -> None:
        button.setStyleSheet(
            f"background-color: {colour.name(QColor.NameFormat.HexArgb)};"
            " border: 1px solid rgba(127,127,127,120); border-radius: 6px;"
        )

    def _set_inspector_fill_mode(self, mode_id: int) -> None:
        if self._fill_inspector_syncing:
            return
        mode = "solid" if mode_id == 0 else "gradient"
        self._fill_inspector_style["mode"] = mode
        self.inspector_fill_stack.setCurrentIndex(mode_id)
        if mode == "solid":
            colour = QColor(self._fill_inspector_style.get("color", "#ff000000"))
        else:
            row = max(0, self.inspector_gradient_stops.currentRow())
            stop = self._fill_inspector_style["gradient"]["stops"][row]
            colour = QColor(stop.get("color", "#ff000000"))
            colour.setAlpha(int(stop.get("alpha", colour.alpha())))
        self.inspector_colour_picker.setCurrentColor(colour)
        self._commit_fill_inspector()

    def _choose_inspector_colour(self, target: str) -> None:
        if target == "solid":
            current = QColor(self._fill_inspector_style.get("color", "#ff000000"))
        else:
            row = self.inspector_gradient_stops.currentRow()
            stops = self._fill_inspector_style["gradient"]["stops"]
            if row < 0 or row >= len(stops):
                return
            current = QColor(stops[row].get("color", "#ff000000"))
            current.setAlpha(int(stops[row].get("alpha", current.alpha())))
        self.inspector_colour_picker.setCurrentColor(current)
        self.inspector_colour_picker.setFocus(
            QtCore.Qt.FocusReason.MouseFocusReason
        )

    def _on_fill_picker_changed(self, colour: QColor) -> None:
        if self._fill_inspector_syncing or not colour.isValid():
            return
        mode = self._fill_inspector_style.get("mode", "solid")
        if mode == "solid":
            colour.setAlpha(round(self.inspector_solid_alpha.value() * 2.55))
            self._fill_inspector_style["color"] = colour.name(
                QColor.NameFormat.HexArgb
            )
            self._set_inspector_swatch(self.inspector_solid_swatch, colour)
            self.inspector_solid_hex.setText(colour.name().upper())
            self._preview_fill_inspector()
            return
        row = self.inspector_gradient_stops.currentRow()
        stops = self._fill_inspector_style["gradient"]["stops"]
        if row < 0 or row >= len(stops):
            return
        stop = stops[row]
        colour.setAlpha(int(stop.get("alpha", colour.alpha())))
        stop["color"] = colour.name(QColor.NameFormat.HexArgb)
        stop["alpha"] = colour.alpha()
        row_widget = self._gradient_stop_row_widget(row)
        if row_widget is not None:
            row_widget.set_stop(stop)
        self.inspector_gradient_bar.set_stops(stops, row)
        self._refresh_gradient_style_previews()
        self._preview_fill_inspector()

    def _update_solid_from_inspector(self) -> None:
        if self._fill_inspector_syncing:
            return
        colour = QColor(self.inspector_solid_hex.text().strip())
        if not colour.isValid():
            colour = QColor(self._fill_inspector_style.get("color", "#ff000000"))
        colour.setAlpha(round(self.inspector_solid_alpha.value() * 2.55))
        self._fill_inspector_style["color"] = colour.name(
            QColor.NameFormat.HexArgb
        )
        self._set_inspector_swatch(self.inspector_solid_swatch, colour)
        self.inspector_solid_hex.setText(colour.name().upper())
        self.inspector_colour_picker.setCurrentColor(colour)

    def _update_solid_alpha_live(self, value: int) -> None:
        if self._fill_inspector_syncing:
            return
        colour = QColor(self._fill_inspector_style.get("color", "#ff000000"))
        colour.setAlpha(round(max(0, min(100, int(value))) * 2.55))
        self._fill_inspector_style["color"] = colour.name(
            QColor.NameFormat.HexArgb
        )
        self._set_inspector_swatch(self.inspector_solid_swatch, colour)
        self._preview_fill_inspector()

    def _gradient_stop_row_widget(self, row: int) -> _GradientStopRow | None:
        item = self.inspector_gradient_stops.item(row)
        if item is None:
            return None
        widget = self.inspector_gradient_stops.itemWidget(item)
        return widget if isinstance(widget, _GradientStopRow) else None

    def _refresh_inspector_gradient_stops(self, selected: int = 0) -> None:
        stops = self._fill_inspector_style["gradient"]["stops"]
        self.inspector_gradient_stops.blockSignals(True)
        self.inspector_gradient_stops.clear()
        for stop in stops:
            item = QtWidgets.QListWidgetItem()
            item.setSizeHint(QtCore.QSize(0, 36))
            self.inspector_gradient_stops.addItem(item)
            row_widget = _GradientStopRow(stop, self.inspector_gradient_stops)
            row_widget.activated.connect(
                lambda target=item: self.inspector_gradient_stops.setCurrentItem(
                    target
                )
            )
            row_widget.positionChanged.connect(
                lambda value, target=item: self._update_gradient_stop_row(
                    target, "position", value
                )
            )
            row_widget.colourChanged.connect(
                lambda colour, target=item: self._update_gradient_stop_row(
                    target, "color", colour
                )
            )
            row_widget.opacityChanged.connect(
                lambda value, target=item: self._update_gradient_stop_row(
                    target, "opacity", value
                )
            )
            row_widget.editingFinished.connect(
                lambda target=item: self._finish_gradient_stop_row_edit(target)
            )
            row_widget.removeRequested.connect(
                lambda target=item: self._remove_gradient_stop_item(target)
            )
            row_widget.remove_button.setEnabled(len(stops) > 2)
            self.inspector_gradient_stops.setItemWidget(item, row_widget)
        selected = max(0, min(selected, len(stops) - 1))
        self.inspector_gradient_stops.setCurrentRow(selected)
        self.inspector_gradient_stops.blockSignals(False)
        self._load_inspector_gradient_stop(selected)
        self.inspector_gradient_bar.set_stops(stops, selected)
        self._refresh_gradient_style_previews()

    def _load_inspector_gradient_stop(self, row: int) -> None:
        stops = self._fill_inspector_style["gradient"]["stops"]
        if row < 0 or row >= len(stops):
            return
        stop = stops[row]
        colour = QColor(stop.get("color", "#ff000000"))
        colour.setAlpha(int(stop.get("alpha", colour.alpha())))
        self._fill_inspector_syncing = True
        try:
            for index in range(self.inspector_gradient_stops.count()):
                row_widget = self._gradient_stop_row_widget(index)
                if row_widget is not None:
                    row_widget.set_selected(index == row)
            if self._fill_inspector_style.get("mode") == "gradient":
                self.inspector_colour_picker.setCurrentColor(colour)
            self.inspector_gradient_bar.set_selected_stop(row)
        finally:
            self._fill_inspector_syncing = False

    def _update_gradient_from_inspector(self, style_index: int | None = None) -> None:
        if self._fill_inspector_syncing:
            return
        if style_index is None:
            checked = self.inspector_gradient_style_group.checkedButton()
            style_key = getattr(checked, "style_key", "linear_90")
        elif 0 <= style_index < len(self._inspector_gradient_style_keys):
            style_key = self._inspector_gradient_style_keys[style_index]
        else:
            style_key = "linear_90"
        self._fill_inspector_style["gradient"]["style"] = style_key
        self._refresh_gradient_style_previews()

    def _select_gradient_style_from_inspector(self, style_index: int) -> None:
        self._update_gradient_from_inspector(style_index)
        self._commit_fill_inspector()

    def _refresh_gradient_style_previews(self) -> None:
        if not hasattr(self, "inspector_gradient_style_buttons"):
            return
        gradient = self._fill_inspector_style.get("gradient", {})
        stops = gradient.get("stops", [])
        selected_style = gradient.get("style", "linear_90")
        for style_key, button in self.inspector_gradient_style_buttons.items():
            button.set_gradient_stops(stops)
            if button.isChecked() != (style_key == selected_style):
                with QtCore.QSignalBlocker(button):
                    button.setChecked(style_key == selected_style)

    def _update_gradient_stop_row(
        self,
        item: QtWidgets.QListWidgetItem,
        field: str,
        value,
    ) -> None:
        if self._fill_inspector_syncing:
            return
        row = self.inspector_gradient_stops.row(item)
        stops = self._fill_inspector_style["gradient"]["stops"]
        if row < 0 or row >= len(stops):
            return
        if self.inspector_gradient_stops.currentRow() != row:
            self.inspector_gradient_stops.setCurrentRow(row)
        stop = stops[row]
        if field == "position":
            stop["position"] = max(0, min(100, int(value)))
        elif field == "opacity":
            stop["alpha"] = round(max(0, min(100, int(value))) * 2.55)
            colour = QColor(stop.get("color", "#ff000000"))
            colour.setAlpha(stop["alpha"])
            stop["color"] = colour.name(QColor.NameFormat.HexArgb)
        elif field == "color":
            colour = QColor(value)
            if not colour.isValid():
                return
            stop["color"] = colour.name(QColor.NameFormat.HexArgb)
            stop["alpha"] = colour.alpha()
        else:
            return
        self.inspector_gradient_bar.set_stops(stops, row)
        self._refresh_gradient_style_previews()
        self._preview_fill_inspector()

    def _finish_gradient_stop_row_edit(
        self,
        item: QtWidgets.QListWidgetItem,
    ) -> None:
        row = self.inspector_gradient_stops.row(item)
        stops = self._fill_inspector_style["gradient"]["stops"]
        if row < 0 or row >= len(stops):
            return
        stop = stops[row]
        stops.sort(key=lambda value: int(value.get("position", 0)))
        self._refresh_inspector_gradient_stops(stops.index(stop))
        self._commit_fill_inspector()

    def _remove_gradient_stop_item(
        self,
        item: QtWidgets.QListWidgetItem,
    ) -> None:
        row = self.inspector_gradient_stops.row(item)
        if row < 0:
            return
        self.inspector_gradient_stops.setCurrentRow(row)
        self._remove_inspector_gradient_stop()

    def _move_inspector_gradient_stop(self, row: int, position: int) -> None:
        stops = self._fill_inspector_style["gradient"]["stops"]
        if row < 0 or row >= len(stops):
            return
        stops[row]["position"] = max(0, min(100, int(position)))
        if self.inspector_gradient_stops.currentRow() != row:
            self.inspector_gradient_stops.setCurrentRow(row)
        row_widget = self._gradient_stop_row_widget(row)
        if row_widget is not None:
            row_widget.set_stop(stops[row])
        self._refresh_gradient_style_previews()
        self._preview_fill_inspector()

    def _finish_inspector_gradient_stop_move(
        self,
        row: int,
        position: int,
    ) -> None:
        stops = self._fill_inspector_style["gradient"]["stops"]
        if row < 0 or row >= len(stops):
            return
        stop = stops[row]
        stop["position"] = max(0, min(100, int(position)))
        stops.sort(key=lambda value: int(value.get("position", 0)))
        self._refresh_inspector_gradient_stops(stops.index(stop))
        self._commit_fill_inspector()

    def _select_inspector_gradient_stop(self, row: int) -> None:
        if 0 <= row < self.inspector_gradient_stops.count():
            self.inspector_gradient_stops.setCurrentRow(row)

    def _add_inspector_gradient_stop_at(self, position: int) -> None:
        stops = self._fill_inspector_style["gradient"]["stops"]
        current_row = self.inspector_gradient_stops.currentRow()
        if 0 <= current_row < len(stops):
            source = stops[current_row]
        else:
            source = stops[0]
        colour = QColor(source.get("color", "#ff000000"))
        stop = {
            "position": max(0, min(100, int(position))),
            "color": colour.name(QColor.NameFormat.HexArgb),
            "alpha": int(source.get("alpha", colour.alpha())),
        }
        stops.append(stop)
        stops.sort(key=lambda value: int(value.get("position", 0)))
        self._refresh_inspector_gradient_stops(stops.index(stop))
        self._commit_fill_inspector()

    def _add_inspector_gradient_stop(self) -> None:
        stops = self._fill_inspector_style["gradient"]["stops"]
        ordered = sorted(stops, key=lambda stop: int(stop.get("position", 0)))
        left, right = max(
            zip(ordered, ordered[1:]),
            key=lambda pair: int(pair[1].get("position", 0))
            - int(pair[0].get("position", 0)),
        )
        position = (
            int(left.get("position", 0)) + int(right.get("position", 100))
        ) // 2
        colour = QColor(left.get("color", "#ff000000"))
        stop = {
            "position": position,
            "color": colour.name(QColor.NameFormat.HexArgb),
            "alpha": int(left.get("alpha", colour.alpha())),
        }
        stops.append(stop)
        stops.sort(key=lambda value: int(value.get("position", 0)))
        self._refresh_inspector_gradient_stops(stops.index(stop))
        self._commit_fill_inspector()

    def _remove_inspector_gradient_stop(self) -> None:
        stops = self._fill_inspector_style["gradient"]["stops"]
        row = self.inspector_gradient_stops.currentRow()
        if len(stops) <= 2 or row < 0:
            return
        stops.pop(row)
        self._refresh_inspector_gradient_stops(max(0, row - 1))
        self._commit_fill_inspector()

    def _commit_fill_inspector(self) -> None:
        if self._fill_inspector_syncing or self._fill_inspector_applying:
            return
        if self._fill_inspector_style.get("mode", "solid") == "solid":
            self._update_solid_from_inspector()
        else:
            self._update_gradient_from_inspector()
        if hasattr(self, "text_ctrl"):
            self._fill_inspector_applying = True
            try:
                style = copy.deepcopy(self._fill_inspector_style)
                if hasattr(self.text_ctrl, "commit_text_fill_preview"):
                    self.text_ctrl.commit_text_fill_preview(style)
                else:
                    self.text_ctrl.apply_text_fill_style(style)
            finally:
                self._fill_inspector_applying = False

    def _preview_fill_inspector(self) -> None:
        if (
            self._fill_inspector_syncing
            or self._fill_inspector_applying
            or not hasattr(self, "text_ctrl")
        ):
            return
        self._fill_inspector_applying = True
        try:
            style = copy.deepcopy(self._fill_inspector_style)
            if hasattr(self.text_ctrl, "preview_text_fill_style"):
                self.text_ctrl.preview_text_fill_style(style)
            else:
                self.text_ctrl.apply_text_fill_style(style)
        finally:
            self._fill_inspector_applying = False

    def _add_text_bar_separator(self) -> None:
        separator = QtWidgets.QFrame(self.text_options_bar)
        separator.setObjectName("textBarSeparator")
        separator.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        separator.setFixedSize(1, 24)
        self.text_options_layout.addWidget(separator)

    def set_onomatopoeia_mode_enabled(self, enabled: bool) -> None:
        self.onomatopoeia_mode_enabled = bool(enabled)
        self._refresh_onomatopoeia_toggle()
        settings = QSettings("ComicLabs", "ComicTranslate")
        settings.beginGroup("workflow")
        settings.setValue("onomatopoeia_mode", bool(enabled))
        settings.endGroup()
        settings.sync()

    def _refresh_onomatopoeia_toggle(self) -> None:
        if not hasattr(self, "onomatopoeia_toggle"):
            return
        status = self.tr("active") if self.onomatopoeia_toggle.isChecked() else self.tr("inactive")
        self.onomatopoeia_toggle.setToolTip(
            self.tr(
                "Onomatopoeia mode: {status}. Complements the selected translator "
                "without replacing the current engines."
            ).format(status=status)
        )

    def set_text_selection_controls_enabled(self, enabled: bool) -> None:
        for control in getattr(self, "_selection_only_text_controls", ()):
            control.setEnabled(bool(enabled))
        # Page-level actions remain available without a translated text box.
        if hasattr(self, "quick_text_button"):
            self.quick_text_button.setEnabled(True)
        if hasattr(self, "watermark_button"):
            self.watermark_button.setEnabled(True)

    def _sync_outline_toolbar_button(self, enabled: bool) -> None:
        if not hasattr(self, "outline_toolbar_button"):
            return
        with QtCore.QSignalBlocker(self.outline_toolbar_button):
            self.outline_toolbar_button.setChecked(bool(enabled))
        self.refresh_outline_toolbar_button()

    def refresh_outline_toolbar_button(self) -> None:
        """Render an unfilled A with the active outline colour beneath it."""
        if not hasattr(self, "outline_toolbar_button"):
            return
        colour = QColor(
            self.outline_font_color_button.property("selected_color") or "#000000"
        )
        if not colour.isValid():
            colour = QColor("#000000")
        foreground = QColor(
            "#f1f1f5" if getattr(self, "_is_dark_theme", False) else "#26272e"
        )
        pixmap = QtGui.QPixmap(28, 28)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(
            QtGui.QPen(
                foreground,
                1.35,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
                QtCore.Qt.PenJoinStyle.RoundJoin,
            )
        )
        # Draw the glyph geometrically so it remains a true outlined A even
        # when the operating system does not expose the requested UI font.
        painter.drawLine(QtCore.QPointF(7.5, 20), QtCore.QPointF(14, 4.5))
        painter.drawLine(QtCore.QPointF(14, 4.5), QtCore.QPointF(20.5, 20))
        painter.drawLine(QtCore.QPointF(10.2, 14), QtCore.QPointF(17.8, 14))
        painter.setPen(
            QtGui.QPen(
                colour,
                3.0,
                QtCore.Qt.PenStyle.SolidLine,
                QtCore.Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawLine(QtCore.QPointF(6, 24), QtCore.QPointF(22, 24))
        painter.end()
        self.outline_toolbar_button.setIcon(QtGui.QIcon(pixmap))

    def set_font_weight_menu_value(self, weight) -> None:
        try:
            weight = int(weight)
        except (TypeError, ValueError):
            weight = 400
        if self.font_weight_actions:
            weight = min(self.font_weight_actions, key=lambda value: abs(value - weight))
            action = self.font_weight_actions[weight]
            action.setChecked(True)
            self.font_weight_button.setToolTip(
                f"{self.tr('Font weight')}: {action.text()}"
            )
            self.set_font_weight_button_active(weight >= 600)

    def _apply_font_weight_from_toolbar(self, weight: int) -> None:
        if hasattr(self, "text_ctrl"):
            self.text_ctrl.on_font_weight_change(int(weight))
        else:
            self.set_font_weight_menu_value(weight)

    def _handle_font_weight_toolbar_clicked(self) -> None:
        if bool(self.font_weight_button.property("weightActive")):
            self._apply_font_weight_from_toolbar(400)
            return
        popup_pos = self.font_weight_button.mapToGlobal(
            QtCore.QPoint(0, self.font_weight_button.height() + 3)
        )
        self.font_weight_menu.popup(popup_pos)

    def set_font_weight_button_active(self, active: bool) -> None:
        if not hasattr(self, "font_weight_button"):
            return
        active = bool(active)
        if self.font_weight_button.property("weightActive") == active:
            return
        self.font_weight_button.setProperty("weightActive", active)
        self.font_weight_button.style().unpolish(self.font_weight_button)
        self.font_weight_button.style().polish(self.font_weight_button)
        self.font_weight_button.update()

    def adjust_font_size(self, delta: int) -> None:
        try:
            current = float(self.font_size_dropdown.currentText())
        except (TypeError, ValueError):
            current = 12.0
        value = max(1.0, min(999.0, current + int(delta)))
        text = str(int(value)) if value.is_integer() else f"{value:g}"
        self.font_size_dropdown.setCurrentText(text)
        self.font_size_dropdown.lineEdit().selectAll()

    def set_line_spacing_menu_value(self, value, trigger: bool = False) -> None:
        try:
            numeric = max(0.5, min(3.0, float(value)))
        except (TypeError, ValueError):
            numeric = 1.0
        with QtCore.QSignalBlocker(self.line_spacing_spinbox):
            self.line_spacing_spinbox.setValue(numeric)
        with QtCore.QSignalBlocker(self.line_spacing_slider):
            self.line_spacing_slider.setValue(round(numeric * 100.0))
        self._update_typography_spacing_tooltip()
        text = f"{numeric:g}"
        if trigger and self.line_spacing_dropdown.currentText() != text:
            self.line_spacing_dropdown.setCurrentText(text)

    def set_letter_spacing_control_value(self, value) -> None:
        try:
            numeric = max(-50.0, min(200.0, float(value)))
        except (TypeError, ValueError):
            numeric = 0.0
        with QtCore.QSignalBlocker(self.letter_spacing_spinbox):
            self.letter_spacing_spinbox.setValue(numeric)
        with QtCore.QSignalBlocker(self.letter_spacing_slider):
            self.letter_spacing_slider.setValue(round(numeric))
        self._update_typography_spacing_tooltip()

    def _sync_letter_spacing_slider(self, value) -> None:
        with QtCore.QSignalBlocker(self.letter_spacing_slider):
            self.letter_spacing_slider.setValue(round(float(value)))
        self._update_typography_spacing_tooltip()

    def _sync_line_spacing_controls(self, value) -> None:
        numeric = max(0.5, min(3.0, float(value)))
        with QtCore.QSignalBlocker(self.line_spacing_slider):
            self.line_spacing_slider.setValue(round(numeric * 100.0))
        text = f"{numeric:g}"
        if self.line_spacing_dropdown.currentText() != text:
            self.line_spacing_dropdown.setCurrentText(text)
        self._update_typography_spacing_tooltip()

    def _update_typography_spacing_tooltip(self) -> None:
        if not hasattr(self, "line_spacing_button"):
            return
        letter_value = (
            self.letter_spacing_spinbox.value()
            if hasattr(self, "letter_spacing_spinbox") else 0.0
        )
        line_value = (
            self.line_spacing_spinbox.value()
            if hasattr(self, "line_spacing_spinbox") else 1.0
        )
        self.line_spacing_button.setToolTip(
            self.tr("Letter spacing")
            + f": {letter_value:g}% · "
            + self.tr("Line spacing")
            + f": {line_value:g}"
        )

    def set_text_opacity_preview(self, value) -> None:
        value = max(0, min(100, int(value)))
        self.text_opacity_button.setToolTip(
            f"{self.tr('Transparency')}: {value}%"
        )
        self.text_opacity_value_label.setText(f"{value}%")

    def _configure_workspace_scrollbars(
        self,
        root: QtWidgets.QWidget,
        is_dark: bool,
    ) -> None:
        """Keep scrollbars unobtrusive until the pointer reaches their hit area."""
        handle = "#4C5D70" if is_dark else "#9a9ca5"
        handle_hover = "#AAB4C1" if is_dark else "#666872"
        scroll_style = f"""
            QScrollBar {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                width: 10px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {handle};
                min-height: 28px;
                border-radius: 2px;
                margin: 0 3px;
            }}
            QScrollBar::handle:vertical:hover,
            QScrollBar[expanded="true"]::handle:vertical {{
                background: {handle_hover};
                border-radius: 5px;
                margin: 0;
            }}
            QScrollBar:horizontal {{
                height: 10px;
                margin: 0;
            }}
            QScrollBar::handle:horizontal {{
                background: {handle};
                min-width: 28px;
                border-radius: 2px;
                margin: 3px 0;
            }}
            QScrollBar::handle:horizontal:hover,
            QScrollBar[expanded="true"]::handle:horizontal {{
                background: {handle_hover};
                border-radius: 5px;
                margin: 0;
            }}
            QScrollBar::add-line,
            QScrollBar::sub-line {{
                width: 0;
                height: 0;
                background: transparent;
                border: none;
            }}
            QScrollBar::add-page,
            QScrollBar::sub-page {{
                background: transparent;
            }}
        """
        if not hasattr(self, "_scrollbar_proximity_filter"):
            self._scrollbar_proximity_filter = _ScrollBarProximityFilter(root)
        for scrollbar in root.findChildren(QtWidgets.QScrollBar):
            if not scrollbar.property("mukaiProximityFilterInstalled"):
                scrollbar.setProperty("expanded", False)
                scrollbar.installEventFilter(self._scrollbar_proximity_filter)
                scrollbar.setProperty("mukaiProximityFilterInstalled", True)
            scrollbar.setStyleSheet(scroll_style)

    def _apply_workspace_theme(self, is_dark: bool) -> None:
        is_black = bool(is_dark) and getattr(self, "_theme_variant", "") == "black"
        border = "#262626" if is_black else ("#1D2430" if is_dark else "#cfd1d8")
        bar_bg = "#080808" if is_black else ("#0F151E" if is_dark else "#ffffff")
        hover = "#242424" if is_black else ("#1A314F" if is_dark else "#f9e1e7")
        hover_text = "#FFFFFF" if is_dark else "#7d2139"
        active = "#FFFFFF" if is_black else ("#1462A9" if is_dark else "#D13655")
        active_border = "#FFFFFF" if is_black else ("#168FF7" if is_dark else "#D13655")
        active_text = "#000000" if is_black else "#FFFFFF"
        separator = "#1F1F1F" if is_black else ("#1D2430" if is_dark else "#d5d7dd")
        shell_bg = "#000000" if is_black else ("#0B0F19" if is_dark else "#f8f8f9")
        secondary_bg = "#080808" if is_black else ("#141A25" if is_dark else "#ffffff")
        center_bg = "#000000" if is_black else ("#131925" if is_dark else "#ffffff")
        button_bg = "#0A0A0A" if is_black else ("#111722" if is_dark else "transparent")

        if hasattr(self, "inspector_gradient_bar"):
            self.inspector_gradient_bar.apply_theme(is_dark)

        if hasattr(self, "workspace_content_widget"):
            self.workspace_content_widget.setStyleSheet(f"""
                QWidget#workspaceRoot {{
                    background: {shell_bg};
                }}
                QWidget#workflowToolbar {{
                    background: {secondary_bg};
                    border: 1px solid {border};
                    border-radius: 7px;
                }}
                QWidget#workflowToolbar QPushButton {{
                    background: {button_bg};
                }}
                QWidget#editorCenterColumn,
                QStackedWidget#editorCanvasStack {{
                    background: {center_bg};
                }}
                QSplitter#workspaceSplitter {{
                    background: {shell_bg};
                }}
                QSplitter#workspaceSplitter::handle {{
                    background: {border};
                }}
            """)
        self.text_options_bar.setStyleSheet(f"""
            QFrame#textOptionsBar {{
                background: {bar_bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            QFrame#textBarSeparator {{
                background: {separator};
                border: none;
            }}
            QFrame#textOptionsBar QPushButton#textOptionsButton {{
                background: {button_bg}; text-align: center;
                border: none; border-radius: 6px;
                padding: 5px 13px; font-weight: 600;
            }}
            QFrame#textOptionsBar QWidget#textCreationGroup {{
                background: transparent;
                border: none;
            }}
            QFrame#textOptionsBar QToolButton#textBarMenuButton,
            QFrame#textOptionsBar QToolButton#textBarActionButton {{
                background: {button_bg};
                border: none; border-radius: 6px;
                padding: 3px; font-weight: 600;
            }}
            QFrame#textOptionsBar QToolButton#textBarMenuButton::menu-indicator {{
                image: none;
                width: 0px;
                height: 0px;
            }}
            QFrame#textOptionsBar QToolButton#textFormatGlyphButton {{
                background: {button_bg};
                border: none;
                border-radius: 6px;
                padding: 0;
                margin: 0;
                text-align: center;
                font-size: 13px;
                font-weight: 600;
            }}
            QFrame#textOptionsBar QToolButton#textFormatGlyphButton[italicGlyph="true"] {{
                font-size: 17px;
                font-weight: 400;
            }}
            QFrame#textOptionsBar QToolButton#textFormatGlyphButton[weightGlyph="true"] {{
                font-size: 17px;
                font-weight: 800;
            }}
            QFrame#textOptionsBar QToolButton#textFormatGlyphButton:hover {{
                background: {hover};
                color: {hover_text};
            }}
            QFrame#textOptionsBar QToolButton#textFormatGlyphButton:checked {{
                background: {active};
                color: {active_text};
                border: 1px solid {active_border};
            }}
            QFrame#textOptionsBar QToolButton#textFormatGlyphButton[weightActive="true"] {{
                background: {active};
                color: {active_text};
                border: 1px solid {active_border};
            }}
            QFrame#textOptionsBar QToolButton#textBarFramedButton {{
                background: {'#111111' if is_black else ('#161C27' if is_dark else 'transparent')};
                border: 1px solid {border};
                border-radius: 5px;
                padding: 5px 9px;
                text-align: left;
            }}
            QFrame#textOptionsBar QFrame#textSizeControl {{
                background: {'#111111' if is_black else ('#161C27' if is_dark else 'transparent')};
                border: 1px solid {border};
                border-radius: 5px;
            }}
            QFrame#textOptionsBar QToolButton#fontSizeStepButton {{
                background: transparent;
                color: {'#F5F7FA' if is_dark else '#30313a'};
                border: none;
                border-radius: 4px;
                padding: 2px;
                font-size: 15px;
                font-weight: 700;
            }}
            QFrame#textOptionsBar QToolButton#fontSizeStepButton:hover {{
                background: {hover};
                color: {hover_text};
            }}
            QFrame#textOptionsBar QPushButton#textOptionsButton:hover {{
                background: {hover}; border: none;
                color: {hover_text};
            }}
            QFrame#textOptionsBar QToolButton#textBarMenuButton:hover,
            QFrame#textOptionsBar QToolButton#textBarActionButton:hover,
            QFrame#textOptionsBar QToolButton#textBarFramedButton:hover {{
                background: {hover}; color: {hover_text};
            }}
            QFrame#textOptionsBar QToolButton#textBarActionButton:checked {{
                background: {active};
                color: {active_text};
                border: 1px solid {active_border};
            }}
            QFrame#textOptionsBar QToolButton#textBarActionButton::menu-button {{
                border: none; width: 14px;
            }}
        """)
        if hasattr(self, "alignment_menu"):
            self.alignment_menu.setStyleSheet(f"""
                QMenu#textAlignmentPopup {{
                    background: {bar_bg};
                    border: 1px solid {border};
                    border-radius: 7px;
                    padding: 0;
                }}
                QWidget#alignmentPopupHost {{
                    background: {bar_bg};
                }}
                QToolButton#alignmentIconChoice {{
                    background: transparent;
                    border: none;
                    border-radius: 5px;
                    padding: 4px;
                }}
                QToolButton#alignmentIconChoice:hover {{
                    background: {hover};
                }}
                QToolButton#alignmentIconChoice:checked {{
                    background: {active};
                    border: 1px solid {active_border};
                }}
            """)
        if hasattr(self, "onomatopoeia_toggle"):
            self.onomatopoeia_toggle.setStyleSheet(f"""
                QToolButton {{
                    background: {button_bg};
                    border: 1px solid transparent;
                    border-radius: 6px;
                    padding: 3px;
                }}
                QToolButton:hover {{ background: {hover}; }}
                QToolButton:checked {{
                    background: {active};
                    border: 1px solid {active_border};
                }}
            """)
        self.refresh_outline_toolbar_button()
        panel_bg = "#000000" if is_black else ("#0B0F19" if is_dark else "#ffffff")
        panel_fg = "#FFFFFF" if is_black else ("#F5F7FA" if is_dark else "#30313a")
        panel_muted = "#B8B8B8" if is_black else ("#AAB4C1" if is_dark else "#6d6f78")
        control_bg = "#111111" if is_black else ("#161C27" if is_dark else "#f7f7f9")
        control_hover = "#242424" if is_black else ("#1A314F" if is_dark else "#eceef2")
        if hasattr(self, "right_widget"):
            self.right_widget.setStyleSheet(
                f"QWidget#rightPanelColumn {{ background: {panel_bg}; }}"
            )
        if hasattr(self, "left_widget"):
            self.left_widget.setStyleSheet(f"""
                QWidget#leftPagesPanel {{
                    background: {panel_bg};
                    color: {panel_fg};
                }}
                QWidget#leftPagesPanel QListWidget {{
                    background: {panel_bg};
                    color: {panel_fg};
                    border: none;
                }}
            """)
        if hasattr(self, "page_list") and hasattr(self.page_list, "apply_theme"):
            self.page_list.apply_theme(
                is_dark,
                getattr(self, "_theme_variant", ""),
            )
        if hasattr(self, "music_player"):
            self.music_player.apply_theme(
                is_dark,
                getattr(self, "_theme_variant", ""),
            )
        if hasattr(self, "normal_right_widget"):
            self.normal_right_widget.setStyleSheet(f"""
                QWidget#normalRightPanel,
                QWidget#defaultRightPanel,
                QStackedWidget#rightPanelStack,
                QWidget#inpaintingToolsHost,
                QScrollArea#inpaintingToolsScroll,
                QScrollArea#inpaintingToolsScroll > QWidget > QWidget {{
                    background: {panel_bg};
                    color: {panel_fg};
                }}
                QLabel#rightPanelSectionTitle {{
                    background: transparent;
                    color: {panel_fg};
                    border: none;
                    padding: 7px 1px 3px 1px;
                    font-size: 12px;
                    font-weight: 700;
                }}
                QWidget#normalRightPanel QTextEdit,
                QWidget#normalRightPanel QPlainTextEdit,
                QWidget#normalRightPanel QLineEdit,
                QWidget#normalRightPanel QComboBox,
                QWidget#normalRightPanel QAbstractSpinBox,
                QWidget#normalRightPanel QListView {{
                    background: {control_bg};
                    color: {panel_fg};
                    border: 1px solid {border};
                    selection-background-color: {active};
                }}
            """)
        self.text_format_panel.setStyleSheet(f"""
            QWidget#textFormatPanel {{
                background: {panel_bg};
                color: {panel_fg};
            }}
            QStackedWidget#textFormatStack,
            QWidget#textFormatPage,
            QWidget#textFormatSubPage {{
                background: {panel_bg};
                color: {panel_fg};
                border: none;
            }}
            QWidget#textFormatPanel QLabel {{
                background: transparent;
                border: none;
            }}
            QLabel#textFormatTitle {{
                background: transparent;
                border: none;
                color: {panel_fg};
                font-size: 14px;
                font-weight: 700;
            }}
            QLabel#formatDescription {{
                background: transparent;
                border: none;
                color: {panel_muted};
                font-size: 12px;
            }}
            QLabel#fontSectionTitle {{
                background: transparent;
                border: none;
                color: {panel_fg};
                font-size: 12px;
                font-weight: 700;
                padding: 0;
            }}
            QWidget#fontSectionHeader,
            QLabel#fontSectionIcon {{
                background: transparent;
                border: none;
            }}
            QLabel#fontSectionEmpty {{
                color: {panel_muted};
                font-size: 11px;
                padding: 3px 7px 7px 7px;
            }}
            QScrollArea#fontBrowserScroll,
            QWidget#fontBrowserHost {{
                background: transparent;
                border: none;
            }}
            QFrame#fontFamilyRow {{
                background: transparent;
                border: none;
                border-radius: 6px;
            }}
            QFrame#fontFamilyRow:hover {{
                background: {control_hover};
            }}
            QPushButton#fontFamilyChoice {{
                background: transparent;
                color: {panel_fg};
                border: none;
                border-radius: 5px;
                padding: 7px 5px;
                text-align: left;
                font-size: 13px;
            }}
            QPushButton#fontFamilyChoice[selected="true"] {{
                background: {active};
                color: {active_text};
                font-weight: 700;
            }}
            QToolButton#formatBackButton,
            QToolButton#formatChoiceButton,
            QToolButton#formatModeButton {{
                background: {control_bg};
                color: {panel_fg};
                border: 1px solid {border};
                border-radius: 7px;
                padding: 7px 9px;
            }}
            QToolButton#formatBackButton:hover,
            QToolButton#formatChoiceButton:hover,
            QToolButton#formatModeButton:hover {{
                background: {control_hover};
            }}
            QToolButton#formatChoiceButton:checked,
            QToolButton#formatModeButton:checked {{
                background: {active};
                color: {active_text};
                border: 2px solid {active_border};
                font-weight: 700;
            }}
            QPushButton#formatApplyButton {{
                background: {active};
                color: {active_text};
                border: 1px solid {active_border};
                border-radius: 7px;
                padding: 8px 12px;
                font-weight: 700;
            }}
            QToolButton#formatSecondaryButton {{
                background: {control_bg};
                color: {panel_fg};
                border: 1px solid {border};
                border-radius: 7px;
                padding: 8px 12px;
                font-weight: 600;
            }}
            QToolButton#formatSecondaryButton:hover {{
                background: {control_hover};
            }}
            QToolButton#outlinePresetColor:hover {{
                border: 2px solid {active_border};
            }}
            QLineEdit, QComboBox, QSpinBox, QListWidget {{
                background: {control_bg};
                color: {panel_fg};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 5px;
            }}
            QListWidget#gradientStopList {{
                background: transparent;
                border: none;
                padding: 0;
                outline: none;
            }}
            QListWidget#gradientStopList::item {{
                background: transparent;
                border: none;
            }}
            QWidget#gradientStopRow {{
                background: {control_bg};
                border: 1px solid {border};
                border-radius: 6px;
            }}
            QWidget#gradientStopRow[selected="true"] {{
                background: {control_hover};
                border: 1px solid {active_border};
            }}
            QSpinBox#gradientStopField,
            QFrame#gradientStopColourField {{
                background: {panel_bg};
                color: {panel_fg};
                border: 1px solid {border};
                border-radius: 5px;
                padding: 1px;
            }}
            QLineEdit#gradientStopHex {{
                background: transparent;
                color: {panel_fg};
                border: none;
                padding: 1px;
                font-size: 11px;
            }}
            QToolButton#gradientStopAdd,
            QToolButton#gradientStopRemove {{
                background: transparent;
                color: {panel_fg};
                border: none;
                border-radius: 5px;
                font-size: 17px;
                font-weight: 600;
            }}
            QToolButton#gradientStopAdd:hover,
            QToolButton#gradientStopRemove:hover {{
                background: {control_hover};
                color: {active_border};
            }}
        """)
        if hasattr(self, "workspace_content_widget"):
            self._configure_workspace_scrollbars(
                self.workspace_content_widget,
                is_dark,
            )
        if hasattr(self, "font_browser_layout"):
            self.refresh_font_inspector()

    def show_text_effects_panel(self) -> None:
        selected_items = self.image_viewer.get_selected_text_items()
        if not selected_items:
            return
        self.right_panel_stack.setCurrentWidget(self.text_effects_panel)

    def show_main_right_panel(self) -> None:
        self.right_panel_stack.setCurrentIndex(0)

    def set_alignment_menu_value(self, index: int, trigger: bool = False) -> None:
        """Synchronise the compact alignment menu with the formatting state."""
        buttons = self.alignment_tool_group.get_button_group().buttons()
        if index < 0 or index >= len(buttons):
            return

        if trigger:
            buttons[index].click()
        else:
            buttons[index].setChecked(True)

        for action_index, action in enumerate(self.alignment_menu_actions):
            action.setChecked(action_index == index)
        self.alignment_menu_button.svg(self._alignment_menu_icons[index])
        self.alignment_menu_button.setToolTip(self.alignment_menu_actions[index].text())

    def _select_alignment_from_popup(self, index: int) -> None:
        self.set_alignment_menu_value(index, trigger=True)
        self.alignment_menu.close()

    def create_tool_button(self, text: str = "", svg: str = "", checkable: bool = False):
        if text:
            button = MToolButton().svg(svg).text_beside_icon()
            button.setText(text)
        else:
            button = MToolButton().svg(svg)

        button.setCheckable(True) if checkable else button.setCheckable(False)

        return button

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


class _SaturationValuePlane(QtWidgets.QWidget):
    colorChanged = QtCore.Signal(QtGui.QColor)
    editingFinished = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hue = 0
        self._saturation = 255
        self._value = 255
        self.setMinimumSize(150, 125)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self.setCursor(QtCore.Qt.CursorShape.CrossCursor)

    def setColor(self, color: QtGui.QColor) -> None:  # noqa: N802 - Qt API
        color = QtGui.QColor(color)
        if not color.isValid():
            return
        hue, saturation, value, _alpha = color.getHsv()
        if hue >= 0:
            self._hue = hue
        self._saturation = saturation
        self._value = value
        self.update()

    def setHue(self, hue: int) -> None:  # noqa: N802 - Qt API
        self._hue = max(0, min(359, int(hue)))
        self.update()

    def color(self) -> QtGui.QColor:
        return QtGui.QColor.fromHsv(
            self._hue,
            self._saturation,
            self._value,
        )

    def paintEvent(self, event):  # noqa: N802 - Qt API
        del event
        rect = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        horizontal = QtGui.QLinearGradient(rect.topLeft(), rect.topRight())
        horizontal.setColorAt(0.0, QtGui.QColor("#ffffff"))
        horizontal.setColorAt(
            1.0,
            QtGui.QColor.fromHsv(self._hue, 255, 255),
        )
        painter.fillRect(rect, horizontal)

        vertical = QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
        vertical.setColorAt(0.0, QtGui.QColor(0, 0, 0, 0))
        vertical.setColorAt(1.0, QtGui.QColor(0, 0, 0, 255))
        painter.fillRect(rect, vertical)
        painter.setPen(QtGui.QPen(self.palette().color(QtGui.QPalette.ColorRole.Mid), 1))
        painter.drawRoundedRect(rect, 3, 3)

        x = rect.left() + (self._saturation / 255.0) * rect.width()
        y = rect.top() + (1.0 - self._value / 255.0) * rect.height()
        marker = QtCore.QPointF(x, y)
        painter.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.black, 3))
        painter.drawEllipse(marker, 5, 5)
        painter.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.white, 1.5))
        painter.drawEllipse(marker, 5, 5)
        painter.end()

    def _update_from_position(self, position: QtCore.QPointF) -> None:
        rect = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        x = max(rect.left(), min(rect.right(), position.x()))
        y = max(rect.top(), min(rect.bottom(), position.y()))
        self._saturation = round(((x - rect.left()) / max(1.0, rect.width())) * 255)
        self._value = round((1.0 - ((y - rect.top()) / max(1.0, rect.height()))) * 255)
        self.update()
        self.colorChanged.emit(self.color())

    def mousePressEvent(self, event):  # noqa: N802 - Qt API
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._update_from_position(event.position())
            event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt API
        if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self._update_from_position(event.position())
            event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt API
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._update_from_position(event.position())
            self.editingFinished.emit()
            event.accept()


class _HueStrip(QtWidgets.QWidget):
    hueChanged = QtCore.Signal(int)
    editingFinished = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hue = 0
        self.setFixedWidth(20)
        self.setMinimumHeight(125)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def setHue(self, hue: int) -> None:  # noqa: N802 - Qt API
        self._hue = max(0, min(359, int(hue)))
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt API
        del event
        rect = QtCore.QRectF(self.rect()).adjusted(2, 1, -2, -1)
        gradient = QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
        for step in range(7):
            hue = round((step / 6.0) * 359)
            gradient.setColorAt(step / 6.0, QtGui.QColor.fromHsv(hue, 255, 255))
        painter = QtGui.QPainter(self)
        painter.fillRect(rect, gradient)
        painter.setPen(QtGui.QPen(self.palette().color(QtGui.QPalette.ColorRole.Mid), 1))
        painter.drawRoundedRect(rect, 3, 3)
        y = rect.top() + (self._hue / 359.0) * rect.height()
        painter.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.white, 2))
        painter.drawLine(
            QtCore.QPointF(rect.left() - 1, y),
            QtCore.QPointF(rect.right() + 1, y),
        )
        painter.end()

    def _update_from_position(self, position: QtCore.QPointF) -> None:
        rect = QtCore.QRectF(self.rect()).adjusted(2, 1, -2, -1)
        y = max(rect.top(), min(rect.bottom(), position.y()))
        self._hue = round(((y - rect.top()) / max(1.0, rect.height())) * 359)
        self.update()
        self.hueChanged.emit(self._hue)

    def mousePressEvent(self, event):  # noqa: N802 - Qt API
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._update_from_position(event.position())
            event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt API
        if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self._update_from_position(event.position())
            event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt API
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._update_from_position(event.position())
            self.editingFinished.emit()
            event.accept()


class CompactColorPicker(QtWidgets.QWidget):
    """Inline hue/saturation/value picker sized for a narrow inspector."""

    currentColorChanged = QtCore.Signal(QtGui.QColor)
    editingFinished = QtCore.Signal()

    def __init__(self, color: QtGui.QColor | str = "#000000", parent=None):
        super().__init__(parent)
        self._color = QtGui.QColor(color)
        if not self._color.isValid():
            self._color = QtGui.QColor("#000000")
        self._syncing = False

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        picker_row = QtWidgets.QHBoxLayout()
        picker_row.setSpacing(6)
        self.plane = _SaturationValuePlane(self)
        self.hue_strip = _HueStrip(self)
        picker_row.addWidget(self.plane, 1)
        picker_row.addWidget(self.hue_strip)
        root.addLayout(picker_row)

        value_row = QtWidgets.QHBoxLayout()
        value_row.setSpacing(6)
        self.preview = QtWidgets.QFrame(self)
        self.preview.setFixedSize(30, 26)
        self.preview.setObjectName("compactColorPreview")
        self.hex_edit = QtWidgets.QLineEdit(self)
        self.hex_edit.setMaxLength(9)
        self.hex_edit.setPlaceholderText("#RRGGBB")
        value_row.addWidget(self.preview)
        value_row.addWidget(self.hex_edit, 1)
        root.addLayout(value_row)

        self.plane.colorChanged.connect(self._on_plane_color)
        self.plane.editingFinished.connect(self.editingFinished)
        self.hue_strip.hueChanged.connect(self._on_hue_changed)
        self.hue_strip.editingFinished.connect(self.editingFinished)
        self.hex_edit.editingFinished.connect(self._on_hex_finished)
        self.setCurrentColor(self._color)

    def currentColor(self) -> QtGui.QColor:  # noqa: N802 - Qt API
        return QtGui.QColor(self._color)

    def setCurrentColor(self, color: QtGui.QColor | str) -> None:  # noqa: N802 - Qt API
        color = QtGui.QColor(color)
        if not color.isValid():
            return
        self._syncing = True
        try:
            self._color = color
            self.plane.setColor(color)
            hue = color.hue()
            if hue < 0:
                hue = self.hue_strip._hue
            self.hue_strip.setHue(hue)
            self.hex_edit.setText(color.name(QtGui.QColor.NameFormat.HexRgb).upper())
            self.preview.setStyleSheet(
                f"background: {color.name(QtGui.QColor.NameFormat.HexArgb)};"
                " border: 1px solid rgba(127,127,127,150); border-radius: 5px;"
            )
        finally:
            self._syncing = False

    def _publish(self, color: QtGui.QColor) -> None:
        if self._syncing or not color.isValid():
            return
        color.setAlpha(self._color.alpha())
        self._color = color
        self.hex_edit.setText(color.name(QtGui.QColor.NameFormat.HexRgb).upper())
        self.preview.setStyleSheet(
            f"background: {color.name(QtGui.QColor.NameFormat.HexArgb)};"
            " border: 1px solid rgba(127,127,127,150); border-radius: 5px;"
        )
        self.currentColorChanged.emit(QtGui.QColor(color))

    def _on_plane_color(self, color: QtGui.QColor) -> None:
        self._publish(color)

    def _on_hue_changed(self, hue: int) -> None:
        self.plane.setHue(hue)
        self._publish(self.plane.color())

    def _on_hex_finished(self) -> None:
        value = self.hex_edit.text().strip()
        if value and not value.startswith("#"):
            value = f"#{value}"
        color = QtGui.QColor(value)
        if not color.isValid():
            self.hex_edit.setText(
                self._color.name(QtGui.QColor.NameFormat.HexRgb).upper()
            )
            return
        color.setAlpha(self._color.alpha())
        self.setCurrentColor(color)
        self.currentColorChanged.emit(QtGui.QColor(color))
        self.editingFinished.emit()

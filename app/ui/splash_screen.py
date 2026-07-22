import math
import os
import random

from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QGraphicsOpacityEffect,
)
from PySide6.QtCore import Qt, Signal, QTimer, QRectF, QPointF, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import (
    QPixmap,
    QPainter,
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QPainterPath,
    QLinearGradient,
    QBrush,
    QPen,
)

_PLUM = "#43152F"
_INK = "#0E0E10"
_PINK = QColor(226, 48, 84)
_PINK_SOFT = QColor(244, 106, 128)
_MUTED = "#8A6E7E"
_TRACK = "#EFDFE8"

_SUBTITLE_TEXT = "ムカイ・トランスレート"

# Japanese fonts bundled with the app, used when the system has none installed.
_FONTS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "resources", "fonts")
)
_BUNDLED_LIGHT_PATH = os.path.join(_FONTS_DIR, "NotoSansJP-Light.otf")
_BUNDLED_BLACK_PATH = os.path.join(_FONTS_DIR, "NotoSansJP-Black.otf")


def _register_bundled_font(path: str, keyword: str) -> str | None:
    if not os.path.exists(path):
        return None
    font_id = QFontDatabase.addApplicationFont(path)
    loaded = QFontDatabase.applicationFontFamilies(font_id) if font_id != -1 else []
    for family in loaded:
        if keyword in family:
            return family
    return loaded[0] if loaded else None


def _pick_japanese_font() -> str:
    """Return the best available minimalist Japanese font family on this system."""
    preferred = [
        "Yu Gothic Light",
        "Yu Gothic UI Light",
        "Noto Sans JP Light",
        "Noto Sans JP",
        "Yu Mincho",
        "MS PMincho",
        "MS Mincho",
        "Noto Serif JP",
        "Yu Gothic",
        "Meiryo",
        "MS Gothic",
    ]
    families = set(QFontDatabase.families())
    for name in preferred:
        if name in families:
            return name

    # Nothing installed: register the font bundled with the app and use it.
    bundled = _register_bundled_font(_BUNDLED_LIGHT_PATH, "Light")
    return bundled if bundled else "sans-serif"


def _pick_mark_font() -> str:
    """Return the heavy Japanese font family used for the MT wordmark."""
    if "Noto Sans JP Black" in set(QFontDatabase.families()):
        return "Noto Sans JP Black"
    bundled = _register_bundled_font(_BUNDLED_BLACK_PATH, "Black")
    return bundled if bundled else _pick_japanese_font()


class _MinimalLoadingBar(QWidget):
    """Thin indeterminate loading bar shaped like a parallelogram, with a
    sliding accent segment of the same slanted shape."""

    SLANT = 7.0  # horizontal offset of the slanted ends

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(180, 8)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._timer.start(16)

    def _advance(self):
        self._phase = (self._phase + 0.011) % 1.0
        self.update()

    @staticmethod
    def _parallelogram(rect: QRectF, slant: float) -> QPainterPath:
        path = QPainterPath()
        path.moveTo(rect.left() + slant, rect.top())
        path.lineTo(rect.right(), rect.top())
        path.lineTo(rect.right() - slant, rect.bottom())
        path.lineTo(rect.left(), rect.bottom())
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())

        track = self._parallelogram(rect, self.SLANT)
        painter.setClipPath(track)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_TRACK))
        painter.drawPath(track)

        seg_w = rect.width() * 0.32
        span = rect.width() + seg_w
        x = self._phase * span - seg_w
        segment = self._parallelogram(QRectF(x, 0, seg_w, rect.height()), self.SLANT)
        painter.setBrush(QColor(_PINK))
        painter.drawPath(segment)


class _MarkWidget(QWidget):
    """The MT wordmark, custom painted so the T can be animated on its own.

    The M is solid ink black; the T rebuilds itself from flying particles,
    then breathes, pulses between two pinkish reds and gets a periodic
    diagonal shine sweep. Both letters get an extra stroke to look bolder.
    """

    PARTICLES_START = 0.2
    PARTICLE_MAX_DELAY = 0.6
    PARTICLE_DURATION = 0.8
    SOLID_FADE = 0.25
    SHINE_PERIOD = 3.2
    SHINE_DURATION = 0.7
    STROKE_WIDTH = 5.0
    GRID_STEP = 4.0

    def __init__(self, family: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(150)
        font = QFont(family)
        font.setPixelSize(112)
        font.setWeight(QFont.Weight.Black)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3.0)
        self._font = font
        self._time = 0.0
        self._particles: list[tuple] | None = None
        self._built_width = -1
        self._particles_end = (
            self.PARTICLES_START + self.PARTICLE_MAX_DELAY + self.PARTICLE_DURATION
        )
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._timer.start(16)

    def _advance(self):
        self._time += 0.016
        self.update()

    def _glyph_geometry(self):
        metrics = QFontMetricsF(self._font)
        m_advance = metrics.horizontalAdvance("M")
        t_advance = metrics.horizontalAdvance("T")
        x0 = (self.width() - (m_advance + t_advance)) / 2.0
        baseline = (self.height() + metrics.capHeight()) / 2.0

        m_path = QPainterPath()
        m_path.addText(x0, baseline, self._font, "M")
        t_path = QPainterPath()
        t_path.addText(x0 + m_advance, baseline, self._font, "T")
        return m_path, t_path

    def _build_particles(self, t_path: QPainterPath) -> None:
        # Sample the T glyph on a grid; each inner point becomes a particle:
        # (target_x, target_y, start_x, start_y, delay, duration, radius,
        #  curve_amplitude, color).
        rng = random.Random()
        rect = t_path.boundingRect()
        particles = []
        y = rect.top()
        while y <= rect.bottom():
            x = rect.left()
            while x <= rect.right():
                if t_path.contains(QPointF(x, y)):
                    angle = rng.uniform(0.0, 2.0 * math.pi)
                    distance = rng.uniform(70.0, 190.0)
                    # Assemble top to bottom: delay follows the row, plus jitter.
                    row = (y - rect.top()) / max(rect.height(), 1.0)
                    delay = row * self.PARTICLE_MAX_DELAY * 0.7 + rng.uniform(
                        0.0, self.PARTICLE_MAX_DELAY * 0.3
                    )
                    # A few particles are bright sparkles, the rest vary in tone.
                    if rng.random() < 0.06:
                        color = QColor(255, 214, 224)
                    else:
                        k = rng.random()
                        color = QColor(
                            round(_PINK.red() + (_PINK_SOFT.red() - _PINK.red()) * k),
                            round(_PINK.green() + (_PINK_SOFT.green() - _PINK.green()) * k),
                            round(_PINK.blue() + (_PINK_SOFT.blue() - _PINK.blue()) * k),
                        )
                    particles.append((
                        x,
                        y,
                        x + math.cos(angle) * distance,
                        y + math.sin(angle) * distance,
                        delay,
                        self.PARTICLE_DURATION * rng.uniform(0.7, 1.0),
                        rng.uniform(1.4, 2.8),
                        rng.uniform(-26.0, 26.0),
                        color,
                    ))
                x += self.GRID_STEP
            y += self.GRID_STEP
        self._particles = particles
        self._built_width = self.width()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        m_path, t_path = self._glyph_geometry()
        t_rect = t_path.boundingRect()

        # M: solid ink black, thickened with an outline stroke.
        ink = QColor(_INK)
        painter.setPen(QPen(ink, self.STROKE_WIDTH, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(ink)
        painter.drawPath(m_path)

        if self._particles is None or self._built_width != self.width():
            self._build_particles(t_path)

        # Soft color pulse between two pinkish reds.
        k = (math.sin(self._time * 2.0) + 1.0) / 2.0
        color = QColor(
            round(_PINK.red() + (_PINK_SOFT.red() - _PINK.red()) * k),
            round(_PINK.green() + (_PINK_SOFT.green() - _PINK.green()) * k),
            round(_PINK.blue() + (_PINK_SOFT.blue() - _PINK.blue()) * k),
        )

        solid_progress = min(max((self._time - self._particles_end) / self.SOLID_FADE, 0.0), 1.0)

        # Particle phase: dots fly in along curved paths, overshoot slightly
        # and settle into place, assembling the T from top to bottom.
        if solid_progress < 1.0:
            painter.setPen(Qt.PenStyle.NoPen)
            for tx, ty, sx, sy, delay, duration, radius, curve, pcolor in self._particles:
                p = min(max((self._time - self.PARTICLES_START - delay) / duration, 0.0), 1.0)
                if p <= 0.0:
                    continue
                # OutBack easing: a small overshoot past the target before settling.
                c1, c3 = 1.70158, 2.70158
                eased = 1.0 + c3 * (p - 1.0) ** 3 + c1 * (p - 1.0) ** 2
                px = sx + (tx - sx) * eased
                py = sy + (ty - sy) * eased
                # Curved flight: a perpendicular arc that vanishes on landing.
                dx, dy = tx - sx, ty - sy
                length = math.hypot(dx, dy) or 1.0
                arc = math.sin(p * math.pi) * curve
                px += (-dy / length) * arc
                py += (dx / length) * arc
                r = radius * (1.35 - 0.35 * p)
                dot = QColor(pcolor)
                dot.setAlpha(round(255 * min(1.0, p * 3.0) * (1.0 - solid_progress)))
                painter.setBrush(dot)
                painter.drawEllipse(QRectF(px - r, py - r, r * 2.0, r * 2.0))

        # Solid phase: the assembled T fades in on top of the converged particles.
        if solid_progress > 0.0:
            painter.save()
            settled = self._time - (self._particles_end + self.SOLID_FADE)
            if settled > 0.0:
                scale = 1.0 + 0.02 * math.sin(settled * (2.0 * math.pi / 2.6))
                center = t_rect.center()
                painter.translate(center)
                painter.scale(scale, scale)
                painter.translate(-center)
            painter.setOpacity(solid_progress)
            painter.setPen(QPen(color, self.STROKE_WIDTH, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(color)
            painter.drawPath(t_path)

            # Periodic diagonal shine sweeping across the T.
            shine_start = self._particles_end + self.SOLID_FADE + 0.4
            if self._time >= shine_start:
                cycle_t = (self._time - shine_start) % self.SHINE_PERIOD
                if cycle_t < self.SHINE_DURATION:
                    shine = cycle_t / self.SHINE_DURATION
                    band_w = t_rect.width() * 0.55
                    x = t_rect.left() - band_w + shine * (t_rect.width() + 2.0 * band_w)
                    gradient = QLinearGradient(x, t_rect.top(), x + band_w, t_rect.bottom())
                    gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
                    gradient.setColorAt(0.5, QColor(255, 255, 255, 180))
                    gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
                    painter.setClipPath(t_path)
                    painter.fillRect(t_rect.adjusted(-6, -6, 6, 6), QBrush(gradient))
            painter.restore()


class SplashScreen(QWidget):
    """Minimal splash screen: MT wordmark, katakana subtitle and a loading bar."""

    cancelled = Signal()  # Signal emitted when cancel button is clicked

    def __init__(self, pixmap: QPixmap | None = None, parent=None):
        # pixmap is accepted for backward compatibility but no longer used.
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(440, 300)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        container = QWidget()
        container.setObjectName("splashContainer")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 26)
        container_layout.setSpacing(0)

        # Title bar with minimize and close buttons
        title_bar = QWidget()
        title_bar.setObjectName("titleBar")
        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(8, 6, 8, 0)
        title_bar_layout.setSpacing(4)
        title_bar_layout.addStretch()

        self.minimize_btn = QPushButton("−")
        self.minimize_btn.setObjectName("minimizeBtn")
        self.minimize_btn.setFixedSize(24, 24)
        self.minimize_btn.clicked.connect(self.showMinimized)
        self.minimize_btn.setToolTip("Minimize")
        title_bar_layout.addWidget(self.minimize_btn)

        self.cancel_btn = QPushButton("✕")
        self.cancel_btn.setObjectName("cancelBtn")
        self.cancel_btn.setFixedSize(24, 24)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.setToolTip("Cancel and exit")
        title_bar_layout.addWidget(self.cancel_btn)

        container_layout.addWidget(title_bar)
        container_layout.addStretch()

        # MT wordmark in a heavy Japanese font; the T animates on its own.
        self.mark = _MarkWidget(_pick_mark_font())
        container_layout.addWidget(self.mark)

        # Katakana subtitle, revealed with a typing effect.
        jp_family = _pick_japanese_font()
        self.subtitle_label = QLabel()
        self.subtitle_label.setObjectName("subtitleLabel")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setStyleSheet(
            f'font-family: "{jp_family}"; font-size: 13px; letter-spacing: 6px;'
        )
        self._typed_chars = 0
        self._set_subtitle_progress(0)
        container_layout.addWidget(self.subtitle_label)

        container_layout.addStretch()

        # Minimal indeterminate loading bar (replaces the loading status text)
        self.loading_bar = _MinimalLoadingBar()
        bar_row = QHBoxLayout()
        bar_row.addStretch()
        bar_row.addWidget(self.loading_bar)
        bar_row.addStretch()
        container_layout.addLayout(bar_row)

        main_layout.addWidget(container)

        self.setStyleSheet(f"""
            #splashContainer {{
                background-color: #FBF7FA;
                border: 1px solid #E9DCE5;
                border-radius: 12px;
            }}
            #titleBar {{
                background-color: transparent;
            }}
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
                color: {_MUTED};
                font-size: 14px;
                font-weight: bold;
            }}
            #minimizeBtn:hover {{
                background-color: #EFDFE8;
                color: {_PLUM};
            }}
            #cancelBtn:hover {{
                background-color: #ff5555;
                color: white;
            }}
        """)

        # --- Animations ---
        # Entrance: the wordmark and the loading bar fade in.
        self._mark_fade = self._fade_in(self.mark, duration=600)
        self._bar_fade = self._fade_in(self.loading_bar, duration=600, delay=500)

        # Typing effect for the katakana subtitle.
        self._type_timer = QTimer(self)
        self._type_timer.timeout.connect(self._type_next_char)
        QTimer.singleShot(450, lambda: self._type_timer.start(90))

        # For dragging the window
        self._drag_pos = None

    # --- Animation helpers ---

    def _fade_in(self, widget: QWidget, duration: int, delay: int = 0) -> QPropertyAnimation:
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        effect.setOpacity(0.0)
        anim = QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        if delay > 0:
            QTimer.singleShot(delay, anim.start)
        else:
            anim.start()
        return anim

    def _set_subtitle_progress(self, count: int) -> None:
        # Render the full text with the untyped part transparent so the
        # centered layout never shifts while characters appear.
        shown = _SUBTITLE_TEXT[:count]
        hidden = _SUBTITLE_TEXT[count:]
        self.subtitle_label.setText(
            f'<span style="color:{_MUTED};">{shown}</span>'
            f'<span style="color:transparent;">{hidden}</span>'
        )

    def _type_next_char(self):
        self._typed_chars += 1
        self._set_subtitle_progress(self._typed_chars)
        if self._typed_chars >= len(_SUBTITLE_TEXT):
            self._type_timer.stop()

    # --- Window behaviour ---

    def _on_cancel(self):
        """Handle cancel button click."""
        self.cancelled.emit()
        self.close()

    def finish(self, main_window):
        """Close the splash screen and show the main window."""
        if main_window:
            main_window.show()
        self.close()

    def set_status(self, text: str):
        # No visible loading text anymore; keep the current step reachable on hover.
        self.loading_bar.setToolTip(text)

    def mousePressEvent(self, event):
        """Enable dragging the splash screen."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        """Handle dragging the splash screen."""
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        """Stop dragging."""
        self._drag_pos = None

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from app.export_enhancer import (
    ExportEnhancementOptions,
    component_is_installed,
)


class ExportQualityDialog(QtWidgets.QDialog):
    """Choose output resolution and restoration profile before rendering."""

    def __init__(
        self,
        initial_options: dict | None = None,
        locked_format: str | None = None,
        sample_size: tuple[int, int] | None = None,
        page_count: int = 1,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Export quality"))
        self.setModal(True)
        self.resize(590, 520)
        self._sample_size = sample_size
        self._page_count = max(1, int(page_count))
        self._locked_format = (
            str(locked_format).lower()
            if str(locked_format or "").lower() in {"png", "jpg"}
            else None
        )
        initial = ExportEnhancementOptions.from_dict(initial_options)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        title = QtWidgets.QLabel(self.tr("Final manga quality"))
        title_font = QtGui.QFont(title.font())
        title_font.setPointSize(title_font.pointSize() + 4)
        title_font.setBold(True)
        title.setFont(title_font)
        root.addWidget(title)

        intro = QtWidgets.QLabel(
            self.tr(
                "Enhancement is applied only to the finished page background. "
                "Translated text and watermarks are rendered afterwards at the "
                "final resolution, so their edges remain clean."
            )
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)

        self.resolution_combo = QtWidgets.QComboBox(self)
        self.resolution_combo.addItem(self.tr("Original quality (no resize)"), 0)
        self.resolution_combo.addItem(self.tr("2K — long edge 2048 px"), 2048)
        self.resolution_combo.addItem(self.tr("4K — long edge 4096 px"), 4096)
        self.resolution_combo.addItem(self.tr("6K — long edge 6144 px"), 6144)
        self.resolution_combo.addItem(self.tr("8K — long edge 8192 px"), 8192)
        self._select_combo_data(self.resolution_combo, initial.target_long_edge)
        form.addRow(self.tr("Resolution"), self.resolution_combo)

        self.profile_combo = QtWidgets.QComboBox(self)
        self.profile_combo.addItem(
            self.tr("Manga balanced — Real-CUGAN conservative"),
            "manga_balanced",
        )
        self.profile_combo.addItem(
            self.tr("Maximum detail — Real-CUGAN without denoise"),
            "manga_detail",
        )
        self.profile_combo.addItem(
            self.tr("Noisy scan — Real-CUGAN strong denoise"),
            "manga_denoise",
        )
        self.profile_combo.addItem(
            self.tr("Compressed color/anime — Real-ESRGAN"),
            "realesrgan_anime",
        )
        self.profile_combo.addItem(
            self.tr("General illustration — Real-ESRGAN"),
            "realesrgan_general",
        )
        self.profile_combo.addItem(
            self.tr("Classic high-quality resize — Lanczos (no AI)"),
            "lanczos",
        )
        self._select_combo_data(self.profile_combo, initial.profile)
        form.addRow(self.tr("Restoration"), self.profile_combo)

        self.format_combo = QtWidgets.QComboBox(self)
        self.format_combo.addItem("PNG", "png")
        self.format_combo.addItem("JPG", "jpg")
        self._select_combo_data(
            self.format_combo,
            self._locked_format or initial.page_format,
        )
        if self._locked_format:
            self.format_combo.setEnabled(False)
            self.format_combo.setToolTip(
                self.tr("The image format was selected in the Export menu.")
            )
        form.addRow(self.tr("Page format"), self.format_combo)

        quality_row = QtWidgets.QWidget(self)
        quality_layout = QtWidgets.QHBoxLayout(quality_row)
        quality_layout.setContentsMargins(0, 0, 0, 0)
        self.jpeg_quality = QtWidgets.QSlider(
            QtCore.Qt.Orientation.Horizontal,
            quality_row,
        )
        self.jpeg_quality.setRange(85, 100)
        self.jpeg_quality.setValue(initial.jpeg_quality)
        self.jpeg_quality_value = QtWidgets.QLabel(str(initial.jpeg_quality))
        self.jpeg_quality_value.setMinimumWidth(26)
        self.jpeg_quality.valueChanged.connect(
            lambda value: self.jpeg_quality_value.setText(str(value))
        )
        quality_layout.addWidget(self.jpeg_quality, 1)
        quality_layout.addWidget(self.jpeg_quality_value)
        form.addRow(self.tr("JPG quality"), quality_row)

        self.gradient_checkbox = QtWidgets.QCheckBox(
            self.tr("Protect gradients and soft tonal transitions"),
            self,
        )
        self.gradient_checkbox.setChecked(initial.protect_gradients)
        form.addRow("", self.gradient_checkbox)
        root.addLayout(form)

        self.profile_help = QtWidgets.QLabel(self)
        self.profile_help.setWordWrap(True)
        self.profile_help.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.profile_help.setOpenExternalLinks(True)
        self.profile_help.setStyleSheet(
            "QLabel { padding: 10px; border-radius: 6px; "
            "background: rgba(127, 127, 127, 28); }"
        )
        root.addWidget(self.profile_help)

        self.estimate_label = QtWidgets.QLabel(self)
        self.estimate_label.setWordWrap(True)
        root.addWidget(self.estimate_label)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
            | QtWidgets.QDialogButtonBox.StandardButton.Save,
            parent=self,
        )
        save_button = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Save)
        save_button.setText(self.tr("Export"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.resolution_combo.currentIndexChanged.connect(self._update_ui)
        self.profile_combo.currentIndexChanged.connect(self._update_ui)
        self.format_combo.currentIndexChanged.connect(self._update_ui)
        self._update_ui()

    @staticmethod
    def _select_combo_data(combo: QtWidgets.QComboBox, value) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _update_ui(self) -> None:
        target = int(self.resolution_combo.currentData() or 0)
        profile = str(self.profile_combo.currentData() or "manga_balanced")
        enhanced = target > 0
        uses_ai = enhanced and profile != "lanczos"
        self.profile_combo.setEnabled(enhanced)
        self.gradient_checkbox.setEnabled(uses_ai)

        is_jpg = self.format_combo.currentData() == "jpg"
        self.jpeg_quality.setEnabled(is_jpg)
        self.jpeg_quality_value.setEnabled(is_jpg)

        descriptions = {
            "manga_balanced": self.tr(
                "<b>Recommended.</b> Preserves line art, intentional blur and "
                "textures better than an aggressive enhancer."
            ),
            "manga_detail": self.tr(
                "For already clean digital pages and screentones. It adds no "
                "denoise, avoiding loss of fine texture."
            ),
            "manga_denoise": self.tr(
                "For visibly noisy or heavily compressed scans. Strong denoise "
                "can remove very fine screentones, so compare before batch use."
            ),
            "realesrgan_anime": self.tr(
                "Stronger reconstruction for compressed color pages and anime "
                "art. It may reinterpret more detail than Real-CUGAN."
            ),
            "realesrgan_general": self.tr(
                "General restoration for painted or mixed-content illustration."
            ),
            "lanczos": self.tr(
                "Changes pixel dimensions without neural reconstruction. Fastest "
                "and completely faithful to the finished raster."
            ),
        }
        if not enhanced:
            self.profile_help.setText(
                self.tr(
                    "<b>Original:</b> the page keeps its current dimensions and "
                    "no enhancement engine is started."
                )
            )
        else:
            installed = component_is_installed(profile)
            suffix = (
                self.tr(" The required engine is already installed.")
                if installed
                else self.tr(" The engine will be downloaded on first use.")
            )
            self.profile_help.setText(descriptions.get(profile, "") + suffix)

        if not self._sample_size:
            self.estimate_label.setText(
                self.tr("{count} page(s) will be exported.").format(
                    count=self._page_count
                )
            )
            return

        source_width, source_height = self._sample_size
        if target <= 0:
            output_width, output_height = source_width, source_height
        else:
            ratio = target / float(max(source_width, source_height))
            output_width = max(1, int(round(source_width * ratio)))
            output_height = max(1, int(round(source_height * ratio)))
        megapixels = output_width * output_height / 1_000_000.0
        warning = ""
        if megapixels >= 25:
            warning = self.tr(
                " High resolutions use considerably more memory and export time."
            )
        self.estimate_label.setText(
            self.tr(
                "Estimated page size: {width} × {height} px ({mp:.1f} MP). "
                "Pages: {count}."
            ).format(
                width=output_width,
                height=output_height,
                mp=megapixels,
                count=self._page_count,
            )
            + warning
        )

    def export_options(self) -> ExportEnhancementOptions:
        return ExportEnhancementOptions.from_dict(
            {
                "target_long_edge": int(
                    self.resolution_combo.currentData() or 0
                ),
                "profile": str(
                    self.profile_combo.currentData() or "manga_balanced"
                ),
                "protect_gradients": self.gradient_checkbox.isChecked(),
                "page_format": str(self.format_combo.currentData() or "png"),
                "jpeg_quality": self.jpeg_quality.value(),
            }
        )

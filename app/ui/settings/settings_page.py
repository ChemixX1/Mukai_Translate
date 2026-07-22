import os, shutil
from typing import Optional
import logging
from dataclasses import asdict, is_dataclass

from PySide6 import QtWidgets, QtGui
from PySide6.QtCore import Signal, QSettings, QUrl, Qt, QSignalBlocker
from PySide6.QtGui import QFont, QFontDatabase, QDesktopServices

from app.shortcuts import get_default_shortcuts
from app.env_config import first_env_value, load_project_env
from .settings_ui import SettingsPageUI
from modules.utils.device import is_gpu_available
from app.update_checker import UpdateChecker, release_notes_to_html
from modules.utils.paths import get_user_data_dir, get_default_project_autosave_dir


logger = logging.getLogger(__name__)


CREDENTIAL_FIELDS = {
    "Custom": ("api_key", "api_url", "model"),
    "Microsoft Azure": ("api_key_ocr", "endpoint", "api_key_translator", "region_translator"),
    "Yandex": ("api_key", "folder_id"),
}

CREDENTIAL_ENV_KEYS = {
    "Open AI GPT": {"api_key": ("OPENAI_API_KEY",)},
    "Google Gemini": {"api_key": ("GEMINI_API_KEY", "GOOGLE_API_KEY")},
    "Anthropic Claude": {"api_key": ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY")},
    "Deepseek": {"api_key": ("DEEPSEEK_API_KEY",)},
    "Grok": {"api_key": ("GROK_API_KEY", "XAI_API_KEY", "CUSTOM_OPENAI_API_KEY")},
    "Custom": {
        "api_key": ("CUSTOM_OPENAI_API_KEY", "CUSTOM_API_KEY"),
        "api_url": ("CUSTOM_OPENAI_API_BASE", "CUSTOM_OPENAI_BASE_URL", "CUSTOM_API_BASE"),
        "model": ("CUSTOM_OPENAI_MODEL", "CUSTOM_MODEL"),
    },
    "Microsoft Azure": {
        "api_key_ocr": ("AZURE_VISION_API_KEY", "MICROSOFT_VISION_API_KEY", "AZURE_API_KEY"),
        "endpoint": ("AZURE_VISION_ENDPOINT", "MICROSOFT_VISION_ENDPOINT", "AZURE_ENDPOINT"),
        "api_key_translator": ("AZURE_TRANSLATOR_API_KEY", "MICROSOFT_TRANSLATOR_API_KEY", "AZURE_API_KEY"),
        "region_translator": ("AZURE_TRANSLATOR_REGION", "MICROSOFT_TRANSLATOR_REGION", "AZURE_REGION"),
    },
    "Google Cloud": {"api_key": ("GOOGLE_CLOUD_API_KEY", "GOOGLE_API_KEY")},
    "Yandex": {
        "api_key": ("YANDEX_API_KEY", "YANDEX_SECRET_KEY"),
        "folder_id": ("YANDEX_FOLDER_ID",),
    },
}

MODEL_CREDENTIAL_PROVIDERS = (
    ("GPT", "Open AI GPT"),
    ("Gemini", "Google Gemini"),
    ("Claude", "Anthropic Claude"),
    ("Deepseek", "Deepseek"),
    ("Grok", "Grok"),
    ("Microsoft", "Microsoft Azure"),
    ("Google Cloud", "Google Cloud"),
)


class SettingsPage(QtWidgets.QWidget):
    theme_changed = Signal(str)
    font_imported = Signal(str)

    def __init__(self, parent=None):
        super(SettingsPage, self).__init__(parent)

        self.ui = SettingsPageUI(self)
        self._setup_connections()
        self._loading_settings = False
        self._is_background_check = False
        self._current_language = None  # Track current language for revert
        load_project_env()

        # Update Checker
        self.update_checker = UpdateChecker()
        self.update_checker.update_available.connect(self.on_update_available)
        self.update_checker.up_to_date.connect(self.on_up_to_date)
        self.update_checker.error_occurred.connect(self.on_update_error)
        self.update_checker.download_progress.connect(self.on_download_progress)
        self.update_checker.download_finished.connect(self.on_download_finished)
        self.update_dialog = None

        # Use the Settings UI directly; inner content is scrollable on the
        # right side (see settings_ui.py). This keeps the left navbar fixed.
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.ui)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

    def _setup_connections(self):
        # Connect signals to slots
        self.ui.theme_combo.currentTextChanged.connect(self.on_theme_changed)
        self.ui.lang_combo.currentTextChanged.connect(self.on_language_changed)
        self.ui.translator_combo.currentTextChanged.connect(self._sync_extra_context_limit)
        self.ui.font_browser.sig_files_changed.connect(self.import_font)
        self.ui.shortcuts_page.shortcut_changed.connect(self.on_shortcut_changed)
        self.ui.check_update_button.clicked.connect(self.check_for_updates)
        self._sync_extra_context_limit(self.ui.translator_combo.currentText())

    def _sync_extra_context_limit(self, translator: str) -> None:
        normalized = self.ui.reverse_mappings.get(translator, translator)
        self.ui.llms_page.set_extra_context_unlimited(normalized == "Custom")

    def on_theme_changed(self, theme: str):
        self.theme_changed.emit(theme)

    def get_language(self):
        return self.ui.lang_combo.currentText()
    
    def get_theme(self):
        return self.ui.theme_combo.currentText()

    def get_tool_selection(self, tool_type):
        tool_combos = {
            'translator': self.ui.translator_combo,
            'ocr': self.ui.ocr_combo,
            'inpainter': self.ui.inpainter_combo,
            'detector': self.ui.detector_combo
        }
        return tool_combos[tool_type].currentText()

    def is_gpu_enabled(self):
        if not is_gpu_available():
            return False
        return self.ui.use_gpu_checkbox.isChecked()

    def get_llm_settings(self):
        return {
            'extra_context': self.ui.extra_context.toPlainText(),
            'image_input_enabled': self.ui.image_checkbox.isChecked(),
        }

    def get_export_settings(self):
        owner = self.window()
        title_bar = getattr(owner, "title_bar", None)
        settings = QSettings("ComicLabs", "ComicTranslate")
        settings.beginGroup('export')
        persisted_autosave_enabled = settings.value('project_autosave_enabled', False, type=bool)
        settings.endGroup()
        if title_bar is not None:
            autosave_enabled = bool(title_bar.autosave_switch.isChecked())
        else:
            autosave_enabled = bool(persisted_autosave_enabled)
        autosave_folder = self.ui.project_autosave_folder_input.text().strip()
        if not autosave_folder:
            autosave_folder = get_default_project_autosave_dir()
        settings = {
            'export_raw_text': self.ui.raw_text_checkbox.isChecked(),
            'export_translated_text': self.ui.translated_text_checkbox.isChecked(),
            'export_inpainted_image': self.ui.inpainted_image_checkbox.isChecked(),
            'project_autosave_enabled': autosave_enabled,
            'project_autosave_interval_min': int(self.ui.project_autosave_interval_spinbox.value()),
            'project_autosave_folder': autosave_folder,
        }
        return settings

    def _normalize_credential_service(self, service: str) -> str:
        normalized = self.ui.value_mappings.get(service, service)
        if normalized in CREDENTIAL_ENV_KEYS or normalized in CREDENTIAL_FIELDS:
            return normalized

        for marker, provider in MODEL_CREDENTIAL_PROVIDERS:
            if marker in normalized:
                return provider

        return normalized

    def _credential_fields_for(self, normalized: str) -> tuple[str, ...]:
        return CREDENTIAL_FIELDS.get(normalized, ("api_key",))

    def _credential_widget_value(self, normalized: str, field: str) -> str:
        candidate_keys = [f"{normalized}_{field}"]
        if normalized == "Microsoft Azure" and field == "region_translator":
            candidate_keys.append("Microsoft Azure_region")

        for widget_key in candidate_keys:
            widget = self.ui.credential_widgets.get(widget_key)
            if widget is not None:
                return widget.text().strip()
        return ""

    def _credential_env_value(self, normalized: str, field: str) -> str:
        return first_env_value(*CREDENTIAL_ENV_KEYS.get(normalized, {}).get(field, ()))

    def get_credentials(self, service: str = "", include_env: bool = True):
        save_keys = self.ui.save_keys_checkbox.isChecked()

        if service:
            normalized = self._normalize_credential_service(service)
            creds = {'save_key': save_keys}
            for field in self._credential_fields_for(normalized):
                value = self._credential_widget_value(normalized, field)
                if not value and include_env:
                    value = self._credential_env_value(normalized, field)
                creds[field] = value
            return creds

        return {s: self.get_credentials(s, include_env=include_env) for s in self.ui.credential_services}

        # no `service` passed → recurse over all known services
        
    def get_hd_strategy_settings(self):
        strategy = self.ui.inpaint_strategy_combo.currentText()
        settings = {
            'strategy': strategy
        }

        if strategy == self.ui.tr("Resize"):
            settings['resize_limit'] = self.ui.resize_spinbox.value()
        elif strategy == self.ui.tr("Crop"):
            settings['crop_margin'] = self.ui.crop_margin_spinbox.value()
            settings['crop_trigger_size'] = self.ui.crop_trigger_spinbox.value()

        return settings
    
    def get_all_settings(self):
        return {
            'language': self.get_language(),
            'theme': self.get_theme(),
            'tools': {
                'translator': self.get_tool_selection('translator'),
                'ocr': self.get_tool_selection('ocr'),
                'detector': self.get_tool_selection('detector'),
                'inpainter': self.get_tool_selection('inpainter'),
                'use_gpu': self.is_gpu_enabled(),
                'hd_strategy': self.get_hd_strategy_settings()
            },
            'llm': self.get_llm_settings(),
            'export': self.get_export_settings(),
            'shortcuts': self.ui.shortcuts_page.get_shortcuts(),
            'credentials': self.get_credentials(include_env=False),
            'save_keys': self.ui.save_keys_checkbox.isChecked(),
        }

    def on_shortcut_changed(self, shortcut_id: str, sequence: str) -> None:
        if self._loading_settings:
            return

        settings = QSettings("ComicLabs", "ComicTranslate")
        settings.beginGroup("shortcuts")
        settings.setValue(shortcut_id, sequence)
        settings.endGroup()

        owner = self.window()
        shortcut_ctrl = getattr(owner, "shortcut_ctrl", None)
        if shortcut_ctrl is not None:
            shortcut_ctrl.apply_shortcuts()

    def import_font(self, file_paths: list[str]):

        file_paths = [f for f in file_paths 
                      if f.lower().endswith((".ttf", ".ttc", ".otf", ".woff", ".woff2"))]
        
        # Determine user font directory
        user_font_dir = os.path.join(get_user_data_dir(), "fonts")

        if not os.path.exists(user_font_dir):
            os.makedirs(user_font_dir, exist_ok=True)

        if file_paths:
            loaded_families = []
            for src in file_paths:
                dst = os.path.join(user_font_dir, os.path.basename(src))
                if os.path.normcase(src) != os.path.normcase(dst):
                    shutil.copy(src, dst)
                font_family = self.add_font_family(dst)
                if font_family:
                    loaded_families.append(font_family)

            if loaded_families:
                self.font_imported.emit(loaded_families[0])

    def select_color(self, outline = False):
        default_color = QtGui.QColor('#000000') if not outline else QtGui.QColor('#FFFFFF')
        color_dialog = QtWidgets.QColorDialog()
        color_dialog.setCurrentColor(default_color)
        
        if color_dialog.exec() == QtWidgets.QDialog.Accepted:
            color = color_dialog.selectedColor()
            if color.isValid():
                button = self.ui.color_button if not outline else self.ui.outline_color_button
                button.setStyleSheet(
                    f"background-color: {color.name()}; border: none; border-radius: 5px;"
                )
                button.setProperty('selected_color', color.name())

    # With the mappings, settings are saved with English values and loaded in the selected language
    def save_settings(self):
        settings = QSettings("ComicLabs", "ComicTranslate")
        all_settings = self.get_all_settings()

        def process_group(group_key, group_value, settings_obj: QSettings):
            """Helper function to process a group and its nested values."""
            if is_dataclass(group_value):
                group_value = asdict(group_value)
            if isinstance(group_value, dict):
                settings_obj.beginGroup(group_key)
                for sub_key, sub_value in group_value.items():
                    process_group(sub_key, sub_value, settings_obj)
                settings_obj.endGroup()
            else:
                # Convert value to English using mappings if available
                mapped_value = self.ui.value_mappings.get(group_value, group_value)
                settings_obj.setValue(group_key, mapped_value)

        for key, value in all_settings.items():
            process_group(key, value, settings)

        # Remove deprecated export keys from older versions.
        settings.beginGroup('export')
        settings.remove('auto_save')
        settings.remove('archive_save_as')
        settings.endGroup()

        # Always save credentials so they persist across sessions
        credentials = self.get_credentials(include_env=False)
        settings.beginGroup('credentials')
        for service, cred in credentials.items():
            translated_service = self._normalize_credential_service(service)
            for field in self._credential_fields_for(translated_service):
                settings.setValue(f"{translated_service}_{field}", cred.get(field, ''))
        settings.endGroup()

    def load_settings(self):
        self._loading_settings = True
        settings = QSettings("ComicLabs", "ComicTranslate")

        # Load language
        language = settings.value('language', 'English')
        translated_language = self.ui.reverse_mappings.get(language, language)
        self.ui.lang_combo.setCurrentText(translated_language)

        # Load theme
        theme = settings.value('theme', 'Blue')
        if theme == "Dark":
            theme = "Blue"
        translated_theme = self.ui.reverse_mappings.get(theme, theme)
        # Loading the saved value used to apply the complete application QSS
        # twice: once through currentTextChanged and once through the explicit
        # emission below.  Applying it once keeps startup responsive while
        # preserving the exact same selected theme and final appearance.
        with QSignalBlocker(self.ui.theme_combo):
            self.ui.theme_combo.setCurrentText(translated_theme)
        self.theme_changed.emit(translated_theme)

        # Load tools settings
        settings.beginGroup('tools')
        translator = settings.value('translator', 'Gemini-3.0-Flash')
        translated_translator = self.ui.reverse_mappings.get(translator, translator)
        if self.ui.translator_combo.findText(translated_translator) != -1:
            self.ui.translator_combo.setCurrentText(translated_translator)
        else:
            self.ui.translator_combo.setCurrentIndex(-1)

        ocr = settings.value('ocr', 'Default')
        translated_ocr = self.ui.reverse_mappings.get(ocr, ocr)
        if self.ui.ocr_combo.findText(translated_ocr) != -1:
            self.ui.ocr_combo.setCurrentText(translated_ocr)
        else:
            self.ui.ocr_combo.setCurrentIndex(-1)

        inpainter = settings.value('inpainter', 'AOT')
        translated_inpainter = self.ui.reverse_mappings.get(inpainter, inpainter)
        if self.ui.inpainter_combo.findText(translated_inpainter) != -1:
            self.ui.inpainter_combo.setCurrentText(translated_inpainter)
        else:
            self.ui.inpainter_combo.setCurrentIndex(-1)

        detector = settings.value('detector', 'RT-DETR-v2')
        translated_detector = self.ui.reverse_mappings.get(detector, detector)
        if self.ui.detector_combo.findText(translated_detector) != -1:
            self.ui.detector_combo.setCurrentText(translated_detector)
        else:
            self.ui.detector_combo.setCurrentIndex(-1)

        if is_gpu_available():
            self.ui.use_gpu_checkbox.setChecked(settings.value('use_gpu', False, type=bool))
        else:
            self.ui.use_gpu_checkbox.setChecked(False)

        # Load HD strategy settings
        settings.beginGroup('hd_strategy')
        strategy = settings.value('strategy', 'Resize')
        translated_strategy = self.ui.reverse_mappings.get(strategy, strategy)
        if self.ui.inpaint_strategy_combo.findText(translated_strategy) != -1:
            self.ui.inpaint_strategy_combo.setCurrentText(translated_strategy)
        else:
            self.ui.inpaint_strategy_combo.setCurrentIndex(0)

        if strategy == 'Resize':
            self.ui.resize_spinbox.setValue(settings.value('resize_limit', 960, type=int))
        elif strategy == 'Crop':
            self.ui.crop_margin_spinbox.setValue(settings.value('crop_margin', 512, type=int))
            self.ui.crop_trigger_spinbox.setValue(settings.value('crop_trigger_size', 512, type=int))
        settings.endGroup()  # hd_strategy
        settings.endGroup()  # tools

        # Load LLM settings
        settings.beginGroup('llm')
        self.ui.extra_context.setPlainText(settings.value('extra_context', ''))
        self.ui.image_checkbox.setChecked(settings.value('image_input_enabled', False, type=bool))
        settings.endGroup()

        # Load export settings
        settings.beginGroup('export')
        self.ui.raw_text_checkbox.setChecked(settings.value('export_raw_text', False, type=bool))
        self.ui.translated_text_checkbox.setChecked(settings.value('export_translated_text', False, type=bool))
        self.ui.inpainted_image_checkbox.setChecked(settings.value('export_inpainted_image', False, type=bool))
        autosave_enabled = settings.value('project_autosave_enabled', False, type=bool)
        owner = self.parent()
        title_bar = getattr(owner, "title_bar", None)
        if title_bar is not None:
            title_bar.set_autosave_checked(bool(autosave_enabled))
        self.ui.project_autosave_interval_spinbox.setValue(
            settings.value('project_autosave_interval_min', 3, type=int)
        )
        self.ui.project_autosave_folder_input.setText(
            settings.value('project_autosave_folder', get_default_project_autosave_dir(), type=str)
        )

        settings.endGroup()  # export

        settings.beginGroup('shortcuts')
        default_shortcuts = get_default_shortcuts()
        shortcut_values = {}
        for shortcut_id, default_value in default_shortcuts.items():
            shortcut_values[shortcut_id] = settings.value(shortcut_id, default_value, type=str)
        settings.endGroup()
        self.ui.shortcuts_page.load_shortcuts(shortcut_values)
        owner = self.window()
        shortcut_ctrl = getattr(owner, "shortcut_ctrl", None)
        if shortcut_ctrl is not None:
            shortcut_ctrl.apply_shortcuts()

        # Always load credentials
        settings.beginGroup('credentials')
        for service in self.ui.credential_services:
            translated_service = self._normalize_credential_service(service)
            for field in self._credential_fields_for(translated_service):
                w = self.ui.credential_widgets.get(f"{translated_service}_{field}")
                if w is not None:
                    w.setText(settings.value(f"{translated_service}_{field}", ''))
        settings.endGroup()

        # Initialize current language tracker after loading
        self._current_language = self.ui.lang_combo.currentText()

        self._loading_settings = False


    def on_language_changed(self, new_language):
        if not self._loading_settings:  
            # Pass the previous language so we can revert if needed
            self.show_restart_dialog(new_language)

    def _show_message_box(self, icon: QtWidgets.QMessageBox.Icon, title: str, text: str):
        msg_box = QtWidgets.QMessageBox(self)
        msg_box.setIcon(icon)
        msg_box.setWindowTitle(title)
        msg_box.setText(text)
        ok_btn = msg_box.addButton(self.tr("OK"), QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        msg_box.setDefaultButton(ok_btn)
        msg_box.exec()

    def _ask_yes_no(self, title: str, text: str, default_yes: bool = False) -> bool:
        msg_box = QtWidgets.QMessageBox(self)
        msg_box.setIcon(QtWidgets.QMessageBox.Icon.Question)
        msg_box.setWindowTitle(title)
        msg_box.setText(text)
        yes_btn = msg_box.addButton(self.tr("Yes"), QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        no_btn = msg_box.addButton(self.tr("No"), QtWidgets.QMessageBox.ButtonRole.RejectRole)
        msg_box.setDefaultButton(yes_btn if default_yes else no_btn)
        msg_box.exec()
        return msg_box.clickedButton() == yes_btn

    def show_restart_dialog(self, new_language):
        from modules.utils.common_utils import restart_application
        
        response = self._ask_yes_no(
            self.tr("Restart Required"),
            self.tr("The application needs to restart for the language changes to take effect.\nRestart now?"),
            default_yes=True
        )
        
        if response:
            # Save settings before restarting
            self.save_settings()
            self._current_language = new_language  # Update tracking
            restart_application()
        else:
            # User declined - revert to previous language
            self._loading_settings = True  # Prevent triggering the handler again
            self.ui.lang_combo.setCurrentText(self._current_language)
            self._loading_settings = False



    def get_min_font_size(self):
        return int(self.ui.min_font_spinbox.value())
    
    def get_max_font_size(self):
        return int(self.ui.max_font_spinbox.value())

    def add_font_family(self, font_input: str) -> QFont:
        # Check if font_input is a file path
        if os.path.splitext(font_input)[1].lower() in [".ttf", ".ttc", ".otf", ".woff", ".woff2"]:
            font_id = QFontDatabase.addApplicationFont(font_input)
            if font_id != -1:
                font_families = QFontDatabase.applicationFontFamilies(font_id)
                if font_families:
                    return font_families[0]
        
        # If not a file path or loading failed, treat as font family name
        return font_input
    
    def check_for_updates(self, is_background=False):
        self._is_background_check = is_background
        if not is_background:
            self.ui.check_update_button.setEnabled(False)
            self.ui.check_update_button.setText(self.tr("Checking..."))
        if not self.update_checker.is_configured:
            self.on_update_error(
                self.tr("The Mukai update channel has not been configured for this edition yet.")
            )
            return
        self.update_checker.check_for_updates()

    def on_update_available(self, version, release_notes, download_url, checksum):
        if not self._is_background_check:
            self.ui.check_update_button.setEnabled(True)
            self.ui.check_update_button.setText(self.tr("Check for Updates"))
        
        # Check ignored version
        settings = QSettings("ComicLabs", "ComicTranslate")
        ignored_version = settings.value("updates/ignored_version", "")
        
        if self._is_background_check and version == ignored_version:
            return

        msg_box = QtWidgets.QMessageBox(self)
        msg_box.setWindowTitle(self.tr("Update Available"))
        msg_box.setTextFormat(Qt.RichText)
        msg_box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        msg_box.setText(self.tr("A new version {version} is available.").format(version=version))
        notes_html = release_notes_to_html(release_notes)
        msg_box.setInformativeText(
            f"<p><b>{self.tr('What is new')}</b></p>"
            f"<div style=\"max-width: 440px;\">{notes_html}</div>"
            f"<p>{self.tr('The installer will be verified before it is opened.')}</p>"
        )
        
        download_btn = msg_box.addButton(self.tr("Yes"), QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        cancel_btn = msg_box.addButton(self.tr("No"), QtWidgets.QMessageBox.ButtonRole.RejectRole)
        
        dotted_ask_btn = None
        if self._is_background_check:
            dotted_ask_btn = msg_box.addButton(self.tr("Skip This Version"), QtWidgets.QMessageBox.ButtonRole.ApplyRole)
        
        msg_box.setDefaultButton(download_btn)
        msg_box.exec()

        if msg_box.clickedButton() == download_btn:
            self.start_download(download_url, checksum)
        elif dotted_ask_btn and msg_box.clickedButton() == dotted_ask_btn:
            settings.setValue("updates/ignored_version", version)
    
    def on_up_to_date(self):
        if self._is_background_check:
            return

        self.ui.check_update_button.setEnabled(True)
        self.ui.check_update_button.setText(self.tr("Check for Updates"))
        self._show_message_box(
            QtWidgets.QMessageBox.Icon.Information,
            self.tr("Up to Date"),
            self.tr("You are using the latest version.")
        )

    def on_update_error(self, message):
        if self._is_background_check:
            logger.error(f"Background update check failed: {message}")
            return

        self.ui.check_update_button.setEnabled(True)
        self.ui.check_update_button.setText(self.tr("Check for Updates"))
        if self.update_dialog:
             self.update_dialog.close()
        
        self._show_message_box(
            QtWidgets.QMessageBox.Icon.Warning,
            self.tr("Update Error"),
            message
        )

    def start_download(self, url, checksum):
        # Create a progress dialog
        self.update_dialog = QtWidgets.QProgressDialog(self.tr("Downloading update..."), self.tr("Cancel"), 0, 100, self)
        self.update_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.update_dialog.show()
        
        filename = url.split("/")[-1]
        self.update_checker.download_installer(url, filename, checksum)

    def on_download_progress(self, percent):
        if self.update_dialog:
             self.update_dialog.setValue(percent)

    def on_download_finished(self, file_path):
        if self.update_dialog:
             self.update_dialog.close()
        
        # Ask to install
        if self._ask_yes_no(
            self.tr("Download Complete"),
            self.tr("Installer downloaded to {path}. Run it now?").format(path=file_path),
            default_yes=True
        ):
             self.update_checker.run_installer(file_path)

    def closeEvent(self, event):
        super().closeEvent(event)

    def shutdown(self):
        """Cleanup resources before app exit."""
        if getattr(self, "_is_shutting_down", False):
            return
        self._is_shutting_down = True

        try:
            self.update_checker.shutdown()
        except Exception:
            pass
    




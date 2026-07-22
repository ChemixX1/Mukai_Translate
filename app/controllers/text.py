from __future__ import annotations

import os
import copy
import numpy as np
from typing import TYPE_CHECKING

from PySide6 import QtCore
from PySide6.QtGui import QColor, QCursor, QTextCursor

from app.ui.commands.textformat import TextFormatCommand
from app.ui.commands.box import AddTextItemCommand, ResizeBlocksCommand
from app.ui.commands.text_edit import TextEditCommand
from app.ui.canvas.text_item import TextBlockItem
from app.ui.canvas.text.text_item_properties import TextItemProperties

from modules.utils.textblock import TextBlock
from modules.rendering.render import TextRenderingSettings, manual_wrap, is_vertical_block, pyside_word_wrap
from modules.utils.pipeline_config import font_selected
from modules.utils.language_utils import get_language_code, get_layout_direction, is_no_space_lang
from modules.utils.image_utils import get_smart_text_color
from modules.utils.common_utils import is_close
from modules.utils.translator_utils import format_translations

if TYPE_CHECKING:
    from controller import ComicTranslate

class TextController:
    def __init__(self, main: ComicTranslate):
        self.main = main

        # List of widgets to block signals for during manual rendering
        self.widgets_to_block = [
            self.main.font_dropdown,
            self.main.font_size_dropdown,
            self.main.line_spacing_dropdown,
            self.main.block_font_color_button,
            self.main.outline_font_color_button,
            self.main.outline_width_dropdown,
            self.main.outline_checkbox
        ]
        self._text_change_timer = QtCore.QTimer(self.main)
        self._text_change_timer.setSingleShot(True)
        self._text_change_timer.setInterval(400)
        self._text_change_timer.timeout.connect(self._commit_pending_text_command)
        self._pending_text_command = None
        self._last_item_text = {}
        self._last_item_html = {}
        self._suspend_text_command = False
        self._is_updating_from_edit = False
        self._render_macro_stack = None
        self._copied_text_style: dict | None = None
        self._text_fill_preview_session = None
        self._typography_adjustment_stack = None
        if hasattr(self.main, "text_effects_panel"):
            self.main.text_effects_panel.effectChanged.connect(
                self.on_text_effect_changed
            )

    def connect_text_item_signals(self, text_item: TextBlockItem, force_reconnect: bool = False):
        if getattr(text_item, "_ct_signals_connected", False) and not force_reconnect:
            return

        if force_reconnect:
            try:
                text_item.item_selected.disconnect(self.on_text_item_selected)
            except (TypeError, RuntimeError):
                pass
            try:
                text_item.item_deselected.disconnect(self.on_text_item_deselected)
            except (TypeError, RuntimeError):
                pass
            if hasattr(text_item, "_ct_text_changed_slot"):
                try:
                    text_item.text_changed.disconnect(text_item._ct_text_changed_slot)
                except (TypeError, RuntimeError):
                    pass
            try:
                text_item.text_highlighted.disconnect(self.set_values_from_highlight)
            except (TypeError, RuntimeError):
                pass
            try:
                text_item.change_undo.disconnect(self.main.rect_item_ctrl.rect_change_undo)
            except (TypeError, RuntimeError):
                pass
            if hasattr(text_item, "_ct_delete_requested_slot"):
                try:
                    text_item.delete_requested.disconnect(text_item._ct_delete_requested_slot)
                except (TypeError, RuntimeError):
                    pass

        if not hasattr(text_item, "_ct_text_changed_slot"):
            text_item._ct_text_changed_slot = (
                lambda text, ti=text_item: self.update_text_block_from_item(ti, text)
            )
        if not hasattr(text_item, "_ct_delete_requested_slot"):
            text_item._ct_delete_requested_slot = (
                lambda _item, ti=text_item: self._delete_requested_text_item(ti)
            )

        text_item.item_selected.connect(self.on_text_item_selected)
        text_item.item_deselected.connect(self.on_text_item_deselected)
        text_item.text_changed.connect(text_item._ct_text_changed_slot)
        text_item.text_highlighted.connect(self.set_values_from_highlight)
        text_item.change_undo.connect(self.main.rect_item_ctrl.rect_change_undo)
        text_item.delete_requested.connect(text_item._ct_delete_requested_slot)
        self._last_item_text[text_item] = text_item.toPlainText()
        self._last_item_html[text_item] = text_item.document().toHtml()
        text_item._ct_signals_connected = True

    def _delete_requested_text_item(self, text_item: TextBlockItem) -> None:
        if text_item not in self.main.image_viewer.get_selected_text_items():
            self.main.image_viewer.deselect_all()
            text_item.selected = True
            text_item.setSelected(True)
        self.main.delete_selected_box()

    def clear_text_edits(self):
        self.commit_text_fill_preview()
        self.main.curr_tblock = None
        self.main.curr_tblock_item = None
        self.main.s_text_edit.clear()
        self.main.t_text_edit.clear()
        if hasattr(self.main, "text_effects_button"):
            self.main.text_effects_button.setEnabled(False)
        if hasattr(self.main, "set_text_selection_controls_enabled"):
            self.main.set_text_selection_controls_enabled(False)
        for menu_name in ("line_spacing_menu", "text_opacity_menu"):
            menu = getattr(self.main, menu_name, None)
            if menu is not None:
                menu.hide()
        if hasattr(self.main, "text_effects_panel"):
            self.main.text_effects_panel.clear_selection()
        if hasattr(self.main, "show_main_right_panel"):
            self.main.show_main_right_panel()

    def on_blk_rendered(self, text: str, font_size: int, blk: TextBlock, image_path: str):
        if not self.main.webtoon_mode:
            if self.main.curr_img_idx < 0 or self.main.curr_img_idx >= len(self.main.image_files):
                return
            current_file = self.main.image_files[self.main.curr_img_idx]
            if os.path.normcase(current_file) != os.path.normcase(image_path):
                return

        if not self.main.image_viewer.hasPhoto():
            print("No main image to add to.")
            return

        target_lang = self.main.lang_mapping.get(self.main.t_combo.currentText(), None)
        trg_lng_cd = get_language_code(target_lang)
        if is_no_space_lang(trg_lng_cd):
            text = text.replace(' ', '')

        render_settings = self.render_settings()
        font_family = render_settings.font_family
        text_color_str = render_settings.color
        text_color = QColor(text_color_str)

        # Smart Color Override
        text_color = get_smart_text_color(blk.font_color, text_color)

        id = render_settings.alignment_id
        alignment = self.main.button_to_alignment[id]
        line_spacing = float(render_settings.line_spacing)
        outline_color_str = render_settings.outline_color
        outline_color = QColor(outline_color_str) if self.main.outline_checkbox.isChecked() else None
        outline_width = float(render_settings.outline_width)
        bold = render_settings.bold
        italic = render_settings.italic
        underline = render_settings.underline
        direction = render_settings.direction
        vertical = is_vertical_block(blk, trg_lng_cd)

        properties = TextItemProperties(
            text=text,
            font_family=font_family,
            font_size=font_size,
            text_color=text_color,
            alignment=alignment,
            line_spacing=line_spacing,
            outline_color=outline_color,
            outline_width=outline_width,
            bold=bold,
            italic=italic,
            underline=underline,
            direction=direction,
            position=(blk.xyxy[0], blk.xyxy[1]),
            rotation=blk.angle,
            vertical=vertical,
            fill_style=copy.deepcopy(
                self.main.block_font_color_button.property('fill_style') or {}
            ),
        )
        
        text_item = self.main.image_viewer.add_text_item(properties)
        prev_suspend = self._suspend_text_command
        self._suspend_text_command = True
        try:
            if is_no_space_lang(trg_lng_cd):
                text_item.set_plain_text(text)
            else:
                # Store as a single re-flowable paragraph so the box re-wraps
                # its content when the user changes its width.
                text_item.set_rendered_text(text)
        finally:
            self._suspend_text_command = prev_suspend
            self._last_item_text[text_item] = text_item.toPlainText()
            self._last_item_html[text_item] = text_item.document().toHtml()

        command = AddTextItemCommand(self.main, text_item)
        self.main.push_command(command)

    def on_text_item_selected(self, text_item: TextBlockItem):
        self._commit_pending_text_command()
        self.commit_text_fill_preview()
        self.main.curr_tblock_item = text_item
        self._last_item_text[text_item] = text_item.toPlainText()
        self._last_item_html[text_item] = text_item.document().toHtml()

        x1, y1 = int(text_item.pos().x()), int(text_item.pos().y())
        rotation = text_item.rotation()

        self.main.curr_tblock = next(
            (
            blk for blk in self.main.blk_list
            if is_close(blk.xyxy[0], x1, 5) and is_close(blk.xyxy[1], y1, 5)
            and is_close(blk.angle, rotation, 1)
            ),
            None
        )

        # Update both s_text_edit and t_text_edit
        if self.main.curr_tblock:
            self.main.s_text_edit.blockSignals(True)
            self.main.s_text_edit.setPlainText(self.main.curr_tblock.text)
            self.main.s_text_edit.blockSignals(False)

        self.main.t_text_edit.blockSignals(True)
        self.main.t_text_edit.setPlainText(text_item.toPlainText())
        self.main.t_text_edit.blockSignals(False)

        self.set_values_for_blk_item(text_item)
        if hasattr(self.main, "text_effects_button"):
            self.main.text_effects_button.setEnabled(True)
        if hasattr(self.main, "set_text_selection_controls_enabled"):
            self.main.set_text_selection_controls_enabled(True)
        if hasattr(self.main, "text_effects_panel"):
            selected_items = self._selected_text_items()
            self.main.text_effects_panel.set_selection(
                text_item.toPlainText(),
                text_item.get_visual_style(),
                len(selected_items),
            )

    def on_text_item_deselected(self):
        self._commit_pending_text_command()
        selected_items = self.main.image_viewer.get_selected_text_items()
        if selected_items:
            if self.main.curr_tblock_item not in selected_items:
                self.on_text_item_selected(selected_items[-1])
            return
        self.clear_text_edits()

    def _selected_text_items(self) -> list[TextBlockItem]:
        selected_items = self.main.image_viewer.get_selected_text_items()
        if selected_items:
            return selected_items
        return [self.main.curr_tblock_item] if self.main.curr_tblock_item else []

    def _apply_format_to_selected(self, macro_name: str, apply_fn):
        items = self._selected_text_items()
        if not items:
            return

        commands = []
        for item in items:
            old_item = copy.copy(item)
            apply_fn(item)
            commands.append(TextFormatCommand(self.main.image_viewer, old_item, item))

        stack = self.main.undo_group.activeStack()
        if stack is None:
            return

        if len(commands) > 1:
            stack.beginMacro(macro_name)
        try:
            for command in commands:
                stack.push(command)
        finally:
            if len(commands) > 1:
                stack.endMacro()

        if self.main.curr_tblock_item in items:
            self.set_values_for_blk_item(self.main.curr_tblock_item)

    def update_text_block(self):
        if self.main.curr_tblock:
            self.main.curr_tblock.text = self.main.s_text_edit.toPlainText()
            self.main.curr_tblock.translation = self.main.t_text_edit.toPlainText()
            self.main.mark_project_dirty()

    def update_text_block_from_edit(self):
        self._is_updating_from_edit = True
        try:
            new_text = self.main.t_text_edit.toPlainText()
            old_translation = None
            old_item_text = None
            if self.main.curr_tblock:
                old_translation = self.main.curr_tblock.translation
                self.main.curr_tblock.translation = new_text

            if self.main.curr_tblock_item and self.main.curr_tblock_item in self.main.image_viewer._scene.items():
                old_item_text = self.main.curr_tblock_item.toPlainText()
                cursor_position = self.main.t_text_edit.textCursor().position()
                self._apply_text_item_text_delta(self.main.curr_tblock_item, new_text)

                # Restore cursor position
                cursor = self.main.t_text_edit.textCursor()
                cursor.setPosition(cursor_position)
                self.main.t_text_edit.setTextCursor(cursor)
            if (old_translation is None or old_translation == new_text) and (
                old_item_text is None or old_item_text == new_text
            ):
                return
        finally:
            self._is_updating_from_edit = False

    def update_text_block_from_item(self, text_item: TextBlockItem, new_text: str):
        if self._suspend_text_command:
            return
        blk = self._find_text_block_for_item(text_item)
        if blk:
            blk.translation = new_text

        if self.main.curr_tblock_item == text_item and not self._is_updating_from_edit:
            self.main.curr_tblock = blk
            self.main.t_text_edit.blockSignals(True)
            self.main.t_text_edit.setPlainText(new_text)
            self.main.t_text_edit.blockSignals(False)
            self._sync_case_button(text_item)

        self._schedule_text_change_command(text_item, new_text, blk)

    def _apply_text_item_text_delta(self, text_item: TextBlockItem, new_text: str):
        old_text = text_item.toPlainText()
        if old_text == new_text:
            return

        prefix = 0
        max_prefix = min(len(old_text), len(new_text))
        while prefix < max_prefix and old_text[prefix] == new_text[prefix]:
            prefix += 1

        suffix = 0
        max_suffix = min(len(old_text) - prefix, len(new_text) - prefix)
        while suffix < max_suffix and old_text[-(suffix + 1)] == new_text[-(suffix + 1)]:
            suffix += 1

        old_mid_end = len(old_text) - suffix
        new_mid_end = len(new_text) - suffix
        old_mid = old_text[prefix:old_mid_end]
        new_mid = new_text[prefix:new_mid_end]

        doc = text_item.document()
        cursor = QTextCursor(doc)
        insert_format = None

        if old_text:
            if prefix < len(old_text):
                cursor.setPosition(prefix)
                insert_format = cursor.charFormat()
            elif prefix > 0:
                cursor.setPosition(prefix - 1)
                insert_format = cursor.charFormat()

        cursor.beginEditBlock()
        if old_mid:
            cursor.setPosition(prefix)
            cursor.setPosition(prefix + len(old_mid), QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
        if new_mid:
            cursor.setPosition(prefix)
            if insert_format is not None:
                cursor.setCharFormat(insert_format)
            cursor.insertText(new_mid)
        cursor.endEditBlock()

    def save_src_trg(self):
        source_lang = self.main.s_combo.currentText()
        target_lang = self.main.t_combo.currentText()
        
        if self.main.curr_img_idx >= 0:
            current_file = self.main.image_files[self.main.curr_img_idx]
            self.main.image_states[current_file]['source_lang'] = source_lang
            self.main.image_states[current_file]['target_lang'] = target_lang

        target_en = self.main.lang_mapping.get(target_lang, None)
        t_direction = get_layout_direction(target_en)
        t_text_option = self.main.t_text_edit.document().defaultTextOption()
        t_text_option.setTextDirection(t_direction)
        self.main.t_text_edit.document().setDefaultTextOption(t_text_option)

        if self.main.curr_img_idx >= 0:
            self.main.mark_project_dirty()

    def set_src_trg_all(self):
        source_lang = self.main.s_combo.currentText()
        target_lang = self.main.t_combo.currentText()
        for image_path in self.main.image_files:
            self.main.image_states[image_path]['source_lang'] = source_lang
            self.main.image_states[image_path]['target_lang'] = target_lang
        if self.main.image_files:
            self.main.mark_project_dirty()

    def change_all_blocks_size(self, diff: int):
        if len(self.main.blk_list) == 0:
            return
        command = ResizeBlocksCommand(self.main, self.main.blk_list, diff)
        stack = self.main.undo_group.activeStack()
        if stack:
            stack.push(command)
        else:
            command.redo()
            self.main.mark_project_dirty()

    def _find_text_block_for_item(self, text_item: TextBlockItem) -> TextBlock | None:
        if not text_item:
            return None

        x1, y1 = int(text_item.pos().x()), int(text_item.pos().y())
        rotation = text_item.rotation()

        return next(
            (
                blk for blk in self.main.blk_list
                if is_close(blk.xyxy[0], x1, 5)
                and is_close(blk.xyxy[1], y1, 5)
                and is_close(blk.angle, rotation, 1)
            ),
            None
        )

    def _schedule_text_change_command(self, text_item: TextBlockItem, new_text: str, blk: TextBlock | None):
        if self._suspend_text_command:
            return

        pending = self._pending_text_command
        if pending and pending['item'] is not text_item:
            self._commit_pending_text_command()
            pending = None

        new_html = text_item.document().toHtml()
        if pending is None:
            old_text = self._last_item_text.get(text_item, new_text)
            old_html = self._last_item_html.get(text_item, new_html)
            if old_text == new_text:
                self._last_item_text[text_item] = new_text
                self._last_item_html[text_item] = new_html
                return
            pending = {
                'item': text_item,
                'old_text': old_text,
                'new_text': new_text,
                'old_html': old_html,
                'new_html': new_html,
                'blk': blk,
            }
            self._pending_text_command = pending
        else:
            pending['new_text'] = new_text
            pending['new_html'] = new_html
            pending['blk'] = blk

        self._last_item_text[text_item] = new_text
        self._last_item_html[text_item] = new_html
        self._text_change_timer.start()

    def _commit_pending_text_command(self):
        if not self._pending_text_command:
            return
        self._text_change_timer.stop()
        pending = self._pending_text_command
        self._pending_text_command = None

        if pending['old_text'] == pending['new_text']:
            return

        command = TextEditCommand(
            self.main,
            pending['item'],
            pending['old_text'],
            pending['new_text'],
            old_html=pending.get('old_html'),
            new_html=pending.get('new_html'),
            blk=pending['blk']
        )
        stack = self.main.undo_group.activeStack()
        if stack:
            stack.push(command)
        else:
            command.redo()
            self.main.mark_project_dirty()

    def apply_text_from_command(self, text_item: TextBlockItem, text: str,
                                html: str | None = None, blk: TextBlock | None = None):
        self._suspend_text_command = True
        try:
            if text_item and text_item in self.main.image_viewer._scene.items():
                if html is not None:
                    if text_item.document().toHtml() != html:
                        text_item.document().setHtml(html)
                elif text_item.toPlainText() != text:
                    text_item.set_plain_text(text)
            if blk is None:
                blk = self._find_text_block_for_item(text_item)
            if blk:
                blk.translation = text
            if self.main.curr_tblock_item == text_item:
                self.main.curr_tblock = blk
                # Only update if the text is actually different to avoid cursor reset
                if self.main.t_text_edit.toPlainText() != text:
                    self.main.t_text_edit.blockSignals(True)
                    self.main.t_text_edit.setPlainText(text)
                    self.main.t_text_edit.blockSignals(False)
        finally:
            self._suspend_text_command = False
        if text_item:
            self._last_item_text[text_item] = text
            self._last_item_html[text_item] = text_item.document().toHtml()
            if self.main.curr_tblock_item == text_item:
                self._sync_case_button(text_item)

    # Formatting actions
    def on_font_dropdown_change(self, font_family: str):
        if hasattr(self.main, "font_family_button") and font_family:
            self.main.font_family_button.setText(font_family)
        if self._selected_text_items() and font_family:
            font_size = int(self.main.font_size_dropdown.currentText())
            self._apply_format_to_selected(
                "change_text_font",
                lambda item: item.set_font(font_family, font_size),
            )

    # Most-used font ordering
    _FONT_USAGE_GROUP = "text_rendering/font_usage"
    _MOST_USED_FONT_COUNT = 6

    def _load_font_usage(self) -> dict[str, int]:
        settings = QtCore.QSettings("ComicLabs", "ComicTranslate")
        settings.beginGroup(self._FONT_USAGE_GROUP)
        usage: dict[str, int] = {}
        for key in settings.childKeys():
            try:
                usage[key] = int(settings.value(key, 0))
            except (TypeError, ValueError):
                continue
        settings.endGroup()
        return usage

    def _save_font_usage(self, usage: dict[str, int]) -> None:
        settings = QtCore.QSettings("ComicLabs", "ComicTranslate")
        settings.beginGroup(self._FONT_USAGE_GROUP)
        settings.remove("")
        for family, count in usage.items():
            # "/" is a group separator for QSettings; skip families that would
            # be stored as nested keys to keep the counts round-trippable.
            if "/" in family or "\\" in family:
                continue
            settings.setValue(family, int(count))
        settings.endGroup()

    def record_font_used(self, font_family: str, *, reorder: bool = True) -> None:
        family = (font_family or "").strip()
        if not family:
            return
        # Only count real families that exist in the dropdown, ignoring the
        # partial text produced while typing in the editable combo box.
        if self.main.font_dropdown.findText(family) < 0:
            return
        usage = self._load_font_usage()
        usage[family] = usage.get(family, 0) + 1
        self._save_font_usage(usage)
        if reorder:
            self.apply_most_used_font_order()

    def apply_most_used_font_order(self) -> None:
        usage = self._load_font_usage()
        if not usage:
            return
        ranked = sorted(usage.items(), key=lambda kv: (-kv[1], kv[0]))
        top = [family for family, count in ranked[: self._MOST_USED_FONT_COUNT] if count > 0]
        if top:
            self.main.font_dropdown.set_priority_families(top)

    def on_font_size_change(self, font_size: str):
        if self._selected_text_items() and font_size:
            try:
                font_size = float(font_size)
            except (TypeError, ValueError):
                return
            if not 1.0 <= font_size <= 999.0:
                return
            self._apply_format_to_selected(
                "change_text_font_size",
                lambda item: item.set_font_size(font_size),
            )

    def on_font_weight_change(self, weight) -> None:
        try:
            weight = int(weight)
        except (TypeError, ValueError):
            return
        if not self._selected_text_items():
            return
        self._apply_format_to_selected(
            "change_text_font_weight",
            lambda item: item.set_font_weight(weight),
        )
        self.main.bold_button.setChecked(weight >= 600)
        self.main.set_font_weight_menu_value(weight)

    def on_line_spacing_change(self, line_spacing: str):
        if self._selected_text_items() and line_spacing:
            try:
                spacing = float(line_spacing)
            except (TypeError, ValueError):
                return
            self.main.set_line_spacing_menu_value(line_spacing)
            self._apply_format_to_selected(
                "change_text_line_spacing",
                lambda item: item.set_line_spacing(spacing),
            )

    def on_letter_spacing_change(self, letter_spacing) -> None:
        if not self._selected_text_items():
            return
        try:
            spacing = float(letter_spacing)
        except (TypeError, ValueError):
            return
        self._apply_format_to_selected(
            "change_text_letter_spacing",
            lambda item: item.set_letter_spacing(spacing),
        )

    def begin_typography_adjustment(self, kind: str) -> None:
        if self._typography_adjustment_stack is not None:
            return
        stack = self.main.undo_group.activeStack()
        if stack is None or not self._selected_text_items():
            return
        stack.beginMacro(f"adjust_text_{kind}")
        self._typography_adjustment_stack = stack

    def end_typography_adjustment(self) -> None:
        stack = self._typography_adjustment_stack
        self._typography_adjustment_stack = None
        if stack is not None:
            stack.endMacro()

    def on_text_opacity_change(self) -> None:
        if not self._selected_text_items():
            return
        opacity = self.main.text_opacity_slider.value()
        self._apply_format_to_selected(
            "change_text_opacity",
            lambda item: item.set_text_opacity(opacity),
        )

    def copy_text_style(self) -> None:
        items = self._selected_text_items()
        if not items:
            return
        item = items[-1]
        self._copied_text_style = {
            "font_family": item.font_family,
            "font_size": float(item.font_size),
            "font_weight": int(getattr(item, "font_weight", 700 if item.bold else 400)),
            "italic": bool(item.italic),
            "underline": bool(item.underline),
            "alignment": item.alignment,
            "line_spacing": float(item.line_spacing),
            "letter_spacing": float(getattr(item, "letter_spacing", 0.0)),
            "outline": bool(item.outline),
            "outline_color": QColor(item.outline_color) if item.outline_color else None,
            "outline_width": float(item.outline_width),
            "opacity": round(item.opacity() * 100),
            "visual_style": item.get_visual_style(),
        }
        self.main.apply_style_action.setEnabled(True)
        self.main.style_copy_button.setToolTip(
            QtCore.QCoreApplication.translate(
                "WorkspaceMixin",
                "Style copied. Click another text box to apply it.",
            )
        )

    def begin_style_paint(self, checked: bool = True) -> None:
        """Copy the selected appearance and arm a one-click paint operation."""
        viewer = self.main.image_viewer
        if not checked:
            viewer.cancel_style_paint()
            return
        if not self._selected_text_items():
            with QtCore.QSignalBlocker(self.main.style_copy_button):
                self.main.style_copy_button.setChecked(False)
            return

        self.copy_text_style()
        pixmap = self.main.style_copy_button.icon().pixmap(28, 28)
        cursor = (
            QCursor(pixmap, 3, max(0, pixmap.height() - 3))
            if not pixmap.isNull()
            else QCursor(QtCore.Qt.CursorShape.DragCopyCursor)
        )
        viewer.start_style_paint(cursor)
        self.main.style_copy_button.setToolTip(
            QtCore.QCoreApplication.translate(
                "WorkspaceMixin",
                "Style painter active. Click a target text box; right-click to cancel.",
            )
        )

    def apply_style_paint_target(self, target: TextBlockItem) -> None:
        if not self._copied_text_style or target not in self.main.image_viewer.text_items:
            self.main.image_viewer.cancel_style_paint()
            return

        viewer = self.main.image_viewer
        viewer.deselect_all()
        target.selected = True
        target.setSelected(True)
        target.item_selected.emit(target)
        self.apply_copied_text_style()
        viewer.cancel_style_paint()

    def on_style_paint_cancelled(self) -> None:
        with QtCore.QSignalBlocker(self.main.style_copy_button):
            self.main.style_copy_button.setChecked(False)
        self.main.style_copy_button.setToolTip(
            QtCore.QCoreApplication.translate(
                "WorkspaceMixin",
                "Paint the selected text style onto another text box",
            )
        )

    def apply_copied_text_style(self) -> None:
        style = copy.deepcopy(self._copied_text_style)
        if not style or not self._selected_text_items():
            return

        def apply_style(item: TextBlockItem) -> None:
            item.set_font(style["font_family"], style["font_size"])
            item.set_font_weight(style["font_weight"])
            item.set_italic(style["italic"])
            item.set_underline(style["underline"])
            item.set_alignment(style["alignment"])
            item.set_line_spacing(style["line_spacing"])
            item.set_letter_spacing(style["letter_spacing"])
            item.set_visual_style(style["visual_style"])
            if style["outline"] and style["outline_color"] is not None:
                item.set_outline(style["outline_color"], style["outline_width"])
            else:
                item.set_outline(None, None)
            item.set_text_opacity(style["opacity"])

        self._apply_format_to_selected("apply_copied_text_style", apply_style)

    def add_quick_text_box(self):
        """Add an immediately editable text item at the center of the view."""
        viewer = self.main.image_viewer
        if not viewer.hasPhoto():
            return

        settings = QtCore.QSettings("ComicLabs", "ComicTranslate")
        settings.beginGroup("text_rendering")
        default_font_family = str(settings.value("font_family", "") or "")
        default_color = QColor(settings.value("color", "#000000"))
        if not default_color.isValid():
            default_color = QColor("#000000")
        default_alignment_id = settings.value("alignment_id", 1, type=int)
        default_line_spacing = settings.value("line_spacing", "1.0")
        settings.endGroup()

        try:
            default_line_spacing = float(default_line_spacing)
        except (TypeError, ValueError):
            default_line_spacing = 1.0
        default_alignment = self.main.button_to_alignment.get(
            int(default_alignment_id),
            QtCore.Qt.AlignmentFlag.AlignCenter,
        )
        direction = get_layout_direction(
            self.main.lang_mapping.get(self.main.t_combo.currentText(), None)
        )
        font_size = 12.0
        text_width = 180.0
        center = viewer.constrain_point(
            viewer.mapToScene(viewer.viewport().rect().center())
        )
        clean_fill_style = {
            "mode": "solid",
            "color": default_color.name(QColor.NameFormat.HexArgb),
        }
        properties = TextItemProperties(
            text="Escribe algo",
            font_family=default_font_family,
            font_size=font_size,
            text_color=QColor(default_color),
            alignment=default_alignment,
            line_spacing=default_line_spacing,
            letter_spacing=0.0,
            outline_color=None,
            outline_width=1.0,
            bold=False,
            font_weight=400,
            italic=False,
            underline=False,
            opacity=1.0,
            direction=direction,
            position=(center.x() - text_width / 2.0, center.y() - font_size),
            width=text_width,
            fill_style=clean_fill_style,
            warp={},
        )
        text_item = viewer.add_text_item(properties)
        self.main.push_command(AddTextItemCommand(self.main, text_item))

        viewer.deselect_all()
        text_item.selected = True
        text_item.setSelected(True)
        text_item.item_selected.emit(text_item)
        text_item.enter_editing_mode()
        cursor = text_item.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        text_item.setTextCursor(cursor)

    def on_font_color_change(self):
        selected_items = self._selected_text_items()
        current_style = (
            selected_items[0].get_visual_style()
            if selected_items and hasattr(selected_items[0], 'get_visual_style')
            else self.main.block_font_color_button.property('fill_style')
        )
        fill_style = self.main.get_text_fill_style(current_style)
        if not fill_style:
            return

        self.apply_text_fill_style(fill_style)

    def apply_text_fill_style(self, fill_style: dict) -> None:
        selected_items = self._selected_text_items()
        if not fill_style:
            return
        self._set_fill_button_preview(fill_style)
        if selected_items:
            self._apply_format_to_selected(
                "change_text_fill",
                lambda item: item.set_visual_style(fill_style),
            )

    def preview_text_fill_style(self, fill_style: dict) -> None:
        """Render inspector changes immediately without flooding the undo stack."""
        items = self._selected_text_items()
        if not fill_style or not items:
            return
        active_items = tuple(item for item, _old in self._text_fill_preview_session or ())
        if active_items and active_items != tuple(items):
            self.commit_text_fill_preview()
        if self._text_fill_preview_session is None:
            self._text_fill_preview_session = [
                (item, copy.copy(item))
                for item in items
            ]
        self._set_fill_button_preview(fill_style)
        for item in items:
            item.set_visual_style(fill_style)

    def commit_text_fill_preview(self, fill_style: dict | None = None) -> None:
        """Commit one undoable command for a completed live-preview gesture."""
        session = self._text_fill_preview_session
        if session is None:
            if fill_style:
                self.apply_text_fill_style(fill_style)
            return

        if fill_style:
            self._set_fill_button_preview(fill_style)
            for item, _old_item in session:
                if item in self.main.image_viewer.text_items:
                    item.set_visual_style(fill_style)

        self._text_fill_preview_session = None
        commands = []
        for item, old_item in session:
            if item not in self.main.image_viewer.text_items:
                continue
            if old_item.get_visual_style() == item.get_visual_style():
                continue
            commands.append(
                TextFormatCommand(self.main.image_viewer, old_item, item)
            )
        stack = self.main.undo_group.activeStack()
        if stack is None or not commands:
            return
        if len(commands) > 1:
            stack.beginMacro("change_text_fill")
        try:
            for command in commands:
                stack.push(command)
        finally:
            if len(commands) > 1:
                stack.endMacro()

    def on_text_effect_changed(
        self,
        effect_key: str,
        effect_value: dict,
        macro_name: str,
    ) -> None:
        """Apply one effect while preserving each selected text's own fill."""
        valid_keys = {
            "glow",
            "drop_shadow",
            "inner_glow",
            "inner_shadow",
            "stroke",
            "warp",
            "three_d",
        }
        if effect_key != "__reset__" and effect_key not in valid_keys:
            return

        def apply_effect(item: TextBlockItem) -> None:
            style = item.get_visual_style()
            if effect_key == "__reset__":
                for key in valid_keys:
                    current = style.get(key, {})
                    if isinstance(current, dict):
                        current = copy.deepcopy(current)
                        current["enabled"] = False
                        style[key] = current
            else:
                style[effect_key] = copy.deepcopy(effect_value)
            item.set_visual_style(style)

        self._apply_format_to_selected(macro_name, apply_effect)

    def _set_fill_button_preview(self, fill_style: dict) -> None:
        """Persist the default style and show a useful swatch in the toolbar."""
        style = copy.deepcopy(fill_style)
        colour = QColor(style.get('color', '#000000'))
        if style.get('mode') == 'gradient':
            stops = style.get('gradient', {}).get('stops', [])
            if stops:
                colour = QColor(stops[0].get('color', '#000000'))
        if not colour.isValid():
            colour = QColor('#000000')
        self.main.block_font_color_button.setStyleSheet(
            f"background-color: {colour.name()}; border: none; border-radius: 5px;"
        )
        self.main.block_font_color_button.setProperty('selected_color', colour.name())
        self.main.block_font_color_button.setProperty('fill_style', style)
        if (
            hasattr(self.main, "set_fill_inspector_style")
            and not getattr(self.main, "_fill_inspector_applying", False)
        ):
            self.main.set_fill_inspector_style(style)

    def left_align(self):
        if self.main.curr_tblock_item:
            old_item = copy.copy(self.main.curr_tblock_item)
            self.main.curr_tblock_item.set_alignment(QtCore.Qt.AlignmentFlag.AlignLeft)

            command = TextFormatCommand(self.main.image_viewer, old_item, self.main.curr_tblock_item)
            self.main.push_command(command)

    def center_align(self):
        if self.main.curr_tblock_item:
            old_item = copy.copy(self.main.curr_tblock_item)
            self.main.curr_tblock_item.set_alignment(QtCore.Qt.AlignmentFlag.AlignCenter)

            command = TextFormatCommand(self.main.image_viewer, old_item, self.main.curr_tblock_item)
            self.main.push_command(command)

    def right_align(self):
        if self.main.curr_tblock_item:
            old_item = copy.copy(self.main.curr_tblock_item)
            self.main.curr_tblock_item.set_alignment(QtCore.Qt.AlignmentFlag.AlignRight)

            command = TextFormatCommand(self.main.image_viewer, old_item, self.main.curr_tblock_item)
            self.main.push_command(command)

    def justify_align(self):
        if self.main.curr_tblock_item:
            old_item = copy.copy(self.main.curr_tblock_item)
            self.main.curr_tblock_item.set_alignment(QtCore.Qt.AlignmentFlag.AlignJustify)

            command = TextFormatCommand(self.main.image_viewer, old_item, self.main.curr_tblock_item)
            self.main.push_command(command)

    def bold(self):
        if self.main.curr_tblock_item:
            old_item = copy.copy(self.main.curr_tblock_item)
            state = self.main.bold_button.isChecked()
            self.main.curr_tblock_item.set_bold(state)

            command = TextFormatCommand(self.main.image_viewer, old_item, self.main.curr_tblock_item)
            self.main.push_command(command)

    def italic(self):
        if self.main.curr_tblock_item:
            old_item = copy.copy(self.main.curr_tblock_item)
            state = self.main.italic_button.isChecked()
            self.main.curr_tblock_item.set_italic(state)

            command = TextFormatCommand(self.main.image_viewer, old_item, self.main.curr_tblock_item)
            self.main.push_command(command)

    def underline(self):
        if self.main.curr_tblock_item:
            old_item = copy.copy(self.main.curr_tblock_item)
            state = self.main.underline_button.isChecked()
            self.main.curr_tblock_item.set_underline(state)

            command = TextFormatCommand(self.main.image_viewer, old_item, self.main.curr_tblock_item)
            self.main.push_command(command)

    def to_uppercase(self, checked=True):
        """Toggle selected text between uppercase and lowercase.

        When editing a box with an active selection, only the selected text is
        transformed; otherwise the whole selected text box is transformed.
        """
        items = self._selected_text_items()
        if not items:
            return
        make_uppercase = bool(checked)

        # Flush any pending typing edit so its command stays separate from this one.
        self._commit_pending_text_command()

        changes = []
        self._suspend_text_command = True
        try:
            for item in items:
                if item not in self.main.image_viewer._scene.items():
                    continue
                old_text = item.toPlainText()
                old_html = item.document().toHtml()
                if not self._change_case_text_item(item, make_uppercase):
                    continue
                new_text = item.toPlainText()
                new_html = item.document().toHtml()
                blk = self._find_text_block_for_item(item)
                changes.append((item, old_text, new_text, old_html, new_html, blk))
                self._last_item_text[item] = new_text
                self._last_item_html[item] = new_html
        finally:
            self._suspend_text_command = False

        if not changes:
            self._sync_case_button()
            return

        stack = self.main.undo_group.activeStack()
        if stack is not None:
            if len(changes) > 1:
                stack.beginMacro(
                    "uppercase_text" if make_uppercase else "lowercase_text"
                )
            try:
                for item, old_text, new_text, old_html, new_html, blk in changes:
                    stack.push(
                        TextEditCommand(self.main, item, old_text, new_text, old_html, new_html, blk)
                    )
            finally:
                if len(changes) > 1:
                    stack.endMacro()
        else:
            for item, old_text, new_text, old_html, new_html, blk in changes:
                if blk:
                    blk.translation = new_text
                if self.main.curr_tblock_item == item:
                    self.main.t_text_edit.blockSignals(True)
                    self.main.t_text_edit.setPlainText(new_text)
                    self.main.t_text_edit.blockSignals(False)
            self.main.mark_project_dirty()
        self._sync_case_button()

    def _uppercase_text_item(self, text_item: TextBlockItem) -> bool:
        return self._change_case_text_item(text_item, True)

    def _change_case_text_item(
        self,
        text_item: TextBlockItem,
        make_uppercase: bool,
    ) -> bool:
        doc = text_item.document()
        cursor = text_item.textCursor()
        if getattr(text_item, "editing_mode", False) and cursor.hasSelection():
            start, end = cursor.selectionStart(), cursor.selectionEnd()
        else:
            whole = QTextCursor(doc)
            whole.select(QTextCursor.SelectionType.Document)
            start, end = whole.selectionStart(), whole.selectionEnd()
        return self._change_case_range(doc, start, end, make_uppercase)

    @staticmethod
    def _uppercase_range(doc, start: int, end: int) -> bool:
        return TextController._change_case_range(doc, start, end, True)

    @staticmethod
    def _change_case_range(
        doc,
        start: int,
        end: int,
        make_uppercase: bool,
    ) -> bool:
        if end <= start:
            return False
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        changed = False
        # Walk backwards so any length change (e.g. ß -> SS) never shifts the
        # positions still to visit, and keep each character's own formatting.
        pos = end - 1
        while pos >= start:
            cursor.setPosition(pos)
            cursor.setPosition(pos + 1, QTextCursor.KeepAnchor)
            char = cursor.selectedText()
            transformed = char.upper() if make_uppercase else char.lower()
            if transformed != char:
                cursor.insertText(transformed, cursor.charFormat())
                changed = True
            pos -= 1
        cursor.endEditBlock()
        return changed

    def _sync_case_button(self, text_item: TextBlockItem | None = None) -> None:
        if not hasattr(self.main, "uppercase_button"):
            return
        items = [text_item] if text_item is not None else self._selected_text_items()
        states = []
        for item in items:
            if item is None:
                continue
            cursor = item.textCursor()
            if getattr(item, "editing_mode", False) and cursor.hasSelection():
                text = cursor.selectedText()
            else:
                text = item.toPlainText()
            has_cased_text = any(char.lower() != char.upper() for char in text)
            states.append(has_cased_text and text == text.upper())
        blocker = QtCore.QSignalBlocker(self.main.uppercase_button)
        self.main.uppercase_button.setChecked(bool(states) and all(states))
        del blocker

    def on_outline_color_change(self):
        outline_color = self.main.get_color()
        if outline_color and outline_color.isValid():
            self.main.outline_font_color_button.setStyleSheet(
                f"background-color: {outline_color.name()}; border: none; border-radius: 5px;"
            )
            self.main.outline_font_color_button.setProperty('selected_color', outline_color.name())
            self.main.refresh_outline_toolbar_button()
            outline_width = float(self.main.outline_width_dropdown.currentText())
            self.main.set_outline_inspector_values(outline_color, outline_width)

            if self.main.curr_tblock_item and self.main.outline_checkbox.isChecked():
                old_item = copy.copy(self.main.curr_tblock_item)
                self.main.curr_tblock_item.set_outline(outline_color, outline_width)

                command = TextFormatCommand(self.main.image_viewer, old_item, self.main.curr_tblock_item)
                self.main.push_command(command)

    def on_outline_width_change(self, outline_width):
        self.main.set_outline_inspector_values(
            self.main.outline_font_color_button.property('selected_color'),
            outline_width,
        )
        if self.main.curr_tblock_item and self.main.outline_checkbox.isChecked():
            old_item = copy.copy(self.main.curr_tblock_item)
            outline_width = float(self.main.outline_width_dropdown.currentText())
            color_str = self.main.outline_font_color_button.property('selected_color')
            color = QColor(color_str)
            self.main.curr_tblock_item.set_outline(color, outline_width)

            command = TextFormatCommand(self.main.image_viewer, old_item, self.main.curr_tblock_item)
            self.main.push_command(command)

    def apply_outline_style(self, colour: QColor, outline_width: float) -> None:
        colour = QColor(colour)
        if not colour.isValid() or not self._selected_text_items():
            return
        try:
            outline_width = max(0.5, min(10.0, float(outline_width)))
        except (TypeError, ValueError):
            outline_width = 1.0
        self._apply_format_to_selected(
            "change_text_outline_style",
            lambda item: item.set_outline(colour, outline_width),
        )

    def toggle_outline_settings(self, state):
        try:
            enabled = int(state) == int(QtCore.Qt.CheckState.Checked.value)
        except (TypeError, ValueError):
            enabled = bool(state)
        self.main._sync_outline_toolbar_button(enabled)
        if not self._selected_text_items():
            return
        try:
            outline_width = float(self.main.outline_width_dropdown.currentText())
        except (TypeError, ValueError):
            outline_width = 1.0
        color = QColor(
            self.main.outline_font_color_button.property('selected_color')
            or "#000000"
        )
        if not color.isValid():
            color = QColor("#000000")
        self._apply_format_to_selected(
            "change_text_outline",
            lambda item: item.set_outline(color, outline_width)
            if enabled
            else item.set_outline(None, None),
        )

    # Widget helpers
    def block_text_item_widgets(self, widgets):
        # Block signals
        for widget in widgets:
            widget.blockSignals(True)

        # Block Signals is buggy for these, so use disconnect/connect
        self.main.bold_button.clicked.disconnect(self.bold)
        self.main.italic_button.clicked.disconnect(self.italic)
        self.main.underline_button.clicked.disconnect(self.underline)

        self.main.alignment_tool_group.get_button_group().buttons()[0].clicked.disconnect(self.left_align)
        self.main.alignment_tool_group.get_button_group().buttons()[1].clicked.disconnect(self.center_align)
        self.main.alignment_tool_group.get_button_group().buttons()[2].clicked.disconnect(self.right_align)
        self.main.alignment_tool_group.get_button_group().buttons()[3].clicked.disconnect(self.justify_align)

    def unblock_text_item_widgets(self, widgets):
        # Unblock signals
        for widget in widgets:
            widget.blockSignals(False)

        self.main.bold_button.clicked.connect(self.bold)
        self.main.italic_button.clicked.connect(self.italic)
        self.main.underline_button.clicked.connect(self.underline)

        self.main.alignment_tool_group.get_button_group().buttons()[0].clicked.connect(self.left_align)
        self.main.alignment_tool_group.get_button_group().buttons()[1].clicked.connect(self.center_align)
        self.main.alignment_tool_group.get_button_group().buttons()[2].clicked.connect(self.right_align)
        self.main.alignment_tool_group.get_button_group().buttons()[3].clicked.connect(self.justify_align)

    def set_values_for_blk_item(self, text_item: TextBlockItem):

        self.block_text_item_widgets(self.widgets_to_block)

        try:
            # Set values
            self.main.set_font(text_item.font_family)
            self.main.font_size_dropdown.setCurrentText(str(int(text_item.font_size)))

            self.main.line_spacing_dropdown.setCurrentText(str(text_item.line_spacing))
            self.main.set_line_spacing_menu_value(text_item.line_spacing)
            self.main.set_letter_spacing_control_value(
                getattr(text_item, "letter_spacing", 0.0)
            )
            self.main.set_font_weight_menu_value(
                getattr(text_item, "font_weight", 700 if text_item.bold else 400)
            )
            opacity_percent = round(text_item.opacity() * 100)
            self.main.text_opacity_slider.setValue(opacity_percent)
            self.main.set_text_opacity_preview(opacity_percent)

            self.main.block_font_color_button.setStyleSheet(
                f"background-color: {text_item.text_color.name()}; border: none; border-radius: 5px;"
            )
            self.main.block_font_color_button.setProperty('selected_color', text_item.text_color.name())
            self.main.block_font_color_button.setProperty(
                'fill_style',
                text_item.get_visual_style() if hasattr(text_item, 'get_visual_style') else {},
            )
            if hasattr(self.main, "text_effects_panel"):
                self.main.text_effects_panel.set_style(text_item.get_visual_style())
            if (
                hasattr(self.main, "set_fill_inspector_style")
                and not getattr(self.main, "_fill_inspector_applying", False)
            ):
                self.main.set_fill_inspector_style(text_item.get_visual_style())

            if text_item.outline_color is not None:
                self.main.outline_font_color_button.setStyleSheet(
                    f"background-color: {text_item.outline_color.name()}; border: none; border-radius: 5px;"
                )
                self.main.outline_font_color_button.setProperty('selected_color', text_item.outline_color.name())
            else:
                fallback_outline = QColor(
                    self.main.outline_font_color_button.property("selected_color")
                    or "#000000"
                )
                if not fallback_outline.isValid():
                    fallback_outline = QColor("#000000")
                self.main.outline_font_color_button.setStyleSheet(
                    f"background-color: {fallback_outline.name()}; border: none; border-radius: 5px;"
                )
                self.main.outline_font_color_button.setProperty(
                    'selected_color', fallback_outline.name()
                )

            self.main.outline_width_dropdown.setCurrentText(str(text_item.outline_width))
            self.main.outline_checkbox.setChecked(text_item.outline)
            self.main._sync_outline_toolbar_button(text_item.outline)
            self.main.refresh_outline_toolbar_button()
            self.main.set_outline_inspector_values(
                self.main.outline_font_color_button.property('selected_color'),
                text_item.outline_width,
            )

            self.main.bold_button.setChecked(text_item.bold)
            self.main.italic_button.setChecked(text_item.italic)
            self.main.underline_button.setChecked(text_item.underline)
            self._sync_case_button(text_item)

            alignment_to_button = {
                QtCore.Qt.AlignmentFlag.AlignLeft: 0,
                QtCore.Qt.AlignmentFlag.AlignCenter: 1,
                QtCore.Qt.AlignmentFlag.AlignRight: 2,
                QtCore.Qt.AlignmentFlag.AlignJustify: 3,
            }

            alignment = text_item.alignment
            button_group = self.main.alignment_tool_group.get_button_group()

            if alignment in alignment_to_button:
                button_index = alignment_to_button[alignment]
                self.main.set_alignment_menu_value(button_index)

        finally:
            self.unblock_text_item_widgets(self.widgets_to_block)

    def set_values_from_highlight(self, item_highlighted = None):

        self.block_text_item_widgets(self.widgets_to_block)

        # Attributes
        font_family = item_highlighted['font_family']
        font_size = item_highlighted['font_size']
        font_weight = item_highlighted.get('font_weight')
        letter_spacing = item_highlighted.get('letter_spacing')
        line_spacing = item_highlighted.get('line_spacing')
        text_color = item_highlighted['text_color']
        opacity = item_highlighted.get('opacity')

        outline_color = item_highlighted['outline_color']
        outline_width =  item_highlighted['outline_width']
        outline = item_highlighted['outline']

        bold = item_highlighted['bold']
        italic =  item_highlighted['italic']
        underline = item_highlighted['underline']

        alignment = item_highlighted['alignment']

        try:
            # Set values
            self.main.set_font(font_family) if font_family else None
            self.main.font_size_dropdown.setCurrentText(str(int(font_size))) if font_size else None
            if font_weight:
                self.main.set_font_weight_menu_value(font_weight)
            if letter_spacing is not None:
                self.main.set_letter_spacing_control_value(letter_spacing)
            if line_spacing is not None:
                self.main.set_line_spacing_menu_value(line_spacing)
            if opacity is not None:
                self.main.text_opacity_slider.setValue(int(opacity))
                self.main.set_text_opacity_preview(int(opacity))

            if text_color is not None:
                self.main.block_font_color_button.setStyleSheet(
                    f"background-color: {text_color}; border: none; border-radius: 5px;"
                )
                self.main.block_font_color_button.setProperty('selected_color', text_color)

            if outline_color is not None:
                self.main.outline_font_color_button.setStyleSheet(
                    f"background-color: {outline_color}; border: none; border-radius: 5px;"
                )
                self.main.outline_font_color_button.setProperty('selected_color', outline_color)
            else:
                fallback_outline = QColor(
                    self.main.outline_font_color_button.property("selected_color")
                    or "#000000"
                )
                if not fallback_outline.isValid():
                    fallback_outline = QColor("#000000")
                self.main.outline_font_color_button.setStyleSheet(
                    f"background-color: {fallback_outline.name()}; border: none; border-radius: 5px;"
                )
                self.main.outline_font_color_button.setProperty(
                    'selected_color', fallback_outline.name()
                )

            self.main.outline_width_dropdown.setCurrentText(str(outline_width)) if outline_width else None
            self.main.outline_checkbox.setChecked(outline)
            self.main._sync_outline_toolbar_button(outline)
            self.main.refresh_outline_toolbar_button()
            self.main.set_outline_inspector_values(
                self.main.outline_font_color_button.property('selected_color'),
                outline_width or 1.0,
            )

            self.main.bold_button.setChecked(bold)
            if not font_weight and hasattr(
                self.main, "set_font_weight_button_active"
            ):
                self.main.set_font_weight_button_active(bool(bold))
            self.main.italic_button.setChecked(italic)
            self.main.underline_button.setChecked(underline)
            self._sync_case_button(self.main.curr_tblock_item)

            alignment_to_button = {
                QtCore.Qt.AlignmentFlag.AlignLeft: 0,
                QtCore.Qt.AlignmentFlag.AlignCenter: 1,
                QtCore.Qt.AlignmentFlag.AlignRight: 2,
                QtCore.Qt.AlignmentFlag.AlignJustify: 3,
            }

            button_group = self.main.alignment_tool_group.get_button_group()

            if alignment in alignment_to_button:
                button_index = alignment_to_button[alignment]
                self.main.set_alignment_menu_value(button_index)

        finally:
            self.unblock_text_item_widgets(self.widgets_to_block)

    # Rendering
    def _begin_render_macro(self):
        if self._render_macro_stack is not None:
            return

        stack = self.main.undo_group.activeStack()
        if stack is None:
            return

        stack.beginMacro("render_text")
        self._render_macro_stack = stack

    def _end_render_macro(self):
        stack = self._render_macro_stack
        self._render_macro_stack = None
        if stack is None:
            return

        try:
            stack.endMacro()
        except RuntimeError:
            pass

    def _handle_render_error(self, error_tuple: tuple):
        self._end_render_macro()
        self.main.default_error_handler(error_tuple)

    def render_text(self):
        selected_paths = self.main.get_selected_page_paths()
        if self.main.image_viewer.hasPhoto() and len(selected_paths) > 1:
            self.main.set_tool(None)
            if not font_selected(self.main):
                return
            self.clear_text_edits()
            self.main.loading.setVisible(True)
            self.main.disable_hbutton_group()

            context = self.main.manual_workflow_ctrl._prepare_multi_page_context(selected_paths)
            render_settings = self.render_settings()
            upper = render_settings.upper_case
            line_spacing = float(self.main.line_spacing_dropdown.currentText())
            font_family = self.main.font_dropdown.currentText()
            outline_width = float(self.main.outline_width_dropdown.currentText())
            bold = self.main.bold_button.isChecked()
            italic = self.main.italic_button.isChecked()
            underline = self.main.underline_button.isChecked()
            align_id = self.main.alignment_tool_group.get_dayu_checked()
            alignment = self.main.button_to_alignment[align_id]
            direction = render_settings.direction
            max_font_size = self.main.settings_page.get_max_font_size()
            min_font_size = self.main.settings_page.get_min_font_size()
            setting_font_color = QColor(render_settings.color)
            outline_color = (
                QColor(render_settings.outline_color)
                if render_settings.outline
                else None
            )

            def render_selected_pages() -> set[str]:
                updated_paths: set[str] = set()
                target_lang_fallback = self.main.t_combo.currentText()
                for file_path in selected_paths:
                    state = self.main.image_states.get(file_path, {})
                    blk_list = state.get("blk_list", [])
                    if not blk_list:
                        continue

                    target_lang = state.get("target_lang", target_lang_fallback)
                    target_lang_en = self.main.lang_mapping.get(target_lang, None)
                    trg_lng_cd = get_language_code(target_lang_en)
                    format_translations(blk_list, trg_lng_cd, upper_case=upper)

                    viewer_state = state.setdefault("viewer_state", {})
                    existing_text_items = list(viewer_state.get("text_items_state", []))
                    existing_keys = {
                        (
                            int(item.get("position", (0, 0))[0]),
                            int(item.get("position", (0, 0))[1]),
                            float(item.get("rotation", 0)),
                        )
                        for item in existing_text_items
                    }

                    new_text_items_state = []
                    for blk in blk_list:
                        blk_key = (int(blk.xyxy[0]), int(blk.xyxy[1]), float(blk.angle))
                        if blk_key in existing_keys:
                            continue

                        x1, y1, block_width, block_height = blk.xywh
                        translation = blk.translation
                        if not translation or len(translation) == 1:
                            continue

                        vertical = is_vertical_block(blk, trg_lng_cd)
                        wrapped, font_size, rendered_width, rendered_height = pyside_word_wrap(
                            translation,
                            font_family,
                            block_width,
                            block_height,
                            line_spacing,
                            outline_width,
                            bold,
                            italic,
                            underline,
                            alignment,
                            direction,
                            max_font_size,
                            min_font_size,
                            vertical,
                            return_metrics=True,
                        )
                        if is_no_space_lang(trg_lng_cd):
                            wrapped = wrapped.replace(" ", "")

                        # Store re-flowable content (single paragraph + pinned
                        # width) so the box re-wraps when its width changes.
                        reflow_text = wrapped
                        fixed_wrap = None
                        if not vertical and not is_no_space_lang(trg_lng_cd):
                            unwrapped = " ".join(
                                part for part in wrapped.split("\n") if part != ""
                            )
                            if unwrapped and unwrapped != wrapped:
                                reflow_text = unwrapped
                                fixed_wrap = rendered_width

                        font_color = get_smart_text_color(blk.font_color, setting_font_color)
                        text_props = TextItemProperties(
                            text=reflow_text,
                            font_family=font_family,
                            font_size=font_size,
                            text_color=font_color,
                            alignment=alignment,
                            line_spacing=line_spacing,
                            outline_color=outline_color,
                            outline_width=outline_width,
                            bold=bold,
                            italic=italic,
                            underline=underline,
                            direction=direction,
                            position=(x1, y1),
                            rotation=blk.angle,
                            scale=1.0,
                            transform_origin=blk.tr_origin_point if blk.tr_origin_point else (0, 0),
                            width=rendered_width,
                            height=rendered_height,
                            vertical=vertical,
                            fixed_wrap_width=fixed_wrap,
                            fill_style=copy.deepcopy(
                                self.main.block_font_color_button.property('fill_style') or {}
                            ),
                        )
                        new_text_items_state.append(text_props.to_dict())

                    if new_text_items_state:
                        viewer_state["text_items_state"] = existing_text_items + new_text_items_state
                        viewer_state["push_to_stack"] = True
                        state["blk_list"] = blk_list
                        updated_paths.add(file_path)

                return updated_paths

            def on_selected_render_ready(updated_paths: set[str]) -> None:
                if not updated_paths:
                    return

                current_file = context["current_file"]
                if current_file in updated_paths:
                    if self.main.webtoon_mode:
                        self.main.manual_workflow_ctrl._set_current_blocks_from_page_state(
                            self.main.image_states.get(current_file, {}).get("blk_list", []),
                            current_page_unloaded=context["current_page_unloaded"],
                        )
                    else:
                        self.main.blk_list = self.main.image_states.get(current_file, {}).get("blk_list", []).copy()
                        self.main.image_ctrl.on_render_state_ready(current_file)

                self.main.mark_project_dirty()

            self.main.run_threaded(
                render_selected_pages,
                on_selected_render_ready,
                self.main.default_error_handler,
                self.main.on_manual_finished,
            )
            return

        if self.main.image_viewer.hasPhoto() and self.main.blk_list:
            self.main.set_tool(None)
            if not font_selected(self.main):
                return
            self.clear_text_edits()
            self.main.loading.setVisible(True)
            self.main.disable_hbutton_group()

            # Add items to the scene if they're not already present
            for item in self.main.image_viewer.text_items:
                if item not in self.main.image_viewer._scene.items():
                    self.main.image_viewer._scene.addItem(item)

            # Create a dictionary to map text items to their positions and rotations
            existing_text_items = {item: (int(item.pos().x()), int(item.pos().y()), item.rotation()) for item in self.main.image_viewer.text_items}

            # Identify new blocks based on position and rotation
            new_blocks = [
                blk for blk in self.main.blk_list
                if (int(blk.xyxy[0]), int(blk.xyxy[1]), blk.angle) not in existing_text_items.values()
            ]

            self.main.image_viewer.clear_rectangles()
            self.main.curr_tblock = None
            self.main.curr_tblock_item = None

            render_settings = self.render_settings()
            upper = render_settings.upper_case

            line_spacing = float(self.main.line_spacing_dropdown.currentText())
            font_family = self.main.font_dropdown.currentText()
            outline_width = float(self.main.outline_width_dropdown.currentText())

            bold = self.main.bold_button.isChecked()
            italic = self.main.italic_button.isChecked()
            underline = self.main.underline_button.isChecked()

            target_lang = self.main.t_combo.currentText()
            target_lang_en = self.main.lang_mapping.get(target_lang, None)
            trg_lng_cd = get_language_code(target_lang_en)

            self.main.run_threaded(
            lambda: format_translations(self.main.blk_list, trg_lng_cd, upper_case=upper)
            )

            min_font_size = self.main.settings_page.get_min_font_size()
            max_font_size = self.main.settings_page.get_max_font_size()

            align_id = self.main.alignment_tool_group.get_dayu_checked()
            alignment = self.main.button_to_alignment[align_id]
            direction = render_settings.direction

            # Retrieve current image path to fix blk_rendered error
            image_path = ""
            if 0 <= self.main.curr_img_idx < len(self.main.image_files):
                image_path = self.main.image_files[self.main.curr_img_idx]

            if new_blocks:
                self._begin_render_macro()

            self.main.run_threaded(
                manual_wrap, 
                self.on_render_complete, 
                self._handle_render_error,
                None, 
                self.main, 
                new_blocks, 
                image_path,
                font_family, 
                line_spacing, 
                outline_width,
                bold, 
                italic, 
                underline, 
                alignment, 
                direction, 
                max_font_size,
                min_font_size
            )

    def on_render_complete(self, rendered_image: np.ndarray):
        # self.main.set_image(rendered_image) 
        self.main.loading.setVisible(False)
        self.main.enable_hbutton_group()
        self._end_render_macro()

    def render_settings(self) -> TextRenderingSettings:
        target_lang = self.main.lang_mapping.get(self.main.t_combo.currentText(), None)
        direction = get_layout_direction(target_lang)

        return TextRenderingSettings(
            alignment_id = self.main.alignment_tool_group.get_dayu_checked(),
            font_family = self.main.font_dropdown.currentText(),
            min_font_size = int(self.main.settings_page.ui.min_font_spinbox.value()),
            max_font_size = int(self.main.settings_page.ui.max_font_spinbox.value()),
            color = self.main.block_font_color_button.property('selected_color'),
            upper_case = self.main.settings_page.ui.uppercase_checkbox.isChecked(),
            outline = self.main.outline_checkbox.isChecked(),
            outline_color = self.main.outline_font_color_button.property('selected_color'),
            outline_width = self.main.outline_width_dropdown.currentText(),
            bold = self.main.bold_button.isChecked(),
            italic = self.main.italic_button.isChecked(),
            underline = self.main.underline_button.isChecked(),
            line_spacing = self.main.line_spacing_dropdown.currentText(),
            direction = direction
        )

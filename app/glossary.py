from __future__ import annotations

import re

from PySide6.QtCore import QSettings

from modules.utils.textblock import TextBlock


GLOSSARY_CONTEXT_MARKER = "[Mukai Glossary]"


def load_glossary_text() -> str:
    settings = QSettings("ComicLabs", "ComicTranslate")
    settings.beginGroup("glossary")
    text = settings.value("entries", "", type=str) or ""
    settings.endGroup()
    return text


def save_glossary_text(text: str) -> None:
    settings = QSettings("ComicLabs", "ComicTranslate")
    settings.beginGroup("glossary")
    settings.setValue("entries", text or "")
    settings.endGroup()


def parse_glossary(text: str | None) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    if not text:
        return entries

    separators = ("=>", "\t", "|", "=")
    seen: set[tuple[str, str]] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        source = ""
        target = ""
        for separator in separators:
            if separator in line:
                source, target = line.split(separator, 1)
                source = source.strip()
                target = target.strip()
                break

        if not source or not target:
            continue

        entry = (source, target)
        if entry not in seen:
            entries.append(entry)
            seen.add(entry)
    return entries


def build_glossary_context(text: str | None = None) -> str:
    entries = parse_glossary(load_glossary_text() if text is None else text)
    if not entries:
        return ""

    lines = [
        GLOSSARY_CONTEXT_MARKER,
        "Use these glossary terms exactly. Preserve the target term spelling:",
    ]
    lines.extend(f"- {source} => {target}" for source, target in entries)
    return "\n".join(lines)


def append_glossary_context(extra_context: str | None, glossary_text: str | None = None) -> str:
    base_context = (extra_context or "").rstrip()
    glossary_context = build_glossary_context(glossary_text)
    if not glossary_context or GLOSSARY_CONTEXT_MARKER in base_context:
        return base_context
    if not base_context:
        return glossary_context
    return f"{base_context}\n\n{glossary_context}"


def _replace_terms(text: str, entries: list[tuple[str, str]]) -> str:
    replacements: dict[str, str] = {}
    pattern_parts: list[str] = []
    sorted_entries = sorted(entries, key=lambda entry: len(entry[0]), reverse=True)
    for source, target in sorted_entries:
        if source == target or source in replacements:
            continue
        replacements[source] = target
        pattern_parts.append(re.escape(source))

    if not pattern_parts:
        return text

    pattern = re.compile("|".join(pattern_parts))
    return pattern.sub(lambda match: replacements[match.group(0)], text)


def apply_glossary_replacements(text: str | None, glossary_text: str | None = None) -> str:
    if not text:
        return text or ""

    entries = parse_glossary(load_glossary_text() if glossary_text is None else glossary_text)
    return _replace_terms(text, entries)


def apply_glossary_to_blocks(
    blk_list: list[TextBlock],
    glossary_text: str | None = None,
) -> list[TextBlock]:
    if not blk_list:
        return blk_list

    entries = parse_glossary(load_glossary_text() if glossary_text is None else glossary_text)
    if not entries:
        return blk_list

    for block in blk_list:
        translation = getattr(block, "translation", "") or ""
        block.translation = _replace_terms(translation, entries)
    return blk_list

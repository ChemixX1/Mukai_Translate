from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from PySide6.QtCore import QSettings


ONOMATOPOEIA_CONTEXT_MARKER = "[Mukai Onomatopoeia Specialist v1]"

_JAPANESE_SFX = {
    "ドキドキ": {"english": "thump thump", "spanish": "pum pum"},
    "どきどき": {"english": "thump thump", "spanish": "pum pum"},
    "バン": {"english": "bang", "spanish": "¡bang!"},
    "バーン": {"english": "baaang", "spanish": "¡baaang!"},
    "ドン": {"english": "boom", "spanish": "¡bum!"},
    "ドーン": {"english": "booom", "spanish": "¡buum!"},
    "ガーン": {"english": "shock", "spanish": "¡impacto!"},
    "ゴゴゴ": {"english": "rumble", "spanish": "retum retum"},
    "ザー": {"english": "shhhh", "spanish": "shhhh"},
    "シーン": {"english": "silence", "spanish": "silencio…"},
    "キラキラ": {"english": "sparkle sparkle", "spanish": "brilla brilla"},
    "ワクワク": {"english": "so excited", "spanish": "qué emoción"},
    "ニヤニヤ": {"english": "grin grin", "spanish": "je, je"},
    "パチパチ": {"english": "clap clap", "spanish": "plas plas"},
    "ガチャ": {"english": "clack", "spanish": "clac"},
    "バタン": {"english": "slam", "spanish": "¡pum!"},
    "ズキ": {"english": "throb", "spanish": "punzada"},
    "ズキズキ": {"english": "throb throb", "spanish": "punzada punzada"},
    "もぐもぐ": {"english": "munch munch", "spanish": "ñam ñam"},
    "モグモグ": {"english": "munch munch", "spanish": "ñam ñam"},
    "じー": {"english": "staaare", "spanish": "miraaada"},
    "ジー": {"english": "staaare", "spanish": "miraaada"},
    "ピカ": {"english": "flash", "spanish": "destello"},
    "ピカピカ": {"english": "sparkle", "spanish": "brilla brilla"},
}

_LANGUAGE_ALIASES = {
    "english": "english",
    "inglés": "english",
    "ingles": "english",
    "spanish": "spanish",
    "español": "spanish",
    "espanol": "spanish",
}


def is_onomatopoeia_mode_enabled(main_page=None) -> bool:
    stored_state = getattr(main_page, "onomatopoeia_mode_enabled", None)
    if stored_state is not None:
        return bool(stored_state)
    toggle = getattr(main_page, "onomatopoeia_toggle", None)
    if toggle is not None:
        return bool(toggle.isChecked())
    settings = QSettings("ComicLabs", "ComicTranslate")
    settings.beginGroup("workflow")
    enabled = settings.value("onomatopoeia_mode", False, type=bool)
    settings.endGroup()
    return enabled


def _normalise_sfx(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"[\s\u3000。、，,.!！?？…〜～―—・♪♬♡♥]+", "", value)


_NORMALIZED_JAPANESE_SFX = {
    _normalise_sfx(source): translations
    for source, translations in _JAPANESE_SFX.items()
}


def is_onomatopoeia_candidate(text: str) -> bool:
    value = unicodedata.normalize("NFKC", text or "").strip()
    compact = re.sub(r"\s+", "", value)
    if not compact or len(compact) > 28:
        return False
    if _normalise_sfx(compact) in _NORMALIZED_JAPANESE_SFX:
        return True

    kana = re.findall(r"[\u3040-\u30ff]", compact)
    if kana:
        kana_ratio = len(kana) / max(1, len(compact))
        repeated_chunk = bool(re.search(r"(.{1,4})\1+", compact))
        repeated_character = bool(re.search(r"(.)\1{1,}", compact))
        katakana_ratio = len(re.findall(r"[\u30a0-\u30ff]", compact)) / len(kana)
        return kana_ratio >= 0.65 and (
            repeated_chunk
            or repeated_character
            or katakana_ratio >= 0.72
            or len(compact) <= 5
        )

    latin = re.sub(r"[^A-Za-z]", "", compact)
    if latin and len(latin) <= 16:
        return (
            value.upper() == value
            and (
                bool(re.search(r"(.)\1{1,}", latin, re.IGNORECASE))
                or bool(re.search(r"(.{1,3})\1+", latin, re.IGNORECASE))
                or bool(re.search(r"[!！?？]{1,}", value))
            )
        )
    return False


def _candidate_texts(blocks: Iterable) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for block in blocks or []:
        text = str(getattr(block, "text", "") or "").strip()
        if text and text not in seen and is_onomatopoeia_candidate(text):
            result.append(text)
            seen.add(text)
        if len(result) >= 24:
            break
    return result


def append_onomatopoeia_context(
    extra_context: str | None,
    blocks: Iterable,
    source_lang: str,
    target_lang: str,
    main_page=None,
) -> str:
    """Add SFX guidance only when the independent workflow toggle is active."""
    base_context = (extra_context or "").rstrip()
    if (
        not is_onomatopoeia_mode_enabled(main_page)
        or ONOMATOPOEIA_CONTEXT_MARKER in base_context
    ):
        return base_context

    candidates = _candidate_texts(blocks)
    lines = [
        ONOMATOPOEIA_CONTEXT_MARKER,
        (
            "Act as a comics sound-effect specialist in addition to the normal "
            f"translation from {source_lang or 'the source language'} to "
            f"{target_lang or 'the target language'}."
        ),
        (
            "Translate probable onomatopoeias as concise, natural comic sound "
            "effects rather than literal dialogue. Preserve the number and order "
            "of blocks; leave ordinary dialogue and names under the normal rules."
        ),
        (
            "Keep intensity, elongation and repetition when they carry visual "
            "impact. If a sound is ambiguous, prefer a readable sound over an "
            "invented explanation."
        ),
    ]
    if candidates:
        lines.append("Probable SFX candidates detected on this page:")
        lines.extend(f"- {candidate}" for candidate in candidates)
    else:
        lines.append(
            "No high-confidence candidate was preclassified; inspect short sound "
            "effects conservatively and do not reinterpret normal dialogue."
        )
    specialist_context = "\n".join(lines)
    return (
        specialist_context
        if not base_context
        else f"{base_context}\n\n{specialist_context}"
    )


def refine_untranslated_onomatopoeias(
    blocks: list,
    target_lang: str,
    main_page=None,
) -> list:
    """Supply safe local fallbacks only when a translator leaves known SFX unchanged."""
    if not is_onomatopoeia_mode_enabled(main_page):
        return blocks
    target_key = _LANGUAGE_ALIASES.get(
        unicodedata.normalize("NFKC", target_lang or "").strip().casefold()
    )
    if target_key not in {"english", "spanish"}:
        return blocks

    for block in blocks or []:
        source = str(getattr(block, "text", "") or "").strip()
        translation = str(getattr(block, "translation", "") or "").strip()
        replacement = _NORMALIZED_JAPANESE_SFX.get(
            _normalise_sfx(source), {}
        ).get(target_key)
        if replacement and (not translation or _normalise_sfx(translation) == _normalise_sfx(source)):
            block.translation = replacement
    return blocks

from __future__ import annotations

import os
from pathlib import Path


PLACEHOLDER_PREFIXES = (
    "YOUR_",
    "PON_AQUI",
    "REEMPLAZA",
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _clean_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value.strip()


def _is_usable_value(value: str) -> bool:
    if not value:
        return False
    upper = value.upper()
    return not any(upper.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def parse_env_file(path: str | os.PathLike | None = None) -> dict[str, str]:
    env_path = Path(path) if path else project_root() / "env"
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("set "):
            line = line[4:].strip()
        if len(line) >= 2 and line[0] == line[-1] and line[0] in ("'", '"'):
            line = line[1:-1].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = _clean_env_value(value)
        if key and _is_usable_value(value):
            values[key] = value
    return values


def load_project_env(path: str | os.PathLike | None = None) -> dict[str, str]:
    if path is not None:
        candidate_paths = [Path(path)]
    else:
        root = project_root()
        candidate_paths = [root / "env"]

    values: dict[str, str] = {}
    for candidate in candidate_paths:
        for key, value in parse_env_file(candidate).items():
            values.setdefault(key, value)

    for key, value in values.items():
        if not os.environ.get(key):
            os.environ[key] = value
    return values


def first_env_value(*keys: str) -> str:
    load_project_env()
    for key in keys:
        value = os.environ.get(key, "")
        if _is_usable_value(value):
            return value
    return ""

from __future__ import annotations

import logging
import os

from app.env_config import load_project_env
from app.startup_preloader import preload_startup_assets


def _progress(message: str) -> None:
    print(f"[INFO] {message}", flush=True)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    load_project_env()

    mode = os.environ.get("MUKAI_BOOTSTRAP_MODE", "essential").strip().lower()
    os.environ["MUKAI_PRELOAD_MODE"] = mode
    os.environ.setdefault("MUKAI_PRELOAD_WATERMARK_REMOVER", "1")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

    print("[INFO] Preparando motores y recursos locales...", flush=True)
    print(f"[INFO] Modo de motores: {mode}", flush=True)
    preload_startup_assets(_progress)
    print("[OK] Recursos preparados.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.watermark_remover_sidecar import (
    LOCAL_FLORENCE_DIR,
    _download_florence_model,
    ensure_sidecar_ready,
)


def main() -> int:
    python_exe = ensure_sidecar_ready()
    print(f"Downloading Florence local files to: {LOCAL_FLORENCE_DIR}", flush=True)
    _download_florence_model(python_exe)
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

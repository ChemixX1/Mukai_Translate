from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path


def _default_log_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "MukaiTranslator" / "logs" / "mukai-launch.log"


def _configure_logging() -> Path:
    log_path = Path(os.environ.get("MUKAI_LAUNCH_LOG") or _default_log_path())
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        filename=str(log_path),
        filemode="a",
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return log_path


def _show_error_message(message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            message,
            "MukaiTranslator",
            0x00000010,
        )
    except Exception:
        pass


def main() -> int:
    log_path = _configure_logging()
    logging.info("Starting MukaiTranslator from hidden launcher.")

    try:
        project_root = Path(__file__).resolve().parents[1]
        os.chdir(project_root)
        root_str = str(project_root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)

        from comic import main as comic_main

        comic_main()
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            logging.info("MukaiTranslator exited with code %s.", code)
            return code
        logging.info("MukaiTranslator exited.")
        return 0
    except BaseException:
        logging.error("MukaiTranslator crashed during startup or runtime:\n%s", traceback.format_exc())
        _show_error_message(
            "MukaiTranslator se cerro con un error inesperado.\n\n"
            f"Revisa el log:\n{log_path}"
        )
        return 1

    logging.info("MukaiTranslator exited normally.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

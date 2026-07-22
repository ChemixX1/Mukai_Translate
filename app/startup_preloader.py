from __future__ import annotations

import logging
import os
from collections.abc import Callable

logger = logging.getLogger(__name__)


def preload_startup_assets(
    progress: Callable[[str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> None:
    """Download local model assets during splash startup.

    This is intentionally best-effort: missing network access or a temporary
    model-host failure should not prevent the UI from opening.
    """

    def emit(message: str) -> None:
        if progress is not None:
            try:
                progress(message)
            except Exception:
                pass
        logger.info(message)

    try:
        from modules.utils.download import ModelDownloader, ModelID
    except Exception:
        logger.exception("Could not import model downloader during startup preload.")
        return

    mode = os.environ.get("MUKAI_PRELOAD_MODE", "essential").strip().lower()
    if mode in {"0", "false", "off", "none", "disabled"}:
        emit("Startup model preload disabled.")
        return

    if mode in {"essential", "basic"}:
        model_ids = _essential_model_ids(ModelID)
    else:
        model_ids = _all_downloadable_model_ids(ModelDownloader)

    total = len(model_ids)
    if total == 0:
        _preload_watermark_remover(emit, should_cancel)
        return

    emit(f"Preparing {total} local model assets...")
    for index, model_id in enumerate(model_ids, start=1):
        if should_cancel is not None and should_cancel():
            emit("Startup model preload cancelled.")
            return
        try:
            if ModelDownloader.is_downloaded(model_id):
                emit(f"Model ready {index}/{total}: {model_id.value}")
                continue
            emit(f"Downloading model {index}/{total}: {model_id.value}")
            ModelDownloader.get(model_id)
        except Exception:
            logger.exception("Startup preload failed for model %s", getattr(model_id, "value", model_id))

    _preload_watermark_remover(emit, should_cancel)
    emit("Startup model preload finished.")


def _all_downloadable_model_ids(model_downloader) -> list:
    model_ids = []
    for model_id, spec in model_downloader.registry.items():
        if getattr(spec, "url", ""):
            model_ids.append(model_id)
    return model_ids


def _essential_model_ids(model_id_cls) -> list:
    return [
        model_id_cls.RTDETR_V2_ONNX,
        model_id_cls.MANGA_OCR_BASE_ONNX,
        model_id_cls.PORORO_ONNX,
        model_id_cls.PPOCR_V5_DET_MOBILE,
        model_id_cls.PPOCR_V5_REC_MOBILE,
        model_id_cls.PPOCR_V5_REC_EN_MOBILE,
        model_id_cls.PPOCR_V5_REC_KOREAN_MOBILE,
        model_id_cls.PPOCR_V5_REC_LATIN_MOBILE,
        model_id_cls.PPOCR_V5_REC_ESLAV_MOBILE,
        model_id_cls.LAMA_ONNX,
        model_id_cls.AOT_ONNX,
        model_id_cls.MIGAN_PIPELINE_ONNX,
    ]


def _preload_watermark_remover(
    emit: Callable[[str], None],
    should_cancel: Callable[[], bool] | None,
) -> None:
    enabled = os.environ.get("MUKAI_PRELOAD_WATERMARK_REMOVER", "1").strip().lower()
    if enabled in {"0", "false", "off", "none", "disabled"}:
        return
    if should_cancel is not None and should_cancel():
        return

    try:
        from app.watermark_remover_sidecar import preload_watermark_remover_assets

        preload_watermark_remover_assets(emit, should_cancel)
    except Exception:
        logger.exception("WatermarkRemover-AI startup preload failed.")

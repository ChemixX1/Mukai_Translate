"""Run real CPU inference through Mukai's production ONNX engines.

This is intentionally separate from the fast release self-test: it loads the
large user models and executes a small synthetic sample through every local
engine. It never changes the selected application settings or translation
credentials.
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run(name: str, fn, results: list[dict[str, object]]) -> None:
    started = time.perf_counter()
    try:
        detail = fn()
    except Exception as exc:
        results.append(
            {
                "engine": name,
                "status": "failed",
                "seconds": round(time.perf_counter() - started, 3),
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return
    results.append(
        {
            "engine": name,
            "status": "ok",
            "seconds": round(time.perf_counter() - started, 3),
            "detail": detail,
        }
    )


def _expect_image(output: np.ndarray, shape: tuple[int, int, int]) -> str:
    if not isinstance(output, np.ndarray):
        raise TypeError(f"expected numpy output, got {type(output)!r}")
    if output.shape != shape:
        raise ValueError(f"expected output shape {shape}, got {output.shape}")
    if not np.isfinite(output).all():
        raise ValueError("output contains non-finite values")
    return f"shape={output.shape}, dtype={output.dtype}"


def _test_detection() -> str:
    from modules.detection.rtdetr_v2_onnx import RTDetrV2ONNXDetection

    engine = RTDetrV2ONNXDetection()
    engine.initialize(device="cpu")
    bubbles, text = engine._detect_single_image(np.full((160, 128, 3), 255, np.uint8))
    return f"bubble_boxes={len(bubbles)}, text_boxes={len(text)}"


def _test_manga_ocr() -> str:
    from modules.ocr.manga_ocr.onnx_engine import MangaOCREngineONNX

    engine = MangaOCREngineONNX()
    engine.initialize(device="cpu")
    text = engine.model(np.full((96, 160, 3), 255, np.uint8))
    return f"decoded_chars={len(text)}"


def _test_pororo() -> str:
    from modules.ocr.pororo.onnx_engine import PororoOCREngineONNX

    engine = PororoOCREngineONNX()
    engine.initialize(lang="ko", device="cpu")
    result = engine.read(np.full((128, 192, 3), 255, np.uint8))
    return f"detections={len(result)}"


def _test_ppocr(language: str, test_detector: bool) -> str:
    from modules.ocr.ppocr.engine import PPOCRv5Engine

    engine = PPOCRv5Engine()
    engine.initialize(lang=language, device="cpu")
    detector_boxes = 0
    if test_detector:
        boxes, _ = engine._det_infer(np.full((128, 192, 3), 255, np.uint8))
        detector_boxes = len(boxes)
    texts, scores = engine._rec_infer([np.full((48, 160, 3), 255, np.uint8)])
    if len(texts) != 1 or len(scores) != 1:
        raise RuntimeError("recognizer returned an unexpected batch size")
    return f"detector_boxes={detector_boxes}, recognizer_batch={len(texts)}"


def _test_inpainter(model_cls) -> str:
    from modules.inpainting.schema import Config

    image = np.full((128, 128, 3), 230, np.uint8)
    image[40:88, 40:88] = (40, 70, 110)
    mask = np.zeros((128, 128), np.uint8)
    mask[48:80, 48:80] = 255
    engine = model_cls("cpu", backend="onnx")
    output = engine(image, mask, Config())
    return _expect_image(output, image.shape)


def _test_migan(model_path: Path | None) -> str:
    from modules.inpainting.mi_gan import MIGAN
    from modules.inpainting.schema import Config
    from modules.utils.download import ModelDownloader, ModelID

    if model_path is not None:
        model_path = model_path.resolve()
        if not model_path.is_file():
            raise FileNotFoundError(model_path)
        current = ModelDownloader.registry[ModelID.MIGAN_PIPELINE_ONNX]
        ModelDownloader.registry[ModelID.MIGAN_PIPELINE_ONNX] = replace(
            current,
            files=[model_path.name],
            save_dir=str(model_path.parent),
        )

    image = np.full((512, 512, 3), 235, np.uint8)
    image[160:352, 160:352] = (45, 80, 120)
    mask = np.zeros((512, 512), np.uint8)
    mask[208:304, 208:304] = 255
    engine = MIGAN("cpu", backend="onnx")
    output = engine(image, mask, Config())
    return _expect_image(output, image.shape)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--migan-model",
        type=Path,
        help="Use an already downloaded official MI-GAN pipeline for this test.",
    )
    args = parser.parse_args()

    results: list[dict[str, object]] = []
    _run("RT-DETR-v2 ONNX", _test_detection, results)
    gc.collect()
    _run("Manga OCR ONNX", _test_manga_ocr, results)
    gc.collect()
    _run("Pororo OCR ONNX", _test_pororo, results)
    gc.collect()
    for index, language in enumerate(("ch", "en", "ko", "latin", "ru")):
        _run(
            f"PP-OCRv5 ONNX ({language})",
            lambda lang=language, det=index == 0: _test_ppocr(lang, det),
            results,
        )
        gc.collect()

    from modules.inpainting.aot import AOT
    from modules.inpainting.lama import LaMa

    _run("LaMa ONNX", lambda: _test_inpainter(LaMa), results)
    gc.collect()
    _run("AOT ONNX", lambda: _test_inpainter(AOT), results)
    gc.collect()
    _run("MI-GAN ONNX", lambda: _test_migan(args.migan_model), results)

    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 1 if any(item["status"] != "ok" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())

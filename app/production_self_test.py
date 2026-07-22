"""Fast, non-destructive checks shared by local and frozen release builds."""

from __future__ import annotations

import base64
import logging
import os
import secrets
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _runtime_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", "")
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[1]


def _configure_log() -> Path:
    explicit_log = os.environ.get("MUKAI_SELF_TEST_LOG", "").strip()
    if explicit_log:
        log_path = Path(explicit_log)
    else:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        log_path = Path(base) / "MukaiTranslator" / "logs" / "production-self-test.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_path),
        filemode="w",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
    )
    return log_path


def _check_distribution_configuration() -> None:
    from app.release_config import LICENSE_API_BASE, UPDATE_MANIFEST_URL, UPDATE_PUBLIC_KEY

    if not LICENSE_API_BASE.startswith("https://") or not UPDATE_MANIFEST_URL.startswith("https://"):
        raise RuntimeError("License and update endpoints must use HTTPS.")
    key = serialization.load_pem_public_key(base64.b64decode(UPDATE_PUBLIC_KEY, validate=True))
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 3072:
        raise RuntimeError("The embedded Mukai public key is invalid or too small.")


def _check_resources() -> None:
    root = _runtime_root()
    attribution_notice = (
        root / "docs" / "NOTICE"
        if getattr(sys, "frozen", False)
        else root / "NOTICE"
    )
    required = (
        attribution_notice,
        root / "resources" / "icons" / "icon.ico",
        root / "resources" / "icons" / "logo_mt.svg",
        root / "resources" / "static" / "marca de agua.png",
        root / "resources" / "translations" / "compiled" / "ct_es.qm",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("Missing production resources: " + ", ".join(missing))


def _check_core_imports_and_models() -> None:
    import cv2
    import onnxruntime
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from app.license_manager import LicenseManager
    from app.update_checker import validate_release_manifest
    from modules.detection.factory import DetectionEngineFactory
    from modules.inpainting.aot import AOT
    from modules.inpainting.lama import LaMa
    from modules.inpainting.mi_gan import MIGAN
    from modules.ocr.factory import OCRFactory
    from modules.translation.factory import TranslationFactory
    from modules.utils.download import ModelDownloader, ModelID
    from pipeline.main_pipeline import ComicTranslatePipeline
    from app.ui.canvas.text_3d import SUPPORTED_TEXT_3D_STYLES
    from app.ui.canvas.text_warp import SUPPORTED_WARP_STYLES, text_warp_backend
    from app.export_enhancer import (
        ExportEnhancementOptions,
        output_dimensions,
        profile_engine,
    )
    from app.ui.music_player import MusicPlayerWidget

    if text_warp_backend() != "opencv-lanczos4" or len(SUPPORTED_WARP_STYLES) != 15:
        raise RuntimeError("High-quality editable text deformation is unavailable.")
    if len(SUPPORTED_TEXT_3D_STYLES) != 10:
        raise RuntimeError("Editable 3D and perspective text effects are unavailable.")
    export_probe = __import__("numpy").zeros((100, 50, 3), dtype="uint8")
    if output_dimensions(export_probe, 4096) != (2048, 4096):
        raise RuntimeError("2K-8K export sizing is unavailable.")
    if (
        profile_engine("manga_balanced") != "realcugan"
        or profile_engine("realesrgan_anime") != "realesrgan"
        or ExportEnhancementOptions.from_dict({"target_long_edge": 8192}).target_long_edge
        != 8192
    ):
        raise RuntimeError("AI manga export profiles are unavailable.")

    _ = (
        cv2.__version__,
        onnxruntime.get_available_providers(),
        LicenseManager,
        validate_release_manifest,
        DetectionEngineFactory,
        AOT,
        LaMa,
        MIGAN,
        OCRFactory,
        TranslationFactory,
        ComicTranslatePipeline,
        MusicPlayerWidget,
        QAudioOutput,
        QMediaPlayer,
    )

    essential_ids = (
        ModelID.RTDETR_V2_ONNX,
        ModelID.MANGA_OCR_BASE_ONNX,
        ModelID.PORORO_ONNX,
        ModelID.PPOCR_V5_DET_MOBILE,
        ModelID.PPOCR_V5_REC_MOBILE,
        ModelID.PPOCR_V5_REC_EN_MOBILE,
        ModelID.PPOCR_V5_REC_KOREAN_MOBILE,
        ModelID.PPOCR_V5_REC_LATIN_MOBILE,
        ModelID.PPOCR_V5_REC_ESLAV_MOBILE,
        ModelID.LAMA_ONNX,
        ModelID.AOT_ONNX,
        ModelID.MIGAN_PIPELINE_ONNX,
    )
    for model_id in essential_ids:
        spec = ModelDownloader.registry.get(model_id)
        if spec is None or not spec.url or not spec.files or len(spec.files) != len(spec.sha256):
            raise RuntimeError(f"Invalid model registry entry: {model_id.value}")
        if not spec.url.startswith("https://"):
            raise RuntimeError(f"Model URL must use HTTPS: {model_id.value}")


def _check_frozen_source_exposure() -> None:
    if not getattr(sys, "frozen", False):
        return
    root = _runtime_root()
    allowed = {(root / "app" / "sam_refiner_runner.py").resolve()}
    exposed = []
    for package in ("app", "modules", "pipeline"):
        package_root = root / package
        if not package_root.exists():
            continue
        for source_file in package_root.rglob("*.py"):
            if source_file.resolve() not in allowed:
                exposed.append(str(source_file))
    if exposed:
        raise RuntimeError("Plain Python sources were bundled: " + ", ".join(exposed[:5]))


def _check_windows_credential_vault() -> None:
    if os.name != "nt":
        return
    import keyring

    backend = keyring.get_keyring()
    if "WinVault" not in backend.__class__.__name__ or getattr(backend, "priority", 0) <= 0:
        raise RuntimeError(f"Windows Credential Vault is unavailable: {backend!r}")

    service = "mukai-production-self-test"
    username = "temporary-" + secrets.token_hex(8)
    secret = secrets.token_urlsafe(32)
    try:
        keyring.set_password(service, username, secret)
        if keyring.get_password(service, username) != secret:
            raise RuntimeError("Windows Credential Vault read-back failed.")
    finally:
        try:
            keyring.delete_password(service, username)
        except Exception:
            pass


def run_production_self_test() -> int:
    log_path = _configure_log()
    try:
        _check_distribution_configuration()
        _check_resources()
        _check_core_imports_and_models()
        _check_windows_credential_vault()
        _check_frozen_source_exposure()
    except Exception:
        logging.exception("Mukai production self-test failed.")
        return 1
    logging.info("Mukai production self-test passed. Runtime root: %s", _runtime_root())
    logging.info("Log path: %s", log_path)
    return 0

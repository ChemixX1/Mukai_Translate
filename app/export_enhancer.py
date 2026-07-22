"""Export-only manga restoration and super-resolution.

The enhancer is deliberately isolated from Mukai's OCR, translation and
inpainting engines.  Real-CUGAN and Real-ESRGAN are optional portable NCNN
components downloaded on first use, verified with pinned SHA-256 hashes, and
executed out of process.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile

import numpy as np
from PIL import Image

from modules.utils.paths import get_user_data_dir


class ExportEnhancementError(RuntimeError):
    """Raised when an export enhancement component cannot finish safely."""


@dataclass(frozen=True)
class ExportEnhancementOptions:
    """Serializable choices made in the export-quality dialog."""

    target_long_edge: int = 0
    profile: str = "manga_balanced"
    protect_gradients: bool = True
    page_format: str = "png"
    jpeg_quality: int = 95

    @classmethod
    def from_dict(cls, raw: dict | None) -> "ExportEnhancementOptions":
        data = raw if isinstance(raw, dict) else {}
        target = int(data.get("target_long_edge", 0) or 0)
        if target not in {0, 2048, 4096, 6144, 8192}:
            target = 0

        profile = str(data.get("profile", "manga_balanced") or "manga_balanced")
        if profile not in {
            "lanczos",
            "manga_detail",
            "manga_balanced",
            "manga_denoise",
            "realesrgan_anime",
            "realesrgan_general",
        }:
            profile = "manga_balanced"

        page_format = str(data.get("page_format", "png") or "png").lower()
        if page_format not in {"png", "jpg"}:
            page_format = "png"

        return cls(
            target_long_edge=target,
            profile=profile,
            protect_gradients=bool(data.get("protect_gradients", True)),
            page_format=page_format,
            jpeg_quality=max(85, min(100, int(data.get("jpeg_quality", 95) or 95))),
        )

    def to_dict(self) -> dict:
        return asdict(self)


_COMPONENTS = {
    "realcugan": {
        "version": "20220728",
        "url": (
            "https://github.com/nihui/realcugan-ncnn-vulkan/releases/download/"
            "20220728/realcugan-ncnn-vulkan-20220728-windows.zip"
        ),
        "archive": "realcugan-ncnn-vulkan-20220728-windows.zip",
        "sha256": "c6e08d46c11704b1e3a1ada9ddd591cb5005f52f132136c8633ba25def400e01",
        "executable": "realcugan-ncnn-vulkan.exe",
    },
    "realesrgan": {
        "version": "20220424",
        "url": (
            "https://github.com/xinntao/Real-ESRGAN/releases/download/"
            "v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip"
        ),
        "archive": "realesrgan-ncnn-vulkan-20220424-windows.zip",
        "sha256": "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d",
        "executable": "realesrgan-ncnn-vulkan.exe",
    },
}

_COMPONENT_LOCK = threading.RLock()
_RESAMPLING = getattr(Image, "Resampling", Image)


def output_dimensions(image: np.ndarray, target_long_edge: int) -> tuple[int, int]:
    """Return (width, height), preserving aspect ratio."""

    height, width = image.shape[:2]
    target = int(target_long_edge or 0)
    if target <= 0:
        return width, height
    ratio = target / float(max(width, height))
    return max(1, int(round(width * ratio))), max(1, int(round(height * ratio)))


def profile_engine(profile: str) -> str | None:
    if profile.startswith("manga_"):
        return "realcugan"
    if profile.startswith("realesrgan_"):
        return "realesrgan"
    return None


def component_is_installed(profile: str) -> bool:
    engine = profile_engine(profile)
    if not engine:
        return True
    try:
        return _find_installed_executable(engine) is not None
    except Exception:
        return False


def enhance_export_background(
    rgb_image: np.ndarray,
    raw_options: ExportEnhancementOptions | dict | None,
) -> np.ndarray:
    """Restore/resize a clean page background without rasterizing its text.

    Text and watermark layers are composited afterwards by the Qt renderer, so
    the neural model never distorts translated lettering.
    """

    options = (
        raw_options
        if isinstance(raw_options, ExportEnhancementOptions)
        else ExportEnhancementOptions.from_dict(raw_options)
    )
    source = _normalise_rgb(rgb_image)
    target_width, target_height = output_dimensions(source, options.target_long_edge)
    if options.target_long_edge <= 0:
        return source.copy()

    baseline = _resize_rgb(source, (target_width, target_height))
    if options.profile == "lanczos":
        return baseline

    engine = profile_engine(options.profile)
    if not engine:
        return baseline

    executable = ensure_component_ready(engine)
    native_scale = _native_scale(source, options)
    restored = _run_ncnn_engine(executable, engine, source, options.profile, native_scale)
    restored = _resize_rgb(restored, (target_width, target_height))

    if options.protect_gradients:
        restored = _blend_original_smooth_regions(restored, baseline)
    return restored


def composite_overlay(background_rgb: np.ndarray, overlay_rgba: np.ndarray) -> np.ndarray:
    """Alpha-composite a high-resolution text/watermark overlay."""

    background = _normalise_rgb(background_rgb)
    overlay = np.asarray(overlay_rgba)
    if overlay.ndim != 3 or overlay.shape[2] != 4:
        raise ValueError("The export overlay must be an RGBA image.")
    if overlay.shape[:2] != background.shape[:2]:
        raise ValueError("The export overlay and background dimensions do not match.")

    result = np.empty_like(background)
    for row_start in range(0, background.shape[0], 256):
        row_end = min(background.shape[0], row_start + 256)
        alpha = overlay[row_start:row_end, :, 3:4].astype(np.float32) / 255.0
        foreground = overlay[row_start:row_end, :, :3].astype(np.float32)
        base = background[row_start:row_end].astype(np.float32)
        result[row_start:row_end] = np.clip(
            foreground * alpha + base * (1.0 - alpha),
            0,
            255,
        ).astype(np.uint8)
    return result


def save_export_image(
    output_path: str,
    rgb_image: np.ndarray,
    raw_options: ExportEnhancementOptions | dict | None,
) -> None:
    options = (
        raw_options
        if isinstance(raw_options, ExportEnhancementOptions)
        else ExportEnhancementOptions.from_dict(raw_options)
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(_normalise_rgb(rgb_image), mode="RGB")
    if options.page_format == "jpg":
        image.save(
            destination,
            format="JPEG",
            quality=options.jpeg_quality,
            subsampling=0,
            optimize=True,
        )
    else:
        image.save(destination, format="PNG", compress_level=6)


def ensure_component_ready(engine: str) -> Path:
    """Download, verify and safely unpack one portable Windows component."""

    if engine not in _COMPONENTS:
        raise ExportEnhancementError(f"Motor de mejora desconocido: {engine}")
    if platform.system() != "Windows":
        raise ExportEnhancementError(
            "Los motores NCNN integrados están disponibles actualmente para Windows."
        )

    with _COMPONENT_LOCK:
        installed = _find_installed_executable(engine)
        if installed is not None:
            return installed

        spec = _COMPONENTS[engine]
        engines_root = Path(get_user_data_dir()) / "engines"
        engines_root.mkdir(parents=True, exist_ok=True)
        downloads_dir = engines_root / "downloads"
        archive_path = downloads_dir / str(spec["archive"])
        try:
            _download_with_sha256(
                str(spec["url"]),
                archive_path,
                str(spec["sha256"]),
            )
            install_dir = engines_root / f"{engine}-{spec['version']}"
            _install_verified_archive(
                archive_path,
                install_dir,
                str(spec["executable"]),
                engines_root,
            )
        except ExportEnhancementError:
            raise
        except Exception as exc:
            raise ExportEnhancementError(
                "No se pudo preparar el motor de mejora. Comprueba la conexión "
                "a Internet, el espacio disponible y vuelve a intentarlo."
            ) from exc

        installed = _find_installed_executable(engine)
        if installed is None:
            raise ExportEnhancementError(
                "El paquete verificado no contiene el ejecutable esperado."
            )
        return installed


def _find_installed_executable(engine: str) -> Path | None:
    spec = _COMPONENTS[engine]
    install_dir = (
        Path(get_user_data_dir())
        / "engines"
        / f"{engine}-{spec['version']}"
    )
    if not install_dir.is_dir():
        return None
    candidates = list(install_dir.rglob(str(spec["executable"])))
    return candidates[0] if candidates else None


def _download_with_sha256(url: str, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and _file_sha256(destination) == expected_sha256:
        return

    temporary = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    try:
        request = Request(url, headers={"User-Agent": "MukaiTranslator/1.0"})
        with urlopen(request, timeout=90) as response, open(temporary, "wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
        if digest.hexdigest().lower() != expected_sha256.lower():
            raise ExportEnhancementError(
                "La descarga del motor no superó la verificación de seguridad SHA-256."
            )
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _install_verified_archive(
    archive_path: Path,
    install_dir: Path,
    executable_name: str,
    engines_root: Path,
) -> None:
    staging = Path(tempfile.mkdtemp(prefix=".upscaler-", dir=str(engines_root)))
    try:
        with ZipFile(archive_path) as archive:
            root = staging.resolve()
            for member in archive.infolist():
                target = (staging / member.filename).resolve()
                if os.path.commonpath((str(root), str(target))) != str(root):
                    raise ExportEnhancementError(
                        "El paquete del motor contiene una ruta no segura."
                    )
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, open(target, "wb") as output:
                    shutil.copyfileobj(source, output)

        if not list(staging.rglob(executable_name)):
            raise ExportEnhancementError(
                "El paquete del motor está incompleto."
            )

        _safe_remove_install_dir(install_dir, engines_root)
        os.replace(staging, install_dir)
    finally:
        if staging.exists():
            _safe_remove_install_dir(staging, engines_root)


def _safe_remove_install_dir(path: Path, engines_root: Path) -> None:
    root = engines_root.resolve()
    target = path.resolve()
    if target == root or os.path.commonpath((str(root), str(target))) != str(root):
        raise ExportEnhancementError("Se rechazó una ruta de instalación no segura.")
    if path.exists():
        shutil.rmtree(path)


def _native_scale(
    source: np.ndarray,
    options: ExportEnhancementOptions,
) -> int:
    width, height = source.shape[1], source.shape[0]
    target = max(1, int(options.target_long_edge))
    ratio = target / float(max(width, height))
    if options.profile.startswith("realesrgan_"):
        return 4
    if ratio <= 2.2:
        return 2
    if ratio <= 3.2:
        return 3
    return 4


def _run_ncnn_engine(
    executable: Path,
    engine: str,
    source: np.ndarray,
    profile: str,
    native_scale: int,
) -> np.ndarray:
    with tempfile.TemporaryDirectory(prefix="mukai-upscale-") as temp_dir:
        input_path = Path(temp_dir) / "input.png"
        output_path = Path(temp_dir) / "output.png"
        Image.fromarray(source, mode="RGB").save(input_path, format="PNG")

        if engine == "realcugan":
            noise_level = {
                "manga_detail": -1,
                "manga_balanced": 0,
                "manga_denoise": 3,
            }.get(profile, 0)
            model_dir = executable.parent / "models-se"
            command = [
                str(executable),
                "-i",
                str(input_path),
                "-o",
                str(output_path),
                "-s",
                str(native_scale),
                "-n",
                str(noise_level),
                "-m",
                str(model_dir),
                "-t",
                "0",
                "-j",
                "1:2:2",
                "-f",
                "png",
            ]
        else:
            model_name = (
                "realesrgan-x4plus"
                if profile == "realesrgan_general"
                else "realesrgan-x4plus-anime"
            )
            command = [
                str(executable),
                "-i",
                str(input_path),
                "-o",
                str(output_path),
                "-s",
                "4",
                "-n",
                model_name,
                "-t",
                "0",
                "-f",
                "png",
            ]

        kwargs: dict = {
            "cwd": str(executable.parent),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "check": False,
            "timeout": 1200,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            completed = subprocess.run(command, **kwargs)
        except subprocess.TimeoutExpired as exc:
            raise ExportEnhancementError(
                "El motor de mejora superó el límite de 20 minutos para una página."
            ) from exc
        except OSError as exc:
            raise ExportEnhancementError(
                "Windows no pudo iniciar el motor de mejora."
            ) from exc

        if completed.returncode != 0 or not output_path.is_file():
            detail = (completed.stderr or completed.stdout or "").strip()[-1600:]
            message = (
                "El motor de mejora no pudo procesar la página. Actualiza el "
                "controlador gráfico y comprueba que Vulkan esté disponible."
            )
            if detail:
                message = f"{message}\n\nDetalle del motor:\n{detail}"
            raise ExportEnhancementError(message)

        try:
            with Image.open(output_path) as result:
                return np.asarray(result.convert("RGB"), dtype=np.uint8).copy()
        except Exception as exc:
            raise ExportEnhancementError(
                "El motor terminó, pero su imagen de salida no se pudo leer."
            ) from exc


def _normalise_rgb(image: np.ndarray) -> np.ndarray:
    array = np.asarray(image)
    if array.ndim == 2:
        array = np.repeat(array[:, :, None], 3, axis=2)
    if array.ndim != 3 or array.shape[2] < 3:
        raise ValueError("Expected an RGB image array.")
    if array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(array[:, :, :3])


def _resize_rgb(image: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    width, height = size
    if (image.shape[1], image.shape[0]) == (width, height):
        return image.copy()
    pil_image = Image.fromarray(_normalise_rgb(image), mode="RGB")
    return np.asarray(
        pil_image.resize((width, height), _RESAMPLING.LANCZOS),
        dtype=np.uint8,
    ).copy()


def _blend_original_smooth_regions(
    restored: np.ndarray,
    baseline: np.ndarray,
    strength: float = 0.38,
) -> np.ndarray:
    """Keep original gradients while retaining AI detail in lines/textures."""

    try:
        import cv2
    except Exception:
        return np.clip(
            restored.astype(np.float32) * (1.0 - strength * 0.35)
            + baseline.astype(np.float32) * (strength * 0.35),
            0,
            255,
        ).astype(np.uint8)

    height, width = restored.shape[:2]
    preview_scale = min(1.0, 1200.0 / max(width, height))
    preview_size = (
        max(1, int(round(width * preview_scale))),
        max(1, int(round(height * preview_scale))),
    )
    preview = cv2.resize(baseline, preview_size, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(preview, cv2.COLOR_RGB2GRAY).astype(np.float32)
    laplacian = np.abs(cv2.Laplacian(gray, cv2.CV_32F, ksize=3))
    gradient_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    structure = laplacian + 0.18 * cv2.magnitude(gradient_x, gradient_y)

    # High values mean a smooth field such as a sky or a painted gradient.
    smooth = np.clip((18.0 - structure) / 18.0, 0.0, 1.0)
    smooth = cv2.GaussianBlur(smooth, (0, 0), sigmaX=1.2)
    smooth_mask = cv2.resize(
        np.round(smooth * 255.0).astype(np.uint8),
        (width, height),
        interpolation=cv2.INTER_LINEAR,
    )

    result = np.empty_like(restored)
    for row_start in range(0, height, 192):
        row_end = min(height, row_start + 192)
        alpha = (
            smooth_mask[row_start:row_end, :, None].astype(np.float32)
            / 255.0
            * float(strength)
        )
        ai_rows = restored[row_start:row_end].astype(np.float32)
        base_rows = baseline[row_start:row_end].astype(np.float32)
        result[row_start:row_end] = np.clip(
            ai_rows * (1.0 - alpha) + base_rows * alpha,
            0,
            255,
        ).astype(np.uint8)
    return result

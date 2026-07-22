from __future__ import annotations

import os
import hashlib
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen, urlretrieve
from zipfile import ZipFile

from modules.utils.paths import get_user_data_dir


REPO_URL = "https://github.com/D-Ogi/WatermarkRemover-AI.git"
REPO_ARCHIVE_URL = "https://github.com/D-Ogi/WatermarkRemover-AI/archive/refs/heads/main.zip"
LAMA_MODEL_URL = "https://github.com/Sanster/models/releases/download/add_big_lama/big-lama.pt"
LAMA_MODEL_BYTES = 205_669_692
SIDECAR_DIR = Path(get_user_data_dir()) / "external" / "WatermarkRemover-AI"
VENV_DIR = SIDECAR_DIR / ".venv"
RUNTIME_DIR = Path(get_user_data_dir()) / "runtime"
UV_VERSION = "0.11.28"
UV_WINDOWS_URL = (
    "https://releases.astral.sh/github/uv/releases/download/"
    f"{UV_VERSION}/uv-x86_64-pc-windows-msvc.zip"
)
UV_WINDOWS_SHA256 = "0a23463216d09c6a72ff80ef5dc5a795f07dc1575cb84d24596c2f124a441b7b"
INSTALL_MARKER = VENV_DIR / ".mukai-installed"
SAM_INSTALL_MARKER = VENV_DIR / ".mukai-segment-anything-installed"
SAM_SOURCE_URL = "https://github.com/facebookresearch/segment-anything/archive/refs/heads/main.zip"
FLORENCE_REMOTE_MODEL_ID = "florence-community/Florence-2-base"
LOCAL_FLORENCE_DIR = SIDECAR_DIR / "models" / "Florence-2-community-base"
FLORENCE_MODEL_ID = os.environ.get("WATERMARK_REMOVER_FLORENCE_MODEL", str(LOCAL_FLORENCE_DIR))
DEFAULT_DETECTION_PROMPT = "watermark|text watermark|transparent watermark|website watermark|logo"
FLORENCE_FILES = [
    "added_tokens.json",
    "config.json",
    "generation_config.json",
    "merges.txt",
    "model.safetensors",
    "preprocessor_config.json",
    "processor_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
]


@dataclass(frozen=True)
class WatermarkRemovalResult:
    output_path: str
    stdout: str
    stderr: str


def remove_watermark_from_file(
    input_path: str,
    output_dir: str,
    detection_prompt: str = DEFAULT_DETECTION_PROMPT,
    max_bbox_percent: float = 15.0,
    max_passes: int = 3,
) -> WatermarkRemovalResult:
    python_exe = ensure_sidecar_ready()
    _download_florence_model(python_exe)
    repo_dir = SIDECAR_DIR
    remwm = repo_dir / "remwm.py"
    if not remwm.exists():
        raise RuntimeError("WatermarkRemover-AI remwm.py was not found after setup.")

    output_path = Path(output_dir) / f"{Path(input_path).stem}_watermark_cleaned.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(python_exe),
        str(remwm),
        str(input_path),
        str(output_path),
        "--overwrite",
        "--force-format",
        "PNG",
        "--max-bbox-percent",
        str(float(max_bbox_percent)),
        "--detection-prompt",
        detection_prompt,
    ]
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    env.setdefault("HF_HUB_DISABLE_XET", "1")
    env.setdefault("WATERMARK_REMOVER_FLORENCE_MODEL", FLORENCE_MODEL_ID)
    env["WATERMARK_REMOVER_MAX_PASSES"] = str(max(1, min(3, int(max_passes))))
    env.setdefault("WATERMARK_REMOVER_MASK_DILATE", "auto")
    env.setdefault("WATERMARK_REMOVER_MASK_CLOSE", "11")

    completed = subprocess.run(
        cmd,
        cwd=str(repo_dir),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=None,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "WatermarkRemover-AI failed.\n"
            f"STDOUT:\n{completed.stdout[-4000:]}\n\n"
            f"STDERR:\n{completed.stderr[-4000:]}"
        )
    if not output_path.exists():
        raise RuntimeError(
            "WatermarkRemover-AI finished but no output image was created.\n"
            f"STDOUT:\n{completed.stdout[-4000:]}\n\n"
            f"STDERR:\n{completed.stderr[-4000:]}"
        )

    return WatermarkRemovalResult(
        output_path=str(output_path),
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def ensure_sidecar_ready() -> Path:
    repo_dir = _ensure_repo()
    _patch_repo(repo_dir)
    python_exe = _ensure_venv(repo_dir)
    if not INSTALL_MARKER.exists():
        _install_dependencies(python_exe)
        INSTALL_MARKER.write_text("ok", encoding="utf-8")
    return python_exe


def ensure_sam_sidecar_ready() -> Path:
    """Prepare SAM only when the Magic Eraser actually requests it.

    WatermarkRemover-AI remains untouched for normal launches.  Installing SAM
    in the same isolated sidecar also avoids adding PyTorch to Mukai's ONNX
    application environment or changing any existing inpainting engine.
    """
    python_exe = ensure_sidecar_ready()
    if _python_can_import(python_exe, "segment_anything"):
        return python_exe

    _run_pip(
        python_exe,
        [
            "install",
            "--upgrade",
            "--no-deps",
            SAM_SOURCE_URL,
        ],
    )
    if not _python_can_import(python_exe, "segment_anything"):
        raise RuntimeError("Segment Anything could not be imported after installation.")
    SAM_INSTALL_MARKER.write_text("ok", encoding="utf-8")
    return python_exe


def preload_watermark_remover_assets(
    progress: Callable[[str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> None:
    def emit(message: str) -> None:
        if progress is not None:
            progress(message)

    emit("Preparing WatermarkRemover-AI sidecar...")
    python_exe = ensure_sidecar_ready()

    if should_cancel is not None and should_cancel():
        return
    emit("Preparing LaMA watermark inpainting model...")
    _download_lama_model(python_exe)

    if should_cancel is not None and should_cancel():
        return
    emit("Preparing Florence-2 watermark detection model...")
    _download_florence_model(python_exe)


def _ensure_repo() -> Path:
    if (SIDECAR_DIR / "remwm.py").exists():
        _patch_repo(SIDECAR_DIR)
        return SIDECAR_DIR

    SIDECAR_DIR.parent.mkdir(parents=True, exist_ok=True)
    if SIDECAR_DIR.exists():
        shutil.rmtree(SIDECAR_DIR)

    git_exe = shutil.which("git")
    if git_exe:
        try:
            subprocess.run(
                [git_exe, "clone", "--depth", "1", REPO_URL, str(SIDECAR_DIR)],
                check=True,
                text=True,
            )
            _patch_repo(SIDECAR_DIR)
            return SIDECAR_DIR
        except subprocess.CalledProcessError:
            if SIDECAR_DIR.exists():
                shutil.rmtree(SIDECAR_DIR)

    _download_repo_archive()
    _patch_repo(SIDECAR_DIR)
    return SIDECAR_DIR


def _ensure_venv(repo_dir: Path) -> Path:
    scripts_dir = VENV_DIR / ("Scripts" if os.name == "nt" else "bin")
    python_exe = scripts_dir / ("python.exe" if os.name == "nt" else "python")
    if python_exe.exists():
        return python_exe

    if getattr(sys, "frozen", False):
        if os.name != "nt":
            raise RuntimeError("The packaged watermark sidecar currently supports Windows only.")
        uv_exe = _ensure_uv_runtime()
        env = os.environ.copy()
        env["UV_PYTHON_INSTALL_DIR"] = str(RUNTIME_DIR / "python")
        env["UV_CACHE_DIR"] = str(RUNTIME_DIR / "cache")
        env["UV_NO_MODIFY_PATH"] = "1"
        subprocess.run(
            [
                str(uv_exe),
                "venv",
                "--python",
                "3.12",
                "--managed-python",
                "--seed",
                "--no-config",
                str(VENV_DIR),
            ],
            cwd=str(repo_dir),
            env=env,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], cwd=str(repo_dir), check=True)

    if not python_exe.exists():
        raise RuntimeError("The isolated watermark Python runtime was not created.")
    return python_exe


def _ensure_uv_runtime() -> Path:
    """Install a pinned, checksum-verified uv binary for frozen customer builds.

    PyInstaller executables cannot create a virtual environment with
    ``sys.executable -m venv`` because ``sys.executable`` is the application
    itself. uv supplies an isolated Python 3.12 automatically without changing
    the user's PATH or requiring a system-wide Python installation.
    """
    uv_exe = RUNTIME_DIR / "uv" / UV_VERSION / "uv.exe"
    if uv_exe.is_file():
        return uv_exe

    archive_path = RUNTIME_DIR / "downloads" / f"uv-{UV_VERSION}-windows-x64.zip"
    _download_with_sha256(UV_WINDOWS_URL, archive_path, UV_WINDOWS_SHA256)
    uv_exe.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive_path) as archive:
        try:
            uv_member = archive.getinfo("uv.exe")
        except KeyError as exc:
            raise RuntimeError("The verified uv archive does not contain uv.exe.") from exc
        with archive.open(uv_member) as source, open(uv_exe, "wb") as destination:
            shutil.copyfileobj(source, destination)
    return uv_exe


def _download_with_sha256(url: str, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and _file_sha256(destination) == expected_sha256:
        return

    temporary = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    try:
        request = Request(url, headers={"User-Agent": "MukaiTranslator/1.0"})
        with urlopen(request, timeout=60) as response, open(temporary, "wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
        if digest.hexdigest().lower() != expected_sha256.lower():
            raise RuntimeError("The uv runtime failed its SHA-256 verification.")
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


def _install_dependencies(python_exe: Path) -> None:
    # Install only the CLI dependencies needed by remwm.py. GUI-only packages
    # from the upstream requirements are intentionally skipped.
    _run_pip(python_exe, ["install", "--upgrade", "pip", "setuptools", "wheel"])
    _run_pip(
        python_exe,
        [
            "install",
            "--upgrade",
            "--extra-index-url",
            "https://download.pytorch.org/whl/cu124",
            "torch>=2.4.0",
            "torchvision>=0.19.0",
            "transformers>=4.50.0",
            "diffusers>=0.30.0",
            "numpy<2",
            "opencv-python-headless>=4.8.0,<4.12.0",
            "Pillow>=10.0.0",
            "huggingface_hub",
            "loguru",
            "click",
            "tqdm",
            "psutil",
            "pyyaml",
        ],
    )
    _run_pip(python_exe, ["install", "--upgrade", "iopaint", "--no-deps"])
    _run_pip(
        python_exe,
        [
            "install",
            "pydantic",
            "typer",
            "einops",
            "omegaconf",
            "easydict",
            "yacs",
        ],
    )


def _run_pip(python_exe: Path, args: list[str]) -> None:
    kwargs = {
        "cwd": str(SIDECAR_DIR),
        "check": True,
        "text": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.run([str(python_exe), "-m", "pip", *args], **kwargs)


def _python_can_import(python_exe: Path, module_name: str) -> bool:
    kwargs = {
        "cwd": str(SIDECAR_DIR),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "check": False,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    completed = subprocess.run(
        [str(python_exe), "-c", f"import {module_name}"],
        **kwargs,
    )
    return completed.returncode == 0


def _download_repo_archive() -> None:
    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        archive_path = tmp_path / "WatermarkRemover-AI.zip"
        extract_path = tmp_path / "extract"
        urlretrieve(REPO_ARCHIVE_URL, archive_path)
        with ZipFile(archive_path) as archive:
            archive.extractall(extract_path)

        roots = [path for path in extract_path.iterdir() if path.is_dir()]
        if not roots:
            raise RuntimeError("WatermarkRemover-AI archive did not contain a repository folder.")
        shutil.move(str(roots[0]), str(SIDECAR_DIR))


def _patch_repo(repo_dir: Path) -> None:
    remwm = repo_dir / "remwm.py"
    if not remwm.exists():
        return

    text = remwm.read_text(encoding="utf-8")
    if "HF_HUB_DISABLE_XET" not in text:
        text = text.replace(
            "from PIL import Image, ImageDraw\n",
            'from PIL import Image, ImageDraw\nimport os\nos.environ.setdefault("HF_HUB_DISABLE_XET", "1")\n',
            1,
        )
    if "WATERMARK_REMOVER_FLORENCE_MODEL" not in text:
        text = text.replace(
            "import os\n",
            f'import os\nFLORENCE_MODEL_ID = os.environ.get("WATERMARK_REMOVER_FLORENCE_MODEL", {str(LOCAL_FLORENCE_DIR)!r})\n',
            1,
        )
    else:
        text = _replace_florence_default(text)
    text = text.replace('"florence-community/Florence-2-large"', "FLORENCE_MODEL_ID")
    text = text.replace('"microsoft/Florence-2-base"', "FLORENCE_MODEL_ID")
    text = _patch_multi_pass_image_processing(text)
    text = _patch_manga_text_guard(text)
    text = _patch_guarded_empty_mask_loop(text)
    text = _patch_prompt_sweep_image_processing(text)
    remwm.write_text(text, encoding="utf-8")


def _download_lama_model(python_exe: Path) -> None:
    dest = Path.home() / ".cache" / "torch" / "hub" / "checkpoints" / "big-lama.pt"
    if _file_ready(dest, LAMA_MODEL_BYTES):
        return
    _prepare_resumable_download(dest)
    _download_url(LAMA_MODEL_URL, dest)
    if not _file_ready(dest, LAMA_MODEL_BYTES):
        raise RuntimeError(f"LaMA model download is incomplete: {dest}")


def _download_florence_model(python_exe: Path) -> None:
    LOCAL_FLORENCE_DIR.mkdir(parents=True, exist_ok=True)
    for file_name in FLORENCE_FILES:
        target = LOCAL_FLORENCE_DIR / file_name
        if target.exists() and target.stat().st_size > 0:
            continue
        url = f"https://huggingface.co/{FLORENCE_REMOTE_MODEL_ID}/resolve/main/{file_name}"
        _download_url(url, target)


def _download_url(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target.with_suffix(target.suffix + ".download")
    curl_exe = shutil.which("curl")
    if curl_exe:
        subprocess.run(
            [
                curl_exe,
                "--fail",
                "--location",
                "--continue-at",
                "-",
                "--retry",
                "3",
                "--retry-delay",
                "2",
                "--output",
                str(temp_target),
                url,
            ],
            check=True,
            text=True,
        )
    else:
        urlretrieve(url, temp_target)
    temp_target.replace(target)


def _file_ready(path: Path, min_size: int | None = None) -> bool:
    if not path.exists():
        return False
    size = path.stat().st_size
    if size <= 0:
        return False
    return min_size is None or size >= min_size


def _prepare_resumable_download(target: Path) -> None:
    temp_target = target.with_suffix(target.suffix + ".download")
    if target.exists() and target.stat().st_size > 0 and not temp_target.exists():
        target.replace(temp_target)


def _replace_florence_default(text: str) -> str:
    marker = 'FLORENCE_MODEL_ID = os.environ.get("WATERMARK_REMOVER_FLORENCE_MODEL", '
    start = text.find(marker)
    if start == -1:
        return text
    value_start = start + len(marker)
    value_end = text.find(")", value_start)
    if value_end == -1:
        return text
    return text[:value_start] + repr(str(LOCAL_FLORENCE_DIR)) + text[value_end:]


def _patch_multi_pass_image_processing(text: str) -> str:
    if "WATERMARK_REMOVER_MAX_PASSES" in text:
        return text

    old = """    # Process image
    image = Image.open(image_path).convert("RGB")
    mask_image = get_watermark_mask(image, florence_model, florence_processor, device, max_bbox_percent, detection_prompt)

    if transparent:
        result_image = make_region_transparent(image, mask_image)
    else:
        lama_result = process_image_with_lama(np.array(image), np.array(mask_image), model_manager)
        result_image = Image.fromarray(cv2.cvtColor(lama_result, cv2.COLOR_BGR2RGB))
"""
    new = """    # Process image
    image = Image.open(image_path).convert("RGB")
    result_image = image
    prompt_values = [part.strip() for part in str(detection_prompt).split("|") if part.strip()] or ["watermark"]
    try:
        watermark_passes = int(os.environ.get("WATERMARK_REMOVER_MAX_PASSES", "1"))
    except ValueError:
        watermark_passes = 1
    watermark_passes = max(1, min(3, watermark_passes))

    for pass_index in range(watermark_passes):
        prompt_value = prompt_values[min(pass_index, len(prompt_values) - 1)]
        mask_image = get_watermark_mask(
            result_image,
            florence_model,
            florence_processor,
            device,
            max_bbox_percent,
            prompt_value,
        )
        mask_array = np.array(mask_image)
        if not np.any(mask_array):
            print(f"watermark_pass:{pass_index + 1}, detected:false")
            break
        print(f"watermark_pass:{pass_index + 1}, detected:true, prompt:{prompt_value}")

        if transparent:
            result_image = make_region_transparent(result_image, mask_image)
        else:
            lama_result = process_image_with_lama(np.array(result_image), mask_array, model_manager)
            result_image = Image.fromarray(cv2.cvtColor(lama_result, cv2.COLOR_BGR2RGB))
"""
    return text.replace(old, new, 1)


def _patch_manga_text_guard(text: str) -> str:
    helper = r'''

def _mukai_filter_manga_text_false_positives(image, mask_image):
    if os.environ.get("WATERMARK_REMOVER_PROTECT_MANGA_TEXT", "1") == "0":
        return mask_image

    mask_array = np.array(mask_image.convert("L"))
    if not np.any(mask_array):
        return mask_image

    image_array = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(image_array, cv2.COLOR_RGB2GRAY)
    saturation = cv2.cvtColor(image_array, cv2.COLOR_RGB2HSV)[:, :, 1]
    binary_mask = (mask_array > 0).astype(np.uint8)
    filtered = mask_array.copy()
    image_area = image_array.shape[0] * image_array.shape[1]

    scope_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))
    mask_scope = cv2.dilate(binary_mask, scope_kernel, iterations=1)
    white_seed = ((gray >= 238) & (mask_scope > 0)).astype(np.uint8)
    white_seed = cv2.morphologyEx(
        white_seed,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)),
        iterations=1,
    )
    white_seed = cv2.morphologyEx(
        white_seed,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
        iterations=1,
    )

    white_count, white_labels, white_stats, _ = cv2.connectedComponentsWithStats(white_seed, 8)
    protected_seed = np.zeros_like(binary_mask)
    min_bubble_area = max(140, int(image_area * 0.00008))
    max_bubble_area = int(image_area * 0.18)

    for white_index in range(1, white_count):
        x, y, width, height, area = white_stats[white_index]
        if area < min_bubble_area or area > max_bubble_area or width <= 0 or height <= 0:
            continue

        aspect_ratio = width / max(1, height)
        if aspect_ratio < 0.12 or aspect_ratio > 8.5:
            continue

        pad = 14
        x0 = max(0, x - pad)
        y0 = max(0, y - pad)
        x1 = min(gray.shape[1], x + width + pad)
        y1 = min(gray.shape[0], y + height + pad)
        expanded_region = gray[y0:y1, x0:x1]
        expanded_saturation = saturation[y0:y1, x0:x1]
        if expanded_region.size == 0:
            continue

        dark_fraction = float(np.mean(expanded_region <= 95))
        contrast = float(np.percentile(expanded_region, 95) - np.percentile(expanded_region, 5))
        color_fraction = float(np.mean(expanded_saturation >= 60))
        fill_ratio = area / max(1, width * height)
        if dark_fraction < 0.004 or contrast < 65 or fill_ratio < 0.20 or color_fraction > 0.10:
            continue

        protected_seed[white_labels == white_index] = 1

    protected = np.zeros_like(binary_mask)
    if np.any(protected_seed):
        protected = cv2.morphologyEx(
            protected_seed,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21)),
            iterations=1,
        )
        protected = cv2.dilate(
            protected,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)),
            iterations=1,
        )
    if np.any(protected & binary_mask):
        filtered[protected > 0] = 0
        print("watermark_guard:protected_nearby_manga_bubble")

    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(binary_mask, 8)
    if component_count <= 1:
        return Image.fromarray(filtered)

    min_component_area = max(48, int(image_area * 0.00005))

    for label_index in range(1, component_count):
        x, y, width, height, area = stats[label_index]
        if area < min_component_area or width <= 0 or height <= 0:
            continue

        region = gray[y:y + height, x:x + width]
        region_saturation = saturation[y:y + height, x:x + width]
        component = labels[y:y + height, x:x + width] == label_index
        component_pixels = region[component]
        component_saturation_pixels = region_saturation[component]
        if component_pixels.size == 0:
            continue

        component_white_fraction = float(np.mean(component_pixels >= 235))
        component_dark_fraction = float(np.mean(component_pixels <= 95))
        component_contrast = float(np.percentile(component_pixels, 95) - np.percentile(component_pixels, 5))
        component_color_fraction = float(np.mean(component_saturation_pixels >= 60))
        region_white_fraction = float(np.mean(region >= 235))
        region_dark_fraction = float(np.mean(region <= 95))
        region_contrast = float(np.percentile(region, 95) - np.percentile(region, 5))
        region_color_fraction = float(np.mean(region_saturation >= 60))

        looks_like_speech_bubble = (
            region_white_fraction >= 0.58
            and region_dark_fraction >= 0.006
            and region_contrast >= 80
            and region_color_fraction <= 0.10
        )
        looks_like_text_on_white = (
            component_white_fraction >= 0.58
            and 0.012 <= component_dark_fraction <= 0.40
            and component_contrast >= 95
            and component_color_fraction <= 0.10
        )

        if looks_like_speech_bubble or looks_like_text_on_white:
            filtered_region = filtered[y:y + height, x:x + width]
            filtered_region[component] = 0
            print(f"watermark_guard:skipped_manga_bubble_like_region:{x},{y},{x + width},{y + height}")

    return Image.fromarray(filtered)


def _mukai_expand_watermark_mask(image, mask_image):
    mask_array = np.array(mask_image.convert("L"))
    if not np.any(mask_array):
        return mask_image

    mask_array = ((mask_array > 0).astype(np.uint8) * 255)
    close_value = os.environ.get("WATERMARK_REMOVER_MASK_CLOSE", "11")
    dilate_value = os.environ.get("WATERMARK_REMOVER_MASK_DILATE", "auto")

    try:
        close_px = max(0, int(close_value))
    except ValueError:
        close_px = 11

    if str(dilate_value).lower() == "auto":
        shortest_side = max(1, min(image.size))
        dilate_px = max(15, min(45, int(shortest_side * 0.028)))
    else:
        try:
            dilate_px = max(0, int(dilate_value))
        except ValueError:
            dilate_px = 17

    if close_px > 1:
        close_px = close_px + 1 if close_px % 2 == 0 else close_px
        mask_array = cv2.morphologyEx(
            mask_array,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_px, close_px)),
            iterations=1,
        )

    if dilate_px > 1:
        dilate_px = dilate_px + 1 if dilate_px % 2 == 0 else dilate_px
        mask_array = cv2.dilate(
            mask_array,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_px, dilate_px)),
            iterations=1,
        )
        print(f"watermark_mask:expanded:{dilate_px}px")

    return _mukai_filter_manga_text_false_positives(image, Image.fromarray(mask_array))
'''
    marker = "\ndef process_image_with_lama("
    existing_start = text.find("\ndef _mukai_filter_manga_text_false_positives(")
    existing_end = text.find(marker, existing_start + 1) if existing_start != -1 else -1
    if existing_start != -1 and existing_end != -1:
        text = text[:existing_start] + helper + text[existing_end:]
    elif marker in text:
        text = text.replace(marker, helper + marker, 1)

    guard_call = "        mask_image = _mukai_filter_manga_text_false_positives(result_image, mask_image)\n"
    target = "        mask_array = np.array(mask_image)\n"
    if guard_call not in text and target in text:
        text = text.replace(target, guard_call + target, 1)

    return text


def _patch_guarded_empty_mask_loop(text: str) -> str:
    new = """        raw_mask_has_pixels = bool(np.any(np.array(mask_image)))
        mask_image = _mukai_filter_manga_text_false_positives(result_image, mask_image)
        mask_array = np.array(mask_image)
        if not np.any(mask_array):
            if pass_index + 1 < watermark_passes:
                reason = "guarded" if raw_mask_has_pixels else "detected:false"
                print(f"watermark_pass:{pass_index + 1}, {reason}, prompt:{prompt_value}")
                continue
            print(f"watermark_pass:{pass_index + 1}, detected:false")
            break
"""
    old_unpatched = """        mask_image = _mukai_filter_manga_text_false_positives(result_image, mask_image)
        mask_array = np.array(mask_image)
        if not np.any(mask_array):
            print(f"watermark_pass:{pass_index + 1}, detected:false")
            break
"""
    old_guarded = """        raw_mask_has_pixels = bool(np.any(np.array(mask_image)))
        mask_image = _mukai_filter_manga_text_false_positives(result_image, mask_image)
        mask_array = np.array(mask_image)
        if not np.any(mask_array):
            if raw_mask_has_pixels and pass_index + 1 < watermark_passes:
                print(f"watermark_pass:{pass_index + 1}, guarded:true, prompt:{prompt_value}")
                continue
            print(f"watermark_pass:{pass_index + 1}, detected:false")
            break
"""
    if old_guarded in text:
        return text.replace(old_guarded, new, 1)
    return text.replace(old_unpatched, new, 1)


def _patch_prompt_sweep_image_processing(text: str) -> str:
    start_marker = '    # Process image\n    image = Image.open(image_path).convert("RGB")\n'
    end_marker = "\n    # Determine output format"
    start = text.find(start_marker)
    if start == -1:
        return text
    end = text.find(end_marker, start)
    if end == -1:
        return text

    current_block = text[start:end]
    if "stopping:multiple_regions" in current_block:
        return text

    new = """    # Process image
    image = Image.open(image_path).convert("RGB")
    result_image = image
    prompt_values = [part.strip() for part in str(detection_prompt).split("|") if part.strip()] or ["watermark"]
    try:
        watermark_passes = int(os.environ.get("WATERMARK_REMOVER_MAX_PASSES", "1"))
    except ValueError:
        watermark_passes = 1
    watermark_passes = max(1, min(3, watermark_passes))

    for pass_index in range(watermark_passes):
        combined_mask_array = np.zeros((result_image.height, result_image.width), dtype=np.uint8)
        detected_prompts = []
        guarded_prompts = []

        for prompt_value in prompt_values:
            mask_image = get_watermark_mask(
                result_image,
                florence_model,
                florence_processor,
                device,
                max_bbox_percent,
                prompt_value,
            )
            raw_mask_has_pixels = bool(np.any(np.array(mask_image)))
            mask_image = _mukai_filter_manga_text_false_positives(result_image, mask_image)
            mask_array = np.array(mask_image)
            if np.any(mask_array):
                combined_mask_array = np.maximum(combined_mask_array, mask_array)
                detected_prompts.append(prompt_value)
            elif raw_mask_has_pixels:
                guarded_prompts.append(prompt_value)

        if not np.any(combined_mask_array):
            if guarded_prompts:
                print(f"watermark_pass:{pass_index + 1}, guarded:true, prompts:{','.join(guarded_prompts)}")
            else:
                print(f"watermark_pass:{pass_index + 1}, detected:false")
            break

        combined_mask_image = _mukai_expand_watermark_mask(result_image, Image.fromarray(combined_mask_array))
        combined_mask_array = np.array(combined_mask_image)
        if not np.any(combined_mask_array):
            print(f"watermark_pass:{pass_index + 1}, guarded:true, prompts:{','.join(detected_prompts)}")
            break

        cleaned_component_count = cv2.connectedComponentsWithStats(
            (combined_mask_array > 0).astype(np.uint8),
            8,
        )[0] - 1
        print(f"watermark_pass:{pass_index + 1}, detected:true, regions:{cleaned_component_count}, prompts:{','.join(detected_prompts)}")

        if transparent:
            result_image = make_region_transparent(result_image, combined_mask_image)
        else:
            lama_result = process_image_with_lama(np.array(result_image), combined_mask_array, model_manager)
            result_image = Image.fromarray(cv2.cvtColor(lama_result, cv2.COLOR_BGR2RGB))

        if cleaned_component_count >= 2:
            print(f"watermark_pass:{pass_index + 1}, stopping:multiple_regions")
            break
"""
    return text[:start] + new + text[end:]


def _run_python(python_exe: Path, script: str) -> None:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    env.setdefault("HF_HUB_DISABLE_XET", "1")
    env.setdefault("WATERMARK_REMOVER_FLORENCE_MODEL", FLORENCE_MODEL_ID)
    subprocess.run(
        [str(python_exe), "-c", script],
        cwd=str(SIDECAR_DIR),
        env=env,
        check=True,
        text=True,
    )

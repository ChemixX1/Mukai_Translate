"""Optional SAM mask refinement for the Magic Eraser.

The main application deliberately keeps its ONNX inpainting runtime free of
PyTorch.  Segment Anything therefore runs in the already isolated optional
watermark sidecar.  Its only output is a binary mask; the configured Mukai
inpainter (LaMa, AOT or MI-GAN) still performs every pixel reconstruction.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from app.watermark_remover_sidecar import ensure_sam_sidecar_ready
from modules.utils.download import ModelDownloader, ModelID


class SAMRefinementError(RuntimeError):
    """Raised when the optional AI mask refinement cannot be completed."""


class SAMMaskRefiner:
    """Refine a painted Magic Eraser mask without touching inpainting engines."""

    def __init__(self) -> None:
        self._runner_path = Path(__file__).with_name("sam_refiner_runner.py")

    @staticmethod
    def _normalise_mask(mask: np.ndarray, image: np.ndarray) -> np.ndarray:
        if image is None or image.ndim < 2:
            raise SAMRefinementError("No hay una imagen válida para refinar la máscara.")
        if mask is None or mask.ndim != 2:
            raise SAMRefinementError("Pinta una zona antes de usar el borrador mágico.")
        if tuple(mask.shape) != tuple(image.shape[:2]):
            raise SAMRefinementError("La máscara del borrador no coincide con el tamaño de la imagen.")

        result = np.where(mask > 0, 255, 0).astype(np.uint8)
        if not np.any(result):
            raise SAMRefinementError("Pinta una zona antes de usar el borrador mágico.")
        return result

    @staticmethod
    def _subprocess_kwargs() -> dict:
        kwargs: dict = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "check": False,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return kwargs

    def refine(self, image: np.ndarray, rough_mask: np.ndarray) -> np.ndarray:
        """Return SAM's safe refinement, always retaining the painted pixels.

        The model and its Python dependencies are downloaded only on the first
        use of the AI option.  This keeps launch time and the normal inpainting
        path exactly as they were before the Magic Eraser was added.
        """
        mask = self._normalise_mask(rough_mask, image)
        if not self._runner_path.is_file():
            raise SAMRefinementError("No se encontró el componente de refinado SAM.")

        try:
            sidecar_python = ensure_sam_sidecar_ready()
            checkpoint_path = ModelDownloader.primary_path(ModelID.SAM_VIT_B)
        except Exception as exc:
            raise SAMRefinementError(
                "No se pudo preparar SAM para el borrador mágico. "
                "Comprueba tu conexión e inténtalo nuevamente."
            ) from exc

        with TemporaryDirectory(prefix="mukai-sam-") as temp_dir:
            temp = Path(temp_dir)
            image_path = temp / "image.npy"
            mask_path = temp / "painted_mask.npy"
            result_path = temp / "refined_mask.npy"
            np.save(image_path, np.ascontiguousarray(image))
            np.save(mask_path, mask)

            command = [
                str(sidecar_python),
                str(self._runner_path),
                "--image",
                str(image_path),
                "--mask",
                str(mask_path),
                "--checkpoint",
                str(checkpoint_path),
                "--output",
                str(result_path),
            ]
            completed = subprocess.run(command, **self._subprocess_kwargs())
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()[-1800:]
                raise SAMRefinementError(
                    "SAM no pudo refinar la selección del borrador mágico."
                    + (f"\n{detail}" if detail else "")
                )
            if not result_path.is_file():
                raise SAMRefinementError("SAM terminó sin generar una máscara refinada.")

            try:
                refined = np.load(result_path, allow_pickle=False)
            except Exception as exc:
                raise SAMRefinementError("No se pudo leer la máscara refinada por SAM.") from exc

        if refined.shape != mask.shape:
            raise SAMRefinementError("SAM generó una máscara con un tamaño inesperado.")

        # A painted pixel is an explicit user decision.  Never let automatic
        # segmentation remove it from the mask, even when SAM is uncertain.
        return np.where((refined > 0) | (mask > 0), 255, 0).astype(np.uint8)

"""Small isolated runner used by :mod:`app.sam_mask_refiner`.

This script intentionally imports PyTorch and ``segment_anything`` only inside
the optional sidecar virtual environment.  Keeping it separate means the main
ONNX application and the existing inpainting engines remain unchanged.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def _painted_bounds(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise ValueError("The painted mask is empty.")
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _sample_positive_points(mask: np.ndarray, maximum: int = 16) -> np.ndarray:
    """Choose deterministic points spread over the user's painted area."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return np.empty((0, 2), dtype=np.float32)

    count = min(maximum, len(xs))
    positions = np.linspace(0, len(xs) - 1, count, dtype=np.int64)
    points = np.column_stack((xs[positions], ys[positions])).astype(np.float32)

    # Make the centre explicit; it makes very short strokes more stable.
    centre = np.array([[float(np.median(xs)), float(np.median(ys))]], dtype=np.float32)
    return np.unique(np.vstack((centre, points)), axis=0)


def _expand_binary(mask: np.ndarray, radius: int = 2) -> np.ndarray:
    """Create the small, deterministic safety margin allowed around a stroke."""
    source = np.asarray(mask, dtype=bool)
    if radius <= 0:
        return source.copy()
    height, width = source.shape
    padded = np.pad(source, radius, mode="constant", constant_values=False)
    result = np.zeros_like(source)
    diameter = (radius * 2) + 1
    for dy in range(diameter):
        for dx in range(diameter):
            result |= padded[dy : dy + height, dx : dx + width]
    return result


def _choose_candidate(
    masks: np.ndarray,
    scores: np.ndarray,
    rough_mask: np.ndarray,
) -> np.ndarray:
    """Pick a conservative SAM candidate and fall back to the painted mask."""
    rough = rough_mask > 0
    allowed = _expand_binary(rough, radius=2)
    rough_area = max(1, int(rough.sum()))
    best: np.ndarray | None = None
    best_rank = float("-inf")

    for candidate, confidence in zip(masks, scores):
        # SAM may recognise an entire balloon from a short stroke.  It can
        # improve the local edge, but never receives permission to leave this
        # two-pixel safety envelope.
        candidate = np.asarray(candidate, dtype=bool) & allowed
        candidate_area = int(candidate.sum())
        if candidate_area == 0:
            continue

        overlap = int(np.logical_and(candidate, rough).sum())
        coverage = overlap / rough_area
        union = int(np.logical_or(candidate, rough).sum())
        iou = overlap / max(1, union)
        expansion = candidate_area / rough_area

        # An entire speech bubble is a bad target for a magic eraser.  The
        # user-painted region is the safety boundary when SAM over-generalises.
        if coverage < 0.70 or expansion > 2.5:
            continue

        rank = (0.55 * coverage) + (0.30 * iou) + (0.15 * float(confidence))
        if rank > best_rank:
            best = candidate
            best_rank = rank

    if best is None:
        return rough.astype(np.uint8) * 255
    return np.where((best | rough) & allowed, 255, 0).astype(np.uint8)


def refine(image: np.ndarray, mask: np.ndarray, checkpoint: str) -> np.ndarray:
    import torch
    from segment_anything import SamPredictor, sam_model_registry

    if image.ndim != 3 or image.shape[2] < 3:
        raise ValueError("Expected an RGB image.")
    if mask.shape != image.shape[:2]:
        raise ValueError("Image and mask sizes differ.")

    rough = np.where(mask > 0, 255, 0).astype(np.uint8)
    x1, y1, x2, y2 = _painted_bounds(rough)
    height, width = rough.shape

    # SAM only needs context around the painted mark.  Cropping prevents a
    # large manga page from adding unnecessary latency and limits overreach.
    mark_size = max(x2 - x1 + 1, y2 - y1 + 1)
    context = max(32, min(256, int(mark_size * 0.55)))
    crop_x1 = max(0, x1 - context)
    crop_y1 = max(0, y1 - context)
    crop_x2 = min(width, x2 + context + 1)
    crop_y2 = min(height, y2 + context + 1)
    crop_image = np.ascontiguousarray(image[crop_y1:crop_y2, crop_x1:crop_x2, :3])
    crop_rough = rough[crop_y1:crop_y2, crop_x1:crop_x2]

    local_x1, local_y1, local_x2, local_y2 = _painted_bounds(crop_rough)
    # A small box padding gives SAM enough boundary context without allowing it
    # to swallow neighbouring art.
    pad = max(2, min(24, int(max(local_x2 - local_x1 + 1, local_y2 - local_y1 + 1) * 0.08)))
    box = np.array(
        [
            max(0, local_x1 - pad),
            max(0, local_y1 - pad),
            min(crop_rough.shape[1] - 1, local_x2 + pad),
            min(crop_rough.shape[0] - 1, local_y2 + pad),
        ],
        dtype=np.float32,
    )
    points = _sample_positive_points(crop_rough)
    labels = np.ones(len(points), dtype=np.int32)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = sam_model_registry["vit_b"](checkpoint=checkpoint)
    model.to(device=device)
    model.eval()
    predictor = SamPredictor(model)
    predictor.set_image(crop_image)
    masks, scores, _ = predictor.predict(
        point_coords=points,
        point_labels=labels,
        box=box,
        multimask_output=True,
    )

    output = np.zeros_like(rough, dtype=np.uint8)
    output[crop_y1:crop_y2, crop_x1:crop_x2] = _choose_candidate(masks, scores, crop_rough)
    allowed = _expand_binary(rough > 0, radius=2)
    return np.where(((output > 0) | (rough > 0)) & allowed, 255, 0).astype(np.uint8)


def main() -> int:
    parser = argparse.ArgumentParser(description="Refine a Magic Eraser mask with Segment Anything.")
    parser.add_argument("--image", required=True)
    parser.add_argument("--mask", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    image = np.load(args.image, allow_pickle=False)
    mask = np.load(args.mask, allow_pickle=False)
    output = refine(image, mask, args.checkpoint)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    np.save(args.output, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

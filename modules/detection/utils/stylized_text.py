"""High-confidence supplemental detection for coloured outlined manga text."""

from __future__ import annotations

import cv2
import numpy as np

from modules.utils.textblock import TextBlock


def _hue_distance(hue: np.ndarray, centre: int) -> np.ndarray:
    difference = np.abs(hue.astype(np.int16) - int(centre))
    return np.minimum(difference, 180 - difference)


def _merge_components(components: list[tuple[int, int, int, int, int]], gap: int = 75):
    groups = [
        ([x, y, x + width, y + height], [(x, y, width, height, area)])
        for x, y, width, height, area in components
    ]
    changed = True
    while changed:
        changed = False
        output = []
        while groups:
            bounds, members = groups.pop()
            index = 0
            while index < len(groups):
                other_bounds, other_members = groups[index]
                overlaps = not (
                    bounds[2] + gap < other_bounds[0]
                    or other_bounds[2] + gap < bounds[0]
                    or bounds[3] + gap < other_bounds[1]
                    or other_bounds[3] + gap < bounds[1]
                )
                if not overlaps:
                    index += 1
                    continue
                bounds = [
                    min(bounds[0], other_bounds[0]),
                    min(bounds[1], other_bounds[1]),
                    max(bounds[2], other_bounds[2]),
                    max(bounds[3], other_bounds[3]),
                ]
                members.extend(other_members)
                groups.pop(index)
                changed = True
                index = 0
            output.append((bounds, members))
        groups = output
    return groups


def _intersection_ratio(bounds: list[int], other: list[float]) -> float:
    x1, y1, x2, y2 = bounds
    ox1, oy1, ox2, oy2 = [float(value) for value in other]
    intersection = max(0.0, min(x2, ox2) - max(x1, ox1)) * max(
        0.0,
        min(y2, oy2) - max(y1, oy1),
    )
    return intersection / max(1.0, float((x2 - x1) * (y2 - y1)))


def detect_coloured_outlined_text(
    image: np.ndarray,
    existing_blocks: list[TextBlock],
) -> list[TextBlock]:
    """Detect unusually coloured, white-outlined free text missed by RT-DETR.

    The conservative white-outline requirement avoids treating ordinary manga
    artwork as text. This complements the neural detector; it never replaces
    or changes already detected dialogue blocks.
    """
    if image is None or image.ndim != 3 or image.size == 0:
        return []

    rgb = np.ascontiguousarray(image[..., :3], dtype=np.uint8)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    height, width = hsv.shape[:2]
    existing_bounds = [block.xyxy for block in existing_blocks if block.xyxy is not None]
    candidates: list[dict] = []

    for hue_centre in range(0, 180, 10):
        colour_mask = (
            (_hue_distance(hsv[..., 0], hue_centre) <= 6)
            & (hsv[..., 1] >= 105)
            & (hsv[..., 2] >= 55)
        ).astype(np.uint8)
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
            colour_mask,
            8,
        )
        if count <= 1:
            continue

        components = []
        for x, y, component_width, component_height, area in stats[1:]:
            x, y, component_width, component_height, area = map(
                int,
                (x, y, component_width, component_height, area),
            )
            fill_ratio = area / max(1, component_width * component_height)
            if (
                24 <= area <= 20000
                and max(component_width, component_height) >= 8
                and fill_ratio <= 0.72
            ):
                components.append(
                    (x, y, component_width, component_height, area)
                )

        for bounds, members in _merge_components(components):
            x1, y1, x2, y2 = bounds
            candidate_width = x2 - x1
            candidate_height = y2 - y1
            area = sum(member[4] for member in members)
            density = area / max(1, candidate_width * candidate_height)
            if (
                area < 180
                or max(candidate_width, candidate_height) < 120
                or candidate_width > width * 0.65
                or candidate_height > height * 0.50
                or density > 0.38
            ):
                continue
            longest_aspect = max(
                max(member[2], member[3]) / max(1, min(member[2], member[3]))
                for member in members
            )
            if len(members) < 3 and longest_aspect < 4.0:
                continue

            local_mask = np.zeros(
                (candidate_height, candidate_width),
                dtype=np.uint8,
            )
            for x, y, component_width, component_height, _area in members:
                local_mask[
                    y - y1:y - y1 + component_height,
                    x - x1:x - x1 + component_width,
                ] |= colour_mask[y:y + component_height, x:x + component_width]
            ring = cv2.dilate(
                local_mask,
                np.ones((9, 9), dtype=np.uint8),
                iterations=1,
            ).astype(bool) & ~local_mask.astype(bool)
            local_hsv = hsv[y1:y2, x1:x2]
            bright_outline = (
                ring
                & (local_hsv[..., 2] >= 190)
                & (local_hsv[..., 1] <= 75)
            )
            outline_ratio = int(np.count_nonzero(bright_outline)) / max(
                1,
                int(np.count_nonzero(ring)),
            )
            if outline_ratio < 0.55:
                continue
            if existing_bounds and max(
                _intersection_ratio(bounds, existing)
                for existing in existing_bounds
            ) > 0.25:
                continue

            pad = max(8, min(18, int(round(min(candidate_width, candidate_height) * 0.04))))
            if candidate_height >= candidate_width * 1.40:
                # Japanese vertical SFX commonly ends in smaller black dots or
                # punctuation after the coloured main strokes.
                trailing_pad = max(pad, int(round(candidate_height * 0.28)))
                padded_bounds = [
                    max(0, x1 - pad),
                    max(0, y1 - pad),
                    min(width, x2 + pad),
                    min(height, y2 + trailing_pad),
                ]
            elif candidate_width >= candidate_height * 1.40:
                trailing_pad = max(pad, int(round(candidate_width * 0.28)))
                padded_bounds = [
                    max(0, x1 - pad),
                    max(0, y1 - pad),
                    min(width, x2 + trailing_pad),
                    min(height, y2 + pad),
                ]
            else:
                padded_bounds = [
                    max(0, x1 - pad),
                    max(0, y1 - pad),
                    min(width, x2 + pad),
                    min(height, y2 + pad),
                ]
            colour_pixels = rgb[y1:y2, x1:x2][local_mask > 0]
            median_colour = tuple(
                int(value) for value in np.median(colour_pixels, axis=0)
            )
            candidates.append(
                {
                    "bounds": padded_bounds,
                    "hue": hue_centre,
                    "colour": median_colour,
                    "score": outline_ratio * np.log1p(area),
                }
            )

    selected: list[dict] = []
    for candidate in sorted(candidates, key=lambda item: item["score"], reverse=True):
        bounds = candidate["bounds"]
        if any(
            _intersection_ratio(bounds, kept["bounds"]) > 0.65
            or _intersection_ratio(kept["bounds"], bounds) > 0.65
            for kept in selected
        ):
            continue
        selected.append(candidate)

    return [
        TextBlock(
            text_bbox=np.asarray(candidate["bounds"], dtype=np.int32),
            text_class="text_free",
            direction="vertical",
            font_color=candidate["colour"],
            mask_hue=int(candidate["hue"]),
        )
        for candidate in selected
    ]

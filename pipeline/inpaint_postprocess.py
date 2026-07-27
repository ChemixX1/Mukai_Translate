"""Safety and colour-continuity helpers for inpainting results.

The neural inpainters remain responsible for reconstructing complex artwork.
This module only performs two deterministic post-processing tasks:

* restore every pixel outside the authorised mask; and
* replace neural output with a fitted colour surface when the surrounding
  pixels clearly describe a smooth fill or gradient.

Keeping these rules outside the model implementations lets LaMa and AOT stay
unchanged while making manual cleanup safer and more predictable.
"""

from __future__ import annotations

import mahotas as mh
import numpy as np
import cv2


def _dilate_binary(mask: np.ndarray, radius: int) -> np.ndarray:
    """Return a square-radius dilation without changing the input array."""
    source = np.asarray(mask, dtype=bool)
    if radius <= 0 or not np.any(source):
        return source.copy()
    diameter = (radius * 2) + 1
    structure = np.ones((diameter, diameter), dtype=bool)
    return np.asarray(mh.dilate(source, structure), dtype=bool)


def _surface_features(y: np.ndarray, x: np.ndarray, height: int, width: int) -> np.ndarray:
    """Build a stable fourth-order basis for soft manga balloon gradients."""
    x_scale = max(1.0, (width - 1) / 2.0)
    y_scale = max(1.0, (height - 1) / 2.0)
    xn = (x.astype(np.float64) - ((width - 1) / 2.0)) / x_scale
    yn = (y.astype(np.float64) - ((height - 1) / 2.0)) / y_scale
    return np.column_stack(
        (
            np.ones_like(xn),
            xn,
            yn,
            xn * yn,
            xn * xn,
            yn * yn,
            xn * xn * xn,
            xn * xn * yn,
            xn * yn * yn,
            yn * yn * yn,
            xn**4,
            (xn**3) * yn,
            (xn * xn) * (yn * yn),
            xn * (yn**3),
            yn**4,
        )
    )


def _clean_background_region(
    image: np.ndarray,
    target_mask: np.ndarray,
    unavailable_mask: np.ndarray,
) -> np.ndarray | None:
    """Find the smooth connected background surrounding the painted text."""
    rgb = np.ascontiguousarray(image[..., :3], dtype=np.uint8)
    smooth = cv2.GaussianBlur(
        rgb,
        (0, 0),
        1.2,
        borderType=cv2.BORDER_REFLECT,
    ).astype(np.float32)
    detail = np.sqrt(
        np.mean((rgb.astype(np.float32) - smooth) ** 2, axis=2)
    )
    luminance = (
        (0.299 * smooth[..., 0])
        + (0.587 * smooth[..., 1])
        + (0.114 * smooth[..., 2])
    )
    grad_x = cv2.Sobel(luminance, cv2.CV_32F, 1, 0, ksize=3) / 8.0
    grad_y = cv2.Sobel(luminance, cv2.CV_32F, 0, 1, ksize=3) / 8.0
    gradient = np.sqrt((grad_x * grad_x) + (grad_y * grad_y))

    known = ~unavailable_mask
    if int(np.count_nonzero(known)) < 64:
        return None
    detail_limit = float(
        np.clip(np.quantile(detail[known], 0.58) * 1.8 + 1.0, 4.0, 9.0)
    )
    gradient_limit = float(
        np.clip(np.quantile(gradient[known], 0.58) * 2.0 + 1.0, 3.0, 12.0)
    )
    clean = (
        known
        & (detail <= detail_limit)
        & (gradient <= gradient_limit)
    )

    labels, count = mh.label(clean, np.ones((3, 3), dtype=bool))
    if count < 1:
        return None

    target_area = max(1, int(np.count_nonzero(target_mask)))
    radius = max(10, min(26, int(round(target_area**0.5 * 0.28))))
    contact_ring = _dilate_binary(target_mask, radius) & known
    ring_area = max(1, int(np.count_nonzero(contact_ring)))

    best_label = 0
    best_overlap = 0
    best_area = 0
    for label_id in range(1, count + 1):
        region = labels == label_id
        overlap = int(np.count_nonzero(region & contact_ring))
        if overlap < best_overlap:
            continue
        area = int(np.count_nonzero(region))
        if overlap > best_overlap or area > best_area:
            best_label = label_id
            best_overlap = overlap
            best_area = area

    if (
        best_label == 0
        or best_overlap < 16
        or (best_overlap / ring_area) < 0.12
        or best_area < max(96, int(target_area * 0.65))
    ):
        return None
    return labels == best_label


def _sample_real_background_texture(
    image: np.ndarray,
    background_mask: np.ndarray,
    target_y: np.ndarray,
    target_x: np.ndarray,
    seed: int,
) -> np.ndarray:
    """Transfer coherent high-frequency patches from neighbouring pixels.

    Sampling an unrelated residual for every destination pixel reproduced the
    right colours but destroyed the spatial pattern of screentone/JPEG grain.
    Here each small destination tile selects one real source tile.  The source
    is required to be clean background and its boundary residual is matched to
    the known boundary around the hole, so lines and grain continue in the
    same direction instead of looking like sprayed noise.
    """
    rgb = np.ascontiguousarray(image[..., :3], dtype=np.uint8)
    low_frequency = cv2.GaussianBlur(
        rgb,
        (0, 0),
        0.9,
        borderType=cv2.BORDER_REFLECT,
    ).astype(np.float32)
    detail = rgb.astype(np.float32) - low_frequency
    samples = detail[background_mask]
    if len(samples) < 32:
        return np.zeros((len(target_x), 3), dtype=np.float32)

    magnitude = np.sqrt(np.mean(samples * samples, axis=1))
    cutoff = max(1.0, float(np.quantile(magnitude, 0.95)))
    samples = samples[magnitude <= cutoff]
    if len(samples) < 24 or float(np.mean(np.std(samples, axis=0))) < 0.35:
        return np.zeros((len(target_x), 3), dtype=np.float32)

    height, width = background_mask.shape
    target_mask = np.zeros((height, width), dtype=np.uint8)
    target_mask[target_y, target_x] = 1
    detail_magnitude = np.sqrt(np.mean(detail * detail, axis=2))
    source_mask = background_mask & (detail_magnitude <= cutoff)

    min_y, max_y = int(target_y.min()), int(target_y.max()) + 1
    min_x, max_x = int(target_x.min()), int(target_x.max()) + 1
    target_height = max_y - min_y
    target_width = max_x - min_x
    tile_size = int(np.clip(min(target_height, target_width) * 0.24, 24, 44))
    step = max(12, tile_size // 2)

    def tile_starts(start: int, stop: int, limit: int) -> list[int]:
        if stop - start <= tile_size:
            return [max(0, min(start, limit - tile_size))]
        values = list(range(start, max(start + 1, stop - tile_size + 1), step))
        final = stop - tile_size
        if not values or values[-1] != final:
            values.append(final)
        return [max(0, min(value, limit - tile_size)) for value in values]

    y_starts = tile_starts(min_y, max_y, height)
    x_starts = tile_starts(min_x, max_x, width)
    texture_field = np.zeros((height, width, 3), dtype=np.float32)
    ownership = np.full((height, width), -1.0, dtype=np.float32)
    source_float = source_mask.astype(np.float32)
    diagonal = max(1.0, float(np.hypot(height, width)))

    for tile_y in y_starts:
        for tile_x in x_starts:
            tile_y2 = min(height, tile_y + tile_size)
            tile_x2 = min(width, tile_x + tile_size)
            tile_target = target_mask[tile_y:tile_y2, tile_x:tile_x2]
            target_count = int(np.count_nonzero(tile_target))
            if target_count < 1:
                continue

            tile_h, tile_w = tile_target.shape
            coverage = cv2.matchTemplate(
                source_float,
                tile_target.astype(np.float32),
                cv2.TM_CCORR,
            ) / float(target_count)
            flat_coverage = coverage.ravel()
            candidate_count = min(48, len(flat_coverage))
            if candidate_count < 1:
                continue
            candidate_indices = np.argpartition(
                flat_coverage,
                -candidate_count,
            )[-candidate_count:]

            # Compare the known residual immediately around the destination
            # hole. This favours the phase/direction already visible there.
            ring = cv2.dilate(
                tile_target,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)),
                iterations=1,
            ).astype(bool) & ~tile_target.astype(bool)
            destination_detail = detail[tile_y:tile_y2, tile_x:tile_x2]
            destination_known = background_mask[
                tile_y:tile_y2,
                tile_x:tile_x2,
            ]

            best_score = -np.inf
            best_source = None
            for flat_index in candidate_indices:
                source_y, source_x = np.unravel_index(
                    int(flat_index),
                    coverage.shape,
                )
                candidate_coverage = float(coverage[source_y, source_x])
                if candidate_coverage < 0.55:
                    continue
                source_known = background_mask[
                    source_y:source_y + tile_h,
                    source_x:source_x + tile_w,
                ]
                comparable = ring & destination_known & source_known
                if int(np.count_nonzero(comparable)) >= 8:
                    source_detail = detail[
                        source_y:source_y + tile_h,
                        source_x:source_x + tile_w,
                    ]
                    boundary_error = float(
                        np.mean(
                            np.abs(
                                destination_detail[comparable]
                                - source_detail[comparable]
                            )
                        )
                    )
                else:
                    boundary_error = 4.0
                distance_penalty = np.hypot(
                    source_y - tile_y,
                    source_x - tile_x,
                ) / diagonal
                tie_break = (
                    ((source_x * 73856093) ^ (source_y * 19349663) ^ seed)
                    & 0xFFFF
                ) / 0xFFFF
                score = (
                    (candidate_coverage * 100.0)
                    - (boundary_error * 1.8)
                    - (distance_penalty * 3.0)
                    + (tie_break * 1e-4)
                )
                if score > best_score:
                    best_score = score
                    best_source = (source_y, source_x, candidate_coverage)

            if best_source is None:
                continue
            source_y, source_x, candidate_coverage = best_source
            source_detail = detail[
                source_y:source_y + tile_h,
                source_x:source_x + tile_w,
            ]
            mapped_valid = tile_target.astype(bool) & source_mask[
                source_y:source_y + tile_h,
                source_x:source_x + tile_w,
            ]

            local_y, local_x = np.mgrid[:tile_h, :tile_w]
            center_y = (tile_h - 1) / 2.0
            center_x = (tile_w - 1) / 2.0
            center_weight = 1.0 - np.maximum(
                np.abs(local_y - center_y) / max(1.0, tile_h / 2.0),
                np.abs(local_x - center_x) / max(1.0, tile_w / 2.0),
            )
            center_weight = np.maximum(0.02, center_weight)
            local_ownership = center_weight * float(candidate_coverage)
            destination_ownership = ownership[
                tile_y:tile_y2,
                tile_x:tile_x2,
            ]
            replace = mapped_valid & (local_ownership > destination_ownership)
            if not np.any(replace):
                continue
            destination_texture = texture_field[
                tile_y:tile_y2,
                tile_x:tile_x2,
            ]
            destination_texture[replace] = source_detail[replace]
            destination_ownership[replace] = local_ownership[replace]

    transferred = texture_field[target_y, target_x]
    missing = ownership[target_y, target_x] < 0.0
    if np.any(missing):
        # A nearest real residual is a safe fallback for tiny edge slivers. It
        # is deliberately not used for the main area, where it would stretch
        # one pixel into the visible faded/smeared pattern.
        distance_source = (~source_mask).astype(np.uint8)
        _distance, labels = cv2.distanceTransformWithLabels(
            distance_source,
            cv2.DIST_L2,
            5,
            labelType=cv2.DIST_LABEL_PIXEL,
        )
        source_y, source_x = np.nonzero(source_mask)
        if len(source_x):
            lookup = np.zeros((int(labels.max()) + 1, 3), dtype=np.float32)
            lookup[labels[source_y, source_x]] = detail[source_y, source_x]
            transferred[missing] = lookup[labels[target_y[missing], target_x[missing]]]

    # The reconstruction model suppresses a little of the page grain.  A mild
    # reinforcement restores it without exaggerating JPEG blocks.
    return transferred * 1.20


def _smooth_surface_domain(
    image: np.ndarray,
    background_mask: np.ndarray,
    target_mask: np.ndarray,
) -> np.ndarray:
    """Return the smooth region bounded by the real balloon edge.

    Most lettering forms a closed hole in the clean background component. If
    a brush or dilated glyph crosses the outline, that hole is open to the
    outside; in that case it is extended only through pixels whose blurred
    colour and local detail still agree with the detected interior.
    """
    background = np.asarray(background_mask, dtype=np.uint8)
    closed = cv2.morphologyEx(
        background,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
        iterations=2,
    )

    # Flood only the outside of the selected smooth component. Remaining
    # holes are the letters/marks enclosed by that component and belong to the
    # same balloon surface.
    inverse = (closed == 0).astype(np.uint8)
    padded = np.pad(inverse, 1, mode="constant", constant_values=1)
    flood_mask = np.zeros(
        (padded.shape[0] + 2, padded.shape[1] + 2),
        dtype=np.uint8,
    )
    cv2.floodFill(padded, flood_mask, (0, 0), 2)
    holes = padded[1:-1, 1:-1] == 1
    domain = (closed > 0) | holes

    target = np.asarray(target_mask, dtype=bool)
    if not np.any(target):
        return cv2.erode(
            domain.astype(np.uint8),
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
            iterations=2,
        ).astype(bool)

    rgb = np.ascontiguousarray(image[..., :3], dtype=np.uint8)
    low_frequency = cv2.GaussianBlur(
        rgb,
        (0, 0),
        5.0,
        borderType=cv2.BORDER_REFLECT,
    ).astype(np.float32)
    fine_smooth = cv2.GaussianBlur(
        rgb,
        (0, 0),
        1.2,
        borderType=cv2.BORDER_REFLECT,
    ).astype(np.float32)
    detail = np.sqrt(
        np.mean((rgb.astype(np.float32) - fine_smooth) ** 2, axis=2)
    )

    distance_source = (~np.asarray(background_mask, dtype=bool)).astype(np.uint8)
    _distance, labels = cv2.distanceTransformWithLabels(
        distance_source,
        cv2.DIST_L2,
        5,
        labelType=cv2.DIST_LABEL_PIXEL,
    )
    background_y, background_x = np.nonzero(background_mask)
    max_label = int(labels.max())
    if len(background_x) and max_label > 0:
        lookup = np.zeros((max_label + 1, 3), dtype=np.float32)
        lookup[labels[background_y, background_x]] = low_frequency[
            background_y,
            background_x,
        ]
        nearest_colour = lookup[labels]
        colour_difference = np.mean(
            np.abs(low_frequency - nearest_colour),
            axis=2,
        )
        open_interior = (
            target
            & (colour_difference <= 22.0)
            & (detail <= 12.0)
        )
        domain |= open_interior

    # This protection must be the final operation. Previously the open-region
    # extension ran after erosion and could re-authorise small square bites in
    # the black outline. Two pixels of the detected inner rim now remain
    # completely immutable.
    return cv2.erode(
        domain.astype(np.uint8),
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
        iterations=2,
    ).astype(bool)


def _interpolate_local_colour_correction(
    image: np.ndarray,
    background_mask: np.ndarray,
    target_y: np.ndarray,
    target_x: np.ndarray,
    coefficients: np.ndarray,
    *,
    whole_surface: bool = False,
) -> np.ndarray:
    """Continue the exact local colour residual into the reconstructed area.

    The polynomial describes the overall balloon gradient.  This correction
    carries the slower, irregular illumination changes that a finite surface
    fit cannot represent and that otherwise appear as a faded rectangular
    patch.
    """
    background_y, background_x = np.nonzero(background_mask)
    if len(background_x) < 32:
        return np.zeros((len(target_x), 3), dtype=np.float64)

    height, width = background_mask.shape
    background_features = _surface_features(
        background_y,
        background_x,
        height,
        width,
    )
    fitted_background = background_features @ coefficients
    low_frequency = cv2.GaussianBlur(
        np.ascontiguousarray(image[..., :3], dtype=np.uint8),
        (0, 0),
        3.0,
        borderType=cv2.BORDER_REFLECT,
    ).astype(np.float64)
    residual = low_frequency[background_y, background_x] - fitted_background

    # Prevent one surviving outline pixel from tinting a whole Voronoi region.
    lower = np.quantile(residual, 0.02, axis=0)
    upper = np.quantile(residual, 0.98, axis=0)
    residual = np.clip(residual, lower, upper)

    distance_source = (~background_mask).astype(np.uint8)
    _distance, labels = cv2.distanceTransformWithLabels(
        distance_source,
        cv2.DIST_L2,
        5,
        labelType=cv2.DIST_LABEL_PIXEL,
    )
    max_label = int(labels.max())
    if max_label < 1:
        return np.zeros((len(target_x), 3), dtype=np.float64)

    lookup = np.zeros((max_label + 1, 3), dtype=np.float64)
    lookup[labels[background_y, background_x]] = residual
    correction_field = lookup[labels]

    if whole_surface:
        # The nearest-sample field contains the silhouette of every unavailable
        # glyph hole. Re-anchoring those samples after each blur makes that
        # silhouette faintly visible in a reconstructed full balloon. A broad
        # interpolation retains only genuine large-scale lighting variation.
        sigma = float(np.clip(min(height, width) * 0.06, 6.0, 18.0))
        for _iteration in range(2):
            correction_field = cv2.GaussianBlur(
                correction_field,
                (0, 0),
                sigma,
                borderType=cv2.BORDER_REFLECT,
            )
        return correction_field[target_y, target_x]

    # Smooth the nearest-pixel field into a coherent low-frequency correction,
    # restoring known samples after each pass so the boundary stays anchored.
    for _iteration in range(4):
        correction_field = cv2.GaussianBlur(
            correction_field,
            (0, 0),
            2.4,
            borderType=cv2.BORDER_REFLECT,
        )
        correction_field[background_y, background_x] = residual

    return correction_field[target_y, target_x]


def _blend_inside_mask_edge(
    original: np.ndarray,
    reconstructed: np.ndarray,
    mask: np.ndarray,
    width: float,
) -> np.ndarray:
    """Blend only the clean inner margin; never touch pixels outside the mask."""
    if width <= 0:
        return reconstructed
    binary = np.asarray(mask, dtype=np.uint8)
    distance = cv2.distanceTransform(binary, cv2.DIST_L2, 3)
    alpha = np.clip(distance / max(0.5, float(width)), 0.0, 1.0)[..., None]
    mixed = (
        original[..., :3].astype(np.float32) * (1.0 - alpha)
        + reconstructed[..., :3].astype(np.float32) * alpha
    )
    output = reconstructed.copy()
    selected = binary > 0
    output[selected, :3] = np.clip(
        np.rint(mixed[selected]),
        0,
        255,
    ).astype(np.uint8)
    return output


def _fit_smooth_colour_surface(
    image: np.ndarray,
    target_mask: np.ndarray,
    unavailable_mask: np.ndarray,
    background_mask: np.ndarray | None = None,
    *,
    whole_surface: bool = False,
) -> np.ndarray | None:
    """Reconstruct a flat/gradient component, or return ``None`` for texture.

    A connected-background segmentation plus robust fourth-order RGB surface
    handles uniform, linear, radial and asymmetric gradients. Fine residuals
    are sampled from real neighbouring pixels so the result retains the page's
    grain instead of looking airbrushed.
    """
    if not np.any(target_mask):
        return None

    height, width = target_mask.shape
    background = background_mask
    if background is None:
        background = _clean_background_region(
            image,
            target_mask,
            unavailable_mask,
        )
    if background is None:
        return None
    known_y, known_x = np.nonzero(background)

    # Bound the least-squares workload for very large painted areas while
    # keeping sampling deterministic for reproducible edits.
    if len(known_x) > 12000:
        sample = np.linspace(0, len(known_x) - 1, 12000, dtype=np.int64)
        known_y = known_y[sample]
        known_x = known_x[sample]

    features = _surface_features(known_y, known_x, height, width)
    colours = image[known_y, known_x, :3].astype(np.float64)
    try:
        coefficients, *_ = np.linalg.lstsq(features, colours, rcond=None)
    except np.linalg.LinAlgError:
        return None

    inliers = np.ones(len(known_x), dtype=bool)
    for _iteration in range(3):
        prediction = features @ coefficients
        residual = np.sqrt(np.mean((prediction - colours) ** 2, axis=1))
        cutoff = max(3.0, float(np.quantile(residual, 0.85)))
        inliers = residual <= cutoff
        if int(np.count_nonzero(inliers)) < 48:
            return None
        try:
            coefficients, *_ = np.linalg.lstsq(
                features[inliers], colours[inliers], rcond=None
            )
        except np.linalg.LinAlgError:
            return None

    prediction = features @ coefficients
    residual = np.sqrt(np.mean((prediction - colours) ** 2, axis=1))
    median_error = float(np.median(residual))
    upper_error = float(np.quantile(residual, 0.75))
    if median_error > 8.0 or upper_error > 16.0:
        return None

    target_y, target_x = np.nonzero(target_mask)
    target_features = _surface_features(target_y, target_x, height, width)
    reconstructed = target_features @ coefficients
    reconstructed += _interpolate_local_colour_correction(
        image,
        background,
        target_y,
        target_x,
        coefficients,
        whole_surface=whole_surface,
    )
    reconstructed += _sample_real_background_texture(
        image,
        background,
        target_y,
        target_x,
        seed=(int(np.count_nonzero(target_mask)) * 2654435761) & 0xFFFFFFFF,
    )
    return np.clip(np.rint(reconstructed), 0, 255).astype(np.uint8)


def postprocess_inpainted_result(
    original: np.ndarray,
    authorised_mask: np.ndarray,
    inpainted: np.ndarray,
    *,
    edge_blend_px: float = 0.0,
    rebuild_entire_smooth_surface: bool = False,
    effective_mask_out: np.ndarray | None = None,
) -> np.ndarray:
    """Return a safe, gradient-aware result.

    ``rebuild_entire_smooth_surface`` is reserved for automatic manga
    cleaning. It normalises the whole detected balloon interior after the
    configured neural engine removes the text. Manual brushes keep their exact
    user-authorised footprint.
    """
    if original is None or inpainted is None:
        return inpainted
    if original.ndim != 3 or inpainted.ndim != 3:
        return inpainted
    if original.shape[:2] != inpainted.shape[:2]:
        return inpainted
    if authorised_mask is None or authorised_mask.shape != original.shape[:2]:
        return inpainted

    mask = np.asarray(authorised_mask) > 0
    if not np.any(mask):
        if effective_mask_out is not None and effective_mask_out.shape == mask.shape:
            effective_mask_out[...] = 0
        return original.copy()

    effective_mask = mask.copy()

    # This assignment is the hard safety boundary.  Even if an optional mask
    # refiner or a model returns changes elsewhere, they cannot reach the UI.
    result = np.asarray(original).copy()
    result[mask, :3] = np.asarray(inpainted)[mask, :3]

    # Nearby glyph fragments belong to one word/balloon and must share a
    # single colour field. Fitting each character independently produced the
    # visible vertical "droplets" seen in gradient balloons.
    grouped_mask = _dilate_binary(mask, radius=12)
    labels, component_count = mh.label(
        grouped_mask,
        np.ones((3, 3), dtype=bool),
    )
    boxes = mh.labeled.bbox(labels)
    image_height, image_width = mask.shape

    for label_id in range(1, component_count + 1):
        y1, y2, x1, x2 = [int(value) for value in boxes[label_id]]
        if y2 <= y1 or x2 <= x1:
            continue

        component_height = y2 - y1
        component_width = x2 - x1
        base_extent = max(component_height, component_width)
        if rebuild_entire_smooth_surface:
            context = max(32, min(160, int(base_extent * 0.80)))
            maximum_context = min(
                384,
                max(context, int(base_extent * 1.05)),
            )
        else:
            context = max(16, min(48, int(base_extent * 0.55)))
            maximum_context = context

        background = None
        # A balloon may be much larger than its text. Grow the context while
        # the selected smooth component still reaches the crop boundary, then
        # reconstruct the complete connected interior rather than a rectangle
        # around the glyphs.
        for _context_attempt in range(4):
            crop_y1 = max(0, y1 - context)
            crop_y2 = min(image_height, y2 + context)
            crop_x1 = max(0, x1 - context)
            crop_x2 = min(image_width, x2 + context)

            crop_labels = labels[crop_y1:crop_y2, crop_x1:crop_x2]
            unavailable = mask[crop_y1:crop_y2, crop_x1:crop_x2]
            component = unavailable & (crop_labels == label_id)
            crop_image = original[crop_y1:crop_y2, crop_x1:crop_x2, :3]
            background = _clean_background_region(
                crop_image,
                component,
                unavailable,
            )
            if background is None or not rebuild_entire_smooth_surface:
                break

            known_area = max(1, int(np.count_nonzero(~unavailable)))
            background_density = int(np.count_nonzero(background)) / known_area
            if background_density < 0.20:
                # Sparse clean islands inside artwork are not a balloon
                # surface. Do not grow the crop through a full webtoon page.
                break

            border_contact = (
                int(np.count_nonzero(background[:2, :]))
                + int(np.count_nonzero(background[-2:, :]))
                + int(np.count_nonzero(background[:, :2]))
                + int(np.count_nonzero(background[:, -2:]))
            )
            can_expand = (
                crop_y1 > 0
                or crop_y2 < image_height
                or crop_x1 > 0
                or crop_x2 < image_width
            )
            if (
                border_contact < 12
                or not can_expand
                or context >= maximum_context
            ):
                break
            context = min(
                maximum_context,
                max(context + 32, int(context * 1.75)),
            )

        if background is None:
            continue

        surface_domain = _smooth_surface_domain(
            crop_image,
            background,
            component,
        )
        # A complete balloon interior is a closed component.  If the inferred
        # surface reaches the crop border, the sampler has locked on to an
        # open page background instead (typically the white area surrounding
        # a narrow rectangular gradient panel). Expanding that open component
        # turned the panel into a large blurred halo. Keep the configured
        # neural engine's native, mask-limited reconstruction in this case.
        domain_border_contact = (
            int(np.count_nonzero(surface_domain[:2, :]))
            + int(np.count_nonzero(surface_domain[-2:, :]))
            + int(np.count_nonzero(surface_domain[:, :2]))
            + int(np.count_nonzero(surface_domain[:, -2:]))
        )
        if rebuild_entire_smooth_surface and domain_border_contact:
            continue

        safe_component = component & surface_domain
        safe_count = int(np.count_nonzero(safe_component))
        target_count = max(1, int(np.count_nonzero(component)))
        safe_ratio = safe_count / target_count
        rejected = component & ~surface_domain
        # A true flat/gradient balloon encloses virtually the complete text
        # mask. Semi-transparent bubbles over artwork produce disconnected
        # smooth islands and a low enclosure ratio; treating those islands as
        # a surface would restore the original Japanese text after AOT/LaMa
        # had already erased it.
        surface_reliable = target_count >= 128 and safe_ratio >= 0.90
        if safe_count < 32 or not surface_reliable:
            continue

        domain_count = max(1, int(np.count_nonzero(surface_domain)))
        background_coverage = int(np.count_nonzero(background)) / domain_count
        can_rebuild_whole_surface = (
            rebuild_entire_smooth_surface
            and background_coverage >= 0.38
        )
        reconstruction_target = (
            surface_domain if can_rebuild_whole_surface else safe_component
        )

        reconstructed = _fit_smooth_colour_surface(
            crop_image,
            reconstruction_target,
            unavailable,
            background_mask=background,
            whole_surface=can_rebuild_whole_surface,
        )
        if reconstructed is None:
            # This is a textured or translucent background rather than a
            # validated smooth balloon. Keep the native-resolution neural
            # result; restoring the original here would also restore the text.
            continue

        crop_result = result[crop_y1:crop_y2, crop_x1:crop_x2, :3]
        if np.any(rejected):
            crop_result[rejected] = crop_image[rejected]
            crop_effective = effective_mask[crop_y1:crop_y2, crop_x1:crop_x2]
            crop_effective[rejected] = False
        crop_result[reconstruction_target] = reconstructed
        if can_rebuild_whole_surface:
            crop_effective = effective_mask[crop_y1:crop_y2, crop_x1:crop_x2]
            crop_effective |= reconstruction_target

    result = _blend_inside_mask_edge(
        np.asarray(original),
        result,
        effective_mask,
        edge_blend_px,
    )
    if effective_mask_out is not None and effective_mask_out.shape == mask.shape:
        if effective_mask_out.dtype == np.bool_:
            effective_mask_out[...] = effective_mask
        else:
            effective_mask_out[...] = np.where(effective_mask, 255, 0).astype(
                effective_mask_out.dtype,
                copy=False,
            )
    return np.ascontiguousarray(result.astype(np.uint8, copy=False))


def make_masked_patch(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Create an RGBA patch whose alpha channel is the exact edit mask."""
    rgb = np.ascontiguousarray(image[..., :3], dtype=np.uint8)
    alpha = np.where(np.asarray(mask) > 0, 255, 0).astype(np.uint8)
    return np.ascontiguousarray(np.dstack((rgb, alpha)))

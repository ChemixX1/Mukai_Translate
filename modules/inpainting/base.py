import abc
from dataclasses import replace
from typing import Optional

import numpy as np
import imkit as imk
from PIL import Image
import logging
from contextlib import nullcontext

logger = logging.getLogger(__name__)

from ..utils.inpainting import (
    boxes_from_mask,
    resize_max_size,
    pad_img_to_modulo,
    # switch_mps_device,
)
from .schema import Config, HDStrategy


class InpaintModel:
    name = "base"
    min_size: Optional[int] = None
    pad_mod = 8
    pad_to_square = False

    def __init__(self, device, **kwargs):
        """

        Args:
            device:
        """
        # device = switch_mps_device(self.name, device)
        self.device = device
        self.init_model(device, **kwargs)

    @abc.abstractmethod
    def init_model(self, device, **kwargs):
        ...

    @staticmethod
    @abc.abstractmethod
    def is_downloaded() -> bool:
        ...

    @abc.abstractmethod
    def forward(self, image, mask, config: Config):
        """Input images and output images have same size
        images: [H, W, C] RGB
        masks: [H, W, 1] 255 为 masks 区域
        return: BGR IMAGE
        """
        ...

    def _pad_forward(self, image, mask, config: Config):
        output_dtype = image.dtype
        origin_height, origin_width = image.shape[:2]
        pad_image = pad_img_to_modulo(
            image, mod=self.pad_mod, square=self.pad_to_square, min_size=self.min_size
        )
        pad_mask = pad_img_to_modulo(
            mask, mod=self.pad_mod, square=self.pad_to_square, min_size=self.min_size
        )

        logger.info(f"final forward pad size: {pad_image.shape}")

        result = self.forward(pad_image, pad_mask, config)
        result = result[0:origin_height, 0:origin_width, :]

        result, image, mask = self.forward_post_process(result, image, mask, config)

        mask = mask[:, :, np.newaxis]
        result = result * (mask / 255) + image * (1 - (mask / 255))
        if np.issubdtype(output_dtype, np.integer):
            limits = np.iinfo(output_dtype)
            result = np.clip(np.rint(result), limits.min, limits.max)
        return result.astype(output_dtype, copy=False)

    def forward_post_process(self, result, image, mask, config):
        return result, image, mask

    @staticmethod
    def _merge_nearby_mask_boxes(
        boxes,
        image_shape: tuple[int, int],
        gap: int,
    ) -> list[np.ndarray]:
        """Merge glyph fragments that belong to one local inpaint region.

        Pixel-accurate manga masks contain one contour per letter, outline
        fragment or punctuation mark. Running a large neural crop for every
        contour is both slow and can exhaust ONNX memory on long webtoons.
        """
        height, width = image_shape[:2]
        merged = [np.asarray(box, dtype=np.int32).copy() for box in boxes]
        gap = max(0, int(gap))
        changed = True
        while changed:
            changed = False
            output = []
            while merged:
                current = merged.pop()
                index = 0
                while index < len(merged):
                    candidate = merged[index]
                    overlaps = not (
                        current[2] + gap < candidate[0]
                        or candidate[2] + gap < current[0]
                        or current[3] + gap < candidate[1]
                        or candidate[3] + gap < current[1]
                    )
                    if not overlaps:
                        index += 1
                        continue
                    current = np.array(
                        [
                            min(current[0], candidate[0]),
                            min(current[1], candidate[1]),
                            max(current[2], candidate[2]),
                            max(current[3], candidate[3]),
                        ],
                        dtype=np.int32,
                    )
                    merged.pop(index)
                    changed = True
                    index = 0
                current[::2] = np.clip(current[::2], 0, width)
                current[1::2] = np.clip(current[1::2], 0, height)
                output.append(current)
            merged = output
        return sorted(merged, key=lambda box: (int(box[1]), int(box[0])))

    def _run_crop_strategy(
        self,
        image: np.ndarray,
        mask: np.ndarray,
        config: Config,
        *,
        crop_margin: int,
    ) -> np.ndarray:
        boxes = boxes_from_mask(mask)
        if not boxes:
            return image.copy()
        merge_gap = max(32, min(192, int(crop_margin * 0.55)))
        boxes = self._merge_nearby_mask_boxes(
            boxes,
            image.shape[:2],
            merge_gap,
        )
        local_config = replace(
            config,
            hd_strategy=HDStrategy.ORIGINAL,
            hd_strategy_crop_margin=int(crop_margin),
        )
        logger.info(
            "Run native crop strategy: %d merged regions, margin=%d",
            len(boxes),
            crop_margin,
        )
        inpaint_result = image.copy()
        for box in boxes:
            crop_image, crop_box = self._run_box(
                image,
                mask,
                box,
                local_config,
            )
            x1, y1, x2, y2 = crop_box
            inpaint_result[y1:y2, x1:x2, :] = crop_image
        return inpaint_result

    def _adaptive_crop_margin(self, mask: np.ndarray) -> int:
        boxes = boxes_from_mask(mask)
        if not boxes:
            return 128
        grouped = self._merge_nearby_mask_boxes(boxes, mask.shape[:2], 96)
        spans = [
            max(int(box[2] - box[0]), int(box[3] - box[1]))
            for box in grouped
        ]
        typical_span = float(np.median(spans)) if spans else 256.0
        return int(np.clip(round(typical_span * 0.38), 112, 256))

    def __call__(self, image, mask, config: Config):
        """
        images: [H, W, C] RGB, not normalized
        masks: [H, W]
        return: BGR IMAGE
        """
        # Only import torch if we're using a torch backend; otherwise avoid dependency
        backend = getattr(self, 'backend', 'torch')
        if backend == 'onnx':
            no_grad_ctx = nullcontext()
        else:
            try:
                import torch  # noqa
                no_grad_ctx = torch.no_grad()
            except ImportError as e:
                raise RuntimeError("Torch backend selected but torch is not installed. Install torch or use backend='onnx'.") from e
        with no_grad_ctx:
            inpaint_result = None
            logger.info(f"hd_strategy: {config.hd_strategy}")
            if config.hd_strategy == HDStrategy.CROP:
                if max(image.shape) > config.hd_strategy_crop_trigger_size:
                    inpaint_result = self._run_crop_strategy(
                        image,
                        mask,
                        config,
                        crop_margin=config.hd_strategy_crop_margin,
                    )

            elif config.hd_strategy == HDStrategy.RESIZE:
                if max(image.shape) > config.hd_strategy_resize_limit:
                    resize_ratio = (
                        float(config.hd_strategy_resize_limit)
                        / float(max(image.shape[:2]))
                    )
                    mask_coverage = float(np.count_nonzero(mask)) / max(
                        1.0,
                        float(mask.shape[0] * mask.shape[1]),
                    )
                    if resize_ratio < 0.45 and mask_coverage < 0.30:
                        # Long webtoons would otherwise shrink from e.g.
                        # 800x5000 to 154x960, making translucent lettering too
                        # small for AOT/LaMa to erase. Process a few native
                        # merged crops while keeping the user's selected model.
                        inpaint_result = self._run_crop_strategy(
                            image,
                            mask,
                            config,
                            crop_margin=self._adaptive_crop_margin(mask),
                        )

                if inpaint_result is None and max(image.shape) > config.hd_strategy_resize_limit:
                    origin_size = image.shape[:2]
                    downsize_image = resize_max_size(
                        image, size_limit=config.hd_strategy_resize_limit
                    )
                    downsize_mask = resize_max_size(
                        mask, size_limit=config.hd_strategy_resize_limit
                    )

                    logger.info(
                        f"Run resize strategy, origin size: {image.shape} forward size: {downsize_image.shape}"
                    )
                    inpaint_result = self._pad_forward(
                        downsize_image, downsize_mask, config
                    )

                    # only paste masked area result
                    inpaint_result = imk.resize(
                        inpaint_result,
                        (origin_size[1], origin_size[0]),
                        mode=Image.Resampling.BICUBIC,
                    )
                    original_pixel_indices = mask < 127
                    inpaint_result[original_pixel_indices] = image[
                        original_pixel_indices
                    ]

            if inpaint_result is None:
                inpaint_result = self._pad_forward(image, mask, config)

            return inpaint_result

    def _crop_box(self, image, mask, box, config: Config):
        """

        Args:
            image: [H, W, C] RGB
            mask: [H, W, 1]
            box: [left,top,right,bottom]

        Returns:
            BGR IMAGE, (l, r, r, b)
        """
        box_h = box[3] - box[1]
        box_w = box[2] - box[0]
        cx = (box[0] + box[2]) // 2
        cy = (box[1] + box[3]) // 2
        img_h, img_w = image.shape[:2]

        w = box_w + config.hd_strategy_crop_margin * 2
        h = box_h + config.hd_strategy_crop_margin * 2

        _l = cx - w // 2
        _r = cx + w // 2
        _t = cy - h // 2
        _b = cy + h // 2

        l = max(_l, 0)
        r = min(_r, img_w)
        t = max(_t, 0)
        b = min(_b, img_h)

        # try to get more context when crop around image edge
        if _l < 0:
            r += abs(_l)
        if _r > img_w:
            l -= _r - img_w
        if _t < 0:
            b += abs(_t)
        if _b > img_h:
            t -= _b - img_h

        l = max(l, 0)
        r = min(r, img_w)
        t = max(t, 0)
        b = min(b, img_h)

        crop_img = image[t:b, l:r, :]
        crop_mask = mask[t:b, l:r]

        logger.info(f"box size: ({box_h},{box_w}) crop size: {crop_img.shape}")

        return crop_img, crop_mask, [l, t, r, b]

    def _calculate_cdf(self, histogram):
        cdf = histogram.cumsum()
        normalized_cdf = cdf / float(cdf.max())
        return normalized_cdf

    def _calculate_lookup(self, source_cdf, reference_cdf):
        # For each source CDF value, find the first reference CDF index >= it.
        # np.searchsorted is O(256 * log 256) and fully vectorized vs the
        # previous O(256²) pure-Python double loop.
        indices = np.searchsorted(reference_cdf, source_cdf, side='left')
        return np.clip(indices, 0, 255).astype(np.float64)

    def _match_histograms(self, source, reference, mask):
        transformed_channels = []
        for channel in range(source.shape[-1]):
            source_channel = source[:, :, channel]
            reference_channel = reference[:, :, channel]

            # only calculate histograms for non-masked parts
            source_histogram, _ = np.histogram(source_channel[mask == 0], 256, [0, 256])
            reference_histogram, _ = np.histogram(
                reference_channel[mask == 0], 256, [0, 256]
            )

            source_cdf = self._calculate_cdf(source_histogram)
            reference_cdf = self._calculate_cdf(reference_histogram)

            lookup = self._calculate_lookup(source_cdf, reference_cdf)

            transformed_channels.append(imk.lut(source_channel, lookup))

        result = imk.merge_channels(transformed_channels)
        result = imk.convert_scale_abs(result)

        return result

    def _apply_cropper(self, image, mask, config: Config):
        img_h, img_w = image.shape[:2]
        l, t, w, h = (
            config.croper_x,
            config.croper_y,
            config.croper_width,
            config.croper_height,
        )
        r = l + w
        b = t + h

        l = max(l, 0)
        r = min(r, img_w)
        t = max(t, 0)
        b = min(b, img_h)

        crop_img = image[t:b, l:r, :]
        crop_mask = mask[t:b, l:r]
        return crop_img, crop_mask, (l, t, r, b)

    def _run_box(self, image, mask, box, config: Config):
        """

        Args:
            image: [H, W, C] RGB
            mask: [H, W, 1]
            box: [left,top,right,bottom]

        Returns:
            BGR IMAGE
        """
        crop_img, crop_mask, [l, t, r, b] = self._crop_box(image, mask, box, config)

        return self._pad_forward(crop_img, crop_mask, config), [l, t, r, b]


class DiffusionInpaintModel(InpaintModel):
    def __call__(self, image, mask, config: Config):
        """
        images: [H, W, C] RGB, not normalized
        masks: [H, W]
        return: BGR IMAGE
        """
        backend = getattr(self, 'backend', 'torch')
        if backend == 'onnx':
            no_grad_ctx = nullcontext()
        else:
            try:
                import torch  # noqa
                no_grad_ctx = torch.no_grad()
            except ImportError as e:
                raise RuntimeError("Torch backend selected but torch is not installed. Install torch or use backend='onnx'.") from e
        with no_grad_ctx:
            # boxes = boxes_from_mask(mask)
            if config.use_croper:
                crop_img, crop_mask, (l, t, r, b) = self._apply_cropper(image, mask, config)
                crop_image = self._scaled_pad_forward(crop_img, crop_mask, config)
                inpaint_result = image
                inpaint_result[t:b, l:r, :] = crop_image
            else:
                inpaint_result = self._scaled_pad_forward(image, mask, config)

            return inpaint_result

    def _scaled_pad_forward(self, image, mask, config: Config):
        longer_side_length = int(config.sd_scale * max(image.shape[:2]))
        origin_size = image.shape[:2]
        downsize_image = resize_max_size(image, size_limit=longer_side_length)
        downsize_mask = resize_max_size(mask, size_limit=longer_side_length)
        if config.sd_scale != 1:
            logger.info(
                f"Resize image to do sd inpainting: {image.shape} -> {downsize_image.shape}"
            )
        inpaint_result = self._pad_forward(downsize_image, downsize_mask, config)
        # only paste masked area result
        inpaint_result = imk.resize(
            inpaint_result,
            (origin_size[1], origin_size[0]),
            mode=Image.Resampling.BICUBIC,
        )
        original_pixel_indices = mask < 127
        inpaint_result[original_pixel_indices] = image[
            original_pixel_indices
        ]
        return inpaint_result

from __future__ import annotations

import unittest

import numpy as np

from modules.inpainting.base import InpaintModel
from modules.inpainting.schema import Config


class _RecordingInpainter(InpaintModel):
    pad_mod = 8

    def init_model(self, device, **kwargs):
        self.backend = "onnx"
        self.calls: list[tuple[int, int]] = []

    @staticmethod
    def is_downloaded() -> bool:
        return True

    def forward(self, image, mask, config):
        self.calls.append(image.shape[:2])
        return np.full_like(image, 173)


class InpaintEngineStrategyTests(unittest.TestCase):
    def test_long_page_uses_merged_native_crops_instead_of_tiny_resize(self):
        image = np.full((1200, 160, 3), 225, dtype=np.uint8)
        mask = np.zeros((1200, 160), dtype=np.uint8)
        # Two glyph fragments in each of two distant speech bubbles.
        mask[150:190, 55:72] = 255
        mask[165:215, 80:98] = 255
        mask[845:890, 48:68] = 255
        mask[862:920, 76:96] = 255
        engine = _RecordingInpainter("cpu")

        result = engine(
            image,
            mask,
            Config(hd_strategy="Resize", hd_strategy_resize_limit=200),
        )

        self.assertEqual(len(engine.calls), 2)
        self.assertTrue(all(height < image.shape[0] for height, _ in engine.calls))
        self.assertTrue(np.all(result[mask > 0] == 173))
        self.assertTrue(np.array_equal(result[mask == 0], image[mask == 0]))


if __name__ == "__main__":
    unittest.main()

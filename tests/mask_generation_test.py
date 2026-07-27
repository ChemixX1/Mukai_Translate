from __future__ import annotations

import unittest

import cv2
import numpy as np

from modules.detection.utils.stylized_text import detect_coloured_outlined_text
from modules.utils.image_utils import build_block_mask_data
from modules.utils.textblock import TextBlock


class MaskGenerationTests(unittest.TestCase):
    def test_bubble_outline_is_never_part_of_the_text_mask(self):
        image = np.full((250, 210, 3), 255, dtype=np.uint8)
        outline = np.zeros(image.shape[:2], dtype=np.uint8)
        cv2.ellipse(outline, (105, 125), (72, 104), 0, 0, 360, 255, 3)
        image[outline > 0] = 15
        # Synthetic vertical black glyphs, comfortably inside the bubble.
        image[72:108, 94:103] = 15
        image[116:154, 106:115] = 15
        image[162:190, 92:102] = 15
        block = TextBlock(
            text_bbox=np.asarray([82, 62, 124, 198], dtype=np.int32),
            bubble_bbox=np.asarray([30, 18, 180, 233], dtype=np.int32),
            text_class="text_bubble",
            text="placeholder",
        )

        local_mask, bounds = build_block_mask_data(image, block)

        self.assertIsNotNone(local_mask)
        self.assertIsNotNone(bounds)
        x1, y1, x2, y2 = bounds
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        mask[y1:y2, x1:x2] = local_mask
        self.assertGreater(np.count_nonzero(mask), 100)
        self.assertFalse(np.any((mask > 0) & (outline > 0)))

    def test_coloured_white_outlined_sfx_gets_a_supplemental_block(self):
        image = np.zeros((1200, 380, 3), dtype=np.uint8)
        image[...] = (242, 166, 92)
        white = (250, 250, 250)
        cyan = (20, 155, 190)
        strokes = [
            ((105, 105), (125, 410)),
            ((125, 245), (72, 315)),
            ((178, 300), (142, 390)),
            ((190, 430), (205, 570)),
            ((205, 490), (260, 555)),
        ]
        for start, end in strokes:
            cv2.line(image, start, end, white, 20, cv2.LINE_AA)
            cv2.line(image, start, end, cyan, 10, cv2.LINE_AA)

        blocks = detect_coloured_outlined_text(image, [])

        self.assertEqual(len(blocks), 1)
        block = blocks[0]
        self.assertEqual(block.text_class, "text_free")
        self.assertIsNotNone(block.mask_hue)
        block.text = "placeholder"
        local_mask, bounds = build_block_mask_data(image, block)
        self.assertIsNotNone(local_mask)
        self.assertGreater(np.count_nonzero(local_mask), 1000)
        self.assertEqual(local_mask[0, 0], 0)

        copied = block.deep_copy()
        self.assertEqual(copied.mask_hue, block.mask_hue)
        self.assertEqual(copied.direction, "vertical")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import imkit as imk
from app.sam_refiner_runner import _choose_candidate, _expand_binary
from pipeline.inpaint_postprocess import (
    _sample_real_background_texture,
    make_masked_patch,
    postprocess_inpainted_result,
)


class InpaintSafetyTests(unittest.TestCase):
    def test_sam_never_leaves_two_pixel_safety_envelope(self):
        rough = np.zeros((40, 40), dtype=np.uint8)
        rough[18:23, 18:23] = 255
        whole_page_candidate = np.ones((1, 40, 40), dtype=bool)

        selected = _choose_candidate(
            whole_page_candidate,
            np.array([0.99], dtype=np.float32),
            rough,
        )
        allowed = _expand_binary(rough > 0, radius=2)

        self.assertFalse(np.any((selected > 0) & ~allowed))
        self.assertTrue(np.all(selected[rough > 0] == 255))

    def test_postprocess_restores_every_unauthorised_pixel(self):
        original = np.zeros((48, 64, 3), dtype=np.uint8)
        original[..., 0] = 23
        original[..., 1] = 71
        original[..., 2] = 149
        engine = np.full_like(original, 240)
        mask = np.zeros(original.shape[:2], dtype=np.uint8)
        mask[15:31, 20:44] = 255

        result = postprocess_inpainted_result(original, mask, engine)

        self.assertTrue(np.array_equal(result[mask == 0], original[mask == 0]))

    def test_smooth_colour_gradient_is_reconstructed(self):
        height, width = 100, 140
        y, x = np.mgrid[:height, :width]
        original = np.stack(
            (
                25 + (0.65 * x) + (0.15 * y),
                50 + (0.20 * x) + (0.50 * y),
                105 + (0.18 * x) + (0.08 * y),
            ),
            axis=-1,
        )
        original = np.clip(original, 0, 255).astype(np.uint8)
        mask = np.zeros((height, width), dtype=np.uint8)
        mask[34:67, 52:91] = 255
        deliberately_bad_engine_result = np.full_like(original, 225)

        result = postprocess_inpainted_result(
            original,
            mask,
            deliberately_bad_engine_result,
        )
        mean_error = np.abs(
            result[mask > 0].astype(np.int16) - original[mask > 0].astype(np.int16)
        ).mean()

        self.assertLess(mean_error, 1.0)

    def test_complex_texture_keeps_neural_engine_result(self):
        height, width = 80, 100
        checker = (np.indices((height, width)).sum(axis=0) % 2) * 255
        original = np.repeat(checker[..., None], 3, axis=2).astype(np.uint8)
        mask = np.zeros((height, width), dtype=np.uint8)
        mask[25:54, 35:66] = 255
        engine = np.full_like(original, 127)

        result = postprocess_inpainted_result(original, mask, engine)

        self.assertTrue(np.array_equal(result[mask > 0], engine[mask > 0]))

    def test_rejected_surface_fit_never_restores_translucent_text(self):
        original = np.full((90, 110, 3), 210, dtype=np.uint8)
        engine = np.full_like(original, 73)
        mask = np.zeros((90, 110), dtype=np.uint8)
        mask[28:64, 38:76] = 255
        effective = np.zeros_like(mask)

        def clean_region(_image, _target, unavailable):
            return ~np.asarray(unavailable, dtype=bool)

        def complete_domain(_image, _background, target):
            return np.ones_like(target, dtype=bool)

        with (
            patch(
                "pipeline.inpaint_postprocess._clean_background_region",
                side_effect=clean_region,
            ),
            patch(
                "pipeline.inpaint_postprocess._smooth_surface_domain",
                side_effect=complete_domain,
            ),
            patch(
                "pipeline.inpaint_postprocess._fit_smooth_colour_surface",
                return_value=None,
            ),
        ):
            result = postprocess_inpainted_result(
                original,
                mask,
                engine,
                rebuild_entire_smooth_surface=True,
                effective_mask_out=effective,
            )

        self.assertTrue(np.array_equal(result[mask > 0], engine[mask > 0]))
        self.assertTrue(np.array_equal(effective, mask))

    def test_nearby_strokes_share_one_textured_radial_gradient(self):
        height, width = 150, 170
        y, x = np.mgrid[:height, :width]
        radius = np.sqrt(((x - 82) / 95) ** 2 + ((y - 28) / 145) ** 2)
        grain = (((x * 17) + (y * 31)) % 7) - 3
        original = np.stack(
            (
                235 - (150 * radius) + grain,
                238 - (145 * radius) + grain,
                250 - (105 * radius) + grain,
            ),
            axis=-1,
        )
        original = np.clip(original, 0, 255).astype(np.uint8)
        mask = np.zeros((height, width), dtype=np.uint8)
        mask[42:119, 61:76] = 255
        mask[45:121, 84:99] = 255
        engine = np.full_like(original, 128)

        result = postprocess_inpainted_result(original, mask, engine)
        error = np.abs(
            result[mask > 0].astype(np.int16) - original[mask > 0].astype(np.int16)
        ).mean()

        self.assertLess(error, 12.0)
        self.assertTrue(np.array_equal(result[mask == 0], original[mask == 0]))

    def test_irregular_low_frequency_colour_does_not_form_a_faded_patch(self):
        height, width = 130, 180
        y, x = np.mgrid[:height, :width]
        wave = 14 * np.sin(x / 15.0) * np.cos(y / 27.0)
        original = np.stack(
            (
                70 + (0.45 * x) + (0.20 * y) + wave,
                90 + (0.20 * x) + (0.35 * y) + (0.70 * wave),
                130 + (0.10 * x) + (0.20 * y) + (0.40 * wave),
            ),
            axis=-1,
        )
        original = np.clip(original, 0, 255).astype(np.uint8)
        mask = np.zeros((height, width), dtype=np.uint8)
        mask[35:104, 65:118] = 255
        engine = np.full_like(original, 220)

        result = postprocess_inpainted_result(original, mask, engine)
        error = np.abs(
            result[mask > 0].astype(np.int16) - original[mask > 0].astype(np.int16)
        ).mean()

        self.assertLess(error, 4.0)
        self.assertTrue(np.array_equal(result[mask == 0], original[mask == 0]))

    def test_texture_transfer_preserves_a_neighbouring_spatial_pattern(self):
        height, width = 96, 128
        y, x = np.mgrid[:height, :width]
        stripes = np.where(((x // 2) % 2) == 0, -6, 6)
        base = 130 + (0.15 * x) + (0.10 * y)
        image = np.stack(
            (base + stripes, base + stripes, base + stripes),
            axis=-1,
        ).astype(np.uint8)
        target = np.zeros((height, width), dtype=bool)
        target[28:70, 42:88] = True
        background = ~target
        target_y, target_x = np.nonzero(target)

        texture = _sample_real_background_texture(
            image,
            background,
            target_y,
            target_x,
            seed=7,
        )
        field = np.zeros((height, width), dtype=np.float32)
        field[target_y, target_x] = texture.mean(axis=1)
        comparable = target[:, :-2] & target[:, 2:]
        correlation = np.corrcoef(
            field[:, :-2][comparable],
            field[:, 2:][comparable],
        )[0, 1]

        # A two-pixel shift is the opposite phase of this four-pixel pattern.
        # Per-pixel random sampling has correlation close to zero; coherent
        # patch transfer retains the strongly negative relationship.
        self.assertLess(correlation, -0.65)

    def test_smooth_inpaint_does_not_cross_an_irregular_balloon_edge(self):
        height = width = 180
        y, x = np.mgrid[:height, :width]
        checker = (((x + y) % 2) * 180) + 20
        original = np.repeat(checker[..., None], 3, axis=2).astype(np.uint8)
        balloon = np.zeros((height, width), dtype=np.uint8)
        polygon = np.array(
            [
                [60, 20], [120, 20], [128, 40], [150, 55], [135, 75],
                [153, 95], [132, 112], [125, 150], [90, 162], [55, 150],
                [48, 120], [28, 102], [44, 80], [30, 58], [55, 45],
            ],
            dtype=np.int32,
        )
        import cv2

        cv2.fillPoly(balloon, [polygon], 1)
        gradient = np.stack(
            (230 - (0.35 * y), 235 - (0.30 * y), 250 - (0.15 * y)),
            axis=-1,
        )
        original[balloon > 0] = np.clip(
            gradient[balloon > 0],
            0,
            255,
        ).astype(np.uint8)
        mask = np.zeros((height, width), dtype=np.uint8)
        # Deliberately crosses the jagged right edge of the balloon.
        # A small automatic-mask overrun crosses the jagged edge. Gross manual
        # selections remain the user's exact brush area and are not guessed.
        mask[48:132, 112:132] = 255
        engine = np.full_like(original, 100)

        result = postprocess_inpainted_result(original, mask, engine)
        outside_balloon = (mask > 0) & (balloon == 0)

        self.assertTrue(
            np.array_equal(result[outside_balloon], original[outside_balloon])
        )

    def test_automatic_cleanup_rebuilds_only_the_complete_balloon_interior(self):
        import cv2

        height = width = 180
        y, x = np.mgrid[:height, :width]
        checker = (((x + y) % 2) * 180) + 20
        original = np.repeat(checker[..., None], 3, axis=2).astype(np.uint8)
        balloon = np.zeros((height, width), dtype=np.uint8)
        polygon = np.array(
            [
                [60, 20], [120, 20], [128, 40], [150, 55], [135, 75],
                [153, 95], [132, 112], [125, 150], [90, 162], [55, 150],
                [48, 120], [28, 102], [44, 80], [30, 58], [55, 45],
            ],
            dtype=np.int32,
        )
        cv2.fillPoly(balloon, [polygon], 1)
        grain = (((x * 7) + (y * 11)) % 5) - 2
        gradient = np.stack(
            (
                230 - (0.35 * y) + grain,
                235 - (0.30 * y) + grain,
                250 - (0.15 * y) + grain,
            ),
            axis=-1,
        )
        original[balloon > 0] = np.clip(
            gradient[balloon > 0],
            0,
            255,
        ).astype(np.uint8)
        text_mask = np.zeros((height, width), dtype=np.uint8)
        text_mask[55:125, 74:108] = 255
        effective_mask = np.zeros_like(text_mask)

        result = postprocess_inpainted_result(
            original,
            text_mask,
            np.full_like(original, 100),
            edge_blend_px=2.5,
            rebuild_entire_smooth_surface=True,
            effective_mask_out=effective_mask,
        )

        self.assertGreater(
            np.count_nonzero(effective_mask),
            np.count_nonzero(text_mask) * 3,
        )
        self.assertFalse(np.any((effective_mask > 0) & (balloon == 0)))
        self.assertTrue(
            np.array_equal(result[balloon == 0], original[balloon == 0])
        )
        error = np.abs(
            result[effective_mask > 0].astype(np.int16)
            - original[effective_mask > 0].astype(np.int16)
        ).mean()
        self.assertLess(error, 5.0)

    def test_automatic_cleanup_does_not_expand_an_open_page_surface(self):
        original = np.full((180, 160, 3), 248, dtype=np.uint8)
        mask = np.zeros((180, 160), dtype=np.uint8)
        mask[58:128, 68:94] = 255
        engine = original.copy()
        effective_mask = np.zeros_like(mask)

        result = postprocess_inpainted_result(
            original,
            mask,
            engine,
            rebuild_entire_smooth_surface=True,
            effective_mask_out=effective_mask,
        )

        self.assertTrue(np.array_equal(effective_mask > 0, mask > 0))
        self.assertTrue(np.array_equal(result, original))

    def test_rgba_patch_round_trip_preserves_exact_mask(self):
        image = np.full((18, 22, 3), 180, dtype=np.uint8)
        mask = np.zeros((18, 22), dtype=np.uint8)
        mask[4:14, 7:17] = 255
        patch = make_masked_patch(image, mask)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "masked_patch.png"
            imk.write_image(str(path), patch)
            loaded = imk.read_image(str(path), preserve_alpha=True)

        self.assertEqual(loaded.shape, (18, 22, 4))
        self.assertTrue(np.array_equal(loaded[..., 3], mask))

    def test_expanded_automatic_mask_blends_only_its_inner_edge(self):
        height, width = 54, 62
        checker = (np.indices((height, width)).sum(axis=0) % 2) * 40
        original = np.repeat(checker[..., None], 3, axis=2).astype(np.uint8)
        mask = np.zeros((height, width), dtype=np.uint8)
        mask[12:43, 14:49] = 255
        engine = np.full_like(original, 180)

        result = postprocess_inpainted_result(
            original,
            mask,
            engine,
            edge_blend_px=2.5,
        )

        self.assertTrue(np.array_equal(result[mask == 0], original[mask == 0]))
        self.assertTrue(np.all(result[27, 31] == 180))
        self.assertTrue(np.all(result[12, 20] < 180))


if __name__ == "__main__":
    unittest.main()

import numpy as np
import time
import logging
import imkit as imk

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QBrush

from app.sam_mask_refiner import SAMMaskRefiner
from modules.utils.device import resolve_device
from modules.utils.pipeline_config import inpaint_map, get_config, get_inpainter_backend
from pipeline.inpaint_postprocess import make_masked_patch, postprocess_inpainted_result

logger = logging.getLogger(__name__)


class InpaintingHandler:
    """Handles image inpainting functionality."""
    
    def __init__(self, main_page):
        self.main_page = main_page
        self.inpainter_cache = None
        self.cached_inpainter_key = None
        # SAM is strictly a mask helper.  It never replaces the configured
        # LaMa, AOT or MI-GAN engine below.
        self.sam_mask_refiner = SAMMaskRefiner()

    def _ensure_inpainter(self):
        settings_page = self.main_page.settings_page
        inpainter_key = settings_page.get_tool_selection('inpainter')
        if self.inpainter_cache is None or self.cached_inpainter_key != inpainter_key:
            backend = get_inpainter_backend(inpainter_key)
            device = resolve_device(settings_page.is_gpu_enabled(), backend)
            InpainterClass = inpaint_map[inpainter_key]
            logger.info("pre-inpaint: initializing inpainter '%s' on device %s", inpainter_key, device)
            t0 = time.time()
            self.inpainter_cache = InpainterClass(device, backend=backend)
            self.cached_inpainter_key = inpainter_key
            logger.info("pre-inpaint: inpainter initialized in %.2fs", time.time() - t0)
        return self.inpainter_cache

    def manual_inpaint(self):
        image_viewer = self.main_page.image_viewer
        settings_page = self.main_page.settings_page
        mask = image_viewer.get_mask_for_inpainting()
        
        # Handle webtoon mode vs regular mode differently
        if self.main_page.webtoon_mode:
            # In webtoon mode, use visible area image for inpainting
            image, mappings = image_viewer.get_visible_area_image()
        else:
            # Regular mode - get the full image
            image = image_viewer.get_image_array()

        if image is None or mask is None:
            return None

        self._ensure_inpainter()
        config = get_config(settings_page)
        inpaint_input_img = self.inpainter_cache(image, mask, config)
        inpaint_input_img = imk.convert_scale_abs(inpaint_input_img) 
        inpaint_input_img = postprocess_inpainted_result(
            image,
            mask,
            inpaint_input_img,
            edge_blend_px=2.0,
        )

        return inpaint_input_img

    def magic_eraser_inpaint(self):
        """Run SAM over the painted mask, then inpaint with the selected engine."""
        image_viewer = self.main_page.image_viewer
        settings_page = self.main_page.settings_page
        # The non-expanded brush footprint is the only region the user has
        # authorised us to alter.  SAM may provide a little extra model
        # context, but it can never enlarge the final composite.
        rough_mask = image_viewer.get_mask_for_inpainting(strict=True)

        if self.main_page.webtoon_mode:
            image, _mappings = image_viewer.get_visible_area_image()
        else:
            image = image_viewer.get_image_array()

        if image is None or rough_mask is None:
            return []

        use_sam = bool(
            getattr(image_viewer, "magic_eraser_refine_with_sam", False)
        )
        refined_mask = (
            self.sam_mask_refiner.refine(image, rough_mask)
            if use_sam
            else rough_mask
        )
        self._ensure_inpainter()
        config = get_config(settings_page)
        inpainted_image = self.inpainter_cache(image, refined_mask, config)
        inpainted_image = imk.convert_scale_abs(inpainted_image)
        effective_mask = np.zeros_like(rough_mask)
        inpainted_image = postprocess_inpainted_result(
            image,
            rough_mask,
            inpainted_image,
            edge_blend_px=2.5,
            rebuild_entire_smooth_surface=True,
            effective_mask_out=effective_mask,
        )
        return self.get_inpainted_patches(effective_mask, inpainted_image)

    def _qimage_to_np(self, qimg: QImage):
        if qimg.width() <= 0 or qimg.height() <= 0:
            return np.zeros((max(1, qimg.height()), max(1, qimg.width())), dtype=np.uint8)
        ptr = qimg.constBits()
        arr = np.array(ptr).reshape(qimg.height(), qimg.bytesPerLine())
        return arr[:, :qimg.width()]

    def _generate_mask_from_saved_strokes(self, strokes: list[dict], image: np.ndarray):
        if image is None or not strokes:
            return None
        height, width = image.shape[:2]
        if width <= 0 or height <= 0:
            return None

        human_qimg = QImage(width, height, QImage.Format_Grayscale8)
        gen_qimg = QImage(width, height, QImage.Format_Grayscale8)
        human_qimg.fill(0)
        gen_qimg.fill(0)

        human_painter = QPainter(human_qimg)
        gen_painter = QPainter(gen_qimg)

        human_painter.setPen(QPen(QColor(255, 255, 255), 1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        gen_painter.setPen(QPen(QColor(255, 255, 255), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        human_painter.setBrush(QBrush(QColor(255, 255, 255)))
        gen_painter.setBrush(QBrush(QColor(255, 255, 255)))

        has_any = False
        for stroke in strokes:
            path = stroke.get('path')
            if path is None:
                continue
            brush_hex = QColor(stroke.get('brush', '#00000000')).name(QColor.HexArgb)
            if brush_hex == "#80ff0000":
                gen_painter.drawPath(path)
                has_any = True
                continue

            width_px = max(1, int(stroke.get('width', 25)))
            human_pen = QPen(QColor(255, 255, 255), width_px, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            human_painter.setPen(human_pen)
            human_painter.drawPath(path)
            has_any = True

        human_painter.end()
        gen_painter.end()

        if not has_any:
            return None

        human_mask = self._qimage_to_np(human_qimg)
        gen_mask = self._qimage_to_np(gen_qimg)
        kernel = np.ones((5, 5), np.uint8)
        human_mask = imk.dilate(human_mask, kernel, iterations=2)
        gen_mask = imk.dilate(gen_mask, kernel, iterations=3)
        mask = np.where((human_mask > 0) | (gen_mask > 0), 255, 0).astype(np.uint8)
        if np.count_nonzero(mask) == 0:
            return None
        return mask

    def _get_regular_patches(self, mask: np.ndarray, inpainted_image: np.ndarray):
        contours, _ = imk.find_contours(mask)
        patches = []
        for c in contours:
            x, y, w, h = imk.bounding_rect(c)
            patch = make_masked_patch(
                inpainted_image[y:y + h, x:x + w],
                mask[y:y + h, x:x + w],
            )
            patches.append({'bbox': [x, y, w, h], 'image': patch.copy()})
        return patches

    def inpaint_page_from_saved_strokes(self, image: np.ndarray, strokes: list[dict]):
        mask = self._generate_mask_from_saved_strokes(strokes, image)
        if mask is None:
            return []
        self._ensure_inpainter()
        config = get_config(self.main_page.settings_page)
        inpainted = self.inpainter_cache(image, mask, config)
        inpainted = imk.convert_scale_abs(inpainted)
        inpainted = postprocess_inpainted_result(
            image,
            mask,
            inpainted,
            edge_blend_px=2.0,
        )
        return self._get_regular_patches(mask, inpainted)

    def inpaint_region(self, image: np.ndarray, region: tuple[int, int, int, int]) -> list[dict]:
        """Inpaint exactly one user-selected rectangular region.

        A small surrounding crop gives the model visual context, while the
        returned patch is clipped back to the selection. This prevents an
        accidental selection from modifying any neighbouring manga art.
        """
        if image is None or image.ndim < 2:
            return []

        image_height, image_width = image.shape[:2]
        x, y, width, height = (int(value) for value in region)
        x = max(0, min(x, image_width))
        y = max(0, min(y, image_height))
        width = max(0, min(width, image_width - x))
        height = max(0, min(height, image_height - y))
        if width < 1 or height < 1:
            return []

        # Crop instead of processing the full page: it is much faster for a
        # watermark and lets the selected area remain the only affected area.
        context = max(32, min(128, int(max(width, height) * 0.35)))
        crop_x1 = max(0, x - context)
        crop_y1 = max(0, y - context)
        crop_x2 = min(image_width, x + width + context)
        crop_y2 = min(image_height, y + height + context)
        crop = image[crop_y1:crop_y2, crop_x1:crop_x2].copy()

        mask = np.zeros(crop.shape[:2], dtype=np.uint8)
        local_x = x - crop_x1
        local_y = y - crop_y1
        mask[local_y:local_y + height, local_x:local_x + width] = 255

        self._ensure_inpainter()
        config = get_config(self.main_page.settings_page)
        inpainted = self.inpainter_cache(crop, mask, config)
        inpainted = imk.convert_scale_abs(inpainted)
        inpainted = postprocess_inpainted_result(crop, mask, inpainted)
        patch = make_masked_patch(
            inpainted[local_y:local_y + height, local_x:local_x + width],
            mask[local_y:local_y + height, local_x:local_x + width],
        )
        return [{'bbox': [x, y, width, height], 'image': patch}]

    def inpaint_complete(self, patch_list):
        # Handle webtoon mode vs regular mode
        if self.main_page.webtoon_mode:
            # In webtoon mode, group patches by page and apply them
            patches_by_page = {}
            for patch in patch_list:
                if 'page_index' in patch and 'file_path' in patch:
                    file_path = patch['file_path']
                    
                    if file_path not in patches_by_page:
                        patches_by_page[file_path] = []
                    
                    # Remove page-specific keys for the patch command but keep scene_pos for webtoon mode
                    clean_patch = {
                        'bbox': patch['bbox'],
                        'image': patch['image']
                    }
                    # Add scene position info for webtoon mode positioning
                    if 'scene_pos' in patch:
                        clean_patch['scene_pos'] = patch['scene_pos']
                        clean_patch['page_index'] = patch['page_index']
                    patches_by_page[file_path].append(clean_patch)
            
            # Apply patches to each page
            for file_path, patches in patches_by_page.items():
                self.main_page.image_ctrl.on_inpaint_patches_processed(patches, file_path)
        else:
            # Regular mode - original behavior
            self.main_page.apply_inpaint_patches(patch_list)
        
        self.main_page.image_viewer.clear_brush_strokes() 
        self.main_page.undo_group.activeStack().endMacro()  
        # get_best_render_area(self.main_page.blk_list, original_image, inpainted)    

    def get_inpainted_patches(self, mask: np.ndarray, inpainted_image: np.ndarray):
        # slice mask into bounding boxes
        contours, _ = imk.find_contours(mask)
        patches = []
        # Handle webtoon mode vs regular mode
        if self.main_page.webtoon_mode:
            # In webtoon mode, we need to map patches back to their respective pages
            visible_image, mappings = self.main_page.image_viewer.get_visible_area_image()
            if visible_image is None or not mappings:
                return patches
                
            for i, c in enumerate(contours):
                x, y, w, h = imk.bounding_rect(c)
                patch_bottom = y + h

                # Find all pages that this patch overlaps with
                overlapping_mappings = []
                for mapping in mappings:
                    if (y < mapping['combined_y_end'] and patch_bottom > mapping['combined_y_start']):
                        overlapping_mappings.append(mapping)
                
                if not overlapping_mappings:
                    continue
                    
                # If patch spans multiple pages, clip and redistribute
                for mapping in overlapping_mappings:
                    # Calculate the intersection with this page
                    clip_top = max(y, mapping['combined_y_start'])
                    clip_bottom = min(patch_bottom, mapping['combined_y_end'])
                    
                    if clip_bottom <= clip_top:
                        continue
                        
                    # Extract the portion of the patch for this page
                    clipped_patch = make_masked_patch(
                        inpainted_image[clip_top:clip_bottom, x:x+w],
                        mask[clip_top:clip_bottom, x:x+w],
                    )
                    
                    # Convert coordinates back to page-local coordinates
                    page_local_y = clip_top - mapping['combined_y_start'] + mapping['page_crop_top']
                    clipped_height = clip_bottom - clip_top
                    
                    # Calculate the correct scene position by converting from visible area coordinates to scene coordinates
                    scene_y = mapping['scene_y_start'] + (clip_top - mapping['combined_y_start'])
                    
                    patches.append({
                        'bbox': [x, int(page_local_y), w, clipped_height],
                        'image': clipped_patch.copy(),
                        'page_index': mapping['page_index'],
                        'file_path': self.main_page.image_files[mapping['page_index']],
                        'scene_pos': [x, scene_y]  # Store correct scene position for webtoon mode
                    })
        else:
            # Regular mode - original behavior
            for c in contours:
                x, y, w, h = imk.bounding_rect(c)
                patch = make_masked_patch(
                    inpainted_image[y:y+h, x:x+w],
                    mask[y:y+h, x:x+w],
                )
                patches.append({
                    'bbox': [x, y, w, h],
                    'image': patch.copy(),
                })
                
        return patches
    
    def inpaint(self):
        mask = self.main_page.image_viewer.get_mask_for_inpainting()
        painted = self.manual_inpaint()
        if mask is None or painted is None:
            return []
        patches = self.get_inpainted_patches(mask, painted)
        return patches         

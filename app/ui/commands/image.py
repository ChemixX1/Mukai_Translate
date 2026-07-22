import numpy as np
import tempfile
from PySide6.QtGui import QPixmap, QUndoCommand
import imkit as imk

from .base import PatchCommandBase


class SetImageCommand(QUndoCommand):
    def __init__(self, parent, file_path: str, img_array: np.ndarray, 
                 display: bool = True):
        super().__init__()
        self.ct = parent
        self.update_image_history(file_path, img_array)
        self.first = True
        self.display_first_time = display

    def redo(self):
        if self.first:
            if not self.display_first_time:
                return
            
            file_path = self.ct.image_files[self.ct.curr_img_idx]
            
            # Ensure the file has proper history initialization
            if file_path not in self.ct.current_history_index:
                self.ct.current_history_index[file_path] = 0
            if file_path not in self.ct.image_history:
                self.ct.image_history[file_path] = [file_path]
                
            current_index = self.ct.current_history_index[file_path]
            img_array = self.get_img(file_path, current_index)
            self.ct.image_viewer.display_image_array(img_array)
            self.first = False

        if self.ct.curr_img_idx >= 0:
            file_path = self.ct.image_files[self.ct.curr_img_idx]
            
            # Ensure proper initialization
            if file_path not in self.ct.current_history_index:
                self.ct.current_history_index[file_path] = 0
            if file_path not in self.ct.image_history:
                self.ct.image_history[file_path] = [file_path]
                
            current_index = self.ct.current_history_index[file_path]
            
            if current_index < len(self.ct.image_history[file_path]) - 1:
                current_index += 1
                self.ct.current_history_index[file_path] = current_index

                img_array = self.get_img(file_path, current_index)

                self.ct.image_data[file_path] = img_array
                self.ct.image_viewer.display_image_array(img_array)

    def undo(self):
        if self.ct.curr_img_idx >= 0:

            file_path = self.ct.image_files[self.ct.curr_img_idx]
            
            # Ensure proper initialization
            if file_path not in self.ct.current_history_index:
                self.ct.current_history_index[file_path] = 0
            if file_path not in self.ct.image_history:
                self.ct.image_history[file_path] = [file_path]
                
            current_index = self.ct.current_history_index[file_path]
            
            if current_index > 0:
                current_index -= 1
                self.ct.current_history_index[file_path] = current_index
                
                img_array = self.get_img(file_path, current_index)

                self.ct.image_data[file_path] = img_array
                self.ct.image_viewer.display_image_array(img_array)

   
    def update_image_history(self, file_path: str, img_array: np.ndarray):
        im = self.ct.load_image(file_path)

        if not np.array_equal(im, img_array):
            self.ct.image_data[file_path] = img_array
            
            # Update file path history
            history = self.ct.image_history[file_path]
            current_index = self.ct.current_history_index[file_path]
            
            # Remove any future history if we're not at the end
            del history[current_index + 1:]
            
            # # Save new image to temp file and add to history
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png', dir=self.ct.temp_dir)
            imk.write_image(temp_file.name, img_array)
            temp_file.close()

            history.append(temp_file.name)

            # Update in-memory history if this image is loaded
            if self.ct.in_memory_history.get(file_path, []):
                in_mem_history = self.ct.in_memory_history[file_path]
                del in_mem_history[current_index + 1:]
                in_mem_history.append(img_array.copy())

            self.ct.current_history_index[file_path] = len(history) - 1

    def get_img(self, file_path, current_index):
        if self.ct.in_memory_history.get(file_path, []):
            img_array = self.ct.in_memory_history[file_path][current_index]
        else:
            img_array = imk.read_image(self.ct.image_history[file_path][current_index])

        return img_array


class ReplaceImagePixelsCommand(QUndoCommand):
    """Replace a page image while keeping the current scene items intact."""

    def __init__(
        self,
        parent,
        file_path: str,
        img_array: np.ndarray,
        text: str = "replace_image_pixels",
        clear_inpaint_patches: bool = False,
    ):
        super().__init__(text)
        self.ct = parent
        self.file_path = file_path
        self.new_img = img_array.copy()
        self.old_index = self._ensure_history()
        self.new_index = None
        self._prepared = False
        self.clear_inpaint_patches = clear_inpaint_patches
        self.old_patches = [
            dict(properties)
            for properties in self.ct.image_patches.get(self.file_path, [])
        ]

        temp_file = tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".png",
            dir=self.ct.temp_dir,
        )
        imk.write_image(temp_file.name, self.new_img)
        temp_file.close()
        self.new_path = temp_file.name

    def redo(self):
        self._prepare_history()
        self._apply_index(self.new_index)
        self._set_inpaint_patches([])

    def undo(self):
        self._apply_index(self.old_index)
        self._set_inpaint_patches(self.old_patches)

    def _ensure_history(self) -> int:
        if self.file_path not in self.ct.image_history:
            self.ct.image_history[self.file_path] = [self.file_path]
        if self.file_path not in self.ct.current_history_index:
            self.ct.current_history_index[self.file_path] = 0
        if self.file_path not in self.ct.in_memory_history:
            self.ct.in_memory_history[self.file_path] = []
        return self.ct.current_history_index[self.file_path]

    def _prepare_history(self):
        if self._prepared:
            return

        history = self.ct.image_history[self.file_path]
        old_index = min(self.old_index, len(history) - 1)
        del history[old_index + 1:]
        history.append(self.new_path)
        self.new_index = len(history) - 1

        in_memory = self.ct.in_memory_history.setdefault(self.file_path, [])
        if in_memory:
            del in_memory[old_index + 1:]
            in_memory.append(self.new_img.copy())

        self.old_index = old_index
        self._prepared = True

    def _apply_index(self, index: int):
        if index is None:
            return

        self.ct.current_history_index[self.file_path] = index
        img_array = self._image_for_index(index)
        self.ct.image_data[self.file_path] = img_array

        if self._is_displayed_page():
            self._update_displayed_pixmap(img_array)

    def _image_for_index(self, index: int):
        in_memory = self.ct.in_memory_history.get(self.file_path, [])
        if in_memory and index < len(in_memory):
            return in_memory[index]

        history_path = self.ct.image_history[self.file_path][index]
        return imk.read_image(history_path)

    def _is_current_page(self) -> bool:
        idx = self.ct.curr_img_idx
        return (
            idx >= 0
            and idx < len(self.ct.image_files)
            and self.ct.image_files[idx] == self.file_path
        )

    def _is_displayed_page(self) -> bool:
        viewer = self.ct.image_viewer
        if viewer.webtoon_mode:
            try:
                page_index = self.ct.image_files.index(self.file_path)
            except ValueError:
                return False
            return page_index in viewer.webtoon_manager.image_items
        return self._is_current_page()

    def _update_displayed_pixmap(self, img_array: np.ndarray):
        viewer = self.ct.image_viewer
        qimage = viewer.qimage_from_array(img_array)
        pixmap = QPixmap.fromImage(qimage)

        if viewer.webtoon_mode:
            try:
                page_index = self.ct.image_files.index(self.file_path)
            except ValueError:
                return

            manager = viewer.webtoon_manager
            manager.image_data[page_index] = img_array.copy()
            image_item = manager.image_items.get(page_index)
            if image_item:
                image_item.setPixmap(pixmap)
            viewer.viewport().update()
            return

        viewer.photo.setPixmap(pixmap)
        viewer._scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())
        viewer.viewport().update()

    def _set_inpaint_patches(self, patches):
        """Update only the cleanup overlays; text/rectangle scene items remain intact."""
        if not self.clear_inpaint_patches:
            return

        if patches:
            self.ct.image_patches[self.file_path] = [dict(properties) for properties in patches]
        else:
            self.ct.image_patches.pop(self.file_path, None)
        self.ct.in_memory_patches.pop(self.file_path, None)

        if not self._is_displayed_page():
            return

        scene = self.ct.image_viewer._scene
        for properties in self.old_patches:
            item = PatchCommandBase.find_matching_item(scene, properties)
            if item:
                scene.removeItem(item)

        for properties in patches:
            if not PatchCommandBase.find_matching_item(scene, properties):
                PatchCommandBase.create_patch_item(properties, self.ct.image_viewer)


class ToggleSkipImagesCommand(QUndoCommand):
    def __init__(self, main, file_paths: list[str], skip_status: bool):
        super().__init__()
        self.main = main
        self.file_paths = file_paths
        self.new_status = skip_status
        self.old_status = {
            path: main.image_states.get(path, {}).get('skip', False)
            for path in file_paths
        }

    def _apply_status(self, file_path: str, skip_status: bool):
        if file_path not in self.main.image_states:
            return
        self.main.image_states[file_path]['skip'] = skip_status

        try:
            idx = self.main.image_files.index(file_path)
        except ValueError:
            return

        item = self.main.page_list.item(idx)
        if item:
            fnt = item.font()
            fnt.setStrikeOut(skip_status)
            item.setFont(fnt)

    def redo(self):
        for file_path in self.file_paths:
            self._apply_status(file_path, self.new_status)

    def undo(self):
        for file_path in self.file_paths:
            self._apply_status(file_path, self.old_status.get(file_path, False))

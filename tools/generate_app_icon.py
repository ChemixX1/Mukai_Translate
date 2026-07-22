"""Install the source SVG and derive the Windows multi-resolution ICO."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from PIL import Image
from PySide6 import QtCore, QtGui, QtSvg


ICON_SIZES = (16, 20, 24, 32, 48, 64, 128, 256)


def render_square(renderer: QtSvg.QSvgRenderer, size: int) -> QtGui.QImage:
    image = QtGui.QImage(size, size, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.transparent)

    source_size = renderer.defaultSize()
    scale = min(size / source_size.width(), size / source_size.height())
    width = source_size.width() * scale
    height = source_size.height() * scale
    target = QtCore.QRectF((size - width) / 2, (size - height) / 2, width, height)

    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter, target)
    painter.end()
    return image


def qimage_to_pillow(image: QtGui.QImage) -> Image.Image:
    converted = image.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    return Image.frombytes(
        "RGBA",
        (converted.width(), converted.height()),
        bytes(converted.constBits()),
        "raw",
        "RGBA",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_svg", type=Path)
    parser.add_argument("resources_dir", type=Path)
    args = parser.parse_args()

    source = args.source_svg.resolve()
    destination = args.resources_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    installed_svg = destination / "logo_mt.svg"
    shutil.copyfile(source, installed_svg)

    renderer = QtSvg.QSvgRenderer(str(installed_svg))
    if not renderer.isValid() or renderer.defaultSize().isEmpty():
        raise ValueError(f"Invalid SVG logo: {source}")

    master = qimage_to_pillow(render_square(renderer, max(ICON_SIZES)))
    master.save(destination / "icon.ico", format="ICO", sizes=[(s, s) for s in ICON_SIZES])
    print(f"Installed {installed_svg}")
    print(f"Generated {destination / 'icon.ico'} with sizes {ICON_SIZES}")


if __name__ == "__main__":
    main()

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from PIL import Image


class ImageType(str, Enum):
    U8 = "u8"
    RGB = "rgb"
    I16 = "i16"


@dataclass(slots=True)
class ImaqImage:
    name: str = ""
    image_type: ImageType = ImageType.U8
    image: Image.Image | None = None
    disposed: bool = False
    window_open: bool = False
    zoom: float = 1.0
    display_mapping: dict[str, Any] | None = None
    drawings: list[Any] | None = None


def imaq_create(name: str = "", image_type: ImageType | str = ImageType.U8) -> ImaqImage:
    if not isinstance(image_type, ImageType):
        image_type = ImageType(str(image_type).lower())
    return ImaqImage(name=name, image_type=image_type, drawings=[])


def imaq_array_to_image(data: Any, image: ImaqImage | None = None) -> ImaqImage:
    target = image or imaq_create()
    target.image = Image.fromarray(data) if hasattr(data, "__array_interface__") else Image.new("L", (len(data[0]), len(data)))
    if not hasattr(data, "__array_interface__"):
        target.image.putdata([int(pixel) for row in data for pixel in row])
    return target


def imaq_copy(source: ImaqImage, target: ImaqImage | None = None) -> ImaqImage:
    copied = target or imaq_create(source.name, source.image_type)
    copied.image = source.image.copy() if source.image is not None else None
    copied.display_mapping = dict(source.display_mapping or {})
    copied.drawings = list(source.drawings or [])
    copied.zoom = source.zoom
    return copied


def imaq_dispose(image: ImaqImage) -> None:
    image.image = None
    image.disposed = True
    image.window_open = False


def imaq_wind_close(image: ImaqImage) -> None:
    image.window_open = False


def imaq_wind_display_mapping(image: ImaqImage, mapping: dict[str, Any] | None = None) -> dict[str, Any]:
    image.display_mapping = dict(mapping or {})
    return image.display_mapping


def imaq_wind_zoom_2(image: ImaqImage, zoom: float) -> float:
    image.zoom = zoom
    image.window_open = True
    return image.zoom


def imaq_wind_draw(image: ImaqImage, drawing: Any) -> None:
    if image.drawings is None:
        image.drawings = []
    image.drawings.append(drawing)
    image.window_open = True


def _ensure_image(image: ImaqImage) -> Image.Image:
    if image.image is None:
        raise ValueError("IMAQ image has no pixel data.")
    return image.image


def imaq_write_file_2(image: ImaqImage, path: str | Path, format_name: str | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_image(image).save(path, format=format_name)
    return path


def imaq_write_tiff_file_2(image: ImaqImage, path: str | Path) -> Path:
    return imaq_write_file_2(image, path, "TIFF")


def imaq_write_png_file_2(image: ImaqImage, path: str | Path) -> Path:
    return imaq_write_file_2(image, path, "PNG")


def imaq_write_jpeg_file_2(image: ImaqImage, path: str | Path) -> Path:
    return imaq_write_file_2(image, path, "JPEG")


def imaq_write_jpeg2000_file_2(image: ImaqImage, path: str | Path) -> Path:
    return imaq_write_file_2(image, path, "JPEG2000")


def imaq_write_bmp_file_2(image: ImaqImage, path: str | Path) -> Path:
    return imaq_write_file_2(image, path, "BMP")


def imaq_write_image_and_vision_info_file_2(image: ImaqImage, path: str | Path) -> Path:
    return imaq_write_file_2(image, path)


def hamamatsu_show_sequence(frames: list[Any]) -> dict[str, Any]:
    return {"frames": frames, "count": len(frames)}

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener()

# Browsers mostly cannot display these, so they are always converted to JPEG.
CONVERTED_TO_JPEG = {".heic", ".heif"}


def output_name(source: Path) -> str:
    """File name of the exported image (HEIC/HEIF pictures become JPEG)."""
    if source.suffix.lower() in CONVERTED_TO_JPEG:
        return f"{source.stem}.jpg"
    return source.name


def _resized_image(image: Image.Image, width: int, square: bool) -> Image.Image | None:
    image = ImageOps.exif_transpose(image)
    if square:
        size = min(width, *image.size)
        if image.size == (size, size):
            return None
        return ImageOps.fit(image, (size, size), Image.Resampling.LANCZOS)
    if image.width <= width:
        return None
    height = max(1, round(image.height * width / image.width))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def export_image(source: Path, destination: Path, width: int, square: bool = False) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(source) as image:
            convert = source.suffix.lower() in CONVERTED_TO_JPEG
            # MP0 is a JPEG with extra frames (e.g. iPhone depth maps).
            image_format = "JPEG" if convert or image.format == "MPO" else image.format
            # Do not resize if image is animated.
            animated = image_format != "JPEG" and getattr(image, "is_animated", False)
            resized = None if animated else _resized_image(image, width, square)
            if resized is None and convert:
                resized = ImageOps.exif_transpose(image)
            if resized is not None:
                if image_format == "JPEG" and resized.mode not in ("RGB", "L"):
                    resized = resized.convert("RGB")
                # Drop metadata (EXIF, e.g. GPS location), but keep the color profile.
                resized.save(
                    destination,
                    format=image_format,
                    quality=85,
                    optimize=True,
                    exif=b"",
                    icc_profile=image.info.get("icc_profile"),
                )
                return
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        if source.suffix.lower() in CONVERTED_TO_JPEG:
            print(f"Could not convert {source} to JPEG, skip: {exc}")
            return
        print(f"Could not resize {source}, skip: {exc}")
    shutil.copyfile(source, destination)

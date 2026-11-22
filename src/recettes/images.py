from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


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
            # MP0 is a JPEG with extra frames (e.g. iPhone depth maps).
            image_format = "JPEG" if image.format == "MPO" else image.format
            # Do not resize if image is animated.
            animated = image_format != "JPEG" and getattr(image, "is_animated", False)
            resized = None if animated else _resized_image(image, width, square)
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
        print(f"Could not resize {source}, skip: {exc}")
        pass
    shutil.copyfile(source, destination)

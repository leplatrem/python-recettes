from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

import PIL
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener()

# Browsers mostly cannot display these, so they are always converted to JPEG.
CONVERTED_TO_JPEG = {".heic", ".heif"}
# Bump when the export logic changes, so cached pictures are generated again.
CACHE_VERSION = "1"
CACHE_ENTRY_RE = re.compile(r"^[0-9a-f]{64}\.[^.]+$")


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


def cached_export_image(
    source: Path, destination: Path, width: int, square: bool, cache_dir: Path | None
) -> Path | None:
    """Export an image, reusing a previous result from `cache_dir` if the source is unchanged.

    Returns the cache entry used, if any.
    """
    if cache_dir is None:
        export_image(source, destination, width, square)
        return None
    digest = hashlib.sha256(f"{CACHE_VERSION}:{PIL.__version__}:{width}:{square}:".encode())
    digest.update(source.read_bytes())
    entry = cache_dir / f"{digest.hexdigest()}{Path(output_name(source)).suffix.lower()}"
    if not entry.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Write to a temporary file, so an interrupted build never leaves a broken entry.
        partial = entry.with_name(f".{entry.name}.partial")
        export_image(source, partial, width, square)
        if not partial.exists():  # Conversion failed and the picture was skipped.
            return None
        partial.replace(entry)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(entry, destination)
    return entry


def prune_cache(cache_dir: Path, used: set[Path]) -> None:
    """Delete cache entries that were not used by the last build."""
    if not cache_dir.is_dir():
        return
    for path in cache_dir.iterdir():
        if path.is_file() and CACHE_ENTRY_RE.match(path.name) and path not in used:
            path.unlink()

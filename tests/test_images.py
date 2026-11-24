from pathlib import Path

import pytest
from PIL import Image, ImageCms

from recettes.images import export_image
from recettes.website import BuildOptions, build


def test_images_are_downscaled_and_main_picture_has_a_thumbnail(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "tarte.md").write_text("# Étape 1\n\nÉtalez.\n", encoding="utf-8")
    Image.new("RGB", (2000, 1000), "red").save(source / "tarte.jpg")
    Image.new("RGB", (300, 600), "blue").save(source / "tarte-etape-1.png")
    output = tmp_path / "site"

    build(source, output, BuildOptions(image_width=800, thumbnail_width=100))

    images = output / "assets" / "images"
    with Image.open(images / "tarte.jpg") as image:
        assert (image.format, image.size) == ("JPEG", (800, 400))
    with Image.open(images / "thumbnails" / "tarte.jpg") as image:
        assert image.size == (100, 100)
    assert (images / "tarte-etape-1.png").read_bytes() == (
        source / "tarte-etape-1.png"
    ).read_bytes()
    assert not (images / "thumbnails" / "tarte-etape-1.png").exists()
    with Image.open(source / "tarte.jpg") as image:
        assert image.size == (2000, 1000)
    with Image.open(images / "small" / "tarte.jpg") as image:
        assert image.size == (400, 200)
    assert not (images / "small" / "tarte-etape-1.png").exists()
    recipe = (output / "recipes" / "tarte.html").read_text(encoding="utf-8")
    assert (
        'srcset="../assets/images/small/tarte.jpg 400w, ../assets/images/tarte.jpg 800w"'
    ) in recipe
    assert 'src="../assets/images/tarte-etape-1.png" width="300" height="600"' in recipe


def test_multi_picture_jpegs_from_phones_are_downscaled(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "tarte.md").write_text("Une tarte.\n", encoding="utf-8")
    frames = [Image.new("RGB", (2000, 1000), "red"), Image.new("RGB", (500, 250), "blue")]
    frames[0].save(source / "tarte.jpeg", format="MPO", save_all=True, append_images=frames[1:])
    with Image.open(source / "tarte.jpeg") as image:
        assert (image.format, image.is_animated) == ("MPO", True)
    output = tmp_path / "site"

    build(source, output, BuildOptions(image_width=800, thumbnail_width=100))

    images = output / "assets" / "images"
    with Image.open(images / "tarte.jpeg") as image:
        assert (image.format, image.size) == ("JPEG", (800, 400))
    with Image.open(images / "thumbnails" / "tarte.jpeg") as image:
        assert (image.format, image.size) == ("JPEG", (100, 100))


def test_resized_images_drop_exif_but_keep_color_profile(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "tarte.md").write_text("Une tarte.\n", encoding="utf-8")
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # Make
    exif[0x8825] = {2: (48.0, 51.0, 24.0)}  # GPS latitude
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.new("RGB", (2000, 1000), "red").save(source / "tarte.jpg", exif=exif, icc_profile=icc)
    output = tmp_path / "site"

    build(source, output, BuildOptions(image_width=800, thumbnail_width=100))

    images = output / "assets" / "images"
    for path in (images / "tarte.jpg", images / "thumbnails" / "tarte.jpg"):
        with Image.open(path) as image:
            assert not image.getexif()
            assert "exif" not in image.info
            assert image.info["icc_profile"] == icc


def test_heic_images_are_converted_to_jpeg(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "gnocchi.md").write_text(
        "# Étape 1\n\nMélangez.\n\n![photo](gnocchi-extra.HEIC)\n", encoding="utf-8"
    )
    Image.new("RGB", (2000, 1000), "red").save(source / "gnocchi.heic", format="HEIF")
    Image.new("RGB", (300, 200), "blue").save(source / "gnocchi-etape-1.heic", format="HEIF")
    Image.new("RGB", (300, 200), "green").save(source / "gnocchi-extra.HEIC", format="HEIF")
    output = tmp_path / "site"

    build(source, output, BuildOptions(image_width=800, thumbnail_width=100))

    images = output / "assets" / "images"
    with Image.open(images / "gnocchi.jpg") as image:
        assert (image.format, image.size) == ("JPEG", (800, 400))
    with Image.open(images / "thumbnails" / "gnocchi.jpg") as image:
        assert (image.format, image.size) == ("JPEG", (100, 100))
    with Image.open(images / "gnocchi-etape-1.jpg") as image:
        assert (image.format, image.size) == ("JPEG", (300, 200))
    with Image.open(images / "gnocchi-extra.jpg") as image:
        assert image.format == "JPEG"
    assert not list(images.rglob("*.heic")) and not list(images.rglob("*.HEIC"))
    recipe = (output / "recipes" / "gnocchi.html").read_text(encoding="utf-8")
    assert 'gnocchi-etape-1.jpg" width="300" height="200"' in recipe
    assert "../assets/images/gnocchi-extra.jpg" in recipe
    assert "heic" not in recipe.lower()
    index = (output / "index.html").read_text(encoding="utf-8")
    assert "assets/images/thumbnails/gnocchi.jpg" in index


def test_cached_images_are_not_processed_again(tmp_path: Path, monkeypatch) -> None:
    from recettes import images as images_module

    source = tmp_path / "recipes"
    source.mkdir()
    (source / "tarte.md").write_text("Une tarte.\n", encoding="utf-8")
    Image.new("RGB", (2000, 1000), "red").save(source / "tarte.jpg")
    Image.new("RGB", (2000, 1000), "blue").save(source / "tarte-1.png")
    cache = tmp_path / "cache"
    calls = []
    original = images_module.export_image

    def counting_export(source_path, destination, width, square=False):
        calls.append((source_path.name, width, square))
        original(source_path, destination, width, square)

    monkeypatch.setattr(images_module, "export_image", counting_export)

    build(
        source,
        tmp_path / "site",
        BuildOptions(image_width=800, thumbnail_width=100, cache_dir=cache),
    )
    # Each picture also has a small version, half as wide.
    assert sorted(calls) == [
        ("tarte-1.png", 400, False),
        ("tarte-1.png", 800, False),
        ("tarte.jpg", 50, True),
        ("tarte.jpg", 100, True),
        ("tarte.jpg", 400, False),
        ("tarte.jpg", 800, False),
    ]
    assert len(list(cache.iterdir())) == 6

    # A fresh output directory is filled from the cache.
    calls.clear()
    output = tmp_path / "site2"
    build(source, output, BuildOptions(image_width=800, thumbnail_width=100, cache_dir=cache))
    assert calls == []
    with Image.open(output / "assets" / "images" / "tarte.jpg") as image:
        assert image.size == (800, 400)
    with Image.open(output / "assets" / "images" / "thumbnails" / "tarte.jpg") as image:
        assert image.size == (100, 100)

    # Only changed pictures (or settings) are processed again; stale entries are pruned.
    Image.new("RGB", (2000, 1000), "green").save(source / "tarte-1.png")
    build(source, output, BuildOptions(image_width=800, thumbnail_width=100, cache_dir=cache))
    assert calls == [("tarte-1.png", 800, False), ("tarte-1.png", 400, False)]
    assert len(list(cache.iterdir())) == 6
    with Image.open(output / "assets" / "images" / "tarte-1.png") as image:
        assert image.getpixel((0, 0)) == (0, 128, 0)

    calls.clear()
    build(source, output, BuildOptions(image_width=600, thumbnail_width=100, cache_dir=cache))
    assert sorted(calls) == [
        ("tarte-1.png", 300, False),
        ("tarte-1.png", 600, False),
        ("tarte.jpg", 300, False),
        ("tarte.jpg", 600, False),
    ]
    assert len(list(cache.iterdir())) == 6


def test_unreadable_picture_warns_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "broken.jpg"
    source.write_bytes(b"not an image")

    export_image(source, tmp_path / "out" / "broken.jpg", 100)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Warning: could not resize" in captured.err

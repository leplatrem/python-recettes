from pathlib import Path

from PIL import Image, ImageCms

from recettes.cli import build


def test_images_are_downscaled_and_main_picture_has_a_thumbnail(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "tarte.md").write_text("# Étape 1\n\nÉtalez.\n", encoding="utf-8")
    Image.new("RGB", (2000, 1000), "red").save(source / "tarte.jpg")
    Image.new("RGB", (300, 600), "blue").save(source / "tarte-etape-1.png")
    output = tmp_path / "site"

    build(source, output, image_width=800, thumbnail_width=100)

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


def test_multi_picture_jpegs_from_phones_are_downscaled(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "tarte.md").write_text("Une tarte.\n", encoding="utf-8")
    frames = [Image.new("RGB", (2000, 1000), "red"), Image.new("RGB", (500, 250), "blue")]
    frames[0].save(source / "tarte.jpeg", format="MPO", save_all=True, append_images=frames[1:])
    with Image.open(source / "tarte.jpeg") as image:
        assert (image.format, image.is_animated) == ("MPO", True)
    output = tmp_path / "site"

    build(source, output, image_width=800, thumbnail_width=100)

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

    build(source, output, image_width=800, thumbnail_width=100)

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

    build(source, output, image_width=800, thumbnail_width=100)

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
    assert "gnocchi-etape-1.jpg" in recipe
    assert "../assets/images/gnocchi-extra.jpg" in recipe
    assert "heic" not in recipe.lower()
    index = (output / "recipes.json").read_text(encoding="utf-8")
    assert "assets/images/thumbnails/gnocchi.jpg" in index

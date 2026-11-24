"""Recipe files, their properties and pictures."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from urllib.parse import quote

import frontmatter
import typer

from recettes.errors import fail
from recettes.images import cached_export_image, output_name
from recettes.markdown import (
    HEADING_RE,
    HTML_COMMENT_RE,
    first_paragraph,
    heading_text,
    markdown_with_ingredients,
    plain_text,
    rewrite_local_links,
)
from recettes.quantities import MASS_UNITS_G, Ingredient, aggregate_ingredients, volume_ml
from recettes.text import natural_key, slugify

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".heic", ".heif"}
# Defaults are twice the stylesheet sizes (recipe page column width, home page card
# thumbnail), so pictures stay sharp on high-density (retina) screens.
DEFAULT_IMAGE_WIDTH = 2 * 760
DEFAULT_THUMBNAIL_WIDTH = 2 * 112


@dataclasses.dataclass
class Property:
    """Front matter property shown on the recipe page, e.g. `preparation: 45`."""

    name: str
    value: object


@dataclasses.dataclass
class Recipe:
    path: Path
    title: str
    lang: str
    tags: list[str]
    properties: list[Property]
    # Start of the first paragraph, and the whole text without markup.
    excerpt: str
    text: str
    portions: int | None
    # As they appear in the text, and summed up for the ingredient list.
    ingredients: list[Ingredient]
    ingredient_list: list[Ingredient]
    content: str
    # Published picture names.
    main_image: str | None
    section_images: dict[str, list[str]]
    gallery: list[str]

    @property
    def slug(self) -> str:
        return self.path.stem


def parse_tags(value: object) -> list[str]:
    if isinstance(value, str):
        tags = value.split(",")
    elif isinstance(value, list):
        tags = [str(tag) for tag in value]
    else:
        return []
    return [tag.strip() for tag in tags if tag.strip()]


def assign_images(source: Path, recipe_stems: set[str]) -> dict[str, list[Path]]:
    """Map recipe stems to their images: `{stem}.ext` or `{stem}-{suffix}.ext`.

    An image goes to the longest matching recipe stem, so `tart-lemon.jpg` belongs to
    `tart-lemon.md` (when it exists) rather than to `tart.md`.
    """
    images: dict[str, list[Path]] = {stem: [] for stem in recipe_stems}
    for path in source.iterdir():
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        owners = [
            stem for stem in recipe_stems if path.stem == stem or path.stem.startswith(stem + "-")
        ]
        if owners:
            images[max(owners, key=len)].append(path)
    published: dict[str, Path] = {}
    for paths in images.values():
        paths.sort(key=lambda path: natural_key(path.name))
        for path in paths:
            name = output_name(path)
            if name in published:
                fail(
                    f"Pictures '{published[name].name}' and '{path.name}' would both be "
                    f"published as '{name}'. Rename one of them."
                )
            published[name] = path
    return images


def classify_images(
    stem: str, images: list[Path], content: str
) -> tuple[str | None, dict[str, list[str]], list[str]]:
    """Split images into the main picture, per-heading pictures, and leftovers."""
    heading_slugs = {
        slugify(heading_text(match.group(2))) for match in HEADING_RE.finditer(content)
    }
    main = None
    sections: dict[str, list[str]] = {}
    gallery = []
    for image in images:
        suffix = image.stem[len(stem) + 1 :]
        name = output_name(image)
        if image.stem == stem and main is None:
            main = name
        elif suffix and suffix in heading_slugs:
            sections.setdefault(suffix, []).append(name)
        else:
            gallery.append(name)
    return main, sections, gallery


def local_link_targets(paths: list[Path], images: dict[str, list[Path]]) -> dict[Path, str]:
    """Map source files that end up in the site to their URL from a recipe page."""
    targets = {}
    for path in paths:
        targets[path.resolve()] = f"../recipes/{quote(path.stem, safe='-_')}.html"
        for image in images[path.stem]:
            targets[image.resolve()] = f"../assets/images/{quote(output_name(image), safe='-_.')}"
    return targets


def parse_portions(value: object) -> int | None:
    """Return portions as a positive integer, or None when it is not one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
    elif not isinstance(value, (int, str)):
        return None
    try:
        portions = int(value)
    except ValueError:
        return None
    return portions if portions >= 1 else None


def recipe_page(
    path: Path,
    image_dir: Path,
    link_targets: dict[Path, str],
    images: list[Path],
    image_width: int = DEFAULT_IMAGE_WIDTH,
    thumbnail_width: int = DEFAULT_THUMBNAIL_WIDTH,
    simple_mode: bool = True,
    cache_dir: Path | None = None,
    used_cache: set[Path] | None = None,
) -> Recipe:
    try:
        document = frontmatter.load(path)
    except (OSError, ValueError) as exc:
        fail(f"Could not read recipe '{path.name}': {exc}")
    metadata = document.metadata
    portions = parse_portions(metadata.get("portions"))
    lang = str(metadata.get("lang", ""))

    title = str(metadata.get("title") or path.stem.replace("-", " ").title())
    body = HTML_COMMENT_RE.sub("", document.content)
    content, ingredients = markdown_with_ingredients(body)
    content = rewrite_local_links(content, path, link_targets)
    main_image, section_images, gallery = classify_images(path.stem, images, content)
    exports = []
    for image in images:
        name = output_name(image)
        exports.append((image, image_dir / name, image_width, False))
        if name == main_image:
            exports.append((image, image_dir / "thumbnails" / name, thumbnail_width, True))
    for image, target, width, square in exports:
        entry = cached_export_image(image, target, width, square, cache_dir)
        if entry is not None and used_cache is not None:
            used_cache.add(entry)

    ingredient_list = aggregate_ingredients(ingredients)
    if simple_mode:
        for ingredient in [*ingredients, *ingredient_list]:
            ingredient.ml = volume_ml(ingredient.amount, ingredient.unit, ingredient.name, lang)
        for ingredient in ingredient_list:
            if ingredient.unit in MASS_UNITS_G and ingredient.ml is None:
                typer.echo(
                    f"Warning: '{path.name}': unknown density for '{ingredient.name}', "
                    "Simple mode will keep the weight",
                    err=True,
                )

    excluded = {"title", "tags"}
    if portions is not None or metadata.get("portions") in (None, ""):
        excluded.add("portions")
    properties = [
        Property(str(key), value) for key, value in metadata.items() if key not in excluded
    ]
    return Recipe(
        path=path,
        title=title,
        lang=lang,
        tags=parse_tags(metadata.get("tags")),
        properties=properties,
        excerpt=first_paragraph(body),
        text=plain_text(body),
        portions=portions,
        ingredients=ingredients,
        ingredient_list=ingredient_list,
        content=content,
        main_image=main_image,
        section_images=section_images,
        gallery=gallery,
    )

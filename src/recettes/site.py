"""Build and lint a recipe website."""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import html
import shutil
from pathlib import Path
from urllib.parse import quote

from recettes import i18n
from recettes.errors import fail
from recettes.images import cached_export_image, image_size, output_name, prune_cache
from recettes.recipes import (
    Recipe,
    load_recipes,
)
from recettes.render import (
    attr,
    edit_link,
    interface_values,
    license_html,
    meta_tags,
    recipe_card_html,
    recipe_html_parts,
    render_template,
    tag_cloud_html,
)

DEFAULT_LICENSE = "[Copyrights CC-BY](https://creativecommons.org/licenses/by/4.0/)"
# Defaults are twice the stylesheet sizes (recipe page column width, home page card
# thumbnail), so pictures stay sharp on high-density (retina) screens.
DEFAULT_IMAGE_WIDTH = 2 * 760
DEFAULT_THUMBNAIL_WIDTH = 2 * 112


@dataclasses.dataclass(frozen=True)
class BuildOptions:
    """Website settings, see the `build` command help."""

    title: str = "Recipes"
    edit_url: str | None = None
    base_url: str | None = None
    license: str = DEFAULT_LICENSE
    image_width: int = DEFAULT_IMAGE_WIDTH
    thumbnail_width: int = DEFAULT_THUMBNAIL_WIDTH
    simple_mode: bool = True
    cache_dir: Path | None = None
    # Language of the interface and of recipes without `lang`, guessed when empty.
    lang: str = ""


def common_language(recipes: list[Recipe]) -> str:
    """Language of all recipes when they have the same, English otherwise."""
    languages = {recipe.lang for recipe in recipes}
    return (languages.pop() or i18n.DEFAULT_LANG) if len(languages) == 1 else i18n.DEFAULT_LANG


def export_images(
    recipe: Recipe,
    image_dir: Path,
    options: BuildOptions,
    used_cache: set[Path],
) -> None:
    """Publish the recipe pictures, and a square thumbnail of the main one.

    Each picture also gets a version half as wide in a `small/` folder, for screens that do
    not have a high density.
    """
    for image in recipe.images:
        name = output_name(image)
        exports = [("", options.image_width, False)]
        if name == recipe.main_image:
            exports.append(("thumbnails/", options.thumbnail_width, True))
        for folder, width, square in exports:
            for path, variant_width in ((folder, width), (f"{folder}small/", max(1, width // 2))):
                target = image_dir / path / name
                entry = cached_export_image(image, target, variant_width, square, options.cache_dir)
                if entry is not None:
                    used_cache.add(entry)
                size = image_size(target) if target.exists() else None
                if size:
                    recipe.picture_sizes[f"{path}{name}"] = size
            # Small pictures are not downscaled: no need for a small version.
            small, large = (
                recipe.picture_sizes.get(f"{path}{name}") for path in (f"{folder}small/", folder)
            )
            if small and (not large or small[0] >= large[0]):
                (image_dir / folder / "small" / name).unlink()
                with contextlib.suppress(OSError):  # Only when empty.
                    (image_dir / folder / "small").rmdir()
                del recipe.picture_sizes[f"{folder}small/{name}"]


def build(
    source: Path,
    destination: Path,
    options: BuildOptions | None = None,
) -> int:
    """Generate the website in `destination`, and return the number of recipes."""
    options = options or BuildOptions()
    source = source.resolve()
    destination = destination.resolve()
    cache_dir = options.cache_dir.resolve() if options.cache_dir else None
    options = dataclasses.replace(options, cache_dir=cache_dir)
    if source == destination or source in destination.parents:
        fail("Output directory must be outside the recipe source directory")
    # Only the top level of the source directory is read, so the cache can be a subdirectory.
    if cache_dir and (
        cache_dir == source or cache_dir == destination or destination in cache_dir.parents
    ):
        fail("Cache directory must be outside the output directory")
    recipes = load_recipes(source, options.simple_mode)

    package_dir = Path(__file__).parent
    static = package_dir / "static"
    templates = package_dir / "templates"
    assets = destination / "assets"
    recipes_dir = destination / "recipes"
    # Remove previous outputs, so deleted recipes and pictures are not published anymore.
    for generated in (assets, recipes_dir):
        if generated.is_dir():
            shutil.rmtree(generated)
    assets.mkdir(parents=True, exist_ok=True)
    # Content hashes appended to asset URLs, so browsers never use stale cached copies.
    versions = {}
    for filename in ("style.css", "app.js", "recipe.js", "favicon.svg"):
        shutil.copyfile(static / filename, assets / filename)
        digest = hashlib.sha256((static / filename).read_bytes()).hexdigest()[:10]
        versions[filename.replace(".", "_") + "_version"] = digest
    footer_license = license_html(options.license)
    shutil.copytree(static / "fonts", assets / "fonts", dirs_exist_ok=True)
    image_dir = assets / "images"
    recipes_dir.mkdir(parents=True, exist_ok=True)
    used_cache: set[Path] = set()
    site_lang = options.lang or common_language(recipes)
    for recipe in recipes:
        slug = recipe.slug
        lang = recipe.lang or site_lang
        export_images(recipe, image_dir, options, used_cache)
        page = render_template(
            templates / "recipe.html",
            root="../",
            title=html.escape(recipe.title),
            lang=attr(lang),
            edit_link=edit_link(options.edit_url, recipe.path, lang),
            meta_tags=meta_tags(
                recipe.title,
                "article",
                options.title,
                options.base_url,
                f"recipes/{quote(slug, safe='-_')}.html",
                recipe.excerpt,
                recipe.main_image,
                recipe.tags,
            ),
            license=footer_license,
            **versions,
            **interface_values(lang),
            **recipe_html_parts(recipe, lang),
        )
        (recipes_dir / f"{slug}.html").write_text(page, encoding="utf-8")
    index = render_template(
        templates / "index.html",
        root="",
        title=html.escape(options.title),
        lang=attr(site_lang),
        search_placeholder=attr(
            i18n.strings(site_lang)["search_placeholder"].format(count=len(recipes))
        ),
        tag_cloud=tag_cloud_html(recipes),
        recipe_cards="".join(recipe_card_html(recipe) for recipe in recipes),
        meta_tags=meta_tags(options.title, "website", options.title, options.base_url, ""),
        license=footer_license,
        **versions,
        **interface_values(site_lang),
    )
    (destination / "index.html").write_text(index, encoding="utf-8")
    if cache_dir:
        prune_cache(cache_dir, used_cache)
    return len(recipes)


def lint(source: Path) -> int:
    """Check recipe files and their local links without generating a website."""
    return len(load_recipes(source.resolve()))

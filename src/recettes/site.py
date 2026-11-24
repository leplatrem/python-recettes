"""Build and lint a recipe website."""

from __future__ import annotations

import hashlib
import html
import shutil
from pathlib import Path
from urllib.parse import quote

from recettes.errors import fail
from recettes.images import cached_export_image, output_name, prune_cache
from recettes.recipes import (
    DEFAULT_IMAGE_WIDTH,
    DEFAULT_THUMBNAIL_WIDTH,
    Recipe,
    load_recipes,
)
from recettes.render import (
    edit_link,
    license_html,
    meta_tags,
    recipe_html_parts,
    recipe_index_data,
    render_template,
)

DEFAULT_LICENSE = "[Copyrights CC-BY](https://creativecommons.org/licenses/by/4.0/)"


def export_images(
    recipe: Recipe,
    image_dir: Path,
    image_width: int,
    thumbnail_width: int,
    cache_dir: Path | None,
    used_cache: set[Path],
) -> None:
    """Publish the recipe pictures, and a square thumbnail of the main one."""
    for image in recipe.images:
        name = output_name(image)
        exports = [(image_dir / name, image_width, False)]
        if name == recipe.main_image:
            exports.append((image_dir / "thumbnails" / name, thumbnail_width, True))
        for target, width, square in exports:
            entry = cached_export_image(image, target, width, square, cache_dir)
            if entry is not None:
                used_cache.add(entry)


def build(
    source: Path,
    destination: Path,
    title: str = "Recipes",
    edit_url: str | None = None,
    image_width: int = DEFAULT_IMAGE_WIDTH,
    thumbnail_width: int = DEFAULT_THUMBNAIL_WIDTH,
    simple_mode: bool = True,
    cache_dir: Path | None = None,
    base_url: str | None = None,
    license: str = DEFAULT_LICENSE,
) -> int:
    source = source.resolve()
    destination = destination.resolve()
    cache_dir = cache_dir.resolve() if cache_dir else None
    if source == destination or source in destination.parents:
        fail("Output directory must be outside the recipe source directory")
    # Only the top level of the source directory is read, so the cache can be a subdirectory.
    if cache_dir and (
        cache_dir == source or cache_dir == destination or destination in cache_dir.parents
    ):
        fail("Cache directory must be outside the output directory")
    recipes = load_recipes(source, simple_mode)

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
    for filename in ("style.css", "app.js", "recipe.js"):
        shutil.copyfile(static / filename, assets / filename)
        digest = hashlib.sha256((static / filename).read_bytes()).hexdigest()[:10]
        versions[filename.replace(".", "_") + "_version"] = digest
    footer_license = license_html(license)
    shutil.copytree(static / "fonts", assets / "fonts", dirs_exist_ok=True)
    image_dir = assets / "images"
    recipes_dir.mkdir(parents=True, exist_ok=True)
    used_cache: set[Path] = set()
    for recipe in recipes:
        slug = recipe.slug
        export_images(recipe, image_dir, image_width, thumbnail_width, cache_dir, used_cache)
        page = render_template(
            templates / "recipe.html",
            title=html.escape(recipe.title),
            lang=html.escape(recipe.lang, quote=True),
            edit_link=edit_link(edit_url, recipe.path),
            meta_tags=meta_tags(
                recipe.title,
                "article",
                title,
                base_url,
                f"recipes/{quote(slug, safe='-_')}.html",
                recipe.excerpt,
                recipe.main_image,
                recipe.tags,
            ),
            license=footer_license,
            **versions,
            **recipe_html_parts(recipe),
        )
        (recipes_dir / f"{slug}.html").write_text(page, encoding="utf-8")
    prefetch_links = "\n    ".join(
        f'<link rel="prefetch" href="recipes/{quote(recipe.slug, safe="-_")}.html">'
        for recipe in recipes
    )
    index_data = recipe_index_data(recipes)
    versions["recipes_json_version"] = hashlib.sha256(index_data.encode()).hexdigest()[:10]
    languages = {recipe.lang for recipe in recipes if recipe.lang}
    index = render_template(
        templates / "index.html",
        title=html.escape(title),
        lang=html.escape(next(iter(languages)) if len(languages) == 1 else "", quote=True),
        prefetch_links=prefetch_links,
        meta_tags=meta_tags(title, "website", title, base_url, ""),
        license=footer_license,
        **versions,
    )
    (destination / "index.html").write_text(index, encoding="utf-8")
    (destination / "recipes.json").write_text(index_data, encoding="utf-8")
    if cache_dir:
        prune_cache(cache_dir, used_cache)
    return len(recipes)


def lint(source: Path) -> int:
    """Check recipe files and their local links without generating a website."""
    return len(load_recipes(source.resolve()))

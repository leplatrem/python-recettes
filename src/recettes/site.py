"""Build and lint a recipe website."""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import shutil
from importlib import resources
from pathlib import Path

from markupsafe import Markup

from recettes.images import cached_export_image, image_size, output_name, prune_cache
from recettes.recipes import (
    Recipe,
    load_recipes,
)
from recettes.render import (
    edit_link,
    license_html,
    recipe_content,
    recipe_url,
    render_template,
    tag_counts,
)
from recettes.utils import DEFAULT_LANG, fail, recipes_count, strings

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
    # Home page description for search engines and link previews, guessed when empty.
    description: str = ""
    # Language of the interface and of recipes without `lang`, guessed when empty.
    lang: str = ""


def common_language(recipes: list[Recipe]) -> str:
    """Language of all recipes when they have the same, English otherwise."""
    languages = {recipe.lang for recipe in recipes}
    return (languages.pop() or DEFAULT_LANG) if len(languages) == 1 else DEFAULT_LANG


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
    if cache_dir and (cache_dir in (source, destination) or destination in cache_dir.parents):
        fail("Cache directory must be outside the output directory")
    recipes = load_recipes(source, options.simple_mode)

    package = resources.files("recettes")
    static = package / "static"
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
        content = (static / filename).read_bytes()
        (assets / filename).write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()[:10]
        versions[filename] = digest
    footer_license = Markup(license_html(options.license))
    (assets / "fonts").mkdir()
    for font in (static / "fonts").iterdir():
        (assets / "fonts" / font.name).write_bytes(font.read_bytes())
    image_dir = assets / "images"
    recipes_dir.mkdir(parents=True, exist_ok=True)
    used_cache: set[Path] = set()
    site_lang = options.lang or common_language(recipes)
    base_url = options.base_url.rstrip("/") + "/" if options.base_url else ""
    # Values used by the layout of all pages.
    common = {
        "site_name": options.title,
        "base_url": base_url,
        "license": footer_license,
        "versions": versions,
    }
    for recipe in recipes:
        slug = recipe.slug
        lang = recipe.lang or site_lang
        export_images(recipe, image_dir, options, used_cache)
        page = render_template(
            "recipe.html",
            root="../",
            title=recipe.title,
            lang=lang,
            recipe=recipe,
            content=recipe_content(recipe),
            edit_url=edit_link(options.edit_url, recipe.path),
            path=recipe_url(recipe),
            page_type="article",
            description=recipe.excerpt,
            image=recipe.main_image,
            article_tags=recipe.tags,
            t=strings(lang),
            **common,
        )
        (recipes_dir / f"{slug}.html").write_text(page, encoding="utf-8")
    index = render_template(
        "index.html",
        root="",
        title=options.title,
        lang=site_lang,
        tags=tag_counts(recipes),
        recipes=recipes,
        path="",
        page_type="website",
        description=options.description or recipes_count(site_lang, len(recipes)),
        image=None,
        article_tags=[],
        t=strings(site_lang),
        **common,
    )
    (destination / "index.html").write_text(index, encoding="utf-8")
    sitemap = destination / "sitemap.xml"
    if options.base_url:
        sitemap.write_text(
            render_template("sitemap.xml", base_url=base_url, recipes=recipes), encoding="utf-8"
        )
    else:
        sitemap.unlink(missing_ok=True)
    if cache_dir:
        prune_cache(cache_dir, used_cache)
    return len(recipes)


def lint(source: Path) -> int:
    """Check recipe files and their local links without generating a website."""
    return len(load_recipes(source.resolve()))

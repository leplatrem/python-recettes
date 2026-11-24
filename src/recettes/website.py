"""Build and lint a recipe website: pages, pictures and assets."""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import shutil
from collections import Counter
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import quote

import jinja2
from markdown_it.token import Token
from markupsafe import Markup

from recettes import __version__, markdown
from recettes.images import cached_export_image, image_size, output_name, prune_cache
from recettes.quantities import Ingredient, format_amount
from recettes.recipes import (
    Recipe,
    load_recipes,
)
from recettes.utils import (
    DEFAULT_LANG,
    fail,
    natural_key,
    recipes_count,
    slugify,
    strings,
    strip_accents,
)

# Called with the number of pictures published, their total, and the last one's name.
Progress = Callable[[int, int, str], None]

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
    on_picture: Callable[[Path], None] = lambda image: None,
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
        on_picture(image)


def build(
    source: Path,
    destination: Path,
    options: BuildOptions | None = None,
    progress: Progress | None = None,
) -> int:
    """Generate the website in `destination`, and return the number of recipes.

    Resizing pictures takes time: `progress` is called after each one is published.
    """
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
    pictures_total = sum(len(recipe.images) for recipe in recipes)
    pictures_done = 0

    def on_picture(image: Path) -> None:
        nonlocal pictures_done
        pictures_done += 1
        if progress:
            progress(pictures_done, pictures_total, image.name)

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
        export_images(recipe, image_dir, options, used_cache, on_picture)
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


# Rendering of pages with templates.


def quantity(ingredient: Ingredient) -> str:
    """Amount, unit and name of an ingredient ("70 g de beurre")."""
    amount = format_amount(ingredient.amount) if ingredient.amount is not None else ""
    return " ".join(part for part in (amount, ingredient.unit, ingredient.name) if part)


def display_value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(display_value(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, bool):
        return str(value).lower()
    return "" if value is None else str(value)


# Displayed width of recipe page pictures, see `.recipe-page` in the stylesheet.
PICTURE_SIZES = "(min-width: 796px) 760px, calc(100vw - 36px)"
THUMBNAIL_SIZES = "(max-width: 480px) 88px, 112px"


@dataclasses.dataclass
class PictureFiles:
    src: str
    # Lets browsers pick the small version of a picture when it is sharp enough.
    srcset: str
    sizes: str
    # Dimensions, so the browser reserves the picture space before loading it.
    size: tuple[int, int] | None


def picture_files(recipe: Recipe, image: str, root: str, thumbnail: bool) -> PictureFiles:
    """URLs and size of a published picture, from a page at `root`."""
    folder = "thumbnails/" if thumbnail else ""
    url = f"{root}assets/images/{folder}"
    name = quote(image, safe="")
    small = recipe.picture_sizes.get(f"{folder}small/{image}")
    large = recipe.picture_sizes.get(f"{folder}{image}")
    srcset = f"{url}small/{name} {small[0]}w, {url}{name} {large[0]}w" if small and large else ""
    sizes = THUMBNAIL_SIZES if thumbnail else PICTURE_SIZES
    return PictureFiles(src=f"{url}{name}", srcset=srcset, sizes=sizes, size=large)


def gallery_alt(recipe: Recipe, image: str, index: int, lang: str) -> str:
    """Describe a gallery picture with its file name suffix (`soup-bowl.jpg` -> "bowl")."""
    suffix = Path(image).stem[len(recipe.slug) + 1 :].replace("-", " ").replace("_", " ")
    if suffix.strip() and not suffix.isdigit():
        return f"{recipe.title} – {suffix.strip()}"
    return f"{recipe.title}, {strings(lang)['photo']} {index}"


def insert_section_images(recipe: Recipe) -> list[Token]:
    """Append each heading's images at the end of its section (before the next heading)."""
    tokens, section_images = recipe.tokens, recipe.section_images
    headings = markdown.headings(tokens)
    insertions: dict[int, str] = {}
    placed = set()
    for number, (_, text) in enumerate(headings):
        slug = slugify(text)
        if slug not in section_images or slug in placed:
            continue
        placed.add(slug)
        end = headings[number + 1][0] if number + 1 < len(headings) else len(tokens)
        figures = "".join(
            macros().figure(recipe, image, f"{recipe.title} – {text}")
            for image in section_images[slug]
        )
        insertions[end] = f'<div class="recipe-step-images">{figures}</div>\n'
    result = []
    for index, token in enumerate([*tokens, None]):
        if index in insertions:
            block = Token("html_block", "", 0)
            block.content = insertions[index]
            result.append(block)
        if token is not None:
            result.append(token)
    return result


def recipe_content(recipe: Recipe) -> Markup:
    """Recipe text, with its ingredients and section pictures."""
    tokens = insert_section_images(recipe)
    return Markup(markdown.render(tokens, lambda item: macros().ingredient(item, "span")))


def search_text(recipe: Recipe) -> str:
    """Text matched by the home page search."""
    properties = [f"{item.name} {display_value(item.value)}" for item in recipe.properties]
    return " ".join([recipe.title, *recipe.tags, recipe.text, *properties])


@dataclasses.dataclass
class TagCount:
    name: str
    count: int
    # From 1 to 2, to show frequent tags larger.
    weight: float


def tag_counts(recipes: list[Recipe]) -> list[TagCount]:
    """Tags of all recipes, in alphabetical order."""
    counts = Counter(tag for recipe in recipes for tag in recipe.tags)
    highest = max(counts.values(), default=1)
    return [
        TagCount(tag, count, 1 + (count - 1) / highest)
        for tag, count in sorted(
            counts.items(), key=lambda item: natural_key(strip_accents(item[0]))
        )
    ]


def recipe_url(recipe: Recipe) -> str:
    return f"recipes/{quote(recipe.slug, safe='-_')}.html"


def license_html(license: str) -> str:
    """Render the license Markdown for the footer, followed by a separator."""
    license = license.strip()
    return f"{markdown.MARKDOWN.renderInline(license)} —" if license else ""


TEMPLATES = jinja2.Environment(
    loader=jinja2.PackageLoader("recettes", "templates"),
    autoescape=True,
    # Fail on typos rather than rendering nothing.
    undefined=jinja2.StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


TEMPLATES.filters.update(
    display=display_value,
    json=lambda value: json.dumps(value, ensure_ascii=False),
    quantity=quantity,
    urlquote=lambda text: quote(text, safe="-_.!~*()"),
)
# Jinja2 types its globals after its own defaults.
template_globals: dict[str, Any] = TEMPLATES.globals
template_globals.update(
    project_url="https://github.com/leplatrem/python-recettes",
    version=__version__,
    gallery_alt=gallery_alt,
    picture_files=picture_files,
    recipe_url=recipe_url,
    search_text=search_text,
)


def macros() -> Any:
    """Template macros, to call them from Python."""
    return TEMPLATES.get_template("macros.html").module


def render_template(filename: str, /, **context: object) -> str:
    return TEMPLATES.get_template(filename).render(context) + "\n"


def edit_link(edit_url: str | None, path: Path) -> str:
    """URL to edit a recipe on its Git forge."""
    return edit_url.rstrip("/") + "/" + quote(path.name) if edit_url else ""

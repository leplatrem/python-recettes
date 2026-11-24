"""HTML rendering of recipe pages and the home page."""

from __future__ import annotations

import dataclasses
import json
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote

import jinja2
from markdown_it.token import Token
from markupsafe import Markup

from recettes import __version__, i18n, markdown
from recettes.quantities import Ingredient, format_amount
from recettes.recipes import Recipe
from recettes.utils import natural_key, slugify, strip_accents


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
    return f"{recipe.title}, {i18n.strings(lang)['photo']} {index}"


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

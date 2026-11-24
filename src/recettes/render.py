"""HTML rendering of recipe pages and the home page."""

from __future__ import annotations

import dataclasses
import html
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


def attr(value: object) -> str:
    return html.escape(str(value), quote=True)


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


def recipe_card_html(recipe: Recipe) -> str:
    """Home page card, with the data used to filter it."""
    lang = f' lang="{attr(recipe.lang)}"' if recipe.lang else ""
    classes = "recipe-card has-image" if recipe.main_image else "recipe-card"
    excerpt = f'<p class="card-excerpt">{html.escape(recipe.excerpt)}</p>' if recipe.excerpt else ""
    tags = "".join(f'<span class="tag">{html.escape(tag)}</span>' for tag in recipe.tags)
    image = (
        macros().picture(
            recipe, recipe.main_image, "", root="", thumbnail=True, **{"class": "card-image"}
        )
        if recipe.main_image
        else ""
    )
    return (
        f'<article class="{classes}"{lang} data-search="{attr(search_text(recipe))}" '
        f'data-tags="{attr(json.dumps(recipe.tags, ensure_ascii=False))}">'
        f'<a href="{attr(recipe_url(recipe))}">'
        f'<div class="card-body"><h2>{html.escape(recipe.title)}</h2>{excerpt}'
        f'<div class="recipe-tags">{tags}</div></div>'
        f'{image}<span class="card-arrow" aria-hidden="true">↗</span></a></article>'
    )


def tag_cloud_html(recipes: list[Recipe]) -> str:
    """Buttons to filter recipes by tag, larger for frequent tags."""
    counts = Counter(tag for recipe in recipes for tag in recipe.tags)
    highest = max(counts.values(), default=1)
    return "".join(
        f'<button class="tag-cloud-item" type="button" aria-pressed="false" '
        f'data-tag="{attr(tag)}" style="--tag-weight: {1 + (count - 1) / highest:.3g}">'
        f"<span>{html.escape(tag)}</span><span data-tag-count>{count}</span></button>"
        for tag, count in sorted(
            counts.items(), key=lambda item: natural_key(strip_accents(item[0]))
        )
    )


def recipe_url(recipe: Recipe) -> str:
    return f"recipes/{quote(recipe.slug, safe='-_')}.html"


def meta_tags(
    title: str,
    page_type: str,
    site_name: str,
    base_url: str | None,
    path: str,
    lang: str,
    description: str = "",
    image: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Description, canonical URL and Open Graph tags.

    The last two need the base URL of the website, since they are absolute.
    """
    tags_html = []
    if description:
        tags_html.append(f'<meta name="description" content="{attr(description)}">')
    if base_url:
        base = base_url.rstrip("/") + "/"
        tags_html.append(f'<link rel="canonical" href="{attr(base + path)}">')
        tags_html.append(
            f'<meta name="twitter:card" content="{"summary_large_image" if image else "summary"}">'
        )
        properties = [
            ("og:title", title),
            ("og:type", page_type),
            ("og:site_name", site_name),
            ("og:url", base + path),
            # Open Graph locales use underscores ("fr_CA").
            ("og:locale", lang.replace("-", "_")),
        ]
        if description:
            properties.append(("og:description", description))
        if image:
            properties.append(("og:image", base + f"assets/images/{quote(image, safe='')}"))
        properties += [("article:tag", tag) for tag in tags or []]
        tags_html += [
            f'<meta property="{name}" content="{attr(value)}">' for name, value in properties
        ]
    return "\n    ".join(tags_html)


def sitemap_xml(base_url: str, recipes: list[Recipe]) -> str:
    """List of the website pages, for search engines."""
    base = base_url.rstrip("/") + "/"
    urls = [base, *(base + recipe_url(recipe) for recipe in recipes)]
    entries = "".join(f"  <url><loc>{html.escape(url)}</loc></url>\n" for url in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}</urlset>\n"
    )


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
    quantity=quantity,
    urlquote=lambda text: quote(text, safe="-_.!~*()"),
)
# Jinja2 types its globals after its own defaults.
template_globals: dict[str, Any] = TEMPLATES.globals
template_globals.update(gallery_alt=gallery_alt, picture_files=picture_files)


def macros() -> Any:
    """Template macros, to call them from Python."""
    return TEMPLATES.get_template("macros.html").module


def render_template(filename: str, /, **context: object) -> str:
    return TEMPLATES.get_template(filename).render(context) + "\n"


PROJECT_URL = "https://github.com/leplatrem/python-recettes"


def interface_values(lang: str) -> dict[str, Markup]:
    """Translated interface strings, as `t_*` template values."""
    strings = i18n.strings(lang)
    values = {f"t_{name}": Markup(attr(text)) for name, text in strings.items()}
    link = f'<a href="{PROJECT_URL}">Recettes v{attr(__version__)}</a>'
    values["t_built_with"] = Markup(attr(strings["built_with"]).replace("{recettes}", link))
    return values


def edit_link(edit_url: str | None, path: Path) -> str:
    """URL to edit a recipe on its Git forge."""
    return edit_url.rstrip("/") + "/" + quote(path.name) if edit_url else ""

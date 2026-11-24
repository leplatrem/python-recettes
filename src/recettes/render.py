"""HTML rendering of recipe pages and the home page."""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from markdown_it.token import Token

from recettes import i18n, markdown
from recettes.quantities import Ingredient, format_amount
from recettes.recipes import Recipe
from recettes.text import natural_key, slugify, strip_accents

if TYPE_CHECKING:  # Python 3.11+
    from importlib.resources.abc import Traversable


def attr(value: object) -> str:
    return html.escape(str(value), quote=True)


def ingredient_html(ingredient: Ingredient, tag: str) -> str:
    amount, unit, name, ml = ingredient.amount, ingredient.unit, ingredient.name, ingredient.ml
    if amount is None:
        return f"<{tag} data-ingredient>{html.escape(name or ingredient.raw)}</{tag}>"
    text = " ".join(part for part in (format_amount(amount), unit, name) if part)
    volume = f' data-ml="{attr(round(ml, 2))}"' if ml is not None else ""
    return (
        f'<{tag} data-ingredient data-amount="{attr(float(amount))}" '
        f'data-unit="{attr(unit)}" data-name="{attr(name)}"{volume}>{html.escape(text)}</{tag}>'
    )


def display_value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(display_value(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, bool):
        return str(value).lower()
    return "" if value is None else str(value)


# Front matter properties holding a duration: plain numbers are minutes.
DURATION_PROPERTIES = {
    *("preparation", "cooking", "resting", "rest", "baking", "total"),
    *("préparation", "cuisson", "repos", "attente"),
    *("preparazione", "cottura", "riposo"),
    *("preparación", "cocción", "reposo"),
}


def property_name(name: str) -> str:
    """Human-friendly property name ("cooking_time" -> "Cooking time")."""
    text = name.replace("_", " ")
    return text[:1].upper() + text[1:]


def property_value(name: str, value: object) -> str:
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if name.casefold() in DURATION_PROPERTIES and is_number:
        return f"{display_value(value)} min"
    return display_value(value)


def size_attributes(recipe: Recipe, path: str) -> str:
    """Picture dimensions, so the browser reserves its space before loading it."""
    size = recipe.picture_sizes.get(path)
    return f' width="{size[0]}" height="{size[1]}"' if size else ""


# Displayed width of recipe page pictures, see `.recipe-page` in the stylesheet.
PICTURE_SIZES = "(min-width: 796px) 760px, calc(100vw - 36px)"
THUMBNAIL_SIZES = "(max-width: 480px) 88px, 112px"


def srcset_attributes(recipe: Recipe, folder: str, url: str, image: str, sizes: str) -> str:
    """Let browsers pick the small version of a picture when it is sharp enough.

    `folder` is the picture folder within the images folder, `url` the URL of the latter.
    """
    small, large = (
        recipe.picture_sizes.get(f"{path}{image}") for path in (f"{folder}small/", folder)
    )
    if not (small and large):
        return ""
    name = quote(image, safe="")
    srcset = f"{url}{folder}small/{name} {small[0]}w, {url}{folder}{name} {large[0]}w"
    return f' srcset="{attr(srcset)}" sizes="{sizes}"'


def image_html(recipe: Recipe, image: str, alt: str, lazy: bool = True) -> str:
    loading = ' loading="lazy"' if lazy else ""
    src = f"../assets/images/{quote(image, safe='')}"
    srcset = srcset_attributes(recipe, "", "../assets/images/", image, PICTURE_SIZES)
    dimensions = size_attributes(recipe, image)
    return f'<img{loading} src="{attr(src)}"{srcset}{dimensions} alt="{attr(alt)}">'


def gallery_alt(recipe: Recipe, image: str, index: int, lang: str) -> str:
    """Describe a gallery picture with its file name suffix (`soup-bowl.jpg` -> "bowl")."""
    suffix = Path(image).stem[len(recipe.slug) + 1 :].replace("-", " ").replace("_", " ")
    if suffix.strip() and not suffix.isdigit():
        return f"{recipe.title} – {suffix.strip()}"
    return f"{recipe.title}, {i18n.strings(lang)['photo']} {index}"


def figure_html(recipe: Recipe, image: str, alt: str) -> str:
    return f"<figure>{image_html(recipe, image, alt)}</figure>"


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
            figure_html(recipe, image, f"{recipe.title} – {text}") for image in section_images[slug]
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


def recipe_html_parts(recipe: Recipe, lang: str) -> dict[str, str]:
    tags = "".join(
        f'<a class="tag" href="../index.html?tag={attr(quote(tag, safe="-_.!~*()"))}">'
        f"{html.escape(tag)}</a>"
        for tag in recipe.tags
    )
    properties = "".join(
        f'<div class="recipe-property"><dt>{html.escape(property_name(item.name))}</dt>'
        f"<dd>{html.escape(property_value(item.name, item.value))}</dd></div>"
        for item in recipe.properties
    )
    title = recipe.title
    gallery = "".join(
        figure_html(recipe, image, gallery_alt(recipe, image, index, lang))
        for index, image in enumerate(recipe.gallery, 1)
    )
    main = (
        f'<figure class="recipe-main-image">'
        f"{image_html(recipe, recipe.main_image, title, lazy=False)}</figure>"
        if recipe.main_image
        else ""
    )
    tokens = insert_section_images(recipe)
    portions = recipe.portions
    return {
        "tags": tags,
        "properties": properties,
        "properties_hidden": "" if properties else " hidden",
        "servings_attrs": f' data-portions="{portions}"' if portions else " hidden",
        "simple_hidden": ("" if any(item.ml for item in recipe.ingredients) else " hidden"),
        "portions": str(portions or ""),
        "ingredient_list": "".join(ingredient_html(item, "li") for item in recipe.ingredient_list),
        "gallery": gallery,
        "main_image": main,
        "content": markdown.render(tokens, lambda item: ingredient_html(item, "span")),
    }


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
    image = ""
    if recipe.main_image:
        name = recipe.main_image
        image = (
            f'<img class="card-image" src="{attr(thumbnail_url(name))}"'
            f"{srcset_attributes(recipe, 'thumbnails/', 'assets/images/', name, THUMBNAIL_SIZES)}"
            f'{size_attributes(recipe, f"thumbnails/{name}")} alt="" loading="lazy">'
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


def thumbnail_url(image: str) -> str:
    return f"assets/images/thumbnails/{quote(image, safe='')}"


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


PARTIAL_RE = re.compile(r"^\{\{> ([\w.-]+) \}\}\n", re.M)
PLACEHOLDER_RE = re.compile(r"\{\{ (\w+) \}\}")


def render_template(templates: Traversable, filename: str, /, **values: str) -> str:
    """Fill a template: `{{> file }}` includes a partial, `{{ name }}` inserts a value.

    Values are inserted in a single pass, so they are never scanned for placeholders.
    """

    def include(match: re.Match[str]) -> str:
        return (templates / "partials" / match.group(1)).read_text(encoding="utf-8")

    def value(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise KeyError(f"Missing value '{name}' for template {filename}")
        return values[name]

    template = PARTIAL_RE.sub(include, (templates / filename).read_text(encoding="utf-8"))
    return PLACEHOLDER_RE.sub(value, template)


PROJECT_URL = "https://github.com/leplatrem/python-recettes"


def interface_values(lang: str) -> dict[str, str]:
    """Translated interface strings, as `t_*` template values."""
    values = {f"t_{name}": attr(text) for name, text in i18n.strings(lang).items()}
    link = f'<a href="{PROJECT_URL}">Recettes</a>'
    values["t_built_with"] = values["t_built_with"].replace("{recettes}", link)
    return values


def edit_link(edit_url: str | None, path: Path, lang: str) -> str:
    if not edit_url:
        return ""
    url = edit_url.rstrip("/") + "/" + quote(path.name)
    label = attr(i18n.strings(lang)["edit"])
    return (
        f'<a href="{attr(url)}" aria-label="{label}" title="{label}" target="_blank" '
        'rel="noopener">✎</a>'
    )

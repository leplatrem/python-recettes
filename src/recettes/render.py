"""HTML rendering of recipe pages and the home page."""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote

from markdown_it.token import Token

from recettes import markdown
from recettes.quantities import Ingredient, format_amount
from recettes.recipes import Recipe
from recettes.text import slugify


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
    if name.casefold() in DURATION_PROPERTIES and isinstance(value, (int, float)):
        if not isinstance(value, bool):
            return f"{display_value(value)} min"
    return display_value(value)


def image_html(image: str, alt: str, lazy: bool = True) -> str:
    loading = ' loading="lazy"' if lazy else ""
    src = f"../assets/images/{quote(image, safe='')}"
    return f'<img{loading} src="{attr(src)}" alt="{attr(alt)}">'


def figure_html(image: str, alt: str) -> str:
    return f"<figure>{image_html(image, alt)}</figure>"


def insert_section_images(
    tokens: list[Token], section_images: dict[str, list[str]], title: str
) -> list[Token]:
    """Append each heading's images at the end of its section (before the next heading)."""
    headings = markdown.headings(tokens)
    insertions: dict[int, str] = {}
    placed = set()
    for number, (index, text) in enumerate(headings):
        slug = slugify(text)
        if slug not in section_images or slug in placed:
            continue
        placed.add(slug)
        end = headings[number + 1][0] if number + 1 < len(headings) else len(tokens)
        figures = "".join(figure_html(image, f"{title} – {text}") for image in section_images[slug])
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


def recipe_html_parts(recipe: Recipe) -> dict[str, str]:
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
        figure_html(image, f"{title} {index}") for index, image in enumerate(recipe.gallery, 1)
    )
    main = (
        f'<figure class="recipe-main-image">'
        f"{image_html(recipe.main_image, title, lazy=False)}</figure>"
        if recipe.main_image
        else ""
    )
    tokens = insert_section_images(recipe.tokens, recipe.section_images, title)
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


def recipe_index_data(recipes: list[Recipe]) -> str:
    entries = []
    for recipe in recipes:
        search_terms = [
            recipe.title,
            *recipe.tags,
            recipe.text,
            *(f"{item.name} {item.value}" for item in recipe.properties),
        ]
        entries.append(
            {
                "slug": recipe.slug,
                "title": recipe.title,
                "tags": recipe.tags,
                "excerpt": recipe.excerpt,
                "search": " ".join(search_terms),
                "lang": recipe.lang,
                "image": (
                    f"assets/images/thumbnails/{quote(recipe.main_image, safe='')}"
                    if recipe.main_image
                    else None
                ),
            }
        )
    return json.dumps(entries, ensure_ascii=False)


def meta_tags(
    title: str,
    page_type: str,
    site_name: str,
    base_url: str | None,
    path: str,
    description: str = "",
    image: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Description and Open Graph tags; the latter need a base URL, since og:url is absolute."""
    tags_html = []
    if description:
        tags_html.append(f'<meta name="description" content="{attr(description)}">')
    if base_url:
        base = base_url.rstrip("/") + "/"
        properties = [
            ("og:title", title),
            ("og:type", page_type),
            ("og:site_name", site_name),
            ("og:url", base + path),
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


def license_html(license: str) -> str:
    """Render the license Markdown for the footer, followed by a separator."""
    license = license.strip()
    return f"{markdown.MARKDOWN.renderInline(license)} —" if license else ""


def render_template(path: Path, **values: str) -> str:
    template = path.read_text(encoding="utf-8")
    for name, value in values.items():
        template = template.replace("{{ " + name + " }}", value)
    return template


def edit_link(edit_url: str | None, path: Path) -> str:
    if not edit_url:
        return ""
    url = edit_url.rstrip("/") + "/" + quote(path.name)
    return f'<a href="{attr(url)}" aria-label="Edit" title="Edit" target="_blank">✎</a>'

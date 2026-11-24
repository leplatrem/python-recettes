from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import unicodedata
from fractions import Fraction
from functools import cache
from pathlib import Path
from typing import Annotated, NoReturn
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import click
import frontmatter
import typer
from markdown_it import MarkdownIt

from recettes.images import cached_export_image, output_name, prune_cache

app = typer.Typer(no_args_is_help=True, help="Build a static recipe website from Markdown.")

INGREDIENT_RE = re.compile(r"\{\{\s*(.*?)\s*\}\}")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
QUANTITY_RE = re.compile(
    r"^(?P<amount>\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)?)"
    r"\s*(?P<unit>(?:c\.?\s*à\.?\s*[sc]\.?|cas|càs|cac|càc|"
    r"cucchiain[oi]|cucchiaio?|"
    r"cdita|cda|cc|ct|tl|el|tsk|msk|ts|ss|fl[_ ]?oz|tablespoons?|tbsp|teaspoons?|tsp|cups?|"
    r"ounces?|oz|pounds?|lbs?|kg|mg|g|ml|cl|l)(?![^\W\d_]))?\s*(?P<name>.*)$",
    re.IGNORECASE,
)
TOKEN_RE = re.compile(r"RECIPEINGREDIENTTOKEN(\d+)END")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".heic", ".heif"}
HEADING_RE = re.compile(r"<h([1-6])>(.*?)</h\1>", re.S)
MARKDOWN = MarkdownIt("default", {"html": False, "typographer": True})
# Defaults are twice the stylesheet sizes (recipe page column width, home page card
# thumbnail), so pictures stay sharp on high-density (retina) screens.
DEFAULT_IMAGE_WIDTH = 2 * 760
DEFAULT_THUMBNAIL_WIDTH = 2 * 112
DEFAULT_LICENSE = "[Copyrights CC-BY](https://creativecommons.org/licenses/by/4.0/)"
# Conversions to milliliters or grams, used by the "Simple" mode (glasses and spoons).
VOLUME_UNITS_ML = {
    "ml": 1,
    "cl": 10,
    "l": 1000,
    "cups": 240,
    "fl oz": 29.57,
    **dict.fromkeys(
        ["tbsp", "c. à s.", "EL", "cda", "Cc", "CC", "cucchiaio", "cucchiai", "msk", "ss"], 15
    ),
    **dict.fromkeys(
        ["tsp", "c. à c.", "TL", "cdita", "cc", "ct", "cucchiaino", "cucchiaini", "tsk", "ts"], 5
    ),
}
MASS_UNITS_G = {"mg": 0.001, "g": 1, "kg": 1000, "oz": 28.35, "lb": 453.6}


@app.callback()
def main() -> None:
    """Build and maintain a static recipe website."""


class RecettesError(click.ClickException):
    """Invalid recipes or options: shown to the user without a traceback."""


def fail(message: str) -> NoReturn:
    raise RecettesError(message)


def parse_quantity(value: str) -> tuple[float | None, str, str]:
    match = QUANTITY_RE.fullmatch(value.strip())
    if not match:
        return None, "", value.strip()
    amount_text = match.group("amount").replace(" ", "").replace(",", ".")
    try:
        amount = float(Fraction(amount_text))
    except (ValueError, ZeroDivisionError):
        return None, "", value.strip()
    raw_unit = (match.group("unit") or "").replace(" ", "").replace(".", "")
    normalized_unit = raw_unit.lower()
    unit_map = {
        "cas": "c. à s.",
        "càs": "c. à s.",
        "cac": "c. à c.",
        "càc": "c. à c.",
        "tl": "TL",
        "el": "EL",
        "fl_oz": "fl oz",
        "floz": "fl oz",
        "tablespoon": "tbsp",
        "tablespoons": "tbsp",
        "teaspoon": "tsp",
        "teaspoons": "tsp",
        "cup": "cups",
        "ounce": "oz",
        "ounces": "oz",
        "pound": "lb",
        "pounds": "lb",
        "lbs": "lb",
    }
    unit = unit_map.get(normalized_unit, raw_unit if normalized_unit == "cc" else normalized_unit)
    return amount, unit, match.group("name").strip()


def name_words(text: str) -> tuple[str, ...]:
    """Lowercase words without accents nor plural "s" ("Pépites de chocolat" -> pepite, de...)."""
    normalized = unicodedata.normalize("NFKD", text.casefold())
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    words = re.findall(r"[a-z0-9]+", ascii_text)
    return tuple(word[:-1] if len(word) > 3 and word.endswith("s") else word for word in words)


@cache
def densities() -> list[tuple[tuple[str, ...], float]]:
    """Known ingredient names (as words) with their density, longest names first."""
    path = Path(__file__).parent / "densities.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    names = [
        (name_words(name), float(entry["density"]))
        for entry in entries.values()
        for name in entry["names"]
    ]
    return sorted(names, key=lambda item: (len(item[0]), len(" ".join(item[0]))), reverse=True)


def find_density(name: str) -> float | None:
    words = name_words(name)
    for candidate, density in densities():
        size = len(candidate)
        if any(words[i : i + size] == candidate for i in range(len(words) - size + 1)):
            return density
    return None


def volume_ml(amount: float | None, unit: str, name: str, lang: str = "") -> float | None:
    """Volume of an ingredient in milliliters, if it can be measured with glasses and spoons."""
    if amount is None:
        return None
    # "cc" is a teaspoon in French ("cuillère à café"), but cubic centimeters in English.
    if unit == "cc" and lang.casefold().startswith("en"):
        return amount
    if unit in VOLUME_UNITS_ML:
        return amount * VOLUME_UNITS_ML[unit]
    if unit in MASS_UNITS_G:
        density = find_density(name)
        if density is not None:
            return amount * MASS_UNITS_G[unit] / density
    return None


def parse_tags(value: object) -> list[str]:
    if isinstance(value, str):
        tags = value.split(",")
    elif isinstance(value, list):
        tags = [str(tag) for tag in value]
    else:
        return []
    return [tag.strip() for tag in tags if tag.strip()]


def aggregate_ingredients(ingredients: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], dict[str, object]] = {}
    for ingredient in ingredients:
        amount = ingredient["amount"]
        unit = str(ingredient["unit"])
        name = str(ingredient["name"])
        normalized_name = " ".join(name.casefold().split())
        if amount is None:
            key = ("plain", normalized_name)
        elif normalized_name:
            key = (unit, normalized_name)
        else:
            key = (unit, "")
        if key not in grouped:
            grouped[key] = dict(ingredient)
        elif amount is not None:
            grouped[key]["amount"] = float(grouped[key]["amount"]) + float(amount)
    return list(grouped.values())


def markdown_with_ingredients(markdown: str) -> tuple[str, list[dict[str, object]]]:
    ingredients: list[dict[str, object]] = []

    def replace(match: re.Match[str]) -> str:
        raw = match.group(1).strip()
        amount, unit, name = parse_quantity(raw)
        ingredients.append({"amount": amount, "unit": unit, "name": name, "raw": raw})
        return f"RECIPEINGREDIENTTOKEN{len(ingredients) - 1}END"

    rendered = MARKDOWN.render(INGREDIENT_RE.sub(replace, markdown))
    return rendered, ingredients


def plain_text(markdown: str) -> str:
    """Text of the recipe without markup, ingredients written as in the source."""
    parts = []
    for token in MARKDOWN.parse(markdown):
        if token.type in {"fence", "code_block"}:
            parts.append(token.content)
        for child in token.children or []:
            if child.type in {"text", "code_inline"}:
                parts.append(child.content)
            elif child.type in {"softbreak", "hardbreak"}:
                parts.append(" ")
        parts.append(" ")
    text = INGREDIENT_RE.sub(lambda match: match.group(1), "".join(parts))
    return " ".join(text.split())


def first_paragraph(markdown: str, limit: int = 180) -> str:
    tokens = MARKDOWN.parse(markdown)
    for index, token in enumerate(tokens):
        if token.type != "paragraph_open":
            continue
        inline = tokens[index + 1]
        if inline.type != "inline":
            continue
        parts = []
        for child in inline.children or []:
            if child.type in {"text", "code_inline", "image"}:
                parts.append(child.content)
            elif child.type in {"softbreak", "hardbreak"}:
                parts.append(" ")
        text = "".join(parts)
        text = INGREDIENT_RE.sub(lambda match: match.group(1), text)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            return text[:limit].rstrip()
    return ""


def slugify(text: str) -> str:
    """Turn a heading into a filename-friendly slug ("Étape 1" -> "etape-1")."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.casefold()).strip("-")


def natural_key(name: str) -> list[object]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name.casefold())]


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


def heading_text(content: str) -> str:
    text = TOKEN_RE.sub("", re.sub(r"<[^>]*>", "", content))
    return html.unescape(" ".join(text.split()))


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


def rewrite_local_links(content: str, source_path: Path, targets: dict[Path, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        attribute, url = match.group(1), html.unescape(match.group(2))
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or parsed.path.startswith("/") or not parsed.path:
            return match.group(0)

        target_path = (source_path.parent / unquote(parsed.path)).resolve()
        candidates = [target_path]
        if target_path.suffix in ("", ".html"):
            candidates.append(target_path.with_suffix(".md"))
        target = next((targets[path] for path in candidates if path in targets), None)
        if target is None:
            fail(
                f"Recipe '{source_path.name}' links to missing file '{url}'. "
                "Link to another recipe's Markdown file, or to a photo named "
                "<recipe>.<ext> or <recipe>-<suffix>.<ext>."
            )

        target_url = urlunsplit(("", "", target, parsed.query, parsed.fragment))
        return f'{attribute}="{html.escape(target_url, quote=True)}"'

    return re.sub(r'\b(href|src)="([^"]*)"', replace, content)


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
) -> dict[str, object]:
    try:
        document = frontmatter.load(path)
    except (OSError, ValueError) as exc:
        fail(f"Could not read recipe '{path.name}': {exc}")
    metadata = document.metadata
    portions = parse_portions(metadata.get("portions"))
    lang = str(metadata.get("lang", ""))

    title = str(metadata.get("title") or path.stem.replace("-", " ").title())
    slug = path.stem
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
            amount, unit = ingredient["amount"], str(ingredient["unit"])
            ingredient["ml"] = volume_ml(amount, unit, str(ingredient["name"]), lang)
        for ingredient in ingredient_list:
            if ingredient["unit"] in MASS_UNITS_G and ingredient["ml"] is None:
                typer.echo(
                    f"Warning: '{path.name}': unknown density for '{ingredient['name']}', "
                    "Simple mode will keep the weight",
                    err=True,
                )

    excluded = {"title", "tags"}
    if portions is not None or metadata.get("portions") in (None, ""):
        excluded.add("portions")
    properties = [
        {"name": str(key), "value": value} for key, value in metadata.items() if key not in excluded
    ]
    return {
        "slug": slug,
        "title": title,
        "lang": lang,
        "tags": parse_tags(metadata.get("tags")),
        "properties": properties,
        "excerpt": first_paragraph(body),
        "text": plain_text(body),
        "portions": portions,
        "ingredients": ingredients,
        "ingredient_list": ingredient_list,
        "content": content,
        "main_image": main_image,
        "section_images": section_images,
        "gallery": gallery,
    }


def attr(value: object) -> str:
    return html.escape(str(value), quote=True)


def format_amount(amount: float) -> str:
    return f"{round(amount, 2):.2f}".rstrip("0").rstrip(".")


def ingredient_html(ingredient: dict[str, object], tag: str) -> str:
    amount = ingredient["amount"]
    if amount is None:
        text = str(ingredient["name"] or ingredient["raw"])
        return f"<{tag} data-ingredient>{html.escape(text)}</{tag}>"
    unit, name = str(ingredient["unit"]), str(ingredient["name"])
    text = " ".join(part for part in (format_amount(float(amount)), unit, name) if part)
    ml = ingredient.get("ml")
    volume = f' data-ml="{attr(round(ml, 2))}"' if ml is not None else ""
    return (
        f'<{tag} data-ingredient data-amount="{attr(float(amount))}" '
        f'data-unit="{attr(unit)}" data-name="{attr(name)}"{volume}>{html.escape(text)}</{tag}>'
    )


def insert_ingredients(content: str, ingredients: list[dict[str, object]]) -> str:
    def replace(match: re.Match[str]) -> str:
        return ingredient_html(ingredients[int(match.group(1))], "span")

    # Only substitute in text, never inside tags/attributes (e.g. image alt text).
    parts = re.split(r"(<[^>]*>)", content)
    return "".join(part if part.startswith("<") else TOKEN_RE.sub(replace, part) for part in parts)


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


def insert_section_images(content: str, section_images: dict[str, list[str]], title: str) -> str:
    """Append each heading's images at the end of its section (before the next heading)."""
    if not section_images:
        return content
    headings = list(HEADING_RE.finditer(content))
    insertions: dict[int, str] = {}
    placed = set()
    for index, heading in enumerate(headings):
        text = heading_text(heading.group(2))
        slug = slugify(text)
        if slug not in section_images or slug in placed:
            continue
        placed.add(slug)
        end = headings[index + 1].start() if index + 1 < len(headings) else len(content)
        figures = "".join(figure_html(image, f"{title} – {text}") for image in section_images[slug])
        insertions[end] = f'<div class="recipe-step-images">{figures}</div>\n'
    for position in sorted(insertions, reverse=True):
        content = content[:position] + insertions[position] + content[position:]
    return content


def recipe_html_parts(recipe: dict[str, object]) -> dict[str, str]:
    tags = "".join(
        f'<a class="tag" href="../index.html?tag={attr(quote(tag, safe="-_.!~*()"))}">'
        f"{html.escape(tag)}</a>"
        for tag in recipe["tags"]
    )
    properties = "".join(
        f'<div class="recipe-property"><dt>{html.escape(property_name(str(item["name"])))}</dt>'
        f"<dd>{html.escape(property_value(str(item['name']), item['value']))}</dd></div>"
        for item in recipe["properties"]
    )
    title = str(recipe["title"])
    gallery = "".join(
        figure_html(image, f"{title} {index}") for index, image in enumerate(recipe["gallery"], 1)
    )
    main_image = recipe["main_image"]
    main = (
        f'<figure class="recipe-main-image">{image_html(main_image, title, lazy=False)}</figure>'
        if main_image
        else ""
    )
    content = insert_section_images(str(recipe["content"]), recipe["section_images"], title)
    portions = recipe["portions"]
    return {
        "tags": tags,
        "properties": properties,
        "properties_hidden": "" if properties else " hidden",
        "servings_attrs": f' data-portions="{portions}"' if portions else " hidden",
        "simple_hidden": (
            "" if any(item.get("ml") for item in recipe["ingredients"]) else " hidden"
        ),
        "portions": str(portions or ""),
        "ingredient_list": "".join(
            ingredient_html(item, "li") for item in recipe["ingredient_list"]
        ),
        "gallery": gallery,
        "main_image": main,
        # Last: inserted recipe content must not be scanned for other placeholders.
        "content": insert_ingredients(content, recipe["ingredients"]),
    }


def recipe_index_data(recipes: list[dict[str, object]]) -> str:
    entries = []
    for recipe in recipes:
        search_terms = [
            str(recipe["title"]),
            *recipe["tags"],
            str(recipe["text"]),
            *(f"{property_['name']} {property_['value']}" for property_ in recipe["properties"]),
        ]
        entries.append(
            {
                "slug": recipe["slug"],
                "title": recipe["title"],
                "tags": recipe["tags"],
                "excerpt": recipe["excerpt"],
                "search": " ".join(search_terms),
                "lang": recipe["lang"],
                "image": (
                    f"assets/images/thumbnails/{quote(str(recipe['main_image']), safe='')}"
                    if recipe["main_image"]
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
    return f"{MARKDOWN.renderInline(license)} —" if license else ""


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


def ci_edit_url(source: Path) -> str | None:
    """Guess the edit URL of the recipes folder from GitHub Actions or GitLab CI variables."""
    env = os.environ
    if env.get("GITHUB_ACTIONS"):
        repo_url = f"{env.get('GITHUB_SERVER_URL')}/{env.get('GITHUB_REPOSITORY')}"
        edit, ref, workspace = "edit", env.get("GITHUB_REF_NAME"), env.get("GITHUB_WORKSPACE")
    elif env.get("GITLAB_CI"):
        repo_url = env.get("CI_PROJECT_URL")
        edit, ref, workspace = "-/edit", env.get("CI_COMMIT_REF_NAME"), env.get("CI_PROJECT_DIR")
    else:
        return None
    if not (repo_url and ref and workspace):
        return None
    try:
        folder = source.resolve().relative_to(Path(workspace).resolve()).as_posix()
    except ValueError:
        return None
    return "/".join(part for part in (repo_url, edit, ref, folder) if part not in ("", "."))


def ci_base_url() -> str | None:
    """Guess the default GitHub Pages URL of the repository when building on GitHub Actions.

    Sites published on a custom domain must pass their URL explicitly.
    """
    env = os.environ
    repository = env.get("GITHUB_REPOSITORY", "")
    if not env.get("GITHUB_ACTIONS") or env.get("GITHUB_SERVER_URL") != "https://github.com":
        return None
    owner, _, name = repository.partition("/")
    if not (owner and name):
        return None
    host = f"{owner.lower()}.github.io"
    # A repository named after the Pages host is served at the root.
    return f"https://{host}/" if name.lower() == host else f"https://{host}/{name}/"


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
    if not source.is_dir():
        fail(f"Recipe directory does not exist: {source}")
    if source == destination or source in destination.parents:
        fail("Output directory must be outside the recipe source directory")
    paths = sorted(path for path in source.glob("*.md") if path.is_file())
    if not paths:
        fail(f"No Markdown recipes found in {source}")
    # Only the top level of the source directory is read, so the cache can be a subdirectory.
    if cache_dir and (
        cache_dir == source or cache_dir == destination or destination in cache_dir.parents
    ):
        fail("Cache directory must be outside the output directory")

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
    recipes = []
    images = assign_images(source, {path.stem for path in paths})
    link_targets = local_link_targets(paths, images)
    used_cache: set[Path] = set()
    for path in paths:
        slug = path.stem
        recipe = recipe_page(
            path,
            image_dir,
            link_targets,
            images[path.stem],
            image_width,
            thumbnail_width,
            simple_mode,
            cache_dir,
            used_cache,
        )
        recipes.append(recipe)
        page = render_template(
            templates / "recipe.html",
            title=html.escape(str(recipe["title"])),
            lang=html.escape(str(recipe["lang"]), quote=True),
            edit_link=edit_link(edit_url, path),
            meta_tags=meta_tags(
                str(recipe["title"]),
                "article",
                title,
                base_url,
                f"recipes/{quote(slug, safe='-_')}.html",
                str(recipe["excerpt"]),
                recipe["main_image"],
                recipe["tags"],
            ),
            license=footer_license,
            **versions,
            **recipe_html_parts(recipe),
        )
        (recipes_dir / f"{slug}.html").write_text(page, encoding="utf-8")
    prefetch_links = "\n    ".join(
        f'<link rel="prefetch" href="recipes/{quote(str(recipe["slug"]), safe="-_")}.html">'
        for recipe in recipes
    )
    index_data = recipe_index_data(recipes)
    versions["recipes_json_version"] = hashlib.sha256(index_data.encode()).hexdigest()[:10]
    languages = {str(recipe["lang"]) for recipe in recipes if recipe["lang"]}
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
    source = source.resolve()
    if not source.is_dir():
        fail(f"Recipe directory does not exist: {source}")
    paths = sorted(path for path in source.glob("*.md") if path.is_file())
    if not paths:
        fail(f"No Markdown recipes found in {source}")
    images = assign_images(source, {path.stem for path in paths})
    link_targets = local_link_targets(paths, images)
    for path in paths:
        try:
            document = frontmatter.load(path)
        except (OSError, ValueError) as exc:
            fail(f"Could not read recipe '{path.name}': {exc}")
        body = HTML_COMMENT_RE.sub("", document.content)
        content, _ = markdown_with_ingredients(body)
        rewrite_local_links(content, path, link_targets)
    return len(paths)


@app.command("lint")
def lint_command(
    source: Annotated[Path, typer.Argument(help="Directory containing recipe Markdown files")],
) -> None:
    """Check recipe content and local links without building the website."""
    count = lint(source)
    typer.echo(f"Checked {count} recipes in {source}")


@app.command("build")
def build_command(
    source: Annotated[Path, typer.Argument(help="Directory containing recipe Markdown files")],
    destination: Annotated[
        Path, typer.Option("--destination", "-d", help="Generated website directory")
    ] = Path("site"),
    title: Annotated[str, typer.Option("--title", help="Title for the home page")] = "Recipes",
    edit_url: Annotated[
        str | None,
        typer.Option(
            "--edit-url",
            help="Base URL to edit recipe files on a Git forge; the filename is appended. "
            "Guessed automatically on GitHub Actions and GitLab CI",
        ),
    ] = None,
    image_width: Annotated[
        int,
        typer.Option(
            "--image-width", min=1, help="Downscale recipe pictures wider than this (pixels)"
        ),
    ] = DEFAULT_IMAGE_WIDTH,
    thumbnail_width: Annotated[
        int,
        typer.Option(
            "--thumbnail-width", min=1, help="Size of the square home page thumbnails (pixels)"
        ),
    ] = DEFAULT_THUMBNAIL_WIDTH,
    simple_mode: Annotated[
        bool,
        typer.Option(
            "--simple-mode/--no-simple-mode",
            help="Offer a switch to measure ingredients with glasses and spoons instead of a scale",
        ),
    ] = True,
    cache_dir: Annotated[
        Path,
        typer.Option(
            "--cache-dir",
            envvar="RECETTES_CACHE_DIR",
            help="Keep resized pictures in this directory, so unchanged ones are not "
            "processed again on the next build",
        ),
    ] = Path(".recettes-cache"),
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            envvar="RECETTES_BASE_URL",
            help="Public URL of the website, used for absolute links in Open Graph tags "
            "(link previews in social networks and messaging apps). "
            "Defaults to the GitHub Pages URL of the repository on GitHub Actions",
        ),
    ] = None,
    license: Annotated[
        str,
        typer.Option(
            "--license",
            help="License of the recipes, shown in the footer of every page (Markdown). "
            "Pass an empty string to hide it",
        ),
    ] = DEFAULT_LICENSE,
) -> None:
    """Build the static recipe website."""
    edit_url = edit_url or ci_edit_url(source)
    base_url = base_url or ci_base_url()
    count = build(
        source,
        destination,
        title,
        edit_url,
        image_width,
        thumbnail_width,
        simple_mode,
        cache_dir,
        base_url,
        license,
    )
    typer.echo(f"Built {count} recipes into {destination}")


if __name__ == "__main__":
    app()

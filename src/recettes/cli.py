from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
from fractions import Fraction
from pathlib import Path
from typing import Annotated
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import frontmatter
import typer
from markdown_it import MarkdownIt

app = typer.Typer(no_args_is_help=True, help="Build a static recipe website from Markdown.")
INGREDIENT_RE = re.compile(r"\{\{\s*(.*?)\s*\}\}")
QUANTITY_RE = re.compile(
    r"^(?P<amount>\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)?)"
    r"\s*(?P<unit>(?:c\.?\s*à\.?\s*[sc]\.?|cas|cac|tablespoons?|tbsp|teaspoons?|tsp|cups?|"
    r"ounces?|oz|pounds?|lbs?|kg|mg|g|ml|cl|l)(?![^\W\d_]))?\s*(?P<name>.*)$",
    re.IGNORECASE,
)
TOKEN_RE = re.compile(r"RECIPEINGREDIENTTOKEN(\d+)END")
STEP_LABEL_RE = re.compile(r"\b(?:etape|étape|step)\s*(\d+)\b", re.I)
STEP_BLOCK_RE = re.compile(r"<(?:p|h[1-6])\b[^>]*>.*?</(?:p|h[1-6])>", re.I | re.S)
MARKDOWN = MarkdownIt("default", {"html": False, "typographer": True})


@app.callback()
def main() -> None:
    """Build and maintain a static recipe website."""


def fail(message: str) -> None:
    raise typer.BadParameter(message)


def parse_quantity(value: str) -> tuple[float | None, str, str]:
    match = QUANTITY_RE.fullmatch(value.strip())
    if not match:
        return None, "", value.strip()
    amount_text = match.group("amount").replace(" ", "").replace(",", ".")
    try:
        amount = float(Fraction(amount_text))
    except (ValueError, ZeroDivisionError):
        return None, "", value.strip()
    raw_unit = (match.group("unit") or "").lower().replace(" ", "").replace(".", "")
    unit = {
        "càs": "cas",
        "càc": "cac",
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
    }.get(raw_unit, raw_unit)
    return amount, unit, match.group("name").strip()


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


def recipe_images(markdown_path: Path) -> list[Path]:
    images: list[Path] = []
    prefix = re.compile(
        rf"^{re.escape(markdown_path.stem)}(?:-(?P<suffix>[^.]+))?\.(?:jpe?g|png|webp|avif)$",
        re.I,
    )
    for path in markdown_path.parent.iterdir():
        if path.is_file() and prefix.fullmatch(path.name):
            images.append(path)
    return sorted(
        images,
        key=lambda path: (
            0 if image_step(path, markdown_path.stem) is None else 1,
            image_step(path, markdown_path.stem) or 0,
            path.name.lower(),
        ),
    )


def image_step(path: Path, recipe_stem: str) -> int | None:
    match = re.fullmatch(
        rf"{re.escape(recipe_stem)}-(\d+)\.(?:jpe?g|png|webp|avif)", path.name, re.I
    )
    return int(match.group(1)) if match else None


def image_figure(image: str, title: str, index: int) -> str:
    return (
        f'<figure><img loading="lazy" src="../assets/images/{attr(quote(image, safe=""))}" '
        f'alt="{attr(title)} {index}"></figure>'
    )


def insert_step_images(content: str, images: list[str], title: str, recipe_stem: str) -> str:
    by_step: dict[int, list[str]] = {}
    for image in images:
        step = image_step(Path(image), recipe_stem)
        if step is not None:
            by_step.setdefault(step, []).append(image)

    pending = set(by_step)
    image_index = {image: index for index, image in enumerate(images, start=1)}

    def place(match: re.Match[str]) -> str:
        paragraph = match.group(0)
        text = html.unescape(re.sub(r"<[^>]+>", " ", paragraph))
        label = STEP_LABEL_RE.search(text)
        if not label:
            return paragraph
        step = int(label.group(1))
        if step not in pending:
            return paragraph
        pending.remove(step)
        figures = "".join(
            image_figure(image, title, image_index[image]) for image in by_step[step]
        )
        return paragraph + f'<div class="recipe-gallery step-gallery">{figures}</div>'

    content = STEP_BLOCK_RE.sub(place, content)
    unmatched = [image for step in sorted(pending) for image in by_step[step]]
    if unmatched:
        content += '<div class="recipe-gallery step-gallery">' + "".join(
            image_figure(image, title, image_index[image]) for image in unmatched
        ) + "</div>"
    return content


def recipe_slug(path: Path) -> str:
    return path.stem


def rewrite_recipe_links(content: str, source_path: Path, recipe_slugs: dict[Path, str]) -> str:
    def replace_href(match: re.Match[str]) -> str:
        href = html.unescape(match.group(1))
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc or parsed.path.startswith("/") or not parsed.path:
            return match.group(0)

        target_path = (source_path.parent / unquote(parsed.path)).resolve()
        candidates = [target_path]
        if target_path.suffix == "":
            candidates.append(target_path.with_suffix(".md"))
        target_slug = next(
            (recipe_slugs[candidate] for candidate in candidates if candidate in recipe_slugs),
            None,
        )
        if target_slug is None:
            return match.group(0)

        target_url = urlunsplit(
            (
                "",
                "",
                f"../recipes/{quote(target_slug, safe='-_')}.html",
                parsed.query,
                parsed.fragment,
            )
        )
        return f'href="{html.escape(target_url, quote=True)}"'

    return re.sub(r'href="([^"]*)"', replace_href, content)


def recipe_page(path: Path, image_dir: Path, recipe_slugs: dict[Path, str]) -> dict[str, object]:
    try:
        document = frontmatter.load(path)
    except (OSError, ValueError) as exc:
        fail(f"Could not read recipe '{path.name}': {exc}")
    metadata = document.metadata
    portions_value = metadata.get("portions")
    portions = None
    if portions_value not in (None, ""):
        try:
            portions = int(portions_value)
        except (TypeError, ValueError):
            fail(f"Recipe '{path.name}' has invalid portions; use a positive integer")
        if isinstance(portions_value, bool) or (
            isinstance(portions_value, float) and not portions_value.is_integer()
        ):
            fail(f"Recipe '{path.name}' has invalid portions; use a positive integer")
        if portions < 1:
            fail(f"Recipe '{path.name}' has invalid portions; use a positive integer")

    title = str(metadata.get("title") or path.stem.replace("-", " ").title())
    slug = recipe_slug(path)
    content, ingredients = markdown_with_ingredients(document.content)
    content = rewrite_recipe_links(content, path, recipe_slugs)
    images = recipe_images(path)
    for image in images:
        image_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(image, image_dir / image.name)
    main_images = [image.name for image in images if image_step(image, path.stem) is None]
    step_images = [image.name for image in images if image_step(image, path.stem) is not None]

    excluded = {"title", "tags", "portions"}
    properties = [
        {"name": str(key), "value": value} for key, value in metadata.items() if key not in excluded
    ]
    return {
        "slug": slug,
        "title": title,
        "lang": str(metadata.get("lang", "")),
        "tags": parse_tags(metadata.get("tags")),
        "properties": properties,
        "excerpt": first_paragraph(document.content),
        "portions": portions,
        "ingredients": ingredients,
        "ingredient_list": aggregate_ingredients(ingredients),
        "content": content,
        "images": main_images,
        "step_images": step_images,
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
    return (
        f'<{tag} data-ingredient data-amount="{attr(float(amount))}" '
        f'data-unit="{attr(unit)}" data-name="{attr(name)}">{html.escape(text)}</{tag}>'
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


def recipe_html_parts(recipe: dict[str, object]) -> dict[str, str]:
    tags = "".join(
        f'<a class="tag" href="../index.html?tag={attr(quote(tag, safe="-_.!~*()"))}">'
        f"{html.escape(tag)}</a>"
        for tag in recipe["tags"]
    )
    properties = "".join(
        f'<div class="recipe-property"><dt>{html.escape(str(item["name"]))}</dt>'
        f"<dd>{html.escape(display_value(item['value']))}</dd></div>"
        for item in recipe["properties"]
    )
    gallery = "".join(
        image_figure(image, str(recipe["title"]), index)
        for index, image in enumerate(recipe["images"], start=1)
    )
    portions = recipe["portions"]
    return {
        "tags": tags,
        "properties": properties,
        "properties_hidden": "" if properties else " hidden",
        "servings_attrs": f' data-portions="{portions}"' if portions else " hidden",
        "portions": str(portions or ""),
        "ingredient_list": "".join(
            ingredient_html(item, "li") for item in recipe["ingredient_list"]
        ),
        "gallery": gallery,
        # Last: inserted recipe content must not be scanned for other placeholders.
        "content": insert_ingredients(
            insert_step_images(
                str(recipe["content"]),
                recipe["step_images"],
                str(recipe["title"]),
                str(recipe["slug"]),
            ),
            recipe["ingredients"],
        ),
    }


def recipe_index_data(recipes: list[dict[str, object]]) -> str:
    entries = []
    for recipe in recipes:
        search_terms = [
            str(recipe["title"]),
            *recipe["tags"],
            str(recipe["content"]),
            *(str(ingredient["raw"]) for ingredient in recipe["ingredients"]),
            *(f"{property_['name']} {property_['value']}" for property_ in recipe["properties"]),
        ]
        entries.append(
            {
                "slug": recipe["slug"],
                "title": recipe["title"],
                "tags": recipe["tags"],
                "excerpt": recipe["excerpt"],
                "search": " ".join([*search_terms, str(recipe["excerpt"])]),
                "lang": recipe["lang"],
            }
        )
    return json.dumps(entries, ensure_ascii=False)


def render_template(path: Path, **values: str) -> str:
    template = path.read_text(encoding="utf-8")
    for name, value in values.items():
        template = template.replace("{{ " + name + " }}", value)
    return template


def build(source: Path, destination: Path, title: str = "Recettes") -> int:
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_dir():
        fail(f"Recipe directory does not exist: {source}")
    if source == destination or source in destination.parents:
        fail("Output directory must be outside the recipe source directory")
    paths = sorted(path for path in source.glob("*.md") if path.is_file())
    if not paths:
        fail(f"No Markdown recipes found in {source}")

    package_dir = Path(__file__).parent
    static = package_dir / "static"
    templates = package_dir / "templates"
    assets = destination / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    # Content hashes appended to asset URLs, so browsers never use stale cached copies.
    versions = {}
    for filename in ("style.css", "app.js", "recipe.js"):
        shutil.copyfile(static / filename, assets / filename)
        digest = hashlib.sha256((static / filename).read_bytes()).hexdigest()[:10]
        versions[filename.replace(".", "_") + "_version"] = digest
    image_dir = assets / "images"
    recipes_dir = destination / "recipes"
    recipes_dir.mkdir(parents=True, exist_ok=True)
    recipes = []
    recipe_slugs = {path.resolve(): recipe_slug(path) for path in paths}
    seen = set()
    for path in paths:
        slug = recipe_slug(path)
        if slug in seen:
            fail(f"Recipe filenames must be unique: {path.name}")
        seen.add(slug)
        recipe = recipe_page(path, image_dir, recipe_slugs)
        recipes.append(recipe)
        page = render_template(
            templates / "recipe.html",
            title=html.escape(str(recipe["title"])),
            lang=html.escape(str(recipe["lang"]), quote=True),
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
        **versions,
    )
    (destination / "index.html").write_text(index, encoding="utf-8")
    (destination / "recipes.json").write_text(index_data, encoding="utf-8")
    return len(recipes)


@app.command("build")
def build_command(
    source: Annotated[Path, typer.Argument(help="Directory containing recipe Markdown files")],
    destination: Annotated[
        Path, typer.Option("--destination", "-d", help="Generated website directory")
    ] = Path("site"),
    title: Annotated[
        str, typer.Option("--title", help="Title for the home page")
    ] = "Recettes",
) -> None:
    """Build the static recipe website."""
    count = build(source, destination, title)
    typer.echo(f"Built {count} recipes into {destination}")


if __name__ == "__main__":
    app()

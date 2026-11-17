from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import unicodedata
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
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}
HEADING_RE = re.compile(r"<h([1-6])>(.*?)</h\1>", re.S)
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
    for paths in images.values():
        paths.sort(key=lambda path: natural_key(path.name))
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
        if image.stem == stem and main is None:
            main = image.name
        elif suffix and suffix in heading_slugs:
            sections.setdefault(suffix, []).append(image.name)
        else:
            gallery.append(image.name)
    return main, sections, gallery


def recipe_slug(path: Path) -> str:
    return path.stem


def local_link_targets(paths: list[Path], images: dict[str, list[Path]]) -> dict[Path, str]:
    """Map source files that end up in the site to their URL from a recipe page."""
    targets = {}
    for path in paths:
        targets[path.resolve()] = f"../recipes/{quote(recipe_slug(path), safe='-_')}.html"
        for image in images[path.stem]:
            targets[image.resolve()] = f"../assets/images/{quote(image.name, safe='-_.')}"
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


def recipe_page(
    path: Path, image_dir: Path, link_targets: dict[Path, str], images: list[Path]
) -> dict[str, object]:
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
    content = rewrite_local_links(content, path, link_targets)
    main_image, section_images, gallery = classify_images(path.stem, images, content)
    for image in images:
        image_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(image, image_dir / image.name)

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
        f'<div class="recipe-property"><dt>{html.escape(str(item["name"]))}</dt>'
        f"<dd>{html.escape(display_value(item['value']))}</dd></div>"
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
                "image": (
                    f"assets/images/{quote(str(recipe['main_image']), safe='')}"
                    if recipe["main_image"]
                    else None
                ),
            }
        )
    return json.dumps(entries, ensure_ascii=False)


def render_template(path: Path, **values: str) -> str:
    template = path.read_text(encoding="utf-8")
    for name, value in values.items():
        template = template.replace("{{ " + name + " }}", value)
    return template


def edit_link(edit_url: str | None, path: Path) -> str:
    if not edit_url:
        return ""
    url = edit_url.rstrip("/") + "/" + quote(path.name)
    return f'<a href="{attr(url)}" aria-label="Edit" title="Edit">✎</a>'


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


def build(
    source: Path, destination: Path, title: str = "Recettes", edit_url: str | None = None
) -> int:
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
    shutil.copytree(static / "fonts", assets / "fonts", dirs_exist_ok=True)
    image_dir = assets / "images"
    recipes_dir = destination / "recipes"
    recipes_dir.mkdir(parents=True, exist_ok=True)
    recipes = []
    images = assign_images(source, {path.stem for path in paths})
    link_targets = local_link_targets(paths, images)
    seen = set()
    for path in paths:
        slug = recipe_slug(path)
        if slug in seen:
            fail(f"Recipe filenames must be unique: {path.name}")
        seen.add(slug)
        recipe = recipe_page(path, image_dir, link_targets, images[path.stem])
        recipes.append(recipe)
        page = render_template(
            templates / "recipe.html",
            title=html.escape(str(recipe["title"])),
            lang=html.escape(str(recipe["lang"]), quote=True),
            edit_link=edit_link(edit_url, path),
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
    edit_url: Annotated[
        str | None,
        typer.Option(
            "--edit-url",
            help="Base URL to edit recipe files on a Git forge; the filename is appended. "
            "Guessed automatically on GitHub Actions and GitLab CI",
        ),
    ] = None,
) -> None:
    """Build the static recipe website."""
    edit_url = edit_url or ci_edit_url(source)
    count = build(source, destination, title, edit_url)
    typer.echo(f"Built {count} recipes into {destination}")


if __name__ == "__main__":
    app()

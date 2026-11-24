"""Recipe Markdown: ingredients, links, headings and text."""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

from markdown_it import MarkdownIt

from recettes.errors import fail
from recettes.quantities import Ingredient

INGREDIENT_RE = re.compile(r"\{\{\s*(.*?)\s*\}\}")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
TOKEN_RE = re.compile(r"RECIPEINGREDIENTTOKEN(\d+)END")
HEADING_RE = re.compile(r"<h([1-6])>(.*?)</h\1>", re.S)
MARKDOWN = MarkdownIt("default", {"html": False, "typographer": True})


def markdown_with_ingredients(markdown: str) -> tuple[str, list[Ingredient]]:
    ingredients: list[Ingredient] = []

    def replace(match: re.Match[str]) -> str:
        ingredients.append(Ingredient.parse(match.group(1).strip()))
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


def heading_text(content: str) -> str:
    text = TOKEN_RE.sub("", re.sub(r"<[^>]*>", "", content))
    return html.unescape(" ".join(text.split()))


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

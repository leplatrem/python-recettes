"""Recipe Markdown: ingredients, links, headings and text."""

from __future__ import annotations

import itertools
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

from markdown_it import MarkdownIt
from markdown_it.renderer import RendererProtocol
from markdown_it.rules_inline import StateInline
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict

from recettes.quantities import Ingredient
from recettes.utils import fail

HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def ingredient_rule(state: StateInline, silent: bool) -> bool:
    """Parse `{{ 50g of butter }}` into an `ingredient` token."""
    start = state.pos
    if not state.src.startswith("{{", start):
        return False
    end = state.src.find("}}", start + 2)
    if end < 0 or "\n" in state.src[start:end]:
        return False
    if not silent:
        raw = state.src[start + 2 : end].strip()
        token = state.push("ingredient", "", 0)
        token.content = raw
        token.meta = {"ingredient": Ingredient.parse(raw)}
    state.pos = end + 2
    return True


def render_ingredient(
    renderer: RendererProtocol,
    tokens: Sequence[Token],
    index: int,
    options: OptionsDict,
    env: EnvType,
) -> str:
    render: Callable[[Ingredient], str] = env["render_ingredient"]
    return render(tokens[index].meta["ingredient"])


MARKDOWN = MarkdownIt("default", {"html": False, "typographer": True})
MARKDOWN.inline.ruler.before("text", "ingredient", ingredient_rule)
MARKDOWN.add_render_rule("ingredient", render_ingredient)


def parse(markdown: str) -> list[Token]:
    """Parse a recipe body; HTML comments are left out."""
    tokens = MARKDOWN.parse(HTML_COMMENT_RE.sub("", markdown))
    # Picture descriptions are plain text (`alt` attribute): keep ingredients as written.
    for token in inline_tokens(tokens):
        if token.type == "image":
            for child in token.children or []:
                if child.type == "ingredient":
                    child.type = "text"
    return tokens


def render(tokens: list[Token], ingredient_html: Callable[[Ingredient], str]) -> str:
    env = {"render_ingredient": ingredient_html}
    html: str = MARKDOWN.renderer.render(tokens, MARKDOWN.options, env)
    return html


def inline_tokens(tokens: list[Token]) -> list[Token]:
    """All inline tokens (text, links, images, ingredients...) of the document."""
    return [child for token in tokens for child in token.children or []]


def ingredients(tokens: list[Token]) -> list[Ingredient]:
    return [
        token.meta["ingredient"] for token in inline_tokens(tokens) if token.type == "ingredient"
    ]


def inline_text(token: Token, with_ingredients: bool = True) -> str:
    """Text of an inline token, without markup."""
    parts = []
    for child in token.children or []:
        if child.type in {"text", "code_inline", "image"} or (
            child.type == "ingredient" and with_ingredients
        ):
            parts.append(child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            parts.append(" ")
    return " ".join("".join(parts).split())


def plain_text(tokens: list[Token]) -> str:
    """Text of the recipe without markup, ingredients written as in the source."""
    parts = [
        token.content if token.type in {"fence", "code_block"} else inline_text(token)
        for token in tokens
        if token.type in {"fence", "code_block", "inline"}
    ]
    return " ".join(" ".join(parts).split())


def first_paragraph(tokens: list[Token], limit: int = 180) -> str:
    for index, token in enumerate(tokens[:-1]):
        inline = tokens[index + 1]
        if token.type == "paragraph_open" and inline.type == "inline":
            text = inline_text(inline)
            if len(text) > limit:
                # Cut between words, and show that the text goes on.
                text = text[: limit + 1].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"
            if text:
                return text
    return ""


def headings(tokens: list[Token]) -> list[tuple[int, str]]:
    """Position of the `heading_open` tokens, with the heading text (ingredients left out)."""
    return [
        (index, inline_text(tokens[index + 1], with_ingredients=False))
        for index, token in enumerate(tokens)
        if token.type == "heading_open"
    ]


def emphasized_text(token: Token) -> str:
    """Words in emphasis or bold of an inline token, e.g. "Cream" in `**Cream** the butter`."""
    parts: list[str] = []
    depth = 0
    for child in token.children or []:
        if child.type in {"em_open", "strong_open"}:
            if depth == 0:
                parts.append("")
            depth += 1
        elif child.type in {"em_close", "strong_close"}:
            depth -= 1
        elif depth and child.type in {"text", "code_inline"}:
            parts[-1] += child.content
        elif depth and child.type in {"softbreak", "hardbreak"}:
            parts[-1] += " "
    return " ".join(" ".join(parts).split())


def diagram_steps(tokens: list[Token]) -> list[tuple[str, list[Ingredient]]]:
    """Steps of the recipe diagram: their words in emphasis or bold, and their ingredients.

    Steps start with the first paragraph that has ingredients, and end with its section.
    Ingredients of paragraphs without emphasis go to the next step (or the last one), so
    there are no steps without words, and no diagram when no paragraph has emphasis.
    """
    steps: list[tuple[str, list[Ingredient]]] = []
    pending: list[Ingredient] = []
    for token, inline in itertools.pairwise(tokens):
        if token.type == "heading_open" and token.tag == "h1" and (steps or pending):
            break
        if token.type != "paragraph_open":
            continue
        pending += ingredients([inline])
        label = emphasized_text(inline)
        if label and (steps or pending):
            steps.append((label, pending))
            pending = []
    if steps:
        steps[-1][1].extend(pending)
    return steps


def rewrite_local_links(tokens: list[Token], source_path: Path, targets: dict[Path, str]) -> None:
    """Point links and pictures to their published URL, and fail if their file is missing."""
    for token in inline_tokens(tokens):
        attribute = {"link_open": "href", "image": "src"}.get(token.type)
        url = token.attrGet(attribute) if attribute else None
        if attribute is None or not isinstance(url, str):
            continue
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or parsed.path.startswith("/") or not parsed.path:
            continue

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
        token.attrSet(attribute, urlunsplit(("", "", target, parsed.query, parsed.fragment)))

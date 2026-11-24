from pathlib import Path

import pytest

from recettes import markdown
from recettes.utils import RecettesError
from recettes.website import build


def test_html_comments_are_not_rendered(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "gnocchi.md").write_text(
        "---\ntitle: Gnocchi\n---\n\n<!-- original (IMG_2469.HEIC):\nsecret notes -->\n\n"
        "Mix {{250g ricotta}} <!-- inline note --> gently.\n",
        encoding="utf-8",
    )
    output = tmp_path / "site"

    build(source, output)

    recipe = (output / "recipes" / "gnocchi.html").read_text(encoding="utf-8")
    index = (output / "index.html").read_text(encoding="utf-8")
    for page in (recipe, index):
        assert "IMG_2469" not in page
        assert "secret notes" not in page
        assert "inline note" not in page
    assert "ricotta" in recipe


def test_local_markdown_recipe_links_resolve_to_recipe_pages(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "flan-coco.md").write_text(
        "---\ntitle: Flan coco\n---\n\nServez avec [caramel](caramel), "
        "[caramel.md](caramel.md), [html](caramel.html), [dot](./caramel.md), "
        "[anchor](caramel.md#etape-2), [accents](<crème brûlée.md>) "
        "ou [haut](#top).\n\n![photo](flan-coco-1.jpg)\n",
        encoding="utf-8",
    )
    (source / "caramel.md").write_text(
        "---\ntitle: Caramel\n---\n\nDu caramel.\n", encoding="utf-8"
    )
    (source / "crème brûlée.md").write_text("Crème.\n", encoding="utf-8")
    (source / "flan-coco-1.jpg").write_bytes(b"fake jpeg")
    output = tmp_path / "site"

    build(source, output)

    recipe = (output / "recipes" / "flan-coco.html").read_text(encoding="utf-8")
    assert recipe.count('href="../recipes/caramel.html"') == 4
    assert 'href="../recipes/caramel.html#etape-2"' in recipe
    assert 'href="../recipes/cr%C3%A8me%20br%C3%BBl%C3%A9e.html"' in recipe
    assert 'href="#top"' in recipe
    assert '<img src="../assets/images/flan-coco-1.jpg" alt="photo">' in recipe


@pytest.mark.parametrize("link", ["[tiramisu](tiramisu.md)", "![photo](flan-2.jpg)"])
def test_links_to_missing_files_fail_the_build(tmp_path: Path, link: str) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "flan.md").write_text(f"Servez avec {link}.\n", encoding="utf-8")

    with pytest.raises(RecettesError, match=r"'flan\.md' links to missing file"):
        build(source, tmp_path / "site")


def test_ingredients_in_picture_descriptions_and_code(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "eggs.md").write_text(
        "![Beaten {{ 2 eggs }}](eggs-1.jpg)\n\nWrite `{{ 1 egg }}` in recipes.\n",
        encoding="utf-8",
    )
    (source / "eggs-1.jpg").write_bytes(b"fake jpeg")

    build(source, tmp_path / "site")

    recipe = (tmp_path / "site" / "recipes" / "eggs.html").read_text(encoding="utf-8")
    assert 'alt="Beaten 2 eggs"' in recipe
    assert "<code>{{ 1 egg }}</code>" in recipe


def test_long_excerpt_is_cut_between_words() -> None:
    tokens = markdown.parse("Whisk the eggs with sugar, then fold in the flour gently.")

    assert markdown.first_paragraph(tokens, limit=30) == "Whisk the eggs with sugar…"
    assert (
        markdown.first_paragraph(tokens)
        == "Whisk the eggs with sugar, then fold in the flour gently."
    )

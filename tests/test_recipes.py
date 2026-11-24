from pathlib import Path

import pytest

from recettes.utils import RecettesError
from recettes.website import build


@pytest.mark.parametrize("value", ["4 à 6", "beaucoup", "2.5", "0"])
def test_non_integer_portions_are_rendered_as_text_property(tmp_path: Path, value: str) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "simple.md").write_text(
        f"---\ntitle: Simple\nportions: '{value}'\n---\n\nJust a recipe.\n", encoding="utf-8"
    )
    output = tmp_path / "site"

    build(source, output)

    recipe = (output / "recipes" / "simple.html").read_text(encoding="utf-8")
    assert '<div class="servings" id="servings-control" hidden>' in recipe
    assert '<dl class="recipe-properties" id="recipe-properties" hidden>' not in recipe
    assert "<dt>portions</dt>" in recipe
    assert value in recipe


def test_pictures_converted_to_the_same_name_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "soup.md").write_text("Hot.", encoding="utf-8")
    (source / "soup.jpg").write_bytes(b"fake jpeg")
    (source / "soup.heic").write_bytes(b"fake heic")

    with pytest.raises(RecettesError, match=r"both be published as 'soup\.jpg'"):
        build(source, tmp_path / "site")

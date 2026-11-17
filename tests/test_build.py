import hashlib
import json
import re
from pathlib import Path

import pytest

from recettes.cli import aggregate_ingredients, build, ci_edit_url, parse_quantity


def test_parse_quantity_and_guessed_count_unit() -> None:
    assert parse_quantity("50g de beurre") == (50.0, "g", "de beurre")
    assert parse_quantity("1cas d'huile") == (1.0, "cas", "d'huile")
    assert parse_quantity("1/2 cac") == (0.5, "cac", "")
    assert parse_quantity("3 gousses d'ail") == (3.0, "", "gousses d'ail")
    assert parse_quantity("2 louches de bouillon") == (2.0, "", "louches de bouillon")
    assert parse_quantity("0.5cac") == (0.5, "cac", "")
    assert parse_quantity("4 oignons") == (4.0, "", "oignons")
    assert parse_quantity("comté râpé") == (None, "", "comté râpé")


def test_aggregate_repeated_ingredients_by_name_and_unit() -> None:
    ingredients = [
        {"amount": 50.0, "unit": "g", "name": "de beurre", "raw": "50g de beurre"},
        {"amount": 20.0, "unit": "g", "name": "de beurre", "raw": "20g de beurre"},
        {"amount": 0.5, "unit": "cac", "name": "de sel", "raw": "1/2 cac de sel"},
        {"amount": 0.5, "unit": "cac", "name": "de sel", "raw": "0.5cac de sel"},
    ]

    aggregated = aggregate_ingredients(ingredients)

    assert [(item["amount"], item["unit"], item["name"]) for item in aggregated] == [
        (70.0, "g", "de beurre"),
        (1.0, "cac", "de sel"),
    ]


def test_build_recipe_site_with_frontmatter_images_and_portion_controls(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "soupe-oignon.md").write_text(
        "---\ntitle: Soupe à l'oignon\nportions: 4\npreparation: 45\n"
        "cuisson: 15\ntags: hiver, soupe\nlang: fr\nauteur: Test\n---\n\n"
        "# Préparation\n\nMélangez {{ 4 oignons }} et {{ 50g de beurre }}.\n\n"
        "Ajoutez {{ 20 g de beurre }} et {{ 1/2 cac de sel }}.\n"
        "Goûtez, puis ajoutez {{ 0.5cac de sel }} si besoin.\n",
        encoding="utf-8",
    )
    (source / "soupe-oignon-1.jpg").write_bytes(b"fake jpeg")
    output = tmp_path / "site"

    assert build(source, output) == 1

    index = (output / "index.html").read_text(encoding="utf-8")
    recipe = (output / "recipes" / "soupe-oignon.html").read_text(encoding="utf-8")
    assert not (output / "data").exists()
    assert '<template id="recipe-card-template">' in index
    assert '<p class="card-excerpt" data-recipe-excerpt></p>' in index
    assert '<link rel="prefetch" href="recipes/soupe-oignon.html">' in index
    assert '<h2 class="ingredients-title">Ingredients</h2>' in recipe
    assert '<html lang="fr">' in recipe
    assert "<title>Soupe à l&#x27;oignon</title>" in recipe
    assert '<a class="tag" href="../index.html?tag=hiver">hiver</a>' in recipe
    properties = [("preparation", "45"), ("cuisson", "15"), ("lang", "fr"), ("auteur", "Test")]
    for name, value in properties:
        assert f"<dt>{name}</dt><dd>{value}</dd>" in recipe
    assert '<div class="servings" id="servings-control" data-portions="4">' in recipe
    assert '<strong id="servings-count">4</strong>' in recipe
    assert (
        '<ul id="ingredient-list">'
        '<li data-ingredient data-amount="4.0" data-unit="" data-name="oignons">4 oignons</li>'
        '<li data-ingredient data-amount="70.0" data-unit="g" data-name="de beurre">'
        "70 g de beurre</li>"
        '<li data-ingredient data-amount="1.0" data-unit="cac" data-name="de sel">1 cac de sel</li>'
        "</ul>"
    ) in recipe
    assert (
        'Ajoutez <span data-ingredient data-amount="20.0" data-unit="g" data-name="de beurre">'
        "20 g de beurre</span>"
    ) in recipe
    assert "RECIPEINGREDIENTTOKEN" not in recipe
    index_data = json.loads((output / "recipes.json").read_text(encoding="utf-8"))
    assert "4 oignons" in index_data[0]["search"]
    assert "auteur Test" in index_data[0]["search"]
    assert index_data[0]["excerpt"] == "Mélangez 4 oignons et 50g de beurre."
    assert (
        '<img loading="lazy" src="../assets/images/soupe-oignon-1.jpg" '
        'alt="Soupe à l&#x27;oignon 1">'
    ) in recipe
    assert (output / "assets" / "images" / "soupe-oignon-1.jpg").read_bytes() == b"fake jpeg"


def test_recipe_without_portions_has_no_toggle_and_properties_are_optional(
    tmp_path: Path,
) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "simple.md").write_text(
        "---\ntitle: Simple\ntags: quick\n---\n\nJust a recipe.\n", encoding="utf-8"
    )
    output = tmp_path / "site"

    build(source, output)

    recipe = (output / "recipes" / "simple.html").read_text(encoding="utf-8")
    assert '<div class="servings" id="servings-control" hidden>' in recipe
    assert '<dl class="recipe-properties" id="recipe-properties" hidden></dl>' in recipe
    assert '<ul id="ingredient-list"></ul>' in recipe
    assert "<p>Just a recipe.</p>" in recipe


def test_local_markdown_recipe_links_resolve_to_recipe_pages(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "flan-coco.md").write_text(
        "---\ntitle: Flan coco\n---\n\nServez avec [caramel](caramel) "
        "ou [caramel.md](caramel.md).\n",
        encoding="utf-8",
    )
    (source / "caramel.md").write_text(
        "---\ntitle: Caramel\n---\n\nDu caramel.\n", encoding="utf-8"
    )
    output = tmp_path / "site"

    build(source, output)

    recipe = (output / "recipes" / "flan-coco.html").read_text(encoding="utf-8")
    assert recipe.count('href="../recipes/caramel.html"') == 2


def test_asset_urls_are_versioned_with_content_hash(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "simple.md").write_text("Just a recipe.\n", encoding="utf-8")
    output = tmp_path / "site"

    build(source, output)

    def version(filename: str) -> str:
        content = (output / "assets" / filename).read_bytes()
        return hashlib.sha256(content).hexdigest()[:10]

    index = (output / "index.html").read_text(encoding="utf-8")
    recipe = (output / "recipes" / "simple.html").read_text(encoding="utf-8")
    assert f'href="assets/style.css?v={version("style.css")}"' in index
    assert f'src="assets/app.js?v={version("app.js")}"' in index
    assert f'href="../assets/style.css?v={version("style.css")}"' in recipe
    assert f'src="../assets/recipe.js?v={version("recipe.js")}"' in recipe
    data_version = hashlib.sha256((output / "recipes.json").read_bytes()).hexdigest()[:10]
    assert (
        f'<link rel="preload" id="recipes-data" href="recipes.json?v={data_version}" '
        'as="fetch" crossorigin>'
    ) in index
    assert not re.search(r"\{\{ \w+ \}\}", index + recipe)


def test_edit_link_only_when_edit_url_given(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "soupe oignon.md").write_text("Hello", encoding="utf-8")

    build(source, tmp_path / "plain")
    plain = (tmp_path / "plain" / "recipes" / "soupe oignon.html").read_text(encoding="utf-8")
    assert "{{ edit_link }}" not in plain
    assert 'aria-label="Edit"' not in plain

    build(source, tmp_path / "edit", edit_url="https://codeberg.org/me/recipes/_edit/main/r/")
    page = (tmp_path / "edit" / "recipes" / "soupe oignon.html").read_text(encoding="utf-8")
    assert (
        '<a href="https://codeberg.org/me/recipes/_edit/main/r/soupe%20oignon.md" '
        'aria-label="Edit" title="Edit">✎</a>'
    ) in page


@pytest.fixture
def no_ci_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in ("GITHUB_ACTIONS", "GITLAB_CI"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_ci_edit_url_from_github_actions(tmp_path: Path, no_ci_env: pytest.MonkeyPatch) -> None:
    assert ci_edit_url(tmp_path / "recipes") is None
    no_ci_env.setenv("GITHUB_ACTIONS", "true")
    no_ci_env.setenv("GITHUB_SERVER_URL", "https://github.com")
    no_ci_env.setenv("GITHUB_REPOSITORY", "me/recipes")
    no_ci_env.setenv("GITHUB_REF_NAME", "main")
    no_ci_env.setenv("GITHUB_WORKSPACE", str(tmp_path))
    assert ci_edit_url(tmp_path / "recipes") == "https://github.com/me/recipes/edit/main/recipes"
    assert ci_edit_url(tmp_path) == "https://github.com/me/recipes/edit/main"
    assert ci_edit_url(Path("/elsewhere")) is None


def test_ci_edit_url_from_gitlab_ci(tmp_path: Path, no_ci_env: pytest.MonkeyPatch) -> None:
    no_ci_env.setenv("GITLAB_CI", "true")
    no_ci_env.setenv("CI_PROJECT_URL", "https://gitlab.com/me/recipes")
    no_ci_env.setenv("CI_COMMIT_REF_NAME", "main")
    no_ci_env.setenv("CI_PROJECT_DIR", str(tmp_path))
    assert ci_edit_url(tmp_path / "r") == "https://gitlab.com/me/recipes/-/edit/main/r"

import hashlib
import json
import re
from pathlib import Path

import pytest
import typer

from recettes.cli import aggregate_ingredients, build, ci_edit_url, parse_quantity


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        ("1.5L of water", (1.5, "l", "of water")),
        ("50g de beurre", (50.0, "g", "de beurre")),
        ("1cas d'huile", (1.0, "c. à s.", "d'huile")),
        ("1/2 cac", (0.5, "c. à c.", "")),
        ("3 gousses d'ail", (3.0, "", "gousses d'ail")),
        ("2 louches de bouillon", (2.0, "", "louches de bouillon")),
        ("0.5cac", (0.5, "c. à c.", "")),
        ("4 oignons", (4.0, "", "oignons")),
        ("comté râpé", (None, "", "comté râpé")),
    ],
)
def test_parse_quantity_and_guessed_count_unit(text: str, parsed: tuple) -> None:
    assert parse_quantity(text) == parsed


@pytest.mark.parametrize(
    ("quantity", "expected_unit"),
    [
        ("1 càs", "c. à s."),
        ("1 c. à s.", "c. à s."),
        ("1 càc", "c. à c."),
        ("1 c. à c.", "c. à c."),
        ("1 TL", "TL"),
        ("1 EL", "EL"),
        ("1 cdita", "cdita"),
        ("1 cda", "cda"),
        ("1 Cc", "Cc"),
        ("1 CC", "CC"),
        ("1 cc", "cc"),
        ("1 ct", "ct"),
        ("1 tsk", "tsk"),
        ("1 msk", "msk"),
        ("1 ts", "ts"),
        ("1 ss", "ss"),
        ("1 fl_oz", "fl oz"),
        ("1 floz", "fl oz"),
        ("1 fl oz", "fl oz"),
    ],
)
def test_parse_localized_spoon_units(quantity: str, expected_unit: str) -> None:
    amount, unit, name = parse_quantity(quantity)
    assert (amount, unit, name) == (1.0, expected_unit, "")


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
        '<li data-ingredient data-amount="1.0" data-unit="c. à c." data-name="de sel">'
        "1 c. à c. de sel</li>"
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

    with pytest.raises(typer.BadParameter, match="'flan.md' links to missing file"):
        build(source, tmp_path / "site")


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


def test_images_are_placed_as_main_picture_in_sections_or_gallery(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "tarte.md").write_text(
        "---\ntitle: Tarte\n---\n\n# Préparation\n\n## Étape 1\n\nÉtalez la pâte.\n\n"
        "## Étape 2\n\nAjoutez {{ 3 pommes }}.\n",
        encoding="utf-8",
    )
    (source / "tarte-citron.md").write_text("Une autre tarte.\n", encoding="utf-8")
    for name in ("tarte.jpg", "tarte-etape-1.png", "tarte-inconnu.webp", "tarte-citron.jpg"):
        (source / name).write_bytes(b"fake")
    output = tmp_path / "site"

    build(source, output)

    recipe = (output / "recipes" / "tarte.html").read_text(encoding="utf-8")
    main = '<figure class="recipe-main-image"><img src="../assets/images/tarte.jpg" alt="Tarte">'
    assert main in recipe
    assert recipe.index("ingredient-list") < recipe.index(main) < recipe.index("recipe-content")
    step = (
        '<p>Étalez la pâte.</p>\n<div class="recipe-step-images"><figure><img loading="lazy" '
        'src="../assets/images/tarte-etape-1.png" alt="Tarte – Étape 1"></figure></div>\n'
        "<h2>Étape 2</h2>"
    )
    assert step in recipe
    gallery = recipe[recipe.index('id="recipe-gallery"') :]
    assert "tarte-inconnu.webp" in gallery
    assert "tarte-citron.jpg" not in recipe
    index_data = {
        entry["slug"]: entry
        for entry in json.loads((output / "recipes.json").read_text(encoding="utf-8"))
    }
    assert index_data["tarte"]["image"] == "assets/images/thumbnails/tarte.jpg"
    other = (output / "recipes" / "tarte-citron.html").read_text(encoding="utf-8")
    assert 'src="../assets/images/tarte-citron.jpg"' in other


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

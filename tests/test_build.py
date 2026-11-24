import hashlib
import html
import re
from pathlib import Path

import pytest

from recettes import markdown
from recettes.ci import ci_base_url, ci_edit_url
from recettes.errors import RecettesError
from recettes.quantities import (
    Ingredient,
    aggregate_ingredients,
    find_density,
    parse_quantity,
    volume_ml,
)
from recettes.site import BuildOptions, build, lint


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
        ("2 cucchiai di zucchero", (2.0, "cucchiai", "di zucchero")),
        ("1/2 cucchiaino di sale", (0.5, "cucchiaino", "di sale")),
        ("3 cucchiaiate di miele", (3.0, "", "cucchiaiate di miele")),
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
        ("1 cucchiaio", "cucchiaio"),
        ("1 cucchiai", "cucchiai"),
        ("1 Cucchiaino", "cucchiaino"),
        ("1 cucchiaini", "cucchiaini"),
    ],
)
def test_parse_localized_spoon_units(quantity: str, expected_unit: str) -> None:
    amount, unit, name = parse_quantity(quantity)
    assert (amount, unit, name) == (1.0, expected_unit, "")


def test_aggregate_repeated_ingredients_by_name_and_unit() -> None:
    ingredients = [
        Ingredient(raw="50g de beurre", amount=50.0, unit="g", name="de beurre"),
        Ingredient(raw="20g de beurre", amount=20.0, unit="g", name="de beurre"),
        Ingredient(raw="1/2 cac de sel", amount=0.5, unit="cac", name="de sel"),
        Ingredient(raw="0.5cac de sel", amount=0.5, unit="cac", name="de sel"),
    ]

    aggregated = aggregate_ingredients(ingredients)

    assert [(item.amount, item.unit, item.name) for item in aggregated] == [
        (70.0, "g", "de beurre"),
        (1.0, "cac", "de sel"),
    ]


@pytest.mark.parametrize(
    ("name", "density"),
    [
        ("of flour", 0.55),
        ("de farine de sarrasin", 0.55),
        ("di zucchero", 0.85),
        ("de azúcar glas", 0.56),
        ("de sucre glace", 0.56),
        ("of icing sugar", 0.56),
        ("of walnuts", 0.45),
        ("de noix de coco râpée", 0.35),
        ("de pépites de chocolat", 0.7),
        ("of salted peanuts", None),
        ("of fresh ginger", None),
    ],
)
def test_find_density_in_several_languages(name: str, density: float | None) -> None:
    assert find_density(name) == density


@pytest.mark.parametrize(
    ("amount", "unit", "name", "ml"),
    [
        (110, "g", "of flour", 200),
        (1, "kg", "de beurre", 1000 / 0.91),
        (1, "c. à s.", "d'huile", 15),
        (2, "tsp", "of anything", 10),
        (2, "cucchiai", "di olio", 30),
        (1, "cucchiaino", "di sale", 5),
        (0.5, "l", "of water", 500),
        (50, "g", "of fresh ginger", None),
        (4, "", "eggs", None),
        (None, "", "lemon zest", None),
    ],
)
def test_volume_ml_for_simple_mode(
    amount: float | None, unit: str, name: str, ml: float | None
) -> None:
    assert volume_ml(amount, unit, name) == (pytest.approx(ml) if ml else None)


def test_simple_mode_volumes_and_unknown_density_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "cake.md").write_text(
        "Mix {{ 110g of flour }}, {{ 1 tbsp of oil }}, {{ 3 eggs }} and {{ 50g of ginger }}.\n",
        encoding="utf-8",
    )
    output = tmp_path / "site"

    build(source, output)

    recipe = (output / "recipes" / "cake.html").read_text(encoding="utf-8")
    assert '<label class="simple-toggle" title="🥛 = 200 ml, 🥄 = 15 ml">' in recipe
    assert 'data-name="of flour" data-ml="200.0">' in recipe
    assert 'data-name="of oil" data-ml="15.0">' in recipe
    assert 'data-name="eggs">' in recipe
    assert 'data-name="of ginger">' in recipe
    assert "'cake.md': unknown density for 'of ginger'" in capsys.readouterr().err


def test_simple_toggle_hidden_without_measurable_ingredients(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "eggs.md").write_text("Boil {{ 2 eggs }}.\n", encoding="utf-8")
    output = tmp_path / "site"

    build(source, output)

    recipe = (output / "recipes" / "eggs.html").read_text(encoding="utf-8")
    assert '<label class="simple-toggle" title="🥛 = 200 ml, 🥄 = 15 ml" hidden>' in recipe


def test_simple_mode_can_be_disabled(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "cake.md").write_text(
        "Mix {{ 110g of flour }} and {{ 50g of ginger }}.\n", encoding="utf-8"
    )
    output = tmp_path / "site"

    build(source, output, BuildOptions(simple_mode=False))

    recipe = (output / "recipes" / "cake.html").read_text(encoding="utf-8")
    assert '<label class="simple-toggle" title="🥛 = 200 ml, 🥄 = 15 ml" hidden>' in recipe
    assert "data-ml" not in recipe
    assert "unknown density" not in capsys.readouterr().err


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
    assert not (output / "recipes.json").exists()
    assert '<a href="recipes/soupe-oignon.html"><div class="card-body">' in index
    assert '<p class="card-excerpt">Mélangez 4 oignons et 50g de beurre.</p>' in index
    assert '<span class="tag">hiver</span>' in index
    assert 'data-tag="hiver" style="--tag-weight: 1">' in index
    assert 'placeholder="Search 1 recipes"' in index
    assert 'rel="prefetch"' not in index
    assert '<script type="speculationrules">' in index
    assert '<h2 class="ingredients-title">Ingredients</h2>' in recipe
    assert '<html lang="fr">' in recipe
    assert "<title>Soupe à l&#x27;oignon</title>" in recipe
    assert '<a class="tag" href="../index.html?tag=hiver">hiver</a>' in recipe
    properties = [
        ("Preparation", "45 min"),
        ("Cuisson", "15 min"),
        ("Lang", "fr"),
        ("Auteur", "Test"),
    ]
    for name, value in properties:
        assert f"<dt>{name}</dt><dd>{value}</dd>" in recipe
    assert '<div class="servings" id="servings-control" data-portions="4">' in recipe
    assert '<strong id="servings-count">4</strong>' in recipe
    assert (
        '<ul id="ingredient-list">'
        '<li data-ingredient data-amount="4.0" data-unit="" data-name="oignons">4 oignons</li>'
        '<li data-ingredient data-amount="70.0" data-unit="g" data-name="de beurre" '
        'data-ml="76.92">70 g de beurre</li>'
        '<li data-ingredient data-amount="1.0" data-unit="c. à c." data-name="de sel" '
        'data-ml="5.0">1 c. à c. de sel</li>'
        "</ul>"
    ) in recipe
    assert (
        'Ajoutez <span data-ingredient data-amount="20.0" data-unit="g" '
        'data-name="de beurre" data-ml="21.98">20 g de beurre</span>'
    ) in recipe
    assert "RECIPEINGREDIENTTOKEN" not in recipe
    search = html.unescape(re.search(r'data-search="([^"]*)"', index).group(1))
    assert "4 oignons" in search
    assert "auteur Test" in search
    assert "<" not in search
    assert "TOKEN" not in search
    assert '<article class="recipe-card" lang="fr"' in index
    assert (
        '<img loading="lazy" src="../assets/images/soupe-oignon-1.jpg" '
        'alt="Soupe à l&#x27;oignon, photo 1">'
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
    assert "<dt>Portions</dt>" in recipe
    assert value in recipe


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

    with pytest.raises(RecettesError, match="'flan.md' links to missing file"):
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
    assert 'alt="Tarte – inconnu"' in gallery
    assert "tarte-citron.jpg" not in recipe
    index = (output / "index.html").read_text(encoding="utf-8")
    assert '<img class="card-image" src="assets/images/thumbnails/tarte.jpg"' in index
    other = (output / "recipes" / "tarte-citron.html").read_text(encoding="utf-8")
    assert 'src="../assets/images/tarte-citron.jpg"' in other


def test_edit_link_only_when_edit_url_given(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "soupe oignon.md").write_text("Hello", encoding="utf-8")

    build(source, tmp_path / "plain")
    plain = (tmp_path / "plain" / "recipes" / "soupe oignon.html").read_text(encoding="utf-8")
    assert "{{ edit_link }}" not in plain
    assert 'aria-label="Edit' not in plain

    build(
        source,
        tmp_path / "edit",
        BuildOptions(edit_url="https://codeberg.org/me/recipes/_edit/main/r/"),
    )
    page = (tmp_path / "edit" / "recipes" / "soupe oignon.html").read_text(encoding="utf-8")
    assert (
        '<a href="https://codeberg.org/me/recipes/_edit/main/r/soupe%20oignon.md" '
        'aria-label="Edit (opens in a new tab)" title="Edit (opens in a new tab)" '
        'target="_blank" rel="noopener">✎</a>'
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


def test_ci_base_url_from_github_actions(no_ci_env: pytest.MonkeyPatch) -> None:
    assert ci_base_url() is None
    no_ci_env.setenv("GITHUB_ACTIONS", "true")
    no_ci_env.setenv("GITHUB_SERVER_URL", "https://github.com")
    no_ci_env.setenv("GITHUB_REPOSITORY", "Me/recipes")
    assert ci_base_url() == "https://me.github.io/recipes/"
    no_ci_env.setenv("GITHUB_REPOSITORY", "Me/me.github.io")
    assert ci_base_url() == "https://me.github.io/"
    no_ci_env.setenv("GITHUB_SERVER_URL", "https://github.example.com")
    assert ci_base_url() is None


def test_open_graph_tags(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "tarte.md").write_text(
        '---\ntitle: Tarte "citron"\ntags: dessert, été\n---\n\nUne tarte acidulée.\n',
        encoding="utf-8",
    )
    (source / "tarte.jpg").write_bytes(b"fake jpeg")
    output = tmp_path / "site"

    build(
        source, output, BuildOptions(title="Mes recettes", base_url="https://example.com/recettes")
    )

    recipe = (output / "recipes" / "tarte.html").read_text(encoding="utf-8")
    assert '<meta property="og:title" content="Tarte &quot;citron&quot;">' in recipe
    assert '<meta property="og:type" content="article">' in recipe
    assert '<meta property="og:site_name" content="Mes recettes">' in recipe
    assert '<meta property="og:description" content="Une tarte acidulée.">' in recipe
    assert '<meta name="description" content="Une tarte acidulée.">' in recipe
    assert (
        '<meta property="og:url" content="https://example.com/recettes/recipes/tarte.html">'
        in recipe
    )
    assert (
        '<meta property="og:image" content="https://example.com/recettes/assets/images/tarte.jpg">'
        in recipe
    )
    assert '<meta property="article:tag" content="dessert">' in recipe
    assert '<meta property="article:tag" content="été">' in recipe
    index = (output / "index.html").read_text(encoding="utf-8")
    assert '<meta property="og:type" content="website">' in index
    assert '<meta property="og:url" content="https://example.com/recettes/">' in index


def test_open_graph_tags_without_base_url(tmp_path: Path, no_ci_env: pytest.MonkeyPatch) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "tarte.md").write_text("Une tarte.\n", encoding="utf-8")
    (source / "tarte.jpg").write_bytes(b"fake jpeg")
    output = tmp_path / "site"

    build(source, output)

    recipe = (output / "recipes" / "tarte.html").read_text(encoding="utf-8")
    assert '<meta name="description" content="Une tarte.">' in recipe
    assert "og:" not in recipe
    assert "og:" not in (output / "index.html").read_text(encoding="utf-8")


def test_license_shown_in_footer(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "eggs.md").write_text("Boil {{ 2 eggs }}.\n", encoding="utf-8")

    build(source, tmp_path / "default")
    for page in ("index.html", "recipes/eggs.html"):
        html = (tmp_path / "default" / page).read_text(encoding="utf-8")
        assert (
            '<a href="https://creativecommons.org/licenses/by/4.0/">Copyrights CC-BY</a> —'
            " Built with"
        ) in html

    build(source, tmp_path / "custom", BuildOptions(license="© *Me*"))
    html = (tmp_path / "custom" / "index.html").read_text(encoding="utf-8")
    assert "© <em>Me</em> — Built with" in html

    build(source, tmp_path / "none", BuildOptions(license=""))
    html = (tmp_path / "none" / "index.html").read_text(encoding="utf-8")
    assert "—" not in html.split('class="site-footer"')[1]


def test_build_removes_outputs_of_deleted_recipes(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "soup.md").write_text("Hot.", encoding="utf-8")
    (source / "cake.md").write_text("Sweet.", encoding="utf-8")
    (source / "cake.jpg").write_bytes(b"fake jpeg")
    output = tmp_path / "site"
    build(source, output)
    (output / "CNAME").write_text("recipes.example.com", encoding="utf-8")

    (source / "cake.md").unlink()
    (source / "cake.jpg").unlink()
    build(source, output)

    assert (output / "recipes" / "soup.html").exists()
    assert not (output / "recipes" / "cake.html").exists()
    assert not (output / "assets" / "images" / "cake.jpg").exists()
    assert (output / "CNAME").exists()


def test_pictures_converted_to_the_same_name_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "soup.md").write_text("Hot.", encoding="utf-8")
    (source / "soup.jpg").write_bytes(b"fake jpeg")
    (source / "soup.heic").write_bytes(b"fake heic")

    with pytest.raises(RecettesError, match="both be published as 'soup.jpg'"):
        build(source, tmp_path / "site")


def test_cc_is_cubic_centimeters_in_english() -> None:
    assert volume_ml(10, "cc", "of milk", "en") == 10
    assert volume_ml(10, "cc", "of milk", "en-GB") == 10
    assert volume_ml(10, "cc", "de lait", "fr") == 50
    assert volume_ml(10, "cc", "de lait") == 50


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


def test_lint_checks_links_and_densities(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "cake.md").write_text("Add {{ 50g of ginger }}.\n", encoding="utf-8")

    assert lint(source) == 1
    assert "unknown density for 'of ginger'" in capsys.readouterr().err
    assert not (tmp_path / "site").exists()

    (source / "soup.md").write_text("Serve with [bread](bread.md).\n", encoding="utf-8")
    with pytest.raises(RecettesError, match="links to missing file 'bread.md'"):
        lint(source)


def test_long_excerpt_is_cut_between_words() -> None:
    tokens = markdown.parse("Whisk the eggs with sugar, then fold in the flour gently.")

    assert markdown.first_paragraph(tokens, limit=30) == "Whisk the eggs with sugar…"
    assert (
        markdown.first_paragraph(tokens)
        == "Whisk the eggs with sugar, then fold in the flour gently."
    )

import hashlib
import html
import re
from pathlib import Path

import pytest

from recettes import __version__
from recettes.utils import RecettesError
from recettes.website import BuildOptions, build, lint


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
    assert 'placeholder="Rechercher parmi 1 recettes"' in index
    assert 'rel="prefetch"' not in index
    assert '<script type="speculationrules">' in index
    assert '<h2 class="ingredients-title">Ingrédients</h2>' in recipe
    assert '<html lang="fr">' in recipe
    assert "<title>Soupe à l&#39;oignon</title>" in recipe
    assert '<a class="tag" href="../index.html?tag=hiver">hiver</a>' in recipe
    properties = [("preparation", "45"), ("cuisson", "15"), ("lang", "fr"), ("auteur", "Test")]
    for name, value in properties:
        assert f"<dt>{name}</dt><dd>{value}</dd>" in recipe
    assert '<div class="servings" id="servings-control" data-portions="4">' in recipe
    assert '<strong id="servings-count">4</strong>' in recipe
    assert (
        '<ul class="ingredient-list">'
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
        '<img src="../assets/images/soupe-oignon-1.jpg" '
        'alt="Soupe à l&#39;oignon, photo 1" loading="lazy">'
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
    assert '<ul class="ingredient-list"></ul>' in recipe
    assert "<p>Just a recipe.</p>" in recipe


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
    assert f'href="../assets/favicon.svg?v={version("favicon.svg")}"' in recipe
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
        '<p>Étalez la pâte.</p>\n<div class="recipe-step-images"><figure>'
        '<img src="../assets/images/tarte-etape-1.png" alt="Tarte – Étape 1" loading="lazy">'
        "</figure></div>\n"
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
    assert '<meta property="og:title" content="Tarte &#34;citron&#34;">' in recipe
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
    assert '<meta property="og:locale" content="en">' in recipe
    assert '<meta name="twitter:card" content="summary_large_image">' in recipe
    assert '<link rel="canonical" href="https://example.com/recettes/recipes/tarte.html">' in recipe
    index = (output / "index.html").read_text(encoding="utf-8")
    assert '<meta property="og:type" content="website">' in index
    assert '<meta property="og:url" content="https://example.com/recettes/">' in index
    assert '<meta name="description" content="1 recipe">' in index
    assert '<meta name="twitter:card" content="summary">' in index
    assert (output / "sitemap.xml").read_text(encoding="utf-8") == (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "  <url><loc>https://example.com/recettes/</loc></url>\n"
        "  <url><loc>https://example.com/recettes/recipes/tarte.html</loc></url>\n"
        "</urlset>\n"
    )

    build(source, output, BuildOptions(description="Family recipes", lang="fr-CA"))
    index = (output / "index.html").read_text(encoding="utf-8")
    assert '<meta name="description" content="Family recipes">' in index


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
    assert "canonical" not in recipe
    assert not (output / "sitemap.xml").exists()


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
    with pytest.raises(RecettesError, match=r"links to missing file 'bread\.md'"):
        lint(source)


def test_interface_language(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "soup.md").write_text("Hot.", encoding="utf-8")
    (source / "sopa.md").write_text("---\nlang: es\n---\nCaliente.", encoding="utf-8")

    build(source, tmp_path / "default")
    index = (tmp_path / "default" / "index.html").read_text(encoding="utf-8")
    soup = (tmp_path / "default" / "recipes" / "soup.html").read_text(encoding="utf-8")
    sopa = (tmp_path / "default" / "recipes" / "sopa.html").read_text(encoding="utf-8")
    assert '<html lang="en">' in index
    assert 'placeholder="Search 2 recipes"' in index
    assert ">Ingredients</h2>" in soup
    assert '<html lang="es">' in sopa
    assert ">Ingredientes</h2>" in sopa
    assert (
        'Hecho con <a href="https://github.com/leplatrem/python-recettes">'
        f"Recettes v{__version__}</a>"
    ) in sopa

    build(source, tmp_path / "french", BuildOptions(lang="fr-CA"))
    index = (tmp_path / "french" / "index.html").read_text(encoding="utf-8")
    soup = (tmp_path / "french" / "recipes" / "soup.html").read_text(encoding="utf-8")
    assert '<html lang="fr-CA">' in index
    assert 'aria-label="Filtrer par étiquette"' in index
    assert 'aria-label="Retour"' in soup


def test_build_reports_progress_of_pictures(tmp_path: Path) -> None:
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "soup.md").write_text("Hot.", encoding="utf-8")
    (source / "soup.jpg").write_bytes(b"fake jpeg")
    (source / "soup-1.jpg").write_bytes(b"fake jpeg")
    (source / "cake.md").write_text("Sweet.", encoding="utf-8")
    calls = []

    build(source, tmp_path / "site", progress=lambda *args: calls.append(args))

    assert calls == [(1, 2, "soup-1.jpg"), (2, 2, "soup.jpg")]

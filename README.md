# Recettes

*Recettes* turns Markdown files into a small, static recipe website. Recipes remain easy to edit in GitHub; the generated site is mobile-friendly and needs no application server.

## Examples

Look at the [examples/](./examples/) folder and how it turned into [this website](https://leplatrem.github.io/python-recettes/).

* [Mat's recipes](https://leplatrem.github.io/recettes/)
* [Alex's recipes](https://recettes.notmyidea.org/)
* [Nyota33's recipes](https://nyota33.github.io/python-recettes/)
* [Ari's recipes](https://recetas.ariadnamvalls.com/)

## Recipe format

Put one Markdown file per recipe in a directory. Optional photos sit beside the Markdown file and are named after it:

```text
examples/
├── onion-soup.md
├── onion-soup.jpg          # main picture, shown below the ingredients
├── onion-soup-step-2.png   # shown at the end of the "Step 2" section
└── onion-soup-1.webp       # no matching heading: shown at the end of the recipe
```

Section pictures use the slug of a heading: lowercase, accents removed, non-alphanumeric characters replaced by dashes (`## Étape 1` → `etape-1`). Supported formats are JPEG, PNG, WebP, AVIF, GIF and HEIC/HEIF (converted to JPEG, e.g. `onion-soup.heic` → `onion-soup.jpg`).

Recipe properties go in YAML front matter. Tags can be a comma-separated string. All properties are optional:

```md
---
title: Onion Soup
portions: 4
preparation: 45
cooking: 15
tags: winter, soup, easy, budget-friendly
lang: en
---

# Preparation

Peel and thinly slice {{ 4 onions }}.

Cook them gently in {{ 50g of butter }} and {{ 1 tbsp of oil }}.
Add {{ 1L of hot water }} and {{ 250ml of white wine }}.

Simmer until tender.

<!-- this comment will be hidden -->
```

Write ingredient amounts inside `{{ }}` in the recipe text.

*Recettes* reads a number and an optional unit from the start of each expression, including decimals and fractions such as `0.5oz` and `1/2 tbsp`.

Supported units include metric units, `tbsp`/`tablespoon(s)`, `tsp`/`teaspoon(s)`, `cup(s)`, `oz`/`ounce(s)`, `fl_oz`/`floz`/`fl oz`, and `lb`/`pound(s)`, plus common spoon abbreviations in French (`cas`, `càs`, `cac`, `càc`), German (`TL`, `EL`), Spanish (`cdita`, `cda`), Italian (`cucchiaio`/`cucchiai` and `Cc`/`CC` for tablespoons, `cucchiaino`/`cucchiaini` and `cc`/`ct` for teaspoons), Swedish (`tsk`, `msk`), and Norwegian (`ts`, `ss`). French units `cas`/`càs` and `cac`/`càc` display as `c. à s.` and `c. à c.`. In recipes with `lang: en`, `cc` means cubic centimeters (milliliters). A number without a unit is treated as a count. Text without a leading number is kept as written.

The optional `portions` property enables serving controls when it is a positive integer (other values are shown as a regular property), and `lang` sets the recipe page's language for browsers and assistive technology.

Link to another recipe with its Markdown file, e.g. `[caramel](caramel.md)`, and show a photo inline with `![photo](onion-soup-1.jpg)`. The build fails if a link points to a missing file.

## Create your own website

To create your own recipe website, [fork](https://docs.github.com/articles/fork-a-repo) [Mat's recipes repository](https://github.com/leplatrem/recettes/) and replace the recipes in the `recipes/` folder with your own.

## Run locally

Install from PyPI with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install recettes
```

Or from a checkout, with `uv tool install .`.

Build the recipes in a directory and preview the generated site:

```sh
recettes build examples/ --destination site/ --title "My Recipes"
python -m http.server --directory site/ 8000
```

Open <http://127.0.0.1:8000>.

Check recipe Markdown and local links without generating the site:

```sh
recettes lint examples/
```

Recipe pages show an edit button linking to the recipe file on your Git forge. When building on GitHub Actions or GitLab CI, its URL is guessed from the CI environment. Elsewhere (e.g. Codeberg, or locally), pass the URL of the recipes folder in the forge's editor with `--edit-url`; the recipe filename is appended to it:

```sh
recettes build examples/ --edit-url https://codeberg.org/USER/REPO/_edit/main/examples/
```

Without an edit URL, the button is not shown.

Pages include [Open Graph](https://ogp.me/) tags, for link previews in social networks and messaging apps. These tags, and the canonical URL of pages, need the public URL of the website, since their links must be absolute. When building on GitHub Actions, the GitHub Pages URL of the repository (`https://USER.github.io/REPO/`) is used. Elsewhere, or with a custom domain, pass the public URL of the website with `--base-url` (or the `RECETTES_BASE_URL` environment variable); without it, the tags are left out:

```sh
recettes build examples/ --base-url https://recipes.example.com/
```

A `sitemap.xml` file listing the pages for search engines is also generated with this URL.

The home page description, for search engines and link previews, can be set with `--description` (the number of recipes by default).

The footer of every page shows the license of the recipes, [Copyrights CC-BY](https://creativecommons.org/licenses/by/4.0/) by default. Pass another one, in Markdown, with `--license` (or an empty string to hide it):

```sh
recettes build examples/ --license "© 2026 Jane Doe, all rights reserved"
```

When building, pictures are downscaled. Desired size can be specified from CLI:

```sh
recettes build examples/ --image-width 760 --thumbnail-width 112
```

Resizing pictures takes time, so resized pictures are kept in a `.recettes-cache/` directory (relative to the current directory), and unchanged pictures are not processed again on the next build. Choose another location (outside the output directory) with `--cache-dir` or the `RECETTES_CACHE_DIR` environment variable:

```sh
recettes build examples/ --cache-dir ~/.cache/recettes/
```

On GitHub Actions, persist this directory between runs with [actions/cache](https://github.com/actions/cache), as in [this repository's workflow](.github/workflows/cd.yaml).

The interface (search, buttons, footer) is available in English, French, Spanish, Italian and German. Recipe pages follow their `lang` property, and the home page the language shared by all recipes (English otherwise). Choose the language of the website, also used for recipes without `lang`, with `--lang` (or the `RECETTES_LANG` environment variable):

```sh
recettes build examples/ --lang fr
```

Recipe pages offer a *Simple* switch to measure ingredients with glasses (🥛 = 200 ml) and spoons (🥄 = 15 ml) instead of a scale. Disable it with:

```sh
recettes build examples/ --no-simple-mode
```

## Development

```sh
uv sync
uv run recettes --help
uv run pytest
uv run pre-commit run --all-files  # Ruff, ty and Prettier
```

## Release

The version comes from the Git tag. Creating a [new release](https://github.com/leplatrem/python-recettes/releases/) will build the package and publish it to PyPI.

## License

CC0 1.0 Universal

The bundled fonts, DM Sans and Playfair Display, are distributed under the [SIL Open Font License](src/recettes/static/fonts/OFL.txt).

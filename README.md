# Recettes

*Recettes* turns Markdown files into a small, static recipe website. Recipes remain easy to edit in GitHub; the generated site is mobile-friendly and needs no application server.

## [Example](https://leplatrem.github.io/python-recettes/)

Look at the [examples/](./examples/) folder and how it turned into [this website](https://leplatrem.github.io/python-recettes/).

## Recipe format

Put one Markdown file per recipe in a directory. Optional photos sit beside the Markdown file and are named after it:

```text
examples/
├── onion-soup.md
├── onion-soup.jpg          # main picture, shown below the ingredients
├── onion-soup-step-2.png   # shown at the end of the "Step 2" section
└── onion-soup-1.webp       # no matching heading: shown at the end of the recipe
```

Section pictures use the slug of a heading: lowercase, accents removed, non-alphanumeric characters replaced by dashes (`## Étape 1` → `etape-1`).

Recipe properties go in YAML front matter. Tags can be a comma-separated string or a YAML list. All properties are optional:

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

Simmer gently until tender.
```

Write ingredient amounts inside `{{ }}` in the recipe text.

*Recettes* reads a number and an optional unit from the start of each expression, including decimals and fractions such as `0.5cac` and `1/2 cac`. Supported units include metric abbreviations, `tbsp`/`tablespoon(s)`, `tsp`/`teaspoon(s)`, `cup(s)`, `oz`/`ounce(s)`, and `lb`/`pound(s)`. A number without a unit is treated as a count. Text without a leading number is kept as written.

The optional `portions` property enables serving controls, and `lang` sets the recipe page's language for browsers and assistive technology.

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

## Development

```sh
uv sync --extra dev
uv run recettes --help
uv run ruff check .
uv run pytest
npx prettier@3.6.2 --check "src/recettes/static/**/*.{js,css}"
```

## Release

The version comes from the Git tag. Creating a [new release](https://github.com/leplatrem/python-recettes/releases/) will build the package and publish it to PyPI.

## License

CC0 1.0 Universal

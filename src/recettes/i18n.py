"""Translations of the website interface."""

from __future__ import annotations

DEFAULT_LANG = "en"

# `{count}` is replaced by a number, `{recettes}` by a link to the project.
STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "search_label": "Search recipes",
        "search_placeholder": "Search {count} recipes",
        "tags_label": "Filter by tag",
        "results_none": "No recipes found",
        "results_one": "{count} recipe",
        "results_other": "{count} recipes",
        "back": "Back",
        "edit": "Edit (opens in a new tab)",
        "ingredients": "Ingredients",
        "simple": "Simple",
        "decrease_servings": "Decrease servings",
        "increase_servings": "Increase servings",
        "photo": "photo",
        "built_with": "Built with {recettes}, the free software that turns Markdown files "
        "into a recipes website.",
    },
    "fr": {
        "search_label": "Rechercher des recettes",
        "search_placeholder": "Rechercher parmi {count} recettes",
        "tags_label": "Filtrer par étiquette",
        "results_none": "Aucune recette trouvée",
        "results_one": "{count} recette",
        "results_other": "{count} recettes",
        "back": "Retour",
        "edit": "Modifier (s’ouvre dans un nouvel onglet)",
        "ingredients": "Ingrédients",
        "simple": "Simple",
        "decrease_servings": "Moins de portions",
        "increase_servings": "Plus de portions",
        "photo": "photo",
        "built_with": "Fait avec {recettes}, le logiciel libre qui transforme des fichiers "
        "Markdown en site de recettes.",
    },
    "es": {
        "search_label": "Buscar recetas",
        "search_placeholder": "Buscar entre {count} recetas",
        "tags_label": "Filtrar por etiqueta",
        "results_none": "No se encontraron recetas",
        "results_one": "{count} receta",
        "results_other": "{count} recetas",
        "back": "Volver",
        "edit": "Editar (se abre en una pestaña nueva)",
        "ingredients": "Ingredientes",
        "simple": "Sencillo",
        "decrease_servings": "Menos raciones",
        "increase_servings": "Más raciones",
        "photo": "foto",
        "built_with": "Hecho con {recettes}, el software libre que convierte archivos "
        "Markdown en un sitio web de recetas.",
    },
    "it": {
        "search_label": "Cerca ricette",
        "search_placeholder": "Cerca tra {count} ricette",
        "tags_label": "Filtra per etichetta",
        "results_none": "Nessuna ricetta trovata",
        "results_one": "{count} ricetta",
        "results_other": "{count} ricette",
        "back": "Indietro",
        "edit": "Modifica (si apre in una nuova scheda)",
        "ingredients": "Ingredienti",
        "simple": "Semplice",
        "decrease_servings": "Meno porzioni",
        "increase_servings": "Più porzioni",
        "photo": "foto",
        "built_with": "Realizzato con {recettes}, il software libero che trasforma file "
        "Markdown in un sito di ricette.",
    },
    "de": {
        "search_label": "Rezepte suchen",
        "search_placeholder": "{count} Rezepte durchsuchen",
        "tags_label": "Nach Schlagwort filtern",
        "results_none": "Keine Rezepte gefunden",
        "results_one": "{count} Rezept",
        "results_other": "{count} Rezepte",
        "back": "Zurück",
        "edit": "Bearbeiten (öffnet in neuem Tab)",
        "ingredients": "Zutaten",
        "simple": "Einfach",
        "decrease_servings": "Weniger Portionen",
        "increase_servings": "Mehr Portionen",
        "photo": "Foto",
        "built_with": "Erstellt mit {recettes}, der freien Software, die Markdown-Dateien "
        "in eine Rezept-Website verwandelt.",
    },
}


def recipes_count(lang: str, count: int) -> str:
    """ "1 recipe", "2 recipes"..."""
    return strings(lang)["results_one" if count == 1 else "results_other"].format(count=count)


def strings(lang: str) -> dict[str, str]:
    """Interface strings for a language tag ("fr-CA" -> French), English by default."""
    primary = lang.split("-")[0].casefold()
    return STRINGS.get(primary, STRINGS[DEFAULT_LANG])

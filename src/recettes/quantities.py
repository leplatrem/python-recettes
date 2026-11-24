"""Ingredient quantities: parsing, units and volumes for the "Simple" mode."""

from __future__ import annotations

import dataclasses
import json
import re
from fractions import Fraction
from functools import cache
from importlib import resources

from recettes.utils import strip_accents

QUANTITY_RE = re.compile(
    r"^(?P<amount>\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)?)"
    r"\s*(?P<unit>(?:c\.?\s*à\.?\s*[sc]\.?|cas|càs|cac|càc|"
    r"cucchiain[oi]|cucchiaio?|"
    r"cdita|cda|cc|ct|tl|el|tsk|msk|ts|ss|fl[_ ]?oz|tablespoons?|tbsp|teaspoons?|tsp|cups?|"
    r"ounces?|oz|pounds?|lbs?|kg|mg|g|ml|cl|l)(?![^\W\d_]))?\s*(?P<name>.*)$",
    re.IGNORECASE,
)
# Conversions to milliliters or grams, used by the "Simple" mode (glasses and spoons).
VOLUME_UNITS_ML = {
    "ml": 1,
    "cl": 10,
    "l": 1000,
    "cups": 240,
    "fl oz": 29.57,
    **dict.fromkeys(
        ["tbsp", "c. à s.", "EL", "cda", "Cc", "CC", "cucchiaio", "cucchiai", "msk", "ss"], 15
    ),
    **dict.fromkeys(
        ["tsp", "c. à c.", "TL", "cdita", "cc", "ct", "cucchiaino", "cucchiaini", "tsk", "ts"], 5
    ),
}
# Units as displayed, from their lowercase spelling without spaces nor dots.
UNIT_ALIASES = {
    "cas": "c. à s.",
    "càs": "c. à s.",
    "cac": "c. à c.",
    "càc": "c. à c.",
    "tl": "TL",
    "el": "EL",
    "fl_oz": "fl oz",
    "floz": "fl oz",
    "tablespoon": "tbsp",
    "tablespoons": "tbsp",
    "teaspoon": "tsp",
    "teaspoons": "tsp",
    "cup": "cups",
    "ounce": "oz",
    "ounces": "oz",
    "pound": "lb",
    "pounds": "lb",
    "lbs": "lb",
}
MASS_UNITS_G = {"mg": 0.001, "g": 1, "kg": 1000, "oz": 28.35, "lb": 453.6}


def parse_quantity(value: str) -> tuple[float | None, str, str]:
    match = QUANTITY_RE.fullmatch(value.strip())
    if not match:
        return None, "", value.strip()
    amount_text = match.group("amount").replace(" ", "").replace(",", ".")
    try:
        amount = float(Fraction(amount_text))
    except (ValueError, ZeroDivisionError):
        return None, "", value.strip()
    raw_unit = (match.group("unit") or "").replace(" ", "").replace(".", "")
    normalized_unit = raw_unit.lower()
    # Case matters for "cc": Italian "Cc"/"CC" are tablespoons, "cc" teaspoons.
    default = raw_unit if normalized_unit == "cc" else normalized_unit
    unit = UNIT_ALIASES.get(normalized_unit, default)
    return amount, unit, match.group("name").strip()


def name_words(text: str) -> tuple[str, ...]:
    """Lowercase words without accents nor plural "s" ("Pépites de chocolat" -> pepite, de...)."""
    words = re.findall(r"[a-z0-9]+", strip_accents(text.casefold()))
    return tuple(word[:-1] if len(word) > 3 and word.endswith("s") else word for word in words)


@cache
def densities() -> list[tuple[tuple[str, ...], float]]:
    """Known ingredient names (as words) with their density, longest names first."""
    path = resources.files("recettes") / "densities.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    names = [
        (name_words(name), float(entry["density"]))
        for entry in entries.values()
        for name in entry["names"]
    ]
    return sorted(names, key=lambda item: (len(item[0]), len(" ".join(item[0]))), reverse=True)


def find_density(name: str) -> float | None:
    words = name_words(name)
    for candidate, density in densities():
        size = len(candidate)
        if any(words[i : i + size] == candidate for i in range(len(words) - size + 1)):
            return density
    return None


def volume_ml(amount: float | None, unit: str, name: str, lang: str = "") -> float | None:
    """Volume of an ingredient in milliliters, if it can be measured with glasses and spoons."""
    if amount is None:
        return None
    # "cc" is a teaspoon in French ("cuillère à café"), but cubic centimeters in English.
    if unit == "cc" and lang.casefold().startswith("en"):
        return amount
    if unit in VOLUME_UNITS_ML:
        return amount * VOLUME_UNITS_ML[unit]
    if unit in MASS_UNITS_G:
        density = find_density(name)
        if density is not None:
            return amount * MASS_UNITS_G[unit] / density
    return None


@dataclasses.dataclass
class Ingredient:
    """An ingredient written as `{{ raw }}` in a recipe, e.g. `{{ 50g of butter }}`."""

    raw: str
    amount: float | None
    unit: str
    name: str
    # Volume in milliliters, for the "Simple" mode.
    ml: float | None = None

    @classmethod
    def parse(cls, raw: str) -> Ingredient:
        amount, unit, name = parse_quantity(raw)
        return cls(raw=raw, amount=amount, unit=unit, name=name)


def aggregate_ingredients(ingredients: list[Ingredient]) -> list[Ingredient]:
    """Sum the amounts of ingredients with the same unit and name."""
    grouped: dict[tuple[str, str], Ingredient] = {}
    for ingredient in ingredients:
        normalized_name = " ".join(ingredient.name.casefold().split())
        key = ("plain" if ingredient.amount is None else ingredient.unit, normalized_name)
        if key not in grouped:
            grouped[key] = dataclasses.replace(ingredient)
        elif ingredient.amount is not None:
            grouped[key].amount = (grouped[key].amount or 0) + ingredient.amount
    return list(grouped.values())


def format_amount(amount: float) -> str:
    return f"{round(amount, 2):.2f}".rstrip("0").rstrip(".")

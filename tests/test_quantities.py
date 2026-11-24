import pytest

from recettes.quantities import (
    Ingredient,
    aggregate_ingredients,
    find_density,
    parse_quantity,
    volume_ml,
)


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


def test_cc_is_cubic_centimeters_in_english() -> None:
    assert volume_ml(10, "cc", "of milk", "en") == 10
    assert volume_ml(10, "cc", "of milk", "en-GB") == 10
    assert volume_ml(10, "cc", "de lait", "fr") == 50
    assert volume_ml(10, "cc", "de lait") == 50

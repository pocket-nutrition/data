"""Unit tests for the EFSA dietary reference values loader (no DB, no network)."""

import pytest

from db.models import EfsaDrvValue
from loaders.efsa_drv import VALUE_KINDS, explode_rows, parse_pal, parse_value


# ── parse_value ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    # A plain number is both bounds of a point value.
    (2.5, ("2.5", 2.5, 2.5, False)),
    (900, ("900", 900.0, 900.0, False)),
    # Pregnancy and lactation rows are increments on top of the non-pregnant value.
    ("(+) 70", ("(+) 70", 70.0, 70.0, True)),
    ("(+) 0.29", ("(+) 0.29", 0.29, 0.29, True)),
    ("(+) 100–200", ("(+) 100–200", 100.0, 200.0, True)),
    # Ranges come with an en dash or a hyphen.
    ("45–60", ("45–60", 45.0, 60.0, False)),
    ("0.8-1.0", ("0.8-1.0", 0.8, 1.0, False)),
    # Not determined / not applicable: kept as raw text, no number.
    ("ND", ("ND", None, None, False)),
    ("NA.", ("NA.", None, None, False)),
])
def test_parse_value(raw, expected):
    assert parse_value(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_parse_value_empty_is_absent(raw):
    assert parse_value(raw) is None


def test_parse_value_unparseable_text_keeps_raw_without_numbers():
    assert parse_value("see opinion") == ("see opinion", None, None, False)


# ── parse_pal ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("label, expected", [
    ("18–29 years PAL=1.4", 1.4),
    ("40–49 year PAL=2.0", 2.0),   # upstream typo "year" must not break parsing
    ("≥ 18 years", None),
    ("6 months", None),
])
def test_parse_pal(label, expected):
    assert parse_pal(label) == expected


# ── explode_rows ─────────────────────────────────────────────────────────────

def _row(**overrides):
    base = {
        "Classification": "Minerals", "Name": "Iron", "Translated": "Iron",
        "Target population": "Adults", "Target population Description": "Adults",
        "From Age": 18, "To Age": 999, "Age range": "18–99", "Age Unit": "y",
        "Age displayed": "≥ 18 years", "Male": 1, "Female": 0, "Sex": "Male",
        "Scientific Opinion AR/PRI or AI or RI LINK": "https://example.org/generic",
        "Additional information related to AR/PRI or AI or RI results": "",
    }
    for kind in VALUE_KINDS:
        base.setdefault(kind.source, "")
        base.setdefault(f"{kind.source} Unit", "")
    base.update(overrides)
    return base


def test_explode_one_row_per_present_value_kind():
    row = _row(**{
        "ARs": 6, "ARs Unit": "mg/day",
        "PRIs": 11, "PRIs Unit": "mg/day",
        "UL": "ND",
    })
    out = explode_rows([row])
    assert sorted(r["value_kind"] for r in out) == ["ar", "pri", "ul"]
    pri = next(r for r in out if r["value_kind"] == "pri")
    assert pri["value_min"] == 11.0 and pri["value_max"] == 11.0
    assert pri["unit"] == "mg/day"
    assert pri["nutrient"] == "Iron"
    assert pri["is_male"] is True and pri["is_female"] is False


def test_explode_keeps_the_trimester_that_distinguishes_duplicate_looking_rows():
    rows = [
        _row(Name="Energy", **{"Target population": "Pregnant women",
                               "Target population Description": "Pregnant women (1st trimester)",
                               "ARs alt": "(+) 70", "ARs alt Unit": "kcal/day"}),
        _row(Name="Energy", **{"Target population": "Pregnant women",
                               "Target population Description": "Pregnant women (3rd trimester)",
                               "ARs alt": "(+) 500", "ARs alt Unit": "kcal/day"}),
    ]
    out = explode_rows(rows)
    assert [r["population_description"] for r in out] == [
        "Pregnant women (1st trimester)", "Pregnant women (3rd trimester)",
    ]
    assert all(r["value_kind"] == "ar_kcal" and r["is_increment"] for r in out)
    assert [r["source_row"] for r in out] == [0, 1]


def test_explode_parses_pal_from_the_age_label():
    row = _row(Name="Energy", **{"Age displayed": "30–39 years PAL=1.6",
                                 "ARs alt": 2588, "ARs alt Unit": "kcal/day"})
    (value,) = explode_rows([row])
    assert value["pal"] == 1.6
    assert value["age_label"] == "30–39 years PAL=1.6"


def test_explode_uses_the_kind_link_then_falls_back_to_the_generic_one():
    row = _row(**{
        "UL": 40, "UL Unit": "mg/day",
        "Scientific Opinion UL LINK": "https://example.org/ul",
        "AIs": 7, "AIs Unit": "mg/day",
    })
    by_kind = {r["value_kind"]: r for r in explode_rows([row])}
    assert by_kind["ul"]["source_link"] == "https://example.org/ul"
    assert by_kind["ai"]["source_link"] == "https://example.org/generic"


def test_explode_kcal_alternative_borrows_the_ar_link():
    row = _row(Name="Energy", **{
        "ARs": 9.8, "ARs Unit": "MJ/day", "ARs alt": 2338, "ARs alt Unit": "kcal/day",
        "Scientific Opinion ARs LINK": "https://example.org/energy",
    })
    by_kind = {r["value_kind"]: r for r in explode_rows([row])}
    assert by_kind["ar_kcal"]["source_link"] == "https://example.org/energy"


def test_every_exploded_key_is_a_real_orm_column():
    row = _row(**{"PRIs": 11, "PRIs Unit": "mg/day"})
    orm_columns = {c.key for c in EfsaDrvValue.__table__.columns}
    for value in explode_rows([row]):
        assert set(value) <= orm_columns, set(value) - orm_columns

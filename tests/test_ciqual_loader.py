"""Unit tests for the Ciqual loader parsing logic (no DB, no network)."""

import pandas as pd
import pytest

from loaders.ciqual import _parse_french_float


@pytest.mark.parametrize("raw, expected", [
    ("12,5", 12.5),
    ("0,0", 0.0),
    ("100", 100.0),
    ("-", None),
    ("< 0,1", 0.05),
    ("<0,05", 0.025),
    ("< 5", 2.5),
    ("traces", 0.0),
    ("Traces", 0.0),
    ("", None),
    (float("nan"), None),
])
def test_parse_french_float(raw, expected):
    assert _parse_french_float(raw) == expected


def test_vitamin_a_maps_to_retinol_activity_equivalents():
    """vitamin_a_ug must be total vitamin A activity, not retinol alone.

    Retinol is ~0 for every plant food, so mapping it would report broccoli or carrots as
    vitamin-A free. The activity column includes provitamin-A carotenoids and matches the
    USDA loaders, which use "Vitamin A, RAE".
    """
    from loaders.ciqual import COLUMN_MAP

    sources = [header for header, target in COLUMN_MAP.items() if target == "vitamin_a_ug"]
    assert len(sources) == 1
    assert sources[0].startswith("Activité\nvitaminique\nA")

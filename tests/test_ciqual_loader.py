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

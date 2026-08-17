"""Unit tests for the OFF loader column filtering logic (no DB, no network)."""

from db.models import OffProduct
from loaders.off import COLUMNS, COLUMN_MAP, NUTRIENT_COLS


def test_column_map_covers_nutrient_cols():
    """Every nutrient column name used in logic must appear in the column map values."""
    mapped = set(COLUMN_MAP.values())
    for col in NUTRIENT_COLS:
        assert col in mapped, f"{col!r} is in NUTRIENT_COLS but not in COLUMN_MAP values"


def test_every_kept_column_resolves_to_a_real_orm_column():
    """
    Guards the one mistake that makes a kept column useless.

    ``load`` selects with ``usecols=lambda c: c in COLUMNS`` and then applies
    ``rename(columns=COLUMN_MAP)``, so a name that survives the rename without matching an
    ``off_products`` column reaches ``insert(OffProduct)`` as an unknown key. That does fail —
    loudly, mid-load, after the download — which is a slow and expensive way to discover a typo.
    Asserting the mapping here turns it into a test failure instead.
    """
    orm_columns = {c.key for c in OffProduct.__table__.columns}
    unresolved = sorted(
        {COLUMN_MAP.get(col, col) for col in COLUMNS} - orm_columns
    )
    assert unresolved == [], (
        f"these OFF columns map to no off_products column: {unresolved} — "
        "either add the ORM column or add a COLUMN_MAP entry"
    )


def test_serving_quantity_is_kept_and_cast_numeric():
    """
    The manufacturer's declared per-serving weight (e.g. "1/4 pizza (100 g)" → 100.0) is what lets
    a pizza or tart offer a real "1 part" shortcut instead of only a whole-package one. It must be
    kept from the CSV, resolve to a real column, and be included in the numeric-cast list — an OFF
    export loads every kept column as `dtype=str`, so a Float ORM column left off that list would
    fail the insert the first time a value made it past `usecols`.
    """
    from loaders.off import NUMERIC_COLS

    assert "serving_quantity" in COLUMNS
    assert "serving_quantity" in NUMERIC_COLS
    assert "serving_quantity" in {c.key for c in OffProduct.__table__.columns}


def test_brand_is_carried_through_the_rename():
    """
    OFF calls it ``brands``; the ORM calls it ``brand``. Both halves are required.

    Without this the search API cannot tell two products apart: thousands of OFF entries have a
    ``product_name`` that is just the bare food word, so a client renders several rows all reading
    "Poulet". Keeping the column but forgetting the rename, or vice versa, silently loses that.
    """
    assert "brands" in COLUMNS
    assert COLUMN_MAP["brands"] == "brand"
    assert "brand" in {c.key for c in OffProduct.__table__.columns}

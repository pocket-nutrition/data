"""USDA Table of Cooking Yields for Meat and Poultry — loader.

Downloads USDA_CookingYields_MeatPoultry02.xlsx (Release 2, 2014) and upserts
rows into usda_cooking_yields.  Values are direct weight-loss measurements from
controlled cooking studies (not energy-ratio estimates).

Source URL:
  https://www.ars.usda.gov/ARSUserFiles/80400535/Data/retn/USDA_CookingYields_MeatPoultry02.xlsx
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

import openpyxl
from sqlalchemy.dialects.postgresql import insert

from db.connection import engine
from db.models import UsdaCookingYield, init_db
from loaders.base import BaseLoader

log = logging.getLogger(__name__)

USDA_COOKING_YIELDS_URL = (
    "https://www.ars.usda.gov/ARSUserFiles/80400535/Data/retn/"
    "USDA_CookingYields_MeatPoultry02.xlsx"
)

def _cell_str(val: object) -> str:
    return str(val).strip() if val is not None else ""


def _to_float(val: object) -> float | None:
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.strip().replace(",", "."))
        except ValueError:
            return None
    return None


def _find_header(sheet_rows: list[tuple]) -> tuple[int, dict[str, int]] | None:
    """Return (row_index, col_map) for the first row that looks like a data header.

    The actual USDA xlsx has these columns (exact names):
      'Yield Description'   → food_description  (col 2)
      'Preparation Method'  → cooking_description (col 3)
      'Cooking Yield %'     → cooking_yield_pct  (col 4)
      'Moisture Gain/Loss %'→ moisture_change_pct (col 9)
      'Fat Gain/Loss %'     → fat_change_pct      (col 10)

    Patterns are checked independently per column type so that
    'Yield Description' (food) and 'Cooking Yield %' (yield pct)
    don't clobber each other.
    """
    for i, row in enumerate(sheet_rows[:40]):
        cells = [_cell_str(c).lower() for c in row]
        # Must contain a 'cooking yield' column to qualify as a data header
        if not any("cooking yield" in c for c in cells):
            continue
        col_map: dict[str, int] = {}
        for j, c in enumerate(cells):
            if not c:
                continue
            # Yield pct: "cooking yield" is the specific phrase for the % column
            if "cooking yield" in c and "col_yield" not in col_map:
                col_map["col_yield"] = j
            # Food description: "yield description" or plain "description"
            if ("yield description" in c or ("description" in c and "cooking" not in c)) and "col_food" not in col_map:
                col_map["col_food"] = j
            # Cooking method: "preparation" or "method" (not the yield column)
            if ("preparation" in c or ("method" in c and "cooking" not in c)) and "col_cook" not in col_map:
                col_map["col_cook"] = j
            # Moisture change
            if "moisture" in c and "col_moisture" not in col_map:
                col_map["col_moisture"] = j
            # Fat change: require "gain" or "loss" to avoid matching "fat" in other contexts
            if "fat" in c and ("gain" in c or "loss" in c) and "col_fat" not in col_map:
                col_map["col_fat"] = j
        if "col_yield" in col_map and "col_food" in col_map:
            return i, col_map
    return None


def _parse_sheet(ws: object) -> Iterator[dict]:
    all_rows = list(ws.iter_rows(values_only=True))
    result = _find_header(all_rows)
    if result is None:
        return
    header_idx, col_map = result

    col_food = col_map["col_food"]
    col_yield = col_map["col_yield"]
    col_cook = col_map.get("col_cook")
    col_moisture = col_map.get("col_moisture")
    col_fat = col_map.get("col_fat")

    empty_streak = 0
    for row in all_rows[header_idx + 1:]:
        n = len(row)
        food_val = row[col_food] if col_food < n else None
        yield_val = row[col_yield] if col_yield < n else None
        cook_val = row[col_cook] if col_cook is not None and col_cook < n else None

        all_empty = (food_val is None and yield_val is None and cook_val is None)
        if all_empty:
            empty_streak += 1
            if empty_streak >= 5:
                break
            continue
        empty_streak = 0

        yield_f = _to_float(yield_val)
        if yield_f is None:
            continue

        food_str = _cell_str(food_val)
        cook_str = _cell_str(cook_val)
        if not food_str:
            continue

        # When no separate cooking column exists, the knowledge script will
        # detect the method from food_description via _COOKING_TERMS regex.
        if not cook_str:
            cook_str = food_str

        moisture_val = row[col_moisture] if col_moisture is not None and col_moisture < n else None
        fat_val = row[col_fat] if col_fat is not None and col_fat < n else None

        yield {
            "food_description": food_str,
            "cooking_description": cook_str,
            "cooking_yield_pct": yield_f,
            "moisture_change_pct": _to_float(moisture_val),
            "fat_change_pct": _to_float(fat_val),
            "source_file": "USDA_CookingYields_MeatPoultry02.xlsx",
            "source_release": "Release 2 (2014)",
        }


class UsdaCookingYieldsLoader(BaseLoader):
    name = "usda_cooking_yields"
    filename = "USDA_CookingYields_MeatPoultry02.xlsx"
    url = USDA_COOKING_YIELDS_URL

    def load(self, path: Path) -> None:
        init_db()
        rows = list(self._parse_xlsx(path))
        if not rows:
            log.warning("[%s] no rows extracted from XLSX — check column layout", self.name)
            return
        log.info("[%s] parsed %d rows", self.name, len(rows))

        update_cols = ["cooking_yield_pct", "moisture_change_pct", "fat_change_pct"]
        stmt = insert(UsdaCookingYield)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_usda_cooking_yield",
            set_={c: getattr(stmt.excluded, c) for c in update_cols},
        )

        with engine.connect() as conn:
            conn.execute(stmt, rows)
            conn.commit()
        log.info("[%s] upserted %d rows into usda_cooking_yields", self.name, len(rows))

    def _parse_xlsx(self, path: Path) -> Iterator[dict]:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                count = 0
                for row in _parse_sheet(ws):
                    count += 1
                    yield row
                if count:
                    log.info("[%s] sheet %r → %d rows", self.name, sheet_name, count)
        finally:
            wb.close()

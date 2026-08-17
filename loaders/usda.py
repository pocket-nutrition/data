"""USDA FoodData Central — FNDDS survey food loader.

Downloads FoodData_Central_survey_food_json_2024-10-31.zip, extracts the
JSON inside, flattens the nested foodNutrients arrays, and upserts into
usda_foods. Values are per 100 g.

During load(), prints a unit-inspection report: exact nutrient names and units
as reported by the USDA, plus a count of cooked vs. raw entries by description.
"""

import json
import logging
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy.dialects.postgresql import insert

from db.connection import engine
from db.models import UsdaFood, init_db
from loaders.base import BaseLoader

log = logging.getLogger(__name__)

USDA_URL = (
    "https://fdc.nal.usda.gov/fdc-datasets/"
    "FoodData_Central_survey_food_json_2024-10-31.zip"
)

# USDA nutrient IDs (FDC) → (ORM column, expected name, expected unit)
# Includes alternate IDs used by FNDDS (2047 = Energy, FNDDS-specific).
NUTRIENT_MAP: Dict[int, Tuple[str, str, str]] = {
    1008: ("energy_kcal",     "Energy",                      "kcal"),
    2047: ("energy_kcal",     "Energy (Atwater General Factors)", "kcal"),
    1003: ("protein_g",       "Protein",                     "g"),
    1004: ("fat_g",           "Total lipid (fat)",           "g"),
    1005: ("carbohydrates_g", "Carbohydrate, by difference", "g"),
    1079: ("fiber_g",         "Fiber, total dietary",        "g"),
    1093: ("sodium_mg",       "Sodium, Na",                  "mg"),
}

# Old USDA nutrient numbers (3-digit) → FDC IDs, for flat JSON formats
_NUMBER_TO_ID: Dict[str, int] = {
    "208": 1008, "957": 2047,
    "203": 1003, "204": 1004, "205": 1005,
    "291": 1079, "307": 1093,
}

# Nutrient IDs included in the unit inspection log
INSPECTION_IDS = [1008, 1003, 1004, 1005, 1093]

CHUNK_SIZE = 1_000


def _detect_format(food_nutrients: List[dict]) -> str:
    """Return parsing strategy based on the structure of the first nutrient entry."""
    if not food_nutrients:
        return "empty"
    first = food_nutrients[0]
    if isinstance(first.get("nutrient"), dict):
        return "nested"          # {nutrient: {id, name, unitName}, amount}
    if "nutrientId" in first:
        return "flat_id"         # {nutrientId, value/amount, unitName}
    if "number" in first or "nutrientNumber" in first:
        return "flat_number"     # {number:"208", name, amount}
    return "unknown"


def _extract_nutrients(food_nutrients: List[dict], fmt: str = "") -> Dict[str, Optional[float]]:
    """Flatten foodNutrients into ORM column → value, trying all known formats."""
    if not fmt:
        fmt = _detect_format(food_nutrients)
    result: Dict[str, Optional[float]] = {}
    for fn in food_nutrients:
        nid: Optional[int] = None
        amount: Optional[float] = None

        if fmt == "nested":
            nid = fn.get("nutrient", {}).get("id")
            amount = fn.get("amount")
        elif fmt == "flat_id":
            nid = fn.get("nutrientId")
            amount = fn.get("value") if fn.get("value") is not None else fn.get("amount")
        elif fmt == "flat_number":
            num = str(fn.get("number") or fn.get("nutrientNumber") or "")
            nid = _NUMBER_TO_ID.get(num)
            amount = fn.get("amount") if fn.get("amount") is not None else fn.get("value")
        else:
            # Unknown format: try all field combinations
            nid = (fn.get("nutrient", {}).get("id")
                   or fn.get("nutrientId")
                   or _NUMBER_TO_ID.get(str(fn.get("number") or fn.get("nutrientNumber") or "")))
            amount = fn.get("amount") if fn.get("amount") is not None else fn.get("value")

        if nid in NUTRIENT_MAP:
            orm_col, _, _ = NUTRIENT_MAP[nid]
            if orm_col not in result:   # first match wins (e.g. 1008 before 2047)
                result[orm_col] = amount
    return result


def _build_row(food: dict) -> dict:
    cat = food.get("wweiaFoodCategory") or {}
    row = {
        "fdc_id":        food["fdcId"],
        "description":   food.get("description", ""),
        "food_code":     food.get("foodCode"),
        "wweia_category": cat.get("wweiaFoodCategoryDescription"),
    }
    row.update(_extract_nutrients(food.get("foodNutrients", [])))
    return row


def _upsert_batch(conn, batch: list[dict]) -> int:
    df = pd.DataFrame(batch)
    nutrient_cols = [v[0] for v in NUTRIENT_MAP.values()]
    for col in nutrient_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    rows = df.where(pd.notna(df), None).to_dict("records")
    if not rows:
        return 0
    stmt = insert(UsdaFood).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["fdc_id"],
        set_={c: stmt.excluded[c] for c in df.columns if c != "fdc_id"},
    )
    conn.execute(stmt)
    conn.commit()
    return len(rows)


class UsdaLoader(BaseLoader):
    name = "usda-fndds"
    filename = "usda_fndds_2024.zip"
    url = USDA_URL

    def load(self, path: Path) -> None:
        init_db()

        # Locate and parse the JSON file inside the ZIP
        with zipfile.ZipFile(path) as zf:
            json_names = [n for n in zf.namelist() if n.endswith(".json")]
            if not json_names:
                raise RuntimeError(f"[{self.name}] No JSON file found in ZIP")
            json_name = json_names[0]
            log.info("[%s] Reading %s from ZIP", self.name, json_name)
            with zf.open(json_name) as f:
                data = json.load(f)

        # The top-level key varies by FDC data type
        foods: Optional[List[dict]] = None
        for key in ("SurveyFoods", "FoundationFoods", "Foods", "foods"):
            if key in data:
                foods = data[key]
                log.info("[%s] Found %d entries under key '%s'", self.name, len(foods), key)
                break
        if foods is None:
            raise RuntimeError(
                f"[{self.name}] Unknown JSON structure; top-level keys: {list(data.keys())}"
            )

        # ── Unit inspection report ───────────────────────────────────────────
        log.info("[%s] ===== Unit Inspection Report =====", self.name)
        if foods:
            # Detect JSON format from first food that has any nutrients
            detected_fmt = "empty"
            for food in foods[:20]:
                fn_list = food.get("foodNutrients", [])
                if fn_list:
                    detected_fmt = _detect_format(fn_list)
                    break
            log.info("[%s]  Detected foodNutrients format: %s", self.name, detected_fmt)

            # Log raw structure of first nutrient entry for debugging
            for food in foods[:5]:
                fn_list = food.get("foodNutrients", [])
                if fn_list:
                    log.info("[%s]  Sample raw foodNutrient entry: %s", self.name, fn_list[0])
                    break

            # Find the first food that has one of the inspection nutrients
            sample_food_nutrients: List[dict] = []
            for food in foods[:200]:
                fn_list = food.get("foodNutrients", [])
                extracted = _extract_nutrients(fn_list, detected_fmt)
                if any(extracted.get(NUTRIENT_MAP[nid][0]) is not None for nid in INSPECTION_IDS if nid in NUTRIENT_MAP):
                    sample_food_nutrients = fn_list
                    log.info("[%s]  Using food '%s' for sample values", self.name, food.get("description", "?"))
                    break

            # Build lookup by nutrient ID for the sample food
            if detected_fmt == "nested":
                sample_map: Dict[int, dict] = {
                    fn.get("nutrient", {}).get("id"): fn for fn in sample_food_nutrients
                }
            elif detected_fmt == "flat_id":
                sample_map = {fn.get("nutrientId"): fn for fn in sample_food_nutrients}
            elif detected_fmt == "flat_number":
                sample_map = {
                    _NUMBER_TO_ID.get(str(fn.get("number") or fn.get("nutrientNumber") or "")): fn
                    for fn in sample_food_nutrients
                }
            else:
                sample_map = {}

            for nid in INSPECTION_IDS:
                if nid not in NUTRIENT_MAP:
                    continue
                orm_col, _, _ = NUTRIENT_MAP[nid]
                fn = sample_map.get(nid)
                if fn:
                    if detected_fmt == "nested":
                        actual_name = fn.get("nutrient", {}).get("name", "?")
                        actual_unit = fn.get("nutrient", {}).get("unitName", "?")
                        sample_val  = fn.get("amount")
                    else:
                        actual_name = fn.get("nutrientName") or fn.get("name", "?")
                        actual_unit = fn.get("unitName", "?")
                        sample_val  = fn.get("value") if fn.get("value") is not None else fn.get("amount")
                    log.info(
                        "[%s]  %-20s → nutrient: %-42s | unit: %-5s | sample: %s",
                        self.name, orm_col, repr(actual_name), actual_unit, sample_val,
                    )
                else:
                    log.warning(
                        "[%s]  %-20s → NOT FOUND in sample food (id=%d)",
                        self.name, orm_col, nid,
                    )

        cooked_kw = {"cook", "boil", "roast", "grill", "fri", "bake"}
        n_cooked = sum(
            1 for f in foods
            if any(kw in f.get("description", "").lower() for kw in cooked_kw)
        )
        n_raw = sum(1 for f in foods if "raw" in f.get("description", "").lower())
        log.info("[%s]  Cooked entries : %d  |  Raw entries : %d", self.name, n_cooked, n_raw)
        log.info("[%s] ===================================", self.name)
        # ── End inspection ──────────────────────────────────────────────────

        total_inserted = 0
        batch: List[dict] = []
        with engine.connect() as conn:
            for food in foods:
                batch.append(_build_row(food))
                if len(batch) >= CHUNK_SIZE:
                    total_inserted += _upsert_batch(conn, batch)
                    batch = []
            if batch:
                total_inserted += _upsert_batch(conn, batch)

        log.info("[%s] upserted %d foods", self.name, total_inserted)

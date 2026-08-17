"""USDA FoodData Central — SR Legacy (Standard Reference) loader.

Downloads FoodData_Central_sr_legacy_food_json_2018-04.zip, extracts the
JSON inside, and upserts into usda_sr_foods. Values are per 100 g.

SR Legacy is the 2018 snapshot of the Standard Reference database, the
historical backbone of US food composition data. It covers ~8 000 basic foods
(raw agricultural commodities, processed staples) with broad nutrient coverage.
It complements FNDDS (survey foods) and Foundation Foods (lab reference).
"""

import json
import logging
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy.dialects.postgresql import insert

from db.connection import engine
from db.models import UsdaSrFood, UsdaSrFoodPortion, init_db
from loaders.base import BaseLoader

log = logging.getLogger(__name__)

_URL = (
    "https://fdc.nal.usda.gov/fdc-datasets/"
    "FoodData_Central_sr_legacy_food_json_2018-04.zip"
)

# FDC nutrient IDs → (ORM column, expected name, expected unit)
# SR Legacy uses the same nutrient ID scheme as Foundation Foods.
NUTRIENT_MAP: Dict[int, Tuple[str, str, str]] = {
    1008: ("energy_kcal",            "Energy",                        "kcal"),
    1003: ("protein_g",              "Protein",                       "g"),
    1004: ("fat_g",                  "Total lipid (fat)",             "g"),
    1005: ("carbohydrates_g",        "Carbohydrate, by difference",   "g"),
    1079: ("fiber_g",                "Fiber, total dietary",          "g"),
    1093: ("sodium_mg",              "Sodium, Na",                    "mg"),
    1087: ("calcium_mg",             "Calcium, Ca",                   "mg"),
    1089: ("iron_mg",                "Iron, Fe",                      "mg"),
    1090: ("magnesium_mg",           "Magnesium, Mg",                 "mg"),
    1091: ("phosphorus_mg",          "Phosphorus, P",                 "mg"),
    1092: ("potassium_mg",           "Potassium, K",                  "mg"),
    1095: ("zinc_mg",                "Zinc, Zn",                      "mg"),
    1162: ("vitamin_c_mg",           "Vitamin C, total ascorbic acid","mg"),
    1114: ("vitamin_d_ug",           "Vitamin D (D2 + D3)",           "µg"),
    1104: ("vitamin_a_ug",           "Vitamin A, RAE",                "µg"),
    1175: ("vitamin_b6_mg",          "Vitamin B-6",                   "mg"),
    1178: ("vitamin_b12_ug",         "Vitamin B-12",                  "µg"),
    1167: ("niacin_mg",              "Niacin",                        "mg"),
    1258: ("saturated_fat_g",        "Fatty acids, total saturated",  "g"),
    1292: ("monounsaturated_fat_g",  "Fatty acids, total monounsaturated", "g"),
    1293: ("polyunsaturated_fat_g",  "Fatty acids, total polyunsaturated", "g"),
    1253: ("cholesterol_mg",         "Cholesterol",                   "mg"),
}

INSPECTION_IDS = [1008, 1003, 1004, 1005, 1093, 1087, 1162]

CHUNK_SIZE = 500


def _extract_nutrients(food_nutrients: List[dict]) -> Dict[str, Optional[float]]:
    result: Dict[str, Optional[float]] = {}
    for fn in food_nutrients:
        nutrient = fn.get("nutrient") or {}
        nid = nutrient.get("id")
        amount = fn.get("amount")
        if nid in NUTRIENT_MAP:
            orm_col = NUTRIENT_MAP[nid][0]
            if orm_col not in result:
                result[orm_col] = amount
    return result


def _build_row(food: dict) -> dict:
    cat = food.get("foodCategory") or {}
    row = {
        "fdc_id":        food["fdcId"],
        "description":   food.get("description", ""),
        "food_category": cat.get("description"),
        "ndb_number":    food.get("ndbNumber"),
    }
    row.update(_extract_nutrients(food.get("foodNutrients", [])))
    return row


def _upsert_batch(conn, batch: List[dict]) -> int:
    df = pd.DataFrame(batch)
    nutrient_cols = [v[0] for v in NUTRIENT_MAP.values()]
    for col in nutrient_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    rows = df.where(pd.notna(df), None).to_dict("records")
    if not rows:
        return 0
    stmt = insert(UsdaSrFood).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["fdc_id"],
        set_={c: stmt.excluded[c] for c in df.columns if c != "fdc_id"},
    )
    conn.execute(stmt)
    conn.commit()
    return len(rows)


def _build_portion_rows(food: dict) -> List[dict]:
    fdc_id = food["fdcId"]
    rows: List[dict] = []
    for p in food.get("foodPortions") or []:
        gram_weight = p.get("gramWeight")
        if not gram_weight or gram_weight <= 0:
            continue
        amount = float(p.get("amount") or 1.0)
        desc = (
            p.get("portionDescription")
            or p.get("modifier")
            or (p.get("measureUnit") or {}).get("name")
            or ""
        ).strip()
        if not desc:
            continue
        rows.append({
            "fdc_id":       fdc_id,
            "description":  desc,
            "gram_weight":  gram_weight,
            "amount":       amount,
        })
    return rows


def _upsert_portions(conn, batch: List[dict]) -> int:
    if not batch:
        return 0
    # Deduplicate by (fdc_id, description); keep highest gram_weight on collision.
    seen: dict[tuple, dict] = {}
    for row in batch:
        key = (row["fdc_id"], row["description"])
        if key not in seen or row["gram_weight"] > seen[key]["gram_weight"]:
            seen[key] = row
    batch = list(seen.values())
    stmt = insert(UsdaSrFoodPortion).values(batch)
    stmt = stmt.on_conflict_do_update(
        index_elements=["fdc_id", "description"],
        set_={"gram_weight": stmt.excluded.gram_weight, "amount": stmt.excluded.amount},
    )
    conn.execute(stmt)
    conn.commit()
    return len(batch)


class UsdaSrLoader(BaseLoader):
    name = "usda-sr"
    filename = "usda_sr_legacy_2018.zip"
    url = _URL

    def load(self, path: Path) -> None:
        init_db()

        with zipfile.ZipFile(path) as zf:
            json_names = [n for n in zf.namelist() if n.endswith(".json")]
            if not json_names:
                raise RuntimeError(f"[{self.name}] No JSON file found in ZIP")
            with zf.open(json_names[0]) as f:
                data = json.load(f)

        foods: Optional[List[dict]] = None
        for key in ("SRLegacyFoods", "FoundationFoods", "Foods", "foods"):
            if key in data:
                foods = data[key]
                log.info("[%s] Found %d entries under key '%s'", self.name, len(foods), key)
                break
        if foods is None:
            raise RuntimeError(
                f"[{self.name}] Unknown JSON structure; top-level keys: {list(data.keys())}"
            )

        log.info("[%s] ===== Unit Inspection Report =====", self.name)
        if foods:
            sample_food: Optional[dict] = next(
                (f for f in foods[:200] if f.get("foodNutrients")), None
            )
            if sample_food:
                log.info("[%s]  Using food '%s'", self.name, sample_food.get("description", "?"))
                sample_map = {
                    fn.get("nutrient", {}).get("id"): fn
                    for fn in sample_food.get("foodNutrients", [])
                }
                for nid in INSPECTION_IDS:
                    if nid not in NUTRIENT_MAP:
                        continue
                    orm_col, _, _ = NUTRIENT_MAP[nid]
                    fn = sample_map.get(nid)
                    if fn:
                        actual_name = fn.get("nutrient", {}).get("name", "?")
                        actual_unit = fn.get("nutrient", {}).get("unitName", "?")
                        log.info(
                            "[%s]  %-25s → %-42s | unit: %s",
                            self.name, orm_col, repr(actual_name), actual_unit,
                        )
                    else:
                        log.warning("[%s]  %-25s → NOT FOUND (id=%d)", self.name, orm_col, nid)

            cooked_kw = {"cook", "boil", "roast", "grill", "fri", "bake"}
            n_cooked = sum(
                1 for f in foods
                if any(kw in f.get("description", "").lower() for kw in cooked_kw)
            )
            n_raw = sum(1 for f in foods if "raw" in f.get("description", "").lower())
            log.info("[%s]  Cooked: %d  |  Raw: %d", self.name, n_cooked, n_raw)
        log.info("[%s] ===================================", self.name)

        total_inserted = 0
        total_portions = 0
        batch: List[dict] = []
        portion_batch: List[dict] = []
        with engine.connect() as conn:
            for food in foods:
                batch.append(_build_row(food))
                portion_batch.extend(_build_portion_rows(food))
                if len(batch) >= CHUNK_SIZE:
                    total_inserted += _upsert_batch(conn, batch)
                    total_portions += _upsert_portions(conn, portion_batch)
                    batch = []
                    portion_batch = []
            if batch:
                total_inserted += _upsert_batch(conn, batch)
                total_portions += _upsert_portions(conn, portion_batch)

        log.info("[%s] upserted %d foods, %d portion rows", self.name, total_inserted, total_portions)

"""Ciqual 2025 loader (ANSES French national food composition database).

The Ciqual XLS uses commas as decimal points (French locale).
Values reported as "<X" (below detection threshold) or "-" (not analysed)
are treated as NULL.
"""

import logging
import re
from pathlib import Path

import pandas as pd
from sqlalchemy.dialects.postgresql import insert

from db.connection import engine
from db.models import CiqualFood, init_db
from loaders.base import BaseLoader

log = logging.getLogger(__name__)

CIQUAL_URL = (
    "https://ciqual.anses.fr/cms/sites/default/files/inline-files/"
    "Table%20Ciqual%202025_FR_2025_11_03.xls"
)

# Map Ciqual 2025 XLS header → ORM column.
# The 2025 file embeds newlines in multi-line header cells instead of spaces/slashes.
COLUMN_MAP = {
    "alim_code": "alim_code",
    "alim_nom_fr": "alim_nom_fr",
    "alim_grp_code": "alim_grp_code",
    "alim_grp_nom_fr": "alim_grp_nom_fr",
    "alim_ssgrp_nom_fr": "alim_ssgrp_nom_fr",
    "Energie,\nRèglement\nUE N°\n1169\n2011 (kcal\n100 g)":    "energy_kcal",
    "Eau\n(g\n100\ng)":                                          "water_g",
    "Protéines,\nN x\nfacteur de\nJones (g\n100 g)":            "proteins_g",
    "Lipides\n(g\n100 g)":                                       "fat_g",
    "Glucides\n(g\n100 g)":                                      "carbohydrates_g",
    "Sucres\n(g\n100 g)":                                        "sugars_g",
    "Fibres\nalimentaires\n(g\n100 g)":                          "fiber_g",
    "Calcium\n(mg\n100 g)":                                      "calcium_mg",
    "Fer (mg\n100 g)":                                           "iron_mg",
    "Magnésium\n(mg\n100 g)":                                    "magnesium_mg",
    "Sodium\n(mg\n100 g)":                                       "sodium_mg",
    "Vitamine\nC (mg\n100 g)":                                   "vitamin_c_mg",
    "AG\nsaturés\n(g\n100 g)":                                   "saturated_fat_g",
    "AG\nmonoinsaturés\n(g\n100 g)":                             "monounsaturated_fat_g",
    "AG\npolyinsaturés\n(g\n100 g)":                             "polyunsaturated_fat_g",
    "Cholestérol\n(mg\n100 g)":                                  "cholesterol_mg",
    "Potassium\n(mg\n100 g)":                                    "potassium_mg",
    "Phosphore\n(mg\n100 g)":                                    "phosphorus_mg",
    "Zinc\n(mg\n100 g)":                                         "zinc_mg",
    # Total vitamin A activity (retinol + provitamin-A carotenoids), not "Rétinol" alone:
    # retinol is ~0 for plant foods. Same definition as the USDA loaders ("Vitamin A, RAE").
    "Activité\nvitaminique\nA,\néquivalents\nrétinol (µg\n100 g)": "vitamin_a_ug",
    "Vitamine\nD (µg\n100 g)":                                   "vitamin_d_ug",
    "Vitamine\nB6 (mg\n100 g)":                                  "vitamin_b6_mg",
    "Vitamine\nB12 (µg\n100 g)":                                 "vitamin_b12_ug",
    "Vitamine\nB3 ou PP\nou\nNiacine\n(mg\n100 g)":              "niacin_mg",
}

NUTRIENT_COLS = [
    "energy_kcal", "water_g", "proteins_g", "fat_g", "carbohydrates_g",
    "sugars_g", "fiber_g", "calcium_mg", "iron_mg", "magnesium_mg",
    "sodium_mg", "vitamin_c_mg",
    "saturated_fat_g", "monounsaturated_fat_g", "polyunsaturated_fat_g",
    "cholesterol_mg", "potassium_mg", "phosphorus_mg", "zinc_mg",
    "vitamin_a_ug", "vitamin_d_ug", "vitamin_b6_mg", "vitamin_b12_ug", "niacin_mg",
]

def _parse_french_float(value) -> float | None:
    """Convert French locale number strings to float.

    Ciqual uses three distinct sentinel values:
    - "-"       not analysed / data unavailable → None
    - "<X"      below detection limit (censored upper bound) → X / 2  (LOQ/2 substitution)
    - "traces"  infinitesimal amount present → 0.0
    """
    if pd.isna(value):
        return None
    s = str(value).strip()
    if s == "-":
        return None
    if s.lower() == "traces":
        return 0.0
    if s.startswith("<"):
        try:
            return float(s[1:].strip().replace(",", ".")) / 2.0
        except ValueError:
            return 0.0
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


class CiqualLoader(BaseLoader):
    name = "ciqual"
    filename = "ciqual_2025.xls"
    url = CIQUAL_URL

    def load(self, path: Path) -> None:
        init_db()

        df = pd.read_excel(path, dtype=str, sheet_name=0)
        df = df.rename(columns=COLUMN_MAP)

        # Keep only known columns
        df = df[[c for c in COLUMN_MAP.values() if c in df.columns]]

        missing = [v for v in COLUMN_MAP.values() if v not in df.columns]
        if missing:
            log.warning("[ciqual] columns not found after rename (file format may have changed): %s", missing)

        # Parse numeric columns
        for col in NUTRIENT_COLS:
            if col in df.columns:
                df[col] = df[col].apply(_parse_french_float)

        # alim_code and alim_grp_code must be integers
        for col in ("alim_code", "alim_grp_code"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df[df["alim_code"].notna()]
        df = df.drop_duplicates(subset=["alim_code"], keep="last")
        # pandas 2.x coerces None back to NaN in float columns; sanitise explicitly.
        raw_rows = df.to_dict("records")
        rows = [
            {k: None if isinstance(v, float) and pd.isna(v) else v for k, v in row.items()}
            for row in raw_rows
        ]

        update_cols = [c for c in df.columns if c != "alim_code"]
        stmt = insert(CiqualFood)
        stmt = stmt.on_conflict_do_update(
            index_elements=["alim_code"],
            set_={c: stmt.excluded[c] for c in update_cols},
        )
        with engine.connect() as conn:
            conn.execute(stmt, rows)
            conn.commit()

        log.info("[ciqual] upserted %d foods", len(rows))

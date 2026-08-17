"""McCance & Widdowson UK food composition loader.

Downloads Composition of Foods Integrated Dataset 2021 (XLSX) and upserts
into mccance_foods. Values are per 100 g edible portion.

Workbook structure (all data sheets share this layout):
  Row 0  — column headers  (Food Code, Food Name, …, nutrient columns)
  Row 1  — abbreviation codes  (PROT, FAT, CHO, KCALS, …)
  Row 2  — display names  (Protein, Fat, Carbohydrate, …)
  Row 3+ — food data

Nutrients are spread across three sheets:
  1.3 Proximates  → energy, protein, fat, carbs, fibre, cholesterol
  1.4 Inorganics  → sodium, potassium, calcium, magnesium, …
  1.5 Vitamins    → retinol equivalent, vitamin C/D, …

The 1.4 Inorganics sheet has a blank first-column header (' ') instead of
'Food Code'; the loader renames it automatically before merging.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy.dialects.postgresql import insert

from db.connection import engine
from db.models import McCanceFood, init_db
from loaders.base import BaseLoader

log = logging.getLogger(__name__)

MCCANCE_URL = (
    "https://assets.publishing.service.gov.uk/media/"
    "60538b91e90e07527df82ae4/McCance_Widdowsons_Composition_of_Foods_Integrated_Dataset_2021..xlsx"
)

# Non-numeric markers used by McCance & Widdowson
MCCANCE_NA_VALUES = ["N", "Tr", "n", "tr", ""]

# ORM field → ordered candidate substring sets.
# Candidates are matched case-insensitively against lowercased column names.
# Verified against the actual XLSX column headers (2021 edition).
FIELD_CANDIDATES: Dict[str, List[List[str]]] = {
    "food_code":       [["food code"]],
    "food_name":       [["food name"]],
    "food_group":      [["group"]],
    "description":     [["description"]],
    "water_g":         [["water (g)"], ["water"]],
    # Proximates — energy columns have doubled unit suffix: "Energy (kJ) (kJ)"
    "energy_kj":       [["energy", "kj"]],
    "energy_kcal":     [["energy", "kcal"]],
    "protein_g":       [["protein (g)"]],
    "fat_g":           [["fat (g)"]],
    "carbohydrate_g":  [["carbohydrate (g)"]],
    # Fibre: "NSP (g)" is preferred; "AOAC fibre (g)" as fallback
    "fibre_g":         [["nsp (g)"], ["nsp"], ["aoac fibre"], ["fibre"], ["fiber"]],
    # Saturated fat: "Satd FA /100g fd (g)" = per 100 g food (not per 100 g FA)
    "saturated_fat_g": [["satd fa /100g fd"], ["satd fa /100g food"],
                        ["saturates"], ["saturated fat"]],
    "cholesterol_mg":  [["cholesterol"]],
    # Inorganics — full element names, not chemical symbols
    "sodium_mg":       [["sodium"]],
    "potassium_mg":    [["potassium"]],
    "calcium_mg":      [["calcium"]],
    "magnesium_mg":    [["magnesium"]],
    "phosphorus_mg":   [["phosphorus"]],
    "iron_mg":         [["iron"]],
    "zinc_mg":         [["zinc"]],
    # Vitamins
    "vitamin_c_mg":    [["vitamin c"]],
    "vitamin_d_ug":    [["vitamin d"]],
    # "Retinol Equivalent (µg)" = total vitamin A activity
    "vitamin_a_ug":    [["retinol equivalent"], ["retinol eq"]],
}

NUTRIENT_FIELDS = [
    "water_g", "energy_kj", "energy_kcal", "protein_g", "fat_g", "carbohydrate_g",
    "fibre_g", "sodium_mg", "potassium_mg", "calcium_mg", "magnesium_mg",
    "phosphorus_mg", "iron_mg", "zinc_mg", "saturated_fat_g",
    "cholesterol_mg", "vitamin_c_mg", "vitamin_d_ug", "vitamin_a_ug",
]

# Inspection: (label, sheet role, fields to show)
INSPECTION_PLAN = [
    ("Proximates", "macro",   ["energy_kj", "energy_kcal", "protein_g", "fat_g", "carbohydrate_g"]),
    ("Inorganics", "mineral", ["sodium_mg"]),
]


def _find_col(columns: List[str], *substrings: str) -> Optional[str]:
    for col in columns:
        cl = col.lower().strip()
        if all(s.lower() in cl for s in substrings):
            return col
    return None


def _build_column_map(columns: List[str]) -> Dict[str, str]:
    """ORM field → raw column name."""
    mapping: Dict[str, str] = {}
    for field, candidates in FIELD_CANDIDATES.items():
        for substrings in candidates:
            hit = _find_col(columns, *substrings)
            if hit:
                mapping[field] = hit
                break
    return mapping


def _find_sheet(sheet_names: List[str], keyword: str, exclude: str = "") -> Optional[str]:
    for name in sheet_names:
        n = name.lower()
        if keyword in n and (not exclude or exclude not in n):
            return name
    return None


def _read_sheet(xl: pd.ExcelFile, sheet: str) -> pd.DataFrame:
    """Read one McCance data sheet.

    All sheets share the same structure:
      header=0   → column names
      iloc[0]    → abbreviation codes   (skip)
      iloc[1]    → display names        (skip)
      iloc[2:]   → food data
    """
    df = pd.read_excel(
        xl,
        sheet_name=sheet,
        header=0,
        dtype=str,
        na_values=MCCANCE_NA_VALUES,
        keep_default_na=True,
        engine="openpyxl",
    )

    # Drop the two fixed label rows that always follow the header
    df = df.iloc[2:].reset_index(drop=True)

    # Inorganics quirk: first column header is ' ' instead of 'Food Code'
    first_col = df.columns[0]
    if first_col.strip() == "":
        df = df.rename(columns={first_col: "Food Code"})
        log.info("[mccance-widdowson] Sheet '%s': renamed blank first column to 'Food Code'", sheet)

    log.info(
        "[mccance-widdowson] Sheet '%s': %d rows, cols[:8]=%s",
        sheet, len(df), list(df.columns[:8]),
    )
    return df


def _rename_to_orm(df: pd.DataFrame) -> pd.DataFrame:
    """Rename raw headers to ORM field names; keep only matched columns."""
    col_map = _build_column_map(list(df.columns))
    inv_map = {v: k for k, v in col_map.items()}
    df = df.rename(columns=inv_map)
    return df[[c for c in df.columns if c in set(col_map.keys())]]


class McCanceLoader(BaseLoader):
    name = "mccance-widdowson"
    filename = "mccance_2021.xlsx"
    url = MCCANCE_URL

    def load(self, path: Path) -> None:
        init_db()

        xl = pd.ExcelFile(path, engine="openpyxl")
        log.info("[%s] Sheets: %s", self.name, xl.sheet_names)

        sheets = {
            "macro":   _find_sheet(xl.sheet_names, "proximate"),
            "mineral": _find_sheet(xl.sheet_names, "inorganic"),
            "vitamin": _find_sheet(xl.sheet_names, "vitamin", exclude="fraction"),
        }
        if not sheets["macro"]:
            raise RuntimeError(
                f"[{self.name}] No Proximates sheet found. Available: {xl.sheet_names}"
            )
        log.info(
            "[%s] Data sheets → macro: %s | mineral: %s | vitamin: %s",
            self.name, sheets["macro"], sheets["mineral"], sheets["vitamin"],
        )

        raw_dfs: Dict[str, Optional[pd.DataFrame]] = {
            role: (_read_sheet(xl, sheet) if sheet else None)
            for role, sheet in sheets.items()
        }

        # ── Unit inspection ──────────────────────────────────────────────────
        log.info("[%s] ===== Unit Inspection Report =====", self.name)
        for label, role, fields in INSPECTION_PLAN:
            sheet_df = raw_dfs.get(role)
            if sheet_df is None:
                log.warning("[%s]  [%s] sheet not found — skipping", self.name, label)
                continue
            col_map = _build_column_map(list(sheet_df.columns))
            log.info("[%s]  [%s]", self.name, label)
            for field in fields:
                raw_col = col_map.get(field)
                if raw_col:
                    sample = sheet_df[raw_col].dropna().head(5).tolist()
                    log.info(
                        "[%s]    %-18s → %-32s | sample: %s",
                        self.name, field, repr(raw_col), sample,
                    )
                else:
                    log.warning("[%s]    %-18s → NOT FOUND", self.name, field)

        macro_df = raw_dfs["macro"]
        name_col_map = _build_column_map(list(macro_df.columns))
        name_col = name_col_map.get("food_name") or name_col_map.get("description")
        if name_col:
            names = macro_df[name_col].fillna("").str.lower()
            n_cooked = names.str.contains(
                r"cook|boil|roast|grill|fry|frie|bake|baked", regex=True
            ).sum()
            n_raw = names.str.contains(r"\braw\b", regex=True).sum()
            log.info(
                "[%s]  Cooked entries : %d  |  Raw entries : %d",
                self.name, n_cooked, n_raw,
            )
        log.info("[%s] ===================================", self.name)
        # ── End inspection ───────────────────────────────────────────────────

        # Rename to ORM names and join on food_code
        df = _rename_to_orm(macro_df)
        for role in ("mineral", "vitamin"):
            supp_raw = raw_dfs.get(role)
            if supp_raw is None:
                continue
            supp = _rename_to_orm(supp_raw)
            if "food_code" not in supp.columns or "food_code" not in df.columns:
                log.warning(
                    "[%s] Cannot merge %s — food_code missing (supp cols: %s)",
                    self.name, role, list(supp.columns),
                )
                continue
            new_cols = [c for c in supp.columns if c not in df.columns or c == "food_code"]
            df = df.merge(supp[new_cols], on="food_code", how="left")
            log.info("[%s] Merged %s: df now has %d columns", self.name, role, len(df.columns))

        for required in ("food_code", "food_name"):
            if required not in df.columns:
                raise RuntimeError(
                    f"[{self.name}] Required column '{required}' not found; "
                    f"available: {list(df.columns)}"
                )

        for field in NUTRIENT_FIELDS:
            if field in df.columns:
                df[field] = pd.to_numeric(df[field], errors="coerce")

        df = df[df["food_code"].notna() & (df["food_code"].str.strip() != "")]
        df["food_code"] = df["food_code"].str.strip()
        df = df.drop_duplicates(subset=["food_code"], keep="last")

        orm_cols = {c.key for c in McCanceFood.__table__.columns} - {"refreshed_at"}
        keep = [c for c in df.columns if c in orm_cols]
        df = df[keep]

        rows = df.where(pd.notna(df), None).to_dict("records")

        with engine.connect() as conn:
            stmt = insert(McCanceFood).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["food_code"],
                set_={c: stmt.excluded[c] for c in keep if c != "food_code"},
            )
            conn.execute(stmt)
            conn.commit()

        log.info("[%s] upserted %d foods", self.name, len(rows))

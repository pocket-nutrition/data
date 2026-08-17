"""Open Food Facts loader.

Downloads the full OFF CSV export and upserts into off_products.
The file is ~9 GB uncompressed; it is processed in chunks to avoid OOM.
Only products with at least one nutritional value are imported.
"""

import logging
from pathlib import Path

import pandas as pd
from sqlalchemy.dialects.postgresql import insert

from db.connection import engine
from db.models import OffProduct, init_db
from loaders.base import BaseLoader

log = logging.getLogger(__name__)

# OFF exports the CSV as a tab-separated .gz file
OFF_URL = "https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz"

# Columns we keep from the ~180-column OFF export
COLUMNS = [
    "code",
    "product_name",
    "product_name_fr",
    "categories_tags",
    "countries_tags",
    "quantity",
    # OFF's normalized numeric companion to `serving_size`, always in grams. This is what lets a
    # pizza or a tart offer a real "1 part" shortcut — deriving a slice weight by parsing the
    # free-text serving_size ("1/4 pizza (100 g)") would need a different regex than quantity's,
    # since it doesn't start with a digit.
    "serving_quantity",
    "image_url",
    # Kept so a search result can be told apart from its neighbours: thousands of OFF products
    # carry a product_name that is just the bare food word ("Poulet", "Salade"), so without the
    # brand a client renders several rows with identical text.
    "brands",
    "energy-kcal_100g",
    "proteins_100g",
    "fat_100g",
    "carbohydrates_100g",
    "fiber_100g",
    "sugars_100g",
    "salt_100g",
    "sodium_100g",
]

# Map OFF column names → ORM column names
# All nutrient columns must appear as values here (even identity mappings)
# so the loader logic and tests have a single source of truth.
COLUMN_MAP = {
    "image_url": "image_front_url",
    "brands": "brand",
    "energy-kcal_100g": "energy_kcal_100g",
    "proteins_100g": "proteins_100g",
    "fat_100g": "fat_100g",
    "carbohydrates_100g": "carbohydrates_100g",
    "fiber_100g": "fiber_100g",
    "sugars_100g": "sugars_100g",
    "salt_100g": "salt_100g",
    "sodium_100g": "sodium_100g",
}

NUTRIENT_COLS = [
    "energy_kcal_100g", "proteins_100g", "fat_100g",
    "carbohydrates_100g", "fiber_100g", "sugars_100g",
    "salt_100g", "sodium_100g",
]

# Non-nutrient columns that still need a numeric cast before insert — kept separate from
# NUTRIENT_COLS because the has_nutrient filter below must only look at actual nutrients.
NUMERIC_COLS = NUTRIENT_COLS + ["serving_quantity"]

CHUNK_SIZE = 50_000


class OffLoader(BaseLoader):
    name = "open-food-facts"
    filename = "off_products.csv.gz"
    url = OFF_URL

    def load(self, path: Path) -> None:
        init_db()
        total_inserted = 0

        reader = pd.read_csv(
            path,
            sep="\t",
            usecols=lambda c: c in COLUMNS,
            dtype=str,
            chunksize=CHUNK_SIZE,
            on_bad_lines="skip",
            compression="gzip",
        )

        with engine.connect() as conn:
            for chunk in reader:
                chunk = chunk.rename(columns=COLUMN_MAP)

                # Drop rows with no barcode
                chunk = chunk[chunk["code"].notna() & (chunk["code"] != "")]

                # Cast numeric columns
                for col in NUMERIC_COLS:
                    if col in chunk.columns:
                        chunk[col] = pd.to_numeric(chunk[col], errors="coerce")

                # Keep only rows that have at least one nutrient value
                has_nutrient = chunk[NUTRIENT_COLS].notna().any(axis=1)
                chunk = chunk[has_nutrient]

                if chunk.empty:
                    continue

                rows = chunk.where(pd.notna(chunk), None).to_dict("records")
                stmt = insert(OffProduct).values(rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["code"],
                    set_={c: stmt.excluded[c] for c in chunk.columns if c != "code"},
                )
                conn.execute(stmt)
                conn.commit()
                total_inserted += len(rows)

        log.info("[open-food-facts] upserted %d products", total_inserted)

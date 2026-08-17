"""
Raw database tables — one per public source.

These tables are the authoritative local copy of upstream datasets.
pocket-nutrition-ingest and pocket-nutrition-api read from these tables; they never
download upstream data themselves.
"""

from sqlalchemy import BigInteger, Column, Float, ForeignKey, Integer, String, Text, DateTime, UniqueConstraint, func, inspect, text
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class OffProduct(Base):
    """Open Food Facts product, keyed by barcode (code)."""

    __tablename__ = "off_products"

    code = Column(String(64), primary_key=True)
    product_name = Column(Text)
    product_name_fr = Column(Text)
    categories_tags = Column(Text)           # comma-separated OFF tags
    countries_tags = Column(Text)
    quantity = Column(String(255), nullable=True)   # total package quantity e.g. "500 g", "1 L"
    # Manufacturer-declared weight of one serving, in grams — OFF's own normalized companion to
    # its free-text `serving_size` (e.g. "1/4 pizza (100 g)"). Kept as the number rather than the
    # text: parsing "1/4 pizza (100 g)" with the same regex that parses `quantity` would fail,
    # since the value doesn't start with a digit.
    serving_quantity = Column(Float, nullable=True)
    # Per-100 g nutritional values (NULL when not reported by contributor)
    energy_kcal_100g = Column(Float)
    proteins_100g = Column(Float)
    fat_100g = Column(Float)
    carbohydrates_100g = Column(Float)
    fiber_100g = Column(Float)
    sugars_100g = Column(Float)
    salt_100g = Column(Float)
    sodium_100g = Column(Float)
    image_front_url = Column(Text, nullable=True)
    # OFF's `brands` column, comma-separated when a product lists several. Kept raw; the search
    # indexer takes the first entry. This is what lets a client distinguish products whose
    # product_name is the bare food word — thousands of them are literally "Poulet" or "Salade".
    brand = Column(Text, nullable=True)
    refreshed_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class CiqualFood(Base):
    """
    ANSES Ciqual 2020 food composition table.
    Source: https://ciqual.anses.fr
    Values are per 100 g of edible portion, raw.
    """

    __tablename__ = "ciqual_foods"

    alim_code = Column(BigInteger, primary_key=True)   # Ciqual food code
    alim_nom_fr = Column(Text, nullable=False)          # French name
    alim_nom_index_fr = Column(Text)                   # Indexed/searchable name
    alim_grp_code = Column(BigInteger)
    alim_grp_nom_fr = Column(Text)                     # Food group
    alim_ssgrp_nom_fr = Column(Text)                   # Sub-group
    # Nutrients (NULL = not analysed / traces / value uncertain)
    energy_kcal = Column(Float)
    water_g = Column(Float)
    proteins_g = Column(Float)
    fat_g = Column(Float)
    carbohydrates_g = Column(Float)
    sugars_g = Column(Float)
    fiber_g = Column(Float)
    calcium_mg = Column(Float)
    iron_mg = Column(Float)
    magnesium_mg = Column(Float)
    sodium_mg = Column(Float)
    vitamin_c_mg = Column(Float)
    # Extended lipid profile
    saturated_fat_g = Column(Float)
    monounsaturated_fat_g = Column(Float)
    polyunsaturated_fat_g = Column(Float)
    cholesterol_mg = Column(Float)
    # Additional minerals
    potassium_mg = Column(Float)
    phosphorus_mg = Column(Float)
    zinc_mg = Column(Float)
    # Additional vitamins
    vitamin_a_ug = Column(Float)
    vitamin_d_ug = Column(Float)
    vitamin_b6_mg = Column(Float)
    vitamin_b12_ug = Column(Float)
    niacin_mg = Column(Float)
    refreshed_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Ingredient(Base):
    """Canonical ingredient catalogue entry, identified by an ASCII slug."""

    __tablename__ = "ingredients"

    id = Column(String(64), primary_key=True)   # slug: "chicken_breast"
    labels = relationship("IngredientLabel", back_populates="ingredient", cascade="all, delete-orphan")


class IngredientLabel(Base):
    """Multilingual display label for an ingredient."""

    __tablename__ = "ingredient_labels"

    ingredient_id = Column(String(64), ForeignKey("ingredients.id"), primary_key=True)
    lang = Column(String(5), primary_key=True)   # "fr" | "en"
    label = Column(Text, nullable=False)
    ingredient = relationship("Ingredient", back_populates="labels")


class McCanceFood(Base):
    """McCance & Widdowson UK food composition (Composition of Foods Integrated Dataset v11).
    Values are per 100 g edible portion.
    """

    __tablename__ = "mccance_foods"

    food_code = Column(String(32), primary_key=True)
    food_name = Column(Text, nullable=False)
    food_group = Column(Text)
    description = Column(Text)
    water_g = Column(Float)
    # McCance reports energy in both kJ and kcal
    energy_kj = Column(Float)
    energy_kcal = Column(Float)
    protein_g = Column(Float)
    fat_g = Column(Float)
    carbohydrate_g = Column(Float)
    fibre_g = Column(Float)
    # Minerals (McCance uses chemical symbols: Na, K, Ca, Mg, P, Fe, Zn)
    sodium_mg = Column(Float)
    potassium_mg = Column(Float)
    calcium_mg = Column(Float)
    magnesium_mg = Column(Float)
    phosphorus_mg = Column(Float)
    iron_mg = Column(Float)
    zinc_mg = Column(Float)
    # Lipids
    saturated_fat_g = Column(Float)
    cholesterol_mg = Column(Float)
    # Vitamins
    vitamin_c_mg = Column(Float)
    vitamin_d_ug = Column(Float)
    vitamin_a_ug = Column(Float)
    refreshed_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class UsdaFood(Base):
    """USDA FoodData Central — FNDDS survey food.
    Values are per 100 g.
    Source: FoodData_Central_survey_food_json_2024-10-31
    """

    __tablename__ = "usda_foods"

    fdc_id = Column(Integer, primary_key=True)
    description = Column(Text, nullable=False)
    food_code = Column(String(32))
    wweia_category = Column(Text)
    # FNDDS reports energy in kcal only; sodium in mg (no "Salt" column)
    energy_kcal = Column(Float)
    protein_g = Column(Float)
    fat_g = Column(Float)
    carbohydrates_g = Column(Float)
    fiber_g = Column(Float)
    sodium_mg = Column(Float)
    refreshed_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class UsdaFoundationFood(Base):
    """USDA FoodData Central — Foundation Foods (laboratory reference).
    Values are per 100 g. Richer nutrient profile than FNDDS.
    Source: FoodData_Central_foundation_food_json_2024-10-31
    """

    __tablename__ = "usda_foundation_foods"

    fdc_id = Column(Integer, primary_key=True)
    description = Column(Text, nullable=False)
    food_category = Column(Text)
    # Core macronutrients
    energy_kcal = Column(Float)
    protein_g = Column(Float)
    fat_g = Column(Float)
    carbohydrates_g = Column(Float)
    fiber_g = Column(Float)
    # Minerals
    sodium_mg = Column(Float)
    calcium_mg = Column(Float)
    iron_mg = Column(Float)
    magnesium_mg = Column(Float)
    phosphorus_mg = Column(Float)
    potassium_mg = Column(Float)
    zinc_mg = Column(Float)
    # Vitamins
    vitamin_c_mg = Column(Float)
    vitamin_d_ug = Column(Float)
    vitamin_a_ug = Column(Float)
    vitamin_b6_mg = Column(Float)
    vitamin_b12_ug = Column(Float)
    niacin_mg = Column(Float)
    # Lipid fractions
    saturated_fat_g = Column(Float)
    monounsaturated_fat_g = Column(Float)
    polyunsaturated_fat_g = Column(Float)
    cholesterol_mg = Column(Float)
    refreshed_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class UsdaSrFood(Base):
    """USDA FoodData Central — SR Legacy (Standard Reference, 2018 snapshot).
    Values are per 100 g. Covers ~8 000 basic foods and raw commodities.
    Source: FoodData_Central_sr_legacy_food_json_2018-04
    """

    __tablename__ = "usda_sr_foods"

    fdc_id = Column(Integer, primary_key=True)
    description = Column(Text, nullable=False)
    food_category = Column(Text)
    ndb_number = Column(Integer)        # historic SR NDB number
    # Core macronutrients
    energy_kcal = Column(Float)
    protein_g = Column(Float)
    fat_g = Column(Float)
    carbohydrates_g = Column(Float)
    fiber_g = Column(Float)
    # Minerals
    sodium_mg = Column(Float)
    calcium_mg = Column(Float)
    iron_mg = Column(Float)
    magnesium_mg = Column(Float)
    phosphorus_mg = Column(Float)
    potassium_mg = Column(Float)
    zinc_mg = Column(Float)
    # Vitamins
    vitamin_c_mg = Column(Float)
    vitamin_d_ug = Column(Float)
    vitamin_a_ug = Column(Float)
    vitamin_b6_mg = Column(Float)
    vitamin_b12_ug = Column(Float)
    niacin_mg = Column(Float)
    # Lipid fractions
    saturated_fat_g = Column(Float)
    monounsaturated_fat_g = Column(Float)
    polyunsaturated_fat_g = Column(Float)
    cholesterol_mg = Column(Float)
    refreshed_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class UsdaSrFoodPortion(Base):
    """USDA SR Legacy food portion data (foodPortions array from the SR Legacy JSON).
    Each row is one portion entry for a given fdc_id.
    """

    __tablename__ = "usda_sr_food_portions"
    __table_args__ = (
        UniqueConstraint("fdc_id", "description", name="uq_usda_sr_portion"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    fdc_id = Column(Integer, nullable=False, index=True)
    description = Column(Text, nullable=False)   # e.g. "1 cup", "1 medium apple"
    gram_weight = Column(Float, nullable=False)
    amount = Column(Float, nullable=False, default=1.0)


class UsdaCookingYield(Base):
    """USDA Table of Cooking Yields for Meat and Poultry, Release 2 (2014).

    Direct weight-loss measurements from controlled cooking studies.
    Source file: USDA_CookingYields_MeatPoultry02.xlsx
    URL: https://www.ars.usda.gov/ARSUserFiles/80400535/Data/retn/USDA_CookingYields_MeatPoultry02.xlsx
    """

    __tablename__ = "usda_cooking_yields"
    __table_args__ = (
        UniqueConstraint("food_description", "cooking_description", name="uq_usda_cooking_yield"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    food_description = Column(Text, nullable=False)
    cooking_description = Column(Text, nullable=False)
    cooking_yield_pct = Column(Float, nullable=False)
    moisture_change_pct = Column(Float, nullable=True)
    fat_change_pct = Column(Float, nullable=True)
    source_file = Column(Text, nullable=False, default="USDA_CookingYields_MeatPoultry02.xlsx")
    source_release = Column(Text, nullable=False, default="Release 2 (2014)")
    refreshed_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


def init_db(eng=None) -> None:
    import logging
    log = logging.getLogger(__name__)
    from db.connection import engine as default_engine
    target = eng or default_engine

    # Migrate existing tables: add columns introduced after initial deployment.
    insp = inspect(target)
    for table_cls in (OffProduct, CiqualFood, McCanceFood, UsdaFood, UsdaFoundationFood, UsdaSrFood, UsdaCookingYield, UsdaSrFoodPortion):
        tname = table_cls.__tablename__
        if insp.has_table(tname):
            existing = {col["name"] for col in insp.get_columns(tname)}
            new_cols = [col for col in table_cls.__table__.columns if col.key not in existing]
            if new_cols:
                with target.connect() as conn:
                    for col in new_cols:
                        col_type = col.type.compile(dialect=target.dialect)
                        log.info("Adding missing column %s.%s (%s)", tname, col.key, col_type)
                        conn.execute(text(
                            f"ALTER TABLE {tname} ADD COLUMN IF NOT EXISTS {col.key} {col_type}"
                        ))
                    conn.commit()

    Base.metadata.create_all(target)

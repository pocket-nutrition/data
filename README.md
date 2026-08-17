# Pocket Nutrition Data

Downloads public nutrition datasets and loads them into PostgreSQL. Single source of truth for raw nutritional data — `pocket-nutrition/ingest` and `pocket-nutrition/api` read from these tables directly.

## Sources

| Source | Table | Format | Refresh |
|--------|-------|--------|---------|
| Ciqual 2025 (ANSES, France) | `ciqual_foods` | XLS (~3.6 MB) | On new release |
| Open Food Facts (international) | `off_products` | TSV.GZ (~1.2 GB / 9 GB uncompressed) | Monthly |
| McCance & Widdowson 2021 (UK) | `mccance_foods` | XLSX (~5 MB) | On new release |
| USDA FoodData Central FNDDS 2024 | `usda_foods` | JSON ZIP (~50 MB) | As released |
| USDA Foundation Foods 2024 | `usda_foundation_foods` | JSON ZIP (~30 MB) | As released |
| USDA SR Legacy 2018 | `usda_sr_foods`, `usda_sr_food_portions` | JSON ZIP (~22 MB) | Static (2018 snapshot) |
| USDA Cooking Yields (Meat/Poultry, Release 2) | `usda_cooking_yields` | XLSX | Static (2014 snapshot) |

## Quick start

```bash
pip install -r requirements.txt

# Load only Ciqual (recommended — smallest source, fastest to verify)
python main.py --loader ciqual

# Load all sources
python main.py

# Force re-download (bypass cache)
python main.py --loader ciqual --force

# Run tests
pytest tests/
```

Available `--loader` values: `ciqual`, `off`, `mccance`, `usda`,
`usda_foundation`, `usda_sr`, `usda_cooking_yields`.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://pocket_nutrition:pocket_nutrition@postgresql:5432/pocket_nutrition` | PostgreSQL DSN |
| `DOWNLOAD_DIR` | `/data/raw` | Local cache for downloaded files |

## Deployment

No deployment manifests are included in this repository — bring your own
(Docker Compose, Kubernetes, etc.). A `Dockerfile` is provided as a starting
point.

## Architecture

```
main.py                     # CLI — runs one or all loaders
loaders/
  base.py                   # BaseLoader: idempotent download + abstract load()
  ciqual.py                 # CiqualLoader           → ciqual_foods (XLS, French locale)
  off.py                    # OffLoader              → off_products (CSV.GZ, chunked)
  mccance.py                # McCanceLoader          → mccance_foods (XLSX)
  usda.py                   # UsdaLoader             → usda_foods (FNDDS survey, JSON)
  usda_foundation.py        # UsdaFoundationLoader   → usda_foundation_foods (JSON)
  usda_sr.py                # UsdaSrLoader           → usda_sr_foods / usda_sr_food_portions (JSON)
  usda_cooking_yields.py    # UsdaCookingYieldsLoader → usda_cooking_yields (XLSX)
db/
  models.py                 # SQLAlchemy ORM models
  connection.py             # engine / session factory
```

All loaders are idempotent (`INSERT … ON CONFLICT DO UPDATE`) and safe to re-run.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, testing, and how to add
a new data source loader.

## License

AGPL-3.0 — see [LICENSE](LICENSE).

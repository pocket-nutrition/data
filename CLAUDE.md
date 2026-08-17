# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

`pocket-nutrition/data` downloads public nutrition databases and loads them into PostgreSQL.  
It is the **single source of truth** for raw nutritional data across the platform — both `pocket-nutrition/ingest` (model training) and `pocket-nutrition/api` (cache fallback) read from these tables.

Currently supported sources:

| Source | Table | Size | Refresh |
|--------|-------|------|---------|
| Open Food Facts (international) | `off_products` | ~1.2 GB GZ / ~9 GB TSV | Monthly |
| Ciqual 2025 (ANSES, France) | `ciqual_foods` | ~3.6 MB XLS | On new release |
| McCance & Widdowson 2021 (UK) | `mccance_foods` | ~5 MB XLSX | On new release |
| USDA FoodData Central FNDDS 2024 | `usda_foods` | ~50 MB JSON ZIP | As released |
| USDA Foundation Foods 2024 | `usda_foundation_foods` | ~30 MB JSON ZIP | As released |
| USDA SR Legacy 2018 | `usda_sr_foods` | ~22 MB JSON ZIP | Static (2018 snapshot) |
| USDA Cooking Yields | `usda_cooking_yields` | small CSV/JSON | Static |

## Architecture

```
main.py              # CLI entry point — runs one or all loaders
loaders/
  base.py            # BaseLoader: download-if-missing + abstract load()
  off.py             # OffLoader            → off_products
  ciqual.py          # CiqualLoader         → ciqual_foods
  mccance.py         # McCanceLoader        → mccance_foods
  usda.py            # UsdaLoader           → usda_foods (FNDDS survey)
  usda_foundation.py # UsdaFoundationLoader → usda_foundation_foods (lab reference)
  usda_sr.py         # UsdaSrLoader         → usda_sr_foods (SR Legacy 2018)
  usda_cooking_yields.py # UsdaCookingYieldsLoader → usda_cooking_yields
db/
  models.py          # SQLAlchemy table definitions
  connection.py      # engine / session factory
tests/
```

**Key design rules:**
- All loaders are **idempotent**: they use `INSERT … ON CONFLICT DO UPDATE` — safe to re-run.
- Files are cached in `DOWNLOAD_DIR` (`/data/raw` in production). Re-download only when `--force` is passed.
- Adding a new source = create `loaders/<name>.py` extending `BaseLoader`, register in `main.py`.

## Commands

```bash
pip install -r requirements.txt

# Run all loaders
python main.py

# Run a single loader
python main.py --loader ciqual
python main.py --loader off

# Force re-download (refresh upstream data)
python main.py --force

# Run tests
pytest tests/

# Run a single test file
pytest tests/test_ciqual_loader.py
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://pocket_nutrition:pocket_nutrition@postgresql:5432/pocket_nutrition` | PostgreSQL DSN |
| `DOWNLOAD_DIR` | `/data/raw` | Local cache for downloaded files |

## Deployment

No deployment manifests are included in this repository. Run the loaders as
a one-shot job (initial load) and, if you want automatic refreshes, a
scheduled job (e.g. a Kubernetes CronJob or a cron entry) — write manifests
appropriate to your own environment. A `Dockerfile` is provided as a
starting point.

**Notes:**
- Ciqual source is now XLS (ANSES removed the CSV). The loader uses `pd.read_excel` and requires `xlrd`.
- OFF downloader sends a `User-Agent` header to avoid S3 CDN 403 responses.
- OFF processing uses 50 K-row chunks to stay within memory limits.

## Adding a new data source

1. Create `loaders/<source>.py` extending `BaseLoader` — implement `load(path)`.
2. Add an entry to `ALL_LOADERS` in `main.py`.
3. Add the SQLAlchemy model in `db/models.py`.
4. Write tests in `tests/`.

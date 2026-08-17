# AGENTS.md — Pocket Nutrition Data

## What this project is

Downloads Open Food Facts and Ciqual datasets, loads them into PostgreSQL.
No deployment manifests are included in this repository — run as a one-shot job
(initial load) and, optionally, a scheduled job for refreshes appropriate to
your own environment.

## Key constraints

- All code in English.
- Loaders must be **idempotent** — always use `INSERT … ON CONFLICT DO UPDATE`, never plain INSERT.
- Cached files in `DOWNLOAD_DIR` must not be re-downloaded unless `--force` is passed.
- Do not add synchronous waits or polling loops; download failures should raise immediately.
- Never hard-code credentials — always use `DATABASE_URL` env var.

## Allowed without approval

- Implementing or improving a loader's `load()` method.
- Adding a new source loader (new file in `loaders/`, registered in `main.py`).
- Adding tests.
- Updating minor versions of existing dependencies.

## Requires approval

- Changing the PostgreSQL schema (`db/models.py`) — downstream consumers (`pocket-nutrition/ingest`, `pocket-nutrition/api`) depend on these table structures.
- Changing the `BaseLoader` interface.
- Adding new dependencies to `requirements.txt`.
- Modifying `Dockerfile`.

## Running

```bash
pip install -r requirements.txt pytest
pytest tests/
python main.py --loader ciqual   # quick test with the small Ciqual file
```

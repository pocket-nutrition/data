# Contributing to Pocket Nutrition Data

Thanks for your interest in improving this project. This document covers the
dev setup, the test workflow, and how to add a new data source loader.

## Development setup

Requires Python 3.12+ (the codebase targets `python:3.12-slim`; `psycopg2-binary`
may fail to build on newer interpreters).

```bash
python3.12 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt pytest

cp .env.example .env             # edit DATABASE_URL / DOWNLOAD_DIR if needed
```

You do not need a running PostgreSQL instance to run the unit tests — they
exercise parsing logic only, with no DB or network access. A real
`DATABASE_URL` is only needed when actually running `python main.py`.

## Running tests

```bash
pytest tests/ -v
```

Run a single test file:

```bash
pytest tests/test_ciqual_loader.py -v
```

New loaders and bug fixes must come with tests. Prefer testing parsing/transform
functions directly (see `tests/test_ciqual_loader.py`, `tests/test_off_loader.py`)
over spinning up a real database.

## Branch and PR workflow

1. Fork the repository and create a branch off `main`.
2. Make your change with focused, well-scoped commits.
3. Ensure `pytest tests/` passes locally.
4. Open a pull request describing the change and, for new loaders, the
   upstream source (URL, license, refresh cadence).
5. Keep PRs scoped to one loader or one fix — easier to review, easier to
   revert if the upstream source changes shape.

## Adding a new data source loader

See `AGENTS.md` for the authoritative list of what's allowed without
approval versus what requires approval before you start — it also lists
the project's hard constraints (idempotency, `DATABASE_URL`-only credentials,
no synchronous polling). In short:

1. Create `loaders/<source>.py` extending `BaseLoader` — implement `load(path)`.
2. Register the loader in `ALL_LOADERS` in `main.py`.
3. Add tests for any pure parsing/transform logic under `tests/`.
4. If the source needs a new table, add the SQLAlchemy model in
   `db/models.py` — per `AGENTS.md`, schema changes need approval since
   downstream services (`pocket-nutrition/ingest`, `pocket-nutrition/api`)
   depend on these table structures.

Loaders must stay idempotent (`INSERT … ON CONFLICT DO UPDATE`), must cache
downloaded files under `DOWNLOAD_DIR` and only re-download when `--force` is
passed, and must never hard-code credentials.

## Code style

- All code, comments, and commit messages in English.
- Type hints on new functions where practical (see existing loaders for the
  prevailing style).
- No `print()` — this project uses the `logging` module.

## Reporting issues

Use the issue templates under `.github/ISSUE_TEMPLATE/`. For bugs, include
the loader name (or `--loader` value), the command you ran, and the
resulting stack trace or unexpected table contents.

## CI and releases

- Every pull request runs `.github/workflows/ci.yml`. The `ci-success` check must be green before a pull
  request can be merged, the branch must be up to date with `main`, and pull requests are squash-merged
  so history stays linear.
- If you contribute from a fork, the workflow waits for a maintainer to approve it. It runs with a
  read-only token and no secrets.
- Every commit merged to `main` is released automatically with a CalVer version, `vYYYY.M.N`: the year, the
  month, then a counter that restarts at 1 each month (for example `v2026.11.1`). You never pick a version
  number or edit a changelog; release notes are generated from the merged pull requests.
- A release publishes the container image `ghcr.io/pocket-nutrition/data`.

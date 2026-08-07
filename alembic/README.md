# Alembic migrations for Flipper

Migrations for the Flipper PostgreSQL schema (`houses`, `active_ads`, `sold_ads`).
Models live in `packages/flipper_db/models.py` — `alembic revision --autogenerate`
diffs them against the DB and emits a migration.

## Setup

Alembic is already configured (`alembic.ini` at repo root, `alembic/env.py` here).
`alembic` must be installed in whatever environment you run it from — add it to
`services/api/requirements.txt` (so `docker compose run --rm api alembic ...`
works) or install locally with `pip install alembic psycopg[binary]`.

## Adopting Alembic on the EXISTING database (one-time)

The DB is already populated (houses 181k, sold_ads 343k, active_ads 3.3k). We
must NOT re-create tables — we mark the current schema as the baseline:

```bash
# 1. Export DATABASE_URL (same as in .env):
export DATABASE_URL=postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper
#    (or @app_postgres:5432 if running inside Docker)

# 2. Generate the initial migration from current models:
alembic revision --autogenerate -m "initial schema"
#    Inspect alembic/versions/<ts>_initial_schema.py — if it tries to CREATE
#    tables that already exist, either:
#      a) wrap the ops in `op.create_table(..., if_not_exists=True)` manually, or
#      b) skip generating DDL and just stamp the DB (step 3).

# 3. Stamp the DB as being at this migration WITHOUT running DDL:
alembic stamp head
#    Now `alembic current` shows the revision, and future `alembic upgrade head`
#    will only run NEW migrations generated after this point.
```

## Daily workflow

```bash
# After editing packages/flipper_db/models.py:
alembic revision --autogenerate -m "add X to houses"
# Inspect the generated file! Autogenerate is not perfect — check it.

# Apply on the dev DB:
alembic upgrade head

# Apply on prod (inside the api container):
docker compose run --rm api alembic upgrade head

# Roll back one migration:
alembic downgrade -1
```

## Notes

- `env.py` converts `postgresql+asyncpg://` (async) → `postgresql+psycopg://`
  (sync) because Alembic runs DDL via a sync engine. Install `psycopg[binary]`
  in the api image (or use `postgresql://` which asyncpg's sync wrapper handles).
- `compare_type=True` and `compare_server_default=True` are on — autogenerate
  detects type and server-default changes, not just column add/drop.
- The `cian_houses_map` view, `dashboard_parsed_ads`, and `pipeline_runs`
  tables are NOT in `packages/flipper_db/models.py` yet (they live as raw SQL
  in `scripts/create_*.sql` and `services/pipeline_runner/main.py`). To bring
  them under Alembic: add ORM models for them, then autogenerate will emit
  migrations. Until then, manage those via the existing SQL scripts.
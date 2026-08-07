"""Alembic environment for Flipper.

Async engine, reads models from packages/flipper_db.models so
`alembic revision --autogenerate` can diff models vs DB schema.

DATABASE_URL is read from the environment (same URL used by all services).
The async URL (postgresql+asyncpg://) is converted to the sync driver
(postgresql+psycopg://) for migrations — Alembic runs DDL synchronously
inside engine.begin() regardless of the URL scheme.
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make packages/flipper_db importable.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from packages.flipper_db.base import get_database_url  # noqa: E402
from packages.flipper_db.models import Base  # noqa: E402

config = context.config

# Interpret config file for Python logging if present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate.
target_metadata = Base.metadata


def _resolve_url() -> str:
    """Pick the DATABASE_URL to use for migrations.

    Priority:
      1. explicit -x url=... on the alembic CLI (overrides everything)
      2. sqlalchemy.url in alembic.ini (if set)
      3. $DATABASE_URL env
      4. packages.flipper_db.base.get_database_url() (DEFAULT_DATABASE_URL)
    """
    # CLI override: `alembic upgrade head -x url=postgresql://...`
    cli_url = context.get_x_argument(as_dictionary=True).get("url")
    if cli_url:
        return cli_url
    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    return get_database_url()


def _sync_url(url: str) -> str:
    """Convert async URL to a sync driver for Alembic's sync engine.

    Alembic runs DDL via engine.begin() (sync). The async URL uses
    postgresql+asyncpg:// — we swap to postgresql+psycopg:// (psycopg3)
    which is sync. Falls back to plain postgresql:// if psycopg isn't
    installed (asyncpg's sync wrapper is used by SQLAlchemy).
    """
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout, no DB connection)."""
    url = _sync_url(_resolve_url())
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect to DB, run DDL)."""
    url = _sync_url(_resolve_url())
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = url

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
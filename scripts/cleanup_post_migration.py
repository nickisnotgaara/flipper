"""scripts.cleanup_post_migration - убрать артефакты первой версии мигратора.

Что делает:
    1. DROP COLUMN active_ads.is_avans (мы добавили её для разделения
       source='avans', но это уже есть в raw_data->>'has_avans_deposit'
       и filter_id=6 — лишняя).
    2. UPDATE active_ads.raw_data: убрать служебные маркеры
       _server_source, _is_avans, _server_filter_id, _local_filter_id.
       Они ничего не значат после репарсинга (flippercrawl затрёт raw_data
       целиком) и при синке обратно на сервер они не нужны.
    3. UPDATE sold_ads.raw_data: убрать _server_source (аналогично).

Идемпотентен: повторный запуск ничего не ломает.

Note: колонка raw_data — ``JSON`` (не ``jsonb``) в текущей схеме, поэтому
оператор ``-`` не работает. Делаем через Python: читаем dict, удаляем ключи,
пишем обратно.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger("cleanup")

ACTIVE_MARKERS = ("_server_source", "_is_avans", "_server_filter_id", "_local_filter_id")
SOLD_MARKERS = ("_server_source",)


def _default_local_url() -> str:
    """URL с +asyncpg (для SQLAlchemy)."""
    return os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://flipper:flipper_secret@app_postgres:5432/flipper",
    )


def _to_asyncpg_dsn(url: str) -> str:
    """asyncpg не ест +asyncpg, нормализуем для прямого коннекта."""
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _strip_keys(d: dict, keys: Iterable[str]) -> tuple[dict, bool]:
    out = dict(d)
    changed = False
    for k in keys:
        if k in out:
            del out[k]
            changed = True
    return out, changed


async def run(local_url: str) -> int:
    # 1. DROP COLUMN is_avans
    engine = create_async_engine(local_url)
    try:
        async with engine.begin() as conn:
            logger.info("Шаг 1/3: DROP COLUMN active_ads.is_avans ...")
            try:
                await conn.execute(
                    text("ALTER TABLE active_ads DROP COLUMN IF EXISTS is_avans")
                )
                logger.info("  -> OK")
            except Exception as e:
                logger.warning("  -> DROP COLUMN: %s (продолжаем)", e)
    finally:
        await engine.dispose()

    # 2 + 3. UPDATE raw_data через asyncpg (JSON тип не поддерживает `-`)
    logger.info("Шаг 2/3: UPDATE active_ads.raw_data: strip markers ...")
    logger.info("Шаг 3/3: UPDATE sold_ads.raw_data: strip _server_source ...")
    conn = await asyncpg.connect(_to_asyncpg_dsn(local_url))
    try:
        for tbl, markers, where in [
            ("active_ads", ACTIVE_MARKERS, "source='cian_active'"),
            ("sold_ads", SOLD_MARKERS, "source='cian_active'"),
        ]:
            updated = 0
            skipped = 0
            BATCH = 500
            offset = 0
            while True:
                rows = await conn.fetch(
                    f"SELECT id, raw_data FROM {tbl} WHERE {where} "
                    f"AND raw_data IS NOT NULL "
                    f"ORDER BY id LIMIT {BATCH} OFFSET {offset}"
                )
                if not rows:
                    break
                for r in rows:
                    raw = r["raw_data"]
                    if isinstance(raw, (bytes, bytearray)):
                        raw = raw.decode("utf-8", errors="replace")
                    if isinstance(raw, str):
                        try:
                            d = json.loads(raw)
                        except (ValueError, TypeError):
                            skipped += 1
                            continue
                    elif isinstance(raw, dict):
                        d = raw
                    else:
                        skipped += 1
                        continue

                    new_d, changed = _strip_keys(d, markers)
                    if not changed:
                        continue
                    new_raw = json.dumps(new_d, ensure_ascii=False)
                    await conn.execute(
                        f"UPDATE {tbl} SET raw_data = $1::json WHERE id = $2",
                        new_raw,
                        r["id"],
                    )
                    updated += 1
                offset += BATCH
            logger.info("  -> %s: updated=%s skipped=%s", tbl, updated, skipped)
    finally:
        await conn.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--local-url",
        default=_default_local_url(),
        help="DATABASE_URL локальной БД. Default: $DATABASE_URL",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    return asyncio.run(run(args.local_url))


if __name__ == "__main__":
    sys.exit(main())

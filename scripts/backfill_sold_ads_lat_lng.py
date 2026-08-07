"""scripts/backfill_sold_ads_lat_lng.py — заполнить lat/lng в sold_ads.

Зачем: 232к снятых объявлений сейчас невидимы на карте «только снятые»
кластеры, потому что у них нет координат ни в raw_data, ни в колонках.
Но у 232,211 из них есть `house_id` → можно заполнить lat/lng из
`houses.lat/lng` и они появятся на карте.

Идемпотентный (запускать можно сколько угодно раз, обновляет только
NULL-ячейки).

Использование:
    py scripts/backfill_sold_ads_lat_lng.py
    py scripts/backfill_sold_ads_lat_lng.py --batch-size 5000 --verbose
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from packages.flipper_db.base import DEFAULT_DATABASE_URL  # noqa: E402


async def main(dsn: str, batch_size: int, verbose: bool) -> None:
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    log = logging.getLogger("backfill")

    t0 = time.monotonic()
    conn = await asyncpg.connect(dsn)
    try:
        # 1) Сначала из связанного houses (если house_id есть и house с lat/lng).
        #    Используем UPDATE FROM (PostgreSQL 9.5+).
        log.info("Backfilling lat/lng from houses for sold_ads WITH house_id...")
        updated = await conn.fetchrow("""
            WITH upd AS (
                UPDATE sold_ads s
                SET lat = h.lat, lng = h.lng
                FROM houses h
                WHERE s.house_id = h.id
                  AND s.lat IS NULL AND s.lng IS NULL
                  AND h.lat IS NOT NULL AND h.lng IS NOT NULL
                RETURNING s.id
            )
            SELECT count(*) AS n FROM upd
        """)
        n_from_houses = int(updated["n"]) if updated else 0
        log.info("  → backfilled %d rows from houses.lat/lng", n_from_houses)

        # 2) Затем для оставшихся NULL-строк берём lat/lng из raw_data.
        log.info("Backfilling lat/lng from raw_data for remaining sold_ads...")
        updated = await conn.fetchrow("""
            WITH upd AS (
                UPDATE sold_ads s
                SET lat = (s.raw_data->'offer'->'geo'->'coordinates'->>'lat')::float8,
                    lng = (s.raw_data->'offer'->'geo'->'coordinates'->>'lng')::float8
                WHERE s.lat IS NULL AND s.lng IS NULL
                  AND (s.raw_data->'offer'->'geo'->'coordinates'->>'lat') IS NOT NULL
                  AND (s.raw_data->'offer'->'geo'->'coordinates'->>'lng') IS NOT NULL
                RETURNING s.id
            )
            SELECT count(*) AS n FROM upd
        """)
        n_from_raw = int(updated["n"]) if updated else 0
        log.info("  → backfilled %d rows from raw_data", n_from_raw)

        # 3) Что осталось без координат — статистика.
        remaining = await conn.fetchrow("""
            SELECT count(*) FILTER (WHERE lat IS NULL OR lng IS NULL) AS no_lat_lng,
                   count(*) FILTER (WHERE house_id IS NULL) AS no_house,
                   count(*) AS total
            FROM sold_ads
        """)
        log.info(
            "Итого: %d всего, %d без lat/lng, %d без house_id",
            remaining["total"],
            remaining["no_lat_lng"],
            remaining["no_house"],
        )

        elapsed = time.monotonic() - t0
        log.info(
            "DONE in %.1fs: from_houses=%d, from_raw=%d, no_coords=%d",
            elapsed, n_from_houses, n_from_raw, remaining["no_lat_lng"],
        )
    finally:
        await conn.close()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dsn", default=DEFAULT_DATABASE_URL.replace(
        "postgresql+asyncpg://", "postgresql://", 1,
    ))
    p.add_argument("--batch-size", type=int, default=5000)
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args.dsn, args.batch_size, args.verbose))

"""scripts.backfill_active_ads_house_id - link active_ads to houses by lat/lng proximity.

После миграции у всех cian_active ads house_id=NULL → карта пустая.
OfferData содержит raw_data.offer.geo.coordinates.{lat,lng}.
houses содержит lat/lng для 29 783 домов.

Стратегия: предварительно бакетезируем houses по 0.01° (~1.1km × 0.7km)
и для каждого ad ищем ближайший в своём бакете ±1 (3×3 grid), потом
fallback к distance check.

Идемпотентен: WHERE house_id IS NULL.
Прерываемый: можно запускать повторно.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sys
from pathlib import Path
from typing import Optional

import asyncpg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("backfill_house_id")


def _default_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://flipper:flipper_secret@app_postgres:5432/flipper",
    )


def _to_asyncpg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _bucket(lat: float, lng: float, size: float = 0.01) -> tuple[int, int]:
    """Бакетезируем по 0.01° (lat=1.1km, lng=~700m в Москве)."""
    return (int(math.floor(lat / size)), int(math.floor(lng / size)))


def _dist_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Грубая оценка расстояния в метрах (для Москвы допустимо)."""
    avg_lat = (lat1 + lat2) / 2
    dlat_m = (lat2 - lat1) * 111_000
    dlng_m = (lng2 - lng1) * 111_000 * math.cos(math.radians(avg_lat))
    return math.hypot(dlat_m, dlng_m)


async def _build_house_index(conn: asyncpg.Connection) -> dict[tuple[int, int], list[dict]]:
    """Загрузить все houses с координатами в память, индексировать по 0.01° bucket."""
    rows = await conn.fetch("""
        SELECT id, lat, lng, address FROM houses
        WHERE lat IS NOT NULL AND lng IS NOT NULL
    """)
    idx: dict[tuple[int, int], list[dict]] = {}
    for r in rows:
        b = _bucket(r["lat"], r["lng"])
        idx.setdefault(b, []).append({"id": r["id"], "lat": r["lat"], "lng": r["lng"]})
    return idx


def _find_nearest(
    house_idx: dict[tuple[int, int], list[dict]],
    lat: float,
    lng: float,
    max_dist_m: float = 500.0,
) -> Optional[int]:
    """Ближайший house_id в 3×3 buckets вокруг (lat,lng), если ≤ max_dist_m."""
    b = _bucket(lat, lng)
    best_id: Optional[int] = None
    best_d = float("inf")
    for dlat in (-1, 0, 1):
        for dlng in (-1, 0, 1):
            for h in house_idx.get((b[0] + dlat, b[1] + dlng), []):
                d = _dist_m(lat, lng, h["lat"], h["lng"])
                if d < best_d:
                    best_d = d
                    best_id = h["id"]
    if best_id is not None and best_d <= max_dist_m:
        return best_id
    return None


async def main_async(url: str, max_dist_m: float) -> int:
    dsn = _to_asyncpg_dsn(url)
    conn = await asyncpg.connect(dsn)
    try:
        # 1. Load houses index
        logger.info("Loading houses index (0.01° buckets) ...")
        house_idx = await _build_house_index(conn)
        logger.info("  -> %d unique buckets, %d houses", len(house_idx), sum(len(v) for v in house_idx.values()))

        # 2. Load ads needing house_id
        rows = await conn.fetch("""
            SELECT external_id,
                   (raw_data->'offer'->'geo'->'coordinates'->>'lat')::float8 AS lat,
                   (raw_data->'offer'->'geo'->'coordinates'->>'lng')::float8 AS lng
            FROM active_ads
            WHERE source='cian_active'
              AND is_active=true
              AND house_id IS NULL
              AND raw_data->'offer'->'geo'->'coordinates'->>'lat' IS NOT NULL
              AND raw_data->'offer'->'geo'->'coordinates'->>'lng' IS NOT NULL
        """)
        ads = [(r["external_id"], r["lat"], r["lng"]) for r in rows]
        logger.info("  -> %d active_ads waiting for house_id", len(ads))
        if not ads:
            return 0

        # 3. Match
        matched: list[tuple[str, int]] = []
        unmatched: list[tuple[str, float, float]] = []
        for ext_id, lat, lng in ads:
            hid = _find_nearest(house_idx, lat, lng, max_dist_m=max_dist_m)
            if hid is not None:
                matched.append((ext_id, hid))
            else:
                unmatched.append((ext_id, lat, lng))
        logger.info("  -> matched (within %dm): %d, unmatched: %d", max_dist_m, len(matched), len(unmatched))

        # 4. UPDATE in batches
        updated = 0
        BATCH = 500
        for i in range(0, len(matched), BATCH):
            chunk = matched[i:i + BATCH]
            values_sql = ",".join(f"(${j*2+1}::text, ${j*2+2}::bigint)" for j in range(len(chunk)))
            params: list = []
            for eid, hid in chunk:
                params.extend([eid, hid])
            sql = f"""
                UPDATE active_ads AS a
                SET house_id = v.hid
                FROM (VALUES {values_sql}) AS v(eid, hid)
                WHERE a.source='cian_active' AND a.external_id = v.eid
            """
            res = await conn.execute(sql, *params)
            try:
                n = int(res.split()[-1])
            except Exception:
                n = 0
            updated += n
            logger.info("  batch %d-%d: %s", i, i + len(chunk), res)

        logger.info("=== DONE ===")
        logger.info("  ads with coords:    %d", len(ads))
        logger.info("  matched candidates: %d", len(matched))
        logger.info("  rows updated:       %d", updated)
        logger.info("  unmatched (>%dm):   %d", max_dist_m, len(unmatched))

        if unmatched[:20]:
            logger.info("--- sample unmatched (lat,lng) ---")
            for eid, lat, lng in unmatched[:20]:
                logger.info("  %s  (%.5f, %.5f)", eid, lat, lng)
        return 0
    finally:
        await conn.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--url", default=_default_url())
    p.add_argument("--max-dist", type=float, default=500.0,
                   help="Max distance in meters to consider a match (default 500)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    return asyncio.run(main_async(args.url, args.max_dist))


if __name__ == "__main__":
    sys.exit(main())

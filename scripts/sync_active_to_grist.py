#!/usr/bin/env python3
"""
sync_active_to_grist.py — синхронизация PostgreSQL active_ads → Grist Active_ads.

Источники active_ads (поле `source`):
  - cian_active  — основной парсер
  - domclick     — domclick активные (если есть)

Использование:
  py scripts/sync_active_to_grist.py                # все active_ads
  py scripts/sync_active_to_grist.py --limit 1000
  py scripts/sync_active_to_grist.py --source cian_active
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import asyncpg
from packages.flipper_core.grist import GristClient


PG_DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper",
)
if PG_DSN.startswith("postgresql+asyncpg://"):
    PG_DSN_ASYNC = PG_DSN.replace("postgresql+asyncpg://", "postgresql://", 1)
else:
    PG_DSN_ASYNC = PG_DSN

GRIST_TABLE = "Active_ads"


def _row_to_grist(row: dict) -> dict:
    """active_ads → Grist dict. Только колонки, которые есть в Active_ads."""
    raw = row.get("raw_data")
    if isinstance(raw, str):
        try:
            parsed_data = json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            parsed_data = {}
    elif isinstance(raw, dict):
        parsed_data = raw
    else:
        parsed_data = {}
    d = {
        "external_id": int(row["external_id"]) if row.get("external_id") else None,
        "source": row.get("source"),
        "url": row.get("url"),
        "house_id": int(row["house_id"]) if row.get("house_id") else None,
        "price": int(row["price"]) if row.get("price") else None,
        "price_per_m2": int(row["price_per_m2"]) if row.get("price_per_m2") else None,
        "area": float(row["area"]) if row.get("area") else None,
        "rooms": int(row["rooms"]) if row.get("rooms") else None,
        "floor_current": int(row["floor_current"]) if row.get("floor_current") else None,
        "floor_total": int(row["floor_total"]) if row.get("floor_total") else None,
        "metro_station": row.get("metro_station") or parsed_data.get("metro_station"),
        "metro_walk_time": int(row["metro_walk_time"]) if row.get("metro_walk_time") else None,
        "district": row.get("district") or parsed_data.get("district"),
        "okrug": row.get("okrug") or parsed_data.get("okrug"),
        "renovation": row.get("renovation") or parsed_data.get("renovation"),
        "is_active": bool(row.get("is_active", True)),
        "days_in_exposition": int(row["days_in_exposition"]) if row.get("days_in_exposition") else None,
        "total_views": int(row["total_views"]) if row.get("total_views") else None,
        "unique_views": int(row["unique_views"]) if row.get("unique_views") else None,
        "publish_date": row.get("publish_date"),
        "filter_id": int(row["filter_id"]) if row.get("filter_id") else None,
    }
    out = {}
    for k, v in d.items():
        if v is not None:
            out[k] = _to_jsonable(v)
    return out


def _to_jsonable(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _to_jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_to_jsonable(x) for x in v]
    return str(v)


async def fetch_active_ads(source: str | None, limit: int | None) -> list[dict]:
    sql = """
        SELECT id, source, external_id, url, house_id, price, price_per_m2, area, rooms,
               floor_current, floor_total, metro_station, metro_walk_time, district, okrug,
               renovation, is_active, days_in_exposition, total_views, unique_views,
               publish_date, filter_id, raw_data
        FROM active_ads
    """
    params: list = []
    if source:
        sql += " WHERE source = $1"
        params.append(source)
    if limit:
        sql += f" LIMIT {int(limit)}"
    conn = await asyncpg.connect(PG_DSN_ASYNC)
    try:
        rows = await conn.fetch(sql, *params)
    finally:
        await conn.close()
    return [dict(r) for r in rows]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    print(f"=== sync_active_to_grist ===")
    print(f"PG:    {PG_DSN_ASYNC.split('@')[-1]}")
    print(f"Grist: {GRIST_TABLE}")
    print(f"Source filter: {args.source or '(all)'}")
    print(f"Limit: {args.limit or '(none)'}")

    rows = await fetch_active_ads(args.source, args.limit)
    print(f"PG rows: {len(rows)}")
    if not rows:
        return 0

    grist = GristClient()
    ok = 0
    failed = 0
    skipped = 0
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        ext_id = r.get("external_id")
        if not ext_id:
            skipped += 1
            continue
        try:
            row_dict = _row_to_grist(r)
            if grist.upsert_dict(GRIST_TABLE, row_dict, ext_id):
                ok += 1
            else:
                skipped += 1
        except Exception as e:
            failed += 1
            print(f"  [{i}/{len(rows)}] FAIL ext_id={ext_id}: {e}")
        if i % 50 == 0:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            print(f"  [{i}/{len(rows)}] {ok} ok, {failed} failed, {skipped} skipped — {rate:.1f} rows/s")

    elapsed = time.time() - t0
    print(f"\n=== DONE ===")
    print(f"Upserted: {ok}  Failed: {failed}  Skipped: {skipped}")
    print(f"Time: {elapsed:.1f}s ({ok/elapsed:.1f} rows/s)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

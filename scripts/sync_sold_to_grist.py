#!/usr/bin/env python3
"""
sync_sold_to_grist.py — синхронизация PostgreSQL sold_ads → Grist Снятые (Sold_Ads).

Источники sold_ads (поле `source`):
  - cian_deactivated   — парсер cian_active при снятии
  - cian_sold          — historical cian sold (services/parsers/cian_sold)
  - domclick_sold      — domclick (services/parsers/domclick_sold)
  - winners_sold       — winners (services/parsers/winners_sold)

Поведение:
  - Берём все sold_ads (limit опционально)
  - Batch insert в Sold_Ads по cian_id (300 actions / /apply call)
  - status="deactivated" выставляется автоматически (через Grist UI — серая заливка)
  - photos_url + map_url — формулы, вычисляются автоматически
  - Архив_Продано (Arhiv_Prodano, бывш. Table1) НЕ трогаем — это read-only история

Использование:
  py scripts/sync_sold_to_grist.py                       # все sold_ads
  py scripts/sync_sold_to_grist.py --limit 1000          # первые 1000 (тест)
  py scripts/sync_sold_to_grist.py --source cian_deactivated
  py scripts/sync_sold_to_grist.py --batch 500           # размер пачки (default 300)
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
# asyncpg ожидает postgresql://, не postgresql+asyncpg://
if PG_DSN.startswith("postgresql+asyncpg://"):
    PG_DSN_ASYNC = PG_DSN.replace("postgresql+asyncpg://", "postgresql://", 1)
else:
    PG_DSN_ASYNC = PG_DSN

GRIST_TABLE_SOLD = "Sold_Ads"   # display: "Снятые"


def _to_jsonable(v):
    """Привести Python-значение к JSON-friendly (для ApplyRecord columns)."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _to_jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_to_jsonable(x) for x in v]
    return str(v)


def _truncate(v, n):
    """Безопасно обрезать строку. Если не строка — _to_jsonable → str."""
    if v is None:
        return None
    if isinstance(v, str):
        s = v
    else:
        s = str(_to_jsonable(v))
    return s[:n] if s else None


def _row_to_grist(row: dict) -> dict:
    """Маппинг sold_ads (PG) → Grist row (Sold_Ads: 28 cols + status).

    Sold_Ads имеет полный набор колонок — пишем всё что есть из PG + raw_data.
    photos_url + map_url — формулы, вычисляются в Grist автоматически.
    """
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

    # floor_info: combine floor_current / floor_total → "X/Y" (или просто X)
    fc = row.get("floor_current")
    ft = row.get("floor_total")
    floor_info = ""
    if fc is not None and ft is not None:
        floor_info = f"{fc}/{ft}"
    elif fc is not None:
        floor_info = str(fc)
    elif ft is not None:
        floor_info = f"?/{ft}"

    d = {
        "source": row.get("source") or "unknown",
        "cian_id": int(row["external_id"]) if row.get("external_id") else None,
        "url": row.get("url"),
        "house_id": int(row["house_id"]) if row.get("house_id") else None,
        "price": int(row["price"]) if row.get("price") is not None else None,
        "price_per_m2": int(row["price_per_m2"]) if row.get("price_per_m2") is not None else None,
        "area": float(row["area"]) if row.get("area") is not None else None,
        "rooms": int(row["rooms"]) if row.get("rooms") is not None else None,
        "floor_current": int(fc) if fc is not None else None,
        "floor_total": int(ft) if ft is not None else None,
        "floor_info": floor_info or None,
        "renovation": row.get("renovation"),
        "publish_date": row.get("publish_date").isoformat() if row.get("publish_date") else None,
        "sold_date": row.get("sold_date").isoformat() if row.get("sold_date") else None,
        "exposition_days": int(row["exposition_days"]) if row.get("exposition_days") is not None else None,
        "parsed_at": row.get("parsed_at").isoformat() if row.get("parsed_at") else None,
        "status": "deactivated",
        # Из parsed_data (если есть):
        "title": _truncate(parsed_data.get("title"), 300),
        "address": _truncate(parsed_data.get("address") or row.get("address"), 300),
        "description": _truncate(parsed_data.get("description"), 2000),
        "construction_year": int(parsed_data["construction_year"]) if parsed_data.get("construction_year") else None,
        "district": parsed_data.get("district") or row.get("district"),
        "okrug": parsed_data.get("okrug") or row.get("okrug"),
        "metro_station": parsed_data.get("metro_station") or row.get("metro_station"),
        "metro_walk_time": int(parsed_data["metro_walk_time"]) if parsed_data.get("metro_walk_time") else None,
        "total_views": int(parsed_data["total_views"]) if parsed_data.get("total_views") else None,
        "unique_views": int(parsed_data["unique_views"]) if parsed_data.get("unique_views") else None,
    }
    out = {}
    for k, v in d.items():
        if v is not None and v != "":
            out[k] = _to_jsonable(v)
    return out


def get_existing_cian_ids(grist: GristClient) -> set[int]:
    """Query Grist for already-synced cian_ids. Skip these in bulk insert."""
    r = grist.sql('SELECT cian_id FROM Sold_Ads WHERE cian_id IS NOT NULL')
    out = set()
    for x in r:
        v = x["fields"].get("cian_id")
        if v is not None:
            try:
                out.add(int(v))
            except (ValueError, TypeError):
                pass
    return out


async def fetch_sold_ads(source: str | None, limit: int | None) -> list[dict]:
    sql = """
        SELECT id, source, external_id, url, house_id, cian_house_id, price,
               price_per_m2, area, rooms, floor_current, floor_total, renovation,
               exposition_days, publish_date, sold_date, raw_data, parsed_at
        FROM sold_ads
    """
    params: list = []
    if source:
        sql += " WHERE source = $1"
        params.append(source)
    sql += " ORDER BY id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    conn = await asyncpg.connect(PG_DSN_ASYNC)
    try:
        rows = await conn.fetch(sql, *params)
    finally:
        await conn.close()
    return [dict(r) for r in rows]


def _bulk_post_records(grist: GristClient, rows: list[dict]) -> int:
    """POST /api/docs/{docId}/tables/{tableId}/records — native bulk endpoint.

    Быстрее BulkAddRecord: ~830 rows/s при batch=2000, ~1650 rows/s при batch=5000.
    body = {"records": [{"fields": {...}}, ...]}
    """
    if not rows:
        return 0
    body = {"records": [{"fields": r} for r in rows]}
    grist._request("POST", f"/api/docs/{grist.doc_id}/tables/{GRIST_TABLE_SOLD}/records", body)
    return len(rows)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None, help="sold_ads.source (cian_deactivated/cian_sold/domclick_sold/winners_sold)")
    ap.add_argument("--limit", type=int, default=None, help="Max rows to sync")
    ap.add_argument("--batch", type=int, default=2000, help="Rows per /records POST (default 2000)")
    ap.add_argument("--dry-run", action="store_true", help="Только показать план, не писать")
    args = ap.parse_args()

    print(f"=== sync_sold_to_grist ===")
    print(f"PG:    {PG_DSN_ASYNC.split('@')[-1]}")
    print(f"Grist: {GRIST_TABLE_SOLD} (display: Снятые)")
    print(f"Source filter: {args.source or '(all)'}")
    print(f"Limit: {args.limit or '(none)'}")
    print(f"Batch size: {args.batch}")
    print()

    grist = GristClient()
    print("Loading existing cian_ids from Sold_Ads (skip duplicates)...")
    t0 = time.time()
    existing = get_existing_cian_ids(grist)
    print(f"  already in Sold_Ads: {len(existing)} ({time.time() - t0:.1f}s)")

    rows = await fetch_sold_ads(args.source, args.limit)
    print(f"PG rows: {len(rows)}")

    # Фильтруем уже синхронизированные
    before = len(rows)
    def _is_synced(r):
        eid = r.get("external_id")
        if not eid:
            return False
        try:
            return int(eid) in existing
        except (ValueError, TypeError):
            return False
    rows = [r for r in rows if not _is_synced(r)]
    skipped_dup = before - len(rows)
    print(f"After skip-existing: {len(rows)} (skipped {skipped_dup} already synced)")
    if not rows:
        return 0

    if args.dry_run:
        print("\n--- DRY RUN: first 3 mapped rows ---")
        for r in rows[:3]:
            print(json.dumps(_row_to_grist(r), ensure_ascii=False, indent=2))
        return 0

    grist_apply = grist.apply
    ok = 0
    failed = 0
    skipped = 0
    t0 = time.time()
    batch: list[dict] = []
    batch_n = 0
    total = len(rows)
    for i, r in enumerate(rows, 1):
        cian_id = r.get("external_id")
        if not cian_id:
            skipped += 1
            continue
        try:
            row_dict = _row_to_grist(r)
            if not row_dict.get("cian_id"):
                skipped += 1
                continue
            batch.append(row_dict)
            if len(batch) >= args.batch:
                try:
                    _bulk_post_records(grist, batch)
                    batch_n += 1
                    ok += len(batch)
                except Exception as e:
                    failed += len(batch)
                    print(f"  [batch {batch_n}] FAIL: {e}")
                batch = []
        except Exception as e:
            failed += 1
            print(f"  [{i}/{total}] FAIL cian_id={cian_id}: {e}")

        if i % 1000 == 0:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (total - i) / rate if rate > 0 else 0
            print(
                f"  [{i}/{total}] {ok} ok, {failed} failed, {skipped} skipped — "
                f"{rate:.0f} rows/s, ETA {eta:.0f}s"
            )

    # last batch
    if batch:
        try:
            _bulk_post_records(grist, batch)
            batch_n += 1
            ok += len(batch)
        except Exception as e:
            failed += len(batch)
            print(f"  [batch {batch_n}] FAIL: {e}")

    elapsed = time.time() - t0
    print(f"\n=== DONE ===")
    print(f"Upserted: {ok}  Failed: {failed}  Skipped: {skipped}")
    print(f"Time: {elapsed:.1f}s ({ok/elapsed:.1f} rows/s)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

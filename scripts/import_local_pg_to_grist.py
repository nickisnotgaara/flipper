"""
import_local_pg_to_grist.py — одноразовая заливка таблиц из локального PG в Grist.

Что делает:
  1. Берёт существующий документ "parsing" в Grist (или свой через --doc-id)
  2. Создаёт таблицы Houses (30k) и ActiveAds (5k) с правильной схемой
  3. Заливает данные батчами по 500 строк

Использование:
  py scripts/import_local_pg_to_grist.py                       # дефолт — parsing doc
  py scripts/import_local_pg_to_grist.py --doc-id <id>        # другой документ
  py scripts/import_local_pg_to_grist.py --tables houses       # только houses
  py scripts/import_local_pg_to_grist.py --tables houses,active_ads
  py scripts/import_local_pg_to_grist.py --dry-run             # показать что будет, не заливать
"""
from __future__ import annotations
import argparse
import os
import sys
import time

import asyncpg
import requests

GRIST_URL = os.environ.get("GRIST_URL", "http://127.0.0.1:8484")
GRIST_API_KEY = os.environ.get(
    "GRIST_API_KEY",
    "flipper_prod_c173df83d342e744aa1fa74bb80bd19a32f5f598d7e582c0c8d4561659290978",
)
PG_DSN = os.environ.get(
    "PG_DSN", "postgresql://flipper:flipper_secret@127.0.0.1:5432/flipper"
)
# Дефолтный документ — parsing doc, который уже живой
DEFAULT_DOC_ID = "mDaHoGD6yahtxaqugwr5mK"
SESSION = requests.Session()
SESSION.headers.update({"Authorization": f"Bearer {GRIST_API_KEY}"})


def grist(method, path, **kw):
    """Thin wrapper around Grist API с авторизацией."""
    r = SESSION.request(method, f"{GRIST_URL}{path}", timeout=180, **kw)
    if not r.ok:
        raise RuntimeError(f"GRIST {method} {path} -> {r.status_code}: {r.text[:1000]}")
    return r.json() if r.text else None


def find_or_create_doc(name: str) -> str:
    """Создаёт новый документ. Запасной путь — если не работает, используйте --doc-id."""
    r = grist("GET", "/api/orgs/flipper/workspaces")
    workspaces = r
    for ws in workspaces:
        for d in ws.get("docs", []):
            if d.get("name") == name:
                print(f"  Found existing doc '{name}' = {d['id']}")
                return d["id"]
    if not workspaces:
        raise RuntimeError("No workspaces found")
    ws_id = workspaces[0]["id"]
    # В Grist 1.7 нужен другой endpoint. Попробуем несколько вариантов.
    for endpoint in [f"/api/orgs/flipper/workspaces/{ws_id}/docs"]:
        r2 = SESSION.post(
            f"{GRIST_URL}{endpoint}",
            json={"name": name},
            timeout=10,
        )
        if r2.ok:
            doc_id = r2.json()
            print(f"  Created new doc '{name}' = {doc_id}")
            return doc_id
    raise RuntimeError(
        f"Could not create doc via API. Use --doc-id <existing> instead. "
        f"Try creating manually in Grist UI first."
    )


def find_or_create_table(doc_id: str, table_name: str, columns: list[dict]) -> str:
    """Создаёт таблицу с заданными колонками. Возвращает tableId."""
    tables = grist("GET", f"/api/docs/{doc_id}/tables").get("tables", [])
    for t in tables:
        if t.get("id") == table_name:
            print(f"    Found existing table {table_name} = {t['id']}")
            return t["id"]
    # Создаём
    cols = [{"id": c["name"], "label": c.get("label", c["name"]), "type": c["type"]} for c in columns]
    r = grist(
        "POST",
        f"/api/docs/{doc_id}/tables",
        json={"tables": [{"id": table_name, "columns": cols}]},
    )
    table_id = r["tables"][0]["id"]
    print(f"    Created table {table_name} = {table_id}")
    return table_id


def upload_records(doc_id: str, table_id: str, rows: list[dict]) -> int:
    """Заливает пачку строк. Возвращает количество залитых."""
    if not rows:
        return 0
    payload = {
        "records": [
            {"fields": {k: _ser(v) for k, v in row.items() if v is not None}}
            for row in rows
        ]
    }
    r = grist(
        "POST",
        f"/api/docs/{doc_id}/tables/{table_id}/records",
        json=payload,
    )
    return len(r.get("records", [])) if isinstance(r, dict) else 0


def _ser(v):
    """Grist не принимает некоторые типы (datetime, date, Decimal). Конвертим в строки."""
    import datetime
    import decimal
    if isinstance(v, datetime.datetime):
        return v.isoformat()
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    return v


# Схемы колонок для импорта
HOUSES_COLS = [
    {"name": "id", "type": "Int"},
    {"name": "source", "type": "Text"},
    {"name": "external_house_id", "type": "Text"},
    {"name": "cian_house_id", "type": "Int"},
    {"name": "address", "type": "Text"},
    {"name": "street", "type": "Text"},
    {"name": "house_num", "type": "Text"},
    {"name": "district", "type": "Text"},
    {"name": "okrug", "type": "Text"},
    {"name": "lat", "type": "Numeric"},
    {"name": "lng", "type": "Numeric"},
    {"name": "year_built", "type": "Int"},
    {"name": "levels", "type": "Int"},
    {"name": "building_type", "type": "Text"},
    {"name": "series", "type": "Text"},
    {"name": "package", "type": "Text"},
    {"name": "updated_at", "type": "DateTime"},
]

ACTIVE_ADS_COLS = [
    {"name": "id", "type": "Int"},
    {"name": "source", "type": "Text"},
    {"name": "external_id", "type": "Text"},
    {"name": "url", "type": "Text"},
    {"name": "house_id", "type": "Int"},
    {"name": "price", "type": "Numeric"},
    {"name": "price_per_m2", "type": "Numeric"},
    {"name": "area", "type": "Numeric"},
    {"name": "rooms", "type": "Int"},
    {"name": "floor_current", "type": "Int"},
    {"name": "floor_total", "type": "Int"},
    {"name": "metro_station", "type": "Text"},
    {"name": "metro_walk_time", "type": "Int"},
    {"name": "district", "type": "Text"},
    {"name": "okrug", "type": "Text"},
    {"name": "renovation", "type": "Text"},
    {"name": "is_active", "type": "Bool"},
    {"name": "days_in_exposition", "type": "Int"},
    {"name": "total_views", "type": "Int"},
    {"name": "unique_views", "type": "Int"},
    {"name": "publish_date", "type": "Date"},
    {"name": "filter_id", "type": "Int"},
    {"name": "updated_at", "type": "DateTime"},
]


async def fetch_chunks(conn, sql, batch=500):
    """Async generator — отдаёт строки пачками."""
    offset = 0
    while True:
        rows = await conn.fetch(f"{sql} LIMIT {batch} OFFSET {offset}")
        if not rows:
            return
        yield [dict(r) for r in rows]
        offset += batch
        if len(rows) < batch:
            return


async def import_table(pg, doc_id, table_name, sql, columns, dry_run=False):
    print(f"\n  Importing {table_name}...")
    table_id = find_or_create_table(doc_id, table_name, columns)
    if dry_run:
        async with pg.acquire() as conn:
            total = await conn.fetchval(f"SELECT COUNT(*) FROM ({sql}) _sub")
        print(f"    [dry-run] would import {total} rows")
        return
    conn = await pg.acquire()
    try:
        total = 0
        t0 = time.time()
        offset = 0
        while True:
            rows = await conn.fetch(f"{sql} LIMIT 500 OFFSET {offset}")
            if not rows:
                break
            payload = [dict(r) for r in rows]
            n = upload_records(doc_id, table_id, payload)
            total += n
            offset += 500
            elapsed = time.time() - t0
            print(f"    ... {total} rows in {elapsed:.1f}s ({total/elapsed:.0f} rows/s)", flush=True)
            if len(rows) < 500:
                break
        print(f"    DONE: {total} rows in {time.time()-t0:.1f}s")
    finally:
        await pg.release(conn)


async def main_async(args):
    pg = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2)
    try:
        if args.doc_id:
            doc_id = args.doc_id
            print(f"Using existing doc: {doc_id}")
        else:
            doc_id = DEFAULT_DOC_ID
            print(f"Using default doc (parsing): {doc_id}")
        print(f"\nDoc URL: {GRIST_URL}/o/flipper/doc/{doc_id}")
        print(f"Doc API: {GRIST_URL}/api/docs/{doc_id}")

        for table in args.tables.split(","):
            table = table.strip()
            if table == "houses":
                sql = """
                  SELECT id, source, external_house_id, cian_house_id,
                         address, street, house_num, district, okrug,
                         lat, lng, year_built, levels, building_type, series,
                         package, updated_at
                  FROM houses
                  ORDER BY id
                """
                await import_table(pg, doc_id, "Houses", sql, HOUSES_COLS, args.dry_run)
            elif table == "active_ads":
                sql = """
                  SELECT id, source, external_id, url, house_id,
                         price, price_per_m2, area, rooms,
                         floor_current, floor_total,
                         metro_station, metro_walk_time,
                         district, okrug, renovation,
                         is_active, days_in_exposition, total_views, unique_views,
                         publish_date, filter_id, updated_at
                  FROM active_ads
                  WHERE is_active = true
                  ORDER BY id
                """
                await import_table(pg, doc_id, "ActiveAds", sql, ACTIVE_ADS_COLS, args.dry_run)
            else:
                print(f"  Unknown table: {table} (supported: houses, active_ads)")
    finally:
        await pg.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc-id", help="Use existing Grist doc instead of creating new one")
    ap.add_argument("--tables", default="houses,active_ads",
                    help="Comma-separated: houses,active_ads (default: both)")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be imported, don't upload")
    args = ap.parse_args()
    import asyncio
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()

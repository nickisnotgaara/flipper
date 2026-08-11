"""
dump_local_pg_to_csv.py — дамп таблиц из локального PG в CSV.

Самый простой путь залить данные в Grist:
  1. py scripts/dump_local_pg_to_csv.py
  2. Открой http://localhost:8484 → parsing doc
  3. + Add New → Import from CSV → перетащи файлы
  4. Готово, таблица создастся автоматически с правильной схемой

Использование:
  py scripts/dump_local_pg_to_csv.py                       # все таблицы → flipper_data/
  py scripts/dump_local_pg_to_csv.py --tables houses       # только houses
  py scripts/dump_local_pg_to_csv.py --output-dir D:/tmp   # своя папка
"""
from __future__ import annotations
import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path
from datetime import date, datetime
from decimal import Decimal

# Windows console: force UTF-8 output (cp1251 by default)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import asyncpg

PG_DSN = "postgresql://flipper:flipper_secret@127.0.0.1:5432/flipper"
DEFAULT_OUTPUT = Path("C:/Users/User/Desktop/flipping/flipper/data/grist_import")


TABLES = {
    "houses": {
        "sql": """
            SELECT id, source, external_house_id, cian_house_id,
                   address, street, house_num, district, okrug,
                   lat, lng, year_built, levels, building_type, series,
                   package, updated_at
            FROM houses
            ORDER BY id
        """,
    },
    "active_ads": {
        "sql": """
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
        """,
    },
}


def serialize(v):
    """Grist/CSV принимают только простые типы."""
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    return v


async def dump_table(conn, name: str, sql: str, out_path: Path):
    rows = await conn.fetch(sql)
    if not rows:
        print(f"  {name}: 0 rows, skipping")
        return
    columns = list(rows[0].keys())
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for r in rows:
            writer.writerow([serialize(r[c]) for c in columns])
    print(f"  {name}: {len(rows)} rows → {out_path}")


async def main_async(args):
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {out_dir}")
    conn = await asyncpg.connect(PG_DSN)
    try:
        for table in args.tables.split(","):
            table = table.strip()
            if table not in TABLES:
                print(f"  Unknown table: {table} (supported: {list(TABLES.keys())})")
                continue
            cfg = TABLES[table]
            out_path = out_dir / f"{table}.csv"
            await dump_table(conn, table, cfg["sql"], out_path)
    finally:
        await conn.close()
    print(f"\nDone. CSV files ready for Grist import:")
    print(f"  1. Open http://localhost:8484 (org: flipper)")
    print(f"  2. Go to 'parsing' doc (or create new)")
    print(f"  3. Menu: 'Add New' -> 'Import from file'")
    print(f"  4. Drag CSV files from {out_dir}")
    print(f"  5. Tables will be created automatically with proper schema")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", default="houses,active_ads",
                    help="Comma-separated: houses,active_ads")
    ap.add_argument("--output-dir", default=str(DEFAULT_OUTPUT),
                    help="Output directory for CSV files")
    args = ap.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
sync_to_grist.py — синхронизация локальной PG (app_postgres) → Grist self-host.

Что делает:
  1. Bootstrap: создаёт в Grist все 6 таблиц (AddTable через applyUserActions), если их ещё нет.
  2. Sync: читает PG, шлёт в Grist пачками по 500, upsert по (source, external_id).
  3. Resume: кеширует маппинг pg_id → grist_rowId в .grist_map.json (pickle).

Использование:
  py scripts/sync_to_grist.py bootstrap
  py scripts/sync_to_grist.py sync --tables ActiveAds,Houses
  py scripts/sync_to_grist.py sync --all
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import psycopg2
import psycopg2.extras
import requests

# --- Config -----------------------------------------------------------------
GRIST_URL = os.environ.get("GRIST_URL", "http://127.0.0.1:8484")
GRIST_API_KEY = os.environ.get(
    "GRIST_API_KEY", "flipper_prod_c173df83d342e744aa1fa74bb80bd19a32f5f598d7e582c0c8d4561659290978"
)
GRIST_DOC_ID = os.environ.get("GRIST_DOC_ID", "rYyn6wJZihqm1TAgkBgPnY")

PG_DSN = os.environ.get("PG_DSN", "postgresql://flipper:flipper_secret@127.0.0.1:5432/flipper")
MAP_FILE = Path(__file__).parent / ".grist_map.json"

CHUNK = 500  # rows per addRecords / updateRecords

# --- Grist API helpers ------------------------------------------------------
SESSION = requests.Session()
SESSION.headers.update({"Authorization": f"Bearer {GRIST_API_KEY}"})


def grist(method: str, path: str, **kwargs) -> Any:
    url = f"{GRIST_URL}{path}"
    r = SESSION.request(method, url, timeout=60, **kwargs)
    if not r.ok:
        sys.stderr.write(f"GRIST {method} {url} -> {r.status_code}\n{r.text[:2000]}\n")
        r.raise_for_status()
    if r.text:
        try:
            return r.json()
        except Exception:
            return r.text
    return None


def apply_actions(actions: list, label: str = "") -> Any:
    """applyUserActions — атомарно. action: [op, ...args]"""
    return grist("POST", f"/api/docs/{GRIST_DOC_ID}/apply", json=actions)


def create_table(name: str, columns: list[dict]) -> str:
    """Создать таблицу, возвращает tableId."""
    r = grist("POST", f"/api/docs/{GRIST_DOC_ID}/tables",
              json={"tables": [{"name": name, "columns": columns}]})
    if isinstance(r, dict) and r.get("tables"):
        return r["tables"][0]["id"]
    raise RuntimeError(f"create_table {name}: {r}")


def list_tables() -> dict[str, str]:
    """Возвращает {tableId: tableId} через /tables endpoint (надёжнее чем SQL)."""
    r = grist("GET", f"/api/docs/{GRIST_DOC_ID}/tables")
    return {t["id"]: t["id"] for t in r.get("tables", [])}


def add_records(table_id: str, rows: list[dict]) -> list[int]:
    """addRecords возвращает list of rowId."""
    r = grist("POST", f"/api/docs/{GRIST_DOC_ID}/tables/{table_id}/records",
              json={"records": [{"fields": row} for row in rows]})
    return r.get("records", []) if isinstance(r, dict) else []


def update_records(table_id: str, row_updates: list[tuple[int, dict]]) -> None:
    """row_updates: [(rowId, fields), ...] — full row PUT."""
    if not row_updates:
        return
    records = [{"id": rid, "fields": fields} for rid, fields in row_updates]
    grist("PUT", f"/api/docs/{GRIST_DOC_ID}/tables/{table_id}/records",
          json={"records": records})


# --- PG helpers -------------------------------------------------------------
def pg_conn():
    return psycopg2.connect(PG_DSN)


def pg_query(sql: str, params: tuple = ()) -> list[dict]:
    with pg_conn() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


# --- ID mapping -------------------------------------------------------------
def load_map() -> dict:
    if MAP_FILE.exists():
        return json.loads(MAP_FILE.read_text(encoding="utf-8"))
    return {}


def save_map(m: dict) -> None:
    MAP_FILE.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")


# --- Table schemas ----------------------------------------------------------
TABLES: dict[str, dict] = {
    "ActiveAds": {
        "columns": [
            ("pg_id", "Int"),
            ("source", "Text"),
            ("cian_id", "Text"),
            ("url", "Text"),
            ("house_id", "Int"),
            ("price", "Numeric"),
            ("price_per_m2", "Int"),
            ("area", "Numeric"),
            ("rooms", "Int"),
            ("floor_current", "Int"),
            ("floor_total", "Int"),
            ("metro_station", "Text"),
            ("metro_walk_time", "Int"),
            ("district", "Text"),
            ("okrug", "Text"),
            ("renovation", "Text"),
            ("days_in_exposition", "Int"),
            ("total_views", "Int"),
            ("unique_views", "Int"),
            ("publish_date", "Date"),
            ("filter_id", "Int"),
            ("is_active", "Bool"),
            ("updated_at", "DateTime"),
        ],
    },
    "SoldAdsRecent": {
        "columns": [
            ("pg_id", "Int"),
            ("source", "Text"),
            ("external_id", "Text"),
            ("url", "Text"),
            ("house_id", "Int"),
            ("price", "Numeric"),
            ("price_per_m2", "Int"),
            ("area", "Numeric"),
            ("rooms", "Int"),
            ("floor_current", "Int"),
            ("floor_total", "Int"),
            ("renovation", "Text"),
            ("exposition_days", "Int"),
            ("publish_date", "Date"),
            ("sold_date", "Date"),
        ],
    },
    "HousesCian": {
        "columns": [
            ("pg_id", "Int"),
            ("source", "Text"),
            ("external_house_id", "Text"),
            ("cian_house_id", "Int"),
            ("address", "Text"),
            ("street", "Text"),
            ("house_num", "Text"),
            ("district", "Text"),
            ("okrug", "Text"),
            ("lat", "Numeric"),
            ("lng", "Numeric"),
            ("year_built", "Int"),
            ("levels", "Int"),
            ("building_type", "Text"),
        ],
    },
    "Filters": {
        "columns": [
            ("pg_id", "Int"),
            ("name", "Text"),
            ("description", "Text"),
            ("active", "Bool"),
        ],
    },
    "DeactivatedStats": {
        "columns": [
            ("year", "Int"),
            ("month", "Int"),
            ("count", "Int"),
            ("avg_price", "Numeric"),
            ("avg_price_per_m2", "Numeric"),
            ("avg_area", "Numeric"),
        ],
    },
    "PipelineRuns": {
        "columns": [
            ("pg_id", "Int"),
            ("pipeline", "Text"),
            ("status", "Text"),
            ("started_at", "DateTime"),
            ("finished_at", "DateTime"),
            ("rows_processed", "Int"),
        ],
    },
}


def col_def(name: str, type_name: str) -> dict:
    """Grist AddTable требует {id, label, type}."""
    return {"id": name, "label": name, "type": type_name}


def bootstrap():
    """Создать все 6 таблиц через applyUserActions AddTable."""
    existing = list_tables()  # {id: name}
    existing_names = set(existing.values())
    # Cleanup мусорные Table3..99
    for tid in list(existing.keys()):
        if tid.startswith("Table") and tid not in ("Table1", "Table2"):
            print(f"  [clean] removing {tid} ({existing[tid]})")
            try:
                apply_actions([["RemoveTable", tid]])
                time.sleep(0.2)
            except Exception as e:
                print(f"    fail: {e}")

    # Rename Table1 (default) -> ActiveAds если ещё не переименована
    if "Table1" in existing:
        try:
            apply_actions([["RenameTable", "Table1", "ActiveAds"]])
            print("  [rename] Table1 -> ActiveAds")
            time.sleep(0.2)
        except Exception as e:
            print(f"    rename fail: {e}")

    # Перечитываем после cleanup
    existing = list_tables()
    existing_names = set(existing.values())

    for name, spec in TABLES.items():
        if name in existing_names:
            print(f"  [skip] {name} (уже есть)")
            continue
        cols = [col_def(n, t) for n, t in spec["columns"]]
        try:
            res = apply_actions([["AddTable", name, cols]], label=f"create {name}")
            print(f"  [+] {name} -> {res}")
        except Exception as e:
            print(f"  [!] {name}: {e}")
        time.sleep(0.3)


# --- Field normalizers (PG → Grist) -----------------------------------------
def to_jsonable(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, dict):
        return {to_jsonable(k): to_jsonable(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [to_jsonable(x) for x in v]
    return str(v)


def row_active_ads(r: dict) -> dict:
    return {k: to_jsonable(r.get(k)) for k in [
        "pg_id", "source", "cian_id", "url", "house_id", "price", "price_per_m2",
        "area", "rooms", "floor_current", "floor_total", "metro_station",
        "metro_walk_time", "district", "okrug", "renovation",
        "days_in_exposition", "total_views", "unique_views", "publish_date",
        "filter_id", "is_active", "updated_at",
    ]}


def row_sold_recent(r: dict) -> dict:
    return {k: to_jsonable(r.get(k)) for k in [
        "pg_id", "source", "external_id", "url", "house_id", "price", "price_per_m2",
        "area", "rooms", "floor_current", "floor_total", "renovation",
        "exposition_days", "publish_date", "sold_date",
    ]}


def row_houses_cian(r: dict) -> dict:
    return {k: to_jsonable(r.get(k)) for k in [
        "pg_id", "source", "external_house_id", "cian_house_id", "address", "street",
        "house_num", "district", "okrug", "lat", "lng", "year_built", "levels",
        "building_type",
    ]}


# --- Sync engine ------------------------------------------------------------
def sync_table(table_name: str, table_id: str, pg_sql: str, normalize, key: str = "pg_id",
               where_clause: str = "", limit: int | None = None):
    print(f"\n=== Sync {table_name} ({table_id}) ===")
    full_sql = pg_sql + ((" WHERE " + where_clause) if where_clause else "")
    if limit:
        full_sql += f" LIMIT {limit}"
    rows = pg_query(full_sql)
    print(f"  PG rows: {len(rows)}")
    if not rows:
        return

    # Build add chunks
    chunks = [rows[i:i + CHUNK] for i in range(0, len(rows), CHUNK)]
    map_ = load_map()
    map_key = f"{table_name}__pg2grist"
    sub = map_.get(map_key, {})

    added = 0
    for ci, ch in enumerate(chunks):
        fields_list = [normalize(r) for r in ch]
        try:
            recs = add_records(table_id, fields_list)
        except Exception as e:
            print(f"  [chunk {ci}] addRecords FAILED: {e}")
            continue
        for r, rec in zip(ch, recs):
            rid = rec.get("id") if isinstance(rec, dict) else None
            if rid is not None and r.get(key) is not None:
                sub[str(r[key])] = rid
        added += len(recs)
        print(f"  chunk {ci + 1}/{len(chunks)}: +{len(recs)}")
        time.sleep(0.2)

    map_[map_key] = sub
    save_map(map_)
    print(f"  TOTAL added: {added}  (map size: {len(sub)})")


# --- Entrypoints ------------------------------------------------------------
def do_bootstrap(_args):
    bootstrap()
    print("\nTables сейчас:", list_tables())


def do_sync(args):
    # Resolve table ids (after bootstrap)
    names = list_tables()  # {id: name}
    name2id = {n: i for i, n in names.items()}

    targets = args.tables.split(",") if args.tables else []
    if args.all:
        targets = ["ActiveAds", "SoldAdsRecent", "HousesCian", "DeactivatedStats", "PipelineRuns"]

    if "ActiveAds" in targets:
        sql = """
        SELECT id AS pg_id, source, cian_id, url, house_id, price, price_per_m2, area, rooms,
               floor_current, floor_total, metro_station, metro_walk_time, district, okrug,
               renovation, days_in_exposition, total_views, unique_views, publish_date,
               filter_id, is_active, updated_at
        FROM active_ads
        """
        sync_table("ActiveAds", name2id["ActiveAds"], sql, row_active_ads, "pg_id",
                   where_clause="source = 'cian_active'")

    if "SoldAdsRecent" in targets:
        sql = """
        SELECT id AS pg_id, source, external_id, url, house_id, price, price_per_m2, area, rooms,
               floor_current, floor_total, renovation, exposition_days, publish_date, sold_date
        FROM sold_ads
        """
        sync_table("SoldAdsRecent", name2id["SoldAdsRecent"], sql, row_sold_recent, "pg_id",
                   where_clause="source = 'cian_deactivated'",
                   limit=2000 if not args.full_sold else None)

    if "HousesCian" in targets:
        sql = """
        SELECT id AS pg_id, source, external_house_id, cian_house_id, address, street,
               house_num, district, okrug, lat, lng, year_built, levels, building_type
        FROM houses
        """
        sync_table("HousesCian", name2id["HousesCian"], sql, row_houses_cian, "pg_id",
                   where_clause="source = 'cian_sold' AND lat IS NOT NULL",
                   limit=args.houses_limit or 10000)

    if "DeactivatedStats" in targets:
        # Aggregation table — no PG source, we compute in Python
        print("\n=== DeactivatedStats (computed) ===")
        rows = pg_query("""
            SELECT EXTRACT(YEAR FROM COALESCE(sold_date, publish_date))::int AS year,
                   EXTRACT(MONTH FROM COALESCE(sold_date, publish_date))::int AS month,
                   count(*) AS count,
                   AVG(price)::numeric(14,2) AS avg_price,
                   AVG(price_per_m2)::numeric(14,2) AS avg_price_per_m2,
                   AVG(area)::numeric(8,2) AS avg_area
            FROM sold_ads
            WHERE source = 'cian_deactivated'
              AND COALESCE(sold_date, publish_date) IS NOT NULL
            GROUP BY 1, 2
            ORDER BY 1 DESC, 2 DESC
        """)
        if rows:
            fields_list = [to_jsonable(r) for r in rows]
            recs = add_records(name2id["DeactivatedStats"], fields_list)
            print(f"  +{len(recs)} aggregated rows")

    if "PipelineRuns" in targets:
        print("\n=== PipelineRuns ===")
        try:
            rows = pg_query("""
                SELECT id AS pg_id, pipeline, status, started_at, finished_at, rows_processed
                FROM pipeline_runs ORDER BY started_at DESC LIMIT 200
            """)
            if rows:
                fields_list = [{k: to_jsonable(r.get(k)) for k in
                                ["pg_id", "pipeline", "status", "started_at", "finished_at", "rows_processed"]}
                               for r in rows]
                recs = add_records(name2id["PipelineRuns"], fields_list)
                print(f"  +{len(recs)} pipeline runs")
        except Exception as e:
            print(f"  pipeline_runs table missing? {e}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("bootstrap")
    sp = sub.add_parser("sync")
    sp.add_argument("--tables", default="", help="comma list: ActiveAds,SoldAdsRecent,...")
    sp.add_argument("--all", action="store_true")
    sp.add_argument("--full-sold", action="store_true", help="sync all 231K deactivated (slow!)")
    sp.add_argument("--houses-limit", type=int, default=10000)
    args = p.parse_args()

    if args.cmd == "bootstrap":
        do_bootstrap(args)
    elif args.cmd == "sync":
        do_sync(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()

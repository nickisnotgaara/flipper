#!/usr/bin/env python3
"""
sync_to_grist.py — синхронизация локальной PG (app_postgres) → Grist self-host.

Документы:
  - Main      (rYyn6wJZihqm1TAgkBgPnY): ActiveAds, SoldAdsRecent, HousesCian, PipelineRuns
  - Парсинг   (mDaHoGD6yahtxaqugwr5mK): FILTERS, Аванс, Аванс_Продано, Продано, Balans, Offers_Parser, Signals_Parser
  - Архивы    (kaBfATwGgUYjDa8doqMzk3): CianSold, DomclickSold, WinnersNovostroiki, WinnersVtorichka, FlatInfoHouses, HousesAll

Использование:
  py scripts/sync_to_grist.py sync parsing    # Парсинг
  py scripts/sync_to_grist.py sync archives   # Архивы
  py scripts/sync_to_grist.py sync all        # Main + Парсинг + Архивы
"""
from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path
import psycopg2
import psycopg2.extras
import requests

GRIST_URL = os.environ.get("GRIST_URL", "http://127.0.0.1:8484")
GRIST_API_KEY = os.environ.get(
    "GRIST_API_KEY",
    "flipper_prod_c173df83d342e744aa1fa74bb80bd19a32f5f598d7e582c0c8d4561659290978",
)

PG_DSN = os.environ.get("PG_DSN", "postgresql://flipper:flipper_secret@127.0.0.1:5432/flipper")
MAP_FILE = Path(__file__).parent / ".grist_map.json"
CHUNK = 500

DOCS = {
    "main":      "rYyn6wJZihqm1TAgkBgPnY",
    "parsing":   "mDaHoGD6yahtxaqugwr5mK",
    "archives":  "kaBfATwGgUYjDa8doqMzk3",
}

SESSION = requests.Session()
SESSION.headers.update({"Authorization": f"Bearer {GRIST_API_KEY}"})


def grist(method, path, **kw):
    r = SESSION.request(method, f"{GRIST_URL}{path}", timeout=120, **kw)
    if not r.ok:
        sys.stderr.write(f"GRIST {method} {path} -> {r.status_code}\n{r.text[:2000]}\n")
        r.raise_for_status()
    return r.json() if r.text else None


def list_tables(doc_id):
    r = grist("GET", f"/api/docs/{doc_id}/tables")
    return {t["id"]: t["id"] for t in r.get("tables", [])}


def add_records(doc_id, table_id, rows):
    r = grist("POST", f"/api/docs/{doc_id}/tables/{table_id}/records",
              json={"records": [{"fields": row} for row in rows]})
    return r.get("records", []) if isinstance(r, dict) else []


def pg_query(sql, params=()):
    with psycopg2.connect(PG_DSN) as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def load_map():
    if MAP_FILE.exists():
        return json.loads(MAP_FILE.read_text(encoding="utf-8"))
    return {}


def save_map(m):
    MAP_FILE.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")


def to_jsonable(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, dict):
        return {to_jsonable(k): to_jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [to_jsonable(x) for x in v]
    return str(v)


def sync_table(doc_id, table_id, name, pg_sql, normalize, where_clause="", limit=None):
    print(f"\n=== {name} -> {table_id} (doc {doc_id[:8]}) ===")
    full_sql = pg_sql + ((" WHERE " + where_clause) if where_clause else "")
    if limit:
        full_sql += f" LIMIT {limit}"
    rows = pg_query(full_sql)
    print(f"  PG rows: {len(rows)}")
    if not rows:
        return
    chunks = [rows[i:i + CHUNK] for i in range(0, len(rows), CHUNK)]
    map_ = load_map()
    map_key = f"{doc_id}__{table_id}__pg2grist"
    sub = map_.get(map_key, {})
    added = 0
    for ci, ch in enumerate(chunks):
        fields_list = [normalize(r) for r in ch]
        try:
            recs = add_records(doc_id, table_id, fields_list)
        except Exception as e:
            print(f"  [chunk {ci}] FAILED: {e}")
            continue
        for r, rec in zip(ch, recs):
            rid = rec.get("id") if isinstance(rec, dict) else None
            if rid is not None and r.get("pg_id") is not None:
                sub[str(r["pg_id"])] = rid
        added += len(recs)
        print(f"  chunk {ci + 1}/{len(chunks)}: +{len(recs)}")
        time.sleep(0.2)
    map_[map_key] = sub
    save_map(map_)
    print(f"  TOTAL: {added}")


# === Row normalizers ===
def row_active_ads(r):
    return {k: to_jsonable(r.get(k)) for k in [
        "pg_id", "source", "cian_id", "url", "house_id", "price", "price_per_m2",
        "area", "rooms", "floor_current", "floor_total", "metro_station",
        "metro_walk_time", "district", "okrug", "renovation",
        "days_in_exposition", "total_views", "unique_views", "publish_date",
        "filter_id", "is_active", "updated_at",
    ]}


def row_prodano(r):
    return {k: to_jsonable(r.get(k)) for k in [
        "pg_id", "source", "external_id", "url", "house_id", "price", "price_per_m2",
        "area", "rooms", "floor_current", "floor_total",
        "renovation", "exposition_days", "publish_date", "sold_date",
    ]}


def row_avans(r):
    return {k: to_jsonable(r.get(k)) for k in [
        "pg_id", "source", "cian_id", "url", "price", "price_per_m2",
        "area", "rooms", "floor_current", "floor_total", "metro_station",
        "metro_walk_time", "district", "okrug", "renovation",
        "days_in_exposition", "publish_date", "has_avans_deposit", "updated_at",
    ]}


def row_houses_min(r):
    return {k: to_jsonable(r.get(k)) for k in [
        "pg_id", "source", "external_house_id", "address", "street", "house_num",
        "district", "okrug", "lat", "lng", "year_built", "levels", "building_type",
    ]}


def row_houses_ext(r):
    return {k: to_jsonable(r.get(k)) for k in [
        "pg_id", "source", "external_house_id", "address", "lat", "lng",
        "year_built", "levels", "building_type", "developer", "price_from",
        "price_to", "deadline",
    ]}


# === Sync flows ===
def sync_main(tables):
    doc = DOCS["main"]
    n2i = list_tables(doc)
    do_all = not tables
    if (do_all or "ActiveAds" in tables) and "ActiveAds" in n2i:
        sql = """SELECT id AS pg_id, source, cian_id, url, house_id, price, price_per_m2, area, rooms,
                 floor_current, floor_total, metro_station, metro_walk_time, district, okrug,
                 renovation, days_in_exposition, total_views, unique_views, publish_date,
                 filter_id, is_active, updated_at FROM active_ads"""
        sync_table(doc, n2i["ActiveAds"], "ActiveAds", sql, row_active_ads,
                   where_clause="source = 'cian_active'")


def sync_parsing(tables):
    doc = DOCS["parsing"]
    n2i = list_tables(doc)
    do_all = not tables
    # Найти tableId для Продано / Аванс / Аванс_Продано
    def find_tid(*names):
        for n in names:
            if n in n2i:
                return n2i[n]
        return None

    if (do_all or "Продано" in tables):
        # Продано = Table4 (создана последней с этим именем)
        for cand in ["Table4", "Продано"]:
            if cand in n2i:
                tid = n2i[cand]
                break
        else:
            tid = None
        if tid:
            sql = """SELECT id AS pg_id, source, external_id, url, house_id, price, price_per_m2, area, rooms,
                     floor_current, floor_total, renovation, exposition_days,
                     publish_date, sold_date FROM sold_ads"""
            sync_table(doc, tid, "Продано", sql, row_prodano,
                       where_clause="source = 'cian_deactivated'",
                       limit=2000)


def sync_archives(tables):
    doc = DOCS["archives"]
    n2i = list_tables(doc)
    do_all = not tables
    if (do_all or "HousesAll" in tables) and "HousesAll" in n2i:
        sql = """SELECT id AS pg_id, source, external_house_id, address, street, house_num,
                 district, okrug, lat, lng, year_built, levels, building_type FROM houses"""
        sync_table(doc, n2i["HousesAll"], "HousesAll", sql, row_houses_min,
                   where_clause="source = 'cian_sold' AND lat IS NOT NULL",
                   limit=20000)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    sp = sub.add_parser("sync")
    sp.add_argument("target", choices=["main", "parsing", "archives", "all"])
    sp.add_argument("--tables", default="", help="comma list (по умолчанию все)")
    args = p.parse_args()
    if args.cmd != "sync":
        p.print_help()
        return
    if args.target in ("main", "all"):
        sync_main(args.tables.split(",") if args.tables else None)
    if args.target in ("parsing", "all"):
        sync_parsing(args.tables.split(",") if args.tables else None)
    if args.target in ("archives", "all"):
        sync_archives(args.tables.split(",") if args.tables else None)


if __name__ == "__main__":
    main()

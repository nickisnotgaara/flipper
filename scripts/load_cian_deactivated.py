"""Load deactivated Cian offers from secondary/cian/data/result.jsonl into sold_ads.

Idempotent: ON CONFLICT (source, external_id) DO UPDATE.
Links to flatinfo.houses via parent.cian.cian_house_id == flatinfo.house_id.

Uses raw asyncpg executemany to avoid SQLAlchemy's prepared-statement type cache
issue (price column is BigInteger; the first row of a batch can fit in int4 but
later rows may be 6+ billion rubles and overflow int32 encoding).
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper",
)

import asyncio
from datetime import date

import asyncpg

from sqlalchemy import select, func

from packages.flipper_db import get_session_factory, House, SoldAd

SRC = "cian_deactivated"
JSONL = Path(r"C:\Users\User\Desktop\flipping\secondary\cian\data\result.jsonl")

# asyncpg DSN (raw)
PG_DSN = "postgresql://flipper:flipper_secret@127.0.0.1:5432/flipper"

# Columns inserted, in order matching the row tuples below.
COLUMNS = [
    "source", "external_id", "url", "house_id", "cian_house_id",
    "price", "price_per_m2", "area", "rooms",
    "floor_current", "floor_total", "renovation",
    "exposition_days", "publish_date", "sold_date", "raw_data",
]

INSERT_SQL = f"""
INSERT INTO sold_ads ({", ".join(COLUMNS)})
VALUES ($1, $2, $3, $4, $5::bigint, $6::bigint, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
ON CONFLICT (source, external_id) DO UPDATE SET
  url = EXCLUDED.url,
  house_id = EXCLUDED.house_id,
  cian_house_id = EXCLUDED.cian_house_id,
  price = EXCLUDED.price,
  price_per_m2 = EXCLUDED.price_per_m2,
  area = EXCLUDED.area,
  rooms = EXCLUDED.rooms,
  floor_current = EXCLUDED.floor_current,
  floor_total = EXCLUDED.floor_total,
  renovation = EXCLUDED.renovation,
  exposition_days = EXCLUDED.exposition_days,
  publish_date = EXCLUDED.publish_date,
  sold_date = EXCLUDED.sold_date,
  raw_data = EXCLUDED.raw_data
"""


def parse_russian_date(s: str | None) -> date | None:
    if not s:
        return None
    months = {
        "янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "мая": 5,
        "июн": 6, "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
    }
    parts = s.strip().split()
    if len(parts) != 3:
        return None
    try:
        d = int(parts[0])
        m = months.get(parts[1][:3].lower())
        y = int(parts[2])
        if not m:
            return None
        return date(y, m, d)
    except Exception:
        return None


def parse_int_money(s: str | None) -> int | None:
    """Parse '30,0 млн ₽' or '6,3 млрд ₽' or '482 930 ₽/м²' into int rubles."""
    if not s:
        return None
    try:
        s_norm = s.replace("\xa0", " ").strip()
        is_mln = "млн" in s_norm
        is_mrd = "млрд" in s_norm or "мрд" in s_norm
        is_per_sqm = "м²" in s_norm or "/м" in s_norm  # price per m²
        s_norm = s_norm.replace("млрд", "").replace("млн", "").replace("₽", "").replace("м²", "").replace("/м", "")
        s_norm = re.sub(r"[^\d,.]", "", s_norm)
        s_norm = s_norm.replace(",", ".")
        if not s_norm.strip():
            return None
        val = float(s_norm.strip())
        if is_mrd:
            val = val * 1_000_000_000
        elif is_mln:
            val = val * 1_000_000
        elif is_per_sqm:
            pass  # already in rubles per m²
        elif val < 10000:  # bare number heuristic
            val = val * 1_000_000
        return int(val)
    except Exception:
        return None


def safe_int32(v: int | None) -> int | None:
    """Clamp to int32 range to keep asyncpg happy on Integer columns."""
    if v is None:
        return None
    INT32_MAX = 2_147_483_647
    if v > INT32_MAX:
        return INT32_MAX
    if v < -INT32_MAX:
        return -INT32_MAX
    return v


def price_diff_key(diff: str | None) -> str | None:
    if not diff or diff == "noChange":
        return None
    if diff == "decrease":
        return "down"
    if diff == "increase":
        return "up"
    return diff


def split_address(addr: str | None) -> tuple[str | None, str | None, str | None]:
    if not addr:
        return None, None, None
    parts = [p.strip() for p in addr.split(",")]
    parts = [p for p in parts if p and p.lower() not in ("москва", "москва г.", "г. москва", "moscow")]
    if not parts:
        return addr, None, None
    if len(parts) == 1:
        return parts[0], None, None
    street = ", ".join(parts[:-1])
    house_num = parts[-1]
    return street, house_num, None


def build_record(cian_id: str, deact: dict, parent: dict, link_house_id: int | None) -> tuple:
    title_parsed = deact.get("title_parsed") or {}
    details = deact.get("details") or {}
    prices = deact.get("prices") or {}
    street, house_num, _district = split_address(details.get("address"))

    p_src = parent.get("source") or {}
    p_cian = parent.get("cian") or {}
    cian_house_id = p_cian.get("cian_house_id") or p_src.get("house_id")

    title = deact.get("title")
    price = parse_int_money(prices.get("price"))
    price_m2 = parse_int_money(prices.get("priceSqm"))
    area = title_parsed.get("total_area_sqm")
    rooms = title_parsed.get("rooms")
    floor_current = title_parsed.get("floor_current")
    floor_total = title_parsed.get("floor_total")

    features = details.get("features") or []
    feat_map = {}
    for f in features:
        if isinstance(f, dict):
            feat_map[f.get("title", "")] = f.get("value")
    renovation = feat_map.get("Ремонт") or feat_map.get("Отделка")
    build_year = None
    try:
        by = feat_map.get("Год постройки")
        if by:
            build_year = int(str(by).strip())
    except Exception:
        pass

    exposition = deact.get("exposition")
    days_in_exposition = None
    if exposition:
        m = re.match(r"(\d+)\s*дн", exposition)
        if m:
            try:
                days_in_exposition = int(m.group(1))
            except Exception:
                pass

    raw = {
        "deactivated": {
            "id": deact.get("id"),
            "title": title,
            "prices": prices,
            "exposition": exposition,
            "status": deact.get("status"),
            "dateStart": deact.get("dateStart"),
            "dateEnd": deact.get("dateEnd"),
            "title_parsed": title_parsed,
            "details": details,
        },
        "parent_house_id": p_src.get("house_id"),
        "parent_cian_house_id": p_cian.get("cian_house_id"),
        "build_year": build_year,
        "price_diff": price_diff_key(prices.get("priceDiff")),
        "metro": (details.get("metro") or {}),
        "address": details.get("address"),
        "street": street,
        "house_num": house_num,
    }

    return (
        SRC,
        cian_id,
        f"https://www.cian.ru/sale/flat/{cian_id}/",
        link_house_id,
        cian_house_id,
        price,
        safe_int32(price_m2),  # price_per_m2 column is Integer (int32)
        area,
        rooms,
        floor_current,
        floor_total,
        renovation,
        days_in_exposition,
        parse_russian_date(deact.get("dateStart")),
        parse_russian_date(deact.get("dateEnd")),
        json.dumps(raw, ensure_ascii=False),
    )


def _chunked(seq, size):
    buf = []
    for r in seq:
        buf.append(r)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


async def main(dry_run: bool = False, limit: int | None = None, batch_size: int = 500):
    t0 = time.time()
    inserted = 0
    skipped = 0
    seen_ids: set[str] = set()

    print("[1/3] Loading house_id map from flatinfo…")
    house_id_map: dict[int, int] = {}
    Session = get_session_factory()
    async with Session() as s:
        rows = (await s.execute(select(House.external_house_id, House.id))).all()
        for h, hid in rows:
            try:
                house_id_map[int(h)] = hid
            except Exception:
                pass
    print(f"  loaded {len(house_id_map)} external_house_id -> db id mappings")

    print(f"[2/3] Streaming {JSONL.name}…")
    raw = JSONL.read_bytes()
    chunks = re.split(rb"\}\r?\n\{", raw)
    total_chunks = len(chunks)
    print(f"  total parent records (raw): {total_chunks}")

    print("[3/3] Building records…")
    records = []
    parent_linked = 0
    n = 0
    bad = 0
    for i in range(total_chunks):
        if limit and len(records) >= limit:
            break
        if i == 0:
            obj_bytes = chunks[0] + b"}"
        elif i == total_chunks - 1:
            obj_bytes = b"{" + chunks[i]
        else:
            obj_bytes = b"{" + chunks[i] + b"}"
        try:
            parent = json.loads(obj_bytes)
        except Exception:
            bad += 1
            continue
        n += 1
        deact = parent.get("deactivated_offers") or []
        if not deact:
            continue
        cian_house_id = (parent.get("cian") or {}).get("cian_house_id") or (parent.get("source") or {}).get("house_id")
        link_house_id = house_id_map.get(cian_house_id) if cian_house_id else None
        if link_house_id:
            parent_linked += 1
        for d in deact:
            cid = str(d.get("id"))
            if not cid or cid in seen_ids:
                skipped += 1
                continue
            seen_ids.add(cid)
            records.append(build_record(cid, d, parent, link_house_id))
        if n % 5000 == 0:
            print(f"  ...parsed {n} parents, collected {len(records)} deacts")

    print(f"  parent records parsed: {n}, bad: {bad}")
    print(f"  prepared {len(records)} unique deactivated ads (skipped {skipped} duplicates)")
    print(f"  parent records with linkable house: {parent_linked}")

    if dry_run:
        print("[dry-run] aborting.")
        return

    # Use raw asyncpg connection - no prepared statement cache, avoids int4/int8 issue
    print(f"[4/4] Inserting via raw asyncpg in batches of {batch_size}…")
    conn = await asyncpg.connect(PG_DSN)
    try:
        for batch in _chunked(records, batch_size):
            await conn.executemany(INSERT_SQL, batch)
            inserted += len(batch)
            if inserted % 5000 == 0 or inserted == len(records):
                elapsed = time.time() - t0
                rate = inserted / elapsed if elapsed > 0 else 0
                pct = inserted / max(1, len(records)) * 100
                print(f"  inserted/updated {inserted}/{len(records)} ({pct:.1f}%) {rate:.0f}/s")
    finally:
        await conn.close()

    print("=" * 60)
    print(f"deactivated inserted/updated: {inserted}")
    print(f"elapsed: {time.time() - t0:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch-size", type=int, default=500)
    args = ap.parse_args()
    asyncio.run(main(dry_run=args.dry_run, limit=args.limit, batch_size=args.batch_size))

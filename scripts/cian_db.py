"""
cian_db — async PostgreSQL upserts for cian offers and houses.

Two idempotent operations, both safe to re-run:
    upsert_house(conn, offer) -> int house_id
    upsert_offer(conn, offer) -> int ad_id
    upsert_batch(conn, offers) -> {"houses": n, "ads": n}

The natural key for houses is (source='cian', external_house_id=str(cian_house_id))
which maps to the unique constraint uq_houses_source_external.

The natural key for ads is (source='cian_active', external_id=str(offer.cian_id))
which maps to uq_active_ads_source_external_id.

Both writes use ON CONFLICT ... DO UPDATE so the same HTML can be re-ingested
without duplicating rows or losing recent data. Updated fields are pulled from
the parser's normalized dataclass, NOT from raw_data (raw_data is preserved
as a side-channel for debugging).

The two-table approach is intentional:
  - `houses` is the canonical registry; we join active_ads.house_id to it.
  - `active_ads` is the offer-level data; one row per (source, cian_id).
  - `offers_parser` VIEW (created externally) aliases active_ads WHERE source='cian_active'.
  - `cian_houses` (legacy) is NOT touched by this module.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable, List, Optional, Sequence, Tuple

import asyncpg

from cian_parse import OfferRecord

log = logging.getLogger("cian_db")

# Keep these as module-level constants — the SQL is easier to read this way
# than as multi-line f-strings.
SQL_UPSERT_HOUSE = """
INSERT INTO houses (
    source, external_house_id,
    cian_house_id,
    address, street, house_num, district, okrug,
    lat, lng,
    year_built, levels, building_type, series, ceiling_height, package,
    raw_data, parsed_at, updated_at
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
    $11, $12, $13, $14, $15, $16, $17::json, NOW(), NOW()
)
ON CONFLICT (source, external_house_id) DO UPDATE SET
    cian_house_id = COALESCE(EXCLUDED.cian_house_id, houses.cian_house_id),
    address       = COALESCE(EXCLUDED.address, houses.address),
    street        = COALESCE(EXCLUDED.street, houses.street),
    house_num     = COALESCE(EXCLUDED.house_num, houses.house_num),
    district      = COALESCE(EXCLUDED.district, houses.district),
    okrug         = COALESCE(EXCLUDED.okrug, houses.okrug),
    lat           = COALESCE(EXCLUDED.lat, houses.lat),
    lng           = COALESCE(EXCLUDED.lng, houses.lng),
    year_built    = COALESCE(EXCLUDED.year_built, houses.year_built),
    levels        = COALESCE(EXCLUDED.levels, houses.levels),
    building_type = COALESCE(EXCLUDED.building_type, houses.building_type),
    series        = COALESCE(EXCLUDED.series, houses.series),
    ceiling_height= COALESCE(EXCLUDED.ceiling_height, houses.ceiling_height),
    package       = COALESCE(EXCLUDED.package, houses.package),
    raw_data      = COALESCE(EXCLUDED.raw_data, houses.raw_data),
    updated_at    = NOW()
RETURNING id
"""

SQL_UPSERT_AD = """
INSERT INTO active_ads (
    source, external_id, url, house_id, cian_house_id,
    price, price_per_m2, area, rooms, floor_current, floor_total,
    metro_station, metro_walk_time, district, okrug, renovation,
    is_active, publish_date, lat, lng,
    raw_data, parsed_at, updated_at
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
    $12, $13, $14, $15, $16, $17, $18, $19, $20,
    $21::json, NOW(), NOW()
)
ON CONFLICT (source, external_id) DO UPDATE SET
    url             = EXCLUDED.url,
    house_id        = COALESCE(EXCLUDED.house_id, active_ads.house_id),
    cian_house_id   = COALESCE(EXCLUDED.cian_house_id, active_ads.cian_house_id),
    price           = COALESCE(EXCLUDED.price, active_ads.price),
    price_per_m2    = COALESCE(EXCLUDED.price_per_m2, active_ads.price_per_m2),
    area            = COALESCE(EXCLUDED.area, active_ads.area),
    rooms           = COALESCE(EXCLUDED.rooms, active_ads.rooms),
    floor_current   = COALESCE(EXCLUDED.floor_current, active_ads.floor_current),
    floor_total     = COALESCE(EXCLUDED.floor_total, active_ads.floor_total),
    metro_station   = COALESCE(EXCLUDED.metro_station, active_ads.metro_station),
    metro_walk_time = COALESCE(EXCLUDED.metro_walk_time, active_ads.metro_walk_time),
    district        = COALESCE(EXCLUDED.district, active_ads.district),
    okrug           = COALESCE(EXCLUDED.okrug, active_ads.okrug),
    renovation      = COALESCE(EXCLUDED.renovation, active_ads.renovation),
    is_active       = EXCLUDED.is_active,
    publish_date    = COALESCE(EXCLUDED.publish_date, active_ads.publish_date),
    lat             = COALESCE(EXCLUDED.lat, active_ads.lat),
    lng             = COALESCE(EXCLUDED.lng, active_ads.lng),
    raw_data        = COALESCE(EXCLUDED.raw_data, active_ads.raw_data),
    updated_at      = NOW()
RETURNING id
"""

# Bounded batch sizes for executemany — asyncpg's prepared-statement parameter
# limit and BigInteger overflow at ~12k parameters across many rows. We keep
# each row at 19 params for ads and 17 for houses; 100 rows = 1700/1900 < 2000.
BATCH_SIZE = 100


def _house_row(o: OfferRecord) -> tuple:
    """Build the parameter tuple for SQL_UPSERT_HOUSE from an OfferRecord.
    The order MUST match the INSERT column list in SQL_UPSERT_HOUSE.
    """
    b = o.building
    raw = json.dumps(o.raw, ensure_ascii=False) if o.raw else None
    return (
        "cian",                          # source
        str(o.cian_house_id) if o.cian_house_id else None,  # external_house_id
        o.cian_house_id,                 # cian_house_id
        o.full_address,                  # address
        o.street_name,                   # street
        o.house_num,                     # house_num
        o.district,                      # district
        o.okrug,                         # okrug
        o.lat,                           # lat
        o.lng,                           # lng
        b.year_built if b else None,     # year_built
        b.levels if b else None,         # levels
        b.material if b else None,       # building_type
        b.series if b else None,         # series
        b.ceiling_height if b else None, # ceiling_height
        b.parking if b else None,        # package (cian "parking" -> package)
        raw,                             # raw_data
    )


def _ad_row(o: OfferRecord, house_id: Optional[int]) -> tuple:
    """Build the parameter tuple for SQL_UPSERT_AD.
    The order MUST match the INSERT column list in SQL_UPSERT_AD.
    """
    raw = json.dumps(o.raw, ensure_ascii=False) if o.raw else None
    return (
        "cian_active",                   # source
        str(o.cian_id),                  # external_id
        o.url,                           # url
        house_id,                        # house_id
        o.cian_house_id,                 # cian_house_id
        o.price,                         # price
        o.price_per_m2,                  # price_per_m2
        o.area,                          # area
        o.rooms,                         # rooms
        o.floor_current,                 # floor_current
        o.floor_total,                   # floor_total
        o.metro_station,                 # metro_station
        o.metro_walk_time,               # metro_walk_time
        o.district,                      # district
        o.okrug,                         # okrug
        o.renovation,                    # renovation
        bool(o.is_active),               # is_active
        o.publish_date,                  # publish_date
        o.lat,                           # lat (from offer.geo.coordinates)
        o.lng,                           # lng (from offer.geo.coordinates)
        raw,                             # raw_data
    )


async def upsert_house(conn: asyncpg.Connection, o: OfferRecord) -> Optional[int]:
    """Upsert a single house. Returns the houses.id (new or existing), or None
    if the offer has no cian_house_id (we can't make a unique key without it).
    """
    if o.cian_house_id is None:
        return None
    row = await conn.fetchrow(SQL_UPSERT_HOUSE, *_house_row(o))
    return int(row["id"]) if row else None


async def upsert_offer(conn: asyncpg.Connection, o: OfferRecord) -> Tuple[Optional[int], Optional[int]]:
    """Upsert a single offer: first its house (if any), then the ad.
    Returns (house_id, ad_id). Either may be None if the offer lacks
    the required keys.
    """
    house_id = await upsert_house(conn, o)
    row = await conn.fetchrow(SQL_UPSERT_AD, *_ad_row(o, house_id))
    ad_id = int(row["id"]) if row else None
    return house_id, ad_id


async def upsert_batch(conn: asyncpg.Connection, offers: Sequence[OfferRecord]) -> dict:
    """Idempotent bulk upsert. Returns counters.
    Houses are upserted first, then ads — within a single transaction so
    the FK from active_ads.house_id is always valid.
    """
    house_rows: list = []
    ad_rows: list = []
    for o in offers:
        if o.cian_id <= 0:
            continue
        if o.cian_house_id is not None:
            house_rows.append(_house_row(o))
        # ad row references the house by house_id; we need that id, so we
        # upsert houses via fetch() first, collect ids, then batch the ads.
        ad_rows.append((o, _ad_row(o, None)))  # house_id filled below

    n_houses = 0
    n_ads = 0
    if not house_rows and not ad_rows:
        return {"houses": 0, "ads": 0}

    async with conn.transaction():
        # 1) upsert houses one at a time, collecting ids keyed by external id.
        #    executemany doesn't return values, so we use a small loop here.
        if house_rows:
            for r in house_rows:
                rid = await conn.fetchval(SQL_UPSERT_HOUSE, *r)
                if rid is not None:
                    n_houses += 1

        # 2) batch the ads. We intentionally do NOT auto-fill ad.house_id
        #    with the cian row's primary key here. The user wants ad.house_id
        #    to point at the FLATINFO house (the canonical registry for the
        #    map), so linking is delegated to scripts/link_ads_to_houses.py
        #    which uses (cian_house_id == flatinfo.cian_real_house_id) first
        #    and falls back to haversine on (lat, lng). Leaving ad.house_id
        #    NULL here keeps that contract clean and idempotent — re-running
        #    the linker fills in only what was previously NULL.
        if ad_rows:
            tuples = [_ad_row(o, None) for o, _ in ad_rows]
            for i in range(0, len(tuples), BATCH_SIZE):
                chunk = tuples[i:i + BATCH_SIZE]
                # executemany doesn't RETURNING, so we just count.
                await conn.executemany(SQL_UPSERT_AD, chunk)
                n_ads += len(chunk)

    return {"houses": n_houses, "ads": n_ads}


# ---------- connection helper ----------

DEFAULT_DSN = "postgresql://flipper:flipper_secret@127.0.0.1:5432/flipper"


async def connect(dsn: Optional[str] = None) -> asyncpg.Connection:
    """Open one connection. The caller is responsible for closing it
    (or wrap in `async with`)."""
    return await asyncpg.connect(dsn or DEFAULT_DSN)


async def fetch_existing_house_ids(conn: asyncpg.Connection, cian_house_ids: Iterable[int]) -> set:
    """Return the subset of cian_house_ids that already have a houses row
    with source='cian'. Used by callers that want to skip already-known houses."""
    ids = list(set(int(x) for x in cian_house_ids))
    if not ids:
        return set()
    rows = await conn.fetch(
        "SELECT external_house_id FROM houses WHERE source='cian' AND external_house_id = ANY($1::text[])",
        [str(x) for x in ids],
    )
    return {str(r["external_house_id"]) for r in rows}

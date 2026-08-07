"""scripts/load_flatinfo_houses - загрузить дома из flatinfo/result.json в houses.

Источник: secondary/flatinfo/result.json (~21 МБ, 28 385 домов, все с lat/lng).
Идентификация: source='flatinfo', external_house_id=str(flatinfo.house_id).
cian_house_id = flatinfo.house_id (id-пространство совпадает с cian source.house_id).

Идемпотентен: ON CONFLICT (source, external_house_id) DO UPDATE.
"""
import argparse
import asyncio
import json
import logging
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from packages.flipper_db import init_engine, get_session_factory

logger = logging.getLogger("load_flatinfo_houses")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def _to_int(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _to_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _clean(s):
    return s.strip() if isinstance(s, str) else None


def build_house_row(r: dict) -> dict:
    """Превратить запись flatinfo в dict для INSERT/UPDATE в houses."""
    street = _clean(r.get("street"))
    house_num = _clean(r.get("house_num"))
    # Человеко-адрес — как будет отображаться в UI
    address = f"Москва, {street}, {house_num}" if street and house_num else (
        f"Москва, {street}" if street else None
    )
    return {
        "source": "flatinfo",
        "external_house_id": str(r["house_id"]),
        "cian_house_id": r["house_id"],
        "address": address,
        "street": street,
        "house_num": house_num,
        "district": None,  # в flatinfo нет
        "okrug": None,
        "lat": _to_float(r.get("lat")),
        "lng": _to_float(r.get("lng")),
        "year_built": _to_int(r.get("year")),
        "levels": _to_int(r.get("levels")),
        "building_type": _clean(r.get("type")),
        "series": _clean(r.get("ser_name")) or _clean(r.get("subser_name")),
        "raw_data": r,
    }


async def load(dry_run: bool = False, limit: int | None = None):
    flatinfo_path = Path(r"C:\Users\User\Desktop\flipping\secondary\flatinfo\result.json")
    logger.info(f"Loading flatinfo from {flatinfo_path} ...")
    with open(flatinfo_path, "rb") as f:
        data = json.load(f)
    logger.info(f"Records in file: {len(data):,}")
    if limit:
        data = data[:limit]
        logger.info(f"Limiting to first {limit} (dry run)")

    rows = [build_house_row(r) for r in data]
    # Moscow bbox filter
    before = len(rows)
    rows = [
        r for r in rows
        if r["lat"] is not None
        and r["lng"] is not None
        and 55.142 <= r["lat"] <= 56.022
        and 36.803 <= r["lng"] <= 37.968
    ]
    logger.info(f"After Moscow bbox filter: {len(rows):,} (dropped {before - len(rows)})")

    if dry_run:
        logger.info("DRY RUN — not writing to DB")
        for r in rows[:3]:
            print(json.dumps(r, ensure_ascii=False, indent=2, default=str)[:500])
        return

    init_engine("postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper")
    sf = get_session_factory()

    start = time.time()
    batch_size = 500
    n_upserted = 0

    async with sf() as s:
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            values_sql = ",".join(
                f"(:s_{k}, :e_{k}, :c_{k}, :a_{k}, :st_{k}, :h_{k}, :la_{k}, :ln_{k}, "
                f":y_{k}, :lv_{k}, :bt_{k}, :se_{k}, CAST(:r_{k} AS JSONB))"
                for k in range(len(batch))
            )
            params = {}
            for k, r in enumerate(batch):
                params.update({
                    f"s_{k}": r["source"],
                    f"e_{k}": r["external_house_id"],
                    f"c_{k}": r["cian_house_id"],
                    f"a_{k}": r["address"],
                    f"st_{k}": r["street"],
                    f"h_{k}": r["house_num"],
                    f"la_{k}": r["lat"],
                    f"ln_{k}": r["lng"],
                    f"y_{k}": r["year_built"],
                    f"lv_{k}": r["levels"],
                    f"bt_{k}": r["building_type"],
                    f"se_{k}": r["series"],
                    f"r_{k}": json.dumps(r["raw_data"], ensure_ascii=False),
                })

            sql = f"""
                INSERT INTO houses (
                    source, external_house_id, cian_house_id, address, street, house_num,
                    lat, lng, year_built, levels, building_type, series, raw_data
                )
                VALUES {values_sql}
                ON CONFLICT (source, external_house_id) DO UPDATE SET
                    cian_house_id = EXCLUDED.cian_house_id,
                    address = EXCLUDED.address,
                    street = EXCLUDED.street,
                    house_num = EXCLUDED.house_num,
                    lat = EXCLUDED.lat,
                    lng = EXCLUDED.lng,
                    year_built = EXCLUDED.year_built,
                    levels = EXCLUDED.levels,
                    building_type = EXCLUDED.building_type,
                    series = EXCLUDED.series,
                    raw_data = EXCLUDED.raw_data,
                    updated_at = CURRENT_TIMESTAMP;
            """
            result = await s.execute(text(sql), params)
            await s.commit()
            n_upserted += result.rowcount

            if (i // batch_size) % 10 == 0:
                elapsed = time.time() - start
                pct = 100 * (i + len(batch)) / len(rows)
                eta = (elapsed / (i + len(batch))) * (len(rows) - i - len(batch))
                logger.info(
                    f"  [{i + len(batch):,}/{len(rows):,}] {pct:.1f}% "
                    f"({n_upserted:,} rows affected) elapsed={elapsed:.1f}s eta={eta:.0f}s"
                )

    elapsed = time.time() - start
    logger.info(f"=== DONE in {elapsed:.1f}s ===")
    logger.info(f"  upserted: {n_upserted:,} rows (ON CONFLICT updates counted)")

    # Финальная статистика
    async with sf() as s:
        row = (await s.execute(text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE source='flatinfo') AS flatinfo,
                COUNT(*) FILTER (WHERE lat IS NOT NULL) AS with_coords
            FROM houses;
        """))).first()
        logger.info(f"  houses.total = {row.total:,}")
        logger.info(f"  houses.flatinfo = {row.flatinfo:,}")
        logger.info(f"  houses.with_coords = {row.with_coords:,}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()
    asyncio.run(load(dry_run=args.dry_run, limit=args.limit))


if __name__ == "__main__":
    main()

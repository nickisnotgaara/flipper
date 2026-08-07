"""scripts/update_flatinfo_coords - залить lat/lng из secondary/flatinfo/result.json в БД.

NB: flatinfo_houses/result.json содержит поля lat и lng, но штатный импортер
(house_pages_result.json) их не подхватывает. Этот скрипт берёт result.json
и обновляет lat/lng у существующих домов (по house_id == external_house_id).

Идемпотентен: только обновляет NULL.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from packages.flipper_db import init_engine
from packages.flipper_db.base import get_session_factory

logger = logging.getLogger("update_flatinfo_coords")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


async def run(
    result_json: Path,
    db_url: str,
    update_existing: bool = False,
    dry_run: bool = False,
) -> int:
    if not result_json.is_file():
        logger.error("Файл не найден: %s", result_json)
        return 2

    init_engine(db_url)
    sf = get_session_factory()

    # Загрузить файл
    logger.info("Загружаю %s (%.1f МБ)...", result_json, result_json.stat().st_size / 1024 / 1024)
    with result_json.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        logger.error("Ожидался JSON-массив, получен %s", type(data).__name__)
        return 2
    logger.info("Загружено %d домов", len(data))

    # Соберём (house_id, lat, lng) для записей с координатами
    updates: list[tuple[int, float, float]] = []
    no_coords = 0
    for rec in data:
        if not isinstance(rec, dict):
            continue
        hid = rec.get("house_id")
        lat = rec.get("lat")
        lng = rec.get("lng")
        if hid is None or lat is None or lng is None:
            no_coords += 1
            continue
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except (TypeError, ValueError):
            no_coords += 1
            continue
        updates.append((int(hid), lat_f, lng_f))

    logger.info("С координатами: %d, без: %d", len(updates), no_coords)

    if dry_run:
        logger.info("[DRY-RUN] Не делаю UPDATE")
        return 0

    # Обновляем порциями
    BATCH = 1000
    n_updated = 0
    n_skipped = 0
    async with sf() as s:
        for i in range(0, len(updates), BATCH):
            batch = updates[i:i + BATCH]
            # VALUES (hid, lat, lng) — сопоставляем по external_house_id
            values_clause = ",".join(f"({hid}, {lat}, {lng})" for hid, lat, lng in batch)
            if update_existing:
                sql = f"""
                    UPDATE houses AS h
                    SET lat = v.lat, lng = v.lng, updated_at = NOW()
                    FROM (VALUES {values_clause}) AS v(hid, lat, lng)
                    WHERE h.source = 'flatinfo_houses'
                      AND h.external_house_id = v.hid::TEXT;
                """
            else:
                sql = f"""
                    UPDATE houses AS h
                    SET lat = v.lat, lng = v.lng, updated_at = NOW()
                    FROM (VALUES {values_clause}) AS v(hid, lat, lng)
                    WHERE h.source = 'flatinfo_houses'
                      AND h.external_house_id = v.hid::TEXT
                      AND h.lat IS NULL;
                """
            result = await s.execute(text(sql))
            n_updated += result.rowcount
            await s.commit()
        # Статистика
        row = (await s.execute(text("""
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (WHERE lat IS NOT NULL) AS with_coords
            FROM houses WHERE source='flatinfo_houses';
        """))).first()
        n_skipped = row[0] - row[1]

    logger.info("=" * 60)
    logger.info("ОБНОВЛЕНО: %d (пропущено уже было: %d)", n_updated, n_skipped)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Залить lat/lng из flatinfo/result.json в БД.")
    p.add_argument(
        "--result",
        type=Path,
        default=ROOT.parent / "secondary" / "flatinfo" / "result.json",
        help="Путь к result.json (default: ../secondary/flatinfo/result.json)",
    )
    p.add_argument(
        "--db", default="postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper",
    )
    p.add_argument(
        "--update-existing", action="store_true",
        help="Обновлять ВСЕ дома, не только с NULL lat/lng",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Только посчитать, без записи в БД",
    )
    args = p.parse_args()
    return asyncio.run(run(args.result, args.db, args.update_existing, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())

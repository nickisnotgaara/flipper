"""scripts/migrate_sqlite_to_postgres - перенос данных из SQLite (secondary_migrated.db)
в новую PostgreSQL-схему (houses, active_ads, sold_ads).

NB: при импорте даты/числа из SQLite приходят как строки (TEXT) — конвертируем
в Python-типы (date, int, float, bool) перед передачей в SQLAlchemy.

Зачем: secondary_migrated.db (2.8 GB) — это результат предыдущей миграции
secondary/* в SQLite (от 2026-07-25). Чтобы быстро получить данные в PostgreSQL,
переливаем SQLite → PostgreSQL напрямую.

Это НЕ замена полной миграции из secondary/:
    scripts/migrate_secondary_files_to_postgres.py
которая читает оригинальные JSONL/JSON файлы из secondary/.
Здесь мы идём по короткому пути: SQLite уже содержит всё, что есть в JSONL.

Идемпотентен: upsert по (source, external_*_id). Повторный запуск безопасен.

Использование:
    # Перелить secondary_migrated.db (default) в PostgreSQL (default)
    py scripts/migrate_sqlite_to_postgres.py

    # С параметрами
    py scripts/migrate_sqlite_to_postgres.py \\
        --sqlite data/secondary_migrated.db \\
        --db "postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper" \\
        --batch-size 1000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from packages.flipper_db import (
    ActiveAd,
    FlipperRepository,
    House,
    SoldAd,
    init_db,
    init_engine,
)

logger = logging.getLogger("migrate_sqlite_to_pg")


# ===================================================================== schema

# Словарь: имя таблицы в SQLite → список колонок для чтения.
# Эти колонки = поля вторичных парсеров, плюс служебные (id, parsed_at и т.д.).
#
# NB: SQLAlchemy-модели не читаем напрямую из dict (не загружаем в ORM),
# а читаем из SQLite как dict и затем вручную конвертируем в ActiveAd/House/SoldAd
# — это безопасно по типам и проще по обработке ошибок.

_HOUSE_COLS = [
    "source", "external_house_id", "cian_house_id", "address",
    "street", "house_num", "district", "okrug", "lat", "lng",
    "year_built", "levels", "building_type", "series", "ceiling_height",
    "package", "raw_data", "parsed_at", "updated_at",
]

_ACTIVE_COLS = [
    "source", "cian_id", "url", "house_id", "cian_house_id",
    "price", "price_per_m2", "area", "rooms", "floor_current", "floor_total",
    "metro_station", "metro_walk_time", "district", "okrug", "renovation",
    "is_active", "days_in_exposition", "total_views", "unique_views",
    "publish_date", "price_history", "raw_data", "parsed_at", "updated_at",
    "filter_id",
]

_SOLD_COLS = [
    "source", "external_id", "url", "house_id", "cian_house_id",
    "price", "price_per_m2", "area", "rooms", "floor_current", "floor_total",
    "renovation", "exposition_days", "publish_date", "sold_date",
    "raw_data", "parsed_at",
]


# ===================================================================== helpers


def _coerce_value(v: Any) -> Any:
    """SQLite возвращает всё в виде str/int/None/bytes.

    Преобразуем в Python-типы, подходящие для SQLAlchemy:
      - bytes → str (json/jsonb хранится как str)
      - None → None
    """
    if v is None:
        return None
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8")
        except UnicodeDecodeError:
            return v.decode("utf-8", errors="replace")
    return v


def _parse_date(v: Any) -> date | None:
    """SQLite хранит DATE как 'YYYY-MM-DD' (TEXT). Парсим в date."""
    if v is None:
        return None
    if isinstance(v, date):
        return v
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    if not s:
        return None
    # ISO date (YYYY-MM-DD)
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _parse_int(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if v.is_integer() else None
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(s)
    except (ValueError, TypeError):
        try:
            return int(float(s))
        except (ValueError, TypeError):
            return None


def _parse_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _parse_bool(v: Any) -> bool | None:
    """SQLite хранит bool как 0/1 (INTEGER)."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "yes", "y"):
        return True
    if s in ("0", "false", "f", "no", "n", ""):
        return False
    return None


def _row_to_dict(cursor, row) -> dict[str, Any]:
    return {col[0]: _coerce_value(val) for col, val in zip(cursor.description, row)}


def _iter_sqlite(sqlite_path: Path, table: str, batch: int) -> Iterable[list[dict]]:
    """Итератор по SQLite-таблице, yield'ит батчи dict'ов."""
    conn = sqlite3.connect(str(sqlite_path))
    # row_factory = sqlite3.Row, но мы читаем через cursor для скорости
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table};")
        total = cursor.fetchone()[0]
        logger.info("SQLite %s: %d строк", table, total)

        offset = 0
        while offset < total:
            cursor.execute(f"SELECT * FROM {table} LIMIT ? OFFSET ?;", (batch, offset))
            rows = cursor.fetchall()
            if not rows:
                break
            batch_dicts = [_row_to_dict(cursor, r) for r in rows]
            yield batch_dicts
            offset += batch
    finally:
        cursor.close()
        conn.close()


# ===================================================================== conversion


def _parse_json_if_str(v: Any) -> Any:
    """Если v — строка, пытаемся распарсить как JSON. Иначе вернуть как есть."""
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, (bytes, bytearray)):
        try:
            v = v.decode("utf-8")
        except Exception:
            return None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except (ValueError, TypeError):
            # Если не JSON, вернуть как строку (для raw_data иногда строка не-JSON)
            return v
    return v


def _to_house(rec: dict[str, Any]) -> House | None:
    """dict из SQLite → House. None если source/external_house_id пустые."""
    src = rec.get("source")
    eid = rec.get("external_house_id")
    if not src or eid is None:
        return None

    return House(
        source=str(src),
        external_house_id=str(eid),
        cian_house_id=_parse_int(rec.get("cian_house_id")),
        address=rec.get("address"),
        street=rec.get("street"),
        house_num=rec.get("house_num"),
        district=rec.get("district"),
        okrug=rec.get("okrug"),
        lat=_parse_float(rec.get("lat")),
        lng=_parse_float(rec.get("lng")),
        year_built=_parse_int(rec.get("year_built")),
        levels=_parse_int(rec.get("levels")),
        building_type=rec.get("building_type"),
        series=rec.get("series"),
        ceiling_height=_parse_float(rec.get("ceiling_height")),
        package=rec.get("package"),
        raw_data=_parse_json_if_str(rec.get("raw_data")),
    )


def _to_active(rec: dict[str, Any]) -> ActiveAd | None:
    src = rec.get("source")
    cid = rec.get("cian_id")
    if not src or not cid:
        return None
    is_act = rec.get("is_active")
    if is_act is None:
        is_act = True
    return ActiveAd(
        source=str(src),
        cian_id=str(cid),
        url=rec.get("url"),
        house_id=_parse_int(rec.get("house_id")),
        cian_house_id=_parse_int(rec.get("cian_house_id")),
        price=_parse_int(rec.get("price")),
        price_per_m2=_parse_int(rec.get("price_per_m2")),
        area=_parse_float(rec.get("area")),
        rooms=_parse_int(rec.get("rooms")),
        floor_current=_parse_int(rec.get("floor_current")),
        floor_total=_parse_int(rec.get("floor_total")),
        metro_station=rec.get("metro_station"),
        metro_walk_time=_parse_int(rec.get("metro_walk_time")),
        district=rec.get("district"),
        okrug=rec.get("okrug"),
        renovation=rec.get("renovation"),
        is_active=_parse_bool(is_act) if not isinstance(is_act, bool) else is_act,
        days_in_exposition=_parse_int(rec.get("days_in_exposition")),
        total_views=_parse_int(rec.get("total_views")),
        unique_views=_parse_int(rec.get("unique_views")),
        publish_date=_parse_date(rec.get("publish_date")),
        filter_id=_parse_int(rec.get("filter_id")),
        price_history=_parse_json_if_str(rec.get("price_history")),
        raw_data=_parse_json_if_str(rec.get("raw_data")),
    )


def _to_sold(rec: dict[str, Any]) -> SoldAd | None:
    src = rec.get("source")
    eid = rec.get("external_id")
    if not src or eid is None:
        return None
    return SoldAd(
        source=str(src),
        external_id=str(eid),
        url=rec.get("url"),
        house_id=_parse_int(rec.get("house_id")),
        cian_house_id=_parse_int(rec.get("cian_house_id")),
        price=_parse_int(rec.get("price")),
        price_per_m2=_parse_int(rec.get("price_per_m2")),
        area=_parse_float(rec.get("area")),
        rooms=_parse_int(rec.get("rooms")),
        floor_current=_parse_int(rec.get("floor_current")),
        floor_total=_parse_int(rec.get("floor_total")),
        renovation=rec.get("renovation"),
        exposition_days=_parse_int(rec.get("exposition_days")),
        publish_date=_parse_date(rec.get("publish_date")),
        sold_date=_parse_date(rec.get("sold_date")),
        raw_data=_parse_json_if_str(rec.get("raw_data")),
    )


# ===================================================================== main


async def run(
    sqlite_path: Path,
    db_url: str,
    batch_size: int = 500,
    dry_run: bool = False,
) -> int:
    if not sqlite_path.is_file():
        logger.error("SQLite не найден: %s", sqlite_path)
        return 2

    logger.info("=" * 60)
    logger.info("SQLite → PostgreSQL миграция")
    logger.info("=" * 60)
    logger.info("SQLite:  %s (%.1f MB)", sqlite_path, sqlite_path.stat().st_size / 1024 / 1024)
    logger.info("DB URL:  %s", db_url.split("@")[-1])
    logger.info("Batch:   %d", batch_size)
    logger.info("Dry run: %s", dry_run)

    if dry_run:
        # Просто посчитаем, без миграции
        conn = sqlite3.connect(str(sqlite_path))
        try:
            for t in ("houses", "active_ads", "sold_ads"):
                n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                logger.info("[DRY-RUN] %s: %d строк будет перенесено", t, n)
        finally:
            conn.close()
        return 0

    # init engine + создать таблицы (если их нет)
    init_engine(db_url)
    await init_db(db_url)
    repo = FlipperRepository()

    # houses
    logger.info("=" * 60)
    logger.info("=== houses ===")
    total_h = 0
    n_batches = 0
    for batch in _iter_sqlite(sqlite_path, "houses", batch_size):
        objs = [_to_house(r) for r in batch]
        objs = [o for o in objs if o is not None]
        n = await repo.upsert_houses_batch(objs)
        total_h += n
        n_batches += 1
        if n_batches % 10 == 0:
            logger.info("houses: %d батчей, %d записей (running)", n_batches, total_h)
    logger.info("houses: итого %d записей", total_h)

    # active_ads
    logger.info("=" * 60)
    logger.info("=== active_ads ===")
    total_a = 0
    n_batches = 0
    for batch in _iter_sqlite(sqlite_path, "active_ads", batch_size):
        objs = [_to_active(r) for r in batch]
        objs = [o for o in objs if o is not None]
        n = await repo.upsert_active_ads_batch(objs)
        total_a += n
        n_batches += 1
        if n_batches % 5 == 0:
            logger.info("active_ads: %d батчей, %d записей (running)", n_batches, total_a)
    logger.info("active_ads: итого %d записей", total_a)

    # sold_ads
    logger.info("=" * 60)
    logger.info("=== sold_ads ===")
    total_s = 0
    n_batches = 0
    for batch in _iter_sqlite(sqlite_path, "sold_ads", batch_size):
        objs = [_to_sold(r) for r in batch]
        objs = [o for o in objs if o is not None]
        n = await repo.upsert_sold_offers_batch(objs)
        total_s += n
        n_batches += 1
        if n_batches % 20 == 0:
            logger.info("sold_ads: %d батчей, %d записей (running)", n_batches, total_s)
    logger.info("sold_ads: итого %d записей", total_s)

    logger.info("=" * 60)
    logger.info(
        "МИГРАЦИЯ ЗАВЕРШЕНА: houses=%d active_ads=%d sold_ads=%d",
        total_h, total_a, total_s,
    )
    logger.info("=" * 60)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Перенос данных из secondary_migrated.db (SQLite) в PostgreSQL."
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=ROOT / "data" / "secondary_migrated.db",
        help="Путь к SQLite (default: data/secondary_migrated.db)",
    )
    parser.add_argument(
        "--db",
        default=os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper",
        ),
        help="DATABASE_URL (default: $DATABASE_URL или локальный flipper)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=500,
        help="Сколько строк SQLite за раз (default: 500)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Только показать, сколько строк в SQLite (без записи)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Подробный вывод (DEBUG)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    return asyncio.run(run(args.sqlite, args.db, args.batch_size, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())

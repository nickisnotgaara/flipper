"""scripts.migrate_cian_active_db - однократный перелив данных cian_active
из старого parser_cian.db (SQLite) в новую PostgreSQL-схему.

Источник: data/parser_cian.db (или другое расположение через --source)
    - cian_active_ads  (3,454 rows): URL + parsed_data (JSON) + is_parsed
    - cian_sold_ads    (2 rows):    URL + parsed_data (JSON) + publish_date
    - cian_filters     (6 rows):    URL + meta (JSON) — НЕ переносим, это URLs из Sheets

Назначение:    flipper_db (PostgreSQL/SQLite, cross-dialect)
    - cian_active_ads → active_ads (source='cian_active')
    - cian_sold_ads   → sold_ads   (source='cian_active')

Идемпотентен: повторный запуск не плодит дубликаты (upsert).

Использование:
    py -m scripts.migrate_cian_active_db \\
        --source "sqlite:///C:/path/parser_cian.db" \\
        --db "postgresql+asyncpg://flipper:secret@app_postgres:5432/flipper"
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
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from packages.flipper_db import (
    ActiveAd,
    FlipperRepository,
    SoldAd,
    init_db,
    init_engine,
)
from packages.flipper_db.enums import Source

logger = logging.getLogger("migrate_cian_active")

BATCH_SIZE = 1000
SOURCE_CIAN_ACTIVE = Source.CIAN_ACTIVE.value  # "cian_active"


# ================================================================== parsers

def _parse_json(raw: Any) -> dict[str, Any]:
    """JSON-строка или уже dict → dict. Пустое → {}."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _parse_date(s: Any) -> Optional[date]:
    """ISO-строка или date → date. None на ошибке."""
    if not s:
        return None
    if isinstance(s, date):
        return s
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


def _parse_dt(s: Any) -> Optional[datetime]:
    """ISO-строка или datetime → naive datetime (UTC). None на ошибке."""
    if not s:
        return None
    if isinstance(s, datetime):
        return s
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        # Конвертируем в naive (UTC) для совместимости с TIMESTAMP без tz
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except (ValueError, TypeError):
        return None


# ================================================================== record mapping

def _is_valid_cian_id(value: Any) -> bool:
    """`cian_id` валиден если это непустая строка, не равная 'null' и не None."""
    if value is None:
        return False
    s = str(value).strip()
    if not s or s.lower() in ("null", "none", "nan"):
        return False
    return True


def _active_ad_from_old_row(row: tuple, cols: list[str]) -> Optional[ActiveAd]:
    """Маппинг строки cian_active_ads (старая схема) → ActiveAd (новая).

    parsed_data: JSON со всеми полями объявления.
    Поля вытаскиваются из parsed_data, а не из колонок.
    """
    rec = dict(zip(cols, row))
    url = rec.get("url")
    if not url:
        return None
    parsed = _parse_json(rec.get("parsed_data"))
    if not parsed:
        return None

    # cian_id: из URL или из parsed_data.
    # Если в parsed_data cian_id = "null" (строка, от бага парсера),
    # fallback на URL: https://www.cian.ru/sale/flat/12345/
    cian_id = parsed.get("cian_id")
    if not _is_valid_cian_id(cian_id):
        import re
        m = re.search(r"/flat/(\d+)/?", url)
        if m:
            cian_id = m.group(1)
    if not _is_valid_cian_id(cian_id):
        return None

    # cian_house_id: если есть в parsed_data (поле house_id от API)
    cian_house_id = parsed.get("house_id") or parsed.get("cian_house_id")
    if cian_house_id is not None:
        try:
            cian_house_id = int(cian_house_id)
        except (TypeError, ValueError):
            cian_house_id = None

    # is_active из parsed_data
    is_active_raw = parsed.get("is_active")
    if is_active_raw is None:
        is_active = True
    else:
        is_active = bool(is_active_raw)

    # floor_info — dict с current/all
    floor_info = parsed.get("floor_info") or {}
    if not isinstance(floor_info, dict):
        floor_info = {}

    return ActiveAd(
        source=SOURCE_CIAN_ACTIVE,
        external_id=str(cian_id),
        url=url,
        house_id=None,  # FK на houses — будет проставлен отдельным шагом
        cian_house_id=cian_house_id,
        price=parsed.get("price"),
        price_per_m2=parsed.get("price_per_m2"),
        area=parsed.get("area"),
        rooms=parsed.get("rooms"),
        floor_current=floor_info.get("current"),
        floor_total=floor_info.get("all"),
        metro_station=(parsed.get("address") or {}).get("metro_station") if isinstance(parsed.get("address"), dict) else parsed.get("metro_station"),
        metro_walk_time=parsed.get("metro_walk_time"),
        district=(parsed.get("address") or {}).get("district") if isinstance(parsed.get("address"), dict) else parsed.get("district"),
        okrug=(parsed.get("address") or {}).get("okrug") if isinstance(parsed.get("address"), dict) else parsed.get("okrug"),
        renovation=parsed.get("renovation"),
        is_active=is_active,
        days_in_exposition=parsed.get("days_in_exposition"),
        total_views=parsed.get("total_views"),
        unique_views=parsed.get("unique_views"),
        publish_date=_parse_date(parsed.get("publish_date")),
        filter_id=rec.get("filter_id"),
        price_history=parsed.get("price_history"),
        raw_data=parsed,
    )


def _sold_ad_from_old_row(row: tuple, cols: list[str]) -> Optional[SoldAd]:
    """Маппинг строки cian_sold_ads (старая схема) → SoldAd (новая)."""
    rec = dict(zip(cols, row))
    url = rec.get("url")
    if not url:
        return None
    parsed = _parse_json(rec.get("parsed_data"))
    if not parsed:
        return None

    cian_id = parsed.get("cian_id")
    if not _is_valid_cian_id(cian_id):
        import re
        m = re.search(r"/flat/(\d+)/?", url)
        if m:
            cian_id = m.group(1)
    if not _is_valid_cian_id(cian_id):
        return None

    cian_house_id = parsed.get("house_id") or parsed.get("cian_house_id")
    if cian_house_id is not None:
        try:
            cian_house_id = int(cian_house_id)
        except (TypeError, ValueError):
            cian_house_id = None

    floor_info = parsed.get("floor_info") or {}
    if not isinstance(floor_info, dict):
        floor_info = {}

    return SoldAd(
        source=SOURCE_CIAN_ACTIVE,
        external_id=str(cian_id),
        url=url,
        house_id=None,
        cian_house_id=cian_house_id,
        price=parsed.get("price"),
        price_per_m2=parsed.get("price_per_m2"),
        area=parsed.get("area"),
        rooms=parsed.get("rooms"),
        floor_current=floor_info.get("current"),
        floor_total=floor_info.get("all"),
        renovation=parsed.get("renovation"),
        exposition_days=parsed.get("days_in_exposition"),
        publish_date=_parse_date(parsed.get("publish_date")),
        sold_date=_parse_date(parsed.get("sold_at") or rec.get("sold_at")),
        raw_data=parsed,
    )


# ================================================================== main

def _read_old_db(source: str) -> tuple[list[ActiveAd], list[SoldAd]]:
    """Читает старую БД и возвращает списки ActiveAd / SoldAd."""
    # Если source не содержит :/// — считаем что это путь к файлу
    if ":///" not in source and "://" not in source:
        # Просто путь к SQLite файлу
        if not os.path.exists(source):
            raise FileNotFoundError(f"SQLite DB not found: {source}")
        con = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    else:
        con = sqlite3.connect(source)

    active_ads: list[ActiveAd] = []
    sold_ads: list[SoldAd] = []

    try:
        # active_ads
        cur = con.execute("SELECT * FROM cian_active_ads")
        cols = [c[0] for c in cur.description]
        for row in cur.fetchall():
            a = _active_ad_from_old_row(row, cols)
            if a is not None:
                active_ads.append(a)

        # sold_ads
        cur = con.execute("SELECT * FROM cian_sold_ads")
        cols = [c[0] for c in cur.description]
        for row in cur.fetchall():
            s = _sold_ad_from_old_row(row, cols)
            if s is not None:
                sold_ads.append(s)
    finally:
        con.close()

    return active_ads, sold_ads


async def _flush_active_ads(repo: FlipperRepository, buffer: list[ActiveAd]) -> int:
    if not buffer:
        return 0
    return await repo.upsert_active_ads_batch(buffer)


async def _flush_sold_ads(repo: FlipperRepository, buffer: list[SoldAd]) -> int:
    if not buffer:
        return 0
    return await repo.upsert_sold_offers_batch(buffer)


async def _ensure_filter_id_column() -> None:
    """Добавляет колонку filter_id в active_ads, если её ещё нет.

    SQLite/PostgreSQL — `create_all` не делает миграции, поэтому добавляем
    вручную. Идемпотентно: повторный запуск не падает.
    """
    from packages.flipper_db.base import get_engine
    from sqlalchemy import text

    engine = get_engine()
    async with engine.begin() as conn:
        dialect = engine.dialect.name
        if dialect == "sqlite":
            # SQLite не поддерживает IF NOT EXISTS для колонок,
            # поэтому пробуем ALTER и игнорируем ошибку «duplicate column».
            try:
                await conn.execute(
                    text("ALTER TABLE active_ads ADD COLUMN filter_id INTEGER")
                )
            except Exception as e:
                msg = str(e).lower()
                if "duplicate" in msg or "already exists" in msg:
                    return
                raise
        else:  # postgresql
            await conn.execute(
                text("ALTER TABLE active_ads ADD COLUMN IF NOT EXISTS filter_id INTEGER")
            )
        # Индекс — отдельная команда
        try:
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS idx_active_ads_filter_id ON active_ads (filter_id)")
            )
        except Exception as e:
            logger.debug("idx_active_ads_filter_id already exists: %s", e)


async def run(source: str, db_url: str, dry_run: bool = False) -> int:
    """Перелив cian_active из старой БД в новую.

    Args:
        source: путь к parser_cian.db или URL SQLite.
        db_url: URL новой БД (PostgreSQL или SQLite).
        dry_run: только посчитать, без записи.
    """
    if not dry_run:
        init_engine(db_url)
        await init_db(db_url)
        await _ensure_filter_id_column()
    repo = FlipperRepository() if not dry_run else None

    logger.info("Читаем cian_active из %s ...", source)
    active_ads, sold_ads = _read_old_db(source)
    logger.info("Прочитано: active_ads=%d, sold_ads=%d", len(active_ads), len(sold_ads))

    if dry_run:
        logger.info("[DRY-RUN] active_ads=%d, sold_ads=%d", len(active_ads), len(sold_ads))
        return 0

    # Batched import
    total_active = 0
    total_sold = 0

    buf_a: list[ActiveAd] = []
    for a in active_ads:
        buf_a.append(a)
        if len(buf_a) >= BATCH_SIZE:
            total_active += await _flush_active_ads(repo, buf_a)
            buf_a = []
    if buf_a:
        total_active += await _flush_active_ads(repo, buf_a)

    buf_s: list[SoldAd] = []
    for s in sold_ads:
        buf_s.append(s)
        if len(buf_s) >= BATCH_SIZE:
            total_sold += await _flush_sold_ads(repo, buf_s)
            buf_s = []
    if buf_s:
        total_sold += await _flush_sold_ads(repo, buf_s)

    logger.info("МИГРАЦИЯ OK: active_ads=%d, sold_ads=%d", total_active, total_sold)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Перелив cian_active из parser_cian.db в новую PostgreSQL-схему."
    )
    parser.add_argument(
        "--source",
        default=str(ROOT / "data" / "parser_cian.db"),
        help="Путь к parser_cian.db (SQLite) или URL",
    )
    parser.add_argument(
        "--db",
        default=os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://flipper:flipper_secret@app_postgres:5432/flipper",
        ),
        help="DATABASE_URL новой БД (default: $DATABASE_URL или локальный flipper)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только посчитать записи (без записи в БД)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Подробный вывод")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    return asyncio.run(run(args.source, args.db, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())

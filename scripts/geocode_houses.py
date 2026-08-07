"""scripts/geocode_houses - пакетное геокодирование домов без координат.

Берёт houses где lat IS NULL или lng IS NULL, геокодирует через Nominatim
(или Photon, если указан --provider photon) и пишет результат обратно в БД.

Идемпотентен: можно прервать и продолжить (обрабатывает только дома без координат).

Использование:
    # Базовый запуск: Nominatim, ~1 запрос/сек, ~154k домов
    py scripts/geocode_houses.py

    # Photon (мягкие лимиты)
    py scripts/geocode_houses.py --provider photon --rate 1.0

    # Тест на 100 домах
    py scripts/geocode_houses.py --limit 100

    # Dry-run (только посчитать)
    py scripts/geocode_houses.py --dry-run

    # Только конкретный source
    py scripts/geocode_houses.py --source winners_sold
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text
from packages.flipper_db import (
    Geocoder,
    GeocoderConfig,
    init_engine,
    moscow_viewbox,
)
from packages.flipper_db.models import House
from packages.flipper_db.base import get_session_factory

logger = logging.getLogger("geocode_houses")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def _build_address(rec) -> str | None:
    """Собрать адрес из полей House (если ещё не собран)."""
    if rec.address and rec.address.strip():
        return rec.address.strip()
    # Собрать из частей
    parts = []
    if rec.street:
        parts.append(rec.street)
    if rec.house_num:
        parts.append(rec.house_num)
    if rec.district:
        parts.append(rec.district)
    if rec.okrug:
        parts.append(rec.okrug)
    if parts:
        return "Москва, " + ", ".join(parts)
    return None


def _check_moscow_bbox(lat: float, lng: float) -> bool:
    """Проверить что точка внутри bbox Москвы (для отсева ошибок геокодера)."""
    return 55.142 <= lat <= 56.022 and 36.803 <= lng <= 37.968


async def run(
    db_url: str,
    provider: str = "nominatim",
    rate: float = 1.0,
    source_filter: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    update_within_bbox_only: bool = True,
    log_every: int = 100,
) -> int:
    init_engine(db_url)
    sf = get_session_factory()

    cfg = GeocoderConfig(
        provider=provider,
        rate_per_sec=rate,
        viewbox=moscow_viewbox(),
    )
    geocoder = Geocoder(cfg)

    async with sf() as s:
        # Подсчёт
        q = select(House).where(House.lat.is_(None))
        if source_filter:
            q = q.where(House.source == source_filter)
        if limit:
            q = q.limit(limit)
        rows = (await s.execute(q)).scalars().all()
        total = len(rows)
        print(f"Домов без координат: {total}")
        print(f"Провайдер: {provider}, rate: {rate}/sec")
        print(f"С учётом bbox Москвы: {update_within_bbox_only}")
        if dry_run:
            print(f"[DRY-RUN] Не делаю запросов")
            return 0

        # Stats
        n_processed = 0
        n_updated = 0
        n_outside_bbox = 0
        n_not_found = 0
        started = time.time()

        for rec in rows:
            address = _build_address(rec)
            if not address:
                n_not_found += 1
                continue

            result = await geocoder.geocode(address)
            n_processed += 1

            if not result:
                n_not_found += 1
            else:
                # Проверить bbox (отсеять ошибочные результаты)
                if update_within_bbox_only and not _check_moscow_bbox(result.lat, result.lng):
                    n_outside_bbox += 1
                    logger.debug(
                        "outside bbox: id=%s address='%s' -> lat=%s lng=%s",
                        rec.id, address, result.lat, result.lng,
                    )
                else:
                    rec.lat = result.lat
                    rec.lng = result.lng
                    n_updated += 1

            # Логируем прогресс
            if n_processed % log_every == 0:
                elapsed = time.time() - started
                rate_actual = n_processed / elapsed if elapsed > 0 else 0
                eta_sec = (total - n_processed) / rate_actual if rate_actual > 0 else 0
                eta_h = eta_sec / 3600
                stats = geocoder.stats
                logger.info(
                    "[%d/%d] updated=%d not_found=%d outside=%d api_ok=%.1f%% (%.2f req/s, ETA %.1fh)",
                    n_processed, total, n_updated, n_not_found, n_outside_bbox,
                    stats["success_rate"], rate_actual, eta_h,
                )

            # Commit каждые 500
            if n_processed % 500 == 0:
                await s.commit()

        await s.commit()

        elapsed = time.time() - started
        logger.info("=" * 60)
        logger.info("ГЕОКОДИРОВАНИЕ ЗАВЕРШЕНО")
        logger.info(f"  обработано: {n_processed}")
        logger.info(f"  обновлено: {n_updated}")
        logger.info(f"  не найдено: {n_not_found}")
        logger.info(f"  вне bbox (пропущено): {n_outside_bbox}")
        logger.info(f"  время: {elapsed/60:.1f} мин")
        logger.info(f"  api stats: {geocoder.stats}")
        logger.info("=" * 60)
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Пакетное геокодирование домов без координат."
    )
    parser.add_argument(
        "--db", default=os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://flipper:flipper_secret@127.0.0.1:5432/flipper",
        ),
        help="DATABASE_URL",
    )
    parser.add_argument(
        "--provider", choices=["nominatim", "photon"], default="nominatim",
        help="Провайдер геокодирования (default: nominatim)",
    )
    parser.add_argument(
        "--rate", type=float, default=1.0,
        help="Запросов в секунду (default: 1.0 — соответствует Nominatim policy)",
    )
    parser.add_argument(
        "--source", default=None,
        help="Только этот source (winners_sold | domclick_sold | flatinfo_houses)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Обработать только N домов (для теста)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Только посчитать, без запросов",
    )
    parser.add_argument(
        "--no-bbox-filter", action="store_true",
        help="Не фильтровать результаты по bbox Москвы (записывать все)",
    )
    parser.add_argument(
        "--log-every", type=int, default=100,
        help="Логировать прогресс каждые N домов (default: 100)",
    )
    args = parser.parse_args()

    return asyncio.run(run(
        args.db, args.provider, args.rate, args.source, args.limit,
        args.dry_run, not args.no_bbox_filter, args.log_every,
    ))


if __name__ == "__main__":
    sys.exit(main())

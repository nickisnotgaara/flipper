"""FlipperRepository — высокоуровневые upsert-операции.

Все методы идемпотентны: повторный вызов с теми же данными обновляет записи,
а не создаёт дубликаты. Используют PostgreSQL ON CONFLICT (source, ext_id) DO UPDATE.
"""

from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .base import _engine, get_session_factory, init_db, init_engine
from .models import ActiveAd, House, SoldAd

logger = logging.getLogger(__name__)


class FlipperRepository:
    """Обёртка над SQLAlchemy-сессиями. Один экземпляр на парсер."""

    def __init__(self, database_url: str | None = None) -> None:
        """Создаёт репозиторий.

        Параметр database_url принимается для согласованности API, но engine
        ДОЛЖЕН быть уже инициализирован через init_db() / init_engine()
        ДО создания репозитория. Если engine не инициализирован и database_url
        передан — инициализирует engine (для удобства вызова из тестов).

        В production: init_db(db_url) → FlipperRepository() — engine переиспользуется.
        В тестах: фикстура явно вызывает init_engine(url), потом init_db(), потом FlipperRepository().
        """
        if database_url is not None and _engine is None:
            init_engine(database_url)
        self._sf: async_sessionmaker[AsyncSession] = get_session_factory()

    async def init_db(self) -> None:
        """Создать таблицы если их нет."""
        await init_db()

    # ------------------------------------------------------------------ houses

    async def upsert_houses_batch(self, houses: Iterable[House]) -> int:
        """Batch upsert домов. Возвращает количество реально вставленных/обновлённых.

        ON CONFLICT (source, external_house_id) DO UPDATE SET
            address = EXCLUDED.address,
            ...
            updated_at = NOW()
        """
        rows = [self._house_to_row(h) for h in houses]
        if not rows:
            return 0
        async with self._sf() as session:
            stmt = pg_insert(House).values(rows)
            # Обновляем всё, кроме id/parsed_at/created_at
            # index_elements (а не constraint="...") — кросс-диалектно: и SQLite,
            # и PostgreSQL понимают (col1, col2).
            stmt = stmt.on_conflict_do_update(
                index_elements=["source", "external_house_id"],
                set_={
                    "cian_house_id": stmt.excluded.cian_house_id,
                    "address": stmt.excluded.address,
                    "street": stmt.excluded.street,
                    "house_num": stmt.excluded.house_num,
                    "district": stmt.excluded.district,
                    "okrug": stmt.excluded.okrug,
                    "lat": stmt.excluded.lat,
                    "lng": stmt.excluded.lng,
                    "year_built": stmt.excluded.year_built,
                    "levels": stmt.excluded.levels,
                    "building_type": stmt.excluded.building_type,
                    "series": stmt.excluded.series,
                    "ceiling_height": stmt.excluded.ceiling_height,
                    "package": stmt.excluded.package,
                    "raw_data": stmt.excluded.raw_data,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            await session.execute(stmt)
            await session.commit()
        logger.info("upsert_houses_batch: %d записей", len(rows))
        return len(rows)

    async def find_house_id(
        self,
        source: str,
        external_house_id: str,
    ) -> int | None:
        """Найти id дома по (source, external_house_id). None если не найден."""
        async with self._sf() as session:
            stmt = select(House.id).where(
                House.source == source,
                House.external_house_id == external_house_id,
            )
            row = (await session.execute(stmt)).first()
            return row[0] if row else None

    async def find_house_by_cian_id(self, cian_house_id: int) -> House | None:
        """Найти дом по cian_house_id (любой source — для будущей сшивки)."""
        async with self._sf() as session:
            stmt = select(House).where(House.cian_house_id == cian_house_id).limit(1)
            return (await session.execute(stmt)).scalars().first()

    # --------------------------------------------------------------- active_ads

    async def upsert_active_ads_batch(self, ads: Iterable[ActiveAd]) -> int:
        """Batch upsert активных объявлений. ON CONFLICT (source, external_id)."""
        rows = [self._active_to_row(a) for a in ads]
        if not rows:
            return 0
        async with self._sf() as session:
            stmt = pg_insert(ActiveAd).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["source", "external_id"],
                set_={
                    "url": stmt.excluded.url,
                    "house_id": stmt.excluded.house_id,
                    "cian_house_id": stmt.excluded.cian_house_id,
                    "price": stmt.excluded.price,
                    "price_per_m2": stmt.excluded.price_per_m2,
                    "area": stmt.excluded.area,
                    "rooms": stmt.excluded.rooms,
                    "floor_current": stmt.excluded.floor_current,
                    "floor_total": stmt.excluded.floor_total,
                    "metro_station": stmt.excluded.metro_station,
                    "metro_walk_time": stmt.excluded.metro_walk_time,
                    "district": stmt.excluded.district,
                    "okrug": stmt.excluded.okrug,
                    "renovation": stmt.excluded.renovation,
                    "is_active": stmt.excluded.is_active,
                    "days_in_exposition": stmt.excluded.days_in_exposition,
                    "total_views": stmt.excluded.total_views,
                    "unique_views": stmt.excluded.unique_views,
                    "publish_date": stmt.excluded.publish_date,
                    "filter_id": stmt.excluded.filter_id,
                    "price_history": stmt.excluded.price_history,
                    "raw_data": stmt.excluded.raw_data,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            await session.execute(stmt)
            await session.commit()
        logger.info("upsert_active_ads_batch: %d записей", len(rows))
        return len(rows)

    # ----------------------------------------------------------------- sold_ads

    async def upsert_sold_offers_batch(self, sold_ads: Iterable[SoldAd]) -> int:
        """Batch upsert снятых объявлений. ON CONFLICT (source, external_id)."""
        rows = [self._sold_to_row(s) for s in sold_ads]
        if not rows:
            return 0
        async with self._sf() as session:
            stmt = pg_insert(SoldAd).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["source", "external_id"],
                set_={
                    "url": stmt.excluded.url,
                    "house_id": stmt.excluded.house_id,
                    "cian_house_id": stmt.excluded.cian_house_id,
                    "price": stmt.excluded.price,
                    "price_per_m2": stmt.excluded.price_per_m2,
                    "area": stmt.excluded.area,
                    "rooms": stmt.excluded.rooms,
                    "floor_current": stmt.excluded.floor_current,
                    "floor_total": stmt.excluded.floor_total,
                    "renovation": stmt.excluded.renovation,
                    "exposition_days": stmt.excluded.exposition_days,
                    "publish_date": stmt.excluded.publish_date,
                    "sold_date": stmt.excluded.sold_date,
                    "raw_data": stmt.excluded.raw_data,
                },
            )
            await session.execute(stmt)
            await session.commit()
        logger.info("upsert_sold_offers_batch: %d записей", len(rows))
        return len(rows)

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _house_to_row(h: House) -> dict:
        """House → dict для insert (исключая id/created_at)."""
        return {
            "source": h.source,
            "external_house_id": h.external_house_id,
            "cian_house_id": h.cian_house_id,
            "address": h.address,
            "street": h.street,
            "house_num": h.house_num,
            "district": h.district,
            "okrug": h.okrug,
            "lat": h.lat,
            "lng": h.lng,
            "year_built": h.year_built,
            "levels": h.levels,
            "building_type": h.building_type,
            "series": h.series,
            "ceiling_height": h.ceiling_height,
            "package": h.package,
            "raw_data": h.raw_data,
        }

    @staticmethod
    def _active_to_row(a: ActiveAd) -> dict:
        return {
            "source": a.source,
            "external_id": a.external_id,
            "url": a.url,
            "house_id": a.house_id,
            "cian_house_id": a.cian_house_id,
            "price": a.price,
            "price_per_m2": a.price_per_m2,
            "area": a.area,
            "rooms": a.rooms,
            "floor_current": a.floor_current,
            "floor_total": a.floor_total,
            "metro_station": a.metro_station,
            "metro_walk_time": a.metro_walk_time,
            "district": a.district,
            "okrug": a.okrug,
            "renovation": a.renovation,
            "is_active": a.is_active,
            "days_in_exposition": a.days_in_exposition,
            "total_views": a.total_views,
            "unique_views": a.unique_views,
            "publish_date": a.publish_date,
            "filter_id": a.filter_id,
            "price_history": a.price_history,
            "raw_data": a.raw_data,
        }

    @staticmethod
    def _sold_to_row(s: SoldAd) -> dict:
        return {
            "source": s.source,
            "external_id": s.external_id,
            "url": s.url,
            "house_id": s.house_id,
            "cian_house_id": s.cian_house_id,
            "price": s.price,
            "price_per_m2": s.price_per_m2,
            "area": s.area,
            "rooms": s.rooms,
            "floor_current": s.floor_current,
            "floor_total": s.floor_total,
            "renovation": s.renovation,
            "exposition_days": s.exposition_days,
            "publish_date": s.publish_date,
            "sold_date": s.sold_date,
            "raw_data": s.raw_data,
        }

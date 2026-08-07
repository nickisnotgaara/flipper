"""Фикстуры для тестов flipper_db.

Используем SQLite in-memory через aiosqlite, чтобы тесты не требовали
живого PostgreSQL. SQLAlchemy-диалект переключаем на sqlite+aiosqlite.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text

from packages.flipper_db import (
    FlipperRepository,
    House,
    SoldAd,
    Source,
    get_session_factory,
    init_db,
    init_engine,
)


@pytest_asyncio.fixture
async def repo():
    """In-memory SQLite repo. Создаёт таблицы + очищает перед каждым тестом.

    С идемпотентным init_engine (тот же URL = тот же in-memory engine),
    между тестами данные сохраняются. Поэтому явно очищаем таблицы.
    """
    init_engine("sqlite+aiosqlite:///:memory:")
    await init_db()

    # Очистка таблиц для изоляции тестов
    sf = get_session_factory()
    async with sf() as session:
        await session.execute(text("DELETE FROM active_ads"))
        await session.execute(text("DELETE FROM sold_ads"))
        await session.execute(text("DELETE FROM houses"))
        await session.commit()

    return FlipperRepository()


@pytest.fixture
def sample_house() -> House:
    return House(
        source=Source.WINNERS_SOLD.value,
        external_house_id="house-1",
        address="Москва, ул. Тверская, 1",
        street="ул. Тверская",
        house_num="1",
        district="Тверской",
        okrug="ЦАО",
        lat=55.7615,
        lng=37.6105,
        year_built=1985,
        levels=9,
        building_type="панель",
        series="П-44",
        package="old_fund",
        ceiling_height=2.65,
        raw_data={"original": "data", "extra": 42},
    )


@pytest.fixture
def sample_house_2() -> House:
    return House(
        source=Source.WINNERS_SOLD.value,
        external_house_id="house-2",
        address="Москва, ул. Арбат, 10",
        lat=55.7494,
        lng=37.5912,
        year_built=2020,
        levels=15,
        building_type="монолит",
        package="new_building",
    )


@pytest.fixture
def sample_sold_ad() -> SoldAd:
    return SoldAd(
        source=Source.WINNERS_SOLD.value,
        external_id="offer-1",
        price=15_000_000,
        price_per_m2=230_000,
        area=65.0,
        rooms=2,
        floor_current=5,
        floor_total=9,
        renovation="косметический",
        exposition_days=45,
        raw_data={"url": "https://example.com/offer-1"},
    )

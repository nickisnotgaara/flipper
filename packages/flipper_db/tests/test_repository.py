"""Тесты repository: upsert идемпотентность, поиск, batch-операции."""

import pytest

from packages.flipper_db import (
    House,
    SoldAd,
    Source,
)


@pytest.mark.asyncio
async def test_upsert_houses_basic(repo, sample_house):
    """Базовый upsert дома."""
    n = await repo.upsert_houses_batch([sample_house])
    assert n == 1

    found = await repo.find_house_id(
        source=Source.WINNERS_SOLD.value,
        external_house_id="house-1",
    )
    assert found is not None


@pytest.mark.asyncio
async def test_upsert_houses_idempotent(repo, sample_house):
    """Повторный upsert с тем же (source, external_house_id) обновляет, не дублирует."""
    await repo.upsert_houses_batch([sample_house])

    # Меняем поле и снова upsert
    sample_house.year_built = 1990
    sample_house.ceiling_height = 2.85
    await repo.upsert_houses_batch([sample_house])

    # Должна быть всё ещё одна запись
    found = await repo.find_house_id(
        source=Source.WINNERS_SOLD.value,
        external_house_id="house-1",
    )
    assert found is not None

    # Проверяем что запись обновилась
    from sqlalchemy import select
    from packages.flipper_db.models import House as HouseModel
    sf = repo._sf
    async with sf() as session:
        result = await session.execute(
            select(HouseModel).where(HouseModel.id == found)
        )
        row = result.scalar_one()
        assert row.year_built == 1990
        assert row.ceiling_height == 2.85


@pytest.mark.asyncio
async def test_upsert_multiple_houses(repo, sample_house, sample_house_2):
    """Batch из нескольких домов."""
    n = await repo.upsert_houses_batch([sample_house, sample_house_2])
    assert n == 2

    id1 = await repo.find_house_id(Source.WINNERS_SOLD.value, "house-1")
    id2 = await repo.find_house_id(Source.WINNERS_SOLD.value, "house-2")
    assert id1 is not None
    assert id2 is not None
    assert id1 != id2


@pytest.mark.asyncio
async def test_find_house_by_cian_id(repo, sample_house):
    """Поиск дома по cian_house_id (для будущей сшивки источников)."""
    sample_house.cian_house_id = 12345
    await repo.upsert_houses_batch([sample_house])

    found = await repo.find_house_by_cian_id(12345)
    assert found is not None
    assert found.cian_house_id == 12345

    not_found = await repo.find_house_by_cian_id(99999)
    assert not_found is None


@pytest.mark.asyncio
async def test_different_sources_can_share_cian_house_id(repo):
    """Один cian_house_id может быть у домов из разных source (это OK,
    find_house_by_cian_id возвращает первый попавшийся — сшивка для
    будущей карты)."""
    from packages.flipper_db.models import House as HouseModel
    from sqlalchemy import select, func

    h1 = House(
        source=Source.CIAN_SOLD.value,
        external_house_id="ext-1",
        cian_house_id=100,
        address="addr-1",
    )
    h2 = House(
        source=Source.WINNERS_SOLD.value,
        external_house_id="ext-2",
        cian_house_id=100,  # тот же cian_house_id
        address="addr-2",
    )
    await repo.upsert_houses_batch([h1, h2])

    # Проверяем что обе записи в БД
    sf = repo._sf
    async with sf() as session:
        result = await session.execute(
            select(func.count(HouseModel.id)).where(HouseModel.cian_house_id == 100)
        )
        assert result.scalar() == 2


@pytest.mark.asyncio
async def test_upsert_sold_offers(repo, sample_sold_ad):
    """Upsert снятого объявления."""
    n = await repo.upsert_sold_offers_batch([sample_sold_ad])
    assert n == 1

    from sqlalchemy import select
    from packages.flipper_db.models import SoldAd as SoldAdModel
    sf = repo._sf
    async with sf() as session:
        result = await session.execute(
            select(SoldAdModel).where(
                SoldAdModel.source == Source.WINNERS_SOLD.value,
                SoldAdModel.external_id == "offer-1",
            )
        )
        row = result.scalar_one()
        assert row.price == 15_000_000
        assert row.area == 65.0
        assert row.rooms == 2


@pytest.mark.asyncio
async def test_upsert_sold_idempotent(repo, sample_sold_ad):
    """Повторный upsert с тем же (source, external_id) обновляет цену."""
    await repo.upsert_sold_offers_batch([sample_sold_ad])
    sample_sold_ad.price = 16_500_000
    await repo.upsert_sold_offers_batch([sample_sold_ad])

    from sqlalchemy import select, func
    from packages.flipper_db.models import SoldAd as SoldAdModel
    sf = repo._sf
    async with sf() as session:
        result = await session.execute(
            select(func.count(SoldAdModel.id)).where(
                SoldAdModel.source == Source.WINNERS_SOLD.value
            )
        )
        assert result.scalar() == 1  # одна запись, не две

        result2 = await session.execute(
            select(SoldAdModel).where(
                SoldAdModel.source == Source.WINNERS_SOLD.value
            )
        )
        row = result2.scalar_one()
        assert row.price == 16_500_000  # обновлённая цена


@pytest.mark.asyncio
async def test_empty_batch_returns_zero(repo):
    """Пустой batch → 0, без ошибок."""
    assert await repo.upsert_houses_batch([]) == 0
    assert await repo.upsert_sold_offers_batch([]) == 0


@pytest.mark.asyncio
async def test_raw_data_stored_as_jsonb(repo, sample_house):
    """raw_data (JSONB) сохраняется и читается корректно."""
    await repo.upsert_houses_batch([sample_house])

    from sqlalchemy import select
    from packages.flipper_db.models import House as HouseModel
    sf = repo._sf
    async with sf() as session:
        result = await session.execute(
            select(HouseModel).where(
                HouseModel.source == Source.WINNERS_SOLD.value
            )
        )
        row = result.scalar_one()
        # В SQLite JSONB хранится как JSON; значения доступны
        assert row.raw_data["original"] == "data"
        assert row.raw_data["extra"] == 42

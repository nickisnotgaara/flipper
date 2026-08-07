"""Тесты scripts/migrate_secondary_files_to_postgres.py."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.migrate_secondary_files_to_postgres import run


@pytest.fixture
def secondary_dir(tmp_path):
    """Создаёт минимальный набор secondary файлов."""
    s = tmp_path / "secondary"
    (s / "cian" / "data").mkdir(parents=True)
    (s / "winners").mkdir(parents=True)
    (s / "domclick").mkdir(parents=True)
    (s / "flatinfo").mkdir(parents=True)

    # cian_sold: 1 запись
    cian_record = {
        "source": {"year": 1985, "levels": 9, "type": "панель"},
        "cian": {"cian_house_id": 999, "address": "addr"},
        "deactivated_offers": [
            {
                "id": 111,
                "prices": {"price": "15 млн", "priceSqm": "230 769"},
                "title_parsed": {"total_area_sqm": 65, "rooms": 2,
                                 "floor_current": 5, "floor_total": 9},
                "details": {},
                "exposition": "82 дня",
                "dateEnd": "3 июл 2024",
            }
        ],
    }
    (s / "cian" / "data" / "result.jsonl").write_text(
        json.dumps(cian_record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # winners: 1 запись
    winners_data = [
        {"guid": "w-1", "address": "Москва, А, 1", "area": 50.0,
         "is_new_building": True, "price_rub": 10_000_000, "total_room_count": 1},
    ]
    (s / "winners" / "all_advs.json").write_text(
        json.dumps(winners_data, ensure_ascii=False), encoding="utf-8"
    )

    # domclick: 1 запись
    domclick_data = {
        "items": [
            {"id": 222, "url": "https://...", "address": "Б", "price": 1_000_000,
             "area": 30, "rooms": 1, "floor_info": "3/5", "construction_year": 2000}
        ]
    }
    (s / "domclick" / "domclick_result.json").write_text(
        json.dumps(domclick_data, ensure_ascii=False), encoding="utf-8"
    )

    # flatinfo: 1 запись
    flatinfo_data = [
        {"hid": 333, "address": "В", "year_built": 2010, "levels": 9}
    ]
    (s / "flatinfo" / "house_pages_result.json").write_text(
        json.dumps(flatinfo_data, ensure_ascii=False), encoding="utf-8"
    )

    return s


@pytest.mark.asyncio
async def test_migrate_all_sources(repo, secondary_dir):
    """Полная миграция: 4 источника → 4 houses + 3 sold_ads.

    Engine инициализирован фикстурой `repo`. run() переиспользует engine
    (FlipperRepository внутри run() берёт глобальный engine, не пересоздаёт).
    """
    rc = await run(secondary_dir, "sqlite+aiosqlite:///:memory:")
    assert rc == 0

    from sqlalchemy import select, func
    from packages.flipper_db.models import House as HouseModel, SoldAd as SoldAdModel

    sf = repo._sf
    async with sf() as session:
        h_total = await session.execute(
            select(func.count(HouseModel.id))
        )
        assert h_total.scalar() == 4, "ожидаем 4 дома (cian_sold + winners_sold + domclick_sold + flatinfo_houses)"

        s_total = await session.execute(
            select(func.count(SoldAdModel.id))
        )
        # cian_sold: 1, winners_sold: 1, domclick_sold: 1, flatinfo: 0
        assert s_total.scalar() == 3


@pytest.mark.asyncio
async def test_migrate_idempotent(repo, secondary_dir):
    """Повторный запуск → без дубликатов."""
    await run(secondary_dir, "sqlite+aiosqlite:///:memory:")
    await run(secondary_dir, "sqlite+aiosqlite:///:memory:")

    from sqlalchemy import select, func
    from packages.flipper_db.models import House as HouseModel, SoldAd as SoldAdModel

    sf = repo._sf
    async with sf() as session:
        h = await session.execute(select(func.count(HouseModel.id)))
        assert h.scalar() == 4
        s = await session.execute(select(func.count(SoldAdModel.id)))
        assert s.scalar() == 3


@pytest.mark.asyncio
async def test_migrate_missing_dir(tmp_path):
    """secondary не существует → rc=2."""
    rc = await run(tmp_path / "does_not_exist", "sqlite+aiosqlite:///:memory:")
    assert rc == 2


@pytest.mark.asyncio
async def test_migrate_partial_sources(repo, tmp_path):
    """Часть файлов отсутствует — скрипт не падает, импортирует что есть."""
    s = tmp_path / "secondary"
    (s / "winners").mkdir(parents=True)

    winners_data = [
        {"guid": "w-only", "address": "x", "area": 30, "price_rub": 1_000_000,
         "is_new_building": False, "total_room_count": 1},
    ]
    (s / "winners" / "all_advs.json").write_text(
        json.dumps(winners_data), encoding="utf-8"
    )

    rc = await run(s, "sqlite+aiosqlite:///:memory:")
    assert rc == 0

    from sqlalchemy import select, func
    from packages.flipper_db.models import House as HouseModel

    sf = repo._sf
    async with sf() as session:
        h = await session.execute(
            select(func.count(HouseModel.id)).where(HouseModel.source == "winners_sold")
        )
        assert h.scalar() == 1

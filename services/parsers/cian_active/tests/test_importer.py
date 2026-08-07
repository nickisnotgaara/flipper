"""Тесты importer.py для cian_active (миграция из parser_cian.db в flipper_db)."""

import json
import sqlite3

import pytest

from services.parsers.cian_active.importer import import_cian_active_to_db


def _make_old_cian_db(path, *, with_active=True, with_sold=True) -> str:
    """Создаёт тестовую parser_cian.db с парой записей."""
    con = sqlite3.connect(str(path))
    cur = con.cursor()
    cur.execute(
        "CREATE TABLE cian_active_ads ("
        "  id INTEGER PRIMARY KEY, url VARCHAR, filter_id INTEGER, source VARCHAR, "
        "  parsed_data JSON, is_parsed BOOLEAN, last_updated TIMESTAMP, added_at TIMESTAMP)"
    )
    cur.execute(
        "CREATE TABLE cian_sold_ads ("
        "  id INTEGER PRIMARY KEY, url VARCHAR, parsed_data JSON, "
        "  publish_date VARCHAR, sold_at TIMESTAMP)"
    )

    if with_active:
        parsed = {
            "cian_id": "111", "house_id": 222, "price": 5_000_000, "area": 30.0,
            "rooms": 1, "is_active": True, "publish_date": "2024-01-15",
            "address": {"district": "D", "metro_station": "M", "okrug": "O"},
            "floor_info": {"current": 3, "all": 5},
        }
        cur.execute(
            "INSERT INTO cian_active_ads (url, source, parsed_data, is_parsed)"
            " VALUES (?, ?, ?, ?)",
            ("https://www.cian.ru/sale/flat/111/", "offers", json.dumps(parsed), 1),
        )
    if with_sold:
        sold_parsed = {
            "cian_id": "999", "house_id": 888, "price": 3_000_000, "area": 25.0,
            "rooms": 1, "is_active": False, "days_in_exposition": 30,
        }
        cur.execute(
            "INSERT INTO cian_sold_ads (url, parsed_data, publish_date, sold_at)"
            " VALUES (?, ?, ?, ?)",
            ("https://www.cian.ru/sale/flat/999/", json.dumps(sold_parsed),
             "2024-04-01", "2024-04-15 12:00:00"),
        )
    con.commit()
    con.close()
    return str(path)


@pytest.mark.asyncio
async def test_import_cian_active_dry_run(repo, tmp_path):
    """dry_run=True: читает БД, но не пишет в новую."""
    src = _make_old_cian_db(tmp_path / "old.db")
    result = await import_cian_active_to_db(repo, source=src, dry_run=True)

    assert result["active_ads"] == 1
    assert result["sold_ads"] == 1
    assert result["dry_run"] is True
    assert result["source"] == src

    # Проверяем что НЕ записали в БД
    from sqlalchemy import select, func
    from packages.flipper_db.models import ActiveAd as ActiveModel, SoldAd as SoldModel

    sf = repo._sf
    async with sf() as session:
        a = await session.execute(
            select(func.count(ActiveModel.id)).where(ActiveModel.source == "cian_active")
        )
        assert a.scalar() == 0
        s = await session.execute(
            select(func.count(SoldModel.id)).where(SoldModel.source == "cian_active")
        )
        assert s.scalar() == 0


@pytest.mark.asyncio
async def test_import_cian_active_full(repo, tmp_path):
    """Полный импорт: cian_active_ads → active_ads, cian_sold_ads → sold_ads."""
    src = _make_old_cian_db(tmp_path / "old.db")
    result = await import_cian_active_to_db(repo, source=src, dry_run=False)

    assert result["active_ads"] == 1
    assert result["sold_ads"] == 1
    assert result["dry_run"] is False

    from sqlalchemy import select
    from packages.flipper_db.models import ActiveAd as ActiveModel, SoldAd as SoldModel

    sf = repo._sf
    async with sf() as session:
        a = (await session.execute(
            select(ActiveModel).where(ActiveModel.source == "cian_active")
        )).scalar_one()
        assert a.external_id == "111"
        assert a.price == 5_000_000
        assert a.is_active is True

        s = (await session.execute(
            select(SoldModel).where(SoldModel.source == "cian_active")
        )).scalar_one()
        assert s.external_id == "999"
        assert s.cian_house_id == 888


@pytest.mark.asyncio
async def test_import_cian_active_idempotent(repo, tmp_path):
    """Повторный запуск: без дублей."""
    src = _make_old_cian_db(tmp_path / "old.db")
    await import_cian_active_to_db(repo, source=src, dry_run=False)
    await import_cian_active_to_db(repo, source=src, dry_run=False)

    from sqlalchemy import select, func
    from packages.flipper_db.models import ActiveAd as ActiveModel, SoldAd as SoldModel

    sf = repo._sf
    async with sf() as session:
        a = await session.execute(
            select(func.count(ActiveModel.id)).where(ActiveModel.source == "cian_active")
        )
        assert a.scalar() == 1
        s = await session.execute(
            select(func.count(SoldModel.id)).where(SoldModel.source == "cian_active")
        )
        assert s.scalar() == 1


@pytest.mark.asyncio
async def test_import_cian_active_missing_source_skipped(repo, tmp_path):
    """Несуществующая БД → skip (никаких ошибок)."""
    result = await import_cian_active_to_db(
        repo, source=str(tmp_path / "does_not_exist.db"), dry_run=False
    )
    assert result.get("skipped") is True
    assert result["active_ads"] == 0
    assert result["sold_ads"] == 0


@pytest.mark.asyncio
async def test_import_cian_active_only_active(repo, tmp_path):
    """БД только с active_ads (без sold) — корректный маппинг."""
    src = _make_old_cian_db(tmp_path / "old.db", with_sold=False)
    result = await import_cian_active_to_db(repo, source=src, dry_run=False)
    assert result["active_ads"] == 1
    assert result["sold_ads"] == 0


@pytest.mark.asyncio
async def test_import_cian_active_filter_id_preserved(repo, tmp_path):
    """filter_id из cian_active_ads → ActiveAd.filter_id (для offers/signals/advance)."""
    con = sqlite3.connect(str(tmp_path / "old.db"))
    cur = con.cursor()
    cur.execute(
        "CREATE TABLE cian_active_ads ("
        "  id INTEGER PRIMARY KEY, url VARCHAR, filter_id INTEGER, source VARCHAR, "
        "  parsed_data JSON, is_parsed BOOLEAN, last_updated TIMESTAMP, added_at TIMESTAMP)"
    )
    cur.execute(
        "CREATE TABLE cian_sold_ads ("
        "  id INTEGER PRIMARY KEY, url VARCHAR, parsed_data JSON, "
        "  publish_date VARCHAR, sold_at TIMESTAMP)"
    )
    # 3 объявления с разными cian_id и filter_id:
    # 1 → offers (filter_id=1), 5 → signals/opeka (filter_id=5), 6 → advance (filter_id=6)
    fixtures = [
        (1, 1),
        (5, 5),
        (6, 6),
    ]
    for cian_id_num, fid in fixtures:
        parsed = {
            "cian_id": str(cian_id_num),
            "price": 5_000_000,
            "area": 30.0,
            "rooms": 1,
            "is_active": True,
            "address": {"district": "D", "metro_station": "M", "okrug": "O"},
            "floor_info": {"current": 3, "all": 5},
        }
        cur.execute(
            "INSERT INTO cian_active_ads (url, filter_id, source, parsed_data, is_parsed)"
            " VALUES (?, ?, ?, ?, ?)",
            (f"https://www.cian.ru/sale/flat/{cian_id_num}/", fid, "offers", json.dumps(parsed), 1),
        )
    con.commit()
    con.close()

    result = await import_cian_active_to_db(repo, source=str(tmp_path / "old.db"), dry_run=False)
    assert result["active_ads"] == 3

    from sqlalchemy import select
    from packages.flipper_db.models import ActiveAd as ActiveModel

    sf = repo._sf
    async with sf() as session:
        rows = (await session.execute(
            select(ActiveModel).where(ActiveModel.source == "cian_active").order_by(ActiveModel.filter_id)
        )).scalars().all()
        by_fid = {r.filter_id: r for r in rows}
        assert set(by_fid.keys()) == {1, 5, 6}, f"ожидали 3 filter_id, получили {set(by_fid.keys())}"
        assert {r.external_id for r in rows} == {"1", "5", "6"}

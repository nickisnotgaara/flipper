"""Тесты scripts/migrate_cian_active_db.py."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.migrate_cian_active_db import (
    _active_ad_from_old_row,
    _parse_date,
    _sold_ad_from_old_row,
    run,
)


def _make_old_db(path: Path) -> Path:
    """Создаёт тестовую parser_cian.db с минимальным набором."""
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

    parsed = {
        "cian_id": "327856435",
        "house_id": 12345,
        "price": 17_000_000,
        "price_per_m2": 354_709,
        "area": 49.9,
        "rooms": 2,
        "address": {
            "full": "Москва",
            "district": "Соколиная гора",
            "metro_station": "Семёновская",
            "okrug": "ВАО",
        },
        "floor_info": {"current": 8, "all": 8},
        "renovation": "Косметический",
        "is_active": True,
        "days_in_exposition": 27,
        "total_views": 1512,
        "unique_views": 73,
        "publish_date": "2026-03-16",
        "price_history": [{"date": "2023-03-23", "price": 17_000_000, "change_type": "initial"}],
    }
    cur.execute(
        "INSERT INTO cian_active_ads (url, filter_id, source, parsed_data, is_parsed, last_updated, added_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("https://www.cian.ru/sale/flat/327856435/", 1, "offers", json.dumps(parsed), 1, "2026-04-11 22:47:17", "2026-04-11 22:18:29"),
    )

    sold_parsed = {**parsed, "cian_id": "999000", "house_id": 67890, "is_active": False, "days_in_exposition": 45}
    cur.execute(
        "INSERT INTO cian_sold_ads (url, parsed_data, publish_date, sold_at)"
        " VALUES (?, ?, ?, ?)",
        ("https://www.cian.ru/sale/flat/999000/", json.dumps(sold_parsed), "2026-04-15", "2026-04-15 12:00:00"),
    )
    con.commit()
    con.close()
    return path


def test_parse_date():
    assert _parse_date("2024-01-15") is not None
    assert _parse_date("2024-01-15T10:00:00Z") is not None
    assert _parse_date(None) is None
    assert _parse_date("") is None
    assert _parse_date("garbage") is None


def test_active_ad_from_old_row_basic():
    parsed = {
        "cian_id": "111",
        "house_id": 222,
        "price": 10_000_000,
        "area": 50.0,
        "rooms": 2,
        "address": {"district": "Test", "metro_station": "M", "okrug": "OAO"},
        "floor_info": {"current": 3, "all": 5},
        "is_active": True,
        "publish_date": "2024-01-15",
    }
    row = (1, "https://www.cian.ru/sale/flat/111/", 1, "offers", json.dumps(parsed), 1, "2024-01-15", "2024-01-15")
    cols = ["id", "url", "filter_id", "source", "parsed_data", "is_parsed", "last_updated", "added_at"]

    a = _active_ad_from_old_row(row, cols)
    assert a is not None
    assert a.source == "cian_active"
    assert a.external_id == "111"
    assert a.url == "https://www.cian.ru/sale/flat/111/"
    assert a.cian_house_id == 222
    assert a.price == 10_000_000
    assert a.is_active is True
    assert a.floor_current == 3
    assert a.floor_total == 5
    assert a.district == "Test"
    assert a.metro_station == "M"
    assert a.okrug == "OAO"


def test_active_ad_from_old_row_cian_id_from_url():
    """Если cian_id нет в parsed_data — извлекаем из URL."""
    parsed = {"price": 5_000_000, "area": 30.0, "is_active": True}
    row = (1, "https://www.cian.ru/sale/flat/555123/", 1, "offers", json.dumps(parsed), 1, "2024", "2024")
    cols = ["id", "url", "filter_id", "source", "parsed_data", "is_parsed", "last_updated", "added_at"]

    a = _active_ad_from_old_row(row, cols)
    assert a is not None
    assert a.external_id == "555123"


def test_active_ad_cian_id_null_string_falls_back_to_url():
    """Регрессия: cian_id='null' (строка, от бага парсера) → fallback на URL.

    Раньше `if not cian_id` пропускал строку 'null' как truthy, и тогда
    10 разных записей с cian_id='null' схлопывались в одну по уникальному
    ключу (source, cian_id). Теперь явно валидируем и fallback-имся на URL.
    """
    parsed = {"cian_id": "null", "price": 5_000_000, "area": 30.0, "is_active": True}
    row = (1, "https://www.cian.ru/sale/flat/777111/", 1, "offers", json.dumps(parsed), 1, "2024", "2024")
    cols = ["id", "url", "filter_id", "source", "parsed_data", "is_parsed", "last_updated", "added_at"]

    a = _active_ad_from_old_row(row, cols)
    assert a is not None
    assert a.external_id == "777111"  # из URL, не 'null'!
    assert a.filter_id == 1


def test_active_ad_filter_id_preserved():
    """filter_id из старой БД сохраняется в ActiveAd (для offers/signals/advance)."""
    parsed = {"cian_id": "999", "price": 1_000_000, "area": 30.0, "is_active": True}
    for fid, label in [(1, "offers"), (5, "signals/opeka"), (6, "advance")]:
        row = (1, "https://www.cian.ru/sale/flat/999/", fid, "offers", json.dumps(parsed), 1, "2024", "2024")
        cols = ["id", "url", "filter_id", "source", "parsed_data", "is_parsed", "last_updated", "added_at"]
        a = _active_ad_from_old_row(row, cols)
        assert a is not None
        assert a.filter_id == fid, f"filter_id для {label} должен сохраниться"


def test_active_ad_no_url_returns_none():
    row = (1, None, 1, "offers", "{}", 1, "2024", "2024")
    cols = ["id", "url", "filter_id", "source", "parsed_data", "is_parsed", "last_updated", "added_at"]
    assert _active_ad_from_old_row(row, cols) is None


def test_sold_ad_from_old_row_basic():
    parsed = {
        "cian_id": "888",
        "house_id": 999,
        "price": 8_000_000,
        "area": 40.0,
        "rooms": 1,
        "floor_info": {"current": 2, "all": 9},
        "is_active": False,
        "days_in_exposition": 30,
    }
    row = (1, "https://www.cian.ru/sale/flat/888/", json.dumps(parsed), "2024-04-01", "2024-04-15 12:00:00")
    cols = ["id", "url", "parsed_data", "publish_date", "sold_at"]

    s = _sold_ad_from_old_row(row, cols)
    assert s is not None
    assert s.source == "cian_active"
    assert s.external_id == "888"
    assert s.url == "https://www.cian.ru/sale/flat/888/"
    assert s.cian_house_id == 999
    assert s.price == 8_000_000
    assert s.sold_date is not None
    assert s.exposition_days == 30


# ============================================================ integration

@pytest.mark.asyncio
async def test_migrate_full(repo, tmp_path):
    src = _make_old_db(tmp_path / "old.db")
    rc = await run(str(src), "sqlite+aiosqlite:///:memory:")
    assert rc == 0

    from sqlalchemy import select, func
    from packages.flipper_db.models import ActiveAd as ActiveModel, SoldAd as SoldModel

    sf = repo._sf
    async with sf() as session:
        a_count = await session.execute(
            select(func.count(ActiveModel.id)).where(ActiveModel.source == "cian_active")
        )
        assert a_count.scalar() == 1

        s_count = await session.execute(
            select(func.count(SoldModel.id)).where(SoldModel.source == "cian_active")
        )
        assert s_count.scalar() == 1


@pytest.mark.asyncio
async def test_migrate_idempotent(repo, tmp_path):
    src = _make_old_db(tmp_path / "old.db")
    await run(str(src), "sqlite+aiosqlite:///:memory:")
    await run(str(src), "sqlite+aiosqlite:///:memory:")

    from sqlalchemy import select, func
    from packages.flipper_db.models import ActiveAd as ActiveModel, SoldAd as SoldModel

    sf = repo._sf
    async with sf() as session:
        a_count = await session.execute(
            select(func.count(ActiveModel.id)).where(ActiveModel.source == "cian_active")
        )
        assert a_count.scalar() == 1

        s_count = await session.execute(
            select(func.count(SoldModel.id)).where(SoldModel.source == "cian_active")
        )
        assert s_count.scalar() == 1


@pytest.mark.asyncio
async def test_migrate_missing_source(repo, tmp_path):
    with pytest.raises(FileNotFoundError):
        await run(str(tmp_path / "does_not_exist.db"), "sqlite+aiosqlite:///:memory:")

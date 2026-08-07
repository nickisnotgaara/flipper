"""Тесты importer.py для domclick_sold."""

import json
from datetime import date

import pytest

from services.parsers.domclick_sold.importer import (
    _house_from_item,
    _parse_date,
    _parse_floor_info,
    _sold_ad_from_item,
    import_domclick_json,
)


def test_parse_date():
    assert _parse_date("2024-01-15T10:00:00") == date(2024, 1, 15)
    assert _parse_date("2024-01-15") == date(2024, 1, 15)
    assert _parse_date(None) is None
    assert _parse_date("") is None
    assert _parse_date("garbage") is None


def test_parse_floor_info():
    assert _parse_floor_info("5/9") == (5, 9)
    assert _parse_floor_info("12 / 17") == (12, 17)
    assert _parse_floor_info(None) == (None, None)
    assert _parse_floor_info("") == (None, None)
    assert _parse_floor_info("garbage") == (None, None)


def test_house_from_item_basic():
    it = {
        "id": 12345,
        "address": "Москва, ул. Тверская, 1",
        "district": "Тверской",
        "okrug": "ЦАО",
        "construction_year": 1985,
        "housing_type": "панель",
    }
    h = _house_from_item(it)
    assert h is not None
    assert h.source == "domclick_sold"
    assert h.external_house_id == "12345"
    assert h.address == "Москва, ул. Тверская, 1"
    assert h.year_built == 1985


def test_house_no_id_returns_none():
    assert _house_from_item({"address": "addr"}) is None


def test_sold_ad_from_item_basic():
    it = {
        "id": 12345,
        "url": "https://domclick.ru/card/12345",
        "publish_date": "2024-01-15T10:00:00",
        "price": 15_000_000,
        "price_per_m2": 230_000,
        "area": 65.0,
        "rooms": 2,
        "floor_info": "5/9",
        "renovation": "косметический",
        "days_in_exposition": 45,
    }
    s = _sold_ad_from_item(it)
    assert s is not None
    assert s.source == "domclick_sold"
    assert s.external_id == "12345"
    assert s.url == "https://domclick.ru/card/12345"
    assert s.price == 15_000_000
    assert s.floor_current == 5
    assert s.floor_total == 9
    assert s.rooms == 2
    assert s.exposition_days == 45
    assert s.publish_date == date(2024, 1, 15)


# ============================================================ integration

@pytest.fixture
def sample_domclick_json(tmp_path):
    p = tmp_path / "domclick_result.json"
    data = {
        "fetched_at": "2024-01-15T12:00:00",
        "list_count": 2,
        "items": [
            {
                "id": 111,
                "url": "https://domclick.ru/card/111",
                "address": "Москва, ул. А, 1",
                "price": 10_000_000,
                "area": 50.0,
                "rooms": 1,
                "floor_info": "3/5",
                "construction_year": 1980,
            },
            {
                "id": 222,
                "url": "https://domclick.ru/card/222",
                "address": "Москва, ул. Б, 2",
                "price": 20_000_000,
                "area": 80.0,
                "rooms": 3,
                "floor_info": "9/17",
                "construction_year": 2010,
            },
        ],
    }
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.mark.asyncio
async def test_import_basic(repo, sample_domclick_json):
    n_h, n_s = await import_domclick_json(repo, sample_domclick_json)
    assert n_h == 2
    assert n_s == 2


@pytest.mark.asyncio
async def test_import_missing_file(repo, tmp_path):
    n_h, n_s = await import_domclick_json(repo, tmp_path / "missing.json")
    assert n_h == 0
    assert n_s == 0


@pytest.mark.asyncio
async def test_import_wrong_format(repo, tmp_path):
    p = tmp_path / "wrong.json"
    p.write_text("not a json", encoding="utf-8")
    n_h, n_s = await import_domclick_json(repo, p)
    assert n_h == 0
    assert n_s == 0


@pytest.mark.asyncio
async def test_import_accepts_list_at_root(repo, tmp_path):
    """Допускаем JSON-массив на верхнем уровне (на случай если items развернут)."""
    p = tmp_path / "list_root.json"
    data = [{"id": 999, "url": "...", "address": "x", "price": 1_000_000, "area": 30, "rooms": 1}]
    p.write_text(json.dumps(data), encoding="utf-8")
    n_h, n_s = await import_domclick_json(repo, p)
    assert n_h == 1
    assert n_s == 1


@pytest.mark.asyncio
async def test_import_idempotent(repo, sample_domclick_json):
    await import_domclick_json(repo, sample_domclick_json)
    await import_domclick_json(repo, sample_domclick_json)

    from sqlalchemy import select, func
    from packages.flipper_db.models import House as HouseModel, SoldAd as SoldAdModel

    sf = repo._sf
    async with sf() as session:
        h_count = await session.execute(
            select(func.count(HouseModel.id)).where(HouseModel.source == "domclick_sold")
        )
        assert h_count.scalar() == 2

        s_count = await session.execute(
            select(func.count(SoldAdModel.id)).where(SoldAdModel.source == "domclick_sold")
        )
        assert s_count.scalar() == 2


@pytest.mark.asyncio
async def test_import_skips_items_without_id(repo, tmp_path):
    p = tmp_path / "mixed.json"
    data = {
        "items": [
            {"id": 1, "url": "...", "address": "x", "price": 1_000_000, "area": 30},
            {"no_id": "bad"},  # пропускается
            "not a dict",       # пропускается
        ]
    }
    p.write_text(json.dumps(data), encoding="utf-8")
    n_h, n_s = await import_domclick_json(repo, p)
    assert n_h == 1
    assert n_s == 1

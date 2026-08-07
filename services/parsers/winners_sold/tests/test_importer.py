"""Тесты importer.py для winners_sold."""

import json

import pytest

from services.parsers.winners_sold.importer import (
    _house_from_record,
    _parse_date,
    _sold_ad_from_record,
    import_winners_json,
)


def test_parse_date():
    from datetime import date
    assert _parse_date("2024-01-15T10:00:00Z") == date(2024, 1, 15)
    assert _parse_date("2024-01-15") == date(2024, 1, 15)
    assert _parse_date(None) is None
    assert _parse_date("") is None
    assert _parse_date("garbage") is None


def test_house_from_record_basic():
    rec = {
        "guid": "abc-123",
        "address": "Москва, ул. Тверская, 1",
        "geo_cache_district_name": "Тверской",
        "area": 65.0,
        "is_new_building": True,
        "ceiling_height": 2.85,
    }
    h = _house_from_record(rec)
    assert h is not None
    assert h.source == "winners_sold"
    assert h.external_house_id == "abc-123"
    assert h.address == "Москва, ул. Тверская, 1"
    assert h.district == "Тверской"
    assert h.package == "new_building"
    assert h.ceiling_height == 2.85


def test_house_from_record_address_from_parts():
    """Если `address` нет, собираем из geo_cache_*."""
    rec = {
        "guid": "x",
        "geo_cache_region_name": "Москва",
        "geo_cache_district_name": "Хамовники",
        "geo_cache_street_name": "Льва Толстого",
        "geo_cache_building_name": "16",
    }
    h = _house_from_record(rec)
    assert "Москва" in h.address
    assert "Льва Толстого" in h.address
    assert "16" in h.address


def test_house_from_record_no_guid_returns_none():
    h = _house_from_record({})
    assert h is None


def test_sold_ad_from_record_basic():
    rec = {
        "guid": "abc-123",
        "price_rub": 15_000_000,
        "meter_price_rub": 230_000,
        "area": 65.0,
        "total_room_count": 2,
        "floor_current": 5,
        "floor_total": 9,
        "renovation": "косметический",
        "creation_datetime": "2024-01-15T10:00:00Z",
    }
    s = _sold_ad_from_record(rec)
    assert s is not None
    assert s.source == "winners_sold"
    assert s.external_id == "abc-123"
    assert s.price == 15_000_000
    assert s.price_per_m2 == 230_000
    assert s.area == 65.0
    assert s.rooms == 2
    assert s.publish_date.year == 2024


def test_sold_ad_from_record_no_guid_returns_none():
    s = _sold_ad_from_record({})
    assert s is None


# ============================================================ integration

@pytest.fixture
def sample_winners_json(tmp_path):
    p = tmp_path / "all_advs.json"
    data = [
        {
            "guid": "w-1",
            "address": "Москва, ул. Арбат, 1",
            "area": 50.0,
            "is_new_building": False,
            "price_rub": 12_000_000,
            "meter_price_rub": 240_000,
            "total_room_count": 1,
        },
        {
            "guid": "w-2",
            "address": "Москва, ул. Арбат, 5",
            "area": 80.0,
            "is_new_building": True,
            "price_rub": 25_000_000,
            "meter_price_rub": 312_500,
            "total_room_count": 3,
        },
    ]
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.mark.asyncio
async def test_import_basic(repo, sample_winners_json):
    n_h, n_s = await import_winners_json(repo, sample_winners_json)
    assert n_h == 2
    assert n_s == 2


@pytest.mark.asyncio
async def test_import_missing_file(repo, tmp_path):
    n_h, n_s = await import_winners_json(repo, tmp_path / "missing.json")
    assert n_h == 0
    assert n_s == 0


@pytest.mark.asyncio
async def test_import_wrong_format(repo, tmp_path):
    """Не-массив на верхнем уровне → (0, 0)."""
    p = tmp_path / "wrong.json"
    p.write_text('{"not": "array"}', encoding="utf-8")
    n_h, n_s = await import_winners_json(repo, p)
    assert n_h == 0
    assert n_s == 0


@pytest.mark.asyncio
async def test_import_idempotent(repo, sample_winners_json):
    await import_winners_json(repo, sample_winners_json)
    await import_winners_json(repo, sample_winners_json)

    from sqlalchemy import select, func
    from packages.flipper_db.models import House as HouseModel, SoldAd as SoldAdModel

    sf = repo._sf
    async with sf() as session:
        h_count = await session.execute(
            select(func.count(HouseModel.id)).where(HouseModel.source == "winners_sold")
        )
        assert h_count.scalar() == 2

        s_count = await session.execute(
            select(func.count(SoldAdModel.id)).where(SoldAdModel.source == "winners_sold")
        )
        assert s_count.scalar() == 2


@pytest.mark.asyncio
async def test_import_skips_malformed_records(repo, tmp_path):
    """Записи без guid пропускаются."""
    p = tmp_path / "mixed.json"
    data = [
        {"guid": "ok-1", "address": "addr", "area": 50, "price_rub": 1_000_000},
        {"no_guid": "bad"},  # пропускается
        "not a dict",         # пропускается
    ]
    p.write_text(json.dumps(data), encoding="utf-8")
    n_h, n_s = await import_winners_json(repo, p)
    assert n_h == 1
    assert n_s == 1

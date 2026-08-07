"""Тесты importer.py для flatinfo_houses."""

import json

import pytest

from services.parsers.flatinfo_houses.importer import (
    _house_from_record,
    import_flatinfo_json,
)


def test_house_from_record_basic():
    rec = {
        "hid": 12345,
        "address": "Москва, ул. Тверская, 1",
        "street": "ул. Тверская",
        "house_num": "1",
        "city_id": "1",
        "year_built": 1985,
        "levels": 9,
        "material": "панель",
        "series": "П-44",
        "ceiling_height": 2.65,
    }
    h = _house_from_record(rec)
    assert h is not None
    assert h.source == "flatinfo_houses"
    assert h.external_house_id == "12345"
    assert h.address == "Москва, ул. Тверская, 1"
    assert h.year_built == 1985
    assert h.levels == 9
    assert h.building_type == "панель"
    assert h.series == "П-44"
    assert h.ceiling_height == 2.65


def test_house_from_record_no_id_returns_none():
    assert _house_from_record({"address": "addr"}) is None


def test_house_from_record_alt_year_key():
    """Допускаем оба варианта: year_built или year."""
    rec = {"hid": 1, "year": 2000}
    h = _house_from_record(rec)
    assert h.year_built == 2000


def test_house_from_record_alt_levels_key():
    rec = {"hid": 1, "floors": 17}
    h = _house_from_record(rec)
    assert h.levels == 17


def test_house_from_record_alt_material_key():
    rec = {"hid": 1, "building_type": "кирпич"}
    h = _house_from_record(rec)
    assert h.building_type == "кирпич"


# ============================================================ реальные данные (от house_pages_parser.py)

def test_house_from_record_real_format_house_id():
    """Реальные данные от house_pages_parser.py используют house_id, year (string), house_type."""
    rec = {
        "house_id": 12345,
        "address": "Москва, ул. Тверская, 1",
        "year": "1985",
        "floors_text": "9 этажей",
        "house_type": "Панельный",
        "series": "П-44",
        "ceiling_height": "2.65 м",
        "okrug": "ЦАО",
        "rayon": "Тверской",
    }
    h = _house_from_record(rec)
    assert h is not None
    assert h.external_house_id == "12345"
    assert h.year_built == 1985
    assert h.levels == 9
    assert h.building_type == "Панельный"
    assert h.series == "П-44"
    assert h.ceiling_height == 2.65
    assert h.district == "Тверской"
    assert h.okrug == "ЦАО"


def test_house_from_record_no_house_id_returns_none():
    """Если нет ни house_id, ни hid, ни id — пропускаем."""
    rec = {"address": "addr", "year": "2000"}
    assert _house_from_record(rec) is None


def test_house_from_record_floors_text_no_text():
    """floors_text без 'этажей' всё равно парсится."""
    rec = {"hid": 1, "floors_text": "17"}
    h = _house_from_record(rec)
    assert h.levels == 17


def test_house_from_record_ceiling_height_decimal_string():
    """ceiling_height типа '2.65 м' → 2.65."""
    rec = {"hid": 1, "ceiling_height": "3.20 м"}
    h = _house_from_record(rec)
    assert h.ceiling_height == 3.20


def test_house_from_record_year_string_parsed():
    rec = {"hid": 1, "year": "2010"}
    h = _house_from_record(rec)
    assert h.year_built == 2010


# ============================================================ integration

@pytest.fixture
def sample_flatinfo_json(tmp_path):
    p = tmp_path / "house_pages_result.json"
    data = [
        {
            "hid": 100,
            "address": "Москва, ул. А, 1",
            "year_built": 1980,
            "levels": 9,
            "material": "панель",
        },
        {
            "hid": 200,
            "address": "Москва, ул. Б, 2",
            "year_built": 2015,
            "levels": 25,
            "material": "монолит",
        },
    ]
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.mark.asyncio
async def test_import_basic(repo, sample_flatinfo_json):
    n_h, n_s = await import_flatinfo_json(repo, sample_flatinfo_json)
    assert n_h == 2
    assert n_s == 0  # flatinfo не пишет sold_ads


@pytest.mark.asyncio
async def test_import_missing_file(repo, tmp_path):
    n_h, n_s = await import_flatinfo_json(repo, tmp_path / "missing.json")
    assert n_h == 0
    assert n_s == 0


@pytest.mark.asyncio
async def test_import_wrong_format(repo, tmp_path):
    p = tmp_path / "wrong.json"
    p.write_text("not a json", encoding="utf-8")
    n_h, n_s = await import_flatinfo_json(repo, p)
    assert n_h == 0
    assert n_s == 0


@pytest.mark.asyncio
async def test_import_not_a_list(repo, tmp_path):
    p = tmp_path / "notlist.json"
    p.write_text('{"not": "array"}', encoding="utf-8")
    n_h, n_s = await import_flatinfo_json(repo, p)
    assert n_h == 0
    assert n_s == 0


@pytest.mark.asyncio
async def test_import_idempotent(repo, sample_flatinfo_json):
    await import_flatinfo_json(repo, sample_flatinfo_json)
    await import_flatinfo_json(repo, sample_flatinfo_json)

    from sqlalchemy import select, func
    from packages.flipper_db.models import House as HouseModel

    sf = repo._sf
    async with sf() as session:
        h_count = await session.execute(
            select(func.count(HouseModel.id)).where(HouseModel.source == "flatinfo_houses")
        )
        assert h_count.scalar() == 2


@pytest.mark.asyncio
async def test_import_skips_records_without_hid(repo, tmp_path):
    p = tmp_path / "mixed.json"
    data = [
        {"hid": 1, "address": "addr"},
        {"no_hid": "bad"},  # пропускается
        "not a dict",        # пропускается
    ]
    p.write_text(json.dumps(data), encoding="utf-8")
    n_h, n_s = await import_flatinfo_json(repo, p)
    assert n_h == 1
    assert n_s == 0

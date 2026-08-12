"""Тесты importer.py для cian_sold."""

import json

import pytest

from services.parsers.cian_sold.importer import (
    classify_house,
    import_cian_sold_jsonl,
    parse_exposition,
    parse_price_int,
    parse_ru_date,
)


# ============================================================ text parsers

def test_parse_exposition():
    assert parse_exposition("82 дня") == 82
    assert parse_exposition("3 дня") == 3
    assert parse_exposition("625 дней") == 625
    assert parse_exposition(None) is None
    assert parse_exposition("") is None
    assert parse_exposition("нет дней") is None


def test_parse_ru_date():
    assert parse_ru_date("3 июл 2024") == pytest.approx(__import__("datetime").date(2024, 7, 3))
    assert parse_ru_date("23 сен 2024") == pytest.approx(__import__("datetime").date(2024, 9, 23))
    assert parse_ru_date("2024-07-03") == pytest.approx(__import__("datetime").date(2024, 7, 3))
    assert parse_ru_date("3 июл 2024 г.") == pytest.approx(__import__("datetime").date(2024, 7, 3))
    assert parse_ru_date(None) is None
    assert parse_ru_date("") is None
    assert parse_ru_date("garbage") is None


def test_parse_price_int():
    assert parse_price_int("35,0 млн ₽") == 35_000_000
    assert parse_price_int("2,5 млрд ₽") == 2_500_000_000
    assert parse_price_int("476 839 ₽/м²") == 476_839
    assert parse_price_int("12 млн") == 12_000_000
    assert parse_price_int(None) is None
    assert parse_price_int("") is None
    assert parse_price_int(15_000_000) == 15_000_000


# ============================================================ classify_house

def test_classify_house_old_fund():
    assert classify_house(1940, 5, None, None) == "old_fund"
    assert classify_house(1980, 9, None, None) == "old_fund"


def test_classify_house_modern():
    assert classify_house(2000, 9, None, None) == "modern"
    assert classify_house(2005, 17, None, None) == "modern"


def test_classify_house_new_building():
    assert classify_house(2015, 25, None, None) == "new_building"
    assert classify_house(2024, 30, None, None) == "new_building"


def test_classify_house_elite():
    """Высотка (12+ этажей) до 1990 → elite."""
    assert classify_house(1985, 16, None, None) == "elite"


def test_classify_house_unknown():
    assert classify_house(None, None, None, None) == "unknown"


# ============================================================ import_cian_sold_jsonl

@pytest.fixture
def sample_jsonl(tmp_path):
    """Создаёт sample.jsonl с одной записью (1 дом + 2 оффера)."""
    rec = {
        "source": {
            "type": "панель",
            "year": 1985,
            "levels": 9,
            "ser_name": "П-44",
            "house_id": 123,
            "street": "ул. Тверская",
            "house_num": "1",
        },
        "cian": {
            "cian_house_id": 99999,
            "address": "Москва, ул. Тверская, 1",
            "lat": 55.7615,
            "lng": 37.6105,
        },
        "deactivated_offers": [
            {
                "id": 111,
                "prices": {"price": "15,0 млн ₽", "priceSqm": "230 769 ₽/м²"},
                "title_parsed": {"total_area_sqm": 65, "rooms": 2,
                                 "floor_current": 5, "floor_total": 9},
                "details": {"features_parsed": {"renovation": "косметический"}},
                "exposition": "82 дня",
                "dateEnd": "3 июл 2024",
                "dateStart": "1 апр 2024",
            },
            {
                "id": 222,
                "prices": {"price": "12,0 млн ₽", "priceSqm": "240 000 ₽/м²"},
                "title_parsed": {"total_area_sqm": 50, "rooms": 1,
                                 "floor_current": 3, "floor_total": 9},
                "details": {},
                "exposition": "45 дней",
                "dateEnd": "15 май 2024",
            },
        ],
    }
    p = tmp_path / "sample.jsonl"
    with p.open("w", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return p


@pytest.mark.asyncio
async def test_import_basic(repo, sample_jsonl):
    """Базовый импорт: 1 дом + 2 оффера."""
    n_houses, n_sold = await import_cian_sold_jsonl(repo, sample_jsonl)
    assert n_houses == 1
    assert n_sold == 2

    # Проверяем что house записан
    house_id = await repo.find_house_id("cian_sold", "99999")
    assert house_id is not None


@pytest.mark.asyncio
async def test_import_missing_file(repo, tmp_path):
    """Несуществующий файл → (0, 0) без падения."""
    n_houses, n_sold = await import_cian_sold_jsonl(repo, tmp_path / "missing.jsonl")
    assert n_houses == 0
    assert n_sold == 0


@pytest.mark.asyncio
async def test_import_skips_malformed_lines(repo, tmp_path):
    """Битые JSON-строки пропускаются, не падают."""
    p = tmp_path / "mixed.jsonl"
    with p.open("w", encoding="utf-8") as f:
        f.write("not a json\n")
        # валидная запись
        rec = {
            "source": {"year": 2000, "levels": 9},
            "cian": {"cian_house_id": 100, "address": "addr"},
            "deactivated_offers": [
                {"id": 1, "prices": {}, "title_parsed": {}, "details": {},
                 "exposition": "10 дней", "dateEnd": "1 янв 2024"}
            ],
        }
        f.write(json.dumps(rec) + "\n")
        f.write("{incomplete\n")  # снова битая

    n_houses, n_sold = await import_cian_sold_jsonl(repo, p)
    assert n_houses == 1
    assert n_sold == 1


@pytest.mark.asyncio
async def test_import_idempotent(repo, sample_jsonl):
    """Повторный импорт тех же данных → без дубликатов."""
    await import_cian_sold_jsonl(repo, sample_jsonl)
    await import_cian_sold_jsonl(repo, sample_jsonl)

    from sqlalchemy import select, func
    from packages.flipper_db.models import House as HouseModel, SoldAd as SoldAdModel

    sf = repo._sf
    async with sf() as session:
        houses_count = await session.execute(
            select(func.count(HouseModel.id)).where(HouseModel.source == "cian_sold")
        )
        assert houses_count.scalar() == 1

        sold_count = await session.execute(
            select(func.count(SoldAdModel.id)).where(SoldAdModel.source == "cian_sold")
        )
        assert sold_count.scalar() == 2


@pytest.mark.asyncio
async def test_import_skip_record_without_cian_house_id(repo, tmp_path):
    """Запись без cian_house_id пропускается (house = None, офферы тоже)."""
    p = tmp_path / "no_cian_id.jsonl"
    rec = {
        "source": {"year": 2000},
        "cian": {},  # пустой — cian_house_id нет
        "deactivated_offers": [{"id": 1}],
    }
    with p.open("w", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")

    n_houses, n_sold = await import_cian_sold_jsonl(repo, p)
    assert n_houses == 0
    assert n_sold == 0

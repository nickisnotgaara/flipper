"""services.parsers.cian_sold.importer - импорт result.jsonl в PostgreSQL.

result.jsonl формат (из secondary/cian/parser/):
    {
      "source": {"type": "...", "year": ..., "levels": ..., "ser_name": "...",
                 "house_id": ..., "street": ..., "house_num": ...},
      "cian": {"cian_house_id": 12345, "address": "...", "lat": 55.75, "lng": 37.61,
               "yandex_formatted_address": "..."},
      "deactivated_offers": [
        {"id": 999, "prices": {"price": "35,0 млн ₽", "priceSqm": "..."},
         "title_parsed": {"total_area_sqm": 65, "rooms": 2, ...},
         "details": {"features_parsed": {"renovation": "..."}},
         "exposition": "82 дня", "dateEnd": "3 июл 2024", "dateStart": "..."},
        ...
      ]
    }

Маппинг:
    house = (source='cian_sold', external_house_id=str(cian_house_id), ...)
    sold_ad = (source='cian_sold', external_id=str(offer_id), house_id=house.id, ...)

Идемпотентен (upsert).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from packages.flipper_db import (
    FlipperRepository,
    House,
    SoldAd,
    Source,
)
from services.parsers._common import safe_float, safe_int, safe_str

logger = logging.getLogger(__name__)

SOURCE = Source.CIAN_SOLD.value

_MONTHS_RU = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4,
    "май": 5, "мая": 5, "июн": 6, "июл": 7,
    "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4,
    "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}


# ================================================================== parsers


def parse_exposition(s: Any) -> int | None:
    """'82 дня' → 82, '3 дня' → 3, '625 дней' → 625."""
    if not s:
        return None
    m = re.search(r"(\d+)", str(s))
    if not m:
        return None
    return safe_int(m.group(1))


def parse_ru_date(s: Any) -> date | None:
    """'3 июл 2024' / '23 сен 2024' / ISO → date."""
    if not s:
        return None
    s = str(s).strip().strip(".")
    if not s:
        return None

    # ISO format
    m_iso = re.search(r"(20\d{2})-(\d{2})-(\d{2})", s)
    if m_iso:
        try:
            return datetime(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))).date()
        except ValueError:
            pass
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        pass

    # '3 июл 2024 г.'
    parts = s.replace(" г.", "").replace("г.", "").split()
    if len(parts) >= 3:
        try:
            day = int(re.sub(r"\D", "", parts[0]))
            mon_word = re.sub(r"[^а-яёa-z]", "", parts[1].lower())
            mon_raw = mon_word[:3] if len(mon_word) >= 3 else mon_word
            year = int(re.sub(r"\D", "", parts[2]))
            mon = _MONTHS_RU.get(mon_raw)
            if mon:
                return datetime(year, mon, day).date()
        except (ValueError, IndexError):
            pass
    return None


def parse_price_int(s: Any) -> int | None:
    """'35,0 млн ₽' → 35_000_000, '476 839 ₽/м²' → 476839."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return int(round(float(s)))
    s = str(s).strip()
    if not s:
        return None
    low = s.lower()
    if "млн" in low or "млрд" in low:
        m = re.search(r"(\d+(?:[.,]\d+)?)", s)
        if not m:
            return None
        val = float(m.group(1).replace(",", "."))
        if "млрд" in low:
            val *= 1_000_000_000
        else:
            val *= 1_000_000
        return int(round(val))
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None
    return int(digits)


# ================================================================== record processing


def _house_from_record(rec: dict[str, Any]) -> House | None:
    src = rec.get("source") or {}
    cian = rec.get("cian") or {}
    cian_house_id = cian.get("cian_house_id")
    if not cian_house_id:
        return None

    year_raw = src.get("year")
    year = int(year_raw) if year_raw and str(year_raw).isdigit() else None
    levels_raw = src.get("levels")
    levels = int(levels_raw) if levels_raw and str(levels_raw).isdigit() else None

    return House(
        source=SOURCE,
        external_house_id=str(cian_house_id),
        cian_house_id=int(cian_house_id),
        address=cian.get("address") or rec.get("yandex_formatted_address"),
        street=src.get("street"),
        house_num=src.get("house_num"),
        year_built=year,
        levels=levels,
        building_type=src.get("type"),
        series=src.get("ser_name"),
        lat=safe_float(cian.get("lat") or src.get("lat")),
        lng=safe_float(cian.get("lng") or src.get("lng")),
        package=classify_house(
            year=year,
            levels=levels,
            building_type=src.get("type"),
            series=src.get("ser_name"),
        ),
        raw_data=rec,  # сохраняем весь JSON
    )


def classify_house(
    year: int | None,
    levels: int | None,
    building_type: str | None,
    series: str | None,
) -> str:
    """Простая классификация: 'old_fund' | 'modern' | 'new_building' | 'elite' | 'unknown'."""
    if not year:
        return "unknown"
    if year < 1950:
        return "old_fund"
    if year < 1990:
        if levels and levels > 12:
            return "elite"
        return "old_fund"
    if year < 2010:
        return "modern"
    return "new_building"


def _sold_ads_from_record(rec: dict[str, Any]) -> list[SoldAd]:
    src = rec.get("source") or {}
    cian = rec.get("cian") or {}
    cian_house_id = cian.get("cian_house_id")
    if not cian_house_id:
        return []

    out: list[SoldAd] = []
    for off in rec.get("deactivated_offers") or []:
        oid = off.get("id")
        if not oid:
            continue
        prices = off.get("prices") or {}
        tp = off.get("title_parsed") or {}
        details = off.get("details") or {}
        fp = (details.get("features_parsed") or {}) if details else {}

        out.append(
            SoldAd(
                source=SOURCE,
                external_id=str(oid),
                cian_house_id=int(cian_house_id),
                url=None,  # cian_sold не хранит URL объявления
                price=parse_price_int(prices.get("price")),
                price_per_m2=parse_price_int(prices.get("priceSqm")),
                area=safe_float(tp.get("total_area_sqm")),
                rooms=safe_int(tp.get("rooms")),
                floor_current=safe_int(tp.get("floor_current")),
                floor_total=safe_int(tp.get("floor_total")),
                renovation=fp.get("renovation"),
                exposition_days=parse_exposition(off.get("exposition")),
                sold_date=parse_ru_date(off.get("dateEnd")) or parse_ru_date(off.get("dateStart")),
                publish_date=parse_ru_date(off.get("dateStart")),
                raw_data=off,
            )
        )
    return out


# ================================================================== main entry

BATCH_SIZE = 1000  # сколько записей накапливаем перед commit


async def import_cian_sold_jsonl(
    repo: FlipperRepository,
    jsonl_path: str | Path,
) -> tuple[int, int]:
    """Импорт result.jsonl в PostgreSQL (houses + sold_ads).

    Потоковый: читает JSONL построчно, накапливает до BATCH_SIZE и коммитит.
    Не загружает весь файл в память — безопасно для больших файлов (1M+ записей).

    Returns:
        (n_houses, n_sold_ads) — количество реально записанных записей.
    """
    jsonl_path = Path(jsonl_path)
    if not jsonl_path.is_file():
        logger.warning("Файл не найден: %s — пропускаю импорт", jsonl_path)
        return (0, 0)

    houses: list[House] = []
    sold_ads: list[SoldAd] = []
    n_lines = 0
    n_errors = 0
    total_h = 0
    total_s = 0

    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n_lines += 1
            try:
                rec = json.loads(line)
                h = _house_from_record(rec)
                if h is not None:
                    houses.append(h)
                sold_ads.extend(_sold_ads_from_record(rec))
            except Exception as exc:
                n_errors += 1
                logger.debug("ошибка записи (line %s): %s", n_lines, exc)

            if n_lines % 1000 == 0:
                logger.info("импорт: %s строк, %s домов, %s офферов (в буфере)",
                            n_lines, len(houses), len(sold_ads))

            # Flush батча
            if len(houses) >= BATCH_SIZE:
                total_h += await repo.upsert_houses_batch(houses)
                houses = []
            if len(sold_ads) >= BATCH_SIZE:
                total_s += await repo.upsert_sold_offers_batch(sold_ads)
                sold_ads = []

    # Финальный flush
    if houses:
        total_h += await repo.upsert_houses_batch(houses)
    if sold_ads:
        total_s += await repo.upsert_sold_offers_batch(sold_ads)

    logger.info(
        "ИМПОРТ ЗАВЕРШЁН: строк=%s домов=%s офферов=%s ошибок=%s",
        n_lines, total_h, total_s, n_errors,
    )
    return (total_h, total_s)

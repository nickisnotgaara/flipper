"""services.parsers.winners_sold.importer - импорт all_advs*.json в PostgreSQL.

Формат JSON (baza-winner.ru API):
    Список объявлений. Каждое объявление:
    {
      "guid": "...",                # уникальный ID
      "external_id": "...",          # альтернативный ID
      "w6_offer_id": 12345,
      "area": 65.0,
      "is_new_building": true,
      "price_rub": 15000000,
      "meter_price_rub": 230000,
      "address": "Москва, ...",
      "ceiling_height": 2.85,
      "geo_cache_region_name": "Москва",
      "geo_cache_district_name": "...",
      "geo_cache_street_name": "...",
      "geo_cache_building_name": "...",
      "geo_cache_subway_station_name_1": "...",
      "walking_access_1": 5,
      "transport_access_1": 3,
      "creation_datetime": "2024-01-15T10:00:00Z",
      "total_room_count": 2,
      ...
    }

Маппинг v1 (простой):
    house = (source='winners_sold', external_house_id=guid, address, lat?, lng?, ...)
    sold_ad = (source='winners_sold', external_id=guid, price, area, rooms, ...)

Один guid = один house + один sold_ad (без группировки разных объявлений одного дома).
TODO (следующий заход): нормализация по (geo_cache_street_name + building_name) →
несколько офферов из одного физического дома сшиваются в один house.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from packages.flipper_db import (
    FlipperRepository,
    House,
    SoldAd,
    Source,
)
from services.parsers._common import safe_float, safe_int, safe_str

logger = logging.getLogger(__name__)

SOURCE = Source.WINNERS_SOLD.value


def _parse_date(s: Any) -> datetime.date | None:
    """ISO datetime/date → date."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt.date()
    except (ValueError, TypeError):
        return None


def _house_from_record(rec: dict[str, Any]) -> House | None:
    guid = rec.get("guid")
    if not guid:
        return None

    address = rec.get("address")
    # Сборка полного адреса если есть части
    if not address:
        parts = [
            rec.get("geo_cache_region_name"),
            rec.get("geo_cache_district_name"),
            rec.get("geo_cache_micro_district_name"),
            rec.get("geo_cache_settlement_name"),
            rec.get("geo_cache_street_name"),
            rec.get("geo_cache_building_name"),
        ]
        address = ", ".join(p for p in parts if p) or None

    return House(
        source=SOURCE,
        external_house_id=str(guid),
        address=address,
        district=rec.get("geo_cache_district_name"),
        okrug=rec.get("geo_cache_region_name"),
        year_built=safe_int(rec.get("year")),
        levels=safe_int(rec.get("levels_count")),
        building_type=rec.get("building_type"),
        ceiling_height=safe_float(rec.get("ceiling_height")),
        package="new_building" if rec.get("is_new_building") else "old_fund",
        raw_data=rec,
    )


def _sold_ad_from_record(rec: dict[str, Any]) -> SoldAd | None:
    guid = rec.get("guid")
    if not guid:
        return None

    return SoldAd(
        source=SOURCE,
        external_id=str(guid),
        cian_house_id=None,  # winners не даёт cian_house_id
        url=None,  # winners API не возвращает прямую ссылку
        price=safe_int(rec.get("price_rub")),
        price_per_m2=safe_int(rec.get("meter_price_rub")),
        area=safe_float(rec.get("area")),
        rooms=safe_int(rec.get("total_room_count")),
        floor_current=safe_int(rec.get("floor_current")),
        floor_total=safe_int(rec.get("floor_total")),
        renovation=rec.get("renovation"),
        exposition_days=None,  # winners не возвращает days_in_exposition
        publish_date=_parse_date(rec.get("creation_datetime")),
        sold_date=None,  # winners возвращает активные объявления, не снятые
        raw_data=rec,
    )


async def import_winners_json(
    repo: FlipperRepository,
    json_path: str | Path,
) -> tuple[int, int]:
    """Импорт all_advs*.json в PostgreSQL.

    Потоковый: загружает JSON, но коммитит порциями по BATCH_SIZE.
    Безопасно для файлов 100k+ записей (110k winners = 300MB JSON).

    Returns:
        (n_houses, n_sold_ads)
    """
    from services.parsers.cian_sold.importer import BATCH_SIZE  # reuse constant
    json_path = Path(json_path)
    if not json_path.is_file():
        logger.warning("Файл не найден: %s — пропускаю", json_path)
        return (0, 0)

    with json_path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        logger.error("Ожидался JSON-массив, получен %s", type(data).__name__)
        return (0, 0)

    houses: list[House] = []
    sold_ads: list[SoldAd] = []
    n_errors = 0
    total_h = 0
    total_s = 0

    for rec in data:
        if not isinstance(rec, dict):
            n_errors += 1
            continue
        try:
            h = _house_from_record(rec)
            if h is not None:
                houses.append(h)
            s = _sold_ad_from_record(rec)
            if s is not None:
                sold_ads.append(s)
        except Exception as exc:
            n_errors += 1
            logger.debug("ошибка записи (guid=%s): %s", rec.get("guid"), exc)

        if len(houses) >= BATCH_SIZE:
            total_h += await repo.upsert_houses_batch(houses)
            houses = []
        if len(sold_ads) >= BATCH_SIZE:
            total_s += await repo.upsert_sold_offers_batch(sold_ads)
            sold_ads = []

    if houses:
        total_h += await repo.upsert_houses_batch(houses)
    if sold_ads:
        total_s += await repo.upsert_sold_offers_batch(sold_ads)

    logger.info(
        "ИМПОРТ %s: домов=%s офферов=%s ошибок=%s",
        json_path.name, total_h, total_s, n_errors,
    )
    return (total_h, total_s)

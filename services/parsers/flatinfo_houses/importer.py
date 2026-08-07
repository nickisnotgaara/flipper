"""services.parsers.flatinfo_houses.importer - импорт house_pages_result.json в PostgreSQL.

Формат JSON (от house_pages_parser.py, реальные данные):
    [
      {
        "house_id": 12345,
        "address": "Москва, ул. Тверская, 1",
        "year": "1985",                    # строка
        "floors_text": "9 этажей",         # строка "N этажей"
        "house_type": "Панельный",         # или "material"/"building_type"
        "series": "П-44",
        "ceiling_height": "2.65 м",        # строка "N м"
        "okrug": "ЦАО",
        "rayon": "Тверской",               # или "district"
        "street": "...",
        "house_num": "...",
        ...
      },
      ...
    ]

Также поддерживает старый формат (для тестов):
    {"hid": 12345, "year_built": 1985, "levels": 9, "material": "панель", "district": "Тверской"}

Маппинг: 1 запись = 1 House. Sold_ads НЕ заполняется (только реестр домов).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from packages.flipper_db import (
    FlipperRepository,
    House,
    Source,
)
from services.parsers._common import safe_float, safe_int, safe_str

logger = logging.getLogger(__name__)

SOURCE = Source.FLATINFO_HOUSES.value

# Парсим "9 этажей" → 9, "2.65 м" → 2.65
_NUM_RE = re.compile(r"(\d+(?:[.,]\d+)?)")


def _parse_first_number(value: Any) -> int | float | None:
    """Извлечь первое число из строки. None если не нашёл."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    s = str(value).strip()
    if not s:
        return None
    m = _NUM_RE.search(s)
    if not m:
        return None
    raw = m.group(1).replace(",", ".")
    if "." in raw:
        try:
            return float(raw)
        except ValueError:
            return None
    try:
        return int(raw)
    except ValueError:
        return None


def _house_from_record(rec: dict[str, Any]) -> House | None:
    # ID: house_id (реальные данные) или hid/id (тесты/legacy)
    hid = rec.get("house_id") or rec.get("hid") or rec.get("id")
    if hid is None:
        return None

    # year: строка или число
    year_raw = rec.get("year_built") or rec.get("year")
    year = _parse_first_number(year_raw)
    year_int = int(year) if year is not None else None

    # levels: floors_text (string "N этажей") или levels/floors (число)
    levels_raw = rec.get("levels") or rec.get("floors") or rec.get("floors_text")
    levels = _parse_first_number(levels_raw)
    levels_int = int(levels) if levels is not None else None

    # ceiling_height: "N м" или число
    ceiling = _parse_first_number(rec.get("ceiling_height"))
    ceiling_float = float(ceiling) if ceiling is not None else None

    return House(
        source=SOURCE,
        external_house_id=str(hid),
        address=safe_str(rec.get("address")),
        street=safe_str(rec.get("street")),
        house_num=safe_str(rec.get("house_num")),
        # rayon (реальные данные) или district (legacy)
        district=safe_str(rec.get("district") or rec.get("rayon")),
        okrug=safe_str(rec.get("okrug")),
        year_built=year_int,
        levels=levels_int,
        # house_type (реальные) или material/building_type (legacy)
        building_type=safe_str(
            rec.get("house_type") or rec.get("material") or rec.get("building_type")
        ),
        series=safe_str(rec.get("series")),
        ceiling_height=ceiling_float,
        package=None,  # flatinfo не возвращает year/series в структурированном виде для классификации
        raw_data=rec,
    )


async def import_flatinfo_json(
    repo: FlipperRepository,
    json_path: str | Path,
) -> tuple[int, int]:
    """Импорт house_pages_result.json в PostgreSQL (только houses).

    Потоковый: загружает JSON, коммитит порциями по BATCH_SIZE.

    Returns:
        (n_houses, 0) — sold_ads не пишутся для flatinfo.
    """
    from services.parsers.cian_sold.importer import BATCH_SIZE  # reuse constant
    json_path = Path(json_path)
    if not json_path.is_file():
        logger.warning("Файл не найден: %s — пропускаю", json_path)
        return (0, 0)

    try:
        with json_path.open(encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        logger.error("Невалидный JSON в %s: %s — пропускаю", json_path, exc)
        return (0, 0)

    if not isinstance(data, list):
        logger.error("Ожидался JSON-массив, получен %s", type(data).__name__)
        return (0, 0)

    houses: list[House] = []
    n_errors = 0
    total_h = 0

    for rec in data:
        if not isinstance(rec, dict):
            n_errors += 1
            continue
        try:
            h = _house_from_record(rec)
            if h is not None:
                houses.append(h)
        except Exception as exc:
            n_errors += 1
            logger.debug("ошибка записи (hid=%s): %s", rec.get("hid"), exc)

        if len(houses) >= BATCH_SIZE:
            total_h += await repo.upsert_houses_batch(houses)
            houses = []

    if houses:
        total_h += await repo.upsert_houses_batch(houses)

    logger.info(
        "ИМПОРТ %s: домов=%s ошибок=%s (sold_ads не пишутся для flatinfo)",
        json_path.name, total_h, n_errors,
    )
    return (total_h, 0)

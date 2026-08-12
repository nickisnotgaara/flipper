"""scripts.migrate_server_parser_cian - read-only копирование
``services.parser_cian`` v1 (таблицы cian_filters/cian_active_ads/cian_sold_ads)
из **серверной** PostgreSQL в локальную новую схему
(``active_ads``/``sold_ads``) с source='cian_active'.

Назначение:
    Серверная БД (где крутится ``parser_cian`` v1) часто содержит более
    свежие данные, чем локальная. Этот скрипт переносит URL +
    сжатую экстракцию (parsed_data) в новую схему. Полный offerData (с photos,
    geo.coordinates) докачивается **отдельным** reparse-скриптом через
    flippercrawl → CianSource.

Что делает (в обычном режиме):
    1. ``DELETE FROM active_ads WHERE source='cian_active'`` (полная замена)
    2. Из серверной БД:
        cian_active_ads → active_ads   (source='cian_active', filter_id remap,
                                       raw_data = server.parsed_data — без маркеров)
        cian_sold_ads   → sold_ads     (source='cian_active', raw_data = server.parsed_data)
    3. Идемпотентен (upsert по (source, external_id) + ON CONFLICT).

Важно:
    Различение avans vs offers — по filter_id (=6 для avans) и
    raw_data->>'has_avans_deposit'. Отдельной колонки is_avans больше нет
    (её удалил cleanup_post_migration.py, мигратор её больше не добавляет).

**Важно:** скрипт НЕ модифицирует серверную БД (только SELECT, никаких
DDL/DML на server-коннекте). Локальная БД — изменяется (TRUNCATE +
upsert), как и другие миграторы в scripts/.

**Важно:** НЕ запускает parser_cian / cian_active (только импорт данных).
Re-parse через flippercrawl — отдельным шагом (см. scripts/reparse_cian_offerdata.py).

Использование:
    # 0. Read-only коннект к серверу через переменные окружения:
    #    SERVER_DATABASE_URL — asyncpg DSN для серверной БД (read-only).
    #    DATABASE_URL — URL локальной БД (куда импортируем).
    set SERVER_DATABASE_URL=postgresql://root:SECRET@server-host:5432/flipper
    set DATABASE_URL=postgresql+asyncpg://flipper:flipper_secret@app_postgres:5432/flipper

    # 1. Dry-run (по умолчанию): показать что есть на сервере, без записи:
    py -3.11 -m scripts.migrate_server_parser_cian

    # 2. Реальный импорт (TRUNCATE + upsert в локальную БД):
    py -3.11 -m scripts.migrate_server_parser_cian --no-dry-run

    # 3. Импорт + dry-run (для отладки — выводит sample + summary):
    py -3.11 -m scripts.migrate_server_parser_cian --sample-size 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from packages.flipper_db import ActiveAd, FlipperRepository, SoldAd, init_db, init_engine
from packages.flipper_db.enums import Source

logger = logging.getLogger("migrate_server_cian")

BATCH_SIZE = 1000
SOURCE_CIAN_ACTIVE = Source.CIAN_ACTIVE.value  # "cian_active"


# ============================================================== URL helpers


def _default_server_url() -> str:
    """``SERVER_DATABASE_URL`` (sync, для asyncpg) или пустая строка.

    URL должен быть **без** ``+asyncpg`` — asyncpg принимает обычный
    ``postgresql://``. Пароль в URL нужно URL-кодировать (если содержит
    спецсимволы). Скрипт сам не кодирует — кодируй на стороне caller'а.
    """
    return os.getenv("SERVER_DATABASE_URL", "")


def _default_local_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://flipper:flipper_secret@app_postgres:5432/flipper",
    )


def _validate_server_url(url: str) -> str:
    """Проверить что URL похож на asyncpg DSN; непустой, postgres scheme."""
    if not url:
        raise ValueError(
            "SERVER_DATABASE_URL не задан. Укажи его через env или --server-url.\n"
            "Пример: postgresql://root:ENCODED_PWD@72.56.33.73:5432/flipper"
        )
    parsed = urlparse(url)
    if not parsed.scheme.startswith("postgres"):
        raise ValueError(f"Не postgres URL: {url!r}")
    if not parsed.hostname:
        raise ValueError(f"Нет host в URL: {url!r}")
    return url


# ============================================================== parsers


def _parse_json(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return {}


def _parse_date(s: Any) -> Optional[date]:
    if not s:
        return None
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if isinstance(s, datetime):
        return s.date()
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt.date()
    except (ValueError, TypeError):
        return None


def _parse_dt(s: Any) -> Optional[datetime]:
    if not s:
        return None
    if isinstance(s, datetime):
        return s
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except (ValueError, TypeError):
        return None


def _is_valid_cian_id(value: Any) -> bool:
    if value is None:
        return False
    s = str(value).strip()
    if not s or s.lower() in ("null", "none", "nan"):
        return False
    return True


def _extract_cian_id_from_url(url: str) -> Optional[str]:
    """https://www.cian.ru/sale/flat/12345/ → '12345'."""
    if not url:
        return None
    m = re.search(r"/flat/(\d+)/?", url)
    return m.group(1) if m else None


# ============================================================== filter_id mapping
#
# Server cian_filters использует ID 406, 481, 482, 483, 485, 486.
# Локальная архитектура ждёт ID 1-6 (1-4=offers, 5=signals, 6=avans).
# Подтверждено сверкой URL'ов обеих БД (одинаковые search-параметры):
#
#   SERVER  LOCAL  min_house_year  max_house_year  district      context
#   481     1      -               2000            23-132        -
#   482     2      2000            -               23-132        -
#   483     3      -               2000            13-22         -
#   406     4      2000            -               13-22         -
#   485     5      -               -               -             опека
#   486     6      -               -               -             Т-банк|запрет долги
#   None    None   (avans или аномалия)

SERVER_TO_LOCAL_FILTER_ID: dict[Optional[int], Optional[int]] = {
    481: 1,  # offers: max_year=2000, dists=23-132
    482: 2,  # offers: min_year=2000, dists=23-132
    483: 3,  # offers: max_year=2000, dists=13-22
    406: 4,  # offers: min_year=2000, dists=13-22
    485: 5,  # signals (опека)
    486: 6,  # avans (Т-банк | запрет долги)
}


def _remap_filter_id(server_filter_id: Optional[int]) -> Optional[int]:
    """server cian_filters.id → local active_ads.filter_id (1..6) или None."""
    if server_filter_id is None:
        return None
    return SERVER_TO_LOCAL_FILTER_ID.get(int(server_filter_id), None)


# ============================================================== record mapping


def _active_ad_from_server_row(
    row: dict[str, Any],
) -> Optional[ActiveAd]:
    """``cian_active_ads`` (server) → ``ActiveAd`` (local).

    Серверный ``parsed_data`` — это сжатый JSON-блоб экстракции,
    не полный offerData. ``raw_data`` оставляем как есть (для последующего
    re-parse через flippercrawl).
    """
    url = row.get("url")
    if not url:
        return None
    parsed = _parse_json(row.get("parsed_data"))
    if not parsed:
        # parsed_data пустое — ad не был спарсен. Не импортируем.
        return None

    cian_id = parsed.get("cian_id")
    if not _is_valid_cian_id(cian_id):
        cian_id = _extract_cian_id_from_url(url)
    if not _is_valid_cian_id(cian_id):
        return None

    cian_house_id = parsed.get("house_id") or parsed.get("cian_house_id")
    if cian_house_id is not None:
        try:
            cian_house_id = int(cian_house_id)
        except (TypeError, ValueError):
            cian_house_id = None

    is_active_raw = parsed.get("is_active")
    is_active = True if is_active_raw is None else bool(is_active_raw)

    floor_info = parsed.get("floor_info") or {}
    if not isinstance(floor_info, dict):
        floor_info = {}

    address = parsed.get("address")
    if not isinstance(address, dict):
        address = {}

    server_source = (row.get("source") or "offers").strip()
    is_avans = (server_source == "avans")
    # Avans без filter_id → локальный filter_id=6 (avans)
    # Offers с filter_id → remap 481/482/483/406/485/486 → 1/2/3/4/5/6
    if is_avans:
        local_filter_id: Optional[int] = 6
    else:
        local_filter_id = _remap_filter_id(row.get("filter_id"))

    # raw_data: server.parsed_data как есть (без наших маркеров).
    # Re-parse через flippercrawl потом затрёт raw_data целиком и запишет туда
    # полный offerData. При синке обратно на сервер маркеры не нужны.
    # Различение avans vs offers — по filter_id (=6 для avans) и по
    # raw_data->>'has_avans_deposit' (=true для avans).
    return ActiveAd(
        source=SOURCE_CIAN_ACTIVE,
        external_id=str(cian_id),
        url=url,
        house_id=None,  # FK на houses — проставится linker'ом после re-parse
        cian_house_id=cian_house_id,
        price=parsed.get("price"),
        price_per_m2=parsed.get("price_per_m2"),
        area=parsed.get("area"),
        rooms=parsed.get("rooms"),
        floor_current=floor_info.get("current"),
        floor_total=floor_info.get("all"),
        metro_station=_truncate_str(
            address.get("metro_station") or parsed.get("metro_station"), 128
        ),
        metro_walk_time=parsed.get("metro_walk_time"),
        district=_truncate_str(
            address.get("district") or parsed.get("district"), 128
        ),
        okrug=_truncate_str(
            address.get("okrug") or parsed.get("okrug"), 128
        ),
        renovation=_truncate_str(parsed.get("renovation"), 64),
        is_active=is_active,
        days_in_exposition=parsed.get("days_in_exposition"),
        total_views=parsed.get("total_views"),
        unique_views=parsed.get("unique_views"),
        publish_date=_parse_date(parsed.get("publish_date")),
        filter_id=local_filter_id,
        price_history=parsed.get("price_history"),
        raw_data=parsed,
    )


def _truncate_str(value: Any, max_len: int) -> Optional[str]:
    """Truncate string to ``max_len`` chars (PostgreSQL varchar limit).
    None stays None. Non-strings converted to str. Полный текст остаётся в raw_data.
    """
    if value is None:
        return None
    s = str(value)
    if len(s) <= max_len:
        return s
    return s[:max_len]


def _sold_ad_from_server_row(
    row: dict[str, Any],
) -> Optional[SoldAd]:
    """``cian_sold_ads`` (server) → ``SoldAd`` (local)."""
    url = row.get("url")
    if not url:
        return None
    parsed = _parse_json(row.get("parsed_data"))
    if not parsed:
        return None

    cian_id = parsed.get("cian_id")
    if not _is_valid_cian_id(cian_id):
        cian_id = _extract_cian_id_from_url(url)
    if not _is_valid_cian_id(cian_id):
        return None

    cian_house_id = parsed.get("house_id") or parsed.get("cian_house_id")
    if cian_house_id is not None:
        try:
            cian_house_id = int(cian_house_id)
        except (TypeError, ValueError):
            cian_house_id = None

    floor_info = parsed.get("floor_info") or {}
    if not isinstance(floor_info, dict):
        floor_info = {}

    return SoldAd(
        source=SOURCE_CIAN_ACTIVE,
        external_id=str(cian_id),
        url=url,
        house_id=None,
        cian_house_id=cian_house_id,
        price=parsed.get("price"),
        price_per_m2=parsed.get("price_per_m2"),
        area=parsed.get("area"),
        rooms=parsed.get("rooms"),
        floor_current=floor_info.get("current"),
        floor_total=floor_info.get("all"),
        # renovation: VARCHAR(64). На сервере изредка попадает полное предложение
        # (description). Truncate до 64 — полный текст остаётся в raw_data.
        renovation=_truncate_str(parsed.get("renovation"), 64),
        exposition_days=parsed.get("days_in_exposition"),
        publish_date=_parse_date(parsed.get("publish_date")),
        sold_date=_parse_date(row.get("sold_at") or parsed.get("sold_at")),
        raw_data=parsed,
    )


# ============================================================== server I/O (READ-ONLY)


async def _fetch_server_rows(
    server_url: str, table: str, columns: list[str]
) -> list[dict[str, Any]]:
    """Читаем ВСЕ строки из серверной таблицы. Только SELECT. Никаких DML.

    Используем чистый asyncpg (не SQLAlchemy) — минимальный API, явный
    контроль над запросами (чтобы случайно не сделать UPDATE/DELETE).
    """
    cols_sql = ", ".join(f'"{c}"' for c in columns)
    query = f'SELECT {cols_sql} FROM "{table}"'

    logger.info("Подключаюсь к серверу (READ-ONLY): %s ...", server_url.split("@")[-1])
    conn = await asyncpg.connect(server_url)
    try:
        rows = await conn.fetch(query)
        logger.info("  -> %s: прочитано %d строк", table, len(rows))
    finally:
        await conn.close()

    return [dict(r) for r in rows]


def _columns_active() -> list[str]:
    return [
        "id",
        "url",
        "filter_id",
        "source",
        "parsed_data",
        "is_parsed",
        "last_updated",
        "added_at",
    ]


def _columns_sold() -> list[str]:
    return ["id", "url", "parsed_data", "publish_date", "sold_at"]


# ============================================================== local DDL (idempotent)
#
# Раньше тут была ``_ensure_is_avans_column`` (CREATE COLUMN is_avans BOOL).
# Удалена: различение avans vs offers — по filter_id (=6 для avans) и
# raw_data->>'has_avans_deposit'. Никаких отдельных колонок не нужно.


async def _truncate_local_active_ads(local_url: str) -> int:
    """TRUNCATE active_ads WHERE source='cian_active'. Возвращает сколько удалено."""
    engine = create_async_engine(local_url)
    try:
        async with engine.begin() as conn:
            res = await conn.execute(
                text("DELETE FROM active_ads WHERE source = :src"),
                {"src": SOURCE_CIAN_ACTIVE},
            )
            removed = res.rowcount or 0
        return int(removed)
    finally:
        await engine.dispose()


# ============================================================== dry-run preview


def _print_sample(rows: list[dict[str, Any]], label: str, n: int = 3) -> None:
    print(f"\n--- SAMPLE: {label} (первые {n}) ---")
    for i, r in enumerate(rows[:n], 1):
        parsed = _parse_json(r.get("parsed_data"))
        cian_id = parsed.get("cian_id") or _extract_cian_id_from_url(r.get("url") or "")
        src = (r.get("source") or "offers") or "offers"
        if src == "avans":
            local_fid_s = "6 (avans)"
        else:
            local_fid = _remap_filter_id(r.get("filter_id"))
            local_fid_s = f"{local_fid} (remap from {r.get('filter_id')})" if local_fid else f"None (server {r.get('filter_id')})"
        print(
            f"  [{i}] cian_id={cian_id!s:>12}  "
            f"local_fid={local_fid_s:<32}  "
            f"source={src!r:>8}  "
            f"price={parsed.get('price')!s:>11}  "
            f"area={parsed.get('area')!s:>5}  "
            f"is_active={parsed.get('is_active')}"
        )
        print(f"      url={r.get('url')}")


def _print_stats(
    active_rows: list[dict[str, Any]],
    sold_rows: list[dict[str, Any]],
) -> None:
    by_source: dict[str, int] = {}
    by_filter: dict[tuple[Optional[int], Optional[str]], int] = {}
    by_local_filter: dict[Optional[int], int] = {}  # post-remap
    is_active_counts = {"True": 0, "False": 0, "None": 0, "no_parsed": 0}
    valid_active = 0
    invalid_active = 0

    for r in active_rows:
        src = (r.get("source") or "offers") or "offers"
        by_source[src] = by_source.get(src, 0) + 1
        key = (r.get("filter_id"), src)
        by_filter[key] = by_filter.get(key, 0) + 1

        # Apply remap (avans → 6, offers 481/482/483/406/485/486 → 1-6, None → None)
        if src == "avans":
            local_fid: Optional[int] = 6
        else:
            local_fid = _remap_filter_id(r.get("filter_id"))
        by_local_filter[local_fid] = by_local_filter.get(local_fid, 0) + 1

        parsed = _parse_json(r.get("parsed_data"))
        if not parsed:
            is_active_counts["no_parsed"] += 1
            invalid_active += 1
            continue
        valid_active += 1
        ia = parsed.get("is_active")
        if ia is True:
            is_active_counts["True"] += 1
        elif ia is False:
            is_active_counts["False"] += 1
        else:
            is_active_counts["None"] += 1

    print("\n========== SERVER STATS (READ-ONLY) ==========")
    print(f"\ncian_active_ads:  {len(active_rows)} строк")
    print(f"  valid (parsed_data непустое):     {valid_active}")
    print(f"  invalid (parsed_data пустое):     {invalid_active}  ← будет пропущено")
    print(f"  is_active:  True={is_active_counts['True']}  "
          f"False={is_active_counts['False']}  None={is_active_counts['None']}")
    print(f"\n  по source/server_filter_id:")
    for (fid, src), cnt in sorted(by_filter.items(), key=lambda x: (x[0][1] or "", x[0][0] or 0)):
        print(f"    source={src!r:>10}  server_filter_id={fid!s:>4}  count={cnt}")
    print(f"\n  по local filter_id (POST-REMAP):")
    for fid, cnt in sorted(by_local_filter.items(), key=lambda x: (x[0] is None, x[0] or 0)):
        label = {
            1: "1 (offers, max_year=2000, dists=23-132)",
            2: "2 (offers, min_year=2000, dists=23-132)",
            3: "3 (offers, max_year=2000, dists=13-22)",
            4: "4 (offers, min_year=2000, dists=13-22)",
            5: "5 (signals, опека)",
            6: "6 (avans, Т-банк|запрет долги)",
        }.get(fid, "None (без фильтра)")
        print(f"    filter_id={fid!s:>5}  count={cnt:>5}  {label}")

    print(f"\ncian_sold_ads:    {len(sold_rows)} строк")
    valid_sold = sum(1 for r in sold_rows if _parse_json(r.get("parsed_data")))
    print(f"  valid: {valid_sold}  invalid: {len(sold_rows) - valid_sold}")

    print("\n========== LOCAL BEFORE (read-only SELECT) ==========")
    # Этот блок выполняется через repo ниже — тут только метка.


# ============================================================== main


async def run(
    server_url: str,
    local_url: str,
    *,
    dry_run: bool,
    sample_size: int = 3,
) -> int:
    server_url = _validate_server_url(server_url)

    # 1. Читаем сервер (READ-ONLY)
    active_rows = await _fetch_server_rows(server_url, "cian_active_ads", _columns_active())
    sold_rows = await _fetch_server_rows(server_url, "cian_sold_ads", _columns_sold())

    _print_stats(active_rows, sold_rows)
    if sample_size > 0:
        _print_sample(active_rows, "cian_active_ads", sample_size)
        _print_sample(sold_rows, "cian_sold_ads", sample_size)

    # 2. Локальная БД — проверяем текущее состояние
    from packages.flipper_db import base as _fb

    init_engine(local_url)
    local_engine = create_async_engine(local_url)
    try:
        async with local_engine.connect() as conn:
            local_active = (
                await conn.execute(
                    text("SELECT COUNT(*) FROM active_ads WHERE source = :s"),
                    {"s": SOURCE_CIAN_ACTIVE},
                )
            ).scalar() or 0
            local_sold = (
                await conn.execute(
                    text("SELECT COUNT(*) FROM sold_ads WHERE source = :s"),
                    {"s": SOURCE_CIAN_ACTIVE},
                )
            ).scalar() or 0
            local_houses = (
                await conn.execute(text("SELECT COUNT(*) FROM houses"))
            ).scalar() or 0
    finally:
        await local_engine.dispose()

    print("\n========== LOCAL BEFORE (current) ==========")
    print(f"  active_ads (source='cian_active'): {local_active}")
    print(f"  sold_ads   (source='cian_active'): {local_sold}")
    print(f"  houses (all sources):              {local_houses}")

    if dry_run:
        print("\n[DRY-RUN] Запись НЕ выполняется. Без флага --no-dry-run ничего не меняется.")
        print("[DRY-RUN] Чтобы выполнить реальный импорт:")
        print("          py -3.11 -m scripts.migrate_server_parser_cian --no-dry-run")
        return 0

    # 3. Реальный импорт
    print("\n========== MIGRATION (REAL) ==========")

    # 3.1 TRUNCATE local active_ads WHERE source='cian_active'
    print(f"Шаг 1/2: DELETE FROM active_ads WHERE source='{SOURCE_CIAN_ACTIVE}' ...")
    removed = await _truncate_local_active_ads(local_url)
    print(f"  -> удалено {removed} записей")

    # 3.2 Конвертируем и upsert
    print("Шаг 2/2: upsert active_ads и sold_ads ...")
    init_db(local_url)
    repo = FlipperRepository()  # переинициализируем после schema check

    active_ads: list[ActiveAd] = []
    skipped_active = 0
    for r in active_rows:
        a = _active_ad_from_server_row(r)
        if a is None:
            skipped_active += 1
        else:
            active_ads.append(a)

    sold_ads: list[SoldAd] = []
    skipped_sold = 0
    for r in sold_rows:
        s = _sold_ad_from_server_row(r)
        if s is None:
            skipped_sold += 1
        else:
            sold_ads.append(s)

    total_a = 0
    for i in range(0, len(active_ads), BATCH_SIZE):
        chunk = active_ads[i : i + BATCH_SIZE]
        # Dedupe by external_id within batch (ON CONFLICT не сработает на дубль)
        seen: set[str] = set()
        deduped: list[ActiveAd] = []
        for a in chunk:
            if a.external_id in seen:
                continue
            seen.add(a.external_id)
            deduped.append(a)
        n = await repo.upsert_active_ads_batch(deduped)
        total_a += n
        if total_a % (BATCH_SIZE * 5) == 0 or i + BATCH_SIZE >= len(active_ads):
            print(f"  active_ads: {total_a}/{len(active_ads)}")

    total_s = 0
    for i in range(0, len(sold_ads), BATCH_SIZE):
        chunk = sold_ads[i : i + BATCH_SIZE]
        seen = set()
        deduped = []
        for s in chunk:
            if s.external_id in seen:
                continue
            seen.add(s.external_id)
            deduped.append(s)
        n = await repo.upsert_sold_offers_batch(deduped)
        total_s += n
        if total_s % (BATCH_SIZE * 5) == 0 or i + BATCH_SIZE >= len(sold_ads):
            print(f"  sold_ads:   {total_s}/{len(sold_ads)}")

    print("\n========== MIGRATION OK ==========")
    print(f"  active_ads upserted: {total_a}  (skipped invalid: {skipped_active})")
    print(f"  sold_ads upserted:   {total_s}  (skipped invalid: {skipped_sold})")
    print()
    print("Следующий шаг: re-parse через flippercrawl (scripts/reparse_cian_offerdata.py)")
    print("  Это докачает полный offerData (photos, geo.coordinates, building.*) в active_ads.raw_data")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only копирование parser_cian v1 (server) → flipper_db v2 (local). "
            "Dry-run по умолчанию."
        )
    )
    parser.add_argument(
        "--server-url",
        default=_default_server_url(),
        help="SERVER_DATABASE_URL (asyncpg DSN, read-only). Default: $SERVER_DATABASE_URL",
    )
    parser.add_argument(
        "--local-url",
        default=_default_local_url(),
        help="DATABASE_URL локальной БД. Default: $DATABASE_URL",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="Реальный импорт (TRUNCATE + upsert). По умолчанию — dry-run.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=3,
        help="Сколько sample-строк печатать (0 = выкл). Default: 3",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG-уровень")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    return asyncio.run(
        run(
            args.server_url,
            args.local_url,
            dry_run=not args.no_dry_run,
            sample_size=args.sample_size,
        )
    )


if __name__ == "__main__":
    sys.exit(main())

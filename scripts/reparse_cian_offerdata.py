"""scripts.reparse_cian_offerdata - backfill полного offerData через flippercrawl.

Назначение:
    После migrate_server_parser_cian.py в active_ads.raw_data лежит
    сжатая экстракция (без photos, без geo.coordinates, без building.* в полном
    виде). Этот скрипт перепарсит каждое объявление через flippercrawl и
    заменит raw_data на полный state.offerData (с photos, lat/lng, building,
    agent, breadcrumbs, etc.).

Что делает:
    1. SELECT external_id FROM active_ads
       WHERE source='cian_active' AND raw_data->>'offer' IS NULL
       (т.е. ещё не перепарсено)
    2. Для каждого: POST /v2/cian/scrape → parse через CianSource → upsert
       active_ads.raw_data = полный offerData
    3. Идемпотентен: повторный запуск skip'ает уже перепарсенные
    4. Прерываемый: Ctrl+C — текущий in-flight ad дообрабатывается, новые не стартуют
    5. Параллельный: --concurrency (default 8)

Идемпотентность:
    Условие фильтра: raw_data->>'offer' IS NULL.
    После успешного reparse raw_data становится полным offerData → ключ 'offer'
    присутствует → на следующем запуске ad skip'ается.

Параметры:
    --limit N         : обработать только первые N (smoke test)
    --concurrency N   : параллельных запросов (default 8)
    --ids a,b,c       : только эти external_id (ручной smoke)

Использование:
    # Smoke (10 ids)
    py -3.11 -m scripts.reparse_cian_offerdata --limit 10

    # Full (все ~5 227)
    py -3.11 -m scripts.reparse_cian_offerdata

    # Прервать и продолжить позже (Ctrl+C) — ничего не теряется,
    # обработанные ads уже имеют raw_data->>'offer'
    py -3.11 -m scripts.reparse_cian_offerdata

    # Конкретные ids (после ручной проверки)
    py -3.11 -m scripts.reparse_cian_offerdata --ids 331354235,330424995
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from packages.flipper_db.sources.cian import CianSource
from packages.flipper_db.cian_state import extract_offer_data

logger = logging.getLogger("reparse_cian")


def _default_local_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://flipper:flipper_secret@app_postgres:5432/flipper",
    )


def _default_flippercrawl_url() -> str:
    return os.getenv(
        "FLIPPERCRAWL_URL",
        "http://127.0.0.1:3002/v2/cian/scrape",
    )


def _to_asyncpg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


_SHUTDOWN = asyncio.Event()


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """Ctrl+C → set shutdown event (in-flight ads дообрабатываются)."""
    def _on_signal() -> None:
        logger.warning("SIGINT/SIGTERM: graceful shutdown requested ...")
        _SHUTDOWN.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except (NotImplementedError, RuntimeError):
            # Windows / нет event loop
            pass


async def _fetch_ad_ids(
    local_url: str,
    limit: Optional[int],
    only_ids: Optional[list[str]],
) -> list[str]:
    """SELECT external_id из active_ads которые ещё не перепарсены."""
    dsn = _to_asyncpg_dsn(local_url)
    conn = await asyncpg.connect(dsn)
    try:
        if only_ids:
            # Ручной список — НЕ фильтруем по offer (хотим принудительно)
            sql = """
                SELECT external_id FROM active_ads
                WHERE source='cian_active' AND external_id = ANY($1::text[])
                ORDER BY id
            """
            rows = await conn.fetch(sql, only_ids)
        else:
            sql = """
                SELECT external_id FROM active_ads
                WHERE source='cian_active' AND raw_data->>'offer' IS NULL
                ORDER BY id
            """
            if limit:
                sql += f" LIMIT {int(limit)}"
            rows = await conn.fetch(sql)
        return [r["external_id"] for r in rows]
    finally:
        await conn.close()


async def _update_raw_data(local_url: str, external_id: str, raw_data: dict) -> int:
    """UPDATE active_ads.raw_data для одного ad. Без нормализации полей — только raw_data."""
    dsn = _to_asyncpg_dsn(local_url)
    conn = await asyncpg.connect(dsn)
    try:
        new_raw = json.dumps(raw_data, ensure_ascii=False)
        res = await conn.execute(
            """
            UPDATE active_ads
            SET raw_data = $1::json
            WHERE source='cian_active' AND external_id=$2
            """,
            new_raw,
            external_id,
        )
        return int(res.split()[-1] or 0)  # "UPDATE n"
    finally:
        await conn.close()


def _build_offer_record(source: CianSource, response_json: str) -> Optional[dict]:
    """Парсит ответ flippercrawl → dict (raw_data) или None.

    Логика как в CianSource.parse_ad:
    1. data.json.rawOfferData (static extract, hot path)
    2. fallback: data.rawHtml → cian_state.extract_offer_data
    """
    try:
        response = json.loads(response_json)
    except (ValueError, TypeError):
        return None
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        return None
    json_block = data.get("json") or {}
    if not isinstance(json_block, dict):
        json_block = {}
    raw_html = data.get("rawHtml") or ""

    raw_offer = json_block.get("rawOfferData")
    if not raw_offer and raw_html:
        raw_offer = extract_offer_data(raw_html)

    if not raw_offer or not isinstance(raw_offer, dict):
        return None
    if not raw_offer.get("offer", {}).get("id"):
        return None

    # Метка extraction mode для observability
    mode = "static" if json_block.get("rawOfferData") else "llm"
    if "_extraction_mode" not in raw_offer:
        raw_offer["_extraction_mode"] = mode
    return raw_offer


async def _process_one(
    source: CianSource,
    local_url: str,
    external_id: str,
    stats: dict,
) -> None:
    """Один ad: fetch + parse + update."""
    if _SHUTDOWN.is_set():
        return
    try:
        response_json = await source.fetch_ad_page(external_id)
    except Exception as e:
        stats["fetch_failed"] += 1
        logger.warning("fetch EXCEPTION %s: %s: %s", external_id, type(e).__name__, e)
        return

    if response_json is None:
        # 404 / network / timeout → CianSource вернул None. Не апдейтим.
        stats["fetch_none"] += 1
        logger.info("fetch returned None (404/timeout?) %s", external_id)
        return

    raw_offer = _build_offer_record(source, response_json)
    if raw_offer is None:
        stats["parse_failed"] += 1
        logger.warning("parse failed %s (no offerData in response)", external_id)
        return

    # Update raw_data
    try:
        n = await _update_raw_data(local_url, external_id, raw_offer)
        if n > 0:
            stats["updated"] += 1
        else:
            stats["update_noop"] += 1
    except Exception as e:
        stats["update_failed"] += 1
        logger.warning("update EXCEPTION %s: %s: %s", external_id, type(e).__name__, e)


async def run(
    local_url: str,
    flippercrawl_url: str,
    limit: Optional[int],
    only_ids: Optional[list[str]],
    concurrency: int,
) -> int:
    _install_signal_handlers(asyncio.get_event_loop())

    logger.info("== reparse_cian_offerdata START ==")
    logger.info("  local_url:    ...@%s", local_url.split("@")[-1])
    logger.info("  flippercrawl: %s", flippercrawl_url)
    logger.info("  limit:        %s", limit)
    logger.info("  only_ids:     %s", only_ids or "—")
    logger.info("  concurrency:  %s", concurrency)

    # 1. Получить список ids
    logger.info("Шаг 1/3: SELECT external_id (где raw_data->>'offer' IS NULL) ...")
    ad_ids = await _fetch_ad_ids(local_url, limit, only_ids)
    logger.info("  -> %s ids to process", len(ad_ids))
    if not ad_ids:
        logger.info("Нечего парсить. Выход.")
        return 0

    # 2. Инициализировать CianSource (его semaphore держит concurrency)
    # timeout=120s: под нагрузкой (8 параллельных) flippercrawl иногда не
    # укладывается в дефолтные 30 сек. 120 сек — мягкий запас.
    source = CianSource(
        flippercrawl_url=flippercrawl_url,
        max_concurrent=concurrency,
        timeout=120.0,
    )

    # 3. Параллельная обработка
    logger.info("Шаг 2/3: re-parse %s ads (concurrency=%s) ...", len(ad_ids), concurrency)
    stats = {
        "updated": 0,
        "update_noop": 0,
        "update_failed": 0,
        "fetch_failed": 0,
        "fetch_none": 0,
        "parse_failed": 0,
    }
    started = time.monotonic()
    sem = asyncio.Semaphore(concurrency)

    async def _worker(ext_id: str) -> None:
        async with sem:
            if _SHUTDOWN.is_set():
                return
            await _process_one(source, local_url, ext_id, stats)

    tasks = [asyncio.create_task(_worker(eid)) for eid in ad_ids]
    last_log_pct = 0
    try:
        done = 0
        for fut in asyncio.as_completed(tasks):
            try:
                await fut
            except Exception as e:
                logger.error("Worker exception: %s", e)
            done += 1
            total = len(ad_ids)
            pct = int(done * 100 / total)
            if pct >= last_log_pct + 5:
                last_log_pct = pct
                logger.info(
                    "  [%s%%] %s/%s  updated=%s failed=%s",
                    pct, done, total,
                    stats["updated"],
                    stats["update_failed"] + stats["fetch_failed"] + stats["parse_failed"],
                )
            if _SHUTDOWN.is_set() and done % 50 == 0:
                # на сигнал остановить dispatch новых, но дать текущим finish
                pass
    finally:
        # cancel pending если shutdown
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    elapsed = time.monotonic() - started
    logger.info("Шаг 3/3: DONE (%.1fs)", elapsed)
    logger.info("  updated:         %s", stats["updated"])
    logger.info("  update_noop:    %s", stats["update_noop"])
    logger.info("  update_failed:  %s", stats["update_failed"])
    logger.info("  fetch_failed:   %s", stats["fetch_failed"])
    logger.info("  fetch_none:     %s", stats["fetch_none"])
    logger.info("  parse_failed:   %s", stats["parse_failed"])

    if _SHUTDOWN.is_set():
        logger.warning("Прервано пользователем. Уже перепарсенные ads имеют raw_data->>'offer'.")
        logger.warning("Следующий запуск продолжит с того же места (resumable).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--local-url", default=_default_local_url())
    parser.add_argument("--flippercrawl-url", default=_default_flippercrawl_url())
    parser.add_argument("--limit", type=int, default=None,
                        help="Обработать только первые N (smoke)")
    parser.add_argument("--concurrency", type=int, default=8,
                        help="Параллельных запросов к flippercrawl (default 8)")
    parser.add_argument("--ids", default=None,
                        help="Ручной список external_id через запятую (force reparse, "
                             "игнорирует фильтр offer IS NULL)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    only_ids = None
    if args.ids:
        only_ids = [s.strip() for s in args.ids.split(",") if s.strip()]

    return asyncio.run(run(
        args.local_url,
        args.flippercrawl_url,
        args.limit,
        only_ids,
        args.concurrency,
    ))


if __name__ == "__main__":
    sys.exit(main())

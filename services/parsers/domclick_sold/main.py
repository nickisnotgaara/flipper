"""services.parsers.domclick_sold.main - оркестратор v2 (тонкий wrapper).

Этот main.py — entry point для Docker-контейнера domclick_sold.
Внутри делегирует всю работу в v2-инфраструктуру:

  * list    -> services/parsers/domclick_sold/acquirer.py (сбор ссылок BFF)
  * pipeline -> packages/flipper_db.pipeline.run_source_pipeline (parse + DB)
  * backfill -> run_source_pipeline + --fetch-missing (re-парс всех)
  * full    -> list + pipeline (полный цикл)

Никаких JSON-файлов как output. Всё пишется сразу в БД PostgreSQL.

Google Sheets / .xlsx НЕ используются (по решению пользователя — отказались
от экспорта в Google Таблицы для domclick).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
LINKS_JSON = THIS_DIR / "domclick_links.json"
PROJECT_ROOT = THIS_DIR.parent.parent.parent  # flipper/

# Добавим корень в PYTHONPATH для импорта packages
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("domclick_sold")


def _run_acquirer(logger: logging.Logger) -> None:
    """Запускает acquirer.py: BFF API -> domclick_links.json"""
    acquirer = THIS_DIR / "acquirer.py"
    if not acquirer.is_file():
        logger.error("acquirer.py не найден: %s", acquirer)
        raise SystemExit(1)
    logger.info("Запускаю acquirer.py (BFF list)...")
    rc = subprocess.call([sys.executable, str(acquirer)], cwd=str(THIS_DIR))
    if rc != 0:
        logger.error("acquirer.py упал с rc=%s", rc)
        raise SystemExit(rc)
    if not LINKS_JSON.is_file():
        logger.error("acquirer.py не создал %s", LINKS_JSON)
        raise SystemExit(1)


def _load_ids_from_links(logger: logging.Logger) -> list[str]:
    """Читает external_id'шники из domclick_links.json."""
    if not LINKS_JSON.is_file():
        raise SystemExit(
            f"{LINKS_JSON} не найден. Сначала запустите --mode list или --mode full."
        )
    doc = json.loads(LINKS_JSON.read_text(encoding="utf-8"))
    items = doc.get("items") if isinstance(doc, dict) else None
    if not isinstance(items, list):
        raise SystemExit(f"Некорректный формат {LINKS_JSON}: ожидался 'items' list")
    ids: list[str] = []
    for it in items:
        if isinstance(it, dict):
            oid = it.get("id")
            if oid is not None:
                ids.append(str(oid))
    logger.info("Загружено %s id из %s", len(ids), LINKS_JSON)
    return ids


async def _run_pipeline(ids: list[str], logger: logging.Logger, **kwargs) -> int:
    """Запускает run_source_pipeline для списка ids."""
    if not ids:
        logger.info("Пустой список id — нечего делать")
        return 0
    from packages.flipper_db import DomclickSource, run_source_pipeline
    source = DomclickSource()
    result = await run_source_pipeline(source, ids, **kwargs)
    logger.info("Pipeline result: %s", result)
    return 0


async def _fetch_missing_ids_from_db(logger: logging.Logger) -> list[str]:
    """Для --mode backfill: SELECT external_id FROM sold_ads WHERE source='domclick_sold'."""
    import asyncpg
    from packages.flipper_db.base import DEFAULT_DATABASE_URL
    dsn = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    logger.info("Читаю все external_id из sold_ads для source=domclick_sold...")
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT external_id FROM sold_ads WHERE source='domclick_sold' ORDER BY external_id"
        )
    finally:
        await conn.close()
    return [r["external_id"] for r in rows]


async def main_async(args: argparse.Namespace) -> int:
    logger = setup_logging()
    logger.info("===== domclick_sold v2 START (mode=%s) =====", args.mode)

    pipeline_kwargs = dict(
        auto_create_houses=not args.no_create_houses,
        cleanup_stale=False,  # sold-only источник — cleanup_stale не нужен
        link_after=not args.no_link,
    )

    if args.mode == "list":
        # Только сбор списка (BFF -> domclick_links.json), pipeline не запускаем
        _run_acquirer(logger)
        logger.info("===== domclick_sold v2 END (list done) =====")
        return 0

    if args.mode == "pipeline":
        # Только pipeline по domclick_links.json
        ids = _load_ids_from_links(logger)
        await _run_pipeline(ids, logger, **pipeline_kwargs)
        logger.info("===== domclick_sold v2 END (pipeline done) =====")
        return 0

    if args.mode == "backfill":
        # Backfill: ВСЕ sold_ads где source='domclick_sold' -> pipeline
        ids = await _fetch_missing_ids_from_db(logger)
        logger.info("Backfill: %s ad", len(ids))
        if args.limit > 0:
            ids = ids[args.limit:]
        if args.offset > 0:
            ids = ids[args.offset:]
        if args.limit > 0:
            ids = ids[:args.limit]
        await _run_pipeline(ids, logger, **pipeline_kwargs)
        logger.info("===== domclick_sold v2 END (backfill done) =====")
        return 0

    if args.mode == "full":
        # list -> pipeline (полный цикл)
        _run_acquirer(logger)
        ids = _load_ids_from_links(logger)
        await _run_pipeline(ids, logger, **pipeline_kwargs)
        logger.info("===== domclick_sold v2 END (full done) =====")
        return 0

    logger.error("Unknown mode: %s", args.mode)
    return 2


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Domclick v2 orchestrator. Modes: list, pipeline, backfill, full. "
            "Default mode: full. Все данные пишутся сразу в БД (без JSON/xlsx)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--mode",
        choices=("list", "pipeline", "backfill", "full"),
        default="full",
        help=(
            "list: BFF -> domclick_links.json. "
            "pipeline: domclick_links.json -> БД. "
            "backfill: ВСЕ domclick_sold в sold_ads -> re-парс. "
            "full: list + pipeline."
        ),
    )
    p.add_argument("--limit", type=int, default=0,
                   help="Max ads (для backfill): 0 = без лимита")
    p.add_argument("--offset", type=int, default=0,
                   help="Skip первые N ads (для chunked backfill)")
    p.add_argument("--no-create-houses", action="store_true",
                   help="Не auto-create новых домов (только link к существующим)")
    p.add_argument("--no-link", action="store_true",
                   help="Не запускать batch linker после pipeline")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())

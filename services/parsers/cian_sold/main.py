"""services.parsers.cian_sold.main - оркестратор.

Шаги:
1. Запустить `python -m acquirer` (CLI парсера) → result.jsonl в data/
2. Импортировать result.jsonl в PostgreSQL (через importer.py)
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from packages.flipper_db import FlipperRepository, init_db
from services.parsers._common import run_subprocess, setup_logging
from services.parsers.cian_sold.importer import import_cian_sold_jsonl

CIAN_SOLD_DIR = Path(__file__).resolve().parent
DATA_DIR = CIAN_SOLD_DIR / "data"


async def main() -> int:
    log = setup_logging("cian_sold")
    log.info("===== cian_sold START =====")

    # 1. Парсинг → JSONL
    jsonl_path = DATA_DIR / "result.jsonl"
    rc = await run_subprocess(
        ["-m", "services.parsers.cian_sold.acquirer",
         "--output", str(jsonl_path),
         "--failed", str(DATA_DIR / "failed.jsonl")],
        cwd=CIAN_SOLD_DIR,
    )
    if rc != 0:
        log.error("acquirer завершился с rc=%s, импорт в БД не выполняется", rc)
        return rc

    if not jsonl_path.is_file():
        log.warning("result.jsonl не создан — нечего импортировать")
        return 0

    # 2. Импорт в PostgreSQL
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        log.error("DATABASE_URL не задан")
        return 2

    await init_db(db_url)
    repo = FlipperRepository()  # engine уже инициализирован

    n_houses, n_sold = await import_cian_sold_jsonl(repo, jsonl_path)
    log.info("===== cian_sold END (houses=%s sold_ads=%s) =====", n_houses, n_sold)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

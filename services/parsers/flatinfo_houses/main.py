"""services.parsers.flatinfo_houses.main - оркестратор.

Шаги:
1. `acquirer.py` → house_pages_result.json (детальные страницы домов)
2. Импорт house_pages_result.json в PostgreSQL (только houses)
3. (Опц.) exporter.py

NB: `houses.py` (фильтрация) — это утилита, не парсер. Запускается отдельно.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from packages.flipper_db import FlipperRepository, init_db
from services.parsers._common import run_subprocess, setup_logging
from services.parsers.flatinfo_houses.importer import import_flatinfo_json

FLATINFO_DIR = Path(__file__).resolve().parent
RESULT_JSON = FLATINFO_DIR / "house_pages_result.json"


async def main() -> int:
    log = setup_logging("flatinfo_houses")
    log.info("===== flatinfo_houses START =====")

    # 1. Парсинг: детальные страницы домов
    rc = run_subprocess(
        [str(FLATINFO_DIR / "acquirer.py"),
         "--output", str(RESULT_JSON)],
        cwd=FLATINFO_DIR,
    )
    if rc != 0:
        log.error("acquirer.py завершился с rc=%s, импорт не выполняется", rc)
        return rc

    if not RESULT_JSON.is_file():
        log.warning("house_pages_result.json не создан — нечего импортировать")
        return 0

    # 2. Импорт в PostgreSQL
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        log.error("DATABASE_URL не задан")
        return 2

    init_db(db_url)
    repo = FlipperRepository()  # engine уже инициализирован
    n_houses, _ = await import_flatinfo_json(repo, RESULT_JSON)

    # 3. Опц. Excel
    if os.getenv("FLATINFO_DUMP_XLSX", "1") == "1":
        run_subprocess([str(FLATINFO_DIR / "exporter.py")], cwd=FLATINFO_DIR)

    log.info("===== flatinfo_houses END (houses=%s) =====", n_houses)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

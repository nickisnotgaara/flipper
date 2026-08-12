"""services.parsers.winners_sold.main - оркестратор.

Шаги:
1. Запустить `acquirer.py` для обоих пресетов ('new' и 'secondary') → all_advs*.json
2. Импортировать JSON-файлы в PostgreSQL (через importer.py)
3. (Опц.) Запустить filters.py + exporter.py для Excel-выгрузки
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from packages.flipper_db import FlipperRepository, init_db
from services.parsers._common import run_subprocess, setup_logging
from services.parsers.winners_sold.importer import import_winners_json

WINNERS_DIR = Path(__file__).resolve().parent


async def main() -> int:
    log = setup_logging("winners_sold")
    log.info("===== winners_sold START =====")

    # 1. Парсинг обоих пресетов
    for category in ("new", "secondary"):
        out_name = "all_advs.json" if category == "new" else "all_advs_vtorichka.json"
        out_path = WINNERS_DIR / out_name
        rc = await run_subprocess(
            [str(WINNERS_DIR / "acquirer.py"),
             "--category", category,
             "--output", str(out_path)],
            cwd=WINNERS_DIR,
        )
        if rc != 0:
            log.error("acquirer.py --category %s завершился с rc=%s", category, rc)
            return rc

    # 2. Импорт в PostgreSQL
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        log.error("DATABASE_URL не задан")
        return 2

    await init_db(db_url)
    repo = FlipperRepository()  # engine уже инициализирован

    total_h, total_s = 0, 0
    for json_file in (
        WINNERS_DIR / "all_advs.json",
        WINNERS_DIR / "all_advs_vtorichka.json",
    ):
        if json_file.is_file():
            n_h, n_s = await import_winners_json(repo, json_file)
            total_h += n_h
            total_s += n_s

    # 3. Опц. Excel-выгрузка
    if os.getenv("WINNERS_DUMP_XLSX", "1") == "1":
        await run_subprocess([str(WINNERS_DIR / "filters.py")], cwd=WINNERS_DIR)
        await run_subprocess([str(WINNERS_DIR / "exporter.py")], cwd=WINNERS_DIR)

    log.info("===== winners_sold END (houses=%s sold_ads=%s) =====", total_h, total_s)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

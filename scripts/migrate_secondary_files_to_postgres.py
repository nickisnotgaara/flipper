"""scripts/migrate_secondary_files_to_postgres - однократный перелив
существующих файлов из secondary/ в новую PostgreSQL-схему.

Что делает:
    secondary/cian/data/result.jsonl             → houses + sold_ads (source='cian_sold')
    secondary/winners/all_advs*.json             → houses + sold_ads (source='winners_sold')
    secondary/domclick/domclick_result.json     → houses + sold_ads (source='domclick_sold')
    secondary/flatinfo/house_pages_result.json   → houses              (source='flatinfo_houses')

Идемпотентен: повторный запуск не плодит дубликаты (upsert по (source, external_id)).
После успешной миграции можно удалить secondary/.

Использование:
    # 1. Запустить вручную на хосте (с поднятым PostgreSQL):
    docker compose up -d app_postgres
    python scripts/migrate_secondary_files_to_postgres.py \\
        --secondary ../secondary \\
        --db "postgresql+asyncpg://flipper:flipper_secret@app_postgres:5432/flipper"

    # 2. Или через контейнер любого парсера (с монтированным secondary/):
    docker compose run --rm cian_sold \\
        python -m scripts.migrate_secondary_files_to_postgres
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Корень репозитория (родитель scripts/)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from packages.flipper_db import FlipperRepository, init_db, init_engine

# Импортируем importer'ы
from services.parsers.cian_sold.importer import import_cian_sold_jsonl
from services.parsers.domclick_sold.importer import import_domclick_json
from services.parsers.flatinfo_houses.importer import import_flatinfo_json
from services.parsers.winners_sold.importer import import_winners_json

logger = logging.getLogger("migrate")


def _default_secondary() -> Path:
    """По умолчанию ../secondary относительно корня репо."""
    return ROOT.parent / "secondary"


def _default_db_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://flipper:flipper_secret@app_postgres:5432/flipper",
    )


async def run(secondary_dir: Path, db_url: str, dry_run: bool = False) -> int:
    """Перелив файлов из secondary/ в PostgreSQL.

    Создаёт таблицы (если их ещё нет) и заливает данные.
    Идемпотентен: повторный запуск не плодит дубликаты.
    """
    if not secondary_dir.is_dir():
        logger.error("secondary директория не найдена: %s", secondary_dir)
        return 2

    # init_engine + init_db: идемпотентны, можно звать повторно.
    # init_db создаёт таблицы (если их нет).
    init_engine(db_url)
    await init_db(db_url)
    repo = FlipperRepository()  # engine уже есть, не пересоздаём

    total_h = 0
    total_s = 0
    failed_steps: list[str] = []

    # 1. cian_sold (result.jsonl)
    cian_sold_path = secondary_dir / "cian" / "data" / "result.jsonl"
    if cian_sold_path.is_file():
        if dry_run:
            logger.info("[DRY-RUN] cian_sold: %s", cian_sold_path)
        else:
            logger.info("=== cian_sold ===")
            n_h, n_s = await import_cian_sold_jsonl(repo, cian_sold_path)
            total_h += n_h
            total_s += n_s
    else:
        logger.warning("Пропускаю cian_sold: %s не найден", cian_sold_path)

    # 2. winners_sold (all_advs.json + all_advs_vtorichka.json)
    for name in ("all_advs.json", "all_advs_vtorichka.json"):
        winners_path = secondary_dir / "winners" / name
        if winners_path.is_file():
            if dry_run:
                logger.info("[DRY-RUN] winners_sold: %s", winners_path)
            else:
                logger.info("=== winners_sold: %s ===", name)
                n_h, n_s = await import_winners_json(repo, winners_path)
                total_h += n_h
                total_s += n_s
        else:
            logger.warning("Пропускаю winners_sold/%s: не найден", name)

    # 3. domclick_sold (domclick_result.json)
    domclick_path = secondary_dir / "domclick" / "domclick_result.json"
    if domclick_path.is_file():
        if dry_run:
            logger.info("[DRY-RUN] domclick_sold: %s", domclick_path)
        else:
            logger.info("=== domclick_sold ===")
            n_h, n_s = await import_domclick_json(repo, domclick_path)
            total_h += n_h
            total_s += n_s
    else:
        logger.warning("Пропускаю domclick_sold: %s не найден", domclick_path)

    # 4. flatinfo_houses (house_pages_result.json)
    flatinfo_path = secondary_dir / "flatinfo" / "house_pages_result.json"
    if flatinfo_path.is_file():
        if dry_run:
            logger.info("[DRY-RUN] flatinfo_houses: %s", flatinfo_path)
        else:
            logger.info("=== flatinfo_houses ===")
            n_h, _ = await import_flatinfo_json(repo, flatinfo_path)
            total_h += n_h
    else:
        logger.warning("Пропускаю flatinfo_houses: %s не найден", flatinfo_path)

    logger.info(
        "МИГРАЦИЯ %s: домов=%s офферов=%s",
        "DRY-RUN" if dry_run else "OK",
        total_h,
        total_s,
    )
    return 0 if not failed_steps else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Перелив существующих файлов из secondary/ в PostgreSQL."
    )
    parser.add_argument(
        "--secondary",
        type=Path,
        default=_default_secondary(),
        help="Путь к secondary/ (default: ../secondary)",
    )
    parser.add_argument(
        "--db",
        default=_default_db_url(),
        help="DATABASE_URL (default: $DATABASE_URL или локальный flipper)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать, какие файлы будут обработаны (без записи в БД)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Подробный вывод"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    return asyncio.run(run(args.secondary, args.db, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())

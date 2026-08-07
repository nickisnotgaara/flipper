"""services.parsers.cian_active.importer - перенос данных cian_active
из старой parser_cian.db (SQLite) в новую PostgreSQL-схему.

Этот модуль — обёртка над scripts/migrate_cian_active_db.py, доступная
как `import_cian_active_to_db(repo, source=...)`.

Назначение:
    cian_active_ads (старая)  → active_ads   (source='cian_active')
    cian_sold_ads (старая)    → sold_ads     (source='cian_active')

Идемпотентен: повторный запуск не плодит дубликаты.

Going-forward hook
------------------
После ``repo.upsert_active_ads_batch`` мы **запускаем линкер** (see
``packages/flipper_db.linker``), чтобы каждый новый/обновлённый ad
сразу получил ``house_id``. Это атомарно: parse → upsert → link,
без ручного шага.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from packages.flipper_db import FlipperRepository

logger = logging.getLogger(__name__)


# Путь к старой SQLite БД по умолчанию
DEFAULT_OLD_DB_PATH = os.getenv(
    "CIAN_OLD_DB_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "data",
        "parser_cian.db",
    ),
)


async def _link_ads_post_upsert(
    *,
    ad_table: str = "active_ads",
    ad_source: str = "cian_active",
    db_url: str | None = None,
    radius_m: float = 75.0,
    ambiguity_ratio: float = 1.3,
) -> dict:
    """Run the linker after an upsert. Opens its own asyncpg connection.

    Returns the link counters (matched_exact, matched_geo, applied, …)
    so the caller can log them.
    """
    from packages.flipper_db import link_ads  # local import
    from packages.flipper_db.base import DEFAULT_DATABASE_URL
    import asyncpg

    if db_url is None:
        db_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

    # asyncpg expects postgresql:// (not postgresql+asyncpg:// — that's SQLAlchemy's
    # async driver marker). Convert so the linker doesn't fail with
    # 'scheme is expected to be either "postgresql" or "postgres"'.
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    # The SQLAlchemy repo doesn't expose the freshly-upserted cian_ids,
    # so we run a full unlinked-scan. It's cheap (~0.1s with cKDTree)
    # and idempotent (``WHERE house_id IS NULL``).
    conn = await asyncpg.connect(db_url)
    try:
        result = await link_ads(
            conn,
            ad_table=ad_table,
            ad_source=ad_source,
            houses_sources=("flatinfo", "cian"),
            radius_m=radius_m,
            ambiguity_ratio=ambiguity_ratio,
            apply=True,
        )
        return result
    finally:
        await conn.close()


async def import_cian_active_to_db(
    repo: "FlipperRepository",
    *,
    source: str | None = None,
    dry_run: bool = False,
    link_after: bool = True,
    db_url: str | None = None,
) -> dict:
    """Перенос cian_active из старой SQLite БД в новую схему.

    Args:
        repo: FlipperRepository с уже инициализированным engine.
        source: путь к parser_cian.db или SQLite URL. По умолчанию ищет
                data/parser_cian.db (рядом с корнем проекта).
        dry_run: только посчитать записи, без записи в БД.
        link_after: после upsert вызвать линкер (default True).
                    Отключить можно для отладки.
        db_url: URL БД для линкера (asyncpg). Берётся из $DATABASE_URL
                или packages.flipper_db.base.DEFAULT_DATABASE_URL.

    Returns:
        dict с ключами: active_ads, sold_ads, dry_run, source,
                        link (counters) if link_after, else skipped.
    """
    # Ленивый импорт: scripts.migrate_cian_active_db зависит от repo,
    # который у нас уже есть
    import sys
    from pathlib import Path

    ROOT = Path(__file__).resolve().parent.parent.parent.parent  # flipper/
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from scripts.migrate_cian_active_db import _read_old_db

    src = source or DEFAULT_OLD_DB_PATH
    if not os.path.exists(src) and "://" not in src:
        logger.warning(
            "import_cian_active_to_db: старая БД не найдена (%s). "
            "Скорее всего данные cian_active ещё не были накоплены. "
            "Пропускаю миграцию.",
            src,
        )
        return {
            "active_ads": 0,
            "sold_ads": 0,
            "dry_run": dry_run,
            "source": src,
            "skipped": True,
        }

    try:
        active_ads, sold_ads = _read_old_db(src)
    except Exception as exc:
        logger.error("import_cian_active_to_db: ошибка чтения %s: %s", src, exc)
        return {
            "active_ads": 0,
            "sold_ads": 0,
            "dry_run": dry_run,
            "source": src,
            "error": str(exc),
        }

    if dry_run:
        logger.info(
            "[DRY-RUN] %s: active_ads=%d, sold_ads=%d",
            src, len(active_ads), len(sold_ads),
        )
        return {
            "active_ads": len(active_ads),
            "sold_ads": len(sold_ads),
            "dry_run": True,
            "source": src,
        }

    # Batched upsert
    from packages.flipper_db.enums import Source
    BATCH = 1000

    total_a = 0
    for i in range(0, len(active_ads), BATCH):
        chunk = active_ads[i : i + BATCH]
        total_a += await repo.upsert_active_ads_batch(chunk)

    total_s = 0
    for i in range(0, len(sold_ads), BATCH):
        chunk = sold_ads[i : i + BATCH]
        total_s += await repo.upsert_sold_offers_batch(chunk)

    logger.info(
        "import_cian_active_to_db: %s → active_ads=%d, sold_ads=%d",
        src, total_a, total_s,
    )

    # Going-forward hook: link freshly-upserted ads to their houses.
    # The cian_house_id was carried over from the old DB; for ads that
    # had a cian_house_id pointing to a known house, the linker matches
    # by id. For the rest, the coord fallback kicks in.
    result: dict = {
        "active_ads": total_a,
        "sold_ads": total_s,
        "dry_run": False,
        "source": src,
    }
    if link_after and total_a > 0:
        try:
            link_stats = await _link_ads_post_upsert(
                ad_table="active_ads",
                ad_source="cian_active",
                db_url=db_url,
            )
            result["link"] = link_stats
            logger.info(
                "import_cian_active_to_db: linked %d/%d active_ads "
                "(exact=%d, geo=%d, ambiguous=%d, no_match=%d)",
                link_stats.get("applied", 0),
                total_a,
                link_stats.get("matched_exact", 0),
                link_stats.get("matched_geo", 0),
                link_stats.get("ambiguous", 0),
                link_stats.get("no_match", 0),
            )
        except Exception as exc:
            logger.warning(
                "import_cian_active_to_db: linker failed (%s). "
                "Run scripts/link_ads_to_houses.py --apply manually.",
                exc,
            )
            result["link_error"] = str(exc)

    return result

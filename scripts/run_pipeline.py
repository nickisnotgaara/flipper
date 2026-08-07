"""scripts.run_pipeline — generic pipeline orchestrator (v2).

Single entry point for going-forward parsing. Supports any
``SourceParser``; today ``CianSource`` and ``DomclickSource`` are wired in,
but any future source (winners, avito, ...) plugs in via the same CLI.

Modes
-----
1. ``--fetch-missing`` (recommended for periodic runs):
   Scan all ads in the source's ad_table for the given source; for each
   one, fetch the latest data from the source, upsert, and do
   stale-cleanup. Cheap re-fetch to keep the data fresh.

2. ``--from-links FILE`` (one-off):
   Read ad external_ids from FILE (one per line). For domclick_sold,
   the file is typically produced by ``acquirer.py --mode list`` →
   ``domclick_links.json``. For cian_active, ids come from
   Google Sheets → ``input_all.json``.

3. ``--recent N``:
   Process the N most-recently-updated ads in the source's table.

4. ``--full-cycle`` (domclick_sold only):
   Run ``acquirer.py`` to fetch fresh list from BFF, save to
   ``domclick_links.json``, then run the pipeline on those ids. Skips
   acquirer if file already exists and is fresh (< 1 hour).

Source → ad_table mapping (driven by ``is_sold_source`` flag):
  - cian_active   → active_ads (refreshes prices, deactivates stale)
  - domclick_sold → sold_ads (re-fetches sold-ads details)

Examples
--------
Periodic re-fetch of all cian_active ads (production cron job)::

    py scripts/run_pipeline.py --source cian_active --fetch-missing

Re-fetch specific ad ids from a file::

    py scripts/run_pipeline.py --source cian_active --from-links ids.txt
    py scripts/run_pipeline.py --source domclick_sold --from-links domclick_links.json

Full cycle for domclick_sold: list (BFF) + parse (pipeline)::

    py scripts/run_pipeline.py --source domclick_sold --full-cycle

Disable stale-cleanup (just refresh prices/photos)::

    py scripts/run_pipeline.py --source cian_active --fetch-missing --no-cleanup

Disable linker (faster; if you plan to run it separately)::

    py scripts/run_pipeline.py --source cian_active --fetch-missing --no-link

Disable house auto-create (only link to existing houses)::

    py scripts/run_pipeline.py --source domclick_sold --full-cycle --no-create-houses
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import asyncpg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from packages.flipper_db import (  # noqa: E402
    CianSource,
    DomclickSource,
    run_source_pipeline,
)
from packages.flipper_db.base import DEFAULT_DATABASE_URL  # noqa: E402

DEFAULT_DSN = DEFAULT_DATABASE_URL

# Source registry: maps source_name → (class, ad_table, supports_full_cycle).
#
# ad_table — куда pipeline смотрит в БД для --fetch-missing/--recent.
#   Для is_sold_source=True → "sold_ads"
#   Для is_sold_source=False → "active_ads"
#
# supports_full_cycle — может ли source сам собрать список объявлений
#   (для domclick_sold: BFF API → domclick_links.json).
#   cian_active берёт ссылки из Google Sheets, поэтому False.
SOURCES: dict[str, dict[str, Any]] = {
    "cian_active": {
        "class": CianSource,
        "ad_table": "active_ads",
        "supports_full_cycle": False,
    },
    "domclick_sold": {
        "class": DomclickSource,
        "ad_table": "sold_ads",
        "supports_full_cycle": True,
    },
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Generic going-forward pipeline for any SourceParser. "
            "Re-fetches ads from the source, upserts, and (for active sources) "
            "moves inactive ads to sold_ads."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--source",
        default="cian_active",
        choices=sorted(SOURCES.keys()),
        help="Which source to run the pipeline for",
    )
    p.add_argument(
        "--dsn",
        default="postgresql://flipper:flipper_secret@127.0.0.1:5432/flipper",
        help="PostgreSQL DSN (asyncpg format: postgresql://...)",
    )

    # One of these is required (mutually exclusive)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--fetch-missing",
        action="store_true",
        help="Re-fetch every ad in the source's ad_table (production cron job)",
    )
    mode.add_argument(
        "--recent",
        type=int,
        metavar="N",
        help="Re-fetch the N most-recently-updated ads",
    )
    mode.add_argument(
        "--from-links",
        dest="from_links",
        metavar="FILE",
        help="Re-fetch the ad external_ids listed in FILE (one per line). "
             "For domclick_sold, typical file is domclick_links.json from acquirer.py.",
    )
    mode.add_argument(
        "--full-cycle",
        action="store_true",
        help="domclick_sold only: run acquirer.py to fetch BFF list, "
             "then run pipeline on those ids (skips if domclick_links.json is fresh).",
    )

    p.add_argument("--no-cleanup", action="store_true",
                   help="Don't move inactive ads to sold_ads (no-op for sold sources)")
    p.add_argument("--no-create-houses", action="store_true",
                   help="Don't auto-create new houses for ads with no spatial match. "
                        "(Default: create with source='auto' if spatial match fails.)")
    p.add_argument("--no-link", action="store_true",
                   help="Don't run the linker after the pipeline")
    p.add_argument("--limit", type=int, default=0,
                   help="Max ads to process in this run (0 = no limit)")
    p.add_argument("--offset", type=int, default=0,
                   help="Skip the first N ads (for chunked runs: "
                        "chunk1=--limit 400, chunk2=--offset 400 --limit 400, etc.)")
    return p.parse_args()


async def _load_ad_ids_from_table(
    conn: asyncpg.Connection,
    ad_table: str,
    source: str,
    *,
    fetch_missing: bool,
    recent_n: Optional[int],
    limit: int,
    offset: int,
) -> list[str]:
    """Resolve the list of ad external_ids from the source's table."""
    if recent_n is not None:
        rows = await conn.fetch(
            f"SELECT external_id FROM {ad_table} "
            f"WHERE source = $1 "
            f"ORDER BY updated_at DESC NULLS LAST "
            f"LIMIT $2 OFFSET $3",
            source, recent_n, offset,
        )
        return [r["external_id"] for r in rows]

    if fetch_missing:
        # All currently-active ads for the source (in stable id order so
        # chunked runs are deterministic and don't overlap)
        rows = await conn.fetch(
            f"SELECT external_id FROM {ad_table} "
            f"WHERE source = $1 "
            f"ORDER BY external_id "
            f"LIMIT $2 OFFSET $3",
            source, limit if limit > 0 else 1_000_000, offset,
        )
        return [r["external_id"] for r in rows]

    raise RuntimeError("unreachable")


def _load_ad_ids_from_links_file(path: Path) -> list[str]:
    """Читает external_ids из файла. Поддерживает 2 формата:
    - one per line
    - JSON: {"items": [{"id": 123, ...}, ...]} (формат domclick_links.json)
    """
    if not path.is_file():
        raise SystemExit(f"--from-links file not found: {path}")
    text = path.read_text(encoding="utf-8")
    text_stripped = text.strip()
    if text_stripped.startswith("{"):
        # JSON формат (domclick_links.json)
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--from-links: invalid JSON in {path}: {exc}")
        items = doc.get("items") if isinstance(doc, dict) else None
        if not isinstance(items, list):
            raise SystemExit(f"--from-links: expected JSON with 'items' list, got {type(doc).__name__}")
        ids = []
        for it in items:
            if isinstance(it, dict):
                oid = it.get("id")
                if oid is not None:
                    ids.append(str(oid))
        return ids
    # Plain text: one per line
    ids = [line.strip() for line in text.splitlines() if line.strip()]
    return ids


def _run_domclick_acquirer(logger: logging.Logger) -> Path:
    """Запускает services/parsers/domclick_sold/acquirer.py для сбора ссылок.

    Returns: путь к domclick_links.json
    """
    acquirer = ROOT / "services" / "parsers" / "domclick_sold" / "acquirer.py"
    if not acquirer.is_file():
        raise SystemExit(f"acquirer.py not found: {acquirer}")
    links_json = acquirer.parent / "domclick_links.json"
    logger.info("Running acquirer.py (BFF list)...")
    rc = subprocess.call([sys.executable, str(acquirer)], cwd=str(acquirer.parent))
    if rc != 0:
        raise SystemExit(f"acquirer.py exited with code {rc}")
    if not links_json.is_file():
        raise SystemExit(f"acquirer.py did not produce {links_json}")
    return links_json


async def main_async(args: argparse.Namespace) -> int:
    logger = logging.getLogger("run_pipeline")
    if not (args.fetch_missing or args.recent or args.from_links or args.full_cycle):
        raise SystemExit("One of --fetch-missing / --recent N / --from-links FILE / --full-cycle is required.")

    # asyncpg expects postgresql://, not postgresql+asyncpg://
    dsn = args.dsn
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)

    source_cfg = SOURCES[args.source]
    source_cls = source_cfg["class"]
    ad_table = source_cfg["ad_table"]

    source = source_cls()

    # 1) Resolve ad ids
    if args.full_cycle:
        if not source_cfg["supports_full_cycle"]:
            raise SystemExit(
                f"--full-cycle is not supported for source {args.source!r}. "
                f"Currently only {', '.join(s for s, c in SOURCES.items() if c['supports_full_cycle'])} "
                f"support full-cycle."
            )
        links_path = _run_domclick_acquirer(logger)
        ad_ids = _load_ad_ids_from_links_file(links_path)
        logger.info("Full-cycle for %s: %d ids from %s", args.source, len(ad_ids), links_path)
    elif args.from_links:
        ad_ids = _load_ad_ids_from_links_file(Path(args.from_links))
        logger.info("From-links for %s: %d ids from %s", args.source, len(ad_ids), args.from_links)
    else:
        conn = await asyncpg.connect(dsn)
        try:
            ad_ids = await _load_ad_ids_from_table(
                conn, ad_table, args.source,
                fetch_missing=args.fetch_missing,
                recent_n=args.recent,
                limit=args.limit,
                offset=args.offset,
            )
        finally:
            await conn.close()

    if not ad_ids:
        logger.info("No ads to process.")
        return 0

    if args.limit > 0:
        ad_ids = ad_ids[args.limit:]
    if args.offset > 0:
        ad_ids = ad_ids[args.offset:]
    if args.limit > 0:
        ad_ids = ad_ids[:args.limit]

    logger.info(
        "run_pipeline: source=%s ad_table=%s ads=%d (no_cleanup=%s, no_create=%s, no_link=%s)",
        args.source, ad_table, len(ad_ids), args.no_cleanup, args.no_create_houses, args.no_link,
    )

    # 2) Run pipeline
    result = await run_source_pipeline(
        source,
        ad_ids,
        auto_create_houses=not args.no_create_houses,
        cleanup_stale=not args.no_cleanup,
        link_after=not args.no_link,
        db_url=dsn,
    )
    logger.info("Pipeline result: %s", result)
    return 0


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())

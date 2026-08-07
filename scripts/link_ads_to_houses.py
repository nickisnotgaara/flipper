"""scripts/link_ads_to_houses.py — link unlinked ads to houses (CLI).

Thin CLI wrapper around :func:`packages.flipper_db.linker.link_ads`
(the async library). Use this for the **one-shot migration**: link
all unlinked ads in the DB.

Going-forward, the cian_active importer calls
:func:`packages.flipper_db.linker.link_ads_by_cian_ids` directly
after each batch of new ads — no CLI roundtrip needed.

Examples
--------
Dry-run (compute, don't write)::

    py scripts/link_ads_to_houses.py --dry-run

Apply (writes to DB)::

    py scripts/link_ads_to_houses.py --apply

Custom radius / ambiguity for the coord fallback::

    py scripts/link_ads_to_houses.py --apply --radius-m 100 --ambiguity-ratio 1.5

Link ``sold_ads`` (any source) instead of ``active_ads``::

    py scripts/link_ads_to_houses.py --apply --ad-table sold_ads --ad-source ""
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from packages.flipper_db import link_ads  # noqa: E402

DEFAULT_DSN = "postgresql://flipper:flipper_secret@127.0.0.1:5432/flipper"

log = logging.getLogger("link_ads_to_houses_cli")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Link unlinked ads to houses (cian_house_id first, then coord "
            "fallback). Thin CLI wrapper around packages.flipper_db.linker."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--dsn", default=DEFAULT_DSN, help="PostgreSQL DSN")
    p.add_argument(
        "--ad-table",
        default="active_ads",
        choices=["active_ads", "sold_ads"],
        help="Table with ads to link",
    )
    p.add_argument(
        "--ad-source",
        default="cian_active",
        help="Source filter on ads (use '' to match all sources)",
    )
    p.add_argument(
        "--houses-sources",
        default="flatinfo,cian",
        help="Comma-separated list of house sources to use as candidates",
    )
    p.add_argument(
        "--radius-m",
        type=float,
        default=75.0,
        help="Max haversine distance for the coord fallback (meters)",
    )
    p.add_argument(
        "--ambiguity-ratio",
        type=float,
        default=1.3,
        help=(
            "Coord fallback: if 2nd_nearest / 1st_nearest < this ratio, "
            "the match is considered ambiguous and skipped. Set to 1.0 to disable."
        ),
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Actually UPDATE. Without this flag, runs in dry-run mode.",
    )
    return p.parse_args()


async def main_async(args: argparse.Namespace) -> int:
    houses_sources = (
        [s.strip() for s in args.houses_sources.split(",") if s.strip()]
        if args.houses_sources
        else None
    )
    ad_source = args.ad_source if args.ad_source else None

    log.info(
        "=== link_ads_to_houses %s ===",
        "APPLY" if args.apply else "DRY-RUN",
    )
    log.info(
        "ad_table=%s ad_source=%s houses_sources=%s radius=%.1f ambiguity=%.2f",
        args.ad_table,
        ad_source,
        houses_sources,
        args.radius_m,
        args.ambiguity_ratio,
    )

    conn = await asyncpg.connect(args.dsn)
    try:
        result = await link_ads(
            conn,
            ad_table=args.ad_table,
            ad_source=ad_source,
            houses_sources=houses_sources,
            radius_m=args.radius_m,
            ambiguity_ratio=args.ambiguity_ratio,
            apply=args.apply,
        )
        log.info("Result: %s", json.dumps(result, ensure_ascii=False))

        if args.apply:
            # Final state snapshot for the operator
            if ad_source:
                row = await conn.fetchrow(
                    f"SELECT COUNT(*) AS total, "
                    f"COUNT(*) FILTER (WHERE house_id IS NOT NULL) AS linked, "
                    f"COUNT(*) FILTER (WHERE house_id IS NULL AND lat IS NOT NULL) AS un_w, "
                    f"COUNT(*) FILTER (WHERE house_id IS NULL AND lat IS NULL) AS un_no "
                    f"FROM {args.ad_table} WHERE source = $1",
                    ad_source,
                )
            else:
                row = await conn.fetchrow(
                    f"SELECT COUNT(*) AS total, "
                    f"COUNT(*) FILTER (WHERE house_id IS NOT NULL) AS linked, "
                    f"COUNT(*) FILTER (WHERE house_id IS NULL AND lat IS NOT NULL) AS un_w, "
                    f"COUNT(*) FILTER (WHERE house_id IS NULL AND lat IS NULL) AS un_no "
                    f"FROM {args.ad_table}"
                )
            log.info(
                "=== Final state (%s, source=%s) ===\n"
                "  total:                    %d\n"
                "  linked:                   %d (%.1f%%)\n"
                "  still unlinked w/coords:  %d\n"
                "  still unlinked no/coords: %d",
                args.ad_table,
                ad_source,
                row["total"],
                row["linked"],
                100 * row["linked"] / max(row["total"], 1),
                row["un_w"],
                row["un_no"],
            )
        return 0
    finally:
        await conn.close()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())

"""scripts/backfill_flatinfo_cian_house_id.py — fix flatinfo.cian_house_id.

The flatinfo import historically populated ``houses.cian_house_id`` from a
different (and often wrong) source than cian itself. The effect: when a
cian ad carries ``cian_house_id = X``, the actual flatinfo house for that
building is at the same lat/lng but has a *different* ``cian_house_id``,
so the coord-based linker can't match by cian_house_id.

This script heals that cross-reference, **only** for flatinfo houses whose
``cian_house_id`` is currently NULL. Strategy:

  1. Load all flatinfo houses with NULL ``cian_house_id`` and lat/lng.
  2. Load all cian houses (source='cian') with lat/lng.
  3. For each flatinfo house, find the closest cian house within RADIUS_M
     (default 30m). If the street + house_num also match (after
     normalization), update flatinfo.cian_house_id.

Idempotent: only updates rows where cian_house_id IS NULL.
Safe to re-run.

Examples
--------
Dry-run (default)::

    py scripts/backfill_flatinfo_cian_house_id.py

Apply::

    py scripts/backfill_flatinfo_cian_house_id.py --apply

Custom radius (more permissive)::

    py scripts/backfill_flatinfo_cian_house_id.py --apply --radius-m 50
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
import time
from pathlib import Path

import asyncpg
import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_DSN = "postgresql://flipper:flipper_secret@127.0.0.1:5432/flipper"
EARTH_R = 6_371_000.0
DEFAULT_RADIUS_M = 30.0
DEFAULT_BATCH = 500

# Address normalization: lowercase, strip "д.", "корп.", "стр.", "к." prefixes.
_STREET_TYPE_LEAD = re.compile(
    r"^(ул\.?|улица|пр-т\.?|проспект|просп\.?|пер\.?|переулок|"
    r"б-р\.?|бульвар|ш\.?|шоссе|наб\.?|набережная|пл\.?|площадь|"
    r"аллея|проезд|тупик|кв-л\.?|квартал)\s+",
    re.IGNORECASE,
)
_HOUSE_PREFIX = re.compile(
    r"^(д\.?|дом|корп\.?|корпус|стр\.?|строение|к\.?)\s*",
    re.IGNORECASE,
)


def norm_street(s: str | None) -> str:
    if not s:
        return ""
    s = _STREET_TYPE_LEAD.sub("", s.strip())
    return s.lower().strip()


def norm_house(s: str | None) -> str:
    if not s:
        return ""
    s = _HOUSE_PREFIX.sub("", s.strip())
    return s.lower().strip()


def addr_key(street: str | None, house_num: str | None) -> tuple[str, str]:
    return (norm_street(street), norm_house(house_num))


log = logging.getLogger("backfill_flatinfo_cian_house_id")


async def main_async(args: argparse.Namespace) -> int:
    t0 = time.monotonic()
    log.info(
        "=== backfill_flatinfo_cian_house_id %s ===",
        "APPLY" if args.apply else "DRY-RUN",
    )
    log.info("radius_m=%.1f", args.radius_m)

    conn = await asyncpg.connect(args.dsn)
    try:
        # 1) Load flatinfo houses with NULL cian_house_id and lat/lng
        flatinfo_rows = await conn.fetch(
            """
            SELECT id, lat, lng, street, house_num
            FROM houses
            WHERE source='flatinfo'
              AND cian_house_id IS NULL
              AND lat IS NOT NULL AND lng IS NOT NULL
            """
        )
        log.info("  flatinfo houses with NULL cian_house_id: %d", len(flatinfo_rows))
        if not flatinfo_rows:
            log.info("Nothing to do.")
            return 0

        # 2) Load cian houses (any source with cian_house_id, but prefer 'cian')
        #    We use source='cian' as the canonical reference for cian_house_id.
        cian_rows = await conn.fetch(
            """
            SELECT id, cian_house_id, lat, lng, street, house_num
            FROM houses
            WHERE source='cian'
              AND cian_house_id IS NOT NULL
              AND lat IS NOT NULL AND lng IS NOT NULL
            """
        )
        log.info("  cian houses: %d", len(cian_rows))
        if not cian_rows:
            log.info("No cian houses to backfill from.")
            return 0

        # Build cian index for spatial lookup
        cian_coords = np.deg2rad(
            np.array([(r["lat"], r["lng"]) for r in cian_rows], dtype=np.float64)
        )
        cian_addr = {
            int(r["cian_house_id"]): addr_key(r["street"], r["house_num"])
            for r in cian_rows
        }
        cian_by_idx = [(int(r["id"]), int(r["cian_house_id"])) for r in cian_rows]
        tree = cKDTree(cian_coords)

        # 3) For each flatinfo house, find closest cian house within radius
        radius_rad = args.radius_m / EARTH_R
        updates: list[tuple[int, int]] = []  # (flatinfo_id, cian_house_id)
        skipped_no_match = 0
        skipped_addr_mismatch = 0
        for fh in flatinfo_rows:
            fh_addr = addr_key(fh["street"], fh["house_num"])
            ad_rad = np.deg2rad(np.array([[fh["lat"], fh["lng"]]], dtype=np.float64))
            idxs = tree.query_ball_point(ad_rad, r=radius_rad)
            if not idxs or len(idxs[0]) == 0:
                skipped_no_match += 1
                continue
            # Take the closest (smallest distance)
            dists = np.linalg.norm(cian_coords[idxs[0]] - ad_rad, axis=1)
            best = idxs[0][int(np.argmin(dists))]
            cian_id, cian_hid = cian_by_idx[best]
            cian_house_addr = cian_addr.get(cian_hid)
            if cian_house_addr != fh_addr:
                # If both streets are empty, fall back to proximity-only match
                # (rare; cian often has street for новостройки). Otherwise skip.
                if not (fh_addr[0] == "" and fh_addr[1] == ""):
                    skipped_addr_mismatch += 1
                    continue
            updates.append((fh["id"], cian_hid))

        log.info(
            "Plan: %d updates, %d no_match, %d addr_mismatch",
            len(updates),
            skipped_no_match,
            skipped_addr_mismatch,
        )

        if not args.apply:
            log.info("DRY-RUN — no UPDATE applied. Re-run with --apply to write.")
            return 0

        # 4) Apply
        n_updated = 0
        for i in range(0, len(updates), args.batch):
            chunk = updates[i : i + args.batch]
            await conn.executemany(
                "UPDATE houses SET cian_house_id = $2::bigint WHERE id = $1::int",
                chunk,
            )
            n_updated += len(chunk)
        log.info("UPDATE: %d rows in %.2fs", n_updated, time.monotonic() - t0)

        # 5) Final state
        row = await conn.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE source='flatinfo') AS flatinfo_total,
              COUNT(*) FILTER (WHERE source='flatinfo' AND cian_house_id IS NOT NULL) AS flatinfo_w_hid,
              COUNT(*) FILTER (WHERE source='flatinfo' AND cian_house_id IS NULL) AS flatinfo_no_hid
            FROM houses
            """
        )
        log.info(
            "=== Final state ===\n"
            "  flatinfo total:        %d\n"
            "  flatinfo w/cian_hid:   %d\n"
            "  flatinfo no cian_hid:  %d",
            row["flatinfo_total"],
            row["flatinfo_w_hid"],
            row["flatinfo_no_hid"],
        )
        log.info("=== DONE in %.2fs ===", time.monotonic() - t0)
        return 0
    finally:
        await conn.close()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Backfill flatinfo.cian_house_id by matching flatinfo houses "
            "(with NULL cian_house_id) to cian houses (source='cian') via "
            "proximity + address match."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--dsn", default=DEFAULT_DSN, help="PostgreSQL DSN")
    p.add_argument(
        "--radius-m",
        type=float,
        default=DEFAULT_RADIUS_M,
        help="Max haversine distance for the proximity match (meters)",
    )
    p.add_argument(
        "--batch",
        type=int,
        default=DEFAULT_BATCH,
        help="Batch size for UPDATE",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Actually UPDATE. Without this flag, runs in dry-run mode.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())

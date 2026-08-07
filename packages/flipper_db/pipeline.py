"""packages.flipper_db.pipeline — generic going-forward pipeline (v3, spatial-first).

v3 design (2026-07-31): "address + coordinates" is the canonical house
identity. cian_house_id is a high-confidence cross-reference when the
source carries one, but NOT the key for creating houses. The pipeline
no longer creates a new ``houses`` row per ``external_house_id`` — that
caused 711 spatial duplicates of flatinfo/cian houses in v2.

Per ad, the pipeline:

  1. ``fetch_ad_page`` → raw response (HTML or JSON) via the source's
     preferred fetcher (e.g. flippercrawl for cian).
  2. ``parse_ad`` → ``AdRecord`` (full raw_data preserved, plus
     lat/lng/address/cian_house_id normalized fields).
  3. **Match house** via ``linker.match_or_create_house``:
        a. cross-ref by ``AdRecord.cian_house_id`` (if set + exists in DB)
        b. spatial match against GOOD_SOURCES houses (cKDTree, ~75m)
        c. optional auto-create a new house with ``source='auto'``
     This is the workhorse: it never creates cian_active duplicates.
  4. Upsert the ad into ``active_ads`` with FULL ``raw_data`` and
     ``house_id`` from step 3.
  5. **Stale cleanup**: if the ad's ``is_active`` is now False but it
     was True in the DB, MOVE it to ``sold_ads`` (atomic, with the
     ``is_active=false`` on the active_ads row).

Idempotent. Re-runnable. Works for any ``SourceParser``.

Going-forward, ``scripts/run_pipeline.py`` is the CLI entry point; the
scheduler calls it periodically (e.g. every 12h for cian_active).
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional

import asyncpg

from . import linker
from .base import DEFAULT_DATABASE_URL
from .parser_types import AdRecord, HouseRecord, SourceParser
from .linker import _CreateStats

log = logging.getLogger("flipper_db.pipeline")


@dataclass
class PipelineResult:
    ads_processed: int = 0
    houses_created: int = 0  # auto-created via linker (source='auto')
    houses_matched_exact: int = 0  # matched via cian_house_id cross-ref
    houses_matched_geo: int = 0  # matched via spatial fallback
    ads_unchanged: int = 0
    moved_to_sold: int = 0  # ad had is_active=False with valid HTML → moved to sold_ads
    deactivated: int = 0  # ad had fetch fail (404/timeout) but was active in DB → is_active=false
    fetch_failures: int = 0  # fetch failed (404/timeout/etc) — counted regardless of deactivation
    parse_failures: int = 0
    linked: int = 0  # applied by the post-batch linker (legacy batch path)

    def to_dict(self) -> dict:
        return {
            "ads_processed": self.ads_processed,
            "houses_created": self.houses_created,
            "houses_matched_exact": self.houses_matched_exact,
            "houses_matched_geo": self.houses_matched_geo,
            "ads_unchanged": self.ads_unchanged,
            "moved_to_sold": self.moved_to_sold,
            "deactivated": self.deactivated,
            "fetch_failures": self.fetch_failures,
            "parse_failures": self.parse_failures,
            "linked": self.linked,
        }


# --- DB helpers ------------------------------------------------------------


async def _upsert_ad(
    conn: asyncpg.Connection,
    source: str,
    ad: AdRecord,
    house_id: Optional[int],
    *,
    ad_lat: Optional[float] = None,
    ad_lng: Optional[float] = None,
) -> bool:
    """Upsert an ad. Returns True if a new row was inserted, False if updated.

    ``cian_house_id`` is filled from ``ad.cian_house_id`` (cross-ref).
    """
    row = await conn.fetchrow(
        """
        INSERT INTO active_ads (
            source, external_id, url, house_id, cian_house_id,
            price, price_per_m2, area, rooms, floor_current, floor_total,
            metro_station, metro_walk_time, district, okrug, renovation,
            is_active, publish_date, lat, lng,
            raw_data, parsed_at, updated_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
            $12, $13, $14, $15, $16, $17, $18, $19, $20,
            $21::json, NOW(), NOW()
        )
        ON CONFLICT (source, external_id) DO UPDATE SET
            url             = EXCLUDED.url,
            house_id        = COALESCE(EXCLUDED.house_id, active_ads.house_id),
            cian_house_id   = COALESCE(EXCLUDED.cian_house_id, active_ads.cian_house_id),
            price           = COALESCE(EXCLUDED.price, active_ads.price),
            price_per_m2    = COALESCE(EXCLUDED.price_per_m2, active_ads.price_per_m2),
            area            = COALESCE(EXCLUDED.area, active_ads.area),
            rooms           = COALESCE(EXCLUDED.rooms, active_ads.rooms),
            floor_current   = COALESCE(EXCLUDED.floor_current, active_ads.floor_current),
            floor_total     = COALESCE(EXCLUDED.floor_total, active_ads.floor_total),
            metro_station   = COALESCE(EXCLUDED.metro_station, active_ads.metro_station),
            metro_walk_time = COALESCE(EXCLUDED.metro_walk_time, active_ads.metro_walk_time),
            district        = COALESCE(EXCLUDED.district, active_ads.district),
            okrug           = COALESCE(EXCLUDED.okrug, active_ads.okrug),
            renovation      = COALESCE(EXCLUDED.renovation, active_ads.renovation),
            is_active       = EXCLUDED.is_active,
            publish_date    = COALESCE(EXCLUDED.publish_date, active_ads.publish_date),
            lat             = COALESCE(EXCLUDED.lat, active_ads.lat),
            lng             = COALESCE(EXCLUDED.lng, active_ads.lng),
            raw_data        = EXCLUDED.raw_data,
            updated_at      = NOW()
        RETURNING (xmax = 0) AS was_insert
        """,
        source,
        ad.external_id,
        ad.url,
        house_id,
        ad.cian_house_id,
        ad.price,
        ad.price_per_m2,
        ad.area,
        ad.rooms,
        ad.floor_current,
        ad.floor_total,
        ad.metro_station,
        ad.metro_walk_time,
        ad.district,
        ad.okrug,
        ad.renovation,
        bool(ad.is_active),
        ad.publish_date,
        ad_lat if ad_lat is not None else ad.lat,
        ad_lng if ad_lng is not None else ad.lng,
        json.dumps(ad.raw_data, ensure_ascii=False, default=str),
    )
    return bool(row["was_insert"])


async def _resolve_ad_geo(
    conn: asyncpg.Connection,
    ad: AdRecord,
    house_id: Optional[int],
) -> tuple[Optional[float], Optional[float]]:
    """Fill in ad.lat/lng from the linked house if missing.

    cian's offerData may lack `geo.coordinates` (rare, but happens). Without
    this fallback, the ad would render on the map as a bucket of ads from
    cian payload only (if any), or disappear from the map entirely. The
    `houses.lat/lng` is the ground truth (came from flatinfo or our own
    geocoder), so we always prefer it.
    """
    if ad.lat is not None and ad.lng is not None:
        return ad.lat, ad.lng
    if house_id is None:
        return ad.lat, ad.lng  # both None is fine
    row = await conn.fetchrow(
        "SELECT lat, lng FROM houses WHERE id=$1 AND lat IS NOT NULL AND lng IS NOT NULL",
        house_id,
    )
    if row is None:
        return ad.lat, ad.lng
    return float(row["lat"]), float(row["lng"])


async def _was_previously_active(
    conn: asyncpg.Connection, source: str, external_id: str
) -> bool:
    """Did this ad exist and was it is_active=True? (for stale cleanup)"""
    row = await conn.fetchrow(
        """
        SELECT is_active FROM active_ads
        WHERE source=$1 AND external_id=$2
        """,
        source, external_id,
    )
    return bool(row and row["is_active"])


async def _deactivate_ad(
    conn: asyncpg.Connection, source: str, external_id: str
) -> None:
    """Mark an ad as inactive in active_ads (without moving to sold_ads).

    Used when fetch failed (404/timeout) but the ad was previously
    is_active=True — i.e. the ad no longer exists on the source. We
    can't create a full sold_ads snapshot because we don't have the
    response to parse the final price/renovation/etc. We just flip
    is_active=false so it stops showing as "currently active".

    Going-forward, on a later successful fetch the ad would either:
      - be re-inserted via upsert (if the source brought it back), or
      - remain is_active=false (if the source keeps it removed)
    """
    await conn.execute(
        """
        UPDATE active_ads
        SET is_active=false, updated_at=NOW()
        WHERE source=$1 AND external_id=$2 AND is_active=true
        """,
        source, external_id,
    )


async def _move_to_sold(
    conn: asyncpg.Connection,
    source: str,
    ad: AdRecord,
    house_id: Optional[int],
) -> None:
    """Move an ad from ``active_ads`` to ``sold_ads``.

    Per user decision: stale ads (source said is_active=False on a
    re-fetch) are moved into ``sold_ads``. The row in ``active_ads``
    has ``is_active=false`` set so it stops showing as "currently active".

    Lat/lng are filled from the linked house if missing — sold_ads is
    shown on the map (synthetic clusters) and without coords it would
    just disappear. See scripts/_migration_sold_ads_lat_lng.sql.
    """
    # Fallback: if ad has no lat/lng, use the linked house's coords.
    lat, lng = await _resolve_ad_geo(conn, ad, house_id)
    # Upsert into sold_ads. Note: sold_ads has no `is_active` column
    # (the fact that an ad is in sold_ads IS the "inactive" state).
    await conn.execute(
        """
        INSERT INTO sold_ads (
            source, external_id, url, house_id, cian_house_id,
            price, price_per_m2, area, rooms, floor_current, floor_total,
            renovation, publish_date, sold_date,
            lat, lng,
            raw_data, parsed_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
            $12, $13, CURRENT_DATE,
            $14, $15,
            $16::json, NOW()
        )
        ON CONFLICT (source, external_id) DO UPDATE SET
            sold_date     = COALESCE(sold_ads.sold_date, CURRENT_DATE),
            house_id      = COALESCE(EXCLUDED.house_id, sold_ads.house_id),
            cian_house_id = COALESCE(EXCLUDED.cian_house_id, sold_ads.cian_house_id),
            price         = COALESCE(EXCLUDED.price, sold_ads.price),
            lat           = COALESCE(EXCLUDED.lat, sold_ads.lat),
            lng           = COALESCE(EXCLUDED.lng, sold_ads.lng),
            raw_data      = COALESCE(EXCLUDED.raw_data, sold_ads.raw_data)
        """,
        source,
        ad.external_id,
        ad.url,
        house_id,
        ad.cian_house_id,
        ad.price,
        ad.price_per_m2,
        ad.area,
        ad.rooms,
        ad.floor_current,
        ad.floor_total,
        ad.renovation,
        ad.publish_date,
        lat, lng,
        json.dumps(ad.raw_data, ensure_ascii=False, default=str),
    )
    # Mark active_ads as inactive
    await conn.execute(
        "UPDATE active_ads SET is_active=false WHERE source=$1 AND external_id=$2",
        source, ad.external_id,
    )


def _extract_sold_date(ad: AdRecord) -> Optional[datetime.date]:
    """Best-effort: достать sold_date из ad.raw_data или fallback.

    Приоритет:
      1. ``ad.raw_data['originalProduct']['soldDate']`` (domclick)
      2. ``ad.raw_data['soldDate']`` (top-level, на всякий случай)
      3. ``ad.raw_data['sold_date']`` (snake_case variant)
      4. ``ad.publish_date`` (если ad.publish_date — date)
      5. ``ad.publish_date`` (если ad.publish_date — ISO str)
    """
    if isinstance(ad.raw_data, dict):
        op = ad.raw_data.get("originalProduct")
        if isinstance(op, dict):
            sd = op.get("soldDate") or op.get("sold_date")
            if sd:
                try:
                    return datetime.datetime.fromisoformat(
                        str(sd).replace("Z", "+00:00")
                    ).date()
                except (ValueError, TypeError):
                    pass
        for key in ("soldDate", "sold_date"):
            sd = ad.raw_data.get(key)
            if sd:
                try:
                    return datetime.datetime.fromisoformat(
                        str(sd).replace("Z", "+00:00")
                    ).date()
                except (ValueError, TypeError):
                    pass
    if isinstance(ad.publish_date, datetime.date):
        return ad.publish_date
    if isinstance(ad.publish_date, str) and ad.publish_date:
        try:
            return datetime.datetime.fromisoformat(
                ad.publish_date.replace("Z", "+00:00")
            ).date()
        except (ValueError, TypeError):
            pass
    return None


def _extract_exposition_days(ad: AdRecord, sold_date: Optional[datetime.date]) -> Optional[int]:
    """days_in_exposition = (sold_date - publish_date).days, если оба есть."""
    pub = ad.publish_date
    if isinstance(pub, datetime.date) and sold_date:
        return max(0, (sold_date - pub).days)
    if isinstance(pub, str) and pub and sold_date:
        try:
            pd = datetime.datetime.fromisoformat(pub.replace("Z", "+00:00")).date()
            return max(0, (sold_date - pd).days)
        except (ValueError, TypeError):
            pass
    return None


async def _upsert_sold_ad(
    conn: asyncpg.Connection,
    source: str,
    ad: AdRecord,
    house_id: Optional[int],
    *,
    ad_lat: Optional[float] = None,
    ad_lng: Optional[float] = None,
) -> bool:
    """Upsert для sold-only источников (SourceParser.is_sold_source=True).

    Сразу пишем в ``sold_ads``, минуя ``active_ads`` и stale-cleanup path.
    Используется для domclick_sold, cian_sold, winners_sold и т.д. — то есть
    источников, у которых ВСЕ объявления уже проданы/сняты.

    Returns: True если новая строка, False если обновлена.
    """
    lat, lng = await _resolve_ad_geo(conn, ad, house_id)
    sold_date = _extract_sold_date(ad)
    exposition_days = _extract_exposition_days(ad, sold_date)

    row = await conn.fetchrow(
        """
        INSERT INTO sold_ads (
            source, external_id, url, house_id, cian_house_id,
            price, price_per_m2, area, rooms, floor_current, floor_total,
            renovation, exposition_days, publish_date, sold_date,
            lat, lng,
            raw_data, parsed_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
            $12, $13, $14, $15, $16, $17, $18::json, NOW()
        )
        ON CONFLICT (source, external_id) DO UPDATE SET
            url             = EXCLUDED.url,
            house_id        = COALESCE(EXCLUDED.house_id, sold_ads.house_id),
            cian_house_id   = COALESCE(EXCLUDED.cian_house_id, sold_ads.cian_house_id),
            price           = COALESCE(EXCLUDED.price, sold_ads.price),
            price_per_m2    = COALESCE(EXCLUDED.price_per_m2, sold_ads.price_per_m2),
            area            = COALESCE(EXCLUDED.area, sold_ads.area),
            rooms           = COALESCE(EXCLUDED.rooms, sold_ads.rooms),
            floor_current   = COALESCE(EXCLUDED.floor_current, sold_ads.floor_current),
            floor_total     = COALESCE(EXCLUDED.floor_total, sold_ads.floor_total),
            renovation      = COALESCE(EXCLUDED.renovation, sold_ads.renovation),
            exposition_days = COALESCE(EXCLUDED.exposition_days, sold_ads.exposition_days),
            publish_date    = COALESCE(EXCLUDED.publish_date, sold_ads.publish_date),
            sold_date       = COALESCE(EXCLUDED.sold_date, sold_ads.sold_date),
            lat             = COALESCE(EXCLUDED.lat, sold_ads.lat),
            lng             = COALESCE(EXCLUDED.lng, sold_ads.lng),
            raw_data        = EXCLUDED.raw_data
        RETURNING (xmax = 0) AS was_insert
        """,
        source,
        ad.external_id,
        ad.url,
        house_id,
        ad.cian_house_id,
        ad.price,
        ad.price_per_m2,
        ad.area,
        ad.rooms,
        ad.floor_current,
        ad.floor_total,
        ad.renovation,
        exposition_days,
        # publish_date: AD может прислать str (от cian_sold/domclick_sold) или date
        # asyncpg умеет принимать и str (parse), и date. Передаём как есть.
        ad.publish_date if isinstance(ad.publish_date, datetime.date) else
        (datetime.datetime.fromisoformat(ad.publish_date.replace("Z", "+00:00")).date()
         if isinstance(ad.publish_date, str) and ad.publish_date else None),
        sold_date,
        ad_lat if ad_lat is not None else lat,
        ad_lng if ad_lng is not None else lng,
        json.dumps(ad.raw_data, ensure_ascii=False, default=str),
    )
    return bool(row["was_insert"])


# --- Main pipeline ---------------------------------------------------------


async def run_source_pipeline(
    source: SourceParser,
    ad_external_ids: Iterable[str],
    *,
    auto_create_houses: bool = True,
    cleanup_stale: bool = True,
    link_after: bool = True,
    db_url: Optional[str] = None,
) -> dict:
    """Generic pipeline — works for any ``SourceParser``.

    Per ad:
      1. fetch_ad_page
      2. parse_ad → AdRecord
      3. match_or_create_house (cross-ref + spatial + optional auto-create)
      4. Upsert ad
      5. Stale cleanup (if is_active=False and was active): move to sold_ads

    After the loop, run the batch linker (link_after=True) to catch any
    stragglers (e.g. where the ad was previously inactive or the new
    auto-created houses need linking into other tables).
    """
    if db_url is None:
        db_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
        if db_url.startswith("postgresql+asyncpg://"):
            db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    t0 = time.monotonic()
    res = PipelineResult()
    ad_ids = list(ad_external_ids)
    log.info(
        "run_source_pipeline START: source=%s ads=%d auto_create=%s cleanup=%s link=%s",
        source.source_name, len(ad_ids), auto_create_houses, cleanup_stale, link_after,
    )

    conn = await asyncpg.connect(db_url)
    # v4: build flatinfo index once for the whole pipeline run
    log.info("building flatinfo address index...")
    index = await linker.build_flatinfo_index(conn)
    log.info("flatinfo index built: %d houses", index.n_houses)
    create_stats = _CreateStats()
    progress_every = max(25, len(ad_ids) // 20) if len(ad_ids) > 50 else 10
    try:
        for idx, ext_id in enumerate(ad_ids, 1):
            try:
                await _process_one_ad(
                    conn, source, ext_id,
                    index=index,
                    auto_create_houses=auto_create_houses,
                    cleanup_stale=cleanup_stale,
                    create_stats=create_stats,
                    res=res,
                )
            except Exception as exc:
                log.exception("Failed to process ad %s: %s", ext_id, exc)
                res.fetch_failures += 1

            if idx % progress_every == 0 or idx == len(ad_ids):
                elapsed = time.monotonic() - t0
                rate = idx / elapsed if elapsed > 0 else 0
                log.info(
                    "progress [%d/%d] %d processed, %d matched(exact=%d geo=%d), "
                    "%d sold, %d deactivated, %d fetch_fail, %d parse_fail, "
                    "%.1f ads/sec, %.0fs elapsed",
                    idx, len(ad_ids), res.ads_processed,
                    res.houses_matched_exact + res.houses_matched_geo,
                    res.houses_matched_exact, res.houses_matched_geo,
                    res.moved_to_sold, res.deactivated,
                    res.fetch_failures, res.parse_failures,
                    rate, elapsed,
                )

        res.houses_created = create_stats.created

        # Batch linker (post-batch, for any stragglers not caught by per-ad
        # match — e.g. ads that had no lat/lng at parse time, or ads that
        # were deactivated on this run)
        if link_after and res.ads_processed > 0:
            link_stats = await linker.link_ads(
                conn, ad_table="active_ads", ad_source=source.source_name, apply=True,
            )
            res.linked = link_stats.get("applied", 0)
    finally:
        await conn.close()

    log.info(
        "run_source_pipeline DONE in %.2fs: %s",
        time.monotonic() - t0, res.to_dict(),
    )
    return res.to_dict()


async def _process_one_ad(
    conn: asyncpg.Connection,
    source: SourceParser,
    ext_id: str,
    *,
    index: linker.FlatinfoIndex,
    auto_create_houses: bool,
    cleanup_stale: bool,
    create_stats: _CreateStats,
    res: PipelineResult,
) -> None:
    # 1. Fetch ad
    html = await source.fetch_ad_page(ext_id)
    if not html:
        res.fetch_failures += 1
        if cleanup_stale and await _was_previously_active(
            conn, source.source_name, ext_id
        ):
            await _deactivate_ad(conn, source.source_name, ext_id)
            res.deactivated += 1
            log.info("ad %s deactivated (fetch fail + previously active)", ext_id)
        return

    # 2. Parse ad
    ad = source.parse_ad(html)
    if ad is None:
        res.parse_failures += 1
        return

    # 3. Match to house via v4 index (address → spatial fallback)
    house_id = await linker.match_or_create_house(
        conn, ad,
        auto_create=auto_create_houses,
        create_stats=create_stats,
        index=index,
        source=source,  # source-agnostic auto-create (v2.1, 2026-08-05)
    )
    # v4 diagnostic: count how it matched (we don't expose exact/geo split
    # per call for simplicity, but we know it used address or spatial)
    if house_id is not None:
        res.houses_matched_geo += 1  # both address and spatial count here

    # 3a. Resolve ad.lat/lng — fall back to houses.lat/lng if missing.
    # Without this, the ad would not appear on the map (synthetic clusters
    # filter on lat/lng), or the marker would land at (0, 0).
    ad_lat, ad_lng = await _resolve_ad_geo(conn, ad, house_id)

    # 4. Branch: sold-only source (SourceParser.is_sold_source=True).
    # Сразу пишем в sold_ads, минуя active_ads и stale cleanup.
    # Используем getattr для обратной совместимости со старыми реализациями Protocol.
    if getattr(source, "is_sold_source", False):
        inserted = await _upsert_sold_ad(
            conn, source.source_name, ad, house_id,
            ad_lat=ad_lat, ad_lng=ad_lng,
        )
        res.ads_processed += 1
        if not inserted:
            res.ads_unchanged += 1
        return  # skip active_ads path

    # 5. Was the ad active BEFORE this fetch? (BEFORE the upsert)
    was_active = False
    if cleanup_stale:
        was_active = await _was_previously_active(conn, source.source_name, ext_id)

    # 6. Upsert ad (sets is_active to ad.is_active).
    inserted = await _upsert_ad(
        conn, source.source_name, ad, house_id,
        ad_lat=ad_lat, ad_lng=ad_lng,
    )
    res.ads_processed += 1
    if not inserted:
        res.ads_unchanged += 1

    # 7. Stale cleanup: active → inactive transition → move to sold_ads.
    if was_active and not ad.is_active:
        await _move_to_sold(conn, source.source_name, ad, house_id)
        res.moved_to_sold += 1

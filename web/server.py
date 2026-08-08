"""web/server.py — FastAPI backend for the Flipper map (Next.js + Leaflet).

**Архитектура v4 (2026-08-02):**

Карта = одна точка на реальный дом, у которого есть ЛЮБЫЕ cian-ads
(active или sold). Все 2,962 active ads и 231,316 sold ads в БД
привязаны к дому (house_id IS NOT NULL), synthetic-кластеры больше
не нужны. flatinfo остался как metadata lookup (year/type/levels/series)
в таблице `houses` (source='flatinfo'), но в /api/clusters не
возвращается — показываем только дома с cian-ads.

  - /api/clusters result is cached in-memory for 30s per bbox so
    map panning is instant after the first query.
  - Card-deck of ads per house: /api/clusters/{id}/ads.
  - Negative cluster_id → 404 (старые synthetic URL'ы с ?house=-...
    корректно отваливаются).

Endpoints:
  GET /                            — old static index.html (fallback)
  GET /api/stats                   — header counters
  GET /api/clusters                — houses with cian ads in bbox
  GET /api/clusters/{id}/ads       — active + sold ads for one house
  GET /api/houses                  — legacy cian view (kept for compat)
  GET /api/ads/map                 — all active ads as markers (legacy)
"""
from __future__ import annotations
import asyncio
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import text
import logging

log = logging.getLogger("flipper.web")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from packages.flipper_db import (
    CianSource,
    get_engine,
    get_session_factory,
    init_engine,
)  # noqa: E402

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"

app = FastAPI(title="Flipper Map", version="0.5.0")

# CORS origins — comma-separated list in $CORS_ORIGINS, or "*" for dev.
# Production example (in .env):
#   CORS_ORIGINS=https://flipper.example.com,https://www.flipper.example.com
_cors_env = os.getenv("CORS_ORIGINS", "*")
_cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Compress large JSON responses (e.g. /api/clusters with 1920 items ≈ 600KB
# → ~50KB gzipped). min_size=512 to skip tiny payloads.
app.add_middleware(GZipMiddleware, minimum_size=512)


# ---- App startup ----
# DB URL: prefer DATABASE_URL env (Docker: postgresql+asyncpg://...@app_postgres:5432/...),
# fall back to 127.0.0.1 for native dev (Windows). get_database_url() inside
# init_engine() handles the lookup; we just call it without args.
@app.on_event("startup")
async def _startup():
    init_engine()  # uses DATABASE_URL env or 127.0.0.1 default


# ---- Static fallback (for the old index.html) ----
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    idx = STATIC_DIR / "index.html"
    if idx.exists():
        return FileResponse(idx)
    return JSONResponse(
        {"error": "index.html not found. Use the Next.js app at http://127.0.0.1:3000/"},
        status_code=200,
    )


# Active offers live in active_ads (source='cian_active'). No view,
# no fallback — single source of truth.
OFFERS_TABLE = "active_ads"
ACTIVE_SOURCE_FILTER = "source='cian_active'"

# Sold (deactivated) offers live in sold_ads. Multiple sources:
#   - cian_deactivated — legacy name for cian_sold (231k rows)
#   - cian_sold        — new cian_sold records (via Source.CIAN_SOLD enum)
#   - domclick_sold    — domclick.ru (sold ads only, is_sold_source=True)
#   - winners_sold     — baza-winner.ru
# All four are surfaced as "deactivated" in the UI (sold/снятые).
SOLD_SOURCE_FILTER = "source IN ('cian_deactivated', 'cian_sold', 'domclick_sold', 'winners_sold')"


def _reconstruct_sold_url(source: str, external_id: str | None) -> str | None:
    """Build the public offer page URL when the `url` column is NULL.

    Legacy parsers didn't store the offer URL; we can rebuild it from
    `(source, external_id)` so the UI still has a link to "open on source".
    Returns None if the source is unknown.
    """
    if not external_id:
        return None
    if source in ("cian_deactivated", "cian_sold"):
        return f"https://www.cian.ru/sale/flat/{external_id}/"
    if source == "domclick_sold":
        return f"https://domclick.ru/card/sale?offerId={external_id}"
    if source == "winners_sold":
        return f"https://baza-winner.ru/card/{external_id}"
    return None


def _sold_ad_to_dict(d) -> dict:
    """Source-agnostic sold-ad → API dict.

    Two storage shapes in raw_data:
      - v2:      raw_data.deactivated.{title, prices, exposition, ...}
      - legacy:  cian_deactivated writes the deactivated object DIRECTLY into
                 raw_data (no nested "deactivated" key). Title/prices/etc. are
                 at the root, photos live in raw_data.details.images[].
    We try the nested key first, then fall back to root.
    """
    r = d.raw_data if isinstance(d.raw_data, dict) else {}
    dct = r.get("deactivated") if isinstance(r.get("deactivated"), dict) else r
    title = dct.get("title")
    prices = dct.get("prices") if isinstance(dct.get("prices"), dict) else {}
    exposition = dct.get("exposition")
    url = d.url or _reconstruct_sold_url(d.source, d.external_id)
    return {
        "id": d.external_id,
        "source": d.source,
        "external_id": d.external_id,
        "url": url,
        "price": d.price,
        "price_per_m2": d.price_per_m2,
        "area": d.area,
        "rooms": d.rooms,
        "floor_current": d.floor_current,
        "floor_total": d.floor_total,
        "renovation": d.renovation,
        "days_in_exposition": d.exposition_days,
        "publish_date": d.publish_date.isoformat() if d.publish_date else None,
        "date_end": d.sold_date.isoformat() if d.sold_date else None,
        "title": title,
        "price_diff": prices.get("priceDiff") if prices else None,
        "exposition": exposition,
        # Отдаём raw_data как есть — для cian_deactivated тут лежат photos,
        # для domclick_sold — photo_urls + originalProduct.
        "raw_data": r,
    }


# ---- /api/clusters TTL cache (bbox → pre-serialized JSON bytes, 30s) ----
# Map panning fires many requests with overlapping bboxes. A 30s
# in-process cache turns subsequent panning into sub-ms lookups. We
# cache the JSON bytes (not the Python list) so the response is a
# direct sendfile — no jsonable_encoder / dict-iteration cost on the
# hot path. Output only changes when an ad is added/removed, so 30s
# is safe for an interactive map.
import time as _time
import json as _json
_clusters_cache: dict[tuple, tuple[float, bytes]] = {}
_CLUSTERS_TTL_S = 30.0


def _clusters_cache_key(min_lat, max_lat, min_lng, max_lng, with_ads_only, limit) -> tuple:
    return (
        round(min_lat or 0, 4),
        round(max_lat or 0, 4),
        round(min_lng or 0, 4),
        round(max_lng or 0, 4),
        bool(with_ads_only),
        int(limit),
    )


# ---- API ----
@app.get("/api/stats")
async def stats():
    """Top-bar counters for the UI."""
    sf = get_session_factory()
    async with sf() as s:
        row = (await s.execute(text(f"""
            SELECT
              (SELECT COUNT(*) FROM houses) AS houses,
              (SELECT COUNT(*) FROM houses WHERE lat IS NOT NULL) AS houses_with_coords,
              (SELECT COUNT(*) FROM {OFFERS_TABLE} WHERE {ACTIVE_SOURCE_FILTER}) AS active_total,
              (SELECT COUNT(*) FROM {OFFERS_TABLE} WHERE {ACTIVE_SOURCE_FILTER} AND house_id IS NOT NULL) AS active_linked,
              (SELECT COUNT(*) FROM {OFFERS_TABLE} WHERE {ACTIVE_SOURCE_FILTER} AND house_id IS NULL) AS active_unlinked,
              (SELECT COUNT(DISTINCT house_id) FROM {OFFERS_TABLE} WHERE {ACTIVE_SOURCE_FILTER} AND house_id IS NOT NULL) AS houses_with_ads,
              (SELECT COUNT(*) FROM sold_ads WHERE {SOLD_SOURCE_FILTER}) AS deactivated_total,
              (SELECT COUNT(DISTINCT house_id) FROM sold_ads
                 WHERE {SOLD_SOURCE_FILTER} AND house_id IS NOT NULL) AS houses_with_deactivated
        """))).first()
        by_source = (await s.execute(text("""
            SELECT source, COUNT(*) AS n FROM houses GROUP BY source ORDER BY source
        """))).all()
        # Per-source breakdowns — UI хочет показывать "ЦИАН 5 000 / ДомКлик 50 / Победители 200".
        # Считаем ВСЕ источники (включая те, которых нет в SOLD_SOURCE_FILTER
        # — чтобы UI мог сам отфильтровать), но помечаем "active" vs "deactivated".
        active_by_source = (await s.execute(text("""
            SELECT source, COUNT(*) AS n FROM active_ads
            GROUP BY source ORDER BY source
        """))).all()
        sold_by_source = (await s.execute(text("""
            SELECT source, COUNT(*) AS n FROM sold_ads GROUP BY source ORDER BY source
        """))).all()
    return {
        "houses": row.houses,
        "houses_with_coords": row.houses_with_coords,
        "active_total": row.active_total,
        "active_linked": row.active_linked,
        "active_unlinked": row.active_unlinked,
        "houses_with_ads": row.houses_with_ads,
        "deactivated_total": row.deactivated_total,
        "houses_with_deactivated": row.houses_with_deactivated,
        "houses_by_source": {r.source: r.n for r in by_source},
        "active_by_source": {r.source: r.n for r in active_by_source},
        "sold_by_source": {r.source: r.n for r in sold_by_source},
        "offers_source": OFFERS_TABLE,
    }


@app.get("/api/pipeline/last-run")
async def pipeline_last_run():
    """Когда в последний раз отрабатывал pipeline_runner.

    Scheduler'у нужен этот endpoint для health-check: если >36ч без
    успешного прогона → алерт в TG. Таблицу ``pipeline_runs`` создаёт
    ``services/pipeline_runner/main.py`` (там же пишет результат).

    Также показываем ``fresh_seconds_ago`` — удобно для UI badge'а.
    """
    sf = get_session_factory()
    try:
        async with sf() as s:
            row = (await s.execute(text("""
                SELECT
                    max(finished_at) FILTER (WHERE status='OK') AS last_ok,
                    max(finished_at) AS last_any,
                    count(*) FILTER (WHERE status='OK') AS n_ok,
                    count(*) FILTER (WHERE status='FAILED') AS n_failed,
                    count(*) AS n_total
                FROM pipeline_runs
                WHERE source='cian_active'
            """))).first()
    except Exception as exc:
        # Таблицы может не быть — pipeline_runner ещё ни разу не запускался
        return {
            "last_ok": None,
            "last_any": None,
            "n_ok": 0,
            "n_failed": 0,
            "n_total": 0,
            "fresh_seconds_ago": None,
            "status": "never_run",
            "error": str(exc),
        }

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    last_ok = row.last_ok
    if last_ok is not None and last_ok.tzinfo is None:
        from datetime import timezone as _tz
        last_ok = last_ok.replace(tzinfo=_tz.utc)
    fresh_s = (now - last_ok).total_seconds() if last_ok else None
    status = "fresh" if (fresh_s is not None and fresh_s < 36 * 3600) else "stale"
    return {
        "last_ok": last_ok.isoformat() if last_ok else None,
        "last_any": row.last_any.isoformat() if row.last_any else None,
        "n_ok": row.n_ok or 0,
        "n_failed": row.n_failed or 0,
        "n_total": row.n_total or 0,
        "fresh_seconds_ago": fresh_s,
        "status": status,
    }


@app.get("/api/houses")
async def houses(
    min_lat: Optional[float] = Query(None),
    max_lat: Optional[float] = Query(None),
    min_lng: Optional[float] = Query(None),
    max_lng: Optional[float] = Query(None),
    with_ads_only: bool = Query(False),
    limit: int = Query(50000, ge=1, le=50000),
):
    """Return cian-домы (через view ``cian_houses_map``) в текущем viewport.

    Каждый item:
        id              = PK в houses (для detail endpoint legacy)
        cian_house_id   = канонический id дома в cian.ru
        address         = полный адрес
        lat, lng        = координаты
        source          = откуда пришёл (cian, cian_active, cian_api_house)
        active_count    = сколько наших parsed active ads на этот дом
        deactivated_count = сколько наших parsed sold ads на этот дом
        parsed_data_available = True если в нашей БД есть parsed data

    Карта рисует **одну точку на дом** (cian house id), не на ad.
    """
    where = ["cm.lat IS NOT NULL", "cm.lng IS NOT NULL"]
    params: dict = {"limit": limit}
    if min_lat is not None and max_lat is not None:
        where.append("cm.lat BETWEEN :min_lat AND :max_lat")
        params.update(min_lat=min_lat, max_lat=max_lat)
    if min_lng is not None and max_lng is not None:
        where.append("cm.lng BETWEEN :min_lng AND :max_lng")
        params.update(min_lng=min_lng, max_lng=max_lng)
    if with_ads_only:
        where.append("""(
            EXISTS (SELECT 1 FROM active_ads aa
                    WHERE aa.cian_house_id = cm.cian_house_id AND aa.source='cian_active')
            OR EXISTS (SELECT 1 FROM dashboard_parsed_ads dpa
                    WHERE dpa.cian_house_id = cm.cian_house_id AND dpa.status='published')
        )""")
    where_sql = " AND ".join(where)
    sf = get_session_factory()
    async with sf() as s:
        rows = (await s.execute(text(f"""
            SELECT
              cm.cian_house_id,
              cm.house_id,
              cm.address,
              cm.lat,
              cm.lng,
              cm.source,
              (SELECT COUNT(*) FROM active_ads aa
                  WHERE aa.cian_house_id = cm.cian_house_id AND aa.source='cian_active') AS active_count,
              (SELECT COUNT(*) FROM dashboard_parsed_ads dpa
                  WHERE dpa.cian_house_id = cm.cian_house_id) AS parsed_count,
              (SELECT COUNT(*) FROM dashboard_parsed_ads dpa
                  WHERE dpa.cian_house_id = cm.cian_house_id AND dpa.status='deactivated') AS deactivated_count
            FROM cian_houses_map cm
            WHERE {where_sql}
            ORDER BY cm.cian_house_id
            LIMIT :limit
        """), params)).all()
    return [
        {
            "id": r.house_id,                                # legacy: PK
            "cian_house_id": r.cian_house_id,                # canonical
            "house_id": r.cian_house_id,                    # alias for UI
            "address": r.address,
            "lat": float(r.lat) if r.lat is not None else None,
            "lng": float(r.lng) if r.lng is not None else None,
            "source": r.source,
            "active_count": r.active_count or 0,
            "parsed_count": r.parsed_count or 0,
            "deactivated_count": r.deactivated_count or 0,
        }
        for r in rows
    ]


# Cache for CianSource (singleton)
_cian_source_singleton: Optional[CianSource] = None
_cian_source_lock = asyncio.Lock()


async def _get_cian_source() -> CianSource:
    """Get or create a singleton CianSource (used by /by-cian endpoints)."""
    global _cian_source_singleton
    async with _cian_source_lock:
        if _cian_source_singleton is None:
            _cian_source_singleton = CianSource()
        return _cian_source_singleton


@app.get("/api/houses/by-cian/{cian_id}/ads")
async def cian_house_ads(cian_id: int):
    """Return ALL ads (active + deactivated) for a cian house.

    Uses cian public API (https://api.cian.ru/valuation-offer-history/v4/)
    as source of truth. Also merges with our local dashboard_parsed_ads
    (when we have flippercrawl-parsed data for the same cian ad).

    Returns:
        {
          "cian_house_id": int,
          "total": int,
          "active_count": int,
          "deactivated_count": int,
          "active": [ {id, title, price, area, rooms, ..., source: "cian_api"|"dashboard_parsed"} ],
          "deactivated": [ {id, title, price, ..., dateStart, dateEnd, source: "cian_api"|"dashboard_parsed"} ],
          "from_cache": bool,  # True если все из нашей БД (cian API недоступен)
        }
    """
    sf = get_session_factory()
    # Сначала пробуем нашу БД (active_ads — главный источник, 3,399 живых ads;
    # dashboard_parsed_ads — full offerData когда распарсили через flippercrawl;
    # sold_ads — снятые, для deactivated вкладки)
    async with sf() as s:
        # 1) active_ads (то что у нас сейчас активно)
        # NB: в active_ads поле cian_id (не external_id) — алиасим как external_id для merge
        active_rows_res = await s.execute(
            text("""SELECT cian_id AS external_id, price, price_per_m2,
                         area, rooms, floor_current, floor_total,
                         days_in_exposition, publish_date, url, raw_data,
                         is_active, metro_station
                  FROM active_ads
                  WHERE cian_house_id = :cid"""),
            {"cid": cian_id},
        )
        active_rows = active_rows_res.fetchall()

        # 2) dashboard_parsed_ads (full offerData из flippercrawl)
        dpa_res = await s.execute(
            text("""SELECT external_id, status, title, price, price_per_m2,
                         area, rooms, floor_current, floor_total, exposition_days,
                         date_start, date_end, url, raw_data, parsed_at
                  FROM dashboard_parsed_ads
                  WHERE cian_house_id = :cid"""),
            {"cid": cian_id},
        )
        dpa_rows = dpa_res.fetchall()

        # 3) sold_ads (снятые, но в нашей БД)
        sold_res = await s.execute(
            text("""SELECT external_id, price, price_per_m2,
                         area, rooms, floor_current, floor_total,
                         exposition_days, publish_date, sold_date, url
                  FROM sold_ads
                  WHERE source='cian_deactivated' AND cian_house_id = :cid
                  ORDER BY sold_date DESC NULLS LAST
                  LIMIT 100"""),
            {"cid": cian_id},
        )
        sold_rows = sold_res.fetchall()

    # Параллельно дёргаем cian API (если нет в БД или для полноты)
    cian_active: list[dict] = []
    cian_deactivated: list[dict] = []
    cian_offers: list[dict] = []  # всё что вернул cian API
    cian_api_ok = False

    try:
        source = await _get_cian_source()
        history = await source.fetch_house_offer_history(cian_id)
        if history and isinstance(history.get("offers"), list):
            cian_api_ok = True
            for raw_offer in history["offers"]:
                offer = source.parse_house_history_offer(raw_offer)
                cian_offers.append({"id": offer["external_id"], "raw": offer})
                if offer["status"] == "published":
                    cian_active.append(offer)
                else:
                    cian_deactivated.append(offer)
    except Exception as exc:
        log.warning("cian house history fetch failed for %s: %s", cian_id, exc)

    # Мерж: три источника объединяются по external_id (cian house ad id):
    #   1. active_ads    — то что у нас сейчас live (3,399 живых ads)
    #   2. sold_ads      — снятые, но в нашей БД (deactivated вкладка)
    #   3. dashboard_parsed_ads — full offerData (когда распарсили через flippercrawl)
    #   4. cian API      — live данные с cian.ru (если не captcha)
    #
    # Приоритет (если один external_id есть в нескольких):
    #   cian_api > dashboard_parsed > active_ads (для live) / sold_ads (для снятых)
    out_active: list[dict] = []
    out_deactivated: list[dict] = []
    seen_active: set[str] = set()
    seen_deactivated: set[str] = set()

    # Словарь parsed data (full offerData) по external_id
    parsed_by_id: dict[str, dict] = {}
    for r in dpa_rows:
        if not r.external_id:
            continue
        parsed_by_id[str(r.external_id)] = {
            "external_id": r.external_id,
            "status": r.status,
            "title": r.title,
            "price": r.price,
            "price_per_m2": r.price_per_m2,
            "area": r.area,
            "rooms": r.rooms,
            "floor_current": r.floor_current,
            "floor_total": r.floor_total,
            "exposition_days": r.exposition_days,
            "date_start": r.date_start,
            "date_end": r.date_end,
            "url": r.url,
            "metro_station": r.metro_station,
            "district": r.district,
            "okrug": r.okrug,
            "raw_data": r.raw_data,
            "parsed_at": r.parsed_at,
        }

    def _enrich_with_parsed(item: dict, eid: str) -> None:
        """Дополнить item полями из dashboard_parsed_ads если есть."""
        if eid in parsed_by_id:
            p = parsed_by_id[eid]
            item.update({
                "area": p.get("area"),
                "rooms": p.get("rooms"),
                "floor_current": p.get("floor_current"),
                "floor_total": p.get("floor_total"),
                "raw_data": p.get("raw_data"),
                "source_detail": "dashboard_parsed",
            })

    # 1) cian API сначала (приоритет)
    for cian_offer in cian_active:
        eid = cian_offer["external_id"]
        seen_active.add(eid)
        item = {
            "external_id": eid,
            "title": cian_offer["title"],
            "price": cian_offer["price_text"],
            "price_per_m2": cian_offer["price_per_m2_text"],
            "exposition_days": cian_offer["exposition_days"],
            "status": "published",
            "source": "cian_api",
            "has_parsed_data": eid in parsed_by_id,
        }
        _enrich_with_parsed(item, eid)
        out_active.append(item)

    for cian_offer in cian_deactivated:
        eid = cian_offer["external_id"]
        seen_deactivated.add(eid)
        item = {
            "external_id": eid,
            "title": cian_offer["title"],
            "price": cian_offer["price_text"],
            "price_per_m2": cian_offer["price_per_m2_text"],
            "exposition_days": cian_offer["exposition_days"],
            "date_start": cian_offer["date_start"],
            "date_end": cian_offer["date_end"],
            "status": "deactivated",
            "source": "cian_api",
            "has_parsed_data": eid in parsed_by_id,
        }
        _enrich_with_parsed(item, eid)
        out_deactivated.append(item)

    # 2) active_ads (то что у нас live)
    for r in active_rows:
        eid = str(r.external_id) if r.external_id else ""
        if not eid or eid in seen_active:
            continue
        seen_active.add(eid)
        item = {
            "external_id": eid,
            "price": r.price,
            "price_per_m2": r.price_per_m2,
            "area": r.area,
            "rooms": r.rooms,
            "floor_current": r.floor_current,
            "floor_total": r.floor_total,
            "exposition_days": r.days_in_exposition,
            "publish_date": r.publish_date.isoformat() if r.publish_date else None,
            "url": r.url,
            "status": "published" if r.is_active else "deactivated",
            "source": "active_ads",
            "has_parsed_data": eid in parsed_by_id,
        }
        _enrich_with_parsed(item, eid)
        if item["status"] == "published":
            out_active.append(item)
        else:
            if eid not in seen_deactivated:
                seen_deactivated.add(eid)
                out_deactivated.append(item)

    # 3) sold_ads (снятые, но в нашей БД)
    for r in sold_rows:
        eid = str(r.external_id) if r.external_id else ""
        if not eid or eid in seen_deactivated or eid in seen_active:
            continue
        seen_deactivated.add(eid)
        item = {
            "external_id": eid,
            "price": r.price,
            "price_per_m2": r.price_per_m2,
            "area": r.area,
            "rooms": r.rooms,
            "floor_current": r.floor_current,
            "floor_total": r.floor_total,
            "exposition_days": r.exposition_days,
            "publish_date": r.publish_date.isoformat() if r.publish_date else None,
            "sold_date": r.sold_date.isoformat() if r.sold_date else None,
            "url": r.url,
            "status": "deactivated",
            "source": "sold_ads",
            "has_parsed_data": eid in parsed_by_id,
        }
        _enrich_with_parsed(item, eid)
        out_deactivated.append(item)

    return {
        "cian_house_id": cian_id,
        "total": len(out_active) + len(out_deactivated),
        "active_count": len(out_active),
        "deactivated_count": len(out_deactivated),
        "active": out_active,
        "deactivated": out_deactivated,
        "from_cache": not cian_api_ok,
    }


@app.get("/api/dashboard/parsed/{cian_id}")
async def dashboard_parsed(cian_id: int):
    """Dashboard: full parsed data для дома (отдельная таблица, не карта).

    Возвращает все parsed ads для дома. Если пусто — парсим через flippercrawl
    на лету и сохраняем в dashboard_parsed_ads (lazy parse). Следующий раз
    будет взято из БД.
    """
    sf = get_session_factory()
    async with sf() as s:
        result = await s.execute(
            text("""SELECT external_id, status, title, price, price_per_m2,
                         area, rooms, floor_current, floor_total, exposition_days,
                         date_start, date_end, url, address_full, metro_station,
                         district, okrug, raw_data, cian_extraction_mode,
                         parsed_at, updated_at
                  FROM dashboard_parsed_ads
                  WHERE cian_house_id = :cid
                  ORDER BY status, parsed_at DESC"""),
            {"cid": cian_id},
        )
        rows = result.fetchall()
        if not rows:
            # Lazy parse: тянем через flippercrawl, сохраняем в dashboard_parsed_ads
            # Берём cian ads с этого дома (если есть в наших active_ads)
            ad_rows_res = await s.execute(
                text("""SELECT external_id FROM active_ads
                         WHERE cian_house_id = :cid AND source='cian_active'"""),
                {"cid": cian_id},
            )
            ad_rows = ad_rows_res.fetchall()
            if not ad_rows:
                raise HTTPException(404, f"no ads for cian house {cian_id}")

            source = await _get_cian_source()
            new_rows: list[dict] = []
            for ad_row in ad_rows:
                ext_id = str(ad_row["external_id"])
                resp_text = await source.fetch_ad_page(ext_id)
                if not resp_text:
                    continue
                ad = source.parse_ad(resp_text)
                if not ad or not ad.raw_data:
                    continue
                offer = ad.raw_data.get("offer", {})
                building = offer.get("building", {})
                geo = offer.get("geo", {})
                bargain = offer.get("bargainTerms", {})
                # extract cian_house_id from offer.geo.address[type=house].id
                house_id_int = None
                for a in (geo.get("address") or []):
                    if isinstance(a, dict) and a.get("type") == "house":
                        try:
                            house_id_int = int(a.get("id"))
                        except (TypeError, ValueError):
                            pass
                        break
                if house_id_int is None:
                    try:
                        house_id_int = int(cian_id)
                    except Exception:
                        house_id_int = cian_id
                # extract metro
                metro = None
                metros = geo.get("undergrounds") or []
                if metros:
                    metro = metros[0].get("name")
                # price
                price = None
                try:
                    price = int(bargain.get("price")) if bargain.get("price") else None
                except (TypeError, ValueError):
                    price = None
                # date_start (creationDate)
                date_start = None
                creation = offer.get("creationDate")
                if isinstance(creation, str) and creation:
                    from datetime import datetime as _dt
                    try:
                        date_start = _dt.fromisoformat(
                            creation.replace("Z", "+00:00")
                        ).date()
                    except ValueError:
                        pass

                row = {
                    "cian_house_id": house_id_int,
                    "external_id": ext_id,
                    "status": "published" if ad.is_active else "deactivated",
                    "title": offer.get("title"),
                    "price": price,
                    "price_per_m2": (offer.get("priceInfo") or {}).get("pricePerSquareValue"),
                    "area": _to_float(offer.get("totalArea")),
                    "rooms": offer.get("roomsCount"),
                    "floor_current": offer.get("floorNumber"),
                    "floor_total": building.get("floorsCount"),
                    "exposition_days": None,
                    "date_start": date_start,
                    "date_end": None,
                    "url": ad.url,
                    "address_full": ad.address,
                    "metro_station": metro,
                    "district": ad.district,
                    "okrug": ad.okrug,
                    "raw_data": ad.raw_data,
                    "cian_extraction_mode": ad.raw_data.get("_extraction_mode", "static"),
                }
                # upsert
                await s.execute(
                    text("""INSERT INTO dashboard_parsed_ads (
                        cian_house_id, external_id, status, title, price, price_per_m2,
                        area, rooms, floor_current, floor_total, exposition_days,
                        date_start, date_end, url, address_full, metro_station,
                        district, okrug, raw_data, cian_extraction_mode,
                        parsed_at, updated_at
                    ) VALUES (
                        :cian_house_id, :external_id, :status, :title, :price, :price_per_m2,
                        :area, :rooms, :floor_current, :floor_total, :exposition_days,
                        :date_start, :date_end, :url, :address_full, :metro_station,
                        :district, :okrug, CAST(:raw_data AS json), :cian_extraction_mode,
                        NOW(), NOW()
                    )
                    ON CONFLICT (cian_house_id, external_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        title = EXCLUDED.title,
                        price = EXCLUDED.price,
                        price_per_m2 = EXCLUDED.price_per_m2,
                        area = EXCLUDED.area,
                        rooms = EXCLUDED.rooms,
                        floor_current = EXCLUDED.floor_current,
                        floor_total = EXCLUDED.floor_total,
                        exposition_days = EXCLUDED.exposition_days,
                        date_start = EXCLUDED.date_start,
                        date_end = EXCLUDED.date_end,
                        url = EXCLUDED.url,
                        address_full = EXCLUDED.address_full,
                        metro_station = EXCLUDED.metro_station,
                        district = EXCLUDED.district,
                        okrug = EXCLUDED.okrug,
                        raw_data = EXCLUDED.raw_data,
                        cian_extraction_mode = EXCLUDED.cian_extraction_mode,
                        updated_at = NOW()
                    """),
                    {
                        "cian_house_id": row["cian_house_id"],
                        "external_id": row["external_id"],
                        "status": row["status"],
                        "title": row["title"],
                        "price": row["price"],
                        "price_per_m2": row["price_per_m2"],
                        "area": row["area"],
                        "rooms": row["rooms"],
                        "floor_current": row["floor_current"],
                        "floor_total": row["floor_total"],
                        "exposition_days": row["exposition_days"],
                        "date_start": row["date_start"],
                        "date_end": row["date_end"],
                        "url": row["url"],
                        "address_full": row["address_full"],
                        "metro_station": row["metro_station"],
                        "district": row["district"],
                        "okrug": row["okrug"],
                        "raw_data": json.dumps(row["raw_data"], default=str),
                        "cian_extraction_mode": row["cian_extraction_mode"],
                    },
                )
                new_rows.append(row)
            await s.commit()
            rows = new_rows  # use just-parsed rows for response

    # Render
    import json as _json
    return {
        "cian_house_id": cian_id,
        "count": len(rows),
        "ads": [
            {
                "external_id": r["external_id"],
                "status": r["status"],
                "title": r["title"],
                "price": r["price"],
                "price_per_m2": r["price_per_m2"],
                "area": float(r["area"]) if r["area"] is not None else None,
                "rooms": r["rooms"],
                "floor_current": r["floor_current"],
                "floor_total": r["floor_total"],
                "exposition_days": r["exposition_days"],
                "date_start": r["date_start"].isoformat() if r["date_start"] else None,
                "date_end": r["date_end"].isoformat() if r["date_end"] else None,
                "url": r["url"],
                "address_full": r["address_full"],
                "metro_station": r["metro_station"],
                "district": r["district"],
                "okrug": r["okrug"],
                "raw_data": r["raw_data"] if isinstance(r["raw_data"], dict) else (
                    _json.loads(r["raw_data"]) if r["raw_data"] else None
                ),
                "cian_extraction_mode": r["cian_extraction_mode"],
                "parsed_at": r["parsed_at"].isoformat() if r["parsed_at"] else None,
            }
            for r in rows
        ],
    }


def _to_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "."))
        except ValueError:
            return None
    return None


@app.get("/api/houses/{house_id}")
async def house_detail(house_id: int):
    """House detail + active ads + deactivated ads (up to 100)."""
    sf = get_session_factory()
    async with sf() as s:
        house = (await s.execute(text("""
            SELECT id, source, external_house_id, cian_house_id, address, street, house_num,
                   lat, lng, year_built, levels, building_type, series
            FROM houses WHERE id = :id
        """), {"id": house_id})).first()
        if not house:
            raise HTTPException(404, "house not found")

        active = (await s.execute(text(f"""
            SELECT id, external_id, source, url, price, price_per_m2, area, rooms,
                   floor_current, floor_total, metro_station, metro_walk_time,
                   district, okrug, renovation, days_in_exposition, publish_date, filter_id,
                   raw_data
            FROM {OFFERS_TABLE}
            WHERE house_id = :id AND source = 'cian_active'
            ORDER BY price NULLS LAST
        """), {"id": house_id})).all()

        deactivated = (await s.execute(text(f"""
            SELECT external_id, source, url, price, price_per_m2, area, rooms,
                   floor_current, floor_total, renovation,
                   exposition_days, publish_date, sold_date, raw_data
            FROM sold_ads
            WHERE {SOLD_SOURCE_FILTER} AND house_id = :id
            ORDER BY sold_date DESC NULLS LAST
            LIMIT 100
        """), {"id": house_id})).all()

    def raw(d):
        return d.raw_data if isinstance(d.raw_data, dict) else {}

    def deact_to_dict(d):
        """Sold ad → dict for /api/houses/{id} response. Source-agnostic (v2)."""
        return _sold_ad_to_dict(d)

    def active_to_dict(a):
        rd = a.raw_data if isinstance(a.raw_data, dict) else None
        return {
            "id": a.id,
            "source": a.source,
            "external_id": a.external_id,
            "url": a.url,
            "price": a.price,
            "price_per_m2": a.price_per_m2,
            "area": a.area,
            "rooms": a.rooms,
            "floor_current": a.floor_current,
            "floor_total": a.floor_total,
            "metro_station": a.metro_station,
            "metro_walk_time": a.metro_walk_time,
            "district": a.district,
            "okrug": a.okrug,
            "renovation": a.renovation,
            "days_in_exposition": a.days_in_exposition,
            "publish_date": a.publish_date.isoformat() if a.publish_date else None,
            "filter_id": a.filter_id,
            "raw_data": rd,
        }

    def _parse_ext_id(v):
        """external_house_id хранится либо как int-строка (flatinfo, cian_sold),
        либо как 'ad_<int>' (cian_ad). Возвращаем int или None."""
        if not v:
            return None
        s = str(v).strip()
        if s.startswith("ad_"):
            s = s[3:]
        try:
            return int(s)
        except (ValueError, TypeError):
            return None

    return {
        "house": {
            "id": house.id,
            "house_id": _parse_ext_id(house.external_house_id),
            "source": house.source,
            "cian_house_id": house.cian_house_id,
            "address": house.address,
            "street": house.street,
            "house_num": house.house_num,
            "lat": float(house.lat) if house.lat is not None else None,
            "lng": float(house.lng) if house.lng is not None else None,
            "year": house.year_built,
            "type": house.building_type,
            "levels": house.levels,
            "series": house.series,
        },
        "active": [active_to_dict(a) for a in active],
        "deactivated": [deact_to_dict(d) for d in deactivated],
        "stats": {
            "total_active": len(active),
            "total_deactivated": len(deactivated),
        },
    }


@app.get("/api/clusters")
async def clusters(
    min_lat: Optional[float] = Query(None),
    max_lat: Optional[float] = Query(None),
    min_lng: Optional[float] = Query(None),
    max_lng: Optional[float] = Query(None),
    zoom: int = Query(15, ge=1, le=22),
    with_ads_only: bool = Query(True),
    limit: int = Query(50000, ge=1, le=50000),
):
    """Map points for the current viewport.

    Two modes depending on `zoom`:
      - zoom >= 15: one row per real house (with active/sold counts).
        Use this for street-level work where the user clicks houses.
      - zoom <  15: server-side grid clusters. Each row is a square
        cell of ~100m..2km, with the count of houses inside plus
        summed active/sold counts. The client renders a bubble with
        the house count; clicking zooms in.

    The cell shrinks as zoom increases so the on-screen cluster size
    stays roughly constant. Tuned for CartoDB tile pyramid (z11 ≈ 5.5km
    cell, z14 ≈ 440m cell).

    Both modes share the same WHERE filter (houses with at least one
    ad from any source — cian_active, cian_deactivated, cian_sold,
    domclick_sold, winners_sold — either active or sold). Orphan ads
    (house_id IS NULL) are not shown — 100% of our ads are linked, so
    this filter doesn't drop anything real.
    """
    # Cell size (degrees lat) for grid clustering. At Moscow's latitude,
    # 1° lng ≈ 62km, so for "square" cells we use the same value for
    # both axes (it'll be slightly stretched horizontally — acceptable
    # for clusters since they're just visual groupings).
    #
    # Tuned to match 2GIS-style overview:
    #   z=11  → 3-5  big clusters (whole Moscow)
    #   z=12  → 6-10  clusters (one per district)
    #   z=13  → 20-30 clusters (one per neighborhood)
    #   z=14  → 80-120 clusters (one per block)
    #   z=15+ → individual houses
    if zoom <= 11:
        cell = 0.05   # ~5.5km
    elif zoom == 12:
        cell = 0.025  # ~2.8km
    elif zoom == 13:
        cell = 0.010  # ~1.1km
    elif zoom == 14:
        cell = 0.003  # ~330m
    else:
        cell = 0.0   # signal: no clustering, return houses

    # TTL cache: bbox+zoom+cell → (timestamp, JSON bytes). Map panning
    # fires many requests with overlapping bboxes; the cache turns them
    # into sub-ms lookups. Output only changes when an ad is added/
    # removed, so 30s is safe for an interactive map.
    cache_key = _clusters_cache_key(
        min_lat, max_lat, min_lng, max_lng, with_ads_only, limit
    ) + (zoom, cell)
    cached = _clusters_cache.get(cache_key)
    if cached is not None:
        ts, payload_bytes = cached
        if _time.time() - ts < _CLUSTERS_TTL_S:
            return Response(content=payload_bytes, media_type="application/json; charset=utf-8")

    sf = get_session_factory()
    params: dict = {"limit": limit, "cell": cell}
    where_clauses = [
        "h.lat IS NOT NULL",
        "h.lng IS NOT NULL",
    ]
    if min_lat is not None and max_lat is not None:
        where_clauses.append("h.lat BETWEEN :min_lat AND :max_lat")
        params["min_lat"] = min_lat
        params["max_lat"] = max_lat
    if min_lng is not None and max_lng is not None:
        where_clauses.append("h.lng BETWEEN :min_lng AND :max_lng")
        params["min_lng"] = min_lng
        params["max_lng"] = max_lng
    # When `with_ads_only=True` (default), only houses that have at least
    # one ad (any source: cian_active | domclick_sold | winners_sold | etc.)
    # show up. When False, every house with lat/lng is shown — this is
    # what the user wants: a real building should be findable on the map
    # even if no one has ever posted an ad there. The grid clusters at
    # z<15 aggregate everything naturally, so the visual cost is mostly
    # bounded to z>=15.
    if with_ads_only:
        # NB: в subqueries явно квалифицируем колонку (`sold_ads.source`),
        # чтобы Postgres не путал с LEFT JOIN алиасом `s` снаружи.
        where_clauses.append(f"""
            (
                EXISTS (
                  SELECT 1 FROM active_ads
                  WHERE active_ads.house_id = h.id
                    AND {ACTIVE_SOURCE_FILTER}
                    AND active_ads.is_active=true
                )
                OR EXISTS (
                  SELECT 1 FROM sold_ads
                  WHERE sold_ads.house_id = h.id
                    AND sold_ads.source IN ('cian_deactivated', 'cian_sold', 'domclick_sold', 'winners_sold')
                )
            )
        """)
    where_sql = " AND ".join(where_clauses)

    async with sf() as s:
        if cell > 0:
            # Grid clusters. The cluster's pin point is the **centroid
            # of the actual houses** in the cell (AVG lat/lng), not the
            # geometric center of the cell. The geometric center can
            # fall in a river, park, or empty block and look like the
            # cluster isn't on any real building. Centroid always
            # lands on a real house position so the cluster follows
            # the city's actual shape.
            rows = (await s.execute(text(f"""
                WITH houses_with_ads AS (
                    SELECT
                        h.id            AS house_id,
                        h.lat, h.lng,
                        COUNT(DISTINCT a.id) FILTER (
                            WHERE a.source='cian_active' AND a.is_active=true
                        ) AS active_count,
                        COUNT(DISTINCT s.id) FILTER (
                            WHERE s.source IN ('cian_deactivated', 'cian_sold', 'domclick_sold', 'winners_sold')
                        ) AS sold_count
                    FROM houses h
                    LEFT JOIN active_ads a ON a.house_id = h.id
                    LEFT JOIN sold_ads s ON s.house_id = h.id
                    WHERE {where_sql}
                    GROUP BY h.id
                ),
                cells AS (
                    SELECT
                        ROUND(lat::numeric / :cell) * :cell AS cell_lat,
                        ROUND(lng::numeric / :cell) * :cell AS cell_lng,
                        lat, lng,
                        active_count, sold_count
                    FROM houses_with_ads
                )
                SELECT
                    cell_lat,
                    cell_lng,
                    AVG(lat)                         AS center_lat,
                    AVG(lng)                         AS center_lng,
                    COUNT(*)                          AS house_count,
                    COALESCE(SUM(active_count), 0)   AS total_active,
                    COALESCE(SUM(sold_count), 0)     AS total_sold
                FROM cells
                GROUP BY cell_lat, cell_lng
                ORDER BY house_count DESC
                LIMIT :limit
            """), params)).all()
        else:
            # Individual houses (street-level)
            rows = (await s.execute(text(f"""
                WITH houses_with_ads AS (
                    SELECT
                        h.id            AS house_id,
                        h.lat, h.lng,
                        h.address, h.street, h.house_num,
                        h.year_built, h.building_type, h.levels, h.series,
                        COUNT(DISTINCT a.id) FILTER (
                            WHERE a.source='cian_active' AND a.is_active=true
                        ) AS active_count,
                        COUNT(DISTINCT s.id) FILTER (
                            WHERE s.source IN ('cian_deactivated', 'cian_sold', 'domclick_sold', 'winners_sold')
                        ) AS sold_count
                    FROM houses h
                    LEFT JOIN active_ads a ON a.house_id = h.id
                    LEFT JOIN sold_ads s ON s.house_id = h.id
                    WHERE {where_sql}
                    GROUP BY h.id
                )
                SELECT * FROM houses_with_ads
                ORDER BY active_count DESC, sold_count DESC
                LIMIT :limit
            """), params)).all()

    out = []
    if cell > 0:
        for r in rows:
            out.append({
                "is_synthetic": True,
                # Cluster pin = centroid of actual houses in the cell,
                # not the geometric center. This puts the bubble on a
                # real building so it visually follows the city.
                "lat": float(r.center_lat),
                "lng": float(r.center_lng),
                "house_count": int(r.house_count),
                "active_count": int(r.total_active),
                "deactivated_count": int(r.total_sold),
                "cell_lat": float(r.cell_lat),
                "cell_lng": float(r.cell_lng),
            })
    else:
        for r in rows:
            out.append({
                "id": int(r.house_id),
                "house_id": int(r.house_id),
                "address": r.address,
                "street": r.street,
                "house_num": r.house_num,
                "lat": float(r.lat),
                "lng": float(r.lng),
                "source": "houses",
                "active_count": int(r.active_count or 0),
                "deactivated_count": int(r.sold_count or 0),
                "is_synthetic": False,
                "year": r.year_built,
                "type": r.building_type,
                "levels": r.levels,
                "series": r.series,
            })

    log.info(
        "/api/clusters bbox=(%s..%s, %s..%s) zoom=%d cell=%.4f → %d items",
        min_lat, max_lat, min_lng, max_lng, zoom, cell, len(out),
    )

    # Store in TTL cache for subsequent pan/zoom with the same bbox.
    # Pre-serialize to JSON bytes so the response is a direct send.
    payload_bytes = _json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    _clusters_cache[cache_key] = (_time.time(), payload_bytes)
    return Response(content=payload_bytes, media_type="application/json; charset=utf-8")


@app.get("/api/clusters/{cluster_id}/ads")
async def cluster_ads(cluster_id: int):
    """All ads (active + sold) for one real house.

    cluster_id must be a positive id (the `houses.id` PK). Negative
    ids are leftover from the old synthetic-cluster scheme and return
    404 — the client should clear its `?house=` param.
    """
    if cluster_id < 0:
        # Synthetic clusters are gone. If a stale URL or bookmark hits
        # this, fail loud so the client can react.
        raise HTTPException(404, "synthetic clusters are no longer supported")

    sf = get_session_factory()
    async with sf() as s:
        house = (await s.execute(text("""
            SELECT id, source, external_house_id, cian_house_id, address,
                   street, house_num, lat, lng, year_built, levels,
                   building_type, series
            FROM houses WHERE id = :id
        """), {"id": cluster_id})).first()
        if not house:
            raise HTTPException(404, "house not found")

        # Use cian_house_id (or external_house_id) to find ads — that's
        # what active_ads stores. Also try house_id for legacy rows.
        cian_id = house.cian_house_id
        ext_id = str(cian_id) if cian_id else (house.external_house_id or str(cluster_id))
        # Filter is_active=true — must match /api/clusters otherwise a house
        # with all-stale active_ads (is_active=false) would show a red
        # dot on the map but the panel would list 0 active, which is
        # confusing ("why does the red 5 have nothing inside?"). Ads
        # that have flipped to is_active=false are surfaced via the
        # deactivated section below, so nothing is lost.
        active = (await s.execute(text(f"""
            SELECT id, external_id, source, url, price, price_per_m2, area, rooms,
                   floor_current, floor_total, metro_station, metro_walk_time,
                   district, okrug, renovation, days_in_exposition, publish_date, filter_id,
                   raw_data
            FROM {OFFERS_TABLE}
            WHERE source = 'cian_active'
              AND is_active = true
              AND (cian_house_id = :cid
                   OR external_id = :ext
                   OR house_id = :hid)
            ORDER BY price NULLS LAST
        """), {"cid": cian_id or -1, "ext": ext_id, "hid": cluster_id})).all()

        deactivated = (await s.execute(text(f"""
            SELECT external_id, source, url, price, price_per_m2, area, rooms,
                   floor_current, floor_total, renovation,
                   exposition_days, publish_date, sold_date, raw_data
            FROM sold_ads
            WHERE {SOLD_SOURCE_FILTER}
              AND (cian_house_id = :cid
                   OR external_id = :ext
                   OR house_id = :hid)
            ORDER BY sold_date DESC NULLS LAST
            LIMIT 100
        """), {"cid": cian_id or -1, "ext": ext_id, "hid": cluster_id})).all()

    def raw(d):
        return d.raw_data if isinstance(d.raw_data, dict) else {}

    def deact_to_dict(d):
        """Sold ad → dict for /api/clusters/{id}/ads. Source-agnostic (v2)."""
        return _sold_ad_to_dict(d)

    def active_to_dict(a):
        rd = a.raw_data if isinstance(a.raw_data, dict) else None
        return {
            "id": a.id,
            "source": a.source,
            "external_id": a.external_id,
            "url": a.url,
            "price": a.price,
            "price_per_m2": a.price_per_m2,
            "area": a.area,
            "rooms": a.rooms,
            "floor_current": a.floor_current,
            "floor_total": a.floor_total,
            "metro_station": a.metro_station,
            "metro_walk_time": a.metro_walk_time,
            "district": a.district,
            "okrug": a.okrug,
            "renovation": a.renovation,
            "days_in_exposition": a.days_in_exposition,
            "publish_date": a.publish_date.isoformat() if a.publish_date else None,
            "filter_id": a.filter_id,
            "raw_data": rd,
        }

    return {
        "house": {
            "id": house.id,
            "house_id": house.cian_house_id,
            "source": house.source,
            "cian_house_id": house.cian_house_id,
            "address": house.address,
            "street": house.street,
            "house_num": house.house_num,
            "lat": float(house.lat) if house.lat is not None else None,
            "lng": float(house.lng) if house.lng is not None else None,
            "year": house.year_built,
            "type": house.building_type,
            "levels": house.levels,
            "series": house.series,
        },
        "active": [active_to_dict(a) for a in active],
        "deactivated": [deact_to_dict(d) for d in deactivated],
        "stats": {
            "total_active": len(active),
            "total_deactivated": len(deactivated),
        },
    }


@app.get("/api/ads/map")
async def ads_map(
    min_lat: Optional[float] = Query(None),
    max_lat: Optional[float] = Query(None),
    min_lng: Optional[float] = Query(None),
    max_lng: Optional[float] = Query(None),
    limit: int = Query(50000, ge=1, le=50000),
):
    """Return ALL active ads as map markers. Each ad carries its own
    lat/lng from the cian offer page (parsed at ingest time), so ads
    without a linked flatinfo house still appear on the map.

    Each item: {id, external_id, url, house_id, lat, lng, price, rooms, area}
    Compact form for marker rendering.
    """
    where = ["lat IS NOT NULL", "lng IS NOT NULL", "is_active = true", ACTIVE_SOURCE_FILTER]
    params: dict = {"limit": limit}
    if min_lat is not None and max_lat is not None:
        where.append("lat BETWEEN :min_lat AND :max_lat")
        params.update(min_lat=min_lat, max_lat=max_lat)
    if min_lng is not None and max_lng is not None:
        where.append("lng BETWEEN :min_lng AND :max_lng")
        params.update(min_lng=min_lng, max_lng=max_lng)
    where_sql = " AND ".join(where)

    sf = get_session_factory()
    async with sf() as s:
        rows = (await s.execute(text(f"""
            SELECT
              id, external_id, url, house_id, cian_house_id,
              lat, lng, price, price_per_m2, area, rooms,
              floor_current, floor_total
            FROM {OFFERS_TABLE}
            WHERE {where_sql}
            LIMIT :limit
        """), params)).all()
    return [
        {
            "id": r.id,
            "external_id": str(r.external_id) if r.external_id is not None else None,
            "url": r.url,
            "house_id": r.house_id,
            "lat": float(r.lat) if r.lat is not None else None,
            "lng": float(r.lng) if r.lng is not None else None,
            "price": int(r.price) if r.price is not None else None,
            "price_per_m2": int(r.price_per_m2) if r.price_per_m2 is not None else None,
            "area": float(r.area) if r.area is not None else None,
            "rooms": int(r.rooms) if r.rooms is not None else None,
            "floor_current": int(r.floor_current) if r.floor_current is not None else None,
            "floor_total": int(r.floor_total) if r.floor_total is not None else None,
        }
        for r in rows
    ]


# ---- /api/suggest — Yandex Suggest proxy with in-process TTL cache ----
# Suggest is per-keystroke from the search input, so we don't hit
# Yandex more than once per (text, bbox) within 60s.
YANDEX_API_KEY = os.environ.get(
    "YANDEX_API_KEY", "7a8defd8-9fea-4454-a450-6e9d1083ead0"
)
# Yandex free tier is 1000 req/day for suggest; the 60s cache + in-input
# debounce is plenty for a single-user map.
_SUGGEST_CACHE: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_SUGGEST_TTL = 60.0
_GEOCODE_CACHE: dict[str, tuple[float, Optional[tuple[float, float]]]] = {}
_GEOCODE_TTL = 60.0 * 60  # 1h — addresses don't move
_HOUSE_SEARCH_CACHE: dict[str, tuple[float, Optional[dict]]] = {}
_HOUSE_SEARCH_TTL = 60.0 * 30  # 30 min

# Moscow bbox: tight to the city proper, MKAD with a small margin.
# Format: min_lng, max_lat, max_lng, min_lat (Yandex suggest convention).
# User feedback: drop everything outside Moscow — Tver Oblast, Lipetsk,
# etc. shouldn't show up when searching for a Moscow address.
_MOSCOW_BBOX = "37.32,55.95,37.88,55.52"


def _parse_yandex_addr(formatted: str) -> tuple[Optional[str], Optional[str]]:
    """Best-effort parse of a Yandex 'formatted_address' like
    'Москва, Новинский бульвар, 15' into (street_full, house_num).

    Returns ('Новинский бульвар', '15') or (None, None) on parse failure.
    'Москва' prefix is skipped. Last token = house number; everything
    between = street (with type: бульвар/улица/переулок/...).
    """
    if not formatted:
        return None, None
    parts = [p.strip() for p in formatted.split(",") if p.strip()]
    # Drop leading "Россия" / "Москва" / region if present.
    while parts and parts[0].lower() in {"россия", "москва", "moscow", "russia"}:
        parts.pop(0)
    if len(parts) < 2:
        return None, None
    # Last is house number (might be "15", "15к1", "8/2С1").
    house = parts[-1]
    street = ", ".join(parts[:-1]) if len(parts) > 2 else parts[0]
    return street, house


# Words that act as street-type prefixes/suffixes and should be
# matched loosely in DB lookups.
_STREET_TYPE_TOKENS = {
    "улица", "ул", "ул.",
    "бульвар", "б-р", "бул.", "б.",
    "переулок", "пер.", "пер",
    "проезд", "пр.", "пр",
    "проспект", "просп.", "пр-кт",
    "шоссе", "ш.", "ш",
    "набережная", "наб.", "наб",
    "площадь", "пл.", "пл",
    "аллея", "ал.",
    "тупик", "туп.",
    "квартал", "кв-л",
}


def _street_loose(street: str) -> str:
    """Normalize street for ILIKE matching: drop 'ул.'/'пер.' tokens
    wherever they appear (start or end of the string).

    'Рождественская улица' -> 'рождественская'
    'Новинский бульвар'    -> 'новинский'
    'улица Покровка'       -> 'покровка'         (type at the START)
    'переулок Проточный'   -> 'проточный'        (type at the START)
    """
    if not street:
        return ""
    s = street.lower()
    s = re.sub(r"[\s\.,]+", " ", s).strip()
    # Drop type tokens from BOTH ends — DB stores "улица Покровка"
    # AND "Пятницкая улица" (and a few other variants). Strip them
    # wherever they appear so the search key is the bare street name.
    tokens = [t for t in s.split(" ") if t and t not in _STREET_TYPE_TOKENS]
    return " ".join(tokens)


def _norm_house(h: str) -> str:
    """Normalize house number for matching: 'д.14/1 с.1' == '14/1с1' == '14/1'.
    Be conservative — keep digits + slashes + latin letters, drop spaces and dots.
    """
    if not h:
        return ""
    h = h.lower()
    # Remove "д.", "к.", "с.", "стр.", "корп." prefixes
    h = re.sub(r"\b(д|к|с|стр|корп)\.\s*", "", h)
    # Keep only [a-zа-я0-9/]
    h = re.sub(r"[^a-zа-я0-9/]", "", h)
    return h


@dataclass
class _AddressKey:
    street_loose: str  # lowercased street without type
    house_loose: str   # lowercased house without prefix


def _extract_house_components(street: str, house: str) -> _AddressKey:
    return _AddressKey(_street_loose(street), _norm_house(house))


async def _search_house_in_db(
    street: Optional[str], house: Optional[str]
) -> Optional[dict]:
    """Look up a house by approximate street + house number.

    Returns {'id', 'address', 'lat', 'lng', 'source'} or None.
    Match is done in two passes:
      1) exact LOWER(street) + LOWER(house_num) (most common case)
      2) loose ILIKE on street name without type token, house base part
    """
    if not street or not house:
        return None
    sk = _extract_house_components(street, house)
    if not sk.street_loose or not sk.house_loose:
        return None

    cache_key = f"{sk.street_loose}|{sk.house_loose}"
    now = time.time()
    cached = _HOUSE_SEARCH_CACHE.get(cache_key)
    if cached and now - cached[0] < _HOUSE_SEARCH_TTL:
        return cached[1]

    sf = get_session_factory()
    async with sf() as s:
        # Pass 1: exact match on normalized street + house base part.
        # We compare LOWER(street) LIKE '...%' because flatinfo stores
        # street as e.g. 'Рождественская' (no 'ул.') but cian/yandex
        # gives us 'Рождественская улица' → both normalize to
        # 'рождественская' so LIKE works.
        # house_num in DB usually has 'д.' prefix (flatinfo) or
        # 'к.1с2' suffixes; we strip those in SQL so the same value
        # like '15' can match both 'д.15' and '15'.
        street_pat = f"{sk.street_loose}%"
        house_pat = f"{sk.house_loose}%"
        # Strip "д."/"к."/"с."/"стр." prefixes and any spaces from
        # house_num so prefix-LIKE works on the numeric part. ASCII-only
        # regex with 'g' flag to strip all prefixes.
        house_sql = (
            "LOWER(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE("
            "COALESCE(house_num,''),"
            "'^\\s*(д|к|с|стр|корп)\\.?\\s*','','i'),"
            "'\\s+','','g'),"
            "'\\.+','','g'))"
        )
        # Strip street type tokens from the DB side too — the type can
        # be either at the start ("улица Покровка", "переулок Проточный")
        # or at the end ("Пятницкая улица", "Новинский бульвар"). The
        # search key from Yandex has already been normalized by
        # `_street_loose` so we apply the same on DB side.
        # Order tokens longest-first so that "переулок" matches before
        # "пер" and "бульвар" before "б-р"/"бул." — otherwise the
        # short alias would eat a prefix of the longer one.
        # IMPORTANT: strip type tokens BEFORE removing spaces — word
        # boundaries (`\m...\M`) need a real separator (space) between
        # the type token and the street name; once we strip spaces
        # everything becomes one word and the boundaries vanish.
        sorted_tokens = sorted(_STREET_TYPE_TOKENS, key=len, reverse=True)
        # Tokens are escaped; word boundaries (\m/\M) prevent 2-3 char
        # aliases like "пер"/"пр"/"ул" from eating prefixes of street
        # names like "проточный".
        type_token_alt = "|".join(f"\\m{re.escape(t)}\\M" for t in sorted_tokens)
        street_sql = (
            "LOWER(REGEXP_REPLACE("
            "REGEXP_REPLACE(REGEXP_REPLACE(COALESCE(street,''),"
            f"'({type_token_alt})\\.?', '', 'gi'),"
            "'\\.', '', 'g'),"
            "'\\s+', '', 'g'))"
        )
        # Prefix of normalized street — used for fuzzy LIKE in pass 2.
        # We strip spaces and trailing type tokens (бульвар, улица, ...)
        # from the search key, then LIKE-prefix match against the
        # space-stripped DB value.
        sk_street_norm = sk.street_loose.replace(" ", "")
        row = (await s.execute(
            text(f"""
                SELECT id, source, address, lat, lng, street, house_num
                FROM houses
                WHERE {street_sql} LIKE :street_pat
                  AND {house_sql} LIKE :house_pat
                  AND lat IS NOT NULL
                ORDER BY
                  CASE WHEN {street_sql} = :street_exact
                            AND {house_sql} = :house_exact
                       THEN 0 ELSE 1 END,
                  -- Prefer flatinfo (most accurate metadata) over cian_ad
                  CASE source WHEN 'flatinfo' THEN 0 ELSE 1 END,
                  id
                LIMIT 1
            """),
            {
                "street_pat": f"{sk_street_norm}%",
                "house_pat": house_pat,
                "street_exact": sk_street_norm,
                "house_exact": sk.house_loose,
            },
        )).mappings().first()

        if not row:
            # Pass 2: looser — match just the leading word(s) of street.
            # Useful when street name is multi-word (e.g. 'Академика
            # Сахарова') and cian gives us 'Академика Сахарова' but
            # flatinfo has just 'Сахарова' (or vice versa).
            first_token = sk_street_norm[: max(4, len(sk_street_norm) // 2)]
            if first_token and first_token != sk_street_norm:
                row = (await s.execute(
                    text(f"""
                        SELECT id, source, address, lat, lng, street, house_num
                        FROM houses
                        WHERE {street_sql} LIKE :street_pat
                          AND {house_sql} LIKE :house_pat
                          AND lat IS NOT NULL
                        ORDER BY
                          CASE WHEN {street_sql} = :street_exact
                                    AND {house_sql} = :house_exact
                               THEN 0 ELSE 1 END,
                          CASE source WHEN 'flatinfo' THEN 0 ELSE 1 END,
                          id
                        LIMIT 1
                    """),
                    {
                        "street_pat": f"{first_token}%",
                        "house_pat": house_pat,
                        "street_exact": sk_street_norm,
                        "house_exact": sk.house_loose,
                    },
                )).mappings().first()

    if not row:
        _HOUSE_SEARCH_CACHE[cache_key] = (now, None)
        return None

    out = {
        "id": int(row["id"]),
        "source": row["source"],
        "address": row["address"],
        "lat": float(row["lat"]) if row["lat"] is not None else None,
        "lng": float(row["lng"]) if row["lng"] is not None else None,
    }
    _HOUSE_SEARCH_CACHE[cache_key] = (now, out)
    return out


@app.get("/api/suggest")
async def suggest(
    text: str = Query(..., min_length=1, max_length=200, description="Search query"),
    bbox: Optional[str] = Query(
        None, description="Optional bbox as 'min_lng,max_lat,max_lng,min_lat'"
    ),
    limit: int = Query(8, ge=1, le=20),
):
    """Proxy to Yandex Maps Suggest API. Returns a slim list of
    {title, subtitle, formatted_address, distance_m, lat, lng, house?}.

    Each entry also includes 'house' (DB match) when we could match the
    suggested address to a house row — null otherwise.

    Cached in-process for 60s per (text, bbox). Yandex returns 10
    results by default; we cap at 8 to keep the dropdown tight.
    """
    text = text.strip()
    if not text:
        return []
    bbox = bbox or _MOSCOW_BBOX
    cache_key = (text, bbox)
    now = time.time()
    cached = _SUGGEST_CACHE.get(cache_key)
    if cached and now - cached[0] < _SUGGEST_TTL:
        return cached[1]

    params = {
        "apikey": YANDEX_API_KEY,
        "text": text,
        "lang": "ru_RU",
        "results": str(limit),
        "types": "geo",
        "print_address": "1",
        "bbox": bbox,
        # strict_bounds=1 — drop everything outside the Moscow bbox.
        # The default (0) lets Yandex return any global match — Тверь,
        # Калуга, etc. — which clutters the dropdown and makes the
        # user think the search is broken.
        "strict_bounds": "1",
    }
    url = "https://suggest-maps.yandex.ru/v1/suggest?" + urllib.parse.urlencode(params)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, headers={
                "Accept": "application/json",
                "User-Agent": "Flipper/1.0",
            })
            if r.status_code != 200:
                log.warning("Yandex suggest HTTP %s for %r: %s", r.status_code, text, r.text[:200])
                return []
            data = r.json()
    except Exception as e:
        log.warning("Yandex suggest error for %r: %s", text, e)
        return []

    results = data.get("results", [])
    out: list[dict] = []
    for item in results:
        title = (item.get("title") or {}).get("text") or ""
        subtitle = (item.get("subtitle") or {}).get("text") or ""
        formatted = (
            (item.get("address") or {}).get("formatted_address")
            or f"{title}, {subtitle}".strip(", ")
        )
        # Only Moscow (and very close — bbox should already filter, but
        # the search box can match Торопец etc. if user types 'Новинский').
        # We accept anything in the bbox; just expose distance for UX.
        dist = (item.get("distance") or {}).get("value")
        tags = item.get("tags") or []
        # We don't have lat/lng from suggest directly — geocode is needed.
        # But we can match the formatted_address to a house in DB without
        # making a second API call.
        street, house_num = _parse_yandex_addr(formatted)
        house_match = None
        if street and house_num and any(t in tags for t in ("house", "entrance")):
            house_match = await _search_house_in_db(street, house_num)
        out.append({
            "title": title,
            "subtitle": subtitle,
            "formatted_address": formatted,
            "distance_m": dist,
            "tags": tags,
            "street": street,
            "house_num": house_num,
            "house": house_match,
        })

    _SUGGEST_CACHE[cache_key] = (now, out)
    return out


@app.get("/api/geocode")
async def geocode(
    text: str = Query(..., min_length=1, max_length=300, description="Address to geocode"),
):
    """Resolve an address to (lat, lng) and find a matching house in DB.

    Strategy:
      1) Look up in DB by parsed street+house (no Yandex call needed if hit)
      2) If no DB hit, call Yandex Geocoder for the address and return
         raw coords so the user can still drop a pin.
    """
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    # Step 1: DB match (cheap, accurate, gives us full house metadata)
    street, house_num = _parse_yandex_addr(text)
    db_hit = None
    if street and house_num:
        db_hit = await _search_house_in_db(street, house_num)

    if db_hit and db_hit.get("lat") is not None:
        return {
            "source": "db",
            "lat": db_hit["lat"],
            "lng": db_hit["lng"],
            "house": db_hit,
        }

    # Step 2: Yandex Geocoder
    cache_key = text.lower()
    now = time.time()
    cached = _GEOCODE_CACHE.get(cache_key)
    if cached and now - cached[0] < _GEOCODE_TTL:
        if cached[1] is None:
            return {"source": "yandex", "lat": None, "lng": None, "house": None}
        return {
            "source": "yandex",
            "lat": cached[1][0],
            "lng": cached[1][1],
            "house": None,
        }

    params = {
        "apikey": YANDEX_API_KEY,
        "geocode": text,
        "format": "json",
        "results": "1",
        "lang": "ru_RU",
        # Restrict to Moscow bbox (same as suggest). `rspn=1` makes
        # the geocoder strictly honour the bbox — without it, Yandex
        # returns the globally best match even if it's outside.
        "bbox": _MOSCOW_BBOX,
        "rspn": "1",
    }
    url = "https://geocode-maps.yandex.ru/v1/?" + urllib.parse.urlencode(params)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, headers={
                "Accept": "application/json",
                "User-Agent": "Flipper/1.0",
            })
            if r.status_code != 200:
                # 403/401 = key has no access to Geocoder. Don't surface
                # as 502 — UI expects a 200 with null lat/lng so it can
                # fall back to "no house in DB" message cleanly. Cache
                # the miss so we don't keep hammering Yandex.
                log.warning("Yandex geocode HTTP %s for %r: %s", r.status_code, text, r.text[:200])
                _GEOCODE_CACHE[cache_key] = (now, None)
                return {"source": "yandex", "lat": None, "lng": None, "house": None, "yandex_error": r.status_code}
            data = r.json()
    except Exception as e:
        log.warning("Yandex geocode error for %r: %s", text, e)
        _GEOCODE_CACHE[cache_key] = (now, None)
        return {"source": "yandex", "lat": None, "lng": None, "house": None, "yandex_error": str(e)[:80]}

    members = ((data.get("response") or {}).get("GeoObjectCollection") or {}).get(
        "featureMember"
    ) or []
    if not members:
        _GEOCODE_CACHE[cache_key] = (now, None)
        return {"source": "yandex", "lat": None, "lng": None, "house": None}

    pos = (members[0].get("GeoObject") or {}).get("Point") or {}
    pos_str = pos.get("pos", "")  # "lng lat"
    try:
        lng_s, lat_s = pos_str.split()
        lat, lng = float(lat_s), float(lng_s)
    except (ValueError, AttributeError):
        _GEOCODE_CACHE[cache_key] = (now, None)
        return {"source": "yandex", "lat": None, "lng": None, "house": None}

    _GEOCODE_CACHE[cache_key] = (now, (lat, lng))
    return {
        "source": "yandex",
        "lat": lat,
        "lng": lng,
        "house": None,
    }


def main():
    import uvicorn
    uvicorn.run("web.server:app", host="127.0.0.1", port=8000, reload=False, log_level="info")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Admin Panel v1 — generic table endpoints (Phase 4+)
# Server-side pagination, sort, search, filters. Returns `{rows, total, stats}`.
# ---------------------------------------------------------------------------

_TABLE_CONFIGS = {
    "active": {
        "table": "active_ads",
        "source_filter": "source='cian_active'",
        "select": "id, source, external_id, url, price, price_per_m2, area, rooms, "
                  "floor_current, floor_total, district, okrug, metro_station, metro_walk_time, "
                  "renovation, days_in_exposition, "
                  "CASE WHEN rooms IS NULL OR rooms = 0 "
                  "  THEN 'Студия ' || COALESCE(area::text, '') || ' м²' "
                  "  ELSE rooms::text || '-к квартира ' || COALESCE(area::text, '') || ' м²' "
                  "END AS title, "
                  "publish_date, filter_id, house_id",
        "search_cols": ["external_id", "district", "okrug", "metro_station", "raw_data"],
        # Editable columns: admin can correct CIAN auto-fill or reassign.
        # `is_active` is the only "going-forward" toggle per dev policy.
        "editable": {
            "filter_id": int,
            "renovation": str,
            "district": str,
            "okrug": str,
            "metro_station": str,
            "metro_walk_time": int,
        },
    },
    "sold": {
        "table": "sold_ads",
        "source_filter": "source='cian_active'",
        "select": "id, source, external_id, url, price, price_per_m2, area, rooms, "
                  "sold_date, exposition_days AS days_in_exposition, "
                  "CASE WHEN rooms IS NULL OR rooms = 0 "
                  "  THEN 'Студия ' || COALESCE(area::text, '') || ' м²' "
                  "  ELSE rooms::text || '-к квартира ' || COALESCE(area::text, '') || ' м²' "
                  "END AS title, "
                  "house_id",
        "search_cols": ["external_id", "raw_data"],
        "editable": {
            "renovation": str,
        },
    },
    "hidden": {
        "table": "sold_ads",
        "source_filter": "source='cian_deactivated'",
        "select": "id, source, external_id, url, price, price_per_m2, area, rooms, "
                  "sold_date, exposition_days AS days_in_exposition, "
                  "CASE WHEN rooms IS NULL OR rooms = 0 "
                  "  THEN 'Студия ' || COALESCE(area::text, '') || ' м²' "
                  "  ELSE rooms::text || '-к квартира ' || COALESCE(area::text, '') || ' м²' "
                  "END AS title, "
                  "house_id",
        "search_cols": ["external_id", "raw_data"],
        "editable": {
            "renovation": str,
        },
    },
    "houses": {
        "table": "houses",
        "source_filter": None,  # all sources
        "select": "id, source, address, street, house_num, "
                  "year_built AS year, building_type AS type, levels, "
                  "series, lat, lng, "
                  "(SELECT COUNT(*) FROM active_ads WHERE house_id = houses.id) AS active_count, "
                  "(SELECT COUNT(*) FROM sold_ads WHERE house_id = houses.id) AS deactivated_count",
        "search_cols": ["address", "street", "house_num", "series", "external_house_id"],
        "stats_cols": (),  # houses have no price/area
        "editable": {
            "address": str,
            "street": str,
            "house_num": str,
            "year_built": int,
            "levels": int,
            "building_type": str,
            "series": str,
            "ceiling_height": float,
        },
    },
}


def _parse_int(v, default=None, lo=None, hi=None):
    if v is None or v == "":
        return default
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    if lo is not None and n < lo:
        n = lo
    if hi is not None and n > hi:
        n = hi
    return n


def _table_query(name: str):
    """Return SELECT clause + source WHERE for a given table name."""
    cfg = _TABLE_CONFIGS.get(name)
    if not cfg:
        return None
    return cfg


async def _fetch_table_rows(name: str, params: dict) -> dict:
    """Generic paginated table fetch with sort + search + filters.

    Returns: {rows: [...], total: int, page, page_size, stats: {...}}
    """
    cfg = _table_query(name)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Unknown table '{name}'")

    page = _parse_int(params.get("page"), default=1, lo=1, hi=100_000)
    page_size = _parse_int(params.get("page_size"), default=50, lo=1, hi=500)
    sort = (params.get("sort") or "").strip() or None
    order = (params.get("order") or "asc").lower()
    if order not in ("asc", "desc"):
        order = "asc"
    q = (params.get("q") or "").strip()

    # Whitelist sort columns to prevent SQL injection.
    SORT_WHITELIST = {
        "active": {"id", "price", "price_per_m2", "area", "rooms", "days_in_exposition", "publish_date"},
        "sold":   {"id", "price", "price_per_m2", "area", "rooms", "sold_date", "days_in_exposition"},
        "hidden": {"id", "price", "area", "rooms", "sold_date"},
        "houses": {"id", "year", "levels", "active_count", "deactivated_count"},
    }
    if sort and sort not in SORT_WHITELIST.get(name, set()):
        sort = None

    where_clauses = []
    # SA 2.0 async + asyncpg requires named-param placeholders (:name) with a
    # dict. The legacy "$1, $2, ..." style with a positional list was
    # mis-parsed as executemany rows, so we switched to explicit names.
    where_params: dict = {}
    _n = [0]  # counter for generating unique param names

    def _p():
        _n[0] += 1
        return f"p{_n[0]}"

    if cfg["source_filter"]:
        where_clauses.append(cfg["source_filter"])

    # Numeric range filters (per-table)
    range_filters = {
        "active": [
            ("price_min", "price_max", "price"),
            ("area_min", "area_max", "area"),
            ("days_min", "days_max", "days_in_exposition"),
        ],
        "sold": [
            ("price_min", "price_max", "price"),
            ("area_min", "area_max", "area"),
            ("days_min", "days_max", "days_in_exposition"),
        ],
        "hidden": [
            ("price_min", "price_max", "price"),
            ("area_min", "area_max", "area"),
        ],
        "houses": [
            ("year_min", "year_max", "year"),
        ],
    }
    for mn, mx, col in range_filters.get(name, []):
        v = _parse_int(params.get(mn))
        if v is not None:
            pk = _p()
            where_clauses.append(f"{col} >= :{pk}")
            where_params[pk] = v
        v = _parse_int(params.get(mx))
        if v is not None:
            pk = _p()
            where_clauses.append(f"{col} <= :{pk}")
            where_params[pk] = v

    # rooms multi-select (CSV)
    if name in ("active", "sold", "hidden"):
        rooms = (params.get("rooms") or "").strip()
        if rooms:
            try:
                rlist = [int(r) for r in rooms.split(",") if r]
                if rlist:
                    pk = _p()
                    # Note the space before `::` — the `::` cast operator would
                    # otherwise swallow our `:p1` named placeholder.
                    where_clauses.append(f"rooms = ANY(:{pk} ::int[])")
                    where_params[pk] = rlist
            except ValueError:
                pass

    # source multi-select (CSV)
    if name in ("active", "sold", "hidden", "houses"):
        sources = (params.get("source") or "").strip()
        if sources:
            slist = [s.strip() for s in sources.split(",") if s.strip()]
            if slist:
                pk = _p()
                where_clauses.append(f"source = ANY(:{pk} ::text[])")
                where_params[pk] = slist

    # Full-text search (case-insensitive contains) — search across configured cols.
    # We use ILIKE on a single concatenated text. Cheap at 5k rows; for 200k
    # we'd switch to a tsvector index, but Flipper's data is too small to matter.
    if q:
        qcol_parts = []
        for c in cfg["search_cols"]:
            # json columns need an explicit ::text cast (raw_data is json)
            qcol_parts.append(f"COALESCE({c}::text, '')")
        concat = " || ' ' || ".join(qcol_parts)
        pk = _p()
        where_clauses.append(f"({concat}) ILIKE :{pk}")
        where_params[pk] = f"%{q}%"

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    sort_sql = f" ORDER BY {sort} {order.upper()}, id {order.upper()}" if sort else " ORDER BY id DESC"

    offset = (page - 1) * page_size
    limit_sql = f" LIMIT {page_size} OFFSET {offset}"

    from sqlalchemy import text as _text

    engine = get_engine()
    async with engine.begin() as conn:
        total = await conn.scalar(
            _text(f"SELECT COUNT(*) FROM {cfg['table']}{where_sql}"),
            where_params,
        )

        sel_sql = f"SELECT {cfg['select']} FROM {cfg['table']}{where_sql}{sort_sql}{limit_sql}"
        result = await conn.execute(_text(sel_sql), where_params)
        cols = list(result.keys())
        rows = [dict(zip(cols, r)) for r in result.fetchall()]

        # Simple stats (count + median-ish). Houses have no price/area,
        # so we look up the stats columns per-config.
        stats_cols = cfg.get("stats_cols", ("price", "area"))
        stats_select = ", ".join(
            [f"COUNT(*) AS n"]
            + [f"COALESCE(AVG({c}), 0) AS avg_{c}" for c in stats_cols]
        )
        stats_sql = f"SELECT {stats_select} FROM {cfg['table']}{where_sql}"
        stats_row = await conn.execute(_text(stats_sql), where_params)
        s = stats_row.fetchone()
        # s[0] = count, s[1..] = avg_<col>; may be missing if stats_cols is empty
        avg_price = float(s[1]) if s and len(s) > 1 and s[1] is not None else 0
        avg_area = float(s[2]) if s and len(s) > 2 and s[2] is not None else 0
        stats = {
            "count": total or 0,
            "avg_price": avg_price,
            "avg_area": avg_area,
        }

    # Serialize datetimes/dates to ISO strings
    for row in rows:
        for k, v in list(row.items()):
            if hasattr(v, "isoformat"):
                row[k] = v.isoformat()

    return {
        "rows": rows,
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
        "stats": stats,
    }


@app.get("/api/tables/active")
async def table_active(request: Request):
    return await _fetch_table_rows("active", dict(request.query_params))


@app.get("/api/tables/sold")
async def table_sold(request: Request):
    return await _fetch_table_rows("sold", dict(request.query_params))


@app.get("/api/tables/hidden")
async def table_hidden(request: Request):
    return await _fetch_table_rows("hidden", dict(request.query_params))


@app.get("/api/tables/houses")
async def table_houses(request: Request):
    return await _fetch_table_rows("houses", dict(request.query_params))


@app.get("/api/tables/{name}/export")
async def table_export(name: str, request: Request):
    """Stream CSV of the current filter set (no pagination — admin-only)."""
    from fastapi.responses import StreamingResponse
    import csv, io

    cfg = _table_query(name)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Unknown table '{name}'")

    # Reuse _fetch_table_rows but with huge page_size.
    params = dict(request.query_params)
    params["page_size"] = "100000"
    params["page"] = "1"
    data = await _fetch_table_rows(name, params)
    rows = data["rows"]
    if not rows:
        return StreamingResponse(
            iter([b"no rows\n"]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
        )

    def gen():
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        yield buf.getvalue()
        buf.seek(0); buf.truncate()
        for r in rows:
            w.writerow({k: ("" if v is None else v) for k, v in r.items()})
            yield buf.getvalue()
            buf.seek(0); buf.truncate()

    return StreamingResponse(
        gen(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
    )


# ---- Row editing (Google-Sheets-style cells) -------------------------------
#
# The DataTable is editable inline: click a cell, type, blur to save. We
# whitelist per-table columns to avoid SQL injection and to keep the contract
# obvious.  Only columns explicitly listed in cfg["editable"] are accepted;
# anything else returns 400.
#
# We use asyncpg directly here (not SA Core) because the SA 2.0 async session
# has a known issue with the dict → named-param binding for UPDATE statements
# when the driver is asyncpg, so for one-off writes we go through conn.execute
# of a parameterised text() statement and the same dict-bind pattern that
# already works for SELECT above.


@app.patch("/api/tables/{name}/rows/{row_id}")
async def table_row_patch(name: str, row_id: int, request: Request):
    """Update a single row. Body: {column: value, ...}.

    Returns: {ok: True, row: <full row after update>} on success.
    """
    cfg = _table_query(name)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Unknown table '{name}'")
    editable = cfg.get("editable") or {}
    if not editable:
        raise HTTPException(
            status_code=400, detail=f"Table '{name}' has no editable columns"
        )

    body = await request.json()
    if not isinstance(body, dict) or not body:
        raise HTTPException(status_code=400, detail="Body must be a non-empty object")

    # Reject unknown columns. Use explicit message so the UI can surface it.
    bad = [k for k in body.keys() if k not in editable]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"Column(s) not editable: {', '.join(sorted(bad))}",
        )

    # Coerce and validate each value against its declared Python type.
    coerced: dict = {}
    for col, raw in body.items():
        cast = editable[col]
        if raw is None:
            coerced[col] = None
            continue
        if cast is int:
            try:
                v = int(raw)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400, detail=f"{col}: expected int, got {raw!r}"
                )
            coerced[col] = v
        elif cast is float:
            try:
                coerced[col] = float(raw)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400, detail=f"{col}: expected number, got {raw!r}"
                )
        elif cast is str:
            coerced[col] = "" if raw is None else str(raw)
        elif cast is bool:
            coerced[col] = bool(raw)
        else:
            coerced[col] = raw

    from sqlalchemy import text as _text

    # Build the SET clause with :p1, :p2, ... placeholders, mirroring the
    # _fetch_table_rows pattern (and the SA 2.0 / asyncpg gotcha).
    set_parts = []
    set_params: dict = {}
    where_params: dict = {}
    _n = [0]

    def _p():
        _n[0] += 1
        return f"p{_n[0]}"

    for col, val in coerced.items():
        pk = _p()
        set_parts.append(f"{col} = :{pk}")
        set_params[pk] = val

    pk_where = _p()
    where_params[pk_where] = row_id

    set_sql = ", ".join(set_parts)
    # Compose WHERE in the right order: id first, then optional source scope,
    # then RETURNING. RETURNING must come last — appending anything after it
    # makes Postgres parse it as part of the projection list (it tried to
    # evaluate `id AND source = $3` and threw "AND must be boolean").
    extra_where = ""
    # Source-scope the UPDATE so users can't accidentally edit a row from a
    # different source than the table tab is showing. The `source` filter is
    # optional for houses (all sources).
    if cfg.get("source_filter"):
        # cfg["source_filter"] is always a `column = 'literal'` form in this
        # codebase. Extract the column name and the literal so we can rebind.
        column, literal = [s.strip() for s in cfg["source_filter"].split("=", 1)]
        literal_value = literal.strip("'")
        scope_pk = _p()
        extra_where = f" AND {column} = :{scope_pk}"
        where_params[scope_pk] = literal_value

    update_sql = (
        f"UPDATE {cfg['table']} SET {set_sql} "
        f"WHERE id = :{pk_where}{extra_where} "
        f"RETURNING id"
    )

    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(_text(update_sql), {**set_params, **where_params})
        ret = result.fetchone()
        if not ret:
            raise HTTPException(
                status_code=404, detail=f"Row {row_id} not found in '{name}'"
            )

        # Re-fetch the row in the same shape as _fetch_table_rows so the
        # frontend can drop the new row straight into the table state.
        sel_sql = f"SELECT {cfg['select']} FROM {cfg['table']} WHERE id = :pk"
        row_result = await conn.execute(_text(sel_sql), {"pk": row_id})
        cols = list(row_result.keys())
        row_dict = dict(zip(cols, row_result.fetchone()))
        for k, v in list(row_dict.items()):
            if hasattr(v, "isoformat"):
                row_dict[k] = v.isoformat()

    return {"ok": True, "row": row_dict}


# ---- Dashboard widgets ------------------------------------------------------

@app.get("/api/dashboard/kpi")
async def dashboard_kpi():
    """Headline KPIs for the dashboard."""
    from sqlalchemy import text as _text
    engine = get_engine()
    async with engine.begin() as conn:
        active = await conn.scalar(
            _text("SELECT COUNT(*) FROM active_ads WHERE source='cian_active'")
        )
        houses = await conn.scalar(_text("SELECT COUNT(*) FROM houses"))
        with_coords = await conn.scalar(
            _text("SELECT COUNT(*) FROM houses WHERE lat IS NOT NULL")
        )
        deactivated = await conn.scalar(
            _text(
                "SELECT COUNT(*) FROM sold_ads WHERE "
                "source IN ('cian_deactivated', 'cian_sold', 'domclick_sold', 'winners_sold')"
            )
        )
        with_ads = await conn.scalar(
            _text(
                "SELECT COUNT(*) FROM houses WHERE EXISTS ("
                "  SELECT 1 FROM active_ads a WHERE a.house_id = houses.id"
                ")"
            )
        )
    return {
        "active_total": int(active or 0),
        "houses": int(houses or 0),
        "houses_with_coords": int(with_coords or 0),
        "deactivated_total": int(deactivated or 0),
        "houses_with_ads": int(with_ads or 0),
    }


@app.get("/api/dashboard/hot-houses")
async def dashboard_hot_houses():
    """Top 10 houses by active_ad count."""
    from sqlalchemy import text as _text
    engine = get_engine()
    async with engine.begin() as conn:
        rows = await conn.execute(
            _text(
                """
                SELECT h.id, h.address, COUNT(a.id) AS n
                FROM houses h
                JOIN active_ads a ON a.house_id = h.id
                WHERE h.lat IS NOT NULL
                GROUP BY h.id, h.address
                ORDER BY n DESC, h.id ASC
                LIMIT 10
                """
            )
        )
    return [
        {"id": r[0], "address": r[1], "count": int(r[2])}
        for r in rows.fetchall()
    ]


# ---- Pipeline status -------------------------------------------------------

@app.get("/api/pipeline/status")
async def pipeline_status():
    """Per-parser status (read from /api/pipeline/last-run if available, else static)."""
    from sqlalchemy import text as _text
    engine = get_engine()
    PARSERS = ["cian_active", "cian_sold", "domclick_sold", "winners_sold", "flatinfo_houses"]
    out = []
    async with engine.begin() as conn:
        for p in PARSERS:
            try:
                row = await conn.execute(
                    _text(
                        "SELECT MAX(last_run_at), MAX(ok) FROM parser_runs WHERE parser_name = :n"
                    ),
                    {"n": p},
                )
                last = row.fetchone()
                out.append({
                    "name": p,
                    "last_run_at": last[0].isoformat() if last and last[0] else None,
                    "status": "ok" if last and last[1] else ("never" if not last or not last[0] else "fail"),
                })
            except Exception:
                out.append({"name": p, "last_run_at": None, "status": "unknown"})
    return out


# ---- Saved filters (Phase 7, simple in-memory) ---------------------------

_SAVED_FILTERS: list[dict] = [
    {
        "id": 1,
        "name": "1к до 12М в ЦАО",
        "table": "active",
        "filters": {"rooms": "1", "price_max": "12000000"},
        "created_at": "2026-08-08T12:00:00",
    },
    {
        "id": 2,
        "name": "С ремонтом, с фото",
        "table": "active",
        "filters": {"has_renovation": "true", "has_photos": "true"},
        "created_at": "2026-08-08T12:30:00",
    },
]


@app.get("/api/saved-filters")
async def saved_filters_list():
    return _SAVED_FILTERS


@app.post("/api/saved-filters")
async def saved_filters_create(payload: dict):
    import time
    new_id = max([f["id"] for f in _SAVED_FILTERS], default=0) + 1
    item = {
        "id": new_id,
        "name": payload.get("name") or f"Filter #{new_id}",
        "table": payload.get("table") or "active",
        "filters": payload.get("filters") or {},
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _SAVED_FILTERS.append(item)
    return item


@app.delete("/api/saved-filters/{fid}")
async def saved_filters_delete(fid: int):
    global _SAVED_FILTERS
    _SAVED_FILTERS = [f for f in _SAVED_FILTERS if f["id"] != fid]
    return {"ok": True, "remaining": len(_SAVED_FILTERS)}



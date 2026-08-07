"""Fast parallel domclick_sold backfill.

Bypasses BFF list API (needs extra auth) — reads IDs from existing
domclick_links.json (May 3 snapshot, 2000 items) and processes them in
parallel using DomclickSource.

Per ad:
  1. fetch_ad_page (HTTP) — parallel, 16 concurrent
  2. parse_ad (CPU) — pure
  3. match_or_create_house (DB) — sequential
  4. _upsert_sold_ad (DB) — sequential

DB writes are serial to keep asyncpg simple and avoid link races.

Run from inside the domclick_sold container:
  docker compose run --rm domclick_sold python -m services.parsers.domclick_sold.fast_backfill
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent.parent.parent
LINKS_JSON = THIS_DIR / "domclick_links.json"

for p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "services")):
    if p not in sys.path:
        sys.path.insert(0, p)

import asyncpg  # noqa: E402

from packages.flipper_db import linker  # noqa: E402
from packages.flipper_db.base import DEFAULT_DATABASE_URL  # noqa: E402
from packages.flipper_db.pipeline import (  # noqa: E402
    _resolve_ad_geo,
    _upsert_sold_ad,
    _CreateStats,
    PipelineResult,
)
from packages.flipper_db.sources.domclick import DomclickSource  # noqa: E402
from services.parsers.domclick_sold.acquirer import (  # noqa: E402
    retry_get as acq_retry_get,
    PAGE_HEADERS as ACQ_PAGE_HEADERS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("domclick_fast")


async def main() -> int:
    # DB url
    db_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    # Load IDs
    if not LINKS_JSON.is_file():
        log.error(f"{LINKS_JSON} not found")
        return 1
    doc = json.loads(LINKS_JSON.read_text(encoding="utf-8"))
    items = list(doc.get("items") or [])
    log.info(f"Loaded {len(items)} items from {LINKS_JSON.name}")

    # Optional limit/offset via env (for chunked runs)
    offset = int(os.getenv("OFFSET", "0"))
    limit = int(os.getenv("LIMIT", "0"))  # 0 = no limit
    if offset:
        items = items[offset:]
        log.info(f"OFFSET applied: skipped first {offset}")
    if limit:
        items = items[:limit]
        log.info(f"LIMIT applied: now {len(items)} items")

    # Build source — use acquirer's urllib-based fetcher instead of httpx
    # (httpx gets Qrator-blocked; urllib with proper headers works fine).
    source = DomclickSource(max_concurrent=16, timeout=30.0)
    cookie = (
        os.environ.get("DOMCLICK_PAGE_COOKIE")
        or os.environ.get("DOMCLICK_API_COOKIE")
        or ""
    ).strip()
    if not cookie:
        # Fallback: read from secrets/domclick_cookie.txt next to LINKS_JSON
        for cand in (
            LINKS_JSON.parent / "domclick_cookie.txt",
            Path("secrets/domclick_cookie.txt"),
            Path("secrets/domclick_cookies.json"),
        ):
            if cand.is_file():
                cookie = cand.read_text(encoding="utf-8").strip()
                if cookie.startswith("["):
                    # JSON array — parse and join
                    import json as _json
                    arr = _json.loads(cookie)
                    cookie = "; ".join(
                        f"{c['name']}={c['value']}" for c in arr if c.get("domain", "").endswith("domclick.ru")
                    )
                log.info(f"Loaded cookie from {cand} ({len(cookie)} bytes)")
                break
    if not cookie:
        log.error("Need DOMCLICK_PAGE_COOKIE or DOMCLICK_API_COOKIE env, or secrets/domclick_cookie.txt")
        return 1
    # Override source's fetcher to use acquirer's urllib
    async def _acq_fetch(external_id: str) -> Optional[str]:
        url = source.ad_url(external_id)
        code, body = await asyncio.to_thread(acq_retry_get, url, ACQ_PAGE_HEADERS, cookie=cookie, timeout=30.0, retries=3)
        if code != 200:
            return None
        return body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    source.fetch_ad_page = _acq_fetch  # type: ignore[assignment]

    # DB
    log.info("connecting to DB...")
    conn = await asyncpg.connect(db_url)
    try:
        log.info("building flatinfo index...")
        index = await linker.build_flatinfo_index(conn)
        log.info(f"flatinfo index built: {index.n_houses} houses")

        res = PipelineResult()
        create_stats = _CreateStats()
        t0 = time.monotonic()

        # Fetch in big batches via asyncio.gather; the source's semaphore
        # caps actual concurrency to max_concurrent=16.
        BATCH = 64
        n = len(items)
        for batch_start in range(0, n, BATCH):
            batch = items[batch_start:batch_start + BATCH]

            # Phase 1: parallel fetch
            async def fetch_one(ext_id: str) -> tuple[str, str | None]:
                html = await source.fetch_ad_page(ext_id)
                return ext_id, html

            fetched = await asyncio.gather(
                *(fetch_one(str(it["id"])) for it in batch if it.get("id"))
            )

            # Phase 2: parse + DB write (sequential per ad to keep things sane)
            for ext_id, html in fetched:
                if html is None:
                    res.fetch_failures += 1
                    continue
                ad = source.parse_ad(html)
                if ad is None:
                    res.parse_failures += 1
                    continue
                try:
                    # Match house
                    house_id = await linker.match_or_create_house(
                        conn, ad,
                        auto_create=True,
                        create_stats=create_stats,
                        index=index,
                        source=source,
                    )
                    if house_id is not None:
                        res.houses_matched_geo += 1
                    ad_lat, ad_lng = await _resolve_ad_geo(conn, ad, house_id)
                    # Sold-source: write directly to sold_ads
                    inserted = await _upsert_sold_ad(
                        conn, source.source_name, ad, house_id,
                        ad_lat=ad_lat, ad_lng=ad_lng,
                    )
                    res.ads_processed += 1
                    if not inserted:
                        res.ads_unchanged += 1
                except Exception as exc:
                    log.exception(f"process failed for {ext_id}: {exc}")
                    res.fetch_failures += 1

            # Progress
            done = batch_start + len(batch)
            elapsed = time.monotonic() - t0
            rate = done / elapsed if elapsed > 0 else 0
            log.info(
                f"[{done}/{n}] processed={res.ads_processed} matched="
                f"{res.houses_matched_exact + res.houses_matched_geo} "
                f"(exact={res.houses_matched_exact}, geo={res.houses_matched_geo}) "
                f"houses_created={create_stats.created} "
                f"fetch_fail={res.fetch_failures} parse_fail={res.parse_failures} "
                f"rate={rate:.1f}/s elapsed={elapsed:.0f}s"
            )

        elapsed = time.monotonic() - t0
        log.info(
            f"DONE processed={res.ads_processed} matched="
            f"{res.houses_matched_exact + res.houses_matched_geo} "
            f"houses_created={create_stats.created} "
            f"fetch_fail={res.fetch_failures} parse_fail={res.parse_failures} "
            f"in {elapsed:.0f}s ({len(items) / max(1, elapsed):.1f} ads/s)"
        )
        log.info(f"Source stats: {source.fetch_total} fetches, {source.fetch_404s} 404s, {source.fetch_other_errors} errors")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

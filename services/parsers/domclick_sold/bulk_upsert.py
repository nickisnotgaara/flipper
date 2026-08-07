"""Parallel backfill for domclick_sold.

Bypasses BFF (which needs extra auth) — reads IDs from existing
domclick_links.json (May 3 snapshot) and parses HTML pages in parallel
with the working PAGE cookie. Writes directly to sold_ads via the v2
pipeline helper, but does the fetch concurrently for speed.

Run from inside the domclick_sold container (or locally with PYTHONPATH).
"""
import asyncio
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
import ssl
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
LINKS_JSON = THIS_DIR / "domclick_links.json"

# Reuse the v2 parser pieces
PROJECT_ROOT = THIS_DIR.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "services"))

from services.parsers.domclick_sold.acquirer import (
    PAGE_HEADERS,
    extract_ssr_state_json,
    parse_offer_html,
)
from packages.flipper_db.sources.domclick import DomclickSource, domclickUrlsToCianPhotos

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("domclick_bulk")

CONCURRENCY = 20
TIMEOUT = 60.0


def http_get(url: str, cookie: str) -> tuple[int, bytes]:
    h = dict(PAGE_HEADERS)
    h["Cookie"] = cookie
    req = urllib.request.Request(url, headers=h, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context()) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if e.fp else b""


async def fetch_one(sem, session_cookie, url):
    async with sem:
        return await asyncio.to_thread(http_get, url, session_cookie)


async def main():
    cookie = os.environ.get("DOMCLICK_PAGE_COOKIE")
    if not cookie:
        log.error("DOMCLICK_PAGE_COOKIE env var is required")
        return 1
    if not LINKS_JSON.is_file():
        log.error(f"{LINKS_JSON} not found")
        return 1
    doc = json.loads(LINKS_JSON.read_text(encoding="utf-8"))
    items = doc.get("items") or []
    log.info(f"Loaded {len(items)} items from {LINKS_JSON.name}")

    # Optionally limit via env
    limit = int(os.environ.get("LIMIT", "0"))
    if limit > 0:
        items = items[:limit]
        log.info(f"LIMIT applied: now {len(items)} items")

    source = DomclickSource()

    sem = asyncio.Semaphore(CONCURRENCY)
    t0 = time.monotonic()
    ok = 0
    fail = 0
    parse_fail = 0

    # Process in chunks to avoid memory blowup
    chunk_size = CONCURRENCY * 4
    for chunk_start in range(0, len(items), chunk_size):
        chunk = items[chunk_start:chunk_start + chunk_size]
        tasks = []
        for it in chunk:
            url = it.get("path")
            if not url:
                continue
            tasks.append((it, url, asyncio.create_task(fetch_one(sem, cookie, url))))

        for it, url, task in tasks:
            try:
                code, body = await task
                if code != 200:
                    fail += 1
                    continue
                text = body.decode("utf-8", errors="replace")
                try:
                    parsed = parse_offer_html(text, it, url)
                except Exception as e:
                    log.warning(f"parse fail {url}: {e}")
                    parse_fail += 1
                    continue
                # Print sample first
                if ok == 0 and parse_fail == 0:
                    log.info(f"First OK: id={parsed.get('id')}, price={parsed.get('price')}, address={parsed.get('address')}")
                ok += 1
            except Exception as e:
                log.warning(f"task fail {url}: {e}")
                fail += 1

        elapsed = time.monotonic() - t0
        rate = (ok + fail + parse_fail) / elapsed if elapsed > 0 else 0
        done = chunk_start + len(chunk)
        log.info(
            f"progress: {done}/{len(items)} ok={ok} fail={fail} parse_fail={parse_fail} "
            f"({rate:.1f}/s, {elapsed:.0f}s elapsed)"
        )

    log.info(f"DONE ok={ok} fail={fail} parse_fail={parse_fail} in {time.monotonic()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

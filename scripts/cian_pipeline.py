"""
cian_pipeline — CLI orchestrator for cian HTML → PostgreSQL.

Use cases:
  1) ingest a directory of cian offer HTMLs:
       py scripts/cian_pipeline.py ingest-dir <dir> [--limit N] [--recursive]
  2) ingest a single HTML file:
       py scripts/cian_pipeline.py ingest-file <path.html>
  3) ingest a list of cian offer URLs (fetched live via dataimpulse + cookies):
       py scripts/cian_pipeline.py ingest-urls <urls.txt> [--limit N]
  4) print a summary without writing:
       py scripts/cian_pipeline.py dry-run <dir>

Each HTML is parsed with cian_parse.parse_offer (pure), then upserted via
cian_db.upsert_batch (idempotent, async). Re-running on the same input is
safe — duplicate (source, cian_id) pairs are updated in place.

This script is intentionally narrow:
  - No proxy / cookie logic lives here. That's cian_fetch's job.
  - HTML bytes are NEVER saved to disk (per user spec).
  - No "phase 1, phase 2, ..." orchestration. Just parse -> upsert -> done.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

# Make sibling modules importable when this script is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import asyncpg

import cian_db
import cian_fetch
import cian_parse
from cian_parse import OfferRecord


log = logging.getLogger("cian_pipeline")


# ---------- IO ----------

def iter_html_files(root: Path, recursive: bool = False) -> Iterable[Path]:
    """Yield every .html under root. Non-recursive by default; pass
    --recursive to walk subdirectories too. Symlinks are followed once.
    """
    if root.is_file():
        if root.suffix.lower() in (".html", ".htm"):
            yield root
        return
    if not root.is_dir():
        return
    if recursive:
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in (".html", ".htm"):
                yield p
    else:
        for p in root.iterdir():
            if p.is_file() and p.suffix.lower() in (".html", ".htm"):
                yield p


def load_offer_from_file(path: Path) -> Optional[OfferRecord]:
    """Read a single HTML file and return its OfferRecord, or None if it
    has no usable offerData. Errors are logged but never raised.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.warning("read failed %s: %s", path, exc)
        return None
    try:
        return cian_parse.parse_offer(text)
    except Exception as exc:  # parser is supposed to be safe, but be paranoid
        log.warning("parse failed %s: %s", path, exc)
        return None


def load_offers_from_urls(
    urls: List[str],
    *,
    fetcher_settings: Optional[cian_fetch.FetchSettings] = None,
    rotator: Optional[cian_fetch.ProxyRotator] = None,
    sleep_between: float = 0.3,
) -> Tuple[List[OfferRecord], List[Tuple[str, str]]]:
    """Fetch each URL live, parse it, return (offers, failures).
    HTML is parsed in-memory; we never write the bytes to disk.
    """
    settings = fetcher_settings or cian_fetch.FetchSettings.from_env()
    rotator = rotator or cian_fetch.ProxyRotator()
    parsed: List[OfferRecord] = []
    failures: List[Tuple[str, str]] = []
    for url, html, err in cian_fetch.iter_fetch(
        urls, settings=settings, rotator=rotator, sleep_between=sleep_between
    ):
        if err or html is None:
            failures.append((url, err or "no html"))
            continue
        try:
            rec = cian_parse.parse_offer(html)
        except Exception as exc:
            failures.append((url, f"parse: {exc}"))
            continue
        if rec is None:
            failures.append((url, "no offerData"))
            continue
        parsed.append(rec)
    return parsed, failures


# ---------- summary stats ----------

def summarize(offers: List[OfferRecord]) -> dict:
    """Roll up counts of a parsed list (used in --dry-run)."""
    n_total = len(offers)
    n_with_house = sum(1 for o in offers if o.cian_house_id is not None)
    n_with_price = sum(1 for o in offers if o.price is not None)
    n_with_geo = sum(1 for o in offers if o.lat is not None and o.lng is not None)
    n_unique_houses = len({o.cian_house_id for o in offers if o.cian_house_id is not None})
    return {
        "offers_parsed": n_total,
        "with_house_id": n_with_house,
        "with_price": n_with_price,
        "with_geo": n_with_geo,
        "unique_houses": n_unique_houses,
    }


# ---------- async orchestration ----------

async def ingest(
    paths: List[Path],
    *,
    dsn: Optional[str],
    limit: Optional[int],
    dry_run: bool,
) -> dict:
    """Read each path, parse, and (unless dry_run) upsert to PostgreSQL.
    Returns a summary dict with counters and timing.
    """
    started = time.monotonic()
    parsed: List[OfferRecord] = []
    failures: List[Tuple[Path, str]] = []
    for p in paths:
        if limit is not None and len(parsed) >= limit:
            break
        rec = load_offer_from_file(p)
        if rec is None:
            failures.append((p, "no offerData"))
            continue
        parsed.append(rec)
    parse_elapsed = time.monotonic() - started

    summary = summarize(parsed)
    summary["files_seen"] = len(paths)
    summary["parse_failures"] = len(failures)
    summary["parse_seconds"] = round(parse_elapsed, 3)

    if dry_run or not parsed:
        summary["db_houses_upserted"] = 0
        summary["db_ads_upserted"] = 0
        summary["db_seconds"] = 0.0
        return summary

    db_started = time.monotonic()
    conn = await cian_db.connect(dsn)
    try:
        result = await cian_db.upsert_batch(conn, parsed)
    finally:
        await conn.close()
    summary["db_houses_upserted"] = result["houses"]
    summary["db_ads_upserted"] = result["ads"]
    summary["db_seconds"] = round(time.monotonic() - db_started, 3)
    summary["total_seconds"] = round(time.monotonic() - started, 3)
    return summary


async def ingest_urls(
    urls: List[str],
    *,
    dsn: Optional[str],
    limit: Optional[int],
    dry_run: bool,
    proxies_file: Optional[Path] = None,
    sleep_between: float = 0.3,
) -> dict:
    """Fetch each URL live (dataimpulse + cian cookies), parse, upsert.
    HTML is held in memory only; never written to disk.
    """
    started = time.monotonic()
    rotator = (
        cian_fetch.ProxyRotator(
            proxies_file.read_text(encoding="utf-8").splitlines()
        )
        if proxies_file and proxies_file.is_file()
        else cian_fetch.ProxyRotator()
    )
    fetcher_settings = cian_fetch.FetchSettings.from_env()
    capped = urls if limit is None else urls[:limit]
    log.info(
        "fetching %d urls (proxy pool=%d, retries=%d, timeout=%.1fs)",
        len(capped), rotator.count, fetcher_settings.retries, fetcher_settings.timeout,
    )
    parsed, fetch_failures = load_offers_from_urls(
        capped, fetcher_settings=fetcher_settings, rotator=rotator, sleep_between=sleep_between
    )
    fetch_elapsed = time.monotonic() - started
    summary = summarize(parsed)
    summary["urls_seen"] = len(capped)
    summary["fetch_failures"] = len(fetch_failures)
    summary["fetch_seconds"] = round(fetch_elapsed, 3)
    if fetch_failures and len(fetch_failures) <= 20:
        summary["fetch_failure_samples"] = [
            {"url": u, "error": e} for u, e in fetch_failures
        ]

    if dry_run or not parsed:
        summary["db_houses_upserted"] = 0
        summary["db_ads_upserted"] = 0
        summary["db_seconds"] = 0.0
        return summary

    db_started = time.monotonic()
    conn = await cian_db.connect(dsn)
    try:
        result = await cian_db.upsert_batch(conn, parsed)
    finally:
        await conn.close()
    summary["db_houses_upserted"] = result["houses"]
    summary["db_ads_upserted"] = result["ads"]
    summary["db_seconds"] = round(time.monotonic() - db_started, 3)
    summary["total_seconds"] = round(time.monotonic() - started, 3)
    return summary


# ---------- CLI ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cian_pipeline",
        description="Parse cian offer HTML and upsert to PostgreSQL.",
    )
    p.add_argument("--dsn", default=None, help="PostgreSQL DSN. Defaults to flipper@127.0.0.1.")
    p.add_argument("--log-level", default="INFO")

    sub = p.add_subparsers(dest="cmd", required=True)

    p_dir = sub.add_parser("ingest-dir", help="Ingest every .html under a directory.")
    p_dir.add_argument("dir", type=Path, help="Path to a directory of cian offer HTMLs.")
    p_dir.add_argument("--recursive", action="store_true", help="Recurse into subdirs.")
    p_dir.add_argument("--limit", type=int, default=None, help="Max files to ingest.")
    p_dir.add_argument("--dry-run", action="store_true", help="Parse only; do not write to DB.")

    p_file = sub.add_parser("ingest-file", help="Ingest a single HTML file.")
    p_file.add_argument("path", type=Path, help="Path to a single cian offer HTML.")
    p_file.add_argument("--dry-run", action="store_true")

    p_urls = sub.add_parser(
        "ingest-urls",
        help="Fetch live cian offer URLs (dataimpulse + cookies) and upsert. "
             "HTML is parsed in-memory, never written to disk.",
    )
    p_urls.add_argument(
        "urls_file", type=Path,
        help="Path to a .txt file with one cian.ru/sale/flat/.../ URL per line.",
    )
    p_urls.add_argument("--limit", type=int, default=None, help="Max URLs to fetch.")
    p_urls.add_argument("--dry-run", action="store_true", help="Parse only; do not write to DB.")
    p_urls.add_argument(
        "--proxies-file", type=Path, default=None,
        help="Optional proxy list (one URL per line). Defaults to env CIAN_PROXY or the bundled dataimpulse proxy.",
    )
    p_urls.add_argument(
        "--sleep", type=float, default=0.3,
        help="Seconds to sleep between successful fetches (rate limit politeness).",
    )

    p_dry = sub.add_parser("dry-run", help="Alias for `ingest-dir --dry-run`.")
    p_dry.add_argument("dir", type=Path)
    p_dry.add_argument("--recursive", action="store_true")
    p_dry.add_argument("--limit", type=int, default=None)

    return p


def _read_urls(path: Path) -> List[str]:
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


async def main_async(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    if args.cmd in ("ingest-dir", "dry-run"):
        paths = list(iter_html_files(args.dir, recursive=args.recursive))
        dry = args.cmd == "dry-run" or getattr(args, "dry_run", False)
        limit = args.limit
        if not paths:
            print(json.dumps({"error": "no files found", "root": str(args.dir)}, ensure_ascii=False))
            return 1
        summary = await ingest(paths, dsn=args.dsn, limit=limit, dry_run=dry)
    elif args.cmd == "ingest-file":
        paths = [args.path]
        dry = args.dry_run
        limit = 1
        summary = await ingest(paths, dsn=args.dsn, limit=limit, dry_run=dry)
    elif args.cmd == "ingest-urls":
        if not args.urls_file.is_file():
            print(json.dumps({"error": "urls file not found", "path": str(args.urls_file)}, ensure_ascii=False))
            return 1
        urls = _read_urls(args.urls_file)
        if not urls:
            print(json.dumps({"error": "no urls in file", "path": str(args.urls_file)}, ensure_ascii=False))
            return 1
        summary = await ingest_urls(
            urls,
            dsn=args.dsn,
            limit=args.limit,
            dry_run=args.dry_run,
            proxies_file=args.proxies_file,
            sleep_between=args.sleep,
        )
    else:
        raise SystemExit(f"unknown cmd: {args.cmd}")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

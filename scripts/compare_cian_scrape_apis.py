#!/usr/bin/env python3
"""
Shadow-сравнение POST /v2/scrape (legacy LLM) и POST /v2/cian/scrape (static).

Запуск из корня репозитория:
  python scripts/compare_cian_scrape_apis.py
  python scripts/compare_cian_scrape_apis.py --cookie "name=value; ..."

Требует живой flippercrawl (FLIPPERCRAWL_BASE_URL, FLIPPERCRAWL_API_KEY).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv()


def build_cian_scrape_body(url: str, cookie: str = "") -> dict:
    body: dict = {"url": url.strip()}
    if cookie.strip():
        body["headers"] = {"Cookie": cookie.strip()}
    return body

DEFAULT_URLS = [
    "https://www.cian.ru/sale/flat/327273828/",
    "https://www.cian.ru/sale/flat/328663696/",
    "https://www.cian.ru/sale/flat/297346236/",
    "https://www.cian.ru/sale/flat/313326812/",
    "https://www.cian.ru/sale/flat/326002860/",
    "https://www.cian.ru/sale/flat/320000001/",
    "https://www.cian.ru/sale/flat/318500123/",
    "https://www.cian.ru/sale/flat/315000456/",
    "https://www.cian.ru/sale/flat/310000789/",
    "https://www.cian.ru/sale/flat/305000321/",
    "https://irkutsk.cian.ru/sale/flat/327214373/",
    "https://www.cian.ru/sale/flat/329100654/",
]

CRITICAL_FIELDS = [
    "cian_id",
    "price",
    "area",
    "rooms",
    "is_active",
    "has_avans_deposit",
]

NESTED_FIELDS = [
    ("address", "full"),
    ("address", "district"),
    ("address", "metro_station"),
    ("address", "okrug"),
    ("floor_info", "current"),
    ("floor_info", "all"),
]


def _load_legacy_body_template() -> dict:
  """Legacy scrape body from reference file or minimal fallback."""
  ref = ROOT / "data" / "scrape_body_current.json"
  if ref.is_file():
      return json.loads(ref.read_text(encoding="utf-8"))
  # Fallback: build via removed AdParser helpers is unavailable — use cian scrape only
  raise FileNotFoundError(
      f"Legacy body template not found: {ref}. "
      "Place scrape_body_current.json in data/ for shadow comparison with /v2/scrape."
  )


def _get_nested(data: dict, parent: str, child: str) -> Any:
    block = data.get(parent) or {}
    if not isinstance(block, dict):
        return None
    return block.get(child)


def _compare_price_history(old: list | None, new: list | None) -> list[str]:
    diffs: list[str] = []
    old = old or []
    new = new or []
    if len(old) != len(new):
        diffs.append(f"price_history length {len(old)} != {len(new)}")
        return diffs
    for i, (o, n) in enumerate(zip(old, new)):
        if not isinstance(o, dict) or not isinstance(n, dict):
            continue
        od = o.get("date")
        nd = n.get("date")
        op = o.get("price")
        np_ = n.get("price")
        if od != nd or op != np_:
            diffs.append(
                f"price_history[{i}]: old=({od},{op}) new=({nd},{np_})"
            )
    return diffs


def _compare_json(old: dict, new: dict) -> list[str]:
    diffs: list[str] = []
    for field in CRITICAL_FIELDS:
        ov, nv = old.get(field), new.get(field)
        if ov != nv:
            diffs.append(f"{field}: {ov!r} != {nv!r}")
    for parent, child in NESTED_FIELDS:
        ov = _get_nested(old, parent, child)
        nv = _get_nested(new, parent, child)
        if ov != nv:
            diffs.append(f"{parent}.{child}: {ov!r} != {nv!r}")
    diffs.extend(_compare_price_history(old.get("price_history"), new.get("price_history")))
    return diffs


def _post_scrape(
    client: httpx.Client,
    base: str,
    path: str,
    body: dict,
    api_key: str,
) -> dict:
    resp = client.post(
        f"{base.rstrip('/')}{path}",
        json=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=180.0,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(data.get("error") or f"success=false for {path}")
    return data["data"]["json"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default=os.getenv("FLIPPERCRAWL_BASE_URL", "http://localhost:3002"))
    ap.add_argument("--api-key", default=os.getenv("FLIPPERCRAWL_API_KEY", "test-key"))
    ap.add_argument("--cookie", default="", help="Cookie string for Cian")
    ap.add_argument("--urls-file", default="", help="JSON file with list of URLs")
    ap.add_argument("--skip-legacy", action="store_true", help="Only smoke-test /v2/cian/scrape")
    args = ap.parse_args()

    urls = DEFAULT_URLS
    if args.urls_file.strip():
        urls = json.loads(Path(args.urls_file.strip()).read_text(encoding="utf-8"))

    legacy_template = None
    if not args.skip_legacy:
        try:
            legacy_template = _load_legacy_body_template()
        except FileNotFoundError as e:
            print(f"WARN: {e}")
            print("Continuing with --skip-legacy mode (cian scrape smoke only).")
            args.skip_legacy = True

    fails = 0
    print(f"Base URL: {args.base_url}")
    print(f"URLs: {len(urls)}")
    print("-" * 80)

    with httpx.Client(trust_env=False) as client:
        for url in urls:
            cian_body = build_cian_scrape_body(url, args.cookie)
            try:
                new_json = _post_scrape(
                    client, args.base_url, "/v2/cian/scrape", cian_body, args.api_key
                )
            except Exception as e:
                print(f"FAIL {url}: cian/scrape error: {e}")
                fails += 1
                continue

            mode = new_json.pop("_extraction_mode", "?")
            if args.skip_legacy:
                cid = new_json.get("cian_id")
                price = new_json.get("price")
                print(f"OK   {url} mode={mode} cian_id={cid} price={price}")
                continue

            legacy_body = {**legacy_template, "url": url}
            if args.cookie.strip():
                legacy_body["headers"] = {"Cookie": args.cookie.strip()}
            try:
                old_json = _post_scrape(
                    client, args.base_url, "/v2/scrape", legacy_body, args.api_key
                )
            except Exception as e:
                print(f"FAIL {url}: legacy scrape error: {e}")
                fails += 1
                continue

            diffs = _compare_json(old_json, new_json)
            if diffs:
                fails += 1
                print(f"FAIL {url} mode={mode}")
                for d in diffs:
                    print(f"      {d}")
            else:
                print(f"PASS {url} mode={mode}")

    print("-" * 80)
    print(f"Done: {fails} FAIL, {len(urls) - fails} OK")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

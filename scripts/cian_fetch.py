"""
cian_fetch — fetch cian offer HTML pages using dataimpulse proxy + cookies.

Pattern copied from secondary/cian (parser/clients/http.py + parser/cookies.py +
parser/proxy.py), adapted for our pipeline: instead of returning parsed JSON
from cian's API endpoints, this module returns raw HTML bytes that the existing
cian_parse.parse_offer() can consume.

The cian page is a single SSR HTML document; the offer data is embedded as
JSON inside window._cianConfig['frontend-offer-card'] and extracted by
_parse_offer_data. We do NOT save the HTML anywhere — pipeline discards it
after parsing (per user requirement: "при парсинге не сохраняем сам файл
или его html, только парсим нужные данные уже в firecrawl").

Public API:
    fetch_offer_page(url, *, proxy, cookie, user_agent, timeout) -> str
    iter_fetch(urls, *, proxy, cookie, user_agent, timeout, retries, sleep)
        -> Iterator[(url, html | None, error_str | None)]
    Fetcher class — async wrapper with bounded concurrency
"""
from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Sequence, Tuple

import requests

log = logging.getLogger("cian_fetch")

DEFAULT_COOKIE_SERVER_URL = "http://72.56.33.73:8000/cookies"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

DEFAULT_PROXY = (
    "http://ebcb8426a4161f417253__cr.kz,uz,ru:44931d094ae8216a@gw.dataimpulse.com:823"
)


# ---------- cookies ----------

def _cookies_list_to_header(cookie_list) -> str:
    parts: List[str] = []
    for item in cookie_list:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not name:
            continue
        parts.append(f"{name}={item.get('value', '')}")
    return "; ".join(parts)


_cached_cookie_header: Optional[str] = None


def fetch_cookies_header(
    url: str = DEFAULT_COOKIE_SERVER_URL,
    *,
    timeout: float = 15.0,
    force_refresh: bool = False,
) -> str:
    """Fetch cookies from the cookie server, return a single Cookie header."""
    global _cached_cookie_header
    if _cached_cookie_header is not None and not force_refresh:
        return _cached_cookie_header
    log.info("Fetching cian cookies from %s ...", url)
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise ValueError(f"Unexpected cookie server response: {type(data)}")
    header = _cookies_list_to_header(data)
    if not header:
        raise ValueError("Cookie server returned empty cookie list")
    _cached_cookie_header = header
    log.info("Got %d cookies from server", len(data))
    return header


# ---------- proxy rotation ----------

class ProxyRotator:
    """Round-robin proxy list. If the list is empty, returns the default
    dataimpulse proxy (so a single proxy still works for the smoke test)."""

    def __init__(self, proxy_lines: Sequence[str] | None = None) -> None:
        self._proxies: List[str] = []
        if proxy_lines:
            for line in proxy_lines:
                line = line.strip()
                if line:
                    self._proxies.append(self._format(line))
        # If user gave a single proxy in .env, accept it
        env_proxy = os.environ.get("CIAN_PROXY", "").strip()
        if env_proxy and env_proxy not in self._proxies:
            self._proxies.insert(0, self._format(env_proxy))
        if not self._proxies:
            self._proxies.append(self._format(DEFAULT_PROXY))
        random.shuffle(self._proxies)
        self._idx = 0

    @staticmethod
    def _format(raw: str) -> str:
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        return f"http://{raw}"

    @property
    def count(self) -> int:
        return len(self._proxies)

    def next(self) -> str:
        if not self._proxies:
            return self._format(DEFAULT_PROXY)
        p = self._proxies[self._idx % len(self._proxies)]
        self._idx += 1
        return p


# ---------- settings ----------

@dataclass(frozen=True)
class FetchSettings:
    proxy: str
    cookie_header: str
    user_agent: str
    timeout: float = 30.0
    retries: int = 3
    retry_base_delay: float = 1.5
    cookie_url: str = DEFAULT_COOKIE_SERVER_URL

    @classmethod
    def from_env(
        cls,
        *,
        proxy: Optional[str] = None,
        cookie_url: Optional[str] = None,
        timeout: float = 30.0,
        retries: int = 3,
        user_agent: Optional[str] = None,
    ) -> "FetchSettings":
        proxy = proxy or os.environ.get("CIAN_PROXY", "").strip() or DEFAULT_PROXY
        cookie_url = cookie_url or os.environ.get(
            "CIAN_COOKIE_SERVER_URL", DEFAULT_COOKIE_SERVER_URL
        ).strip()
        # Cookie header: try env, else fetch
        cookie_header = os.environ.get("CIAN_COOKIES", "").strip()
        if not cookie_header:
            cookie_header = fetch_cookies_header(cookie_url)
        return cls(
            proxy=proxy,
            cookie_header=cookie_header,
            user_agent=user_agent or DEFAULT_USER_AGENT,
            timeout=timeout,
            retries=retries,
            cookie_url=cookie_url,
        )


# ---------- single fetch ----------

def _build_headers(cookie: str, user_agent: str) -> dict:
    return {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "user-agent": user_agent,
        "Cookie": cookie,
    }


def fetch_offer_page(
    url: str,
    *,
    proxy: str,
    cookie_header: str,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: float = 30.0,
    session: Optional[requests.Session] = None,
) -> str:
    """Fetch a single cian offer page. Returns HTML text. Raises on transport
    failure (caller decides retry policy)."""
    headers = _build_headers(cookie_header, user_agent)
    proxies = {"http": proxy, "https": proxy}
    sess = session or requests.Session()
    sess.trust_env = False
    r = sess.get(url, headers=headers, proxies=proxies, timeout=timeout, allow_redirects=True)
    if r.status_code in (403, 429) or r.status_code >= 500:
        raise requests.HTTPError(f"HTTP {r.status_code} for {url}", response=r)
    if r.status_code >= 400:
        # client error — likely permanent
        raise requests.HTTPError(f"HTTP {r.status_code} for {url}", response=r)
    return r.text


def iter_fetch(
    urls: Iterable[str],
    *,
    settings: FetchSettings,
    rotator: Optional[ProxyRotator] = None,
    sleep_between: float = 0.3,
) -> Iterator[Tuple[str, Optional[str], Optional[str]]]:
    """Yield (url, html_or_None, error_str_or_None) for each url. Never raises —
    errors are reported as the third tuple element."""
    rotator = rotator or ProxyRotator()
    sess = requests.Session()
    sess.trust_env = False
    for url in urls:
        url = url.strip()
        if not url:
            continue
        last_err: Optional[str] = None
        for attempt in range(1, settings.retries + 1):
            proxy = rotator.next()
            try:
                html = fetch_offer_page(
                    url,
                    proxy=proxy,
                    cookie_header=settings.cookie_header,
                    user_agent=settings.user_agent,
                    timeout=settings.timeout,
                    session=sess,
                )
                if "defaultState" not in html or "offerData" not in html:
                    last_err = "no offerData in response"
                else:
                    yield url, html, None
                    break
            except Exception as exc:
                last_err = f"{type(exc).__name__}: {exc}"
            if attempt < settings.retries:
                delay = settings.retry_base_delay * (2 ** (attempt - 1))
                delay += random.uniform(0, 0.25)
                log.debug("retry %s in %.2fs: %s", url, delay, last_err)
                time.sleep(delay)
        else:
            yield url, None, last_err or "unknown failure"
        if sleep_between > 0:
            time.sleep(sleep_between)


# ---------- CLI sanity (used by smoke tests) ----------

def _main() -> int:
    import argparse
    import json

    p = argparse.ArgumentParser(description="Fetch one or more cian offer URLs.")
    p.add_argument("urls", nargs="+", help="One or more cian.ru/sale/flat/.../ URLs")
    p.add_argument("--proxy", default=None, help="Override proxy URL")
    p.add_argument("--cookie-url", default=None)
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--proxies-file", default=None, help="Path to proxy list (one per line)")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    rotator: Optional[ProxyRotator] = None
    if args.proxies_file:
        lines = Path(args.proxies_file).read_text(encoding="utf-8").splitlines()
        rotator = ProxyRotator(lines)
    settings = FetchSettings.from_env(
        proxy=args.proxy,
        cookie_url=args.cookie_url,
        timeout=args.timeout,
        retries=args.retries,
    )
    out = []
    for url, html, err in iter_fetch(args.urls, settings=settings, rotator=rotator):
        if err:
            out.append({"url": url, "ok": False, "error": err})
        else:
            out.append({
                "url": url,
                "ok": True,
                "size": len(html or ""),
                "has_offerData": "offerData" in (html or ""),
            })
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if all(o["ok"] for o in out) else 1


if __name__ == "__main__":
    raise SystemExit(_main())

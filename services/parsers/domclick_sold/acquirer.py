#!/usr/bin/env python3
"""
services.parsers.domclick_sold.acquirer - парсер Domclick.

BFF-список (API_COOKIE) + карточки HTML (PAGE_COOKIE из браузера).
Аргументы: только --workers и --mode (list | cards | full).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import ssl
import time
from collections import OrderedDict
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# --- статика из offers.bash (при необходимости обновите вручную) ---

LIST_URL = (
    "https://bff-search-web.domclick.ru/api/offers/sold/v1?"
    "address=1d1463ae-c80f-4d19-9331-a1b68a85b553&offset=0&limit=20&"
    "sort=sold_dt&sort_dir=desc&deal_type=sold_sale&category=living&"
    "offer_type=flat&aids=2299&floor_not_first=1&is_apartment=0"
)

API_COOKIE = os.environ.get(
    "DOMCLICK_API_COOKIE",
    # Legacy fallback (stale — Qrator ~1yr). Override via env on prod.
    "ns_session=87dca04d-9f52-496b-b0e7-fc0ef5fd7b1d; "
    "max-chat-settings-show=%7B%22countOfEntry%22%3A4%2C%22lastStatus%22%3A%22NOT_CREATED%22%7D; "
    "_ym_uid=177186413778171625; _ym_d=1776362284; logoSuffix=; showDddIntro=false; "
    "dddIntroOnline=false; _sv=SV1.f15bc47c-aef3-4b5f-af0b-06c7a6e6815c.1771864192; "
    "adtech_uid=08a95931-5005-4dde-98aa-eaa3a55ce1c7%3Adomclick.ru; "
    "top100_id=t1.7711713.601821872.1776362284811; "
    "tmr_lvid=f18418b3a862bab0cbfe2187ea9738f9; tmr_lvidTS=1771864138346; regionAlert=1; "
    "currentRegionGuid=1d1463ae-c80f-4d19-9331-a1b68a85b553; "
    "regionName=1d1463ae-c80f-4d19-9331-a1b68a85b553:%D0%9C%D0%BE%D1%81%D0%BA%D0%B2%D0%B0; "
    "currentLocalityGuid=1d1463ae-c80f-4d19-9331-a1b68a85b553; "
    "region={%22data%22:{%22name%22:%22%D0%9C%D0%BE%D1%81%D0%BA%D0%B2%D0%B0%22%2C%22regionGuid%22:%221d1463ae-c80f-4d19-9331-a1b68a85b553%22%2C%22localityGuid%22:%221d1463ae-c80f-4d19-9331-a1b68a85b553%22}%2C%22isAutoResolved%22:true}; "
    "canary-bind-id-13078=next-1; CAS_ID=54308715; "
    "CAS_ID_SIGNED=eyJleHAiOiAxNzg1NTAzNzkzLCAidGd0IjogIlRHVC0zMDY1OC1xVWU1QldZVEoxSGVKQkJNbGp2R3FVQ21mTUVLYmYwQlIyb2FnMnVjZU5iYlpuUWVpWi1jYXMubGMiLCAiY2FzSWQiOiA1NDMwODcxNSwgImxvZ2luVHlwZSI6ICJTQkVSX0lEX0xJVEUiLCAic3ViIjogImVhZTU4M2UyNjJhMGJiZDIzMmMxMmQyMmMzODZmNWU1ZWQwNzhiNTQ5NTM1MzIxYjMzZmVmNTdmYzk2Y2EwNzJjOTI0YmNmODExZDQyNDc1Iiwic2JlclV1aWQiOiAiNGI2MTA2MTdlMjk4NjZlMmFiYTUxMzM2NDVjNGYyZWYyYjU5YzIwMDYxMGE5ZjU1MTlhYjczYzdmNmZjNTdjZDU5MTYxNTRiNjJlODQzZGIiLCJzYmVyVmVyaWZpZWQiOiBmYWxzZSwibG9naW5UaW1lIjogMTc3NzYxOTc5M30=.BeJZxg1kaEHrwITGNFZC4JlQh6U6Jo73UuBuJmPtIh/HWhZAl2TQnRmkitrMtqWrkoaSHwAKz899YJMYIx1Ghy/NviB6drxtymo7PCXrlq3ImCUtg3Psc3LqDCYfLjZOy52UceOYCN1yFqM1bRvVh0AFOjQz7YG26L13gk0Leh0=; "
    "TGT_COPY=TGT-30658-qUe5BWYTJ1HeJBBMljvGqUCmfMEKbf0BR2oag2uceNbbZnQeiZ-cas.lc; "
    "ftgl_cookie_id=c14badf2eaad75fa1e47b6eb608c43d0; "
    "RETENTION_COOKIES_NAME=e88a70bb5c124e33bbda4f3e90f60a45:mC8JQTpvZb9GyMliTYgpgxY4-gk; "
    "sessionId=ac556e7d94104d79aab93c6a880e5265:ZO65u_AR3J3qN4JvetJWPDCPIaM; "
    "UNIQ_SESSION_ID=7842decca19d421d86ebaadd0c46b05b:pacyo2KTeT-yF_4ZWdVnUTC0mjs; "
    "iosAppLink=; _ym_isad=2; "
    "t3_sid_7731951=s1.1034783954.1777756836647.1777756997544.4.29.3.1..; "
    "qrator_jsid2=v2.0.1777756787.048.92463436YIBbcYR4|UZsBNr6zajwGEPEY|nB17zDl+4TVoh3vYEmwPaO2aBcLT6b+QEpDp07C3EgvIYvonk6Or5BpCleVOxx4gZzVseLIz/V30Uw7y2K/P5wuQ29Iuvo9tSbiQQDPofUgcaLqVxx9+QBoSx+pd7T3philpEJ1y4v4vjE4YeeddmUHYu8FgoPAuFoqGLqSVgFI=-GxyPrxGVEHhtHPJ4CC0uLTCk4+4=; "
    "_sas.2c534172f17069dd8844643bb4eb639294cd4a7a61de799648e70dc86bc442b9=SV1.f15bc47c-aef3-4b5f-af0b-06c7a6e6815c.1771864192.1777763498; "
    "isPartnerTopline=1; _visitId=c0e8d8e0-0251-403d-8a1b-25b4451d9910-f4f0dcc432ac8ba6; "
    "_sas=SV1.f15bc47c-aef3-4b5f-af0b-06c7a6e6815c.1771864192.1777763501; "
    "t3_sid_7711713=s1.1153297741.1777763498783.1777763740762.8.22.4.1..; tmr_reqNum=162"
)

# Карточки /card/... — без cookie часто 401 (Qrator и сессия). См. offer-document.bash
# Override via DOMCLICK_PAGE_COOKIE env (если задан) — обычно совпадает с API_COOKIE,
# но при желании можно задать отдельный.
PAGE_COOKIE = os.environ.get(
    "DOMCLICK_PAGE_COOKIE",
    "qrator_jsr=v2.0.1777767082.797.52d76607h9ib7ny9|d0VpKi7neFUd5o6a|"
    "fkRm3y8+glG70OlOCbINceM76sCvsG3gXB9L9t2S3hHkHzpIphOwjvvxOBZ1+vtl3sFHn0fdwPFzx3iUekH+dw==-"
    "g3h69dK/D7GiFgc55O/WYXNfXIc=-00; "
    "qrator_jsid2=v2.0.1777767082.797.52d76607h9ib7ny9|go0gFNyPY2XwAnmE|"
    "IqTfFDzO8AEGOXbUFAqhB4oQ/OTIINM4FL9XRBYhg7KqdFHraNJppimElI8NvrkiXUTQv24acK8TaDEGWM9IrcbgnpQJQsxr1EZO/dNWMazFbvBCJ+ghrvB38ipTu+HPG4GRaxT36ep12Ij9brPBvXkKHk+KjOrB3Us9vYGN928=-"
    "JXIJU2VJyQ4VnBbflAMxGZOgp3g=; "
    "ns_session=9bf9fca7-9b19-4e7b-8300-b0a18e63d093; logoSuffix=; iosAppLink=; showDddIntro=false; "
    "dddIntroOnline=false; _ym_uid=1777767084415499213; _ym_d=1777767084; "
    "RETENTION_COOKIES_NAME=4fcfb28242c545e0b3734c78eb3bd0be:iQbscAgxq2mfX6hi42SOYExMVoE; "
    "sessionId=5e6baa40c3584876bb73cd8514904e3f:5MB8B2R4vTBrvhC0nUx6yzkKKNE; "
    "UNIQ_SESSION_ID=a2ce581464e34b11971b17d930e3a452:FlNpj94TF1TIcbYICX3uxNsEcJo; _ym_isad=2; "
    "_sv=SV1.00462ab7-d956-4874-a67d-d9a4e4879270.1777767040; "
    "_sas.2c534172f17069dd8844643bb4eb639294cd4a7a61de799648e70dc86bc442b9="
    "SV1.00462ab7-d956-4874-a67d-d9a4e4879270.1777767040.1777767084; "
    "_visitId=ca8a781e-6984-4381-81f5-3e92bc6c8c38-f4f0dcc432ac8ba6; "
    "adtech_uid=85f038dc-498a-4c80-90a6-2567f774d219%3Adomclick.ru; "
    "top100_id=t1.7711713.578157722.1777767084713; "
    "region={%22data%22:{%22name%22:%22%D0%9C%D0%BE%D1%81%D0%BA%D0%B2%D0%B0%22%2C%22regionGuid%22:%221d1463ae-c80f-4d19-9331-a1b68a85b553%22}%2C%22isAutoResolved%22:true}; "
    "tmr_lvid=d68be592fc814b2d11898e60e3835500; tmr_lvidTS=1777767085322; regionAlert=1; "
    "_sas=SV1.00462ab7-d956-4874-a67d-d9a4e4879270.1777767040.1777767086; "
    "tmr_detect=0%7C1777767087695; "
    "t3_sid_7711713=s1.1180009951.1777767084714.1777767091151.1.4.1.0..; tmr_reqNum=11"
)

LIST_PAGE_LIMIT = 20
# Не более 100 страниц по 20 (offset 0…1980; при offset=2000 BFF отвечает 400).
MAX_LIST_PAGES = 100
MAX_LIST_OFFSET = MAX_LIST_PAGES * LIST_PAGE_LIMIT

_DIR = Path(__file__).resolve().parent
PATH_LINKS = _DIR / "domclick_links.json"
PATH_RESULT = _DIR / "domclick_result.json"

logger = logging.getLogger(__name__)

# --- HTTP ---

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)

API_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru,en;q=0.9",
    "Origin": "https://domclick.ru",
    "Referer": "https://domclick.ru/",
    "User-Agent": DEFAULT_UA,
}

PAGE_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
        "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en",
    "Cache-Control": "max-age=0",
    "Referer": "https://domclick.ru/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": DEFAULT_UA,
    'sec-ch-ua': '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    'sec-ch-ua-platform': '"Windows"',
}


def _ssl_ctx() -> ssl.SSLContext:
    return ssl.create_default_context()


def http_get(
    url: str,
    headers: dict[str, str],
    cookie: Optional[str] = None,
    timeout: float = 60.0,
) -> tuple[int, bytes]:
    h = dict(headers)
    if cookie:
        h["Cookie"] = cookie
    req = urllib.request.Request(url, headers=h, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if e.fp else b""


def retry_get(
    url: str,
    headers: dict[str, str],
    cookie: Optional[str] = None,
    timeout: float = 60.0,
    retries: int = 4,
    sleep: float = 1.5,
) -> tuple[int, bytes]:
    last: tuple[int, bytes] = (0, b"")
    for attempt in range(retries):
        code, body = http_get(url, headers, cookie=cookie, timeout=timeout)
        last = (code, body)
        if code == 200:
            return last
        if code in (429, 500, 502, 503, 504) and attempt < retries - 1:
            logger.warning(
                "HTTP %s, повтор %s/%s через %.1fs: %s",
                code,
                attempt + 1,
                retries - 1,
                sleep * (attempt + 1),
                url[:120],
            )
            time.sleep(sleep * (attempt + 1))
            continue
        return last
    return last


def set_query_param(url: str, **updates: Any) -> str:
    """Сохраняет порядок параметров как в LIST_URL (sorted() ломал часть BFF)."""
    parts = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    od: OrderedDict[str, str] = OrderedDict(pairs)
    for k, v in updates.items():
        od[k] = str(v)
    new_query = urllib.parse.urlencode(list(od.items()))
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, new_query, parts.fragment)
    )


def fetch_all_list_items(
    page_limit: int = LIST_PAGE_LIMIT,
    max_items: Optional[int] = None,
) -> list[dict[str, Any]]:
    first_url = set_query_param(LIST_URL, offset=0, limit=page_limit)
    code, raw = retry_get(first_url, API_HEADERS, cookie=API_COOKIE)
    if code != 200:
        raise RuntimeError(f"list API HTTP {code}: {raw[:500]!r}")
    data = json.loads(raw.decode("utf-8", errors="replace"))
    result = data.get("result") or {}
    pag = result.get("pagination") or {}
    api_total = int(pag.get("total") or 0)
    target_total = min(api_total, MAX_LIST_OFFSET)
    if max_items is not None:
        target_total = min(target_total, max_items)

    items: list[dict[str, Any]] = list(result.get("items") or [])
    normal_offset = len(items)

    logger.info(
        "Список: первая страница %s шт., в каталоге %s, цель %s (макс. %s стр. × %s)",
        len(items),
        api_total,
        target_total,
        MAX_LIST_PAGES,
        page_limit,
    )

    while len(items) < target_total and normal_offset < MAX_LIST_OFFSET:
        url = set_query_param(LIST_URL, offset=normal_offset, limit=page_limit)
        code, raw = retry_get(url, API_HEADERS, cookie=API_COOKIE)
        if code != 200:
            raise RuntimeError(
                f"list API HTTP {code} offset={normal_offset}: {raw[:500]!r}"
            )
        chunk = json.loads(raw.decode("utf-8", errors="replace"))
        batch = list((chunk.get("result") or {}).get("items") or [])
        if not batch:
            logger.warning("Список: пустая страница при offset=%s", normal_offset)
            break
        off = normal_offset
        items.extend(batch)
        normal_offset += len(batch)
        logger.info(
            "Список: offset=%s, +%s шт. (всего %s/%s)",
            off,
            len(batch),
            len(items),
            target_total,
        )
        if len(items) >= target_total:
            break

    if api_total > MAX_LIST_OFFSET:
        logger.warning(
            "В каталоге %s объявлений; из-за лимита API загружено не больше %s (%s×%s).",
            api_total,
            MAX_LIST_OFFSET,
            MAX_LIST_PAGES,
            page_limit,
        )

    return items[:target_total]


def save_links_snapshot(items: list[dict[str, Any]]) -> None:
    slim: list[dict[str, Any]] = []
    for it in items:
        path = it.get("path")
        if not path:
            continue
        slim.append(
            {
                "path": path,
                "publishedDate": it.get("publishedDate"),
                "soldDate": it.get("soldDate"),
                "id": it.get("id"),
            }
        )
    doc = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "count": len(slim),
        "items": slim,
    }
    PATH_LINKS.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def load_links_snapshot() -> list[dict[str, Any]]:
    if not PATH_LINKS.is_file():
        raise FileNotFoundError(
            f"Нет файла {PATH_LINKS}. Сначала запустите с --mode list или full."
        )
    doc = json.loads(PATH_LINKS.read_text(encoding="utf-8"))
    return list(doc.get("items") or [])


# --- SSR JSON ---


def extract_ssr_state_json(html: str) -> dict[str, Any]:
    marker = "window.__SSR_STATE__"
    end = "window.__SSR_CONTEXT__"
    if marker not in html or end not in html:
        raise ValueError("window.__SSR_STATE__ not found in HTML")
    chunk = html.split(end, 1)[0]
    _, rest = chunk.split(marker, 1)
    rest = rest.split("=", 1)[1].strip()
    if rest.endswith(";"):
        rest = rest[:-1].strip()
    rest = re.sub(r"\bundefined\b", "null", rest)
    rest = re.sub(r"\bNaN\b", "null", rest)
    rest = re.sub(r"\bInfinity\b", "null", rest)
    return json.loads(rest)


def _first_subway(orig: dict[str, Any]) -> dict[str, Any]:
    addr = orig.get("address") or {}
    subs = addr.get("subways") or []
    return subs[0] if subs else {}


def _district_label(orig: dict[str, Any]) -> Optional[str]:
    addr = orig.get("address") or {}
    parents = addr.get("parents") or []
    names: list[str] = []
    for p in parents:
        if p.get("kind") == "district" and p.get("name"):
            names.append(str(p["name"]))
    if not names:
        return None
    return ", ".join(names)


def _okrug(orig: dict[str, Any]) -> Optional[str]:
    addr = orig.get("address") or {}
    parents = addr.get("parents") or []
    for p in parents:
        n = str(p.get("name") or "")
        if "округ" in n.lower():
            return n
    return None


def _days_exposition(orig: dict[str, Any], list_meta: dict[str, Any]) -> Optional[int]:
    pub = list_meta.get("publishedDate") or orig.get("published_dt")
    sold = list_meta.get("soldDate")
    if not pub:
        return None
    try:
        pdt = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
    except ValueError:
        return None
    end: Optional[datetime] = None
    if sold:
        try:
            end = datetime.fromisoformat(str(sold).replace("Z", "+00:00"))
        except ValueError:
            end = None
    if end is None:
        end = datetime.now(timezone.utc)
    return max(0, (end.date() - pdt.date()).days)


def parse_offer_html(
    html: str,
    list_meta: dict[str, Any],
    page_url: str,
) -> dict[str, Any]:
    ssr = extract_ssr_state_json(html)
    pc = ssr.get("productCard") or {}
    orig = pc.get("originalProduct") or {}
    if not orig:
        raise ValueError("productCard.originalProduct missing")

    price_info = orig.get("price_info") or {}
    addr = orig.get("address") or {}
    oi = orig.get("object_info") or {}
    house = orig.get("house") or {}
    offer_stat = orig.get("offer_stat") or {}
    sub = _first_subway(orig)

    floor = oi.get("floor")
    floors = house.get("floors")
    floor_info: Optional[str] = None
    if floor is not None and floors is not None:
        floor_info = f"{floor}/{floors}"
    elif floor is not None:
        floor_info = str(floor)

    ren = oi.get("renovation")
    renovation = None
    if isinstance(ren, dict):
        renovation = ren.get("display_name")
    elif isinstance(ren, str):
        renovation = ren

    wall = house.get("wall_type")
    housing_type = wall.get("display_name") if isinstance(wall, dict) else None

    title = _extract_h1_title(html) or _extract_meta_title(html)

    oid = orig.get("id")
    href = (pc.get("href") or page_url).replace("\\u002F", "/")

    return {
        "url": href,
        "publish_date": orig.get("published_dt"),
        "price": price_info.get("price"),
        "title": title,
        "address": addr.get("short_display_name") or addr.get("display_name"),
        "description": orig.get("description") or oi.get("description"),
        "price_per_m2": price_info.get("square_price"),
        "area": oi.get("area"),
        "construction_year": house.get("build_year"),
        "days_in_exposition": _days_exposition(orig, list_meta),
        "district": _district_label(orig),
        "floor_info": floor_info,
        "housing_type": housing_type,
        "metro_station": sub.get("display_name"),
        "metro_walk_time": sub.get("time_on_foot"),
        "okrug": _okrug(orig),
        "renovation": renovation,
        "rooms": oi.get("rooms"),
        "total_views": offer_stat.get("views_count"),
        "unique_views": offer_stat.get("unique_views_count")
        or offer_stat.get("unique_views"),
        "id": oid,
    }


def _extract_h1_title(html: str) -> Optional[str]:
    m = re.search(
        r'<h1[^>]*id="title"[^>]*>(.*?)</h1>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return None
    inner = m.group(1)
    inner = re.sub(r"<[^>]+>", " ", inner)
    inner = re.sub(r"\s*,\s*", ", ", inner)
    inner = re.sub(r"\s+", " ", inner).strip()
    return inner or None


def _extract_meta_title(html: str) -> Optional[str]:
    m = re.search(
        r'<meta\s+property="og:title"\s+content="([^"]*)"',
        html,
        re.IGNORECASE,
    )
    return m.group(1).strip() if m else None


@dataclass
class Job:
    url: str
    list_meta: dict[str, Any]


def _job_from_link_entry(entry: dict[str, Any]) -> Optional[Job]:
    path = entry.get("path")
    if not path:
        return None
    url = str(path)
    if url.startswith("/"):
        url = "https://domclick.ru" + url
    meta = {
        "publishedDate": entry.get("publishedDate"),
        "soldDate": entry.get("soldDate"),
    }
    return Job(url=url, list_meta=meta)


def _job_from_api_item(item: dict[str, Any]) -> Optional[Job]:
    return _job_from_link_entry(
        {
            "path": item.get("path"),
            "publishedDate": item.get("publishedDate"),
            "soldDate": item.get("soldDate"),
        }
    )


def parse_cards(
    jobs: list[Job],
    workers: int,
    list_count: int,
    on_item: Optional[Callable[[dict[str, Any]], None]] = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    errors: list[tuple[str, str]] = []

    def work(job: Job) -> tuple[str, Optional[dict[str, Any]], Optional[str]]:
        code, body = retry_get(job.url, PAGE_HEADERS, cookie=PAGE_COOKIE)
        if code != 200:
            return job.url, None, f"HTTP {code}"
        try:
            text = body.decode("utf-8", errors="replace")
            row = parse_offer_html(text, job.list_meta, job.url)
            return job.url, row, None
        except Exception as e:  # noqa: BLE001
            return job.url, None, str(e)

    total_jobs = len(jobs)
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(work, j): j for j in jobs}
        for fut in as_completed(futs):
            url, row, err = fut.result()
            done += 1
            if done == 1 or done == total_jobs or done % 100 == 0:
                logger.info("Карточки: обработано %s/%s", done, total_jobs)
            if row:
                results.append(row)
                if on_item:
                    on_item(row)
            else:
                errors.append((url, err or "unknown"))

    results.sort(key=lambda r: (r.get("id") is None, r.get("id") or 0))

    out_obj = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "list_count": list_count,
        "parsed_ok": len(results),
        "errors": [{"url": u, "error": e} for u, e in errors],
        "items": results,
    }
    PATH_RESULT.write_text(json.dumps(out_obj, ensure_ascii=False, indent=2), encoding="utf-8")

    if errors:
        logger.warning("Не удалось разобрать %s страниц(ы)", len(errors))
    return results


def run_list() -> None:
    items = fetch_all_list_items()
    save_links_snapshot(items)
    logger.info("Список ссылок: %s шт. → %s", len(items), PATH_LINKS)


def run_cards(workers: int) -> None:
    entries = load_links_snapshot()
    jobs: list[Job] = []
    for e in entries:
        j = _job_from_link_entry(e)
        if j:
            jobs.append(j)
    parse_cards(jobs, workers=workers, list_count=len(entries))
    logger.info("Карточки → %s", PATH_RESULT)


def run_full(workers: int) -> None:
    items = fetch_all_list_items()
    save_links_snapshot(items)
    jobs: list[Job] = []
    for it in items:
        j = _job_from_api_item(it)
        if j:
            jobs.append(j)
    parse_cards(jobs, workers=workers, list_count=len(items))
    logger.info("Готово: %s и %s", PATH_LINKS, PATH_RESULT)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    p = argparse.ArgumentParser(
        description="Domclick: list — только ссылки; cards — только HTML; full — всё."
    )
    p.add_argument(
        "--mode",
        choices=("list", "cards", "full"),
        default="full",
        help="list: только API → domclick_links.json; cards: ссылки из файла → domclick_result.json; full: оба шага",
    )
    p.add_argument("--workers", type=int, default=24, help="Потоков для загрузки карточек (cards/full)")
    args = p.parse_args()

    if args.mode == "list":
        run_list()
    elif args.mode == "cards":
        run_cards(args.workers)
    else:
        run_full(args.workers)


if __name__ == "__main__":
    main()

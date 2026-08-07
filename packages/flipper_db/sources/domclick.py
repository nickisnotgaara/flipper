"""packages.flipper_db.sources.domclick — SourceParser implementation for Domclick.ru.

Sold-only источник (SourceParser.is_sold_source=True). Парсит
"проданные" объявления с domclick.ru через:

  1. ``fetch_ad_page(external_id)`` → GET на
     ``https://domclick.ru/card/sale__flat__{id}/`` с PAGE_COOKIE → HTML
     (None на 404 / network error).
  2. ``parse_ad(html)`` → ``AdRecord`` (raw_data = productCard.originalProduct).
  3. ``house_record_from_ad(ad)`` → ``HouseRecord`` из ad.raw_data.

Cookie (для обхода Qrator) — берётся из ``DOMCLICK_PAGE_COOKIE`` env
или из дефолтной константы PAGE_COOKIE. На проде cookie ротируется
вручную (как в существующем services/parsers/domclick_sold/acquirer.py).

Источник данных:
  - BFF API (https://bff-search-web.domclick.ru/api/offers/sold/v1) — для
    списка (отдельно, через acquirer.py → domclick_links.json)
  - HTML-страница карточки /card/sale__flat__<id>/ — содержит
    ``window.__SSR_STATE__`` с ``productCard.originalProduct`` +
    JSON-LD ``schema.org/GeoCoordinates`` (lat/lng).

Поля из SSR ``productCard.originalProduct``:
  - object_info.{area, rooms, floor, renovation.display_name, isApartment}
  - house.{floors, build_year, wall_type.display_name, ceiling_height}
  - address.{display_name, subways[], parents[]}
  - price_info.{price, square_price, price_history[], sold_price}
  - photos[]
  - published_dt, updated_dt, description, soldDate

Поля, которых НЕТ в domclick (корректно None): kitchen_area, living_area.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import re
from typing import Any, Optional

import httpx

from ..parser_types import AdRecord, HouseRecord

log = logging.getLogger("flipper_db.sources.domclick")


# ---------------------------------------------------------------------------
# URL templates & defaults
# ---------------------------------------------------------------------------

# Base URL домклик карточки "проданной" квартиры.
DOMCLICK_AD_URL = "https://domclick.ru/card/sale__flat__"


def get_page_cookie() -> str:
    """Читает PAGE_COOKIE из env DOMCLICK_PAGE_COOKIE.

    На проде cookie ротируется вручную; выносим в env для удобства.
    Если env пуст — используем дефолтное значение из acquirer.py.
    """
    env = os.getenv("DOMCLICK_PAGE_COOKIE", "").strip()
    if env:
        return env
    # Fallback: константа из acquirer.py (можно обновить там).
    return _DEFAULT_PAGE_COOKIE


# ВНИМАНИЕ: эта константа — копия из services/parsers/domclick_sold/acquirer.py.
# На проде предпочтительно подставлять через env DOMCLICK_PAGE_COOKIE.
# Если env задан, эта константа игнорируется (см. get_page_cookie()).
_DEFAULT_PAGE_COOKIE = (
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


DEFAULT_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
        "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "ru,en;q=0.9",
    "Cache-Control": "max-age=0",
    "Referer": "https://domclick.ru/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
    ),
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


# ---------------------------------------------------------------------------
# Tiny type-coercion helpers
# ---------------------------------------------------------------------------


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _to_float(value: Any) -> Optional[float]:
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


def _parse_iso_date_or_none(value: Any) -> Optional[datetime.date]:
    """Парсит ISO date / datetime строку → ``datetime.date`` для колонок
    ``sold_ads.publish_date`` / ``sold_ads.sold_date`` (DATE)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime.date):
        return value
    if not isinstance(value, str):
        return None
    s = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt.date()


# ---------------------------------------------------------------------------
# SSR JSON extraction (reuse logic from services/parsers/domclick_sold/acquirer.py)
# ---------------------------------------------------------------------------


_SSR_STATE_MARKER = "window.__SSR_STATE__"
_SSR_CONTEXT_MARKER = "window.__SSR_CONTEXT__"

# Численные значения в JS, которые ломают json.loads (NaN, Infinity, undefined)
_JS_LITERAL_NULL_REPLACEMENTS = (
    (re.compile(r"\bundefined\b"), "null"),
    (re.compile(r"\bNaN\b"), "null"),
    (re.compile(r"\bInfinity\b"), "null"),
    (re.compile(r"-Infinity"), "null"),
)


def extract_ssr_state_json(html: str) -> dict[str, Any]:
    """Извлекает ``window.__SSR_STATE__ = {...}`` из HTML-страницы domclick.

    Возвращает распарсенный dict или поднимает ValueError, если маркер не найден.
    """
    if _SSR_STATE_MARKER not in html or _SSR_CONTEXT_MARKER not in html:
        raise ValueError("window.__SSR_STATE__ not found in HTML")
    chunk = html.split(_SSR_CONTEXT_MARKER, 1)[0]
    _, rest = chunk.split(_SSR_STATE_MARKER, 1)
    rest = rest.split("=", 1)[1].strip()
    if rest.endswith(";"):
        rest = rest[:-1].strip()
    for pat, repl in _JS_LITERAL_NULL_REPLACEMENTS:
        rest = pat.sub(repl, rest)
    return json.loads(rest)


# ---------------------------------------------------------------------------
# JSON-LD GeoCoordinates (lat/lng)
# ---------------------------------------------------------------------------

# schema.org/GeoCoordinates — обычно встречается в <script type="application/ld+json">.
# Пример: '"latitude": 55.512048,\n"longitude": 37.573683'
_GEOCOORD_LAT_RE = re.compile(r'"latitude"\s*:\s*([+-]?\d+(?:\.\d+)?)')
_GEOCOORD_LNG_RE = re.compile(r'"longitude"\s*:\s*([+-]?\d+(?:\.\d+)?)')


def _extract_lat_lng_from_jsonld(html: str) -> tuple[Optional[float], Optional[float]]:
    """Достаёт (lat, lng) из schema.org/GeoCoordinates (JSON-LD).

    Если JSON-LD не найден или поля битые → (None, None).
    """
    lat_m = _GEOCOORD_LAT_RE.search(html)
    lng_m = _GEOCOORD_LNG_RE.search(html)
    if not lat_m or not lng_m:
        return None, None
    try:
        lat = float(lat_m.group(1))
        lng = float(lng_m.group(1))
        # Разумные границы для Москвы (lat 55-56, lng 37-38)
        # Не валим — domclick теоретически может быть для других регионов,
        # но вернём None если значения подозрительные.
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            return None, None
        return lat, lng
    except (ValueError, TypeError):
        return None, None


# ---------------------------------------------------------------------------
# Address helpers (parents, district, okrug, metro)
# ---------------------------------------------------------------------------


def _first_subway(address: dict[str, Any]) -> dict[str, Any]:
    """Возвращает первое метро из address.subways[]. Иначе пустой dict."""
    subs = address.get("subways") or []
    return subs[0] if subs else {}


def _extract_parent_by_kind(address: dict[str, Any], kind: str) -> Optional[str]:
    """Ищет в address.parents[] элемент с kind=<kind>, возвращает name."""
    parents = address.get("parents") or []
    for p in parents:
        if isinstance(p, dict) and p.get("kind") == kind:
            n = p.get("name")
            if n:
                return str(n)
    return None


def _extract_okrug(address: dict[str, Any]) -> Optional[str]:
    """Ищет в address.parents[] элемент, где name содержит 'округ' (case-insensitive)."""
    parents = address.get("parents") or []
    for p in parents:
        if isinstance(p, dict):
            n = str(p.get("name") or "")
            if "округ" in n.lower():
                return n
    return None


def _extract_renovation(object_info: dict[str, Any]) -> Optional[str]:
    """Достаёт human-readable renovation из object_info.renovation.

    object_info.renovation может быть:
      - dict с display_name (основной случай)
      - str (на всякий случай)
      - None
    """
    ren = object_info.get("renovation")
    if isinstance(ren, dict):
        n = ren.get("display_name") or ren.get("displayName") or ren.get("name")
        return str(n) if n else None
    if isinstance(ren, str) and ren:
        return ren
    return None


# ---------------------------------------------------------------------------
# SourceParser implementation
# ---------------------------------------------------------------------------


class DomclickSource:
    """SourceParser для domclick.ru (sold-only).

    Attributes (per ``SourceParser`` protocol):
      - ``source_name = "domclick_sold"``
      - ``source_label = "ДомКлик"``
      - ``has_house_pages = False`` — отдельных страниц домов на domclick
        нет; всё есть в productCard.originalProduct.house
      - ``is_sold_source = True`` — domclick_sold парсит ТОЛЬКО проданные
        объявления (BFF API параметр deal_type=sold_sale). Pipeline пишет
        сразу в ``sold_ads``, минуя ``active_ads`` и stale cleanup.
    """

    source_name: str = "domclick_sold"
    source_label: str = "ДомКлик"
    has_house_pages: bool = False
    is_sold_source: bool = True

    def __init__(
        self,
        page_cookie: Optional[str] = None,
        *,
        max_concurrent: int = 8,
        timeout: float = 30.0,
    ) -> None:
        self._cookie = page_cookie if page_cookie is not None else get_page_cookie()
        self._sem = asyncio.Semaphore(max_concurrent)
        self._timeout = timeout
        # Метрики для отладки долгих прогонов
        self.fetch_total = 0
        self.fetch_404s = 0
        self.fetch_other_errors = 0
        self.parse_failures = 0

    # ---- URL builders ----------------------------------------------------

    def ad_url(self, external_id: str) -> str:
        return f"{DOMCLICK_AD_URL}{external_id}/"

    def house_url(self, external_house_id: str) -> str:
        # Не используется (has_house_pages=False), но оставлено для совместимости
        return self.ad_url(external_house_id)

    @staticmethod
    def _extract_title_from_html(html: str) -> Optional[str]:
        """Extract short offer title from <h1 id="title"> in domclick HTML.
        Falls back to og:title. Returns None if neither found.
        """
        import re
        m = re.search(
            r'<h1[^>]*id=["\\\']title["\\\'][^>]*>(.*?)</h1>',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            inner = re.sub(r"<[^>]+>", " ", m.group(1))
            inner = re.sub(r"\s+", " ", inner).strip()
            if inner:
                return inner
        m = re.search(
            r'<meta\s+property=["\\\']og:title["\\\']\s+content=["\\\']([^"\\\']+)',
            html,
            re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()
        return None

    # ---- HTTP fetch ------------------------------------------------------

    async def fetch_ad_page(self, external_id: str) -> Optional[str]:
        """GET https://domclick.ru/card/sale__flat__{id}/ → HTML-строка, или None.

        Семантика для pipeline: ``None`` ⇔ ad больше не существует
        (domclick вернул 404) или network-ошибка. Pipeline тогда вызовет
        ``_deactivate_ad`` (если ad был активен в БД). Для sold-источника
        этот путь пропускается (см. pipeline.is_sold_source ветка).
        """
        url = self.ad_url(external_id)
        headers = dict(DEFAULT_HEADERS)
        headers["Cookie"] = self._cookie

        async with self._sem:
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    r = await client.get(url, headers=headers, follow_redirects=True)
            except httpx.HTTPError as exc:
                log.warning("domclick GET %s failed: %s", external_id, exc)
                self.fetch_other_errors += 1
                return None

        self.fetch_total += 1
        if r.status_code == 404:
            self.fetch_404s += 1
            log.info("domclick 404 for ad %s", external_id)
            return None
        if r.status_code != 200:
            self.fetch_other_errors += 1
            log.warning(
                "domclick HTTP %s for ad %s: %s",
                r.status_code, external_id, r.text[:200],
            )
            return None

        return r.text

    # ---- parse_ad --------------------------------------------------------

    def parse_ad(self, html: str) -> Optional[AdRecord]:
        """HTML от fetch_ad_page → AdRecord.

        ``raw_data`` = полный ``productCard.originalProduct`` + ``pc.href``
        + ``jsonld_lat``/``jsonld_lng`` (для observability).

        Возвращает None, если HTML не парсится или в нём нет originalProduct.
        """
        if not html:
            return None
        try:
            ssr = extract_ssr_state_json(html)
        except (ValueError, json.JSONDecodeError) as exc:
            log.warning("parse_ad: SSR_STATE parse failed: %s", exc)
            self.parse_failures += 1
            return None

        pc = ssr.get("productCard") or {}
        orig = pc.get("originalProduct") or {}
        if not orig or not orig.get("id"):
            log.warning("parse_ad: productCard.originalProduct missing or empty")
            self.parse_failures += 1
            return None

        oi = orig.get("object_info") or {}
        house = orig.get("house") or {}
        price_info = orig.get("price_info") or {}
        addr = orig.get("address") or {}
        sub = _first_subway(addr)

        # lat/lng из JSON-LD (schema.org/GeoCoordinates)
        lat, lng = _extract_lat_lng_from_jsonld(html)

        # Floors
        floor_current = _to_int(oi.get("floor"))
        floor_total = _to_int(house.get("floors"))

        # Photos
        photos = orig.get("photos") or []
        photo_urls = [p.get("url") for p in photos if isinstance(p, dict) and p.get("url")]

        # external_house_id: domclick не разделяет house id и offer id.
        # Используем тот же id — каждое объявление = один "дом" с точки зрения domclick.
        oid = str(orig["id"])
        href = (pc.get("href") or self.ad_url(oid)).replace("\\u002F", "/")

        # Title: extract from <h1 id="title"> in HTML (fallback to og:title).
        # This gives the standard cian-style "73,3 м², 3-комн., 11/16 этаж" line.
        title = self._extract_title_from_html(html)

        # Сырой JSON-блок для raw_data (с проглатыванием URL encoding)
        raw_block = {
            "originalProduct": orig,
            "pc_href": pc.get("href"),
            "jsonld_lat": lat,
            "jsonld_lng": lng,
            "photo_urls": photo_urls,
            "title": title,  # храним и здесь, чтобы /api отдавал title в JSON
        }

        return AdRecord(
            external_id=oid,
            external_house_id=oid,  # domclick: offer id == house surrogate
            cian_house_id=None,  # domclick не даёт cian_house_id
            url=href,
            is_active=False,  # domclick_sold = всегда sold
            raw_data=raw_block,
            price=_to_int(price_info.get("price")),
            price_per_m2=_to_int(price_info.get("square_price")),
            area=_to_float(oi.get("area")),
            rooms=_to_int(oi.get("rooms")),
            floor_current=floor_current,
            floor_total=floor_total,
            address=addr.get("display_name") or addr.get("short_display_name"),
            lat=lat,
            lng=lng,
            publish_date=orig.get("published_dt"),  # ISO str → parse в pipeline
            metro_station=sub.get("display_name") or sub.get("name"),
            metro_walk_time=_to_int((sub.get("remoteness") or {}).get("time")),
            district=_extract_parent_by_kind(addr, "district"),
            okrug=_extract_okrug(addr),
            renovation=_extract_renovation(oi),
        )

    # ---- HouseRecord -----------------------------------------------------

    def house_record_from_ad(
        self, ad: AdRecord, html: str = ""
    ) -> Optional[HouseRecord]:
        """Строит HouseRecord из уже-распарсенного ``ad.raw_data``.

        Не делает дополнительных fetch'ей — всё есть внутри
        ``originalProduct`` (house + address). Это основная оптимизация.

        street/house_num парсятся из address.display_name (через
        linker.extract_street_house) для dedup в linker'е.
        """
        if not ad.raw_data:
            return None
        orig = ad.raw_data.get("originalProduct")
        if not isinstance(orig, dict):
            return None
        house = orig.get("house") or {}
        if not house:
            return None

        addr = orig.get("address") or {}
        full_address = ad.address or addr.get("display_name")

        # Парсим (street, house_num) из address.display_name для dedup
        # (использует ту же нормализацию, что и flatinfo: drop суффиксов 'улица'/'шоссе'/etc)
        from ..linker import extract_street_house
        street_norm, house_num_norm = extract_street_house(full_address or "")

        # wall_type.display_name → building_type
        wall = house.get("wall_type")
        building_type = None
        if isinstance(wall, dict):
            building_type = wall.get("display_name") or wall.get("displayName")
        elif isinstance(wall, str):
            building_type = wall

        return HouseRecord(
            external_house_id=ad.external_house_id or ad.external_id,
            address=full_address,
            street=street_norm or None,
            house_num=house_num_norm or None,
            district=ad.district,
            okrug=ad.okrug,
            lat=ad.lat,
            lng=ad.lng,
            year_built=_to_int(house.get("build_year")),
            levels=floor_total_from(house),
            building_type=building_type,
            series=None,  # domclick не выдаёт series
            ceiling_height=_to_float(house.get("ceiling_height")),
            raw_data={
                "house": house,
                "address": addr,
            },
        )

    # ---- Не используется (has_house_pages=False) ------------------------

    async def fetch_house_page(
        self, external_house_id: str
    ) -> Optional[str]:
        """Не используется (has_house_pages=False), но требуется Protocol."""
        return None

    def parse_house(self, html: str) -> Optional[HouseRecord]:
        """Не используется."""
        return None


def floor_total_from(house: dict[str, Any]) -> Optional[int]:
    """Helper: достать total floors из house dict."""
    return _to_int(house.get("floors"))

"""packages.flipper_db.sources.cian — SourceParser implementation for Cian.

Flippercrawl-driven fetcher (v2 архитектура, Phase 3).

**Единственный путь получения данных циана** — POST на flippercrawl
``/v2/cian/scrape``. flippercrawl сам ходит в cian.ru (cookie rotation,
proxy, anti-bot), делает гибридный static extract + LLM-fallback, и
возвращает ``data.json`` (parsed fields) + ``data.rawHtml`` (полный HTML
с ``_cianConfig['frontend-offer-card']`` → ``state.offerData``) +
``data.json.rawOfferData`` (полный ``state.offerData`` при успешном
static extract; при LLM-fallback отсутствует).

**Отсюда CianSource делает:**
  1. ``fetch_ad_page(ext_id)`` → POST /v2/cian/scrape → JSON-строка (None на 404)
  2. ``parse_ad(json_text)`` → ``AdRecord`` (raw_data = полный offerData)
  3. ``house_record_from_ad(ad)`` → ``HouseRecord`` из ``offer.building`` +
     ``offer.bti`` + ``offer.geo`` (без отдельного fetch на /house/{id}/)

**Никакого прямого HTTP в cian.ru** — cookie/proxy/rate-limit всё в flippercrawl.
Никакого ``scripts/cian_fetch.py`` / ``scripts/cian_parse.py`` (после
успешного 500-чанка — удаляются).

**Multi-source ready:** этот source реализует ``SourceParser`` Protocol из
``parser_types``. Подключение к pipeline / repository / linker — без правок.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import Any, Optional

import httpx

from ..cian_state import extract_offer_data
from ..linker import extract_address_from_offer
from ..parser_types import AdRecord, HouseRecord

log = logging.getLogger("flipper_db.sources.cian")


# ---------------------------------------------------------------------------
# URL templates & defaults
# ---------------------------------------------------------------------------

# flippercrawl запущен в docker-compose на хосте; из flipper-api (тоже в
# compose или локально) — http://127.0.0.1:3002. Если когда-нибудь
# завернём flipper-api в ту же сеть — поменять на http://api:3002.
DEFAULT_FLIPPERCRAWL_URL = "http://127.0.0.1:3002/v2/cian/scrape"

DEFAULT_TIMEOUT = 30.0  # секунд; flippercrawl обычно отвечает за 3-8 сек,
# но LLM-fallback с self-heal может затянуться до 20-30 сек.

# Прямой endpoint cian API (НЕ через flippercrawl). Публичный, не требует
# авторизации. Возвращает ВСЕ объявления на доме (активные + снятые) с
# status, dateStart, dateEnd, prices. Используется для точного stale cleanup
# (Phase 3.5) и для backfill снятых ads без перепарсинга offer-страниц.
DEFAULT_CIAN_HOUSE_HISTORY_URL = (
    "https://api.cian.ru/valuation-offer-history/v4/get-house-offer-history-desktop/"
)
DEFAULT_CIAN_BROWSER_HEADERS = {
    "accept": "*/*",
    "accept-language": "en,ru;q=0.9,en-US;q=0.8,uz;q=0.7",
    "content-type": "application/json",
    "origin": "https://www.cian.ru",
    "referer": "https://www.cian.ru/",
    "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
    ),
}


# ---------------------------------------------------------------------------
# Tiny type-coercion helpers
# ---------------------------------------------------------------------------


def _to_float(value: Any) -> Optional[float]:
    """cian отдаёт many-поля как строки ('72.7', '2.7'). Конвертим в float."""
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


def _parse_date_or_none(value: Any) -> Optional["datetime.date"]:
    """Парсит ISO date / datetime строку → ``datetime.date`` для колонки
    ``active_ads.publish_date`` (DATE). None на любой неудаче.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime.date):
        return value
    if not isinstance(value, str):
        return None
    # ``datetime.fromisoformat`` (Python 3.11+) понимает и "2026-06-01",
    # и "2026-06-01T11:56:18.11", и "Z"-суффикс.
    s = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt.date()


def _find_address_elem(
    address_arr: list, type_name: str
) -> Optional[dict]:
    """Ищет элемент в ``offer.geo.address[]`` по ``type`` ('street', 'house', ...)."""
    if not isinstance(address_arr, list):
        return None
    for elem in address_arr:
        if isinstance(elem, dict) and elem.get("type") == type_name:
            return elem
    return None


# cian house history endpoint отдаёт даты в human-readable виде,
# напр. "10 апр 2026", "3 июн 2026", "вчера, 18:02". Парсим их в date.
_RU_MONTHS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "мая": 5,
    "июн": 6, "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}


def _parse_cian_human_date(value: Any) -> Optional[str]:
    """Парсит cian-формат "10 апр 2026" / "вчера, 18:02" в ISO date string.

    Возвращает ``"YYYY-MM-DD"`` или ``None`` если не удаётся распарсить
    (напр. "сегодня", "вчера" без года — пропускаем как None, можно
    потом разрулить по dateStart, но для sold_date нам нужен абсолютный
    день).
    """
    if not value or not isinstance(value, str):
        return None
    # Нормализуем whitespace и NBSP
    s = value.replace("\u00a0", " ").strip()
    # Убираем время после запятой: "вчера, 18:02" → "вчера"
    s = s.split(",", 1)[0].strip()
    if not s:
        return None
    # "10 апр 2026"
    parts = s.split()
    if len(parts) == 3:
        try:
            day = int(parts[0])
            month = _RU_MONTHS.get(parts[1].lower()[:3])
            year = int(parts[2])
            if month and 1 <= day <= 31 and 2000 <= year <= 2100:
                return datetime.date(year, month, day).isoformat()
        except (ValueError, KeyError):
            return None
    # "сегодня" / "вчера" / "3 дня назад" — без года. Вернём None.
    return None


def _parse_exposition_days(value: Any) -> Optional[int]:
    """Парсит "55 дней" / "123 дня" / "77 дней" в int."""
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    parts = s.split()
    if not parts:
        return None
    try:
        return int(parts[0])
    except ValueError:
        return None



# ---------------------------------------------------------------------------
# SourceParser implementation
# ---------------------------------------------------------------------------


class CianSource:
    """SourceParser для cian.ru через flippercrawl.

    Attributes (per ``SourceParser`` protocol):
      - ``source_name = "cian_active"``
      - ``source_label = "ЦИАН"``
      - ``has_house_pages = False`` — flippercrawl не ходит на cian
        ``/house/{id}/`` страницы; всё есть в ``offer.building`` внутри
        ``offerData``. Это упрощает и ускоряет pipeline: -1 fetch на ad.
      - ``is_sold_source = False`` — cian_active парсит АКТИВНЫЕ объявления;
        pipeline пишет в ``active_ads`` и только при stale cleanup
        (active→inactive transition) перемещает в ``sold_ads``.
    """

    source_name: str = "cian_active"
    source_label: str = "ЦИАН"
    has_house_pages: bool = False
    is_sold_source: bool = False

    def __init__(
        self,
        flippercrawl_url: Optional[str] = None,
        *,
        max_concurrent: int = 8,
        timeout: float = DEFAULT_TIMEOUT,
        api_key: Optional[str] = None,
    ) -> None:
        self._url = flippercrawl_url or DEFAULT_FLIPPERCRAWL_URL
        self._sem = asyncio.Semaphore(max_concurrent)
        self._timeout = timeout
        self._api_key = api_key
        # Метрики для отладки долгих прогонов
        self.fetch_total = 0
        self.fetch_static_hits = 0
        self.fetch_llm_fallbacks = 0
        self.fetch_404s = 0

    # ---- URL builders ----------------------------------------------------

    def ad_url(self, external_id: str) -> str:
        return f"https://www.cian.ru/sale/flat/{external_id}/"

    def house_url(self, external_house_id: str) -> str:
        # Не используется (has_house_pages=False), но оставлено для совместимости
        return f"https://www.cian.ru/house/{external_house_id}/"

    # ---- HTTP fetch ------------------------------------------------------

    async def fetch_ad_page(self, external_id: str) -> Optional[str]:
        """POST /v2/cian/scrape → JSON-строка всего response, или None на 404.

        Семантика для pipeline: ``None`` ⇔ ad больше не существует
        (cian вернул 404) или network-ошибка. Pipeline тогда вызовет
        ``_deactivate_ad`` если ad был активен в БД.
        """
        url = self._url
        payload = {"url": self.ad_url(external_id)}
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with self._sem:
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    r = await client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                log.warning("flippercrawl POST %s failed: %s", external_id, exc)
                return None

        self.fetch_total += 1
        if r.status_code == 404:
            self.fetch_404s += 1
            log.info("flippercrawl 404 for ad %s (de-listed on cian)", external_id)
            return None
        if r.status_code != 200:
            log.warning(
                "flippercrawl HTTP %s for ad %s: %s",
                r.status_code, external_id, r.text[:200],
            )
            return None

        return r.text

    # ---- cian.ru direct API (NOT via flippercrawl) ----------------------

    async def fetch_house_offer_history(
        self, cian_house_id: int, *, results_per_page: int = 100
    ) -> Optional[dict[str, Any]]:
        """POST /valuation-offer-history/v4/get-house-offer-history-desktop/

        Прямой вызов cian.ru (НЕ через flippercrawl — этот endpoint
        публичный, не требует anti-bot/cookie/proxy). Возвращает все
        объявления на доме (активные + снятые) с их status, dateStart,
        dateEnd, price, title.

        Это **source-of-truth** для точного stale cleanup: если наш
        active_ads.cian_house_id=X больше нет в response или имеет
        ``status: "deactivated"`` → снимаем.

        Возвращает:
            dict с полями:
                - totalCount: int
                - statusCounts: [{status, offersCount}]
                - offers: [{id, title, prices, exposition, status,
                            dateStart, dateEnd, previewPhoto}, ...]
        или None на network/parse error.

        Endpoint не имеет официальной пагинации в общем виде (page=1..N),
        но ``resultsOnPage`` контролирует размер. По умолчанию 100 — для
        большинства домов этого достаточно.
        """
        url = DEFAULT_CIAN_HOUSE_HISTORY_URL
        payload = {
            "houseId": int(cian_house_id),
            "resultsOnPage": int(results_per_page),
            "page": 1,
        }

        async with self._sem:
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout,
                    headers=DEFAULT_CIAN_BROWSER_HEADERS,
                ) as client:
                    r = await client.post(url, json=payload)
            except httpx.HTTPError as exc:
                log.warning(
                    "cian house history POST houseId=%s failed: %s",
                    cian_house_id, exc,
                )
                return None

        if r.status_code != 200:
            log.warning(
                "cian house history HTTP %s for houseId=%s: %s",
                r.status_code, cian_house_id, r.text[:200],
            )
            return None

        try:
            data = json.loads(r.text)
        except (ValueError, TypeError) as exc:
            log.warning("cian house history invalid JSON: %s", exc)
            return None

        if not isinstance(data, dict):
            return None
        if "offers" not in data or not isinstance(data.get("offers"), list):
            log.warning(
                "cian house history unexpected shape (no 'offers' list): %s",
                list(data.keys()),
            )
            return None
        return data

    @staticmethod
    def parse_house_history_offer(raw: dict[str, Any]) -> dict[str, Any]:
        """Нормализует один offer из cian house history в стандартный dict.

        Возвращает:
            {
              "external_id": str,        # cian_id (offer id)
              "title": str,
              "status": "published" | "deactivated" | "other...",
              "date_start": Optional[str],  # ISO "YYYY-MM-DD" если парсится
              "date_end": Optional[str],    # ISO "YYYY-MM-DD" или None
              "price_text": str,            # как есть, напр. "38,0 млн ₽"
              "price_per_m2_text": str,
            }
        """
        status = raw.get("status") or "unknown"
        prices = raw.get("prices") or {}
        return {
            "external_id": str(raw.get("id")) if raw.get("id") is not None else "",
            "title": str(raw.get("title") or ""),
            "status": status,
            "date_start": _parse_cian_human_date(raw.get("dateStart")),
            "date_end": _parse_cian_human_date(raw.get("dateEnd")),
            "price_text": str(prices.get("price") or ""),
            "price_per_m2_text": str(prices.get("priceSqm") or ""),
            "exposition_days": _parse_exposition_days(raw.get("exposition")),
        }

        return r.text

    # ---- parse_ad -------------------------------------------------------

    def parse_ad(self, response_json: str) -> Optional[AdRecord]:
        """JSON-строка от flippercrawl → AdRecord.

        ``raw_data`` = полный ``state.offerData``:
            - из ``data.json.rawOfferData`` (static extract, основной путь)
            - fallback: парсим ``data.rawHtml`` через ``cian_state.extract_offer_data``
              (когда flippercrawl ушёл в LLM-fallback и ``rawOfferData`` нет)
        """
        if not response_json:
            return None
        try:
            response = json.loads(response_json)
        except (ValueError, TypeError) as exc:
            log.warning("parse_ad: invalid JSON: %s", exc)
            return None

        data = response.get("data") if isinstance(response, dict) else None
        if not isinstance(data, dict):
            return None

        json_block = data.get("json") or {}
        if not isinstance(json_block, dict):
            json_block = {}
        raw_html = data.get("rawHtml") or ""

        # 1) primary: data.json.rawOfferData (static extract, hot path)
        raw_offer = json_block.get("rawOfferData")
        extraction_mode = json_block.get("_extraction_mode") or (
            "static" if raw_offer else "unknown"
        )
        if not raw_offer and raw_html:
            # 2) fallback: парсим rawHtml сами (LLM-fallback случай)
            raw_offer = extract_offer_data(raw_html)
            if raw_offer:
                extraction_mode = "llm"

        if extraction_mode == "static":
            self.fetch_static_hits += 1
        elif extraction_mode == "llm":
            self.fetch_llm_fallbacks += 1

        if not raw_offer or not isinstance(raw_offer, dict):
            log.warning(
                "parse_ad: no offerData in response (mode=%s, html_len=%d)",
                extraction_mode, len(raw_html),
            )
            return None

        offer = raw_offer.get("offer") or {}
        if not isinstance(offer, dict) or not offer.get("id"):
            log.warning("parse_ad: offer.id missing in rawOfferData")
            return None

        geo = offer.get("geo") or {}
        address_arr = geo.get("address") or []
        house_elem = _find_address_elem(address_arr, "house")
        street_elem = _find_address_elem(address_arr, "street")
        coords = geo.get("coordinates") or {}
        building = offer.get("building") or {}
        bargain = offer.get("bargainTerms") or {}
        bti = offer.get("bti") or {}
        bti_house = bti.get("houseData") or {}

        # Дополнительно пробрасываем _extraction_mode в raw_data для observability
        # (он приходит от flippercrawl, не из cian).
        if "_extraction_mode" not in raw_offer:
            raw_offer["_extraction_mode"] = extraction_mode

        return AdRecord(
            external_id=str(offer["id"]),
            external_house_id=str(house_elem["id"]) if house_elem else None,
            cian_house_id=int(house_elem["id"]) if house_elem and house_elem.get("id") else None,
            url=self.ad_url(offer["id"]),
            # is_active приходит от flippercrawl static extract:
            # status==="published" && !flags.isArchived
            is_active=bool(json_block.get("is_active", True)),
            raw_data=raw_offer,
            price=_to_int(bargain.get("price")) or _to_int(offer.get("priceTotal")),
            price_per_m2=_to_int(
                (offer.get("priceInfo") or {}).get("pricePerSquareValue")
            ) or _to_int(json_block.get("price_per_m2")),
            area=_to_float(offer.get("totalArea")) or _to_float(json_block.get("area")),
            rooms=_to_int(offer.get("roomsCount")) or _to_int(json_block.get("rooms")),
            floor_current=_to_int(offer.get("floorNumber"))
            or _to_int(json_block.get("floor_info", {}).get("current")),
            floor_total=_to_int(building.get("floorsCount"))
            or _to_int(json_block.get("floor_info", {}).get("all")),
            address=extract_address_from_offer(raw_offer)
            or json_block.get("address", {}).get("full")
            or _build_full_address(address_arr),
            lat=_to_float(coords.get("lat")) or _to_float(json_block.get("lat")),
            lng=_to_float(coords.get("lng")) or _to_float(json_block.get("lng")),
            publish_date=_parse_date_or_none(
                offer.get("creationDate") or json_block.get("publish_date")
            ),
            metro_station=json_block.get("address", {}).get("metro_station"),
            metro_walk_time=_to_int(json_block.get("metro_walk_time")),
            district=json_block.get("address", {}).get("district"),
            okrug=json_block.get("address", {}).get("okrug"),
            renovation=json_block.get("renovation"),
        )

    # ---- HouseRecord из offer.building + bti ---------------------------

    def house_record_from_ad(
        self, ad: AdRecord, html: str = ""
    ) -> Optional[HouseRecord]:
        """Строит HouseRecord из уже-распарсенного ``ad.raw_data``.

        Не делает дополнительных fetch'ей — flippercrawl не использует
        ``/house/{id}/`` страницы, всё есть внутри ``offerData``. Это
        основная оптимизация vs старой версии CianSource (которая ходила
        на /house/{id}/ отдельно).
        """
        if not ad.raw_data:
            return None
        offer = ad.raw_data.get("offer") or {}
        geo = offer.get("geo") or {}
        address_arr = geo.get("address") or []
        house_elem = _find_address_elem(address_arr, "house")
        if house_elem is None or not ad.external_house_id:
            return None

        building = offer.get("building") or {}
        bti = offer.get("bti") or {}
        bti_house = bti.get("houseData") or {}
        street_elem = _find_address_elem(address_arr, "street")

        return HouseRecord(
            external_house_id=ad.external_house_id,
            address=ad.address or _build_full_address(address_arr),
            street=(street_elem or {}).get("name"),
            house_num=(house_elem or {}).get("name"),
            district=ad.district,
            okrug=ad.okrug,
            lat=ad.lat,
            lng=ad.lng,
            year_built=_to_int(building.get("buildYear"))
            or _to_int(bti_house.get("yearRelease")),
            levels=_to_int(building.get("floorsCount"))
            or _to_int(bti_house.get("floorMax")),
            building_type=_material_type_to_human(building.get("materialType"))
            or bti_house.get("houseMaterialType"),
            series=building.get("series") or bti_house.get("seriesName"),
            ceiling_height=_to_float(building.get("ceilingHeight")),
            raw_data={
                "building": building,
                "bti": bti,
                "geo": geo,
            },
        )

    # ---- Не нужно -------------------------------------------------------

    async def fetch_house_page(
        self, external_house_id: str
    ) -> Optional[str]:
        """Не используется (has_house_pages=False), но требуется Protocol."""
        return None

    def parse_house(self, html: str) -> Optional[HouseRecord]:
        """Не используется."""
        return None


# ---------------------------------------------------------------------------
# Helpers (внутренние)
# ---------------------------------------------------------------------------


def _build_full_address(address_arr: list) -> Optional[str]:
    """Собирает строку адреса из ``offer.geo.address[]``.

    Пример: ``["Москва", "ЮАО", "р-н Чертаново Южное", "Варшавское ш.", "145К1"]``
    → ``"Москва, ЮАО, р-н Чертаново Южное, Варшавское ш., 145К1"``.
    """
    if not isinstance(address_arr, list) or not address_arr:
        return None
    parts: list[str] = []
    for elem in address_arr:
        if isinstance(elem, dict):
            name = elem.get("name")
            if name:
                parts.append(str(name))
    return ", ".join(parts) if parts else None


def _material_type_to_human(value: Optional[str]) -> Optional[str]:
    """Маппинг cian materialType → русский (как в старом cian_parse.py)."""
    if not value:
        return None
    mapping = {
        "monolith": "Монолитный",
        "panel": "Панельный",
        "brick": "Кирпичный",
        "block": "Блочный",
        "monolithBrick": "Монолитно-кирпичный",
        "stalin": "Сталинский",
        "wood": "Деревянный",
        "aerocreteBlock": "Газобетонный блок",
        "foamConcreteBlock": "Пенобетонный блок",
        "gasSilicateBlock": "Газосиликатный блок",
        "boards": "Щитовой",
        "old": "Старый фонд",
    }
    return mapping.get(value, value)

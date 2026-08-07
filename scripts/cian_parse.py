"""
cian_parse — pure parsers for cian offer HTML pages.

Extracts the embedded `offerData` JSON (cian is a SSR app: it embeds
the full offer state in an inline <script> as
    window._cianConfig['frontend-offer-card'] = (...||[]).concat([{...}, ...]);
where one entry is {key: "defaultState", value: {offerData: {...}}}).

Everything here is a pure function: HTML string -> typed dataclass, or None.
No I/O, no DB, no network. Trivially testable.

Public API:
    parse_offer(html) -> Optional[OfferRecord]
    parse_house_page(html) -> Optional[HouseRecord]
    OfferRecord, HouseRecord, BuildingRecord  (frozen dataclasses)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional


# ---- the SSR marker that cian embeds in the offer page ----
_MARKER = "_cianConfig['frontend-offer-card']"


# ---------- low-level JSON extraction ----------

def _scan_balanced_array(text: str, open_bracket: int) -> Optional[str]:
    """Return the JSON array text starting at open_bracket (which must be '['),
    correctly skipping string contents (including escaped chars).
    Returns None if no matching close bracket is found.
    """
    if open_bracket >= len(text) or text[open_bracket] != "[":
        return None
    depth = 0
    in_str = False
    i = open_bracket
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                return text[open_bracket:i + 1]
        i += 1
    return None


def _extract_offer_data(html: str) -> Optional[dict]:
    """Find defaultState.value.offerData in cian HTML. Returns the offerData dict or None."""
    if not html:
        return None
    search_from = 0
    while True:
        m = html.find(_MARKER, search_from)
        if m < 0:
            return None
        search_from = m + len(_MARKER)
        concat = html.find("concat(", m)
        if concat < 0 or concat - m > 500:
            continue
        ob = html.find("[", concat)
        if ob < 0 or ob - concat > 20:
            continue
        arr_text = _scan_balanced_array(html, ob)
        if not arr_text:
            continue
        try:
            entries = json.loads(arr_text)
        except Exception:
            continue
        if not isinstance(entries, list):
            continue
        for e in entries:
            if (
                isinstance(e, dict)
                and e.get("key") == "defaultState"
                and isinstance(e.get("value"), dict)
            ):
                od = e["value"].get("offerData")
                if isinstance(od, dict):
                    return od
    return None


def _extract_state_default(html: str) -> Optional[dict]:
    """Same as _extract_offer_data but returns the whole defaultState.value dict.
    Useful for pages where offerData is not the only thing we want.
    """
    if not html:
        return None
    search_from = 0
    while True:
        m = html.find(_MARKER, search_from)
        if m < 0:
            return None
        search_from = m + len(_MARKER)
        concat = html.find("concat(", m)
        if concat < 0 or concat - m > 500:
            continue
        ob = html.find("[", concat)
        if ob < 0 or ob - concat > 20:
            continue
        arr_text = _scan_balanced_array(html, ob)
        if not arr_text:
            continue
        try:
            entries = json.loads(arr_text)
        except Exception:
            continue
        if not isinstance(entries, list):
            continue
        for e in entries:
            if (
                isinstance(e, dict)
                and e.get("key") == "defaultState"
                and isinstance(e.get("value"), dict)
            ):
                return e["value"]
    return None


# ---------- typed records ----------

@dataclass(frozen=True)
class BuildingRecord:
    year_built: Optional[int] = None
    levels: Optional[int] = None
    material: Optional[str] = None
    series: Optional[str] = None
    ceiling_height: Optional[float] = None
    parking: Optional[str] = None
    total_area: Optional[float] = None
    lifts_passenger: Optional[int] = None
    lifts_cargo: Optional[int] = None


@dataclass(frozen=True)
class OfferRecord:
    cian_id: int
    cian_house_id: Optional[int] = None
    full_address: Optional[str] = None
    street_name: Optional[str] = None
    house_num: Optional[str] = None
    district: Optional[str] = None
    okrug: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    price: Optional[int] = None
    price_per_m2: Optional[int] = None
    area: Optional[float] = None
    rooms: Optional[int] = None
    floor_current: Optional[int] = None
    floor_total: Optional[int] = None
    metro_station: Optional[str] = None
    metro_walk_time: Optional[int] = None
    renovation: Optional[str] = None
    publish_date: Optional[str] = None
    is_active: bool = True
    building: Optional[BuildingRecord] = None
    url: Optional[str] = None
    raw: dict = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class HouseRecord:
    """What a cian house page gives us. Currently the building data
    already comes from the offer HTML, so this is mainly a thin wrapper
    for future expansion (separate /house/{id}/ page)."""
    cian_house_id: int
    full_address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    building: Optional[BuildingRecord] = None
    url: Optional[str] = None
    raw: dict = field(default_factory=dict, repr=False, compare=False)


# ---------- safe extractors ----------

def _safe_get(d: Any, *keys: str, default=None) -> Any:
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def _as_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _as_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        return v.strip() or None
    return str(v).strip() or None


def _parse_building(b: Any) -> Optional[BuildingRecord]:
    if not isinstance(b, dict):
        return None
    material = _as_str(b.get("materialType")) or _as_str(b.get("houseMaterialType"))
    series = _as_str(b.get("series"))
    if series and isinstance(series, dict):
        # sometimes series is {id, name, ...}
        series = _as_str(series.get("name")) or _as_str(series.get("shortName"))
    parking = b.get("parking")
    if isinstance(parking, dict):
        parking = _as_str(parking.get("type")) or "yes"
    else:
        parking = _as_str(parking)
    return BuildingRecord(
        year_built=_as_int(b.get("buildYear")),
        levels=_as_int(b.get("floorsCount")),
        material=material,
        series=series,
        ceiling_height=_as_float(b.get("ceilingHeight")),
        parking=parking,
        total_area=_as_float(b.get("totalArea")),
        lifts_passenger=_as_int(b.get("passengerLiftsCount")),
        lifts_cargo=_as_int(b.get("cargoLiftsCount")),
    )


def _address_part(addr_list: Any, type_name: str) -> Optional[dict]:
    if not isinstance(addr_list, list):
        return None
    for a in addr_list:
        if isinstance(a, dict) and a.get("type") == type_name:
            return a
    return None


def _format_address(geo: dict) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Returns (full_address, street_name, house_num, district, okrug).
    full_address is "City, district, street, house" style if available.
    """
    if not isinstance(geo, dict):
        return None, None, None, None, None
    addr = geo.get("address", [])
    if not isinstance(addr, list):
        return None, None, None, None, None
    loc = _address_part(addr, "location")
    okrug = _address_part(addr, "okrug")
    raion = _address_part(addr, "raion")
    street = _address_part(addr, "street")
    house = _address_part(addr, "house")

    parts = []
    for x in (loc, okrug, raion, street, house):
        if x:
            n = x.get("fullName") or x.get("name")
            if n:
                parts.append(str(n))

    full = ", ".join(parts) if parts else None
    street_name = street.get("fullName") or street.get("name") if street else None
    house_num = house.get("fullName") or house.get("name") if house else None
    district = raion.get("fullName") or raion.get("name") if raion else None
    okrug_n = okrug.get("fullName") or okrug.get("name") if okrug else None
    return full, street_name, house_num, district, okrug_n


# ---------- public parsers ----------

_PRICE_NUM = re.compile(r"-?\d+")


def _parse_money(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        m = _PRICE_NUM.search(v.replace("\u00a0", " ").replace(" ", ""))
        if m:
            try:
                return int(m.group(0))
            except ValueError:
                return None
    if isinstance(v, dict):
        # some cian fields are {value, currency, ...}
        for k in ("value", "amount", "price", "RUR", "rur"):
            if k in v:
                got = _parse_money(v[k])
                if got is not None:
                    return got
    return None


def parse_offer(html: str) -> Optional[OfferRecord]:
    """Parse a cian offer page HTML (e.g. /sale/flat/12345/) into an OfferRecord.

    Returns None if no offerData could be extracted. The function never raises
    on malformed HTML — it logs nothing and returns None instead.
    """
    od = _extract_offer_data(html)
    if not od:
        return None
    offer = od.get("offer")
    if not isinstance(offer, dict):
        return None
    cid = _as_int(offer.get("id"))
    if cid is None:
        return None

    geo = offer.get("geo") if isinstance(offer.get("geo"), dict) else {}
    full, street, hnum, district, okrug = _format_address(geo)

    coords = geo.get("coordinates") if isinstance(geo.get("coordinates"), dict) else {}
    lat = _as_float(coords.get("lat"))
    lng = _as_float(coords.get("lng"))

    house = _address_part(geo.get("address", []), "house")
    cian_house_id = _as_int(house.get("id")) if isinstance(house, dict) else None

    price = _parse_money(_safe_get(offer, "bargainTerms", "prices", "rur"))
    if price is None:
        price = _parse_money(_safe_get(offer, "price", "rur")) or _parse_money(offer.get("price"))
    price_per_m2 = _as_int(_safe_get(offer, "pricePerSquareMeter"))
    if price_per_m2 is None:
        price_per_m2 = _as_int(_safe_get(offer, "price", "pricePerSquareMeter"))
    if price_per_m2 is None:
        price_per_m2 = _as_int(_safe_get(offer, "bargainTerms", "prices", "perMeter"))

    area = _as_float(_safe_get(offer, "totalArea"))
    rooms = _as_int(offer.get("roomsCount")) or _as_int(offer.get("rooms"))
    floor = _as_int(offer.get("floorNumber"))
    floors_total = _as_int(offer.get("floorsCount"))

    # metro
    metro_list = offer.get("undergrounds")
    metro_station: Optional[str] = None
    metro_walk: Optional[int] = None
    if isinstance(metro_list, list) and metro_list:
        m = metro_list[0] if isinstance(metro_list[0], dict) else None
        if m:
            metro_station = _as_str(m.get("name")) or _as_str(_safe_get(m, "metro", "name"))
            t = m.get("transportType") or m.get("type")
            if t == "walk" or t == 1:
                metro_walk = _as_int(m.get("time")) or _as_int(m.get("travelTime"))
            elif t == "transport" or t == 2:
                # convert transport to a rough walk equivalent
                tr_time = _as_int(m.get("travelTime"))
                if tr_time is not None:
                    metro_walk = tr_time + 5  # heuristic
            else:
                metro_walk = _as_int(m.get("time")) or _as_int(m.get("travelTime"))

    renovation = _as_str(_safe_get(offer, "repair", "name")) or _as_str(offer.get("renovation"))
    publish_date = _as_str(offer.get("publishDate")) or _as_str(_safe_get(offer, "publication", "publishDate"))

    building = _parse_building(offer.get("building"))

    url = None
    slug = offer.get("slug") or offer.get("cianId")
    if slug is not None:
        url = f"https://www.cian.ru/sale/flat/{int(slug)}/"

    return OfferRecord(
        cian_id=cid,
        cian_house_id=cian_house_id,
        full_address=full,
        street_name=street,
        house_num=hnum,
        district=district,
        okrug=okrug,
        lat=lat,
        lng=lng,
        price=price,
        price_per_m2=price_per_m2,
        area=area,
        rooms=rooms,
        floor_current=floor,
        floor_total=floors_total,
        metro_station=metro_station,
        metro_walk_time=metro_walk,
        renovation=renovation,
        publish_date=publish_date,
        is_active=True,
        building=building,
        url=url,
        raw=od,
    )


def parse_house_page(html: str) -> Optional[HouseRecord]:
    """Parse a cian house page HTML (e.g. /house/{id}/) into a HouseRecord.
    Currently a thin wrapper — the offer HTML already has the building
    data we need. This is the hook for future expansion.
    """
    state = _extract_state_default(html)
    if state is None:
        return None
    od = state.get("offerData") if isinstance(state.get("offerData"), dict) else None
    if not od:
        return None
    offer = od.get("offer") if isinstance(od.get("offer"), dict) else {}
    geo = offer.get("geo") if isinstance(offer.get("geo"), dict) else {}
    full, _, _, _, _ = _format_address(geo)
    coords = geo.get("coordinates") if isinstance(geo.get("coordinates"), dict) else {}
    house = _address_part(geo.get("address", []), "house")
    hid = _as_int(house.get("id")) if isinstance(house, dict) else None
    if hid is None:
        return None
    return HouseRecord(
        cian_house_id=hid,
        full_address=full,
        lat=_as_float(coords.get("lat")),
        lng=_as_float(coords.get("lng")),
        building=_parse_building(offer.get("building")),
        url=f"https://www.cian.ru/house/{hid}/" if hid else None,
        raw=state,
    )

"""Unit-тесты для DomclickSource (SourceParser Protocol implementation).

Покрывает:
  - Атрибуты класса (source_name, source_label, has_house_pages, is_sold_source)
  - URL builders
  - parse_ad на реальном fixture
  - house_record_from_ad
  - Helpers (extract_ssr_state_json, lat/lng, address, renovation, okrug)
  - Edge cases: пустой HTML, битый JSON

Fixture: services/parsers/domclick_sold/offer-page.html (offer id=2069491413,
Москва, Новомосковский АО, 1-комн, 52 м², 12 690 000 ₽, sold).
"""
from __future__ import annotations

import json
import pathlib

import pytest

from packages.flipper_db.sources.domclick import (
    DomclickSource,
    _extract_lat_lng_from_jsonld,
    _extract_okrug,
    _extract_parent_by_kind,
    _extract_renovation,
    _first_subway,
    extract_ssr_state_json,
)


FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def domclick_html() -> str:
    p = FIXTURES / "domclick-offer.html"
    if not p.is_file():
        pytest.skip(f"fixture not found: {p}")
    return p.read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def domclick_source() -> DomclickSource:
    return DomclickSource()


# ---------------------------------------------------------------------------
# SourceParser-атрибуты
# ---------------------------------------------------------------------------


def test_domclick_source_attributes(domclick_source: DomclickSource) -> None:
    """Все SourceParser-атрибуты установлены корректно."""
    assert domclick_source.source_name == "domclick_sold"
    assert domclick_source.source_label == "ДомКлик"
    assert domclick_source.has_house_pages is False
    # Critical: domclick_sold — sold-only источник
    assert domclick_source.is_sold_source is True


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------


def test_ad_url(domclick_source: DomclickSource) -> None:
    assert domclick_source.ad_url("2069491413") == "https://domclick.ru/card/sale__flat__2069491413/"
    assert domclick_source.ad_url("1") == "https://domclick.ru/card/sale__flat__1/"


def test_house_url(domclick_source: DomclickSource) -> None:
    """house_url оставлен для совместимости, но не используется."""
    assert domclick_source.house_url("123") == "https://domclick.ru/card/sale__flat__123/"


# ---------------------------------------------------------------------------
# extract_ssr_state_json helper
# ---------------------------------------------------------------------------


def test_extract_ssr_state_json_happy_path(domclick_html: str) -> None:
    ssr = extract_ssr_state_json(domclick_html)
    assert isinstance(ssr, dict)
    assert "productCard" in ssr


def test_extract_ssr_state_json_missing_marker() -> None:
    with pytest.raises(ValueError, match="not found"):
        extract_ssr_state_json("<html><body>no marker here</body></html>")


def test_extract_ssr_state_json_garbage() -> None:
    with pytest.raises((ValueError, json.JSONDecodeError)):
        extract_ssr_state_json("window.__SSR_STATE__ = {not valid json}")


# ---------------------------------------------------------------------------
# lat/lng из JSON-LD
# ---------------------------------------------------------------------------


def test_extract_lat_lng_from_real_html(domclick_html: str) -> None:
    """lat/lng берётся из schema.org/GeoCoordinates (JSON-LD)."""
    lat, lng = _extract_lat_lng_from_jsonld(domclick_html)
    assert lat is not None and lng is not None
    # Координаты из fixture: 55.512048, 37.573683 (Южное Бутово)
    assert 55.0 <= lat <= 56.0
    assert 37.0 <= lng <= 38.0


def test_extract_lat_lng_no_jsonld() -> None:
    assert _extract_lat_lng_from_jsonld("<html>no lat here</html>") == (None, None)
    assert _extract_lat_lng_from_jsonld("") == (None, None)


def test_extract_lat_lng_out_of_range() -> None:
    html = '"latitude": 999.0, "longitude": 999.0'
    assert _extract_lat_lng_from_jsonld(html) == (None, None)


# ---------------------------------------------------------------------------
# parse_ad — happy path (на реальном fixture)
# ---------------------------------------------------------------------------


def test_parse_ad_returns_record(domclick_html: str, domclick_source: DomclickSource) -> None:
    ad = domclick_source.parse_ad(domclick_html)
    assert ad is not None
    assert ad.external_id == "2069491413"
    assert ad.external_house_id == "2069491413"
    assert ad.cian_house_id is None  # domclick не даёт cian_house_id
    assert ad.is_active is False  # sold-only


def test_parse_ad_normalized_fields(domclick_html: str, domclick_source: DomclickSource) -> None:
    ad = domclick_source.parse_ad(domclick_html)
    assert ad is not None
    assert ad.price == 12_690_000
    assert ad.area == 52.0
    assert ad.rooms == 1
    assert ad.floor_current == 13
    assert ad.floor_total == 15
    assert ad.lat is not None
    assert abs(ad.lat - 55.512048) < 0.001
    assert abs(ad.lng - 37.573683) < 0.001


def test_parse_ad_address(domclick_html: str, domclick_source: DomclickSource) -> None:
    ad = domclick_source.parse_ad(domclick_html)
    assert ad is not None
    assert ad.address is not None
    # Адрес должен содержать "Москва" и "15/1"
    assert "Москва" in ad.address or "москва" in ad.address.lower()
    assert "15/1" in ad.address


def test_parse_ad_district_okrug(domclick_html: str, domclick_source: DomclickSource) -> None:
    ad = domclick_source.parse_ad(domclick_html)
    assert ad is not None
    # district и okrug непустые (значения зависят от fixture)
    assert ad.district is not None
    assert len(ad.district) > 0
    assert ad.okrug is not None
    assert len(ad.okrug) > 0
    # okrug должен содержать "округ" (case-insensitive)
    assert "округ" in ad.okrug.lower()


def test_parse_ad_renovation(domclick_html: str, domclick_source: DomclickSource) -> None:
    ad = domclick_source.parse_ad(domclick_html)
    assert ad is not None
    assert ad.renovation is not None
    # В fixture: "Без отделки" (или подобное)
    assert isinstance(ad.renovation, str)
    assert len(ad.renovation) > 0


def test_parse_ad_raw_data_preserves_price_history(domclick_html: str, domclick_source: DomclickSource) -> None:
    """raw_data.price_history — критичное поле, должно сохраниться."""
    ad = domclick_source.parse_ad(domclick_html)
    assert ad is not None
    op = ad.raw_data.get("originalProduct", {})
    price_info = op.get("price_info", {})
    history = price_info.get("price_history")
    assert history is not None
    assert isinstance(history, list)
    assert len(history) > 0
    # Каждая запись — dict с date/price/diff/state
    first = history[0]
    assert "date" in first
    assert "price" in first


def test_parse_ad_raw_data_preserves_photos(domclick_html: str, domclick_source: DomclickSource) -> None:
    ad = domclick_source.parse_ad(domclick_html)
    assert ad is not None
    photos = ad.raw_data.get("photo_urls", [])
    assert isinstance(photos, list)
    assert len(photos) > 0
    assert all(isinstance(p, str) for p in photos)
    # Проверим, что URL похож на domclick (содержит /vitrina/ или /owner/)
    assert any("/vitrina/" in p or "/owner/" in p for p in photos)


def test_parse_ad_jsonld_in_raw_data(domclick_html: str, domclick_source: DomclickSource) -> None:
    ad = domclick_source.parse_ad(domclick_html)
    assert ad is not None
    # jsonld_lat/jsonld_lng прокидываются в raw_data для observability
    assert ad.raw_data.get("jsonld_lat") is not None
    assert ad.raw_data.get("jsonld_lng") is not None


# ---------------------------------------------------------------------------
# parse_ad — edge cases
# ---------------------------------------------------------------------------


def test_parse_ad_empty_html(domclick_source: DomclickSource) -> None:
    assert domclick_source.parse_ad("") is None


def test_parse_ad_no_marker(domclick_source: DomclickSource) -> None:
    assert domclick_source.parse_ad("<html>no marker</html>") is None


def test_parse_ad_malformed_json(domclick_source: DomclickSource) -> None:
    html = (
        "window.__SSR_STATE__ = {not valid json};\n"
        "window.__SSR_CONTEXT__ = {};"
    )
    assert domclick_source.parse_ad(html) is None


def test_parse_ad_no_originalProduct(domclick_source: DomclickSource) -> None:
    html = (
        'window.__SSR_STATE__ = {"productCard": {"_id": "1", "originalProduct": null}};\n'
        "window.__SSR_CONTEXT__ = {};"
    )
    assert domclick_source.parse_ad(html) is None


def test_parse_ad_js_literals_in_json(domclick_source: DomclickSource) -> None:
    """NaN/Infinity/undefined → null (наш preprocess)."""
    html = (
        'window.__SSR_STATE__ = {"productCard": {"originalProduct": '
        '{"id": 123, "x": NaN, "y": undefined, "z": Infinity}}};\n'
        "window.__SSR_CONTEXT__ = {};"
    )
    # Не падаем, NaN/undefined/Infinity заменяются на null
    ad = domclick_source.parse_ad(html)
    assert ad is not None
    assert ad.external_id == "123"


# ---------------------------------------------------------------------------
# house_record_from_ad
# ---------------------------------------------------------------------------


def test_house_record_from_ad(domclick_html: str, domclick_source: DomclickSource) -> None:
    ad = domclick_source.parse_ad(domclick_html)
    assert ad is not None
    hr = domclick_source.house_record_from_ad(ad)
    assert hr is not None
    assert hr.external_house_id == "2069491413"
    assert hr.year_built == 2011
    assert hr.levels == 15
    assert hr.building_type is not None
    assert hr.lat is not None
    assert hr.lng is not None


def test_house_record_from_ad_no_raw_data(domclick_source: DomclickSource) -> None:
    from packages.flipper_db.parser_types import AdRecord
    empty = AdRecord(external_id="1", raw_data={})
    assert domclick_source.house_record_from_ad(empty) is None


# ---------------------------------------------------------------------------
# Не используемые (но требуются Protocol)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_house_page_returns_none(domclick_source: DomclickSource) -> None:
    assert await domclick_source.fetch_house_page("123") is None


def test_parse_house_returns_none(domclick_source: DomclickSource) -> None:
    assert domclick_source.parse_house("<html></html>") is None


# ---------------------------------------------------------------------------
# Helpers (unit tests)
# ---------------------------------------------------------------------------


def test_first_subway_empty() -> None:
    assert _first_subway({}) == {}
    assert _first_subway({"subways": []}) == {}
    assert _first_subway({"subways": None}) == {}


def test_first_subway_with_data() -> None:
    addr = {"subways": [{"name": "A"}, {"name": "B"}]}
    assert _first_subway(addr) == {"name": "A"}


def test_extract_parent_by_kind_found() -> None:
    addr = {"parents": [
        {"kind": "district", "name": "Тверской"},
        {"kind": "area", "name": "ЦАО"},
    ]}
    assert _extract_parent_by_kind(addr, "district") == "Тверской"
    assert _extract_parent_by_kind(addr, "area") == "ЦАО"


def test_extract_parent_by_kind_missing() -> None:
    assert _extract_parent_by_kind({}, "district") is None
    assert _extract_parent_by_kind({"parents": []}, "district") is None
    assert _extract_parent_by_kind({"parents": [{"kind": "other", "name": "x"}]}, "district") is None


def test_extract_okrug() -> None:
    addr = {"parents": [
        {"name": "Новомосковский административный округ"},
        {"name": "Тверской"},
    ]}
    assert _extract_okrug(addr) == "Новомосковский административный округ"
    assert _extract_okrug({"parents": [{"name": "Тверской"}]}) is None


def test_extract_renovation_dict() -> None:
    oi = {"renovation": {"display_name": "Без отделки"}}
    assert _extract_renovation(oi) == "Без отделки"


def test_extract_renovation_str() -> None:
    oi = {"renovation": "косметический"}
    assert _extract_renovation(oi) == "косметический"


def test_extract_renovation_none() -> None:
    assert _extract_renovation({}) is None
    assert _extract_renovation({"renovation": None}) is None
    assert _extract_renovation({"renovation": {}}) is None

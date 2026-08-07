"""Тесты для ``packages.flipper_db.cian_state``.

Покрывают:
  - Happy path: синтетический HTML с корректным concat([{key:"defaultState",value:{offerData:...}}])
  - Marker not found → None
  - Malformed JSON внутри marker → None
  - Empty raw_html → None
  - Несколько вхождений маркера (страница может содержать сериализованные копии)
  - Эскейпы внутри строк JSON не ломают сканер

Тесты синхронные, без БД. Синтетический HTML строится в helper-е, чтобы
не зависеть от 645KB-сэмпла.
"""
from __future__ import annotations

import json
import pytest

from packages.flipper_db.cian_state import extract_offer_data


def _make_cian_html(
    offer_data: dict,
    *,
    extra_garbage_before: str = "",
    extra_garbage_after: str = "",
) -> str:
    """Синтетический HTML карточки Cian с заданным ``offerData``.

    Структура повторяет реальную страницу (см. ``flippercrawl/cian-flat.html``):
        <html>
          <head>…<script>…concat([{key:"defaultState",value:{offerData:…}}, …])…</script></head>
          …
        </html>
    """
    state = {"offerData": offer_data, "anotherTopLevelKey": "x"}
    default_state_entry = {"key": "defaultState", "value": state}
    other_entry = {"key": "user", "value": {"id": 42}}
    entries_json = json.dumps(
        [default_state_entry, other_entry], ensure_ascii=False
    )
    # Эмулируем window._cianConfig['frontend-offer-card'] = (...).concat([...])
    return (
        f"{extra_garbage_before}"
        f"<html><head><script>"
        f"window._cianConfig['frontend-offer-card'] = (function(){{return [];}}).concat({entries_json});"
        f"</script></head><body>{extra_garbage_after}</body></html>"
    )


# --- Happy path -----------------------------------------------------------


def test_extract_offer_data_happy_path():
    """Корректный HTML → dict с offer, agent, photos, priceChanges."""
    offer_data = {
        "offer": {
            "id": 330637131,
            "cianId": 330637131,
            "status": "published",
            "title": "3к.квартира в 2 мин от м. Аннино",
            "totalArea": "72.7",
            "roomsCount": 3,
            "floorNumber": 13,
            "bargainTerms": {"price": 22590000, "currency": "rur"},
            "building": {
                "materialType": "panel",
                "floorsCount": 16,
                "buildYear": 1978,
                "ceilingHeight": "2.7",
                "series": "П-3/16",
            },
            "geo": {
                "coordinates": {"lat": 55.580482, "lng": 37.598061},
                "address": [
                    {"type": "location", "name": "Москва"},
                    {"type": "okrug", "name": "ЮАО"},
                    {"type": "street", "name": "Варшавское"},
                    {"type": "house", "id": 35703, "name": "145К1"},
                ],
            },
        },
        "agent": {
            "id": 140408468,
            "name": "Юлия Полуосьмак",
            "companyName": "CENTURY 21 Столичная недвижимость",
        },
        "priceChanges": [
            {"changeTime": "2026-07-04T09:15:06Z", "priceData": {"price": 22590000}}
        ],
        "_extraction_note": "синтетический сэмпл для теста",
    }

    html = _make_cian_html(offer_data, extra_garbage_before="<!DOCTYPE html>")
    result = extract_offer_data(html)

    assert result is not None
    assert result["offer"]["id"] == 330637131
    assert result["offer"]["building"]["buildYear"] == 1978
    assert result["offer"]["geo"]["coordinates"]["lat"] == 55.580482
    assert result["agent"]["companyName"] == "CENTURY 21 Столичная недвижимость"
    assert len(result["priceChanges"]) == 1
    # Гарантия: возвращаем именно ``offerData`` (не ``state`` и не ``entries``)
    assert "offerData" not in result  # т.к. это и есть offerData
    assert "offer" in result
    # defaultState.value.anotherTopLevelKey не должен попасть в result
    assert "anotherTopLevelKey" not in result


# --- Edge cases -----------------------------------------------------------


def test_extract_offer_data_empty_html():
    """Пустая строка → None."""
    assert extract_offer_data("") is None


def test_extract_offer_data_no_marker():
    """HTML без маркера _cianConfig → None."""
    html = "<html><body>Just a regular page, no cian config here.</body></html>"
    assert extract_offer_data(html) is None


def test_extract_offer_data_malformed_json_after_marker():
    """Маркер есть, но JSON битый → None (не raise)."""
    bad_html = (
        "<html><head><script>"
        "window._cianConfig['frontend-offer-card'] = (function(){{return [];}}).concat("
        "{not valid json at all]})"
        "</script></head></html>"
    )
    assert extract_offer_data(bad_html) is None


def test_extract_offer_data_marker_but_no_default_state():
    """Маркер есть, concat есть, JSON валидный, но нет ``defaultState`` → None."""
    entries_json = json.dumps([{"key": "user", "value": {"id": 1}}])
    html = (
        f"<html><head><script>"
        f"window._cianConfig['frontend-offer-card'] = (function(){{return [];}}).concat({entries_json});"
        f"</script></head></html>"
    )
    assert extract_offer_data(html) is None


def test_extract_offer_data_default_state_without_offer_data():
    """``defaultState`` есть, но ``offerData`` отсутствует → None."""
    entries_json = json.dumps([
        {"key": "defaultState", "value": {"other": "stuff"}},
    ])
    html = (
        f"<html><head><script>"
        f"window._cianConfig['frontend-offer-card'] = (function(){{return [];}}).concat({entries_json});"
        f"</script></head></html>"
    )
    assert extract_offer_data(html) is None


# --- Robustness -----------------------------------------------------------


def test_extract_offer_data_with_escaped_quotes_in_strings():
    """Строки с экранированными кавычками внутри JSON не ломают сканер баланса."""
    offer_data = {
        "offer": {
            "id": 1,
            "description": 'Квартира с "особенностями" и \\backslashes\\',
        }
    }
    html = _make_cian_html(offer_data)
    result = extract_offer_data(html)
    assert result is not None
    assert 'с "особенностями"' in result["offer"]["description"]


def test_extract_offer_data_picks_correct_marker_among_duplicates():
    """Если в HTML есть копия маркера без defaultState (например, в JSON-stringify
    внутри другого скрипта) — парсер должен найти правильный, а не первый."""
    real_offer = {"offer": {"id": 999, "status": "published"}}
    real_entries = json.dumps(
        [{"key": "defaultState", "value": {"offerData": real_offer}}]
    )
    # В начале: сериализованная копия, но это просто строка в скрипте,
    # не concat([...]).
    fake_marker = (
        "var cached = 'window._cianConfig[\\'frontend-offer-card\\'] = "
        "(...).concat([{key:\\'defaultState\\', value: {offerData: {stale: true}}}]);';"
    )
    html = (
        f"<html><head><script>{fake_marker}</script>"
        f"<script>"
        f"window._cianConfig['frontend-offer-card'] = (function(){{return [];}}).concat({real_entries});"
        f"</script></head></html>"
    )
    result = extract_offer_data(html)
    assert result is not None
    assert result["offer"]["id"] == 999
    assert "stale" not in result  # не должен взять первый фейк

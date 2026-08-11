"""Unit tests for parser normalization helpers."""

from __future__ import annotations

from services.parser_cian.parser import (
    AdParser,
    _parse_price_history_date_str,
    _sanitize_building_type,
)


def test_sanitize_building_type_rejects_series():
    assert _sanitize_building_type("П-44Т") == ""
    assert _sanitize_building_type("Индивидуальный проект") == ""
    assert _sanitize_building_type("Монолитный") == "Монолитный"


def test_parse_price_history_date_str_iso():
    assert _parse_price_history_date_str("2025-02-06").isoformat() == "2025-02-06"


def test_parse_price_history_date_str_russian():
    d = _parse_price_history_date_str("8 апр 2026")
    assert d is not None
    assert d.isoformat() == "2026-04-08"


def test_normalize_data_preserves_server_price_history():
    parser = AdParser(cookie_manager_url="http://cookie-manager.test")
    data = {
        "url": "https://www.cian.ru/sale/flat/1/",
        "cian_id": "1",
        "price": 1_000_000,
        "area": 40.0,
        "price_history": [
            {
                "date": "2025-01-01",
                "price": 900_000,
                "change_amount": 0,
                "change_type": "initial",
            },
            {
                "date": "2025-02-01",
                "price": 1_000_000,
                "change_amount": 100_000,
                "change_type": "increase",
            },
        ],
    }
    result = parser._normalize_data(data)
    ph = result["price_history"]
    assert len(ph) == 2
    assert ph[0]["date"] == "2025-01-01"
    assert ph[0]["change_type"] == "initial"
    assert ph[1]["date"] == "2025-02-01"
    assert ph[1]["change_amount"] == 100_000
    assert ph[1]["change_type"] == "increase"

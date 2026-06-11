"""Fixtures for parser_cian unit tests."""

from __future__ import annotations

import pytest

SAMPLE_URL = "https://www.cian.ru/sale/flat/313326812/"
SAMPLE_CIAN_ID = "313326812"
SAMPLE_COOKIE = "_CIAN_GK=test; session_region_id=1"


@pytest.fixture
def sample_firecrawl_json() -> dict:
    return {
        "cian_id": SAMPLE_CIAN_ID,
        "price": 9_405_000,
        "area": 51.5,
        "price_per_m2": 182_621,
        "title": "Продается квартира",
        "rooms": 2,
        "is_active": True,
        "has_avans_deposit": False,
        "address": {
            "full": "Москва, р-н Раменки",
            "district": "Раменки",
            "metro_station": "Ломоносовский проспект",
            "okrug": "ЗАО",
        },
        "floor_info": {"current": 9, "all": 12},
        "price_history": [
            {
                "date": "2025-02-06",
                "price": 8_850_000,
                "change_amount": 0,
                "change_type": "initial",
            },
            {
                "date": "2025-03-01",
                "price": 9_405_000,
                "change_amount": 555_000,
                "change_type": "increase",
            },
        ],
    }


@pytest.fixture
def sample_firecrawl_response(sample_firecrawl_json: dict) -> dict:
    creation_date = "2025-02-06"
    raw_html = (
        f'<html><body>"creationDate":"{creation_date}T10:00:00"</body></html>'
    )
    return {
        "success": True,
        "data": {
            "markdown": "# listing",
            "rawHtml": raw_html,
            "json": {
                **sample_firecrawl_json,
                "_extraction_mode": "static",
            },
        },
    }


@pytest.fixture
def sample_cian_stats_response() -> dict:
    return {
        "totalViews": "100 просмотров с 06.02.2025",
        "daily": {
            "totalViews": "100 просмотров",
            "dailyViews": [
                {"date": "2025-02-06", "views": 10},
                {"date": "2025-06-11", "views": 4},
            ],
        },
    }

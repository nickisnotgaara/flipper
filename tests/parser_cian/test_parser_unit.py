"""Unit tests for AdParser (/v2/cian/scrape integration)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from services.parser_cian.parser import AdParser
from tests.parser_cian.conftest import SAMPLE_COOKIE, SAMPLE_URL

COOKIE_MANAGER = "http://cookie-manager.test"
FIRECRAWL_BASE = "http://firecrawl.test"


def _make_parser() -> AdParser:
    return AdParser(
        cookie_manager_url=COOKIE_MANAGER,
        firecrawl_base_url=FIRECRAWL_BASE,
        firecrawl_api_key="test-key",
        cookies_cache_ttl_sec=3600.0,
    )


def _mock_cookies(route: respx.Route, cookies: list | None = None) -> None:
    payload = cookies if cookies is not None else [
        {"name": "_CIAN_GK", "value": "test"},
        {"name": "session_region_id", "value": "1"},
    ]
    route.respond(json=payload)


@respx.mock
def test_firecrawl_url_is_cian_scrape():
    parser = _make_parser()
    assert parser.firecrawl_api_url == "http://firecrawl.test/v2/cian/scrape"


@respx.mock
@pytest.mark.asyncio
async def test_payload_minimal(sample_firecrawl_response):
    _mock_cookies(respx.get(f"{COOKIE_MANAGER}/cookies"))

    captured: dict = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=sample_firecrawl_response)

    respx.post(f"{FIRECRAWL_BASE}/v2/cian/scrape").mock(side_effect=_capture)
    respx.get(url__regex=r"https://api\.cian\.ru/.*").respond(
        json={
            "totalViews": "10 просмотров с 06.02.2025",
            "daily": {"dailyViews": []},
        }
    )

    parser = _make_parser()
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await parser.parse_async(SAMPLE_URL)

    body = captured["body"]
    assert body["url"] == SAMPLE_URL
    assert "Cookie" in body["headers"]
    assert "excludeTags" not in body
    assert "formats" not in body


@respx.mock
@pytest.mark.asyncio
async def test_parse_success_static(sample_firecrawl_response):
    _mock_cookies(respx.get(f"{COOKIE_MANAGER}/cookies"))
    respx.post(f"{FIRECRAWL_BASE}/v2/cian/scrape").respond(
        json=sample_firecrawl_response
    )
    respx.get(url__regex=r"https://api\.cian\.ru/.*").respond(
        json={
            "totalViews": "100 просмотров с 06.02.2025",
            "daily": {
                "dailyViews": [
                    {"date": "2025-02-06", "views": 10},
                    {"date": "2025-06-11", "views": 4},
                ]
            },
        }
    )

    parser = _make_parser()
    with patch("asyncio.sleep", new_callable=AsyncMock):
        parsed = await parser.parse_async(SAMPLE_URL)

    assert parsed.cian_id == "313326812"
    assert parsed.price == 9_405_000
    assert parsed.area == 51.5
    assert parsed.publish_date == "2025-02-06"


@respx.mock
@pytest.mark.asyncio
async def test_parse_success_llm_fallback(sample_firecrawl_response):
    _mock_cookies(respx.get(f"{COOKIE_MANAGER}/cookies"))
    llm_response = sample_firecrawl_response.copy()
    llm_response["data"] = sample_firecrawl_response["data"].copy()
    llm_response["data"]["json"] = {
        **sample_firecrawl_response["data"]["json"],
        "_extraction_mode": "llm",
    }
    respx.post(f"{FIRECRAWL_BASE}/v2/cian/scrape").respond(json=llm_response)
    respx.get(url__regex=r"https://api\.cian\.ru/.*").respond(
        json={"daily": {"dailyViews": []}}
    )

    parser = _make_parser()
    with patch("asyncio.sleep", new_callable=AsyncMock):
        parsed = await parser.parse_async(SAMPLE_URL)

    assert parsed.cian_id == "313326812"
    assert parsed.price == 9_405_000


@respx.mock
@pytest.mark.asyncio
async def test_extraction_mode_logged(
    sample_firecrawl_response, caplog
):
    import logging

    caplog.set_level(logging.INFO)
    _mock_cookies(respx.get(f"{COOKIE_MANAGER}/cookies"))
    respx.post(f"{FIRECRAWL_BASE}/v2/cian/scrape").respond(
        json=sample_firecrawl_response
    )
    respx.get(url__regex=r"https://api\.cian\.ru/.*").respond(
        json={"daily": {"dailyViews": []}}
    )

    parser = _make_parser()
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await parser.parse_async(SAMPLE_URL)

    assert any(
        "extraction_mode=static" in r.message for r in caplog.records
    )


@respx.mock
@pytest.mark.asyncio
async def test_captcha_raises():
    _mock_cookies(respx.get(f"{COOKIE_MANAGER}/cookies"))
    respx.post(f"{FIRECRAWL_BASE}/v2/cian/scrape").respond(
        json={
            "success": True,
            "data": {
                "rawHtml": "<html><title>captcha</title></html>",
                "json": {"cian_id": "1", "price": 1, "area": 1},
            },
        }
    )

    parser = _make_parser()
    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(ValueError, match="captcha"):
            await parser.parse_async(SAMPLE_URL)


@respx.mock
@pytest.mark.asyncio
async def test_creation_date_triggers_stats(sample_firecrawl_response):
    _mock_cookies(respx.get(f"{COOKIE_MANAGER}/cookies"))
    respx.post(f"{FIRECRAWL_BASE}/v2/cian/scrape").respond(
        json=sample_firecrawl_response
    )
    stats_route = respx.get(url__regex=r"https://api\.cian\.ru/.*")
    stats_route.respond(
        json={
            "totalViews": "50 просмотров с 06.02.2025",
            "daily": {
                "dailyViews": [
                    {"date": "2025-02-06", "views": 5},
                    {"date": "2025-06-11", "views": 2},
                ]
            },
        }
    )

    parser = _make_parser()
    with patch("asyncio.sleep", new_callable=AsyncMock):
        parsed = await parser.parse_async(SAMPLE_URL)

    assert stats_route.call_count == 1
    assert parsed.total_views == 50
    assert parsed.unique_views == 2


@respx.mock
@pytest.mark.asyncio
async def test_retry_on_scrape_all_engines_failed(sample_firecrawl_response):
    _mock_cookies(respx.get(f"{COOKIE_MANAGER}/cookies"))
    route = respx.post(f"{FIRECRAWL_BASE}/v2/cian/scrape")
    route.side_effect = [
        httpx.Response(
            500,
            json={"success": False, "code": "SCRAPE_ALL_ENGINES_FAILED"},
        ),
        httpx.Response(200, json=sample_firecrawl_response),
    ]
    respx.get(url__regex=r"https://api\.cian\.ru/.*").respond(
        json={"daily": {"dailyViews": []}}
    )

    parser = _make_parser()
    with patch("asyncio.sleep", new_callable=AsyncMock):
        parsed = await parser.parse_async(SAMPLE_URL)

    assert route.call_count == 2
    assert parsed.cian_id == "313326812"


@respx.mock
@pytest.mark.asyncio
async def test_empty_cookies_raises():
    respx.get(f"{COOKIE_MANAGER}/cookies").respond(json=[])
    respx.post(f"{COOKIE_MANAGER}/check").respond(
        json={"valid": False}
    )

    parser = _make_parser()
    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(ValueError, match="Cookies are empty"):
            await parser.parse_async(SAMPLE_URL)

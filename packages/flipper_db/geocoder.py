"""packages.flipper_db.geocoder - геокодирование адресов через Nominatim / Photon.

Использование:
    from packages.flipper_db import init_engine
    from packages.flipper_db.geocoder import Geocoder, GeocoderConfig

    init_engine("postgresql+asyncpg://...")
    cfg = GeocoderConfig(provider="nominatim", rate_per_sec=1.0)
    gc = Geocoder(cfg)
    result = await gc.geocode("Москва, Арбат, 10")
    # result: GeocodeResult(lat=55.75..., lng=37.59..., provider="nominatim", confidence=0.8) | None
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Literal, Optional

import httpx

logger = logging.getLogger(__name__)


# BBOX Москвы: [min_lng, min_lat, max_lng, max_lat]
# Москва: 55.1422-56.0212 N, 36.8031-37.9678 E
MOSCOW_BBOX_LAT_MIN = 55.142
MOSCOW_BBOX_LAT_MAX = 56.022
MOSCOW_BBOX_LNG_MIN = 36.803
MOSCOW_BBOX_LNG_MAX = 37.968


@dataclass
class GeocodeResult:
    lat: float
    lng: float
    provider: str
    display_name: str = ""
    raw: dict | None = None


@dataclass
class GeocoderConfig:
    provider: Literal["nominatim", "photon"] = "nominatim"
    rate_per_sec: float = 1.0
    timeout: float = 15.0
    user_agent: str = "flipper/1.0 (geocoder; contact: dev@flipper.local)"
    viewbox: tuple[float, float, float, float] | None = None
    """(min_lng, min_lat, max_lng, max_lat) — ограничить результаты Москвой.
    Nominatim: viewbox=x1,y1,x2,y2 (lng,lat,lng,lat)."""
    country_codes: str = "ru"
    """ISO 3166-1 alpha2 — ограничить поиск страной (ru)."""
    max_retries: int = 3
    backoff_base: float = 2.0


class Geocoder:
    """Геокодер с rate-limiting и retry. Поддерживает Nominatim и Photon."""

    NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
    PHOTON_URL = "https://photon.komoot.io/api/"

    def __init__(self, cfg: GeocoderConfig | None = None) -> None:
        self.cfg = cfg or GeocoderConfig()
        self._lock = asyncio.Lock()
        self._last_request_ts: float = 0.0
        self._n_failed: int = 0
        self._n_success: int = 0
        self._n_total: int = 0

    @property
    def stats(self) -> dict:
        return {
            "total": self._n_total,
            "success": self._n_success,
            "failed": self._n_failed,
            "success_rate": (
                100.0 * self._n_success / self._n_total if self._n_total else 0.0
            ),
        }

    async def _throttle(self) -> None:
        """Гарантирует rate-limit между запросами."""
        if self.cfg.rate_per_sec <= 0:
            return
        interval = 1.0 / self.cfg.rate_per_sec
        async with self._lock:
            now = asyncio.get_event_loop().time()
            wait = self._last_request_ts + interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_ts = asyncio.get_event_loop().time()

    async def geocode(self, address: str) -> GeocodeResult | None:
        """Геокодировать один адрес. None если не нашли.

        Использует настроенный провайдер (nominatim или photon).
        """
        if not address or not address.strip():
            return None
        address = address.strip()

        self._n_total += 1

        if self.cfg.provider == "nominatim":
            result = await self._geocode_nominatim(address)
        elif self.cfg.provider == "photon":
            result = await self._geocode_photon(address)
        else:
            raise ValueError(f"Unknown provider: {self.cfg.provider}")

        if result:
            self._n_success += 1
        else:
            self._n_failed += 1
        return result

    async def _request_with_retry(
        self, method: str, url: str, **kwargs
    ) -> httpx.Response | None:
        """HTTP запрос с retry + exponential backoff."""
        last_exc: Exception | None = None
        for attempt in range(self.cfg.max_retries):
            try:
                await self._throttle()
                async with httpx.AsyncClient(
                    timeout=self.cfg.timeout,
                    headers={"User-Agent": self.cfg.user_agent},
                ) as client:
                    resp = await client.request(method, url, **kwargs)
                if resp.status_code == 200:
                    return resp
                if resp.status_code in (429, 503):
                    # rate-limited — back off
                    wait = self.cfg.backoff_base ** attempt + random.random()
                    logger.warning(
                        "%s: HTTP %s, retry in %.1fs", url, resp.status_code, wait
                    )
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code == 404:
                    return None  # not found
                # other errors
                logger.warning("%s: HTTP %s: %s", url, resp.status_code, resp.text[:200])
                return None
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                wait = self.cfg.backoff_base ** attempt + random.random()
                logger.warning(
                    "%s: %s, retry %d/%d in %.1fs",
                    url, exc, attempt + 1, self.cfg.max_retries, wait,
                )
                await asyncio.sleep(wait)
        if last_exc:
            logger.error("%s: failed after %d attempts: %s", url, self.cfg.max_retries, last_exc)
        return None

    async def _geocode_nominatim(self, address: str) -> GeocodeResult | None:
        params = {
            "q": address,
            "format": "json",
            "limit": 1,
            "addressdetails": 0,
            "countrycodes": self.cfg.country_codes,
        }
        if self.cfg.viewbox:
            params["viewbox"] = (
                f"{self.cfg.viewbox[0]},{self.cfg.viewbox[1]},"
                f"{self.cfg.viewbox[2]},{self.cfg.viewbox[3]}"
            )
            params["bounded"] = 1

        resp = await self._request_with_retry("GET", self.NOMINATIM_URL, params=params)
        if not resp:
            return None
        try:
            data = resp.json()
        except Exception:
            return None
        if not data:
            return None
        first = data[0]
        try:
            lat = float(first["lat"])
            lng = float(first["lon"])
        except (KeyError, ValueError, TypeError):
            return None
        return GeocodeResult(
            lat=lat,
            lng=lng,
            provider="nominatim",
            display_name=first.get("display_name", ""),
            raw=first,
        )

    async def _geocode_photon(self, address: str) -> GeocodeResult | None:
        # Photon supports: default, de, en, fr (no ru). Use default (English-ish) for RU.
        params = {
            "q": address,
            "limit": 1,
            "lang": "default",
        }
        if self.cfg.viewbox:
            # Photon: bbox=minLng,minLat,maxLng,maxLat
            params["bbox"] = ",".join(str(v) for v in self.cfg.viewbox)

        resp = await self._request_with_retry("GET", self.PHOTON_URL, params=params)
        if not resp:
            return None
        try:
            data = resp.json()
        except Exception:
            return None
        features = data.get("features") or []
        if not features:
            return None
        first = features[0]
        coords = first.get("geometry", {}).get("coordinates", [])
        if len(coords) < 2:
            return None
        # Photon: [lng, lat]
        lng, lat = float(coords[0]), float(coords[1])
        return GeocodeResult(
            lat=lat,
            lng=lng,
            provider="photon",
            display_name=first.get("properties", {}).get("name", ""),
            raw=first,
        )


def moscow_viewbox() -> tuple[float, float, float, float]:
    """BBox Москвы для Nominatim: (min_lng, min_lat, max_lng, max_lat)."""
    return (MOSCOW_BBOX_LNG_MIN, MOSCOW_BBOX_LAT_MIN, MOSCOW_BBOX_LNG_MAX, MOSCOW_BBOX_LAT_MAX)

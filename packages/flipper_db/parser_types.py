"""packages.flipper_db.parser_types — common types for all source parsers.

This module is the foundation of the v2 architecture: every source
parser (cian, domclick, winners, future) implements the
``SourceParser`` protocol and produces ``AdRecord`` / ``HouseRecord``
records that the generic pipeline (``flipper_db.pipeline``) consumes.

**Source-agnostic**. No cian-specific or domclick-specific fields.
Source-specific data lives in ``AdRecord.raw_data`` (the full source
JSON, e.g. ``offerData`` for cian) and is preserved as-is for debugging
or re-parsing.

Public API
----------
``AdRecord`` — standardized ad data (extracted fields + raw source JSON).
``HouseRecord`` — standardized house data.
``SourceParser`` — Protocol that all parsers implement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


# --- Common dataclasses ----------------------------------------------------


@dataclass
class AdRecord:
    """A single ad (currently active or deactivated) from any source.

    Normalized fields are extracted by the source-specific parser.
    ``raw_data`` carries the FULL source response (e.g. cian's
    ``offerData``, domclick's JSON, etc.) so we can re-parse later
    without re-fetching.
    """

    # Identification
    external_id: str  # source-specific natural key (cian_id, domclick_id, etc.)
    external_house_id: Optional[str] = None  # source-specific house key (for the source's own dedup)
    cian_house_id: Optional[int] = None  # cross-ref to cian's house id (when cian carries it)

    # Source signals
    url: Optional[str] = None
    is_active: bool = True  # False ⇔ the source itself says the ad is no longer live

    # Full source response (for debugging / re-parsing). MANDATORY.
    raw_data: dict = field(default_factory=dict)

    # Normalized fields (best-effort; parsers fill what they can)
    price: Optional[int] = None
    price_per_m2: Optional[int] = None
    area: Optional[float] = None
    rooms: Optional[int] = None
    floor_current: Optional[int] = None
    floor_total: Optional[int] = None
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    publish_date: Optional[str] = None  # ISO date string
    metro_station: Optional[str] = None
    metro_walk_time: Optional[int] = None
    district: Optional[str] = None
    okrug: Optional[str] = None
    renovation: Optional[str] = None
    days_in_exposition: Optional[int] = None


@dataclass
class HouseRecord:
    """A single physical building from any source.

    Like ``AdRecord``, normalized fields + full raw source JSON.
    """

    # Identification (source-specific)
    external_house_id: str

    # Address / geo
    address: Optional[str] = None
    street: Optional[str] = None
    house_num: Optional[str] = None
    district: Optional[str] = None
    okrug: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None

    # Building characteristics
    year_built: Optional[int] = None
    levels: Optional[int] = None
    building_type: Optional[str] = None
    series: Optional[str] = None
    ceiling_height: Optional[float] = None

    # Full source response (cian's houseData, etc.)
    raw_data: dict = field(default_factory=dict)


# --- Parser protocol -------------------------------------------------------


@runtime_checkable
class SourceParser(Protocol):
    """Common contract for all source parsers.

    Every source (cian, domclick, winners, future) implements this.
    The pipeline consumes ``AdRecord`` / ``HouseRecord`` and never
    touches source-specific code.

    Required attributes
    -------------------
    ``source_name`` : str
        Canonical source identifier used in ``houses.source`` and
        ``active_ads.source``. Examples: ``"cian_active"``,
        ``"cian_sold"``, ``"domclick_sold"``, ``"winners_sold"``.
    ``source_label`` : str
        Human-readable label for UI badges ("ЦИАН", "ДомКлик", "Победители").
    ``has_house_pages`` : bool
        True iff the source has a dedicated page per house (e.g. cian's
        ``/house/{id}/``). If False, ``fetch_house_page`` should return None.
    ``is_sold_source`` : bool
        True iff this source only produces SOLD/deactivated ads (never
        active). The pipeline then writes directly into ``sold_ads``,
        skipping ``active_ads`` and the active→sold stale-cleanup path.
        Default False (sources that may produce both active and sold ads,
        like cian_active). Examples: ``cian_sold``, ``domclick_sold``,
        ``winners_sold``.

    Required methods
    ----------------
    ``fetch_ad_page(external_id) -> str | None``
        Fetch raw HTML/JSON for an ad. Return None on 404 / network error.
    ``fetch_house_page(external_house_id) -> str | None``
        Fetch raw HTML/JSON for a house. Return None if not supported
        (i.e. ``has_house_pages is False``) or on error.
    ``parse_ad(html) -> AdRecord | None``
        Pure function: HTML/JSON → AdRecord. Never raises; returns None
        if the page can't be parsed.
    ``parse_house(html) -> HouseRecord | None``
        Pure function: HTML/JSON → HouseRecord. Same contract as ``parse_ad``.
    """

    source_name: str
    source_label: str
    has_house_pages: bool
    is_sold_source: bool

    async def fetch_ad_page(self, external_id: str) -> Optional[str]:
        ...

    async def fetch_house_page(self, external_house_id: str) -> Optional[str]:
        ...

    def parse_ad(self, html: str) -> Optional[AdRecord]:
        ...

    def parse_house(self, html: str) -> Optional[HouseRecord]:
        ...

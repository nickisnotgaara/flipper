"""flipper_db - Shared SQLAlchemy models & repository for all Flipper parsers.

Единая схема PostgreSQL, общая для всех парсеров (cian_active, cian_sold,
winners_sold, domclick_sold, flatinfo_houses). Подробнее — README.md.

Использование:
    from packages.flipper_db import (
        init_db, Base, House, ActiveAd, SoldAd, Source, FlipperRepository,
        link_ads, link_ads_by_cian_ids,
        AdRecord, HouseRecord, SourceParser,
        run_source_pipeline, CianSource,
    )
"""

from .base import (
    DEFAULT_DATABASE_URL,
    get_engine,
    get_session_factory,
    init_db,
    init_engine,
)
from .enums import Source
from .geocoder import GeocodeResult, Geocoder, GeocoderConfig, moscow_viewbox
from .linker import link_ads, link_ads_by_cian_ids
from .models import House, ActiveAd, SoldAd
from .parser_types import AdRecord, HouseRecord, SourceParser
from .pipeline import run_source_pipeline
from .repository import FlipperRepository
from .sources.cian import CianSource
from .sources.domclick import DomclickSource

__all__ = [
    "init_db",
    "init_engine",
    "get_engine",
    "get_session_factory",
    "DEFAULT_DATABASE_URL",
    "Base",
    "House",
    "ActiveAd",
    "SoldAd",
    "Source",
    "FlipperRepository",
    "Geocoder",
    "GeocoderConfig",
    "GeocodeResult",
    "moscow_viewbox",
    "link_ads",
    "link_ads_by_cian_ids",
    "AdRecord",
    "HouseRecord",
    "SourceParser",
    "run_source_pipeline",
    "CianSource",
    "DomclickSource",
]

"""Source — перечисление всех источников данных (парсеров)."""

from __future__ import annotations

from enum import Enum


class Source(str, Enum):
    """Источник данных в таблицах houses/active_ads/sold_ads.

    Должен совпадать с именем парсера в services/parsers/<source>/, но
    хранится как строка (для совместимости с JSONB и быстрых сравнений в SQL).

    Маппинг сервис ↔ source:
        services/parsers/cian_active/     → 'cian_active'
        services/parsers/cian_sold/       → 'cian_sold'
        services/parsers/winners_sold/    → 'winners_sold'
        services/parsers/domclick_sold/   → 'domclick_sold'
        services/parsers/flatinfo_houses/ → 'flatinfo_houses'
    """

    CIAN_ACTIVE = "cian_active"
    CIAN_SOLD = "cian_sold"
    WINNERS_SOLD = "winners_sold"
    DOMCLICK_SOLD = "domclick_sold"
    FLATINFO_HOUSES = "flatinfo_houses"

    @classmethod
    def all(cls) -> list[str]:
        """Все известные source-теги (для валидации, тестов)."""
        return [s.value for s in cls]

    @classmethod
    def has_active_ads(cls, source: str | "Source") -> bool:
        """True, если этот источник пишет в active_ads (сейчас только cian_active)."""
        s = source.value if isinstance(source, Source) else source
        return s == cls.CIAN_ACTIVE.value

    @classmethod
    def has_sold_ads(cls, source: str | "Source") -> bool:
        """True, если этот источник пишет в sold_ads (все кроме flatinfo_houses)."""
        s = source.value if isinstance(source, Source) else source
        return s != cls.FLATINFO_HOUSES.value

"""Тесты Source enum."""

import pytest

from packages.flipper_db import Source


def test_all_sources():
    """Все ожидаемые source-теги присутствуют."""
    expected = {
        "cian_active",
        "cian_sold",
        "winners_sold",
        "domclick_sold",
        "flatinfo_houses",
    }
    assert set(Source.all()) == expected


def test_source_values_are_strings():
    """Source — это str, можно сравнивать напрямую с колонкой БД."""
    assert Source.CIAN_ACTIVE == "cian_active"
    assert Source.WINNERS_SOLD.value == "winners_sold"
    # str-enum ведёт себя как строка
    assert Source.CIAN_SOLD + "_test" == "cian_sold_test"


def test_has_active_ads():
    """Только cian_active пишет в active_ads."""
    assert Source.has_active_ads(Source.CIAN_ACTIVE) is True
    assert Source.has_active_ads("cian_active") is True
    assert Source.has_active_ads(Source.CIAN_SOLD) is False
    assert Source.has_active_ads(Source.WINNERS_SOLD) is False
    assert Source.has_active_ads(Source.DOMCLICK_SOLD) is False
    assert Source.has_active_ads(Source.FLATINFO_HOUSES) is False


def test_has_sold_ads():
    """Все кроме flatinfo_houses пишут в sold_ads."""
    assert Source.has_sold_ads(Source.CIAN_ACTIVE) is True
    assert Source.has_sold_ads(Source.CIAN_SOLD) is True
    assert Source.has_sold_ads(Source.WINNERS_SOLD) is True
    assert Source.has_sold_ads(Source.DOMCLICK_SOLD) is True
    assert Source.has_sold_ads(Source.FLATINFO_HOUSES) is False


def test_source_is_iterable():
    """Можно итерироваться по enum."""
    sources = list(Source)
    assert len(sources) == 5
    assert Source.CIAN_ACTIVE in sources

"""Фикстуры для тестов cian_sold."""

import pytest_asyncio

# Импортируем общую фикстуру `repo` из flipper_db
from packages.flipper_db.tests.conftest import repo  # noqa: F401

__all__ = ["repo"]

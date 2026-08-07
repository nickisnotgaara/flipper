"""Engine, session, init_db() — общая инфраструктура PostgreSQL.

Парсеры вызывают:
    init_db(DATABASE_URL)            # один раз при старте
    FlipperRepository(DATABASE_URL)  # для upsert-операций
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://flipper:flipper_secret@app_postgres:5432/flipper"
)

# Глобальный engine + session factory (инициализируются через init_engine()).
_engine: AsyncEngine | None = None
_AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None
_engine_url: str | None = None


def get_database_url() -> str:
    """DATABASE_URL из окружения или дефолт."""
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def init_engine(database_url: str | None = None) -> AsyncEngine:
    """(Пере)инициализация engine + session factory.

    Идемпотентно: если engine уже инициализирован с тем же URL,
    переиспользует его. Это критично для:
      - тестов с SQLite in-memory: фикстура инициализирует engine,
        тест и run() не должны пересоздавать (иначе БД разная);
      - production: init_db() + FlipperRepository() с тем же URL.

    Если URL передан и engine уже с этим URL — переиспользуем.
    Если URL другой — пересоздаём.
    """
    global _engine, _AsyncSessionLocal, _engine_url
    url = database_url or get_database_url()

    # Идемпотентность по URL: если engine уже с этим URL, переиспользуем.
    if _engine is not None and _engine_url == url:
        return _engine

    # pool_size / max_overflow работают только для PostgreSQL/MySQL/etc.
    # SQLite (aiosqlite) использует StaticPool — эти kwargs недопустимы.
    is_sqlite = url.startswith("sqlite")
    engine_kwargs: dict = {"echo": False, "pool_pre_ping": True}
    if not is_sqlite:
        engine_kwargs["pool_size"] = 5
        engine_kwargs["max_overflow"] = 10

    _engine = create_async_engine(url, **engine_kwargs)
    _AsyncSessionLocal = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    _engine_url = url
    logger.info("DB engine initialized: %s", url.split("@")[-1])  # без пароля в лог
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        return init_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _AsyncSessionLocal is None:
        init_engine()
    assert _AsyncSessionLocal is not None
    return _AsyncSessionLocal


async def init_db(database_url: str | None = None) -> None:
    """Создаёт все таблицы (houses, active_ads, sold_ads) если их нет.

    Используется парсерами при старте. Идемпотентно.
    Если database_url не указан — использует уже инициализированный engine.
    """
    if database_url is not None:
        engine = init_engine(database_url)
    else:
        engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("DB tables ensured (houses, active_ads, sold_ads)")

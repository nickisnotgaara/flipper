"""SQLAlchemy models for the unified Flipper schema (houses, active_ads, sold_ads).

Схема спроектирована под будущую интерактивную карту 2gis-style: клик на
дом → окошко с активными и снятыми объявлениями. Дома нормализованы по
(source, external_house_id) + опционально cian_house_id для кросс-источниковой
сшивки.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import declarative_base, relationship

from .enums import Source

Base = declarative_base()

# Кросс-диалектный PK type: BIGINT в PostgreSQL, INTEGER в SQLite
# (SQLite rowid autoincrement работает только для INTEGER).
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")


class House(Base):
    """Единый реестр домов со всех источников.

    Идентификация: (source, external_house_id) — уникальна.
    Опционально: cian_house_id (BIGINT) — если известен, позволяет
    сшивать дома из разных источников на будущей карте.
    """

    __tablename__ = "houses"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    source = Column(String(64), nullable=False, index=True)
    external_house_id = Column(String(128), nullable=False)
    cian_house_id = Column(BigInteger, nullable=True)
    domclick_house_id = Column(BigInteger, nullable=True)
    winners_house_id = Column(String(128), nullable=True)

    address = Column(Text, nullable=True)
    street = Column(String(256), nullable=True)
    house_num = Column(String(32), nullable=True)
    district = Column(String(128), nullable=True)
    okrug = Column(String(128), nullable=True)

    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)

    year_built = Column(Integer, nullable=True)
    levels = Column(Integer, nullable=True)
    building_type = Column(String(64), nullable=True)
    series = Column(String(128), nullable=True)
    ceiling_height = Column(Float, nullable=True)

    # Классификация (для фильтрации на будущей карте):
    # 'old_fund' | 'modern' | 'new_building' | 'elite' | 'unknown'
    package = Column(String(32), nullable=True)

    # Полный сырой JSON от парсера — fallback для полей, которые не
    # вытащили в нормализованные колонки.
    raw_data = Column(JSON, nullable=True)

    parsed_at = Column(TIMESTAMP(timezone=True), server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    active_ads = relationship("ActiveAd", back_populates="house", cascade="save-update")
    sold_ads = relationship("SoldAd", back_populates="house", cascade="save-update")

    __table_args__ = (
        UniqueConstraint("source", "external_house_id", name="uq_houses_source_external"),
        Index("idx_houses_cian_house_id", "cian_house_id"),
        Index("idx_houses_domclick_house_id", "domclick_house_id", postgresql_where=text("domclick_house_id IS NOT NULL")),
        Index("idx_houses_winners_house_id", "winners_house_id", postgresql_where=text("winners_house_id IS NOT NULL")),
        Index("idx_houses_latlng", "lat", "lng"),
    )

    def __repr__(self) -> str:
        return f"<House id={self.id} source={self.source!r} ext={self.external_house_id!r}>"


class ActiveAd(Base):
    """Активные объявления. Сейчас пишет только cian_active."""

    __tablename__ = "active_ads"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    source = Column(String(64), nullable=False, default=Source.CIAN_ACTIVE.value)
    external_id = Column(String(64), nullable=False)  # source-specific natural key
    url = Column(Text, nullable=True)

    house_id = Column(BigInteger, ForeignKey("houses.id", ondelete="SET NULL"), nullable=True)
    cian_house_id = Column(BigInteger, nullable=True)

    price = Column(BigInteger, nullable=True)
    price_per_m2 = Column(Integer, nullable=True)
    area = Column(Float, nullable=True)
    rooms = Column(Integer, nullable=True)
    floor_current = Column(Integer, nullable=True)
    floor_total = Column(Integer, nullable=True)

    metro_station = Column(String(128), nullable=True)
    metro_walk_time = Column(Integer, nullable=True)
    district = Column(String(128), nullable=True)
    okrug = Column(String(128), nullable=True)
    renovation = Column(String(64), nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    days_in_exposition = Column(Integer, nullable=True)
    total_views = Column(Integer, nullable=True)
    unique_views = Column(Integer, nullable=True)
    publish_date = Column(Date, nullable=True)

    # ID поискового фильтра из cian_filters (для cian_active).
    # Связывает объявление с вкладкой Google Sheets:
    # 1-2 = offers (до/после 2000, не-ЦАО),
    # 3-4 = offers (до/после 2000, ЦАО),
    # 5   = signals (Опека),
    # 6   = advance/deposit (Запрет долги).
    filter_id = Column(Integer, nullable=True)

    price_history = Column(JSON, nullable=True)
    raw_data = Column(JSON, nullable=True)

    parsed_at = Column(TIMESTAMP(timezone=True), server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    house = relationship("House", back_populates="active_ads")

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_active_ads_source_external_id"),
        Index("idx_active_ads_house_id", "house_id"),
        Index("idx_active_ads_is_active", "is_active"),
        Index("idx_active_ads_filter_id", "filter_id"),
    )

    def __repr__(self) -> str:
        return f"<ActiveAd id={self.id} source={self.source!r} external_id={self.external_id!r}>"


class SoldAd(Base):
    """Снятые/проданные объявления. Пишут: cian_active, cian_sold,
    winners_sold, domclick_sold."""

    __tablename__ = "sold_ads"

    id = Column(BigIntPK, primary_key=True, autoincrement=True)
    source = Column(String(64), nullable=False, index=True)
    external_id = Column(String(128), nullable=False)
    url = Column(Text, nullable=True)

    house_id = Column(BigInteger, ForeignKey("houses.id", ondelete="SET NULL"), nullable=True)
    cian_house_id = Column(BigInteger, nullable=True)

    price = Column(BigInteger, nullable=True)
    price_per_m2 = Column(Integer, nullable=True)
    area = Column(Float, nullable=True)
    rooms = Column(Integer, nullable=True)
    floor_current = Column(Integer, nullable=True)
    floor_total = Column(Integer, nullable=True)
    renovation = Column(String(64), nullable=True)

    exposition_days = Column(Integer, nullable=True)
    publish_date = Column(Date, nullable=True)
    sold_date = Column(Date, nullable=True)

    raw_data = Column(JSON, nullable=True)

    parsed_at = Column(TIMESTAMP(timezone=True), server_default=func.current_timestamp())

    house = relationship("House", back_populates="sold_ads")

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_sold_ads_source_external_id"),
        Index("idx_sold_ads_house_id", "house_id"),
        Index("idx_sold_ads_cian_house_id", "cian_house_id"),
        Index("idx_sold_ads_sold_date", "sold_date"),
    )

    def __repr__(self) -> str:
        return f"<SoldAd id={self.id} source={self.source!r} ext={self.external_id!r}>"

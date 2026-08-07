-- Dashboard: parsed ads (отдельная таблица, НЕ влияет на карту).
--
-- Хранит full offerData, который flippercrawl парсит через /v2/cian/scrape.
-- Карта использует другой источник (cian house history endpoint) — поэтому
-- эта таблица может быть пустой / частично заполненной, и карта всё равно
-- работает. Dashboard'у же нужны full данные (photos, agent, description,
-- bti, priceChanges, и т.д.) для глубокого анализа.
--
-- Source: CianSource через /v2/cian/scrape → rawOfferData + mapped fields
-- Stored once per (cian_house_id, external_id); idempotent upsert.

CREATE TABLE IF NOT EXISTS dashboard_parsed_ads (
    id              BIGSERIAL PRIMARY KEY,
    cian_house_id   BIGINT NOT NULL,
    external_id     TEXT NOT NULL,                -- cian offer id (string)
    status          TEXT,                         -- 'published' | 'deactivated' | 'unknown'
    title           TEXT,
    price           BIGINT,
    price_per_m2    BIGINT,
    area            DOUBLE PRECISION,
    rooms           INTEGER,
    floor_current   INTEGER,
    floor_total     INTEGER,
    exposition_days INTEGER,
    date_start      DATE,
    date_end        DATE,
    url             TEXT,
    address_full    TEXT,
    metro_station   TEXT,
    district        TEXT,
    okrug           TEXT,
    -- Full offerData (offer, agent, photos, bti, seoData, ...) для дашборда
    raw_data        JSON,
    -- Metadata
    cian_extraction_mode TEXT,                    -- 'static' / 'llm'
    parsed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (cian_house_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_dpa_cian_house_id
    ON dashboard_parsed_ads (cian_house_id);
CREATE INDEX IF NOT EXISTS idx_dpa_external_id
    ON dashboard_parsed_ads (external_id);
CREATE INDEX IF NOT EXISTS idx_dpa_status
    ON dashboard_parsed_ads (cian_house_id, status);
CREATE INDEX IF NOT EXISTS idx_dpa_parsed_at
    ON dashboard_parsed_ads (parsed_at DESC);

COMMENT ON TABLE dashboard_parsed_ads IS
    'Parsed cian offerData from flippercrawl /v2/cian/scrape. '
    'Separate from main pipeline: used only by the dashboard tab, '
    'NOT by the map (map uses cian house history endpoint directly).';

COMMENT ON COLUMN dashboard_parsed_ads.raw_data IS
    'Full state.offerData (offer, agent, photos, bti, priceChanges, '
    'seoData, breadcrumbs, ...). Same data as flippercrawl returns.';

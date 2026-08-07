-- View: cian_houses_map
--
-- Объединяет все известные нам cian-дома (дом = source='cian'/'cian_active'/'cian_api_house',
-- external_house_id или cian_house_id содержит cian house id) в один список.
-- Возвращает cian house id как BIGINT, lat/lng, address, source — то что нужно карте.
--
-- Поля:
--   cian_house_id   : BIGINT   — канонический id дома в cian.ru
--   address         : TEXT
--   lat, lng        : DOUBLE
--   source          : TEXT     — откуда пришёл (для отладки / dedup)
--   house_id        : BIGINT   — PK в houses (для drill-down / detail endpoint)
--   parsed_count    : INT     — сколько ads у нас в БД на этот дом (для UI)
--
-- Дома из source='cian' (claimed flatinfo) — те, что мы раньше линковали через
-- link_cian_active_to_houses.py. У них external_house_id = flatinfo PK, cian_house_id
-- = cian house id. Они тоже попадают на карту.
--
-- Дома из source='cian_api_house' / 'cian_active' — у них external_house_id = cian house id.
-- Парсим строку 'cian:NNNN' или чистую 'NNNN'.

CREATE OR REPLACE VIEW cian_houses_map AS
WITH all_cian_houses AS (
    -- Группа 1: cian house id из cian_house_id колонки (claimed flatinfo)
    SELECT
        cian_house_id::bigint AS cian_house_id,
        address,
        lat,
        lng,
        'cian'::text AS source,
        id AS house_id,
        cian_real_house_id
    FROM houses
    WHERE source = 'cian' AND cian_house_id IS NOT NULL

    UNION ALL

    -- Группа 2: cian house id из external_house_id (с префиксом 'cian:')
    SELECT
        (regexp_replace(external_house_id, '^cian:', ''))::bigint AS cian_house_id,
        address,
        lat,
        lng,
        source,
        id AS house_id,
        cian_real_house_id
    FROM houses
    WHERE source = 'cian_api_house' AND external_house_id ~ '^cian:[0-9]+$'

    UNION ALL

    -- Группа 3: cian house id из external_house_id (без префикса, чистое число)
    SELECT
        external_house_id::bigint AS cian_house_id,
        address,
        lat,
        lng,
        source,
        id AS house_id,
        cian_real_house_id
    FROM houses
    WHERE source = 'cian_active' AND external_house_id ~ '^[0-9]+$'

    UNION ALL

    -- Группа 4: cian_api_house без префикса (если такие есть)
    SELECT
        external_house_id::bigint AS cian_house_id,
        address,
        lat,
        lng,
        source,
        id AS house_id,
        cian_real_house_id
    FROM houses
    WHERE source = 'cian_api_house' AND external_house_id ~ '^[0-9]+$'
)
SELECT
    cian_house_id,
    MIN(address) FILTER (WHERE address IS NOT NULL) AS address,
    AVG(lat)::double precision AS lat,
    AVG(lng)::double precision AS lng,
    -- Берём "лучший" source: cian_active > cian > cian_api_house
    (array_agg(source ORDER BY CASE source
        WHEN 'cian_active' THEN 1
        WHEN 'cian' THEN 2
        WHEN 'cian_api_house' THEN 3
        ELSE 4
    END ASC))[1] AS source,
    -- Один из PK в houses (для drill-down)
    (array_agg(house_id ORDER BY CASE source
        WHEN 'cian_active' THEN 1
        WHEN 'cian' THEN 2
        WHEN 'cian_api_house' THEN 3
        ELSE 4
    END ASC))[1] AS house_id
FROM all_cian_houses
WHERE cian_house_id IS NOT NULL
GROUP BY cian_house_id;

-- Тест: сколько домов в view
SELECT count(*) AS total,
       count(*) FILTER (WHERE lat IS NOT NULL AND lng IS NOT NULL) AS with_coords,
       count(DISTINCT source) AS distinct_sources
FROM cian_houses_map;

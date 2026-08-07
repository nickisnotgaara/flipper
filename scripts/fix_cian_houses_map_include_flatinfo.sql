-- Migration: include source='flatinfo' in cian_houses_map view.
--
-- Why: all 28,382 flatinfo houses already have cian_house_id set (filled by
-- the old pipeline that did the spatial link). But the view only looked at
-- source IN ('cian', 'cian_active', 'cian_api_house'), so the map only
-- showed ~1k dots. Adding flatinfo as a 4th source in the UNION ALL brings
-- the map to ~29k dots — full Moscow coverage.
--
-- This is the core of the user's request: "we need to know every house's
-- cian id for the map". We already HAD that data in houses.cian_house_id;
-- the view just wasn't reading it.

CREATE OR REPLACE VIEW cian_houses_map AS
WITH all_cian_houses AS (
    -- Group 1: source='cian' (claimed flatinfo, claimed via cian search)
    -- 988 rows. These are the "best quality" links (the address+lat/lng
    -- came from cian search itself).
    SELECT
        cian_house_id::bigint AS cian_house_id,
        address, lat, lng,
        'cian'::text AS source,
        id AS house_id,
        cian_real_house_id
    FROM houses
    WHERE source = 'cian' AND cian_house_id IS NOT NULL

    UNION ALL

    -- Group 2: source='cian_api_house' with 'cian:' prefix
    SELECT
        (regexp_replace(external_house_id, '^cian:', ''))::bigint AS cian_house_id,
        address, lat, lng,
        source, id AS house_id, cian_real_house_id
    FROM houses
    WHERE source = 'cian_api_house' AND external_house_id ~ '^cian:[0-9]+$'

    UNION ALL

    -- Group 3: source='cian_active' with numeric external_house_id
    -- (these come from parsing cian ads and extracting house id from
    -- offer.geo.address[type=house].id)
    SELECT
        external_house_id::bigint AS cian_house_id,
        address, lat, lng,
        source, id AS house_id, cian_real_house_id
    FROM houses
    WHERE source = 'cian_active' AND external_house_id ~ '^[0-9]+$'

    UNION ALL

    -- Group 4: source='cian_api_house' with numeric external_house_id
    SELECT
        external_house_id::bigint AS cian_house_id,
        address, lat, lng,
        source, id AS house_id, cian_real_house_id
    FROM houses
    WHERE source = 'cian_api_house' AND external_house_id ~ '^[0-9]+$'

    UNION ALL

    -- Group 5 (NEW): source='flatinfo' houses
    -- These are 28,382 Moscow houses from the old flatinfo feed. They have
    -- cian_house_id set (via old spatial-link pipeline). Adding this group
    -- brings the map from ~1k dots to ~29k dots — full Moscow coverage.
    SELECT
        cian_house_id::bigint AS cian_house_id,
        address, lat, lng,
        'flatinfo'::text AS source,
        id AS house_id,
        cian_real_house_id
    FROM houses
    WHERE source = 'flatinfo' AND cian_house_id IS NOT NULL
)
SELECT
    cian_house_id,
    MIN(address) FILTER (WHERE address IS NOT NULL) AS address,
    AVG(lat)::double precision AS lat,
    AVG(lng)::double precision AS lng,
    -- Best-source picker. Priority (lower = better):
    --   cian_active 1 (came from parsing an actual ad)
    --   cian        2 (came from cian search)
    --   cian_api_house 3 (came from cian API directly)
    --   flatinfo    4 (came from old flatinfo link)
    (array_agg(source ORDER BY CASE source
        WHEN 'cian_active' THEN 1
        WHEN 'cian' THEN 2
        WHEN 'cian_api_house' THEN 3
        WHEN 'flatinfo' THEN 4
        ELSE 5
    END ASC))[1] AS source,
    (array_agg(house_id ORDER BY CASE source
        WHEN 'cian_active' THEN 1
        WHEN 'cian' THEN 2
        WHEN 'cian_api_house' THEN 3
        WHEN 'flatinfo' THEN 4
        ELSE 5
    END ASC))[1] AS house_id
FROM all_cian_houses
WHERE cian_house_id IS NOT NULL
GROUP BY cian_house_id;

-- Sanity check
SELECT count(*) AS total,
       count(*) FILTER (WHERE lat IS NOT NULL AND lng IS NOT NULL) AS with_coords,
       count(DISTINCT source) AS sources
FROM cian_houses_map;

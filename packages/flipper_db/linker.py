"""packages.flipper_db.linker — async linker for ads → houses (v4, address-first).

**v4 design (2026-08-01 00:18)** — Per user request, address is the canonical
match key. cian_house_id is dropped (was unreliable, full of duplicates).
Pipeline is: parse ad → extract address from offerData → match against
flatinfo by (street, house_num). Spatial is FALLBACK only.

Strategy:
  1. **Address match** (PRIMARY) — extract (street, house_num) from
     `offer.geo.address[]`. Normalize (drop "улица"/"шоссе"/etc suffix,
     drop "д." prefix). Try:
       a. Exact (street_norm, house_base) match
       b. (street_norm, leading_num) match — lenient fallback for
          "15" → "15/22" or "27к3" → "27"
  2. **Spatial fallback** — if no address match but ad has lat/lng,
     fall back to cKDTree search within 75m.
  3. **No cian_house_id cross-ref** (per user, all wrong).
  4. **No auto-create** (per user, only flatinfo is allowed).

Performance:
  - Address index is built ONCE per pipeline run (cached in
    ``FlatinfoIndex`` instance). 28k flatinfo houses → ~50k index entries.
  - Per-ad match is O(1) dict lookup + O(log n) spatial.
  - Index load is ~100ms on warm Postgres.

Public API
----------
``async def build_flatinfo_index(conn) -> FlatinfoIndex``
    Build the address+spatial index for all flatinfo houses.

``class FlatinfoIndex``
    ``match(address: str, lat: float, lng: float) -> Optional[int]``
        Returns house_id or None. PRIMARY entry point for the pipeline.

``async def match_or_create_house(conn, ad, *, index=None, ...) -> Optional[int]``
    Per-ad match. Thin wrapper around ``FlatinfoIndex.match``.

``async def link_ads(conn, *, ad_table='active_ads', ad_source='cian_active', ...)``
    Batch reconciliation (post-pipeline).

``async def link_ads_by_cian_ids(...)``
    Same as link_ads, but only for a specific set of external_ids.

Both batch functions return a dict with:
  ``matched_exact``, ``matched_geo``, ``ambiguous``, ``no_match``,
  ``no_coords``, ``applied``.

Dependencies: numpy, scipy, asyncpg.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

import asyncpg
import numpy as np
from scipy.spatial import cKDTree

log = logging.getLogger("flipper_db.linker")

EARTH_R = 6_371_000.0
DEFAULT_RADIUS_M = 75.0
DEFAULT_AMBIGUITY_RATIO = 1.3

AD_TABLES: tuple[str, ...] = ("active_ads", "sold_ads")

# Sources that are "real" houses (v4: flatinfo only).
GOOD_SOURCES: tuple[str, ...] = ("flatinfo",)

# Sources that must be excluded from matching.
EXCLUDED_SOURCES: tuple[str, ...] = (
    "cian_active", "cian_active_ad", "cian", "cian_api_house", "auto",
)

DEFAULT_HOUSES_SOURCES: tuple[str, ...] = GOOD_SOURCES


# --- Address normalization -------------------------------------------------

STREET_SUFFIXES = (
    "улица", "шоссе", "проезд", "переулок", "площадь",
    "набережная", "бульвар", "аллея", "проспект", "тракт",
    "тупик", "квартал",
)


def normalize_street(s: str) -> str:
    """Drop suffix/prefix 'улица' etc. Lowercase. Collapse whitespace."""
    if not s:
        return ""
    s = s.lower().replace("ё", "е").strip()
    for suf in STREET_SUFFIXES:
        if s.endswith(" " + suf):
            s = s[: -len(suf) - 1].strip()
            break
    s = re.sub(r"[.,]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_house_base(h: str) -> str:
    """Extract just the base number (no д., no корпус, no строение).
    e.g. 'д.39 с.1' -> '39', '5/12 к.2' -> '5/12', '46/2с3' -> '46/2'
    """
    if not h:
        return ""
    h = h.lower().replace("ё", "е")
    h = re.sub(r"^(д|дом)\.?\s*", "", h).strip()
    parts = h.split()
    return parts[0].strip() if parts else ""


def leading_num(s: str) -> str:
    """Extract leading numeric part. '5/12' -> '5', '15' -> '15'"""
    m = re.match(r"(\d+)", s or "")
    return m.group(1) if m else ""


def extract_address_from_offer(raw_offer: dict) -> Optional[str]:
    """Build full address string from cian's `offer.geo.address[]`.

    Returns "Москва, ЦАО, Хамовники, Льва Толстого, 16" or None.
    """
    if not raw_offer:
        return None
    geo = raw_offer.get("geo") or {}
    addr_arr = geo.get("address") or []
    parts = []
    for elem in addr_arr:
        if isinstance(elem, dict) and elem.get("name"):
            parts.append(str(elem["name"]))
    if not parts:
        return None
    return ", ".join(parts)


def extract_street_house(full_addr: str) -> tuple[str, str]:
    """From "Москва, ЦАО, Хамовники, Льва Толстого, 16" → ("льва толстого", "16")."""
    if not full_addr:
        return "", ""
    parts = [p.strip() for p in full_addr.split(",")]
    if len(parts) < 2:
        return "", ""
    return normalize_street(parts[-2]), normalize_house_base(parts[-1])


# --- Flatinfo index --------------------------------------------------------


@dataclass
class _CreateStats:
    """Mutable container for create-stats (legacy, ignored in v4)."""
    created: int = 0
    updated: int = 0


class FlatinfoIndex:
    """In-memory index of all flatinfo houses for address+spatial matching.

    Built once per pipeline run via ``await build_flatinfo_index(conn)``.
    Thread-unsafe (async-only). Stateless after construction.
    """

    def __init__(self):
        # (street_norm, house_base) -> house_id
        self._exact: dict[tuple[str, str], int] = {}
        # (street_norm, leading_num) -> [house_ids]
        self._lead: dict[tuple[str, str], list[int]] = {}
        # Spatial fallback
        self._spatial_ids: Optional[np.ndarray] = None
        self._spatial_coords: Optional[np.ndarray] = None
        self._spatial_tree: Optional[cKDTree] = None
        self._loaded: bool = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def n_houses(self) -> int:
        return len(self._exact) if self._loaded else 0

    async def load(self, conn: asyncpg.Connection) -> "FlatinfoIndex":
        """Load from DB. Idempotent."""
        if self._loaded:
            return self
        rows = await conn.fetch(
            "SELECT id, street, house_num, lat, lng FROM houses "
            "WHERE source='flatinfo'"
        )
        spatial_ids = []
        spatial_coords = []
        for r in rows:
            sn = normalize_street(r["street"])
            hb = normalize_house_base(r["house_num"])
            if sn and hb:
                self._exact[(sn, hb)] = r["id"]
                ln = leading_num(hb)
                if ln:
                    self._lead.setdefault((sn, ln), []).append(r["id"])
            if r["lat"] is not None and r["lng"] is not None:
                spatial_ids.append(r["id"])
                spatial_coords.append((r["lat"], r["lng"]))
        if spatial_ids:
            self._spatial_ids = np.array(spatial_ids, dtype=np.int64)
            self._spatial_coords = np.deg2rad(
                np.array(spatial_coords, dtype=np.float64)
            )
            self._spatial_tree = cKDTree(self._spatial_coords)
        self._loaded = True
        log.info(
            "FlatinfoIndex loaded: %d exact, %d leading-num, %d spatial",
            len(self._exact), len(self._lead), len(spatial_ids),
        )
        return self

    def match(
        self,
        address: Optional[str],
        lat: Optional[float],
        lng: Optional[float],
        *,
        radius_m: float = DEFAULT_RADIUS_M,
    ) -> Optional[int]:
        """Match an ad to a house. Returns house_id or None.

        1. Address exact (street_norm, house_base)
        2. Address leading-num (street_norm, leading_num) — only if single match
        3. Spatial fallback (75m) — if address match didn't work
        """
        if not self._loaded:
            return None

        # 1. Address match
        if address:
            street, house = extract_street_house(address)
            if street and house:
                key = (street, house)
                if key in self._exact:
                    return self._exact[key]
                # Lenient: leading num
                ln = leading_num(house)
                if ln:
                    key2 = (street, ln)
                    cands = self._lead.get(key2)
                    if cands and len(cands) == 1:
                        return cands[0]

        # 2. Spatial fallback
        if (lat is not None and lng is not None
                and self._spatial_tree is not None):
            ad_rad = np.deg2rad(np.array([(lat, lng)], dtype=np.float64))
            dists, idxs = self._spatial_tree.query(ad_rad, k=1)
            d_m = float(dists[0]) * EARTH_R
            if d_m <= radius_m:
                return int(self._spatial_ids[int(idxs[0])])

        return None


async def build_flatinfo_index(conn: asyncpg.Connection) -> FlatinfoIndex:
    """Build and return a fresh ``FlatinfoIndex``."""
    idx = FlatinfoIndex()
    await idx.load(conn)
    return idx


# --- Auto-create house from cian ad (v3.0) ---------------------------------

# Material→building_type mapping (cian offer.building.materialType strings)
_MATERIAL_MAP = {
    "brick": "Кирпичный",
    "monolith": "Монолитный",
    "panel": "Панельный",
    "monolithBrick": "Монолитно-кирпичный",
    "block": "Блочный",
    "wood": "Деревянный",
    "stalMonolith": "Монолитный",
    "reinforcedConcrete": "Железобетонный",
    "aeratedConcrete": "Газобетонный",
    "foamConcrete": "Пенобетон",
}


def _safe_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        s = str(v).strip()
        if not s:
            return None
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


async def _create_house_from_ad(
    conn: asyncpg.Connection,
    ad: Any,
    *,
    source: Any = None,  # SourceParser — для source-agnostic house extraction
) -> Optional[int]:
    """Create a new house row from an ad's raw_data.

    Source-agnostic v2 (2026-08-05): если передан ``source`` (SourceParser),
    вызывает ``source.house_record_from_ad(ad)`` для извлечения полей дома
    (address, year_built, levels, building_type, series, ceiling_height).
    Иначе — fallback на cian-специфичную логику (parse raw.offer.building).

    Returns the new house id, или id существующего дома (dedup по
    (street_norm, house_base) перед INSERT), или None если required fields
    отсутствуют.
    """
    addr = getattr(ad, "address", None) or ""
    lat = getattr(ad, "lat", None)
    lng = getattr(ad, "lng", None)
    if not addr and (lat is None or lng is None):
        return None  # nothing to work with

    # Source-agnostic extraction через HouseRecord
    source_name = "cian_ad"  # default для обратной совместимости
    year_built = None
    levels = None
    building_type = None
    series = None
    ceiling_height = None
    raw_data_payload = None

    if source is not None and hasattr(source, "house_record_from_ad"):
        # Source-agnostic путь (CianSource, DomclickSource, ...)
        try:
            hr = source.house_record_from_ad(ad)
        except Exception as exc:
            log.warning("source.house_record_from_ad failed: %s", exc)
            hr = None
        if hr is not None:
            # Берём поля из HouseRecord
            addr = addr or hr.address  # не затираем если уже был
            street_from_hr = hr.street
            house_num_from_hr = hr.house_num
            district_name = hr.district
            okrug_name = hr.okrug
            year_built = hr.year_built
            levels = hr.levels
            building_type = hr.building_type
            series = hr.series
            ceiling_height = hr.ceiling_height
            source_name = source.source_name  # правильный source
            raw_data_payload = hr.raw_data
        else:
            log.warning("source.house_record_from_ad returned None, falling back")
            source = None  # fallback ниже

    if source is None:
        # Fallback: cian-специфичный парсинг (для обратной совместимости)
        raw = getattr(ad, "raw_data", None) or {}
        if isinstance(raw, str):
            try:
                import json as _json
                raw = _json.loads(raw)
            except Exception:
                raw = {}
        offer = raw.get("offer") if isinstance(raw, dict) else None
        offer = offer or {}
        building = offer.get("building") or {}
        geo = offer.get("geo") or {}
        address_arr = geo.get("address") or []

        street_name = None
        house_num = None
        district_name = None
        okrug_name = None
        for elem in address_arr:
            if not isinstance(elem, dict):
                continue
            etype = elem.get("type")
            ename = elem.get("name")
            if not ename:
                continue
            if etype == "street":
                street_name = str(ename)
            elif etype == "house":
                house_num = str(ename)
            elif etype == "raion":
                district_name = str(ename)
            elif etype == "okrug":
                okrug_name = str(ename)

        street_from_hr = street_name
        house_num_from_hr = house_num
        year_built = _safe_int(building.get("buildYear"))
        levels = _safe_int(building.get("floorsCount"))
        series = building.get("series")
        series = str(series).strip() if series else None
        material_raw = building.get("materialType")
        building_type = _MATERIAL_MAP.get(material_raw) if material_raw else None
        ceiling_height = _safe_float(building.get("ceilingHeight"))
        raw_data_payload = {"offer_building": building, "offer_geo": geo}

    # Normalize street/house для dedup
    street_norm = normalize_street(street_from_hr or "")
    house_base = normalize_house_base(house_num_from_hr or "")

    if (not street_norm or not house_base) and (lat is None or lng is None):
        return None  # neither address nor coords

    # Synthesize full address from parts (lat/lng fallback if addr is empty)
    full_address = addr or None
    if not full_address and (lat is not None and lng is not None):
        full_address = f"{lat:.5f}, {lng:.5f}"

    external_id = getattr(ad, "external_id", None) or "unknown"
    # external_house_id: используем source-specific префикс, чтобы не
    # пересекаться с существующими cian_ad домами
    if source_name == "cian_ad":
        ext_house_id = f"ad_{external_id}"[:128]  # legacy cian_ad формат
    else:
        ext_house_id = str(external_id)[:128]  # domclick_sold: external_id напрямую

    # Dedup by (street_norm, house_base) перед INSERT.
    # cian_ad: dedup against same source (legacy).
    # non-cian sources (domclick_sold, winners_sold, etc.): dedup against ANY
    # existing house with the same address — otherwise we get spatial duplicates
    # of cian_ad / flatinfo houses. (Bug fix 2026-08-05.)
    if street_norm and house_base:
        if source_name == "cian_ad":
            dup = await conn.fetchrow(
                """
                SELECT id FROM houses
                WHERE LOWER(COALESCE(street,'')) = $1
                  AND LOWER(COALESCE(house_num,'')) = $2
                LIMIT 1
                """,
                street_norm, house_base,
            )
            if dup:
                return int(dup["id"])
        else:
            # Address dedup across ALL sources — prefer a non-auto house if any
            dup = await conn.fetchrow(
                """
                SELECT id, source FROM houses
                WHERE LOWER(COALESCE(street,'')) = $1
                  AND LOWER(COALESCE(house_num,'')) = $2
                ORDER BY (source = 'auto') ASC,  -- prefer real sources
                         (source = 'flatinfo') DESC,
                         id ASC
                LIMIT 1
                """,
                street_norm, house_base,
            )
            if dup:
                log.info(
                    "Dedup: skipping new %s house for ad %s — reusing existing house id=%s source=%s (same street+house)",
                    source_name, external_id, dup["id"], dup["source"],
                )
                return int(dup["id"])

    # Final spatial dedup for non-cian sources: even if street/house don't
    # match exactly, the building might already exist nearby (e.g. domclick
    # has lat/lng but no street_name → street dedup above skipped).
    if source_name != "cian_ad" and lat is not None and lng is not None:
        spatial_dup = await conn.fetchrow(
            """
            SELECT id, source, dist_m FROM (
                SELECT id, source,
                       6371000 * acos(
                           LEAST(1.0, GREATEST(-1.0,
                               cos(radians($1)) * cos(radians(lat)) *
                               cos(radians(lng) - radians($2)) +
                               sin(radians($1)) * sin(radians(lat))
                           ))
                       ) AS dist_m
                FROM houses
                WHERE lat IS NOT NULL AND lng IS NOT NULL
                  AND source IN ('cian_ad', 'flatinfo', 'domclick_sold', 'winners_sold', 'cian_sold', 'cian_deactivated')
            ) sub
            WHERE dist_m <= $3
            ORDER BY dist_m ASC
            LIMIT 1
            """,
            float(lat), float(lng), 75.0,
        )
        if spatial_dup:
            log.info(
                "Dedup: skipping new %s house for ad %s — reusing existing house id=%s source=%s (%.0fm away)",
                source_name, external_id, spatial_dup["id"], spatial_dup["source"], spatial_dup["dist_m"],
            )
            return int(spatial_dup["id"])

    row = await conn.fetchrow(
        """
        INSERT INTO houses (
            source, external_house_id, address, street, house_num,
            district, okrug,
            lat, lng,
            year_built, year_built_source,
            levels, levels_source,
            building_type, building_type_source,
            series, series_source,
            ceiling_height,
            enriched_from_source, created_from_ad,
            raw_data, parsed_at, updated_at
        )
        VALUES (
            $1, $2, $3, $4, $5,
            $6, $7,
            $8, $9,
            $10, $11,
            $12, $13,
            $14, $15,
            $16, $17,
            $18,
            $19, $20,
            $21, NOW(), NOW()
        )
        RETURNING id
        """,
        # 1: source, 2: external_house_id, 3: address, 4: street, 5: house_num
        source_name, ext_house_id, full_address, street_norm or None, house_base or None,
        # 6: district, 7: okrug
        district_name, okrug_name,
        # 8: lat, 9: lng
        lat, lng,
        # 10: year_built, 11: year_built_source
        year_built, source_name,
        # 12: levels, 13: levels_source
        levels, source_name,
        # 14: building_type, 15: building_type_source
        building_type, source_name,
        # 16: series, 17: series_source
        series, source_name,
        # 18: ceiling_height
        ceiling_height,
        # 19: enriched_from_source, 20: created_from_ad
        source_name, external_id,
        # 21: raw_data
        _json_dumps_safe(raw_data_payload) if raw_data_payload else "{}",
    )
    if row is None:
        return None
    new_id = int(row["id"])
    log.info(
        "Auto-created house id=%s source=%s from ad %s (street=%s, house=%s, lat=%s, lng=%s, year=%s)",
        new_id, source_name, external_id, street_norm, house_base, lat, lng, year_built,
    )
    return new_id


def _json_dumps_safe(obj) -> str:
    import json as _json
    try:
        return _json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return "{}"


# --- Per-ad match (workhorse for the pipeline) -----------------------------


async def match_or_create_house(
    conn: asyncpg.Connection,
    ad: Any,  # AdRecord — duck-typed
    *,
    source_name: str = "auto",  # ignored in v4
    auto_create: bool = False,  # v4 default False; v3+ enable per-run
    radius_m: float = DEFAULT_RADIUS_M,
    ambiguity_ratio: float = DEFAULT_AMBIGUITY_RATIO,
    create_stats: Optional[_CreateStats] = None,  # ignored
    index: Optional[FlatinfoIndex] = None,
    source: Any = None,  # SourceParser (для source-agnostic auto-create)
) -> Optional[int]:
    """Match an ad to a house. v3.0+: address-first, then auto-create on miss.

    Strategy:
      1. Address match (PRIMARY): (street, house) exact → (street, leading_num) lenient
      2. Spatial fallback (if ad has lat/lng and no address match)
      3. NO cian_house_id cross-ref (user request, v4)
      4. If auto_create=True and no match, INSERT a new house row.
         Source-agnostic v2 (2026-08-05): если передан ``source``, вызывает
         ``source.house_record_from_ad(ad)`` для извлечения полей дома.
         Иначе — fallback на cian-специфичный parse raw.offer.building.

    If ``index`` is None, builds a fresh one from the DB.
    """
    if index is None:
        index = await build_flatinfo_index(conn)
    addr = getattr(ad, "address", None)
    lat = getattr(ad, "lat", None)
    lng = getattr(ad, "lng", None)
    matched = index.match(addr, lat, lng, radius_m=radius_m)
    if matched is not None:
        return matched
    if not auto_create:
        return None
    return await _create_house_from_ad(conn, ad, source=source)


# --- DB loaders (for batch link_ads) ---------------------------------------


async def _load_houses_by_cian_hid(conn, sources):
    """v4: cian_house_id cross-ref is dropped. Returns empty dict."""
    return {}


async def _load_houses_with_coords(
    conn: asyncpg.Connection, sources: Sequence[str] | None
) -> tuple[np.ndarray, list[tuple[int, float, float]]]:
    if sources is None:
        sources = GOOD_SOURCES
    rows = await conn.fetch(
        "SELECT id, lat, lng FROM houses "
        "WHERE source = ANY($1::text[]) "
        "  AND lat IS NOT NULL AND lng IS NOT NULL",
        list(sources),
    )
    if not rows:
        return np.empty((0, 2), dtype=np.float64), []
    coords_deg = np.array([(r["lat"], r["lng"]) for r in rows], dtype=np.float64)
    return np.deg2rad(coords_deg), [(r["id"], r["lat"], r["lng"]) for r in rows]


async def _load_unlinked_ads(
    conn: asyncpg.Connection,
    ad_table: str,
    ad_source: str | None,
    cian_id_filter: Iterable[str] | None = None,
) -> list[tuple[str, int | None, float | None, float | None]]:
    if cian_id_filter is not None:
        ids = [str(x) for x in cian_id_filter]
        if ad_source:
            rows = await conn.fetch(
                f"""
                SELECT external_id, cian_house_id, lat, lng FROM {ad_table}
                WHERE source = $1 AND external_id = ANY($2::text[])
                  AND house_id IS NULL
                """,
                ad_source, ids,
            )
        else:
            rows = await conn.fetch(
                f"""
                SELECT external_id, cian_house_id, lat, lng FROM {ad_table}
                WHERE external_id = ANY($1::text[])
                  AND house_id IS NULL
                """,
                ids,
            )
    elif ad_source:
        rows = await conn.fetch(
            f"""
            SELECT external_id, cian_house_id, lat, lng FROM {ad_table}
            WHERE source = $1 AND house_id IS NULL
            """,
            ad_source,
        )
    else:
        rows = await conn.fetch(
            f"""
            SELECT external_id, cian_house_id, lat, lng FROM {ad_table}
            WHERE house_id IS NULL
            """
        )
    out = []
    for r in rows:
        out.append((
            str(r["external_id"]),
            int(r["cian_house_id"]) if r["cian_house_id"] is not None else None,
            float(r["lat"]) if r["lat"] is not None else None,
            float(r["lng"]) if r["lng"] is not None else None,
        ))
    return out


# --- Planning (batch match logic) ------------------------------------------


@dataclass
class LinkResult:
    matched_exact: int = 0  # matched via cian_house_id cross-ref (always 0 in v4)
    matched_geo: int = 0  # matched via address or spatial
    ambiguous: int = 0
    no_match: int = 0
    no_coords: int = 0
    applied: int = 0

    def to_dict(self) -> dict:
        return {
            "matched_exact": self.matched_exact,
            "matched_geo": self.matched_geo,
            "ambiguous": self.ambiguous,
            "no_match": self.no_match,
            "no_coords": self.no_coords,
            "applied": self.applied,
        }


def _match_by_cian_hid(ads, houses_by_cian_hid):
    """v4: cian_house_id cross-ref is dropped. Returns all as remaining."""
    return [], [(ext_id, lat, lng) for ext_id, _, lat, lng in ads]


def _match_by_coords(remaining, houses_coords_rad, houses, radius_m, ambiguity_ratio):
    if houses_coords_rad.shape[0] == 0:
        no_match = []
        no_coords = []
        for ext_id, lat, lng in remaining:
            if lat is None or lng is None:
                no_coords.append(ext_id)
            else:
                no_match.append((ext_id, float("inf")))
        return [], [], no_match, no_coords
    tree = cKDTree(houses_coords_rad)
    use_ambiguity = ambiguity_ratio > 1.0 and houses_coords_rad.shape[0] >= 2
    k = 2 if use_ambiguity else 1
    matched = []
    ambiguous = []
    no_match = []
    no_coords = []
    for ext_id, lat, lng in remaining:
        if lat is None or lng is None:
            no_coords.append(ext_id)
            continue
        ad_rad = np.deg2rad(np.array([(lat, lng)], dtype=np.float64))
        dists_rad, idxs = tree.query(ad_rad, k=k)
        if k == 1:
            dists_rad = dists_rad.reshape(-1, 1)
            idxs = idxs.reshape(-1, 1)
        best_idx = int(idxs[0, 0])
        best_d = float(dists_rad[0, 0]) * EARTH_R
        if best_d > radius_m:
            no_match.append((ext_id, best_d))
            continue
        if use_ambiguity:
            second_d = float(dists_rad[0, 1]) * EARTH_R
            if best_d >= 1.0 and second_d / best_d < ambiguity_ratio:
                ambiguous.append((ext_id, best_d, second_d))
                continue
        house_id = houses[best_idx][0]
        matched.append((ext_id, house_id, best_d))
    return matched, ambiguous, no_match, no_coords


# --- Apply -----------------------------------------------------------------


async def _apply(
    conn, matched_exact, matched_geo, ad_table, ad_source
) -> int:
    n = 0
    if matched_geo:
        if ad_source:
            await conn.executemany(
                f"""
                UPDATE {ad_table} AS a
                SET house_id = $1::int
                WHERE a.external_id = $2::text
                  AND a.source = $3::text
                  AND a.house_id IS NULL
                """,
                [(h, cid, ad_source) for cid, h, _ in matched_geo],
            )
        else:
            await conn.executemany(
                f"""
                UPDATE {ad_table} AS a
                SET house_id = $1::int
                WHERE a.external_id = $3::text AND a.house_id IS NULL
                """,
                [(h, cid) for cid, h, _ in matched_geo],
            )
        n += len(matched_geo)
    return n


# --- Public batch entry points ---------------------------------------------


def _plan(ads, houses_by_cian_hid, houses_coords_rad, houses, radius_m, ambiguity_ratio):
    matched_exact, remaining = _match_by_cian_hid(ads, houses_by_cian_hid)
    matched_geo, ambiguous, no_match, no_coords = _match_by_coords(
        remaining, houses_coords_rad, houses, radius_m, ambiguity_ratio
    )
    return matched_exact, matched_geo, ambiguous, no_match, no_coords


async def link_ads(
    conn,
    *,
    ad_table: str = "active_ads",
    ad_source: str | None = "cian_active",
    houses_sources: Sequence[str] | None = None,
    radius_m: float = DEFAULT_RADIUS_M,
    ambiguity_ratio: float = DEFAULT_AMBIGUITY_RATIO,
    apply: bool = False,
) -> dict:
    """Plan + (optionally) apply links for all unlinked ads (v4)."""
    if ad_table not in AD_TABLES:
        raise ValueError(f"ad_table must be one of {AD_TABLES}, got {ad_table!r}")
    sources = list(houses_sources) if houses_sources is not None else list(GOOD_SOURCES)
    ads = await _load_unlinked_ads(conn, ad_table, ad_source)
    if not ads:
        return LinkResult().to_dict()
    houses_coords, houses = await _load_houses_with_coords(conn, sources)
    houses_by_cian_hid: dict = {}
    matched_exact, matched_geo, ambiguous, no_match, no_coords = _plan(
        ads, houses_by_cian_hid, houses_coords, houses, radius_m, ambiguity_ratio
    )
    res = LinkResult(
        matched_exact=len(matched_exact),
        matched_geo=len(matched_geo),
        ambiguous=len(ambiguous),
        no_match=len(no_match),
        no_coords=len(no_coords),
    )
    if apply:
        res.applied = await _apply(
            conn, matched_exact, matched_geo, ad_table, ad_source
        )
    return res.to_dict()


async def link_ads_by_cian_ids(
    conn,
    cian_ids: Sequence[str],
    *,
    ad_table: str = "active_ads",
    ad_source: str | None = "cian_active",
    houses_sources: Sequence[str] | None = None,
    radius_m: float = DEFAULT_RADIUS_M,
    ambiguity_ratio: float = DEFAULT_AMBIGUITY_RATIO,
    apply: bool = False,
) -> dict:
    if ad_table not in AD_TABLES:
        raise ValueError(f"ad_table must be one of {AD_TABLES}, got {ad_table!r}")
    if not cian_ids:
        return LinkResult().to_dict()
    sources = list(houses_sources) if houses_sources is not None else list(GOOD_SOURCES)
    ads = await _load_unlinked_ads(conn, ad_table, ad_source, cian_id_filter=cian_ids)
    if not ads:
        return LinkResult().to_dict()
    houses_coords, houses = await _load_houses_with_coords(conn, sources)
    houses_by_cian_hid: dict = {}
    matched_exact, matched_geo, ambiguous, no_match, no_coords = _plan(
        ads, houses_by_cian_hid, houses_coords, houses, radius_m, ambiguity_ratio
    )
    res = LinkResult(
        matched_exact=len(matched_exact),
        matched_geo=len(matched_geo),
        ambiguous=len(ambiguous),
        no_match=len(no_match),
        no_coords=len(no_coords),
    )
    if apply:
        res.applied = await _apply(
            conn, matched_exact, matched_geo, ad_table, ad_source
        )
    return res.to_dict()

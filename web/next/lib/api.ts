// Lightweight API client. Talks to FastAPI at 127.0.0.1:8000 directly.
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000';
const BASE = API_BASE;

export type SuggestItem = {
  title: string;
  subtitle: string;
  formatted_address: string;
  distance_m?: number | null;
  tags: string[];
  street?: string | null;
  house_num?: string | null;
  /** DB match — set when the suggested address corresponds to a known house. */
  house?: {
    id: number;
    source: string;
    address: string;
    lat: number;
    lng: number;
  } | null;
};

export type GeocodeResult = {
  source: 'db' | 'yandex';
  lat: number | null;
  lng: number | null;
  house: {
    id: number;
    source: string;
    address: string;
    lat: number;
    lng: number;
  } | null;
  yandex_error?: number | string;
};

export type House = {
  id: number;
  house_id: number | null;
  address: string | null;
  street: string | null;
  house_num: string | null;
  year: number | null;
  type: string | null;
  levels: number | null;
  series: string | null;
  lat: number | null;
  lng: number | null;
  active_count: number;
  deactivated_count: number;
  /** True for grid-cluster rows (server returns a cell, not a real house). */
  is_synthetic?: boolean;
  /** Number of houses inside the cluster (only set when is_synthetic=true). */
  house_count?: number;
  /** Backend source tag (flatinfo / synthetic / cian_api_house). */
  source?: string;
};

export type Stats = {
  houses: number;
  houses_with_coords: number;
  active_total: number;
  active_linked: number;
  active_unlinked: number;
  deactivated_total: number;
  houses_with_ads: number;
  houses_with_deactivated: number;
  offers_source?: string;  // 'offers_parser' or 'active_ads' — for debugging
  /** Breakdown by source (dynamic — новые источники добавляются без правки фронта). */
  houses_by_source?: Record<string, number>;
  active_by_source?: Record<string, number>;
  sold_by_source?: Record<string, number>;
};

export type Ad = {
  id: number | string;
  source: string;
  /** Source-specific natural key (cian_id, domclick_id, ...). */
  external_id: string;
  url: string;
  price: number | null;
  price_per_m2: number | null;
  area: number | null;
  rooms: number | null;
  floor_current: number | null;
  floor_total: number | null;
  metro_station: string | null;
  metro_walk_time: number | null;
  district: string | null;
  okrug: string | null;
  renovation: string | null;
  days_in_exposition: number | null;
  title: string | null;
  publish_date: string | null;
  date_end: string | null;
  price_diff: string | null;
  exposition: string | null;
  filter_id?: number | null;
  /**
   * Full offerData from flippercrawl (active_ads.raw_data, dashboard_parsed_ads.raw_data).
   * Only populated for ads that have been re-parsed through flippercrawl — the
   * deactivated list reads this from sold_ads.raw_data when available, but for
   * legacy server-migrated rows the schema is different and photos are not
   * present.
   *
   * Photo URLs live at `raw_data.offer.photos[]` with each item having
   * `fullUrl`, `thumbnail2Url`, `thumbnailUrl`, `miniUrl`.
   */
  raw_data?: any | null;
};

export type HouseDetail = {
  house: House;
  active: Ad[];
  deactivated: Ad[];
  stats: { total_active: number; total_deactivated: number };
};

async function get<T>(path: string, params?: Record<string, any>): Promise<T> {
  const url = new URL(BASE + path);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === '') continue;
      url.searchParams.set(k, String(v));
    }
  }
  const r = await fetch(url.toString(), { cache: 'no-store' });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export const fetchHouses = (bbox: {
  min_lat: number;
  max_lat: number;
  min_lng: number;
  max_lng: number;
  limit?: number;
  with_ads_only?: boolean;
}) => get<House[]>('/api/houses', bbox);

/** Map clusters: real houses (zoom>=15) or grid clusters (zoom<15). */
export const fetchClusters = (bbox: {
  min_lat: number;
  max_lat: number;
  min_lng: number;
  max_lng: number;
  zoom: number;
  limit?: number;
  with_ads_only?: boolean;
}) => get<House[]>('/api/clusters', bbox);

export const fetchHouse = (id: number) => get<HouseDetail>(`/api/houses/${id}`);

/** Cluster detail — works for both real (id>0) and synthetic (id<0) clusters. */
export const fetchCluster = (id: number) =>
  get<HouseDetail>(`/api/clusters/${id}/ads`);

export const fetchStats = () => get<Stats>('/api/stats');

export const fetchSuggest = (text: string, bbox?: string) =>
  get<SuggestItem[]>('/api/suggest', { text, bbox });

export const fetchGeocode = (text: string) =>
  get<GeocodeResult>('/api/geocode', { text });

/** Фотки одного объявления по external_id. Источник-агностик. */
export type AdPhotos = {
  external_id: string;
  source: 'active_ads' | 'sold_ads' | null;
  ad_source: string | null;
  count: number;
  photos: Array<{
    id: string;
    fullUrl: string;
    thumbnail2Url: string;
    thumbnailUrl: string;
    miniUrl: string;
  }>;
};

export const fetchAdPhotos = (external_id: string) =>
  get<AdPhotos>(`/api/ads/${encodeURIComponent(external_id)}/photos`);

// Legacy GeoJSON helper — kept for compatibility, returns empty.
export type GeoJsonFC = { type: 'FeatureCollection'; features: any[] };
export const _legacyFetchGeoJson = async (): Promise<GeoJsonFC> => ({
  type: 'FeatureCollection',
  features: [],
});

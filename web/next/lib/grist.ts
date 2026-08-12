// Minimal Grist helper — only the base URL and a docIds map.
// The UI no longer renders Grist tables server-side; users open the live
// Grist UI in a new tab from the Sidebar (Парсинг / Архивы / Дома).
// Keep this file in case we need to call Grist's API from server code
// later (e.g. for embedding a small widget, exporting data, etc.).

// Production Grist endpoint (self-hosted at 217.149.23.102:8484).
// Override with NEXT_PUBLIC_GRIST_URL at build time if hosting elsewhere.
export const GRIST_URL = process.env.NEXT_PUBLIC_GRIST_URL ?? 'http://217.149.23.102:8484';

// Current Grist doc on production hosts the parsing, archives and main data
// in a single document. Override per-env with NEXT_PUBLIC_GRIST_DOC_*.
export const GRIST_DOCS = {
  parsing: process.env.NEXT_PUBLIC_GRIST_DOC_PARSING ?? 'em6piHbbtWXq3oyLYRahnd',
  archives: process.env.NEXT_PUBLIC_GRIST_DOC_ARCHIVES ?? 'em6piHbbtWXq3oyLYRahnd',
  main: process.env.NEXT_PUBLIC_GRIST_DOC_ID ?? 'em6piHbbtWXq3oyLYRahnd',
} as const;

// Real table IDs in production Grist doc (the ones with actual data after the
// 2026-08-12 import). The dashboard/sidebar links use these.
export const GRIST_TABLES = {
  houses: 'Houses3',
  activeAds: 'Active_ads2',
  soldAds: 'Sold_Ads2',
  cianFilters: 'Cian_Filters2',
  offersParser: 'Offers_Parser',
  arhivProdano: 'Arhiv_Prodano',
  signalsParser: 'Signals_Parser',
  balans: 'Balans',
} as const;

/** Build a deep link to a Grist document (page 1, no specific table). */
export function gristDocUrl(docId: string, tableId?: string): string {
  const base = `${GRIST_URL}/${docId}/p/1`;
  return tableId ? `${base}?table=${tableId}` : base;
}

// === Stub helpers (left for legacy /_disabled_analytics page; unused by the
// current app which opens the live Grist UI in a new tab). They are kept here
// so the production build still type-checks the disabled page.
export async function listTables(_docId: string): Promise<Array<{ id: string; fields: Record<string, unknown> }>> {
  return [];
}
export async function sqlRecords(_docId: string, _sql: string): Promise<unknown[]> {
  return [];
}
export async function tableColumns(_docId: string, _tableId: string): Promise<Array<{ id: string; label: string }>> {
  return [];
}
export async function tableRecords(_docId: string, _tableId: string, _opts: Record<string, unknown> = {}): Promise<{ records: Array<{ id: number; fields: Record<string, unknown> }> }> {
  return { records: [] };
}

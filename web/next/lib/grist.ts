// Minimal Grist helper — only the base URL and a docIds map.
// The UI no longer renders Grist tables server-side; users open the live
// Grist UI in a new tab from the Sidebar (Парсинг / Архивы / Дома).
// Keep this file in case we need to call Grist's API from server code
// later (e.g. for embedding a small widget, exporting data, etc.).

export const GRIST_URL = process.env.NEXT_PUBLIC_GRIST_URL ?? 'http://localhost:8484';

export const GRIST_DOCS = {
  parsing: process.env.NEXT_PUBLIC_GRIST_DOC_PARSING ?? 'mDaHoGD6yahtxaqugwr5mK',
  archives: process.env.NEXT_PUBLIC_GRIST_DOC_ARCHIVES ?? 'kaBfATwGgUYjDa8doqMzk3',
  main: process.env.NEXT_PUBLIC_GRIST_DOC_ID ?? 'rYyn6wJZihqm1TAgkBgPnY',
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

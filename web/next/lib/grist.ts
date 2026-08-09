// Server-side helper for Grist API.
// Centralizes: API key, base URL, table listing, records, SQL queries.

export const GRIST_URL = process.env.GRIST_URL ?? 'http://localhost:8484';
const GRIST_API_KEY =
  process.env.GRIST_API_KEY ??
  'flipper_prod_c173df83d342e744aa1fa74bb80bd19a32f5f598d7e582c0c8d4561659290978';

const HEADERS = { Authorization: `Bearer ${GRIST_API_KEY}` };

export type GristTable = {
  id: string;
  name: string;
  fields?: Record<string, unknown>;
};

async function gristFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${GRIST_URL}${path}`, {
    ...init,
    headers: { ...HEADERS, 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    cache: 'no-store',
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`Grist ${r.status}: ${t.slice(0, 500)}`);
  }
  return r.json() as Promise<T>;
}

export async function listTables(docId: string): Promise<GristTable[]> {
  const r = await gristFetch<{ tables: Array<{ id: string; fields: Record<string, unknown> }> }>(
    `/api/docs/${docId}/tables`,
  );
  return (r.tables ?? []).map((t) => ({ id: t.id, name: t.id, fields: t.fields }));
}

export async function tableRecords(
  docId: string,
  tableId: string,
  limit = 5000,
): Promise<Array<{ id: number; fields: Record<string, unknown> }>> {
  // SQL endpoint is the simplest, consistent, and works for any table.
  const sql = `SELECT * FROM ${tableId} LIMIT ${Math.max(1, Math.min(limit, 20000))}`;
  return sqlRecords(docId, sql);
}

export async function sqlRecords(
  docId: string,
  sql: string,
): Promise<Array<{ id: number; fields: Record<string, unknown> }>> {
  const url = `${GRIST_URL}/api/docs/${docId}/sql?` + new URLSearchParams({ q: sql });
  const rr = await fetch(url, { headers: HEADERS, cache: 'no-store' });
  if (!rr.ok) throw new Error(`Grist SQL ${rr.status}: ${(await rr.text()).slice(0, 500)}`);
  const data = (await rr.json()) as {
    records?: Array<{ id: number; fields: Record<string, unknown> }>;
  };
  return data.records ?? [];
}

export async function tableColumns(
  docId: string,
  tableId: string,
): Promise<Array<{ id: string; label: string; type: string }>> {
  // Grist doesn't expose column metadata in a single endpoint, but
  // the first record's `fields` keys + their types are a reasonable
  // approximation for table display.
  const rows = await tableRecords(docId, tableId, 1);
  if (rows.length === 0) return [];
  // Drop Grist's reserved / internal columns that have no meaning for
  // a user-facing table.
  const RESERVED = new Set(['id', 'manualSort']);
  return Object.entries(rows[0].fields ?? {})
    .filter(([id]) => !RESERVED.has(id))
    .map(([id, v]) => ({
      id,
      label: id,
      type: typeof v === 'number' ? 'Numeric' : typeof v,
    }));
}

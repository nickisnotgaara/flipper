"use client";

import { useEffect, useState } from "react";

// /grist — UI-обёртка над Grist API.
//
// Grist 1.7.17 в single-org mode имеет баг URL-routing, из-за которого
// клик по документу в Grist-UI кидает на 404. Эта страница обходит баг:
// читает данные через /api/grist/* (FastAPI proxy → Grist SQL API) и
// показывает их как нормальную таблицу с пагинацией.

type GristTable = { id: string; rows: number | null; fields_count: number };
type GristTablesResp = {
  doc_id: string;
  grist_base: string;
  tables: GristTable[];
  error?: string;
  reason?: string;
};

type GristColumn = { id: string; label?: string; type?: string };
type GristColumnsResp = {
  table_id: string;
  columns: GristColumn[];
  error?: string;
};

type GristRecord = { id: number; fields: Record<string, any> };
type GristTableResp = {
  table_id: string;
  records: GristRecord[];
  count: number;
  error?: string;
};

type GristSqlResp = {
  records?: GristRecord[];
  error?: string;
  reason?: string;
};

const API = (() => {
  if (typeof window === "undefined") return "";
  // Same host that served the page; FastAPI is at :8000 (api) or :8001 (host)
  const port = window.location.port === "3000" ? "8001" : window.location.port;
  return `${window.location.protocol}//${window.location.hostname}:${port}`;
})();

function fmtCell(v: any): string {
  if (v == null) return "";
  if (typeof v === "object") return JSON.stringify(v);
  const s = String(v);
  return s.length > 80 ? s.slice(0, 80) + "…" : s;
}

function Cell({ value }: { value: any }) {
  return (
    <td className="px-3 py-2 text-sm border-b border-[var(--paper-2)] align-top max-w-[280px] truncate">
      <span title={typeof value === "object" ? JSON.stringify(value) : String(value ?? "")}>
        {fmtCell(value)}
      </span>
    </td>
  );
}

export default function GristPage() {
  const [tables, setTables] = useState<GristTablesResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [columns, setColumns] = useState<GristColumnsResp | null>(null);
  const [rows, setRows] = useState<GristTableResp | null>(null);
  const [pageLimit, setPageLimit] = useState(50);
  const [sql, setSql] = useState("SELECT * FROM FILTERS LIMIT 50");
  const [sqlResult, setSqlResult] = useState<GristSqlResp | null>(null);
  const [sqlBusy, setSqlBusy] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/api/grist/tables`)
      .then((r) => r.json())
      .then((d) => {
        setTables(d);
        setLoading(false);
      })
      .catch((e) => {
        setTables({ doc_id: "?", grist_base: "?", tables: [], error: String(e) });
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    if (!selected) return;
    setRows(null);
    setColumns(null);
    Promise.all([
      fetch(`${API}/api/grist/columns/${encodeURIComponent(selected)}`).then((r) => r.json()),
      fetch(`${API}/api/grist/table/${encodeURIComponent(selected)}?limit=${pageLimit}`).then(
        (r) => r.json()
      ),
    ]).then(([c, t]) => {
      setColumns(c);
      setRows(t);
    });
  }, [selected, pageLimit]);

  const runSql = async () => {
    setSqlBusy(true);
    setSqlResult(null);
    try {
      const r = await fetch(`${API}/api/grist/sql`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sql }),
      });
      const d = await r.json();
      setSqlResult(d);
    } catch (e: any) {
      setSqlResult({ error: "network", reason: String(e) });
    }
    setSqlBusy(false);
  };

  const totalRows = tables?.tables?.reduce((acc, t) => acc + (t.rows ?? 0), 0) ?? 0;
  const populated = tables?.tables?.filter((t) => (t.rows ?? 0) > 0) ?? [];

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Grist Viewer</h1>
          <p className="text-sm text-[var(--ink-3)] mt-1">
            Read-only обёртка над Grist API. Grist UI имеет баг routing в single-org mode 1.7.17
            (404 при клике на документ), поэтому читаем данные через{" "}
            <code className="px-1.5 py-0.5 rounded bg-[var(--paper-2)]">/api/grist/*</code> и
            рендерим тут.
          </p>
        </div>
        <div className="text-right text-xs text-[var(--ink-3)] space-y-1">
          {tables?.grist_base && <div>Grist: <code>{tables.grist_base}</code></div>}
          {tables?.doc_id && <div>Doc: <code>{tables.doc_id.slice(0, 12)}…</code></div>}
          <a
            href={`${tables?.grist_base || "http://217.149.23.102:8484"}/o/flipper/${tables?.doc_id || "em6piHbbtWXq3oyLYRahnd"}/p/1`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block mt-1 text-blue-600 hover:underline"
          >
            Open in Grist UI ↗
          </a>
        </div>
      </header>

      {/* Tables list */}
      <section>
        <h2 className="text-lg font-medium mb-3">
          Таблицы{" "}
          <span className="text-sm font-normal text-[var(--ink-3)]">
            ({populated.length} непустых, {totalRows.toLocaleString("ru")} строк всего)
          </span>
        </h2>
        {loading && <div className="text-sm text-[var(--ink-3)]">Загружаю…</div>}
        {tables?.error && (
          <div className="p-3 rounded border border-red-300 bg-red-50 text-sm text-red-800">
            Grist недоступен: {tables.reason ?? tables.error}
            <br />
            Проверь <code>GRIST_BASE_URL</code> и что контейнер <code>flipper_grist</code> запущен.
          </div>
        )}
        {tables && !tables.error && (
          <div className="overflow-x-auto rounded border border-[var(--paper-2)]">
            <table className="min-w-full text-sm">
              <thead className="bg-[var(--paper-2)]">
                <tr>
                  <th className="text-left px-3 py-2 font-medium">Имя таблицы</th>
                  <th className="text-right px-3 py-2 font-medium">Строк</th>
                  <th className="text-right px-3 py-2 font-medium">Колонок</th>
                </tr>
              </thead>
              <tbody>
                {tables.tables.map((t) => (
                  <tr
                    key={t.id}
                    onClick={() => setSelected(t.id)}
                    className={
                      "cursor-pointer hover:bg-[var(--paper-2)] " +
                      (selected === t.id ? "bg-[var(--paper-2)]" : "")
                    }
                  >
                    <td className="px-3 py-2 font-mono">
                      {t.id}{" "}
                      {(t.rows ?? 0) === 0 && (
                        <span className="ml-1 text-xs text-[var(--ink-3)]">(пустая)</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {(t.rows ?? "—").toLocaleString("ru")}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-[var(--ink-3)]">
                      {t.fields_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Table viewer */}
      {selected && (
        <section>
          <div className="flex items-end justify-between mb-3">
            <h2 className="text-lg font-medium">
              <code className="font-mono">{selected}</code>
            </h2>
            <div className="flex gap-2 items-center text-sm">
              <label>
                Лимит:{" "}
                <select
                  value={pageLimit}
                  onChange={(e) => setPageLimit(Number(e.target.value))}
                  className="border rounded px-2 py-1 bg-[var(--paper)]"
                >
                  <option value={20}>20</option>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                  <option value={200}>200</option>
                </select>
              </label>
              <button
                onClick={() => setSelected(null)}
                className="px-3 py-1 rounded border border-[var(--paper-2)] hover:bg-[var(--paper-2)]"
              >
                Закрыть
              </button>
            </div>
          </div>
          {rows?.error && (
            <div className="p-3 rounded border border-red-300 bg-red-50 text-sm text-red-800">
              Ошибка: {rows.error}
            </div>
          )}
          {rows && !rows.error && (
            <div className="overflow-x-auto rounded border border-[var(--paper-2)]">
              <table className="min-w-full text-sm">
                <thead className="bg-[var(--paper-2)]">
                  <tr>
                    {(columns?.columns ?? []).map((c) => (
                      <th key={c.id} className="text-left px-3 py-2 font-medium whitespace-nowrap">
                        <div>{c.label || c.id}</div>
                        <div className="text-[10px] text-[var(--ink-3)] font-mono">
                          {c.type} · {c.id}
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.records.map((r) => (
                    <tr key={r.id} className="hover:bg-[var(--paper-2)]">
                      {(columns?.columns ?? []).map((c) => (
                        <Cell key={c.id} value={r.fields?.[c.id] ?? r.fields?.[c.label ?? ""]} />
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {rows.records.length === 0 && (
                <div className="text-sm text-[var(--ink-3)] p-4 text-center">Нет строк</div>
              )}
            </div>
          )}
        </section>
      )}

      {/* SQL runner */}
      <section>
        <h2 className="text-lg font-medium mb-3">SQL (только SELECT)</h2>
        <div className="flex gap-2">
          <textarea
            value={sql}
            onChange={(e) => setSql(e.target.value)}
            rows={3}
            className="flex-1 font-mono text-xs p-2 rounded border border-[var(--paper-2)] bg-[var(--paper)]"
            spellCheck={false}
          />
          <button
            onClick={runSql}
            disabled={sqlBusy}
            className="px-4 py-2 rounded bg-blue-600 text-white text-sm font-medium disabled:opacity-50 self-start"
          >
            {sqlBusy ? "…" : "Выполнить"}
          </button>
        </div>
        {sqlResult?.error && (
          <div className="mt-2 p-3 rounded border border-red-300 bg-red-50 text-sm text-red-800">
            {sqlResult.error}: {sqlResult.reason}
          </div>
        )}
        {sqlResult?.records && sqlResult.records.length > 0 && (
          <div className="mt-3 overflow-x-auto rounded border border-[var(--paper-2)]">
            <table className="min-w-full text-sm">
              <thead className="bg-[var(--paper-2)]">
                <tr>
                  {Object.keys(sqlResult.records[0].fields ?? {}).map((k) => (
                    <th key={k} className="text-left px-3 py-2 font-medium">
                      {k}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sqlResult.records.map((r, i) => (
                  <tr key={r.id ?? i} className="hover:bg-[var(--paper-2)]">
                    {Object.entries(r.fields ?? {}).map(([k, v]) => (
                      <Cell key={k} value={v} />
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {sqlResult?.records && sqlResult.records.length === 0 && (
          <div className="mt-2 text-sm text-[var(--ink-3)]">0 строк</div>
        )}
      </section>
    </div>
  );
}

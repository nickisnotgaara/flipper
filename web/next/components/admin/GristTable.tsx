'use client';

// GristTable — TanStack Table view of a Grist document's data.
// Server pre-fetches the rows (via lib/grist.ts) and passes them in.

import { useMemo, useState } from 'react';
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import Link from 'next/link';

type Row = { id: number; fields: Record<string, unknown> };

type Col = { id: string; label: string; type: string };

function fmtCell(v: unknown): string {
  if (v === null || v === undefined) return '';
  if (typeof v === 'number') {
    if (Number.isInteger(v)) return v.toLocaleString('ru-RU');
    return v.toLocaleString('ru-RU', { maximumFractionDigits: 2 });
  }
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

function isUrl(v: unknown): v is string {
  return typeof v === 'string' && /^https?:\/\//.test(v);
}

export default function GristTable({
  docId,
  tableId,
  columns,
  rows,
  allTables,
}: {
  docId: string;
  tableId: string;
  columns: Col[];
  rows: Row[];
  allTables: Array<{ id: string; label: string }>;
}) {
  const [globalFilter, setGlobalFilter] = useState('');

  // tableId у нас часто Table1, Table2…; показываем display name если есть.
  const displayName = useMemo(
    () => allTables.find((t) => t.id === tableId)?.label ?? tableId,
    [allTables, tableId],
  );

  const cols = useMemo<ColumnDef<Row>[]>(() => {
    return [
      { id: '__id', accessorFn: (r) => r.id, header: 'id', cell: (info) => info.getValue<number>() },
      ...columns.map<ColumnDef<Row>>((c) => ({
        id: c.id,
        accessorFn: (r) => r.fields[c.id],
        header: c.label,
        cell: (info) => {
          const v = info.getValue();
          if (isUrl(v)) {
            return (
              <a
                href={v}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[var(--accent)] hover:underline"
              >
                {fmtCell(v).slice(0, 50)}
                {v.length > 50 ? '…' : ''}
              </a>
            );
          }
          return <span className="tabular-nums">{fmtCell(v)}</span>;
        },
      })),
    ];
  }, [columns]);

  const table = useReactTable({
    data: rows,
    columns: cols,
    state: { globalFilter },
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 100 } },
  });

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Table header bar: table picker + search + counts */}
      <div className="flex items-center justify-between border-b border-[var(--rule)] bg-[var(--paper-card)] px-4 py-2">
        <div className="flex items-center gap-2">
          <label className="text-[12px] text-[var(--ink-mute)]">Таблица:</label>
          <select
            value={tableId}
            onChange={(e) => {
              const url = new URL(window.location.href);
              url.searchParams.set('table', e.target.value);
              window.location.href = url.toString();
            }}
            className="rounded border border-[var(--rule)] bg-[var(--paper)] px-2 py-1 text-[12px] text-[var(--ink)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
          >
            {allTables.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
                {t.label !== t.id ? ` · ${t.id}` : ''}
              </option>
            ))}
          </select>
          <span className="ml-2 rounded bg-[var(--paper-mute)] px-2 py-0.5 font-mono text-[10px] text-[var(--ink-mute)]">
            {displayName}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
            placeholder="Поиск…"
            className="rounded border border-[var(--rule)] bg-[var(--paper)] px-2 py-1 text-[12px] text-[var(--ink)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
          />
          <span className="text-[11px] text-[var(--ink-faint)] tabular-nums">
            {table.getFilteredRowModel().rows.length} строк
            {globalFilter ? ` (filtered from ${rows.length})` : ''}
          </span>
        </div>
      </div>

      {/* Table body */}
      <div className="flex-1 overflow-auto">
        {rows.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-[var(--ink-mute)]">
            Нет данных в таблице <span className="ml-1 font-mono">{tableId}</span>
          </div>
        ) : (
          <table className="w-full border-collapse text-[12.5px]">
            <thead className="sticky top-0 z-10 bg-[var(--paper-card)]">
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id} className="border-b border-[var(--rule)]">
                  {hg.headers.map((h) => (
                    <th
                      key={h.id}
                      onClick={h.column.getToggleSortingHandler()}
                      className="cursor-pointer select-none px-2 py-1.5 text-left font-medium text-[var(--ink-soft)]"
                    >
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      {h.column.getIsSorted() === 'asc' && ' ▲'}
                      {h.column.getIsSorted() === 'desc' && ' ▼'}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr key={row.id} className="border-b border-[var(--rule-soft)] hover:bg-[var(--paper-2)]">
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-2 py-1 align-top text-[var(--ink)]">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {rows.length > 100 && (
        <div className="flex items-center justify-between border-t border-[var(--rule)] bg-[var(--paper-card)] px-4 py-2 text-[11.5px] text-[var(--ink-mute)]">
          <div>
            Страница {table.getState().pagination.pageIndex + 1} из{' '}
            {table.getPageCount()} ({table.getFilteredRowModel().rows.length} строк)
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => table.setPageIndex(0)}
              disabled={!table.getCanPreviousPage()}
              className="rounded border border-[var(--rule)] px-2 py-0.5 disabled:opacity-30"
            >
              «
            </button>
            <button
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
              className="rounded border border-[var(--rule)] px-2 py-0.5 disabled:opacity-30"
            >
              ‹
            </button>
            <button
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
              className="rounded border border-[var(--rule)] px-2 py-0.5 disabled:opacity-30"
            >
              ›
            </button>
            <button
              onClick={() => table.setPageIndex(table.getPageCount() - 1)}
              disabled={!table.getCanNextPage()}
              className="rounded border border-[var(--rule)] px-2 py-0.5 disabled:opacity-30"
            >
              »
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

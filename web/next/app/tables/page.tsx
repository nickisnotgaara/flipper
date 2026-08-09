'use client';

/**
 * /tables — Univer-backed Google-Sheets-style workbook.
 *
 * The actual spreadsheet engine is in `FlipperWorkbook.tsx`. This file is
 * a thin wrapper that lazy-loads it client-side only (`ssr: false` is
 * mandatory — Univer touches `window`/`document` at init time and would
 * crash during server rendering).
 *
 * `?tab=X` URL state is owned by FlipperWorkbook itself; the sidebar
 * links point at `/tables?tab=active` etc. for deep-linking.
 */

import dynamic from 'next/dynamic';

const FlipperWorkbook = dynamic(
  () => import('@/components/admin/FlipperWorkbook'),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-screen w-screen items-center justify-center text-sm text-[var(--ink-mute)]">
        Загружаю таблицу…
      </div>
    ),
  },
);

export default function TablesPage() {
  return <FlipperWorkbook />;
}

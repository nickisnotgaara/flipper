'use client';

import { useCallback, useMemo } from 'react';
import { useRouter, useSearchParams, usePathname } from 'next/navigation';
import DataTable, { type DataTableProps } from '@/components/admin/DataTable';
import SheetTabs, { type SheetTab } from '@/components/admin/SheetTabs';
import type { ColumnDef } from '@tanstack/react-table';
import type { FilterDef } from '@/components/admin/FilterPanel';
import {
  activeColumns,
  activeFilters,
  ACTIVE_TOTAL,
} from './_sheets/active';
import {
  soldColumns,
  soldFilters,
  SOLD_TOTAL,
} from './_sheets/sold';
import {
  hiddenColumns,
  hiddenFilters,
  HIDDEN_TOTAL,
} from './_sheets/hidden';
import {
  housesColumns,
  housesFilters,
  HOUSES_TOTAL,
} from './_sheets/houses';

// ---- Sheet registry ----------------------------------------------
// One tab = one data source. Column/filter defs live in _sheets/* so
// they can be imported cleanly and re-used by any future per-tab
// subroute (e.g. /tables/active for a deep link).

type SheetId = 'active' | 'sold' | 'hidden' | 'houses';

type Sheet = {
  id: SheetId;
  label: string;
  count?: number;
  columns: ColumnDef<any, any>[];
  filters?: FilterDef[];
  initialSort?: DataTableProps<any>['initialSort'];
  totalLabel: string;
  rowHref?: DataTableProps<any>['rowHref'];
};

const SHEETS: Sheet[] = [
  {
    id: 'active',
    label: 'Активные',
    count: ACTIVE_TOTAL,
    columns: activeColumns as unknown as ColumnDef<any, any>[],
    filters: activeFilters,
    initialSort: [{ id: 'price_per_m2', desc: false }],
    totalLabel: 'объявлений',
    rowHref: (row: any) => row.url || null,
  },
  {
    id: 'sold',
    label: 'Снято',
    count: SOLD_TOTAL,
    columns: soldColumns as unknown as ColumnDef<any, any>[],
    filters: soldFilters,
    initialSort: [{ id: 'sold_date', desc: true }],
    totalLabel: 'сделок',
    rowHref: (row: any) => row.url || null,
  },
  {
    id: 'hidden',
    label: 'Скрытые',
    count: HIDDEN_TOTAL,
    columns: hiddenColumns as unknown as ColumnDef<any, any>[],
    filters: hiddenFilters,
    initialSort: [{ id: 'sold_date', desc: true }],
    totalLabel: 'скрытых',
    rowHref: (row: any) => row.url || null,
  },
  {
    id: 'houses',
    label: 'Дома',
    count: HOUSES_TOTAL,
    columns: housesColumns as unknown as ColumnDef<any, any>[],
    filters: housesFilters,
    initialSort: [{ id: 'active_count', desc: true }],
    totalLabel: 'домов',
  },
];

// Sheet tab strip data (separate from SHEETS so the bottom strip can
// be rendered in one pass and the type stays narrow).
const TABS: SheetTab[] = SHEETS.map((s) => ({ id: s.id, label: s.label, count: s.count }));

const VALID_TAB_IDS = new Set<SheetId>(['active', 'sold', 'hidden', 'houses']);

function normalizeTab(raw: string | null | undefined): SheetId {
  if (raw && VALID_TAB_IDS.has(raw as SheetId)) return raw as SheetId;
  return 'active';
}

export default function TablesPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Tab state is owned by the URL (?tab=...) so deep-links, reloads
  // and back/forward all work the way the user expects. We default
  // to 'active' when the param is missing or unknown.
  const tab = normalizeTab(searchParams.get('tab'));
  const current = useMemo(() => SHEETS.find((s) => s.id === tab) ?? SHEETS[0], [tab]);

  const setTab = useCallback(
    (id: string) => {
      const next = normalizeTab(id);
      const sp = new URLSearchParams(searchParams.toString());
      if (next === 'active') sp.delete('tab');
      else sp.set('tab', next);
      const qs = sp.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname, searchParams],
  );

  // Workbook footer: "X строк · 4 листа" sits on the right of the
  // tab strip. Kept here (not inside SheetTabs) so we don't have to
  // pass numbers down through props.
  const totalAll = useMemo(
    () => SHEETS.reduce((s, sh) => s + (sh.count ?? 0), 0),
    [],
  );

  return (
    <div className="h-screen w-screen flex flex-col bg-[var(--paper-2)] overflow-hidden">
      {/* ===== Formula bar / workbook header =======================
          Thin 40px row that mimics Google Sheets' formula bar: a
          "back to dashboard" link, a breadcrumb-style "Таблицы /
          {active sheet label}", and a count on the right. Sits at
          the very top so the sheet content has the rest of the
          viewport. */}
      <div className="flex items-center gap-3 px-4 h-10 bg-[var(--paper-card)] border-b border-[var(--rule)] shrink-0">
        <a
          href="/dashboard"
          className="text-[12.5px] text-[var(--ink-mute)] hover:text-[var(--ink)] transition-colors"
        >
          ← В панель
        </a>
        <span className="text-[12px] text-[var(--ink-faint)]">/</span>
        <span className="text-[13px] text-[var(--ink)] font-medium">Таблицы</span>
        <span className="text-[12px] text-[var(--ink-faint)]">/</span>
        <span className="text-[13px] text-[var(--ink-soft)]">{current.label}</span>

        <div className="flex-1" />

        <span className="text-[11.5px] text-[var(--ink-faint)] font-mono tabular-nums">
          {totalAll.toLocaleString('ru-RU')} строк · {SHEETS.length} листа
        </span>
      </div>

      {/* ===== Active sheet content ================================
          We mount ONLY the active sheet's DataTable (not all 4
          inside a hidden div). Switching tabs unmounts/remounts via
          `key={tab}` so virtualizer, sort, filter, scroll, and
          selection all reset per sheet — same model as Google
          Sheets where each tab is its own DOM tree. */}
      <div className="flex-1 min-h-0 overflow-hidden p-0">
        <DataTable
          key={current.id}
          name={current.id}
          columns={current.columns as any}
          filters={current.filters}
          initialSort={current.initialSort}
          totalLabel={current.totalLabel}
          rowHref={current.rowHref}
          chrome="excel"
        />
      </div>

      {/* ===== Sheet tab strip (BOTTOM) =============================
          The signature Excel/Sheets piece. Active tab "pops up" from
          the strip, inactive tabs sit half a pixel lower. Tab state
          is owned by the URL — see setTab() above. */}
      <SheetTabs
        sheets={TABS}
        selected={tab}
        onSelect={setTab}
      />
    </div>
  );
}

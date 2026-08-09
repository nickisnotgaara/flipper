'use client';

/**
 * FlipperWorkbook — real Google-Sheets look for the /tables route.
 *
 * Built on Univer (Apache-2.0, Canvas2D renderer, multi-sheet tabs, formula
 * bar, A1 cell ref, F2/Enter/Ctrl+C/V — all out of the box).
 *
 * Architecture:
 *  - One Univer instance, one workbook, 7 sheets (one per tab).
 *  - Sheet creation is lazy: we only create the active sheet on mount and
 *    create the rest on first click. Keeps initial payload small.
 *  - On `SheetEditEnded` (isConfirm=true) we look up the PK in column A of
 *    the edited row, then PATCH /api/tables/{name}/rows/{pk} with the new
 *    value. The cell value is read directly from the worksheet.
 *  - Tab UI (bottom strip) is plain React so we can keep `?tab=X` URL
 *    state and the visual style consistent with the rest of the admin
 *    panel; Univer's built-in sheet bar is hidden in favour of ours.
 *
 * Russian locale is loaded via `mergeLocales([sheetsCoreRuRU])` so all
 * chrome text (File/Edit/Insert/Format/Data) shows in Russian.
 */

import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { useRouter, useSearchParams, usePathname } from 'next/navigation';
import {
  createUniver,
  defaultTheme,
  LocaleType,
  mergeLocales,
} from '@univerjs/presets';
import { UniverSheetsCorePreset } from '@univerjs/preset-sheets-core';
import sheetsCoreRuRU from '@univerjs/preset-sheets-core/locales/ru-RU';
import '@univerjs/preset-sheets-core/lib/index.css';

import type { FUniver, Univer } from '@univerjs/presets';
import type { CellValue, ICellData, IObjectMatrixPrimitiveType } from '@univerjs/presets';

import { API_BASE } from '@/lib/api';

// FWorkbook and FWorksheet are registered as a side-effect of
// `@univerjs/preset-sheets-core` (see its index.js — it imports
// `@univerjs/sheets/lib/facade`). They're not hoisted in our pnpm
// layout, so we use `any` for those runtime values and rely on
// Univer's IDE support in the sheets-ui playground for inline help.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyWorkbook = any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyWorksheet = any;

// ---- Tab registry ----------------------------------------------------------
// 7 tabs total. Each is a separate Univer sheet. `count` is loaded on mount
// (and revalidated in the background) and shown as a chip on the tab label.

export type TabId =
  | 'active'
  | 'sold'
  | 'hidden'
  | 'houses'
  | 'filters'
  | 'avans'
  | 'offers';

type Tab = {
  id: TabId;
  label: string;
  count?: number;
};

const TABS: Tab[] = [
  { id: 'active',  label: 'Активные' },
  { id: 'sold',    label: 'Снято' },
  { id: 'hidden',  label: 'Скрытые' },
  { id: 'houses',  label: 'Дома' },
  { id: 'filters', label: 'FILTERS' },
  { id: 'avans',   label: 'Аванс' },
  { id: 'offers',  label: 'Offers_Parser' },
];

const VALID_TAB_IDS = new Set<TabId>(TABS.map((t) => t.id));

function normalizeTab(raw: string | null | undefined): TabId {
  if (raw && VALID_TAB_IDS.has(raw as TabId)) return raw as TabId;
  return 'active';
}

const TAB_TO_SHEET_ID: Record<TabId, string> = {
  active:  'sheet-active',
  sold:    'sheet-sold',
  hidden:  'sheet-hidden',
  houses:  'sheet-houses',
  filters: 'sheet-filters',
  avans:   'sheet-avans',
  offers:  'sheet-offers',
};

// ---- API helpers -----------------------------------------------------------

type ColumnMeta = {
  key: string;
  label: string;
  type: 'number' | 'text' | 'date' | 'url';
  editable: boolean;
  width: number;
};

type TableResponse = {
  rows: Array<Record<string, unknown>>;
  total: number;
  columns: ColumnMeta[];
};

async function fetchTab(tab: TabId, pageSize = 1000): Promise<TableResponse> {
  const r = await fetch(
    `${API_BASE}/api/tables/${tab}?page=1&page_size=${pageSize}`,
  );
  if (!r.ok) throw new Error(`fetchTab ${tab} failed: ${r.status}`);
  return r.json();
}

async function patchCell(
  tab: TabId,
  rowPk: number,
  column: string,
  value: unknown,
): Promise<void> {
  const r = await fetch(`${API_BASE}/api/tables/${tab}/rows/${rowPk}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ [column]: value }),
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => '');
    throw new Error(`PATCH ${tab}/rows/${rowPk} → ${r.status}: ${detail}`);
  }
}

// ---- Cell-matrix adapter ---------------------------------------------------
// Univer's `IObjectMatrixPrimitiveType<ICellData>` is `{ [row: number]:
// { [col: number]: ICellData } }`. ICellData.v is Nullable<CellValue> which
// is `string | number | boolean | null | undefined` (not `unknown`).

// `columnData` per-column metadata — drives the actual column widths
// from the server-side `_TABLE_COLUMNS` definitions so the spreadsheet
// matches the rest of the admin panel (id narrow, URL wide, etc.).
// Univer uses `w` for width (IColumnData) and `hd` for hidden.
function buildColumnData(
  columns: ColumnMeta[],
): Record<number, { w: number; hd?: 0 | 1 }> {
  const out: Record<number, { w: number; hd?: 0 | 1 }> = {};
  for (let c = 0; c < columns.length; c++) {
    out[c] = { w: columns[c].width };
  }
  return out;
}

function rowsToCellData(
  rows: Array<Record<string, unknown>>,
  columns: ColumnMeta[],
): IObjectMatrixPrimitiveType<ICellData> {
  const cellData: IObjectMatrixPrimitiveType<ICellData> = {};
  // Row 0 = header row (column labels). Data rows start at index 1.
  // The worksheet is created with `freeze: { ySplit: 1 }` so the header
  // row stays visible while the user scrolls through the data.
  const headerRow: { [col: number]: ICellData } = {};
  for (let c = 0; c < columns.length; c++) {
    headerRow[c] = { v: columns[c].label, t: 4 /* force-string */ };
  }
  cellData[0] = headerRow;
  for (let r = 0; r < rows.length; r++) {
    const row = rows[r];
    const rowMap: { [col: number]: ICellData } = {};
    for (let c = 0; c < columns.length; c++) {
      const col = columns[c];
      const raw = row[col.key];
      if (raw === null || raw === undefined) continue;
      // Univer cell types:
      //   1 = string (auto-detect — Univer will try to interpret as formula
      //                or hyperlink; for URLs this fires the
      //                `sheets-ui.info.error` tooltip)
      //   2 = number
      //   3 = boolean
      //   4 = force-string (no auto-detection; safe for URLs and free text)
      let t: number | undefined;
      let v: CellValue;
      if (col.type === 'number') {
        t = 2;
        v = Number(raw) as CellValue;
      } else if (col.type === 'url') {
        // We keep URL as plain text; opening via click can be added later.
        // `t: 4` skips Univer's auto-hyperlink detection that otherwise
        // renders a broken-link badge + "sheets-ui.info.error" tooltip.
        t = 4;
        v = String(raw);
      } else {
        // Plain text columns — also force-string so dates and numeric-looking
        // strings (e.g. `1-к квартира 38.3 м²`) are not re-interpreted.
        t = 4;
        v = String(raw);
      }
      rowMap[c] = { v, t };
    }
    cellData[r + 1] = rowMap;
  }
  return cellData;
}

// ---- Component -------------------------------------------------------------

export default function FlipperWorkbook() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const tab = normalizeTab(searchParams.get('tab'));
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [ready, setReady] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  // Per-tab data cache so sort can re-render without re-fetching.
  const dataCacheRef = useRef<Record<string, { rows: Array<Record<string, unknown>>; columns: ColumnMeta[] }>>({});
  // Sort state: per-tab, by column key + direction. `null` = no sort.
  const [sortBy, setSortBy] = useState<{ column: string; dir: 'asc' | 'desc' } | null>(null);
  const [sortOpen, setSortOpen] = useState(false);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const univerRef = useRef<Univer | null>(null);
  const univerAPIRef = useRef<FUniver | null>(null);
  const workbookRef = useRef<AnyWorkbook | null>(null);
  // Per-sheet state cache. Each entry holds the column metadata so we can
  // map (row, col) → (pk, column_key) when an edit fires.
  const sheetMetaRef = useRef<
    Record<string, { columns: ColumnMeta[]; pkByRow: Map<number, number> }>
  >({});
  // We track the in-flight tab so concurrent setTab() calls don't race.
  const loadedSheetsRef = useRef<Set<string>>(new Set());

  // Tab switching — keep ?tab=X in URL for deep-link / back-button support.
  const setTab = (id: TabId) => {
    const next = normalizeTab(id);
    const sp = new URLSearchParams(searchParams.toString());
    if (next === 'active') sp.delete('tab');
    else sp.set('tab', next);
    const qs = sp.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };

  // 1. Mount Univer once.
  useEffect(() => {
    if (!containerRef.current) return;

    const { univer, univerAPI } = createUniver({
      locale: LocaleType.RU_RU,
      locales: { [LocaleType.RU_RU]: mergeLocales(sheetsCoreRuRU) },
      theme: defaultTheme,
      presets: [
        UniverSheetsCorePreset({
          container: containerRef.current,
          // Strip the heavy Office-style chrome — we render our own top bar
          // and our own bottom tab strip. What stays is the data grid +
          // column/row headers + a slim formula bar (A1 ref + value) — the
          // bare minimum that still reads as a spreadsheet.
          header: false,        // Hide the "Начало / Формулы / Данные" ribbon.
          toolbar: false,       // Hide the B/I/U/alignment toolbar.
          contextMenu: false,   // Hide right-click context menu.
          footer: false,        // Hide Univer's built-in bottom sheet bar.
          formulaBar: true,     // Keep A1 cell ref + value display.
        }),
      ],
    });
    univerRef.current = univer;
    univerAPIRef.current = univerAPI;
    setReady(true);

    // Force Univer to re-measure its container. The dynamic-import +
    // mount happens before the layout has settled, so the canvas can
    // latch onto the initial (smaller) container width and refuse to
    // grow. A resize event after a short delay (and another on
    // ResizeObserver changes) tells Univer to re-layout.
    const triggerResize = () => {
      window.dispatchEvent(new Event('resize'));
    };
    const resizeT = setTimeout(triggerResize, 50);
    const resizeT2 = setTimeout(triggerResize, 300);
    let ro: ResizeObserver | null = null;
    if (containerRef.current && typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(() => triggerResize());
      ro.observe(containerRef.current);
    }

    // 2. Edit hook — fires on SheetEditEnded with isConfirm=true (Enter / blur).
    // We always allow Univer's UI to commit the edit visually first, then
    // fire PATCH in the background. Failed PATCH shows a flash message.
    const disposable = univerAPI.addEvent(
      univerAPI.Event.SheetEditEnded,
      (params) => {
        const { worksheet, row, column, isConfirm } = params as {
          worksheet: AnyWorksheet;
          row: number;
          column: number;
          isConfirm: boolean;
        };
        if (!isConfirm) return;
        const sheetId = worksheet.getSheetId();
        const tabId = TABS.find((t) => TAB_TO_SHEET_ID[t.id] === sheetId)?.id;
        if (!tabId) return;

        const meta = sheetMetaRef.current[sheetId];
        if (!meta) return;
        const col = meta.columns[column];
        if (!col || !col.editable) return;

        const newValue = worksheet.getRange(row, column, 1, 1).getValue();
        // PK is column A (index 0) — that never moves in our schema.
        const pk = worksheet.getRange(row, 0, 1, 1).getValue();
        if (pk == null) return;
        const rowPk = Number(pk);

        // Cast: Univer returns `v` from getValue, which is the raw scalar.
        // For numbers we keep as number; for text we send as string.
        let v: unknown = newValue;
        if (col.type === 'number' && v !== '' && v !== null) v = Number(v);

        setStatusMsg(`Сохраняю ${col.label}…`);
        patchCell(tabId as TabId, rowPk, col.key, v)
          .then(() => {
            setStatusMsg(`✓ ${col.label} обновлено`);
            setTimeout(() => setStatusMsg(null), 1500);
          })
          .catch((err: Error) => {
            console.error('PATCH failed', err);
            setStatusMsg(`✗ Ошибка: ${err.message}`);
            setTimeout(() => setStatusMsg(null), 4000);
          });
      },
    );

    return () => {
      clearTimeout(resizeT);
      clearTimeout(resizeT2);
      if (ro) ro.disconnect();
      disposable.dispose();
      univer.dispose();
      univerRef.current = null;
      univerAPIRef.current = null;
      workbookRef.current = null;
      sheetMetaRef.current = {};
      loadedSheetsRef.current.clear();
    };
    // We intentionally mount Univer once and let setTab()/loadTab() drive
    // the rest. Adding deps here would tear down the entire workbook.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 2. When Univer is ready and the active tab changes, load (or switch to)
  // that tab's sheet. First load creates the workbook; subsequent loads
  // just call setActiveSheet() if the data is already in memory.
  useEffect(() => {
    if (!ready) return;
    // Switching tabs resets the sort — each tab has its own data and
    // remembering the previous sort key would be confusing.
    setSortBy(null);
    void loadTab(tab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, tab]);

  // Close the sort dropdown on outside click. The button uses
  // `data-sort-trigger` and the menu uses `role="menu"` so a single
  // delegated listener handles both.
  useEffect(() => {
    if (!sortOpen) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as HTMLElement | null;
      if (!t) return;
      if (t.closest('[data-sort-trigger]') || t.closest('[role="menu"]')) return;
      setSortOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [sortOpen]);

  async function loadTab(tabId: TabId) {
    const univerAPI = univerAPIRef.current;
    if (!univerAPI) return;
    const sheetId = TAB_TO_SHEET_ID[tabId];

    // If sheet not yet created, fetch the data and build it.
    if (!loadedSheetsRef.current.has(sheetId)) {
      try {
        setStatusMsg(`Загружаю ${TABS.find((t) => t.id === tabId)?.label}…`);
        const data = await fetchTab(tabId);
        // Cache the rows so the sort handler can re-render without a
        // server round-trip. We keep one snapshot per tab.
        dataCacheRef.current[tabId] = { rows: data.rows, columns: data.columns };
        const cellData = rowsToCellData(data.rows, data.columns);
        const columnCount = data.columns.length;
        const rowCount = data.rows.length;

        // Cache the columns for the edit hook. The PK-by-row map is keyed
        // by DATA row index (0-based, excluding the header), matching
        // the row position in `cellData` (which has the header at index 0).
        sheetMetaRef.current[sheetId] = {
          columns: data.columns,
          pkByRow: new Map(
            data.rows.map((r, i) => [i, Number(r.id ?? 0)]),
          ),
        };

        if (!workbookRef.current) {
          // First sheet — create the workbook.
          const wb = univerAPI.createWorkbook({
            id: 'flipper',
            name: 'flipper',
            appVersion: '0.25.1',
            locale: LocaleType.RU_RU,
            styles: {},
            sheetOrder: [sheetId],
            sheets: {
              [sheetId]: {
                id: sheetId,
                name: TABS.find((t) => t.id === tabId)?.label ?? tabId,
                tabColor: '',
                hidden: 0,
                freeze: { xSplit: 0, ySplit: 1, startColumn: 0, startRow: 1 },
                rowCount: Math.max(rowCount + 1, 30),
                columnCount: Math.max(columnCount, 5),
                zoomRatio: 1,
                scrollTop: 0,
                scrollLeft: 0,
                defaultColumnWidth: 88,
                defaultRowHeight: 22,
                mergeData: [],
                cellData,
                rowData: {},
                columnData: buildColumnData(data.columns),
                rowHeader: { width: 46, hidden: 0 },
                columnHeader: { height: 26, hidden: 0 },
                showGridlines: 1,
                rightToLeft: 0,
              },
            },
          });
          workbookRef.current = wb;
        } else {
          // Add a new sheet to the existing workbook. The `create()` API
          // auto-generates the internal sheet id; we read it from the
          // returned FWorksheet and use THAT for the meta cache so the
          // edit hook can find the column metadata for the new sheet.
          const newSheet = workbookRef.current.create(
            TABS.find((t) => t.id === tabId)?.label ?? tabId,
            Math.max(rowCount + 1, 30),
            Math.max(columnCount, 5),
            {
              sheet: {
                cellData,
                columnData: buildColumnData(data.columns),
                defaultColumnWidth: 88,
                defaultRowHeight: 22,
                rowHeader: { width: 46, hidden: 0 },
                columnHeader: { height: 26, hidden: 0 },
                freeze: { xSplit: 0, ySplit: 1, startColumn: 0, startRow: 1 },
              },
            },
          );
          // Re-key the meta cache to the actual Univer sheet id.
          if (newSheet && typeof newSheet.getSheetId === 'function') {
            const realId = newSheet.getSheetId();
            if (realId && realId !== sheetId) {
              sheetMetaRef.current[realId] = sheetMetaRef.current[sheetId];
              delete sheetMetaRef.current[sheetId];
            }
          }
        }

        loadedSheetsRef.current.add(sheetId);
        setCounts((c) => ({ ...c, [tabId]: data.total }));
        setStatusMsg(null);
      } catch (err) {
        console.error('loadTab failed', tabId, err);
        setStatusMsg(
          `✗ Не удалось загрузить ${TABS.find((t) => t.id === tabId)?.label}: ${(err as Error).message}`,
        );
        return;
      }
    }

    // Switch the visible sheet.
    const wb = workbookRef.current;
    if (!wb) return;
    const target = wb.getSheetBySheetId(sheetId);
    if (target) {
      // FUniver provides setActiveSheet via the workbook.
      try {
        // Univer sets active sheet by id via setCurrentTab? Actually the
        // public API uses `wb.getActiveSheet()` + a setActive command. The
        // safest path is to dispatch the `sheet.command.set-active-sheet`
        // command, but for now we use the FUniver shortcut if present.
        const anyWb = wb as any;
        if (typeof anyWb.setActiveSheet === 'function') {
          anyWb.setActiveSheet(target);
        } else if (typeof anyWb.activateSheet === 'function') {
          anyWb.activateSheet(target);
        }
      } catch (e) {
        console.warn('setActiveSheet failed', e);
      }
    }
  }

  // ---- Sort ----------------------------------------------------------------
  // Google-Sheets-style sort: pick a column and ASC / DESC, the data re-renders
  // in place. We sort on the client (rows are already cached per tab) and call
  // FRange.setValues() to write the new order back into Univer — no server
  // round-trip, the current tab is the only thing that needs re-rendering.
  const applySort = useCallback(
    (col: ColumnMeta | null, dir: 'asc' | 'desc' | null) => {
      const wb = workbookRef.current;
      if (!wb) return;
      const sheetId = TAB_TO_SHEET_ID[tab];
      const ws = wb.getSheetBySheetId(sheetId);
      if (!ws) return;
      const cached = dataCacheRef.current[tab];
      if (!cached) return;
      const { rows, columns } = cached;
      if (rows.length === 0) return;

      // Build a sorted copy of the rows. We never mutate the cached array.
      const sorted = rows.slice();
      if (col && dir) {
        const k = col.key;
        const numeric = col.type === 'number';
        const collator = new Intl.Collator('ru', { numeric: true, sensitivity: 'base' });
        sorted.sort((a, b) => {
          const av = a[k];
          const bv = b[k];
          if (av == null && bv == null) return 0;
          if (av == null) return 1;
          if (bv == null) return -1;
          let cmp: number;
          if (numeric) {
            cmp = Number(av) - Number(bv);
          } else {
            cmp = collator.compare(String(av), String(bv));
          }
          return dir === 'asc' ? cmp : -cmp;
        });
      }

      // Re-build the cell matrix from the sorted rows and write it back.
      // The header row (index 0) is left untouched; only data rows 1..N
      // are re-rendered.
      const matrix: Array<Array<CellValue | ICellData>> = [];
      for (let r = 0; r < sorted.length; r++) {
        const row = sorted[r];
        const rowMap: Array<CellValue | ICellData> = [];
        for (let c = 0; c < columns.length; c++) {
          const colMeta = columns[c];
          const raw = row[colMeta.key];
          if (raw === null || raw === undefined) {
            rowMap.push(null);
            continue;
          }
          if (colMeta.type === 'number') rowMap.push({ v: Number(raw) as CellValue, t: 2 });
          else rowMap.push({ v: String(raw), t: 4 });
        }
        matrix.push(rowMap);
      }
      try {
        // Row 1 is the first data row (row 0 is the header).
        const range = (ws as any).getRange(1, 0, sorted.length, columns.length);
        if (range && typeof range.setValues === 'function') {
          range.setValues(matrix);
        }
      } catch (e) {
        console.error('setValues after sort failed', e);
      }
    },
    [tab],
  );

  const setSortColumn = useCallback(
    (key: string) => {
      const cached = dataCacheRef.current[tab];
      if (!cached) return;
      const col = cached.columns.find((c) => c.key === key) ?? null;
      const dir: 'asc' | 'desc' =
        sortBy && sortBy.column === key ? (sortBy.dir === 'asc' ? 'desc' : 'asc') : 'asc';
      setSortBy(col ? { column: key, dir } : null);
      applySort(col, dir);
      setSortOpen(false);
    },
    [tab, sortBy, applySort],
  );

  const clearSort = useCallback(() => {
    setSortBy(null);
    applySort(null, null);
    setSortOpen(false);
  }, [applySort]);

  // Total across all tabs (used in the formula bar).
  const totalAll = useMemo(
    () => Object.values(counts).reduce((s, n) => s + (n || 0), 0),
    [counts],
  );
  const currentLabel = TABS.find((t) => t.id === tab)?.label ?? '';

  // Current tab's columns (used to build the sort dropdown). The data
  // cache may not exist yet on first mount — we just show nothing.
  const cachedCols = dataCacheRef.current[tab]?.columns ?? [];
  const sortCol = sortBy
    ? cachedCols.find((c) => c.key === sortBy.column) ?? null
    : null;
  const sortLabel = sortBy
    ? `${sortCol?.label ?? sortBy.column} ${sortBy.dir === 'asc' ? '↑' : '↓'}`
    : 'Сортировка';

  return (
    <div className="h-screen w-screen flex flex-col bg-[var(--paper-2)] overflow-hidden">
      {/* ===== Top bar =====================================================
          Slim. Back link to map (the only other primary view) + active tab
          name + total + a transient status message slot for save feedback
          + a sort dropdown that re-renders the current sheet client-side. */}
      <div className="flex items-center gap-3 px-4 h-9 bg-[var(--paper-card)] border-b border-[var(--rule)] shrink-0 text-[12.5px]">
        <a
          href="/map"
          className="text-[var(--ink-mute)] hover:text-[var(--ink)] transition-colors"
        >
          ← Карта
        </a>
        <span className="text-[var(--ink-faint)]">·</span>
        <span className="text-[var(--ink-soft)] font-medium">{currentLabel}</span>
        <div className="flex-1" />
        {statusMsg && (
          <span className="text-[var(--ink-mute)] font-mono">{statusMsg}</span>
        )}

        {/* Sort dropdown — Google-Sheets style: pick a column, click again
            to flip ASC/DESC. The popover is plain React (no external lib). */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setSortOpen((o) => !o)}
            className="flex items-center gap-1.5 rounded border border-[var(--rule)] bg-[var(--paper-2)] px-2 h-7 text-[var(--ink-soft)] hover:bg-[var(--paper-soft)] hover:text-[var(--ink)]"
            aria-haspopup="menu"
            aria-expanded={sortOpen}
            data-sort-trigger=""
          >
            <span className="text-[var(--ink-faint)]">↕</span>
            <span>{sortLabel}</span>
          </button>
          {sortOpen && (
            <div
              role="menu"
              className="absolute right-0 top-8 z-50 w-64 max-h-96 overflow-y-auto rounded-md border border-[var(--rule)] bg-[var(--paper-card)] py-1 text-[12.5px] shadow-lg"
            >
              {sortBy && (
                <button
                  type="button"
                  onClick={clearSort}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[var(--ink-mute)] hover:bg-[var(--paper-soft)] hover:text-[var(--ink)]"
                >
                  <span className="text-[var(--ink-faint)]">⊘</span>
                  <span>Без сортировки</span>
                </button>
              )}
              {sortBy && <div className="my-1 h-px bg-[var(--rule-soft)]" />}
              {cachedCols.map((c) => {
                const active = sortBy?.column === c.key;
                return (
                  <button
                    key={c.key}
                    type="button"
                    onClick={() => setSortColumn(c.key)}
                    className={
                      'flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors ' +
                      (active
                        ? 'bg-[var(--accent-soft)] text-[var(--accent-ink)]'
                        : 'text-[var(--ink)] hover:bg-[var(--paper-soft)]')
                    }
                  >
                    <span className="w-3 text-[var(--ink-faint)]">
                      {active ? (sortBy?.dir === 'asc' ? '↑' : '↓') : ''}
                    </span>
                    <span className="flex-1">{c.label}</span>
                    <span className="font-mono text-[10.5px] text-[var(--ink-faint)]">
                      {c.type === 'number' ? '123' : 'АЯ'}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <span className="text-[var(--ink-faint)] font-mono tabular-nums">
          {totalAll.toLocaleString('ru-RU')} строк
        </span>
      </div>

      {/* ===== Univer data grid ============================================
          Stripped chrome (ribbon / toolbar / context menu all off in the
          preset config above). What renders inside the container is just
          the cell grid + column/row headers + slim formula bar. */}
      <div
        ref={containerRef}
        className="univer-container flex-1 min-h-0 w-full"
        style={{ background: 'var(--paper-card)', width: '100%' }}
      />

      {/* ===== Bottom tab strip ============================================ */}
      <div
        className="flex items-end gap-0 px-2 h-9 bg-[var(--paper-2)] border-t border-[var(--rule)] shrink-0 overflow-x-auto"
        role="tablist"
      >
        {TABS.map((t) => {
          const active = t.id === tab;
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={active}
              onClick={() => setTab(t.id)}
              data-tab={t.id}
              className={
                'flex items-center gap-2 px-3 h-8 text-[12.5px] border border-[var(--rule)] ' +
                'rounded-t-md transition-colors ' +
                (active
                  ? 'bg-[var(--paper-card)] text-[var(--ink)] font-medium -mb-px border-b-0 z-10'
                  : 'bg-[var(--paper)] text-[var(--ink-mute)] hover:text-[var(--ink)] hover:bg-[var(--paper-soft)]')
              }
            >
              <span>{t.label}</span>
              {counts[t.id] != null && (
                <span
                  className={
                    'text-[10.5px] font-mono tabular-nums px-1.5 py-0.5 rounded ' +
                    (active
                      ? 'bg-[var(--accent-soft)] text-[var(--accent-ink)]'
                      : 'bg-[var(--paper-2)] text-[var(--ink-faint)]')
                  }
                >
                  {counts[t.id]!.toLocaleString('ru-RU')}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

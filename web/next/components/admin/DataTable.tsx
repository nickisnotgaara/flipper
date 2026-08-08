'use client';

import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import {
  Spinner,
  Button,
  Input,
  Checkbox,
  Tooltip,
  Kbd,
} from '@heroui/react';
import {
  ArrowUp,
  ArrowDown,
  ArrowUpDown,
  Search,
  X,
  Download,
  SlidersHorizontal,
  RefreshCcw,
  ExternalLink,
} from 'lucide-react';
import FilterPanel, { countActiveFilters, type FilterDef } from './FilterPanel';
import ActiveFilterChips from './ActiveFilterChips';
import ColumnVisibilityMenu from './ColumnVisibilityMenu';
import EmptyState from './EmptyState';
import EditableCell from './EditableCell';

// ----------------------------------------------------------------
// DataTable v4 — Google-Sheets style:
//  - infinite scroll (useInfiniteQuery + virtualizer)
//  - inline editable cells (columnDef.editable)
//  - optimistic updates via queryClient.setQueryData
//  - clean, no decoration, hero search, sienna accents only on focus / selection
// ----------------------------------------------------------------

const DEFAULT_API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000';

const PAGE_SIZE = 200;

// Editable column metadata. Add to a columnDef:
//   editable: { type: 'text' | 'integer' | 'select', options?, format? }
export type EditableMeta = {
  type: 'text' | 'integer' | 'select';
  options?: { value: string; label: string }[];
  /** Display formatter — turns raw DB value into a human string. */
  format?: (value: unknown) => string;
};

export type DataTableProps<T extends Record<string, any>> = {
  name: string;
  columns: ColumnDef<T, any>[];
  initialSort?: SortingState;
  filters?: FilterDef[];
  queryParams?: Record<string, string>;
  apiBase?: string;
  totalLabel?: string;
  rowHref?: (row: T) => string | null;
  idKey?: string;
};

type ApiPage<T> = {
  rows: T[];
  total: number;
  page: number;
  page_size: number;
  stats: { count: number; avg_price: number; avg_area: number };
};

// ---- Local mock fallback (so the UI works when API is down) ---------

const MOCK: Record<string, { rows: any[]; total: number }> = {
  active: {
    total: 5227,
    rows: [
      { id: 1, source: 'cian_active', external_id: '331354235', url: 'https://www.cian.ru/sale/flat/331354235/', price: 37000000, price_per_m2: 503401, area: 73.5, rooms: 3, floor_current: 5, floor_total: 9, district: 'Хамовники', okrug: 'ЦАО', metro_station: 'Парк Культуры', metro_walk_time: 8, renovation: 'Без ремонта', days_in_exposition: 4, title: '3-к квартира 73.5 м²', publish_date: '2026-08-05', filter_id: 2, house_id: 363094 },
      { id: 2, source: 'cian_active', external_id: '330424995', url: 'https://www.cian.ru/sale/flat/330424995/', price: 17300000, price_per_m2: 316270, area: 54.7, rooms: 2, floor_current: 7, floor_total: 14, district: 'Тверской', okrug: 'ЦАО', metro_station: 'Маяковская', metro_walk_time: 5, renovation: 'Косметический', days_in_exposition: 12, title: '2-к квартира 54.7 м²', publish_date: '2026-08-01', filter_id: 1, house_id: 363422 },
      { id: 3, source: 'avans', external_id: '294656832', url: 'https://www.cian.ru/sale/flat/294656832/', price: 22500000, price_per_m2: 345115, area: 65.2, rooms: 2, floor_current: 3, floor_total: 17, district: 'Пресненский', okrug: 'ЦАО', metro_station: 'Деловой Центр', metro_walk_time: 4, renovation: 'Евроремонт', days_in_exposition: 8, title: '2-к квартира 65.2 м²', publish_date: '2026-08-04', filter_id: 6, house_id: 366744 },
    ],
  },
};

function getMockData<T>(name: string): ApiPage<T> {
  const m = MOCK[name] || { rows: [], total: 0 };
  return {
    rows: m.rows as T[],
    total: m.total,
    page: 1,
    page_size: m.rows.length,
    stats: {
      count: m.total,
      avg_price: 0,
      avg_area: 0,
    },
  };
}

function formatNum(n: number, opts?: { decimals?: number }): string {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toLocaleString('ru-RU', {
    minimumFractionDigits: opts?.decimals ?? 0,
    maximumFractionDigits: opts?.decimals ?? 0,
  });
}

function formatPriceShort(n: number): string {
  if (n == null || Number.isNaN(n)) return '—';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)} млн`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)} тыс`;
  return String(Math.round(n));
}

// ----------------------------------------------------------------

export default function DataTable<T extends Record<string, any>>(props: DataTableProps<T>) {
  const {
    name,
    columns: userColumns,
    initialSort = [],
    filters = [],
    queryParams: initialParams = {},
    apiBase = DEFAULT_API_BASE,
    totalLabel = 'строк',
    rowHref,
    idKey = 'id',
  } = props;

  const queryClient = useQueryClient();

  const [params, setParams] = useState<Record<string, string>>(initialParams);
  const [sort, setSort] = useState<SortingState>(initialSort);
  const [selected, setSelected] = useState<Set<string | number>>(new Set());
  const [columnVisibility, setColumnVisibility] = useState<Record<string, boolean>>({});
  const [searchInput, setSearchInput] = useState(params.q || '');
  const [filterPanelOpen, setFilterPanelOpen] = useState(false);
  const [savingCells, setSavingCells] = useState<Set<string>>(new Set());

  // Debounce search → 250ms
  useEffect(() => {
    const t = setTimeout(() => {
      setParams((p) => {
        const next = { ...p };
        if (searchInput) next.q = searchInput;
        else delete next.q;
        return next;
      });
    }, 250);
    return () => clearTimeout(t);
  }, [searchInput]);

  // Sort + filter params as the query key (so they reset on change).
  const queryKey = useMemo(() => {
    const q: Record<string, string> = { ...params };
    if (sort.length) {
      q.sort = String(sort[0].id);
      q.order = sort[0].desc ? 'desc' : 'asc';
    }
    return ['table', name, q] as const;
  }, [name, params, sort]);

  // Infinite query
  const {
    data,
    isLoading,
    isFetching,
    isFetchingNextPage,
    fetchNextPage,
    hasNextPage,
    refetch,
  } = useInfiniteQuery({
    queryKey,
    initialPageParam: 1,
    queryFn: async ({ pageParam }) => {
      const flat: Record<string, string> = { ...params };
      if (sort.length) {
        flat.sort = String(sort[0].id);
        flat.order = sort[0].desc ? 'desc' : 'asc';
      }
      flat.page = String(pageParam);
      flat.page_size = String(PAGE_SIZE);
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(flat)) {
        if (v != null && v !== '') qs.set(k, v);
      }
      try {
        const r = await fetch(`${apiBase}/api/tables/${name}?${qs.toString()}`, {
          cache: 'no-store',
        });
        if (!r.ok) throw new Error(`API ${r.status}`);
        return (await r.json()) as ApiPage<T>;
      } catch {
        return getMockData<T>(name);
      }
    },
    getNextPageParam: (lastPage) => {
      const fetched = (lastPage.page - 1) * lastPage.page_size + lastPage.rows.length;
      return fetched < lastPage.total ? lastPage.page + 1 : undefined;
    },
    staleTime: 15_000,
  });

  // Flatten pages.
  const allRows: T[] = useMemo(() => {
    if (!data?.pages) return [];
    const out: T[] = [];
    for (const p of data.pages) {
      for (const r of p.rows) out.push(r);
    }
    return out;
  }, [data]);

  const total = data?.pages?.[0]?.total ?? 0;
  const stats = data?.pages?.[0]?.stats ?? { count: 0, avg_price: 0, avg_area: 0 };

  // Optimistic cell update — mutates the cached page that holds this row.
  const mutateCell = useCallback(
    (rowId: string | number, columnId: string, value: unknown) => {
      const key = `${rowId}:${columnId}`;
      setSavingCells((prev) => new Set(prev).add(key));
      queryClient.setQueryData<typeof data>(queryKey, (old) => {
        if (!old) return old;
        return {
          ...old,
          pages: old.pages.map((p) => ({
            ...p,
            rows: p.rows.map((r) =>
              String(r[idKey]) === String(rowId) ? { ...r, [columnId]: value } : r,
            ),
          })),
        };
      });
      // Clear saving flag after a tick — the actual network call lives in
      // EditableCell; here we just mark a small grace period for the spinner.
      setTimeout(() => {
        setSavingCells((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
      }, 800);
    },
    [queryClient, queryKey, idKey],
  );

  // Columns: prepend selection checkbox.
  const allColumns = useMemo<ColumnDef<T, any>[]>(() => {
    const selCol: ColumnDef<T, any> = {
      id: '__select',
      header: ({ table }) => (
        <Checkbox
          size="sm"
          aria-label="Выбрать все"
          isSelected={
            table.getRowModel().rows.length > 0 &&
            table.getRowModel().rows.every((r) => selected.has(r.original[idKey]))
          }
          isIndeterminate={
            table.getRowModel().rows.some((r) => selected.has(r.original[idKey])) &&
            !table.getRowModel().rows.every((r) => selected.has(r.original[idKey]))
          }
          onValueChange={(v) => {
            setSelected((prev) => {
              const next = new Set(prev);
              for (const r of table.getRowModel().rows) {
                const k = r.original[idKey];
                if (v) next.add(k);
                else next.delete(k);
              }
              return next;
            });
          }}
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          size="sm"
          aria-label="Выбрать строку"
          isSelected={selected.has(row.original[idKey])}
          onValueChange={(v) => {
            setSelected((prev) => {
              const next = new Set(prev);
              const k = row.original[idKey];
              if (v) next.add(k);
              else next.delete(k);
              return next;
            });
          }}
        />
      ),
      enableSorting: false,
      size: 36,
    };
    return [selCol, ...userColumns];
  }, [userColumns, selected, idKey]);

  const table = useReactTable<T>({
    data: allRows,
    columns: allColumns,
    state: {
      sorting: sort,
      columnVisibility: { ...columnVisibility, __select: true },
    },
    onSortingChange: setSort,
    manualSorting: true,
    manualFiltering: true,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row: any, idx) => String(row[idKey] ?? idx),
  });

  const parentRef = useRef<HTMLDivElement>(null);
  const rowHeight = 44;
  const virtualizer = useVirtualizer({
    count: allRows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => rowHeight,
    overscan: 12,
  });

  // Infinite scroll trigger: when the last virtual row is rendered, fetch more.
  const virtualItems = virtualizer.getVirtualItems();
  useEffect(() => {
    const last = virtualItems[virtualItems.length - 1];
    if (!last) return;
    if (last.index >= allRows.length - 8 && hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [virtualItems, allRows.length, hasNextPage, isFetchingNextPage, fetchNextPage]);

  const activeFilters = countActiveFilters(filters, params);
  const hasSearch = !!params.q;
  const hasAnyFilter = hasSearch || activeFilters > 0;
  const rowCount = allRows.length;

  const updateParam = useCallback((key: string, value: string | undefined) => {
    setParams((p) => {
      const next = { ...p };
      if (value == null || value === '') delete next[key];
      else next[key] = value;
      return next;
    });
  }, []);

  const resetAll = useCallback(() => {
    setParams({});
    setSearchInput('');
    setSort(initialSort);
  }, [initialSort]);

  const exportCSV = useCallback(() => {
    const qs = new URLSearchParams({ ...params, page_size: '100000', page: '1' });
    window.open(`${apiBase}/api/tables/${name}/export?${qs.toString()}`, '_blank');
  }, [apiBase, name, params]);

  // '/' focuses search
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (
        e.key === '/' &&
        document.activeElement?.tagName !== 'INPUT' &&
        document.activeElement?.tagName !== 'TEXTAREA'
      ) {
        e.preventDefault();
        const el = document.getElementById('dt-search-input') as HTMLInputElement | null;
        el?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const selectedRows = useMemo(() => {
    if (selected.size === 0) return [];
    return allRows.filter((r: any) => selected.has(r[idKey]));
  }, [allRows, selected, idKey]);

  return (
    <div className="flex flex-col gap-3">
      {/* ========== Hero search + filter row ========== */}
      <div className="flex items-center gap-2 flex-wrap">
        <Input
          id="dt-search-input"
          value={searchInput}
          onValueChange={setSearchInput}
          placeholder="Поиск по адресу, ID, району…"
          size="md"
          variant="bordered"
          radius="sm"
          startContent={<Search size={16} className="text-[var(--ink-mute)]" strokeWidth={2} />}
          endContent={
            searchInput ? (
              <Button
                isIconOnly
                size="sm"
                radius="full"
                variant="light"
                onPress={() => setSearchInput('')}
                aria-label="Очистить"
                className="!w-6 !h-6 !min-w-6 !text-[var(--ink-mute)] data-[hover=true]:!bg-[var(--paper-2)]"
              >
                <X size={13} />
              </Button>
            ) : (
              <Kbd className="hidden md:inline-flex">/</Kbd>
            )
          }
          classNames={{
            base: 'flex-1 min-w-[260px]',
            mainWrapper: '!h-10',
            inputWrapper:
              '!h-10 !bg-[var(--paper-card)] data-[hover=true]:!bg-[var(--paper-card)] group-data-[focus=true]:!bg-[var(--paper-card)]',
            input: '!text-[14px] placeholder:!text-[var(--ink-faint)]',
          }}
        />

        <Button
          size="md"
          variant={activeFilters > 0 ? 'solid' : 'bordered'}
          color={activeFilters > 0 ? 'primary' : 'default'}
          startContent={<SlidersHorizontal size={14} strokeWidth={2} />}
          onPress={() => setFilterPanelOpen(true)}
        >
          Фильтры
          {activeFilters > 0 && (
            <span className="ml-1 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 bg-white/20 text-[11px] font-semibold rounded-full tabular-nums">
              {activeFilters}
            </span>
          )}
        </Button>

        <Tooltip content="Обновить" placement="bottom">
          <Button
            isIconOnly
            size="md"
            variant="bordered"
            onPress={() => refetch()}
            isDisabled={isFetching && !isLoading}
            aria-label="Обновить"
          >
            <RefreshCcw size={14} strokeWidth={2} className={isFetching ? 'animate-spin' : ''} />
          </Button>
        </Tooltip>

        <ColumnVisibilityMenu
          columns={userColumns}
          visible={columnVisibility}
          onChange={setColumnVisibility}
        />

        <Tooltip content="Export CSV" placement="bottom">
          <Button
            isIconOnly
            size="md"
            variant="bordered"
            onPress={exportCSV}
            aria-label="Export"
          >
            <Download size={14} strokeWidth={2} />
          </Button>
        </Tooltip>
      </div>

      {/* ========== Active filter chips + stats ========== */}
      <div className="flex items-center gap-3 flex-wrap min-h-[28px] text-[12.5px] text-[var(--ink-mute)]">
        <ActiveFilterChips
          filters={filters}
          params={params}
          onChange={updateParam}
          onReset={resetAll}
        />
        <span className="flex-1" />
        <span className="tabular-nums">
          Найдено{' '}
          <span className="font-semibold text-[var(--ink)]">{formatNum(total)}</span>{' '}
          {totalLabel}
        </span>
        {stats.avg_price > 0 ? (
          <>
            <span className="text-[var(--ink-faint)]">·</span>
            <span>
              ср.{' '}
              <span className="font-mono tabular-nums text-[var(--ink)]">
                {formatPriceShort(stats.avg_price)}
              </span>
            </span>
          </>
        ) : null}
        {stats.avg_area > 0 ? (
          <>
            <span className="text-[var(--ink-faint)]">·</span>
            <span>
              <span className="font-mono tabular-nums text-[var(--ink)]">
                {Math.round(stats.avg_area)}
              </span>{' '}
              м²
            </span>
          </>
        ) : null}
        {rowCount > 0 && hasNextPage ? (
          <span className="text-[var(--ink-faint)] tabular-nums">
            показано {rowCount}
          </span>
        ) : null}
      </div>

      {/* ========== Table ========== */}
      <div className="bg-[var(--paper-card)] border border-[var(--rule)] rounded-lg overflow-hidden">
        <div
          className="overflow-auto"
          style={{ height: 'calc(100vh - 270px)' }}
          ref={parentRef}
        >
          <table className="w-full text-[13px] border-collapse">
            <thead className="sticky top-0 z-10">
              {table.getHeaderGroups().map((hg) => (
                <tr
                  key={hg.id}
                  className="bg-[var(--paper-2)] border-b border-[var(--rule)]"
                >
                  {hg.headers.map((h) => {
                    const canSort = h.column.getCanSort();
                    const sortDir = h.column.getIsSorted();
                    const w = h.column.columnDef.size;
                    const editable = (h.column.columnDef.meta as any)?.editable as
                      | EditableMeta
                      | undefined;
                    return (
                      <th
                        key={h.id}
                        style={w ? { width: w } : undefined}
                        className={[
                          'px-3 py-2.5 text-left font-medium text-[11px] uppercase tracking-wider text-[var(--ink-mute)] select-none whitespace-nowrap',
                          canSort ? 'cursor-pointer hover:text-[var(--ink)] transition-colors' : '',
                        ].join(' ')}
                        onClick={canSort ? h.column.getToggleSortingHandler() : undefined}
                      >
                        <span className="inline-flex items-center gap-1.5">
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {editable ? (
                            <span
                              className="text-[var(--ink-faint)] text-[9px] normal-case tracking-normal"
                              title="Редактируется кликом"
                            >
                              ✎
                            </span>
                          ) : null}
                          {canSort ? (
                            <span
                              className={
                                sortDir ? 'text-[var(--accent)]' : 'text-[var(--ink-faint)]'
                              }
                            >
                              {sortDir === 'asc' ? (
                                <ArrowUp size={11} strokeWidth={2.5} />
                              ) : sortDir === 'desc' ? (
                                <ArrowDown size={11} strokeWidth={2.5} />
                              ) : (
                                <ArrowUpDown size={11} strokeWidth={1.5} />
                              )}
                            </span>
                          ) : null}
                        </span>
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody style={{ height: `${virtualizer.getTotalSize()}px`, position: 'relative' }}>
              {isLoading && rowCount === 0 ? (
                <tr>
                  <td colSpan={allColumns.length} className="text-center py-20">
                    <div className="flex flex-col items-center gap-2 text-[var(--ink-mute)]">
                      <Spinner size="md" />
                      <span className="text-[12px]">Загружаем…</span>
                    </div>
                  </td>
                </tr>
              ) : !isLoading && rowCount === 0 ? (
                <tr>
                  <td colSpan={allColumns.length} className="p-0">
                    <EmptyState
                      variant="no-results"
                      hasFilters={activeFilters > 0}
                      hasSearch={hasSearch}
                      onResetFilters={resetAll}
                      onResetSearch={() => {
                        setSearchInput('');
                        updateParam('q', undefined);
                      }}
                      onRefresh={() => refetch()}
                    />
                  </td>
                </tr>
              ) : (
                virtualizer.getVirtualItems().map((vr) => {
                  const row = table.getRowModel().rows[vr.index];
                  if (!row) return null;
                  const isSelected = selected.has(row.original[idKey]);
                  return (
                    <tr
                      key={row.id}
                      style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        right: 0,
                        height: `${vr.size}px`,
                        transform: `translateY(${vr.start}px)`,
                        display: 'table',
                        tableLayout: 'auto',
                        width: '100%',
                      }}
                      className={[
                        'border-b border-[var(--rule-soft)] transition-colors group/row',
                        isSelected ? 'bg-[var(--highlight)]' : 'hover:bg-[var(--paper-2)]',
                        rowHref ? 'cursor-pointer' : '',
                      ].join(' ')}
                      onClick={(e) => {
                        const tgt = e.target as HTMLElement;
                        if (tgt.closest('a, button, input, [role="button"]')) return;
                        if (rowHref) {
                          const href = rowHref(row.original);
                          if (href) window.open(href, '_blank', 'noopener,noreferrer');
                        }
                      }}
                    >
                      {row.getVisibleCells().map((cell, i) => {
                        const editable = (cell.column.columnDef.meta as any)?.editable as
                          | EditableMeta
                          | undefined;
                        const cellRowId = row.original[idKey];
                        const savingKey = `${cellRowId}:${cell.column.id}`;
                        const isSaving = savingCells.has(savingKey);
                        const rawValue =
                          (row.original as any)[cell.column.id] ??
                          (cell.column.id === '__select' ? undefined : undefined);
                        return (
                          <td
                            key={cell.id}
                            className={[
                              'px-3 align-middle relative',
                              editable ? 'p-0' : 'py-2',
                            ].join(' ')}
                          >
                            {isSelected && i === 0 ? (
                              <span className="absolute left-0 top-0 bottom-0 w-[3px] bg-[var(--accent)]" />
                            ) : null}
                            {editable ? (
                              <EditableCell
                                value={rawValue}
                                rowId={cellRowId}
                                columnId={cell.column.id}
                                apiBase={apiBase}
                                tableName={name}
                                isSaving={isSaving}
                                mutate={mutateCell}
                                type={editable.type}
                                options={editable.options}
                                align={
                                  (cell.column.columnDef.meta as any)?.align === 'right'
                                    ? 'right'
                                    : 'left'
                                }
                              />
                            ) : (
                              flexRender(cell.column.columnDef.cell, cell.getContext())
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>

          {/* Infinite scroll footer */}
          {rowCount > 0 && isFetchingNextPage ? (
            <div className="flex items-center justify-center gap-2 py-4 text-[12.5px] text-[var(--ink-mute)]">
              <Spinner size="sm" />
              <span>Загружаем ещё…</span>
            </div>
          ) : rowCount > 0 && !hasNextPage ? (
            <div className="flex items-center justify-center py-3 text-[11.5px] text-[var(--ink-faint)]">
              · конец ·{' '}
              <span className="tabular-nums ml-1">
                {rowCount} из {formatNum(total)}
              </span>
            </div>
          ) : null}
        </div>
      </div>

      {/* ========== Bulk action bar ========== */}
      {selectedRows.length > 0 ? (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[1000] bg-[var(--ink)] text-[var(--paper)] shadow-2xl rounded-lg pl-4 pr-1 py-1.5 flex items-center gap-2 text-[13px]">
          <span className="font-semibold tabular-nums">{selectedRows.length}</span>
          <span className="opacity-70">выбрано</span>
          <span className="w-px h-4 bg-white/20 mx-1" />
          {rowHref ? (
            <Button
              size="sm"
              variant="light"
              startContent={<ExternalLink size={12} strokeWidth={2} />}
              onPress={() => {
                const href = rowHref(selectedRows[0]);
                if (href) window.open(href, '_blank', 'noopener,noreferrer');
              }}
              className="!text-[var(--paper)] data-[hover=true]:!bg-white/10"
            >
              Открыть
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="light"
            startContent={<Download size={12} strokeWidth={2} />}
            onPress={exportCSV}
            className="!text-[var(--paper)] data-[hover=true]:!bg-white/10"
          >
            Export
          </Button>
          <span className="w-px h-4 bg-white/20 mx-1" />
          <Button
            isIconOnly
            size="sm"
            variant="light"
            onPress={() => setSelected(new Set())}
            aria-label="Снять выделение"
            className="!text-[var(--paper)] data-[hover=true]:!bg-white/10"
          >
            <X size={13} strokeWidth={2} />
          </Button>
        </div>
      ) : null}

      {/* ========== Filter drawer ========== */}
      <FilterPanel
        isOpen={filterPanelOpen}
        onOpenChange={setFilterPanelOpen}
        filters={filters}
        params={params}
        onChange={updateParam}
        onReset={resetAll}
      />
    </div>
  );
}

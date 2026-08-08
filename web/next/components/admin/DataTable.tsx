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
import { useQuery } from '@tanstack/react-query';
import {
  Spinner,
  Button,
  Input,
  Checkbox,
  Select,
  SelectItem,
  Pagination,
  Tooltip,
  Kbd,
  Chip,
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
  Rows3,
} from 'lucide-react';
import FilterPanel, { countActiveFilters, type FilterDef } from './FilterPanel';
import ActiveFilterChips from './ActiveFilterChips';
import ColumnVisibilityMenu from './ColumnVisibilityMenu';
import EmptyState from './EmptyState';

// ----------------------------------------------------------------
// Generic DataTable — clean, professional, no decoration.
// ----------------------------------------------------------------

export type DataTableProps<T extends Record<string, any>> = {
  name: string;
  columns: ColumnDef<T, any>[];
  initialSort?: SortingState;
  filters?: FilterDef[];
  pageSize?: number;
  pageSizeOptions?: number[];
  queryParams?: Record<string, string>;
  apiBase?: string;
  totalLabel?: string;
  rowHref?: (row: T) => string | null;
  idKey?: string;
};

const DEFAULT_API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000';

const DEFAULT_PAGE_SIZE_OPTIONS = [25, 50, 100, 200];

// ---- Local mock fallback (so the UI works when API is down) ---------

const MOCK: Record<string, { rows: any[]; total: number }> = {
  active: {
    total: 5227,
    rows: [
      { id: 1, source: 'cian_active', external_id: '331354235', url: 'https://www.cian.ru/sale/flat/331354235/', price: 37000000, price_per_m2: 503401, area: 73.5, rooms: 3, floor_current: 5, floor_total: 9, district: 'Хамовники', okrug: 'ЦАО', metro_station: 'Парк Культуры', metro_walk_time: 8, renovation: 'Без ремонта', days_in_exposition: 4, title: '3-к квартира 73.5 м²', publish_date: '2026-08-05', filter_id: 2, house_id: 363094 },
      { id: 2, source: 'cian_active', external_id: '330424995', url: 'https://www.cian.ru/sale/flat/330424995/', price: 17300000, price_per_m2: 316270, area: 54.7, rooms: 2, floor_current: 7, floor_total: 14, district: 'Тверской', okrug: 'ЦАО', metro_station: 'Маяковская', metro_walk_time: 5, renovation: 'Косметический', days_in_exposition: 12, title: '2-к квартира 54.7 м²', publish_date: '2026-08-01', filter_id: 1, house_id: 363422 },
      { id: 3, source: 'avans', external_id: '294656832', url: 'https://www.cian.ru/sale/flat/294656832/', price: 22500000, price_per_m2: 345115, area: 65.2, rooms: 2, floor_current: 3, floor_total: 17, district: 'Пресненский', okrug: 'ЦАО', metro_station: 'Деловой Центр', metro_walk_time: 4, renovation: 'Евроремонт', days_in_exposition: 8, title: '2-к квартира 65.2 м²', publish_date: '2026-08-04', filter_id: 6, house_id: 366744 },
      { id: 4, source: 'cian_active', external_id: '331234567', url: 'https://www.cian.ru/sale/flat/331234567/', price: 14200000, price_per_m2: 402000, area: 35.3, rooms: 1, floor_current: 9, floor_total: 14, district: 'Басманный', okrug: 'ЦАО', metro_station: 'Курская', metro_walk_time: 7, renovation: 'Дизайнерский', days_in_exposition: 22, title: '1-к квартира 35.3 м²', publish_date: '2026-07-22', filter_id: 1, house_id: 370001 },
      { id: 5, source: 'cian_active', external_id: '330987654', url: 'https://www.cian.ru/sale/flat/330987654/', price: 19800000, price_per_m2: 350000, area: 56.5, rooms: 2, floor_current: 4, floor_total: 9, district: 'Замоскворечье', okrug: 'ЦАО', metro_station: 'Павелецкая', metro_walk_time: 6, renovation: 'Косметический', days_in_exposition: 14, title: '2-к квартира 56.5 м²', publish_date: '2026-07-30', filter_id: 2, house_id: 370002 },
      { id: 6, source: 'cian_active', external_id: '330123456', url: 'https://www.cian.ru/sale/flat/330123456/', price: 9500000, price_per_m2: 285000, area: 33.3, rooms: 1, floor_current: 2, floor_total: 5, district: 'Таганский', okrug: 'ЦАО', metro_station: 'Таганская', metro_walk_time: 3, renovation: 'Без ремонта', days_in_exposition: 3, title: '1-к квартира 33.3 м²', publish_date: '2026-08-06', filter_id: 4, house_id: 370003 },
      { id: 7, source: 'cian_active', external_id: '329876543', url: 'https://www.cian.ru/sale/flat/329876543/', price: 28900000, price_per_m2: 392000, area: 73.7, rooms: 3, floor_current: 8, floor_total: 12, district: 'Арбат', okrug: 'ЦАО', metro_station: 'Смоленская', metro_walk_time: 9, renovation: 'Евроремонт', days_in_exposition: 6, title: '3-к квартира 73.7 м²', publish_date: '2026-08-02', filter_id: 2, house_id: 370004 },
      { id: 8, source: 'avans', external_id: '328765432', url: 'https://www.cian.ru/sale/flat/328765432/', price: 11700000, price_per_m2: 322000, area: 36.3, rooms: 1, floor_current: 14, floor_total: 17, district: 'Сокольники', okrug: 'ВАО', metro_station: 'Сокольники', metro_walk_time: 4, renovation: 'Косметический', days_in_exposition: 19, title: '1-к квартира 36.3 м²', publish_date: '2026-07-25', filter_id: 6, house_id: 370005 },
    ],
  },
  sold: {
    total: 18375,
    rows: [
      { id: 1, source: 'cian_active', external_id: '328760023', url: 'https://www.cian.ru/sale/flat/328760023/', price: 15500000, price_per_m2: 268631, area: 57.7, rooms: 3, sold_date: '2026-04-11', days_in_exposition: 4, title: '3-к квартира 57.7 м²', house_id: 366758 },
      { id: 2, source: 'cian_active', external_id: '328139838', url: 'https://www.cian.ru/sale/flat/328139838/', price: 14500000, price_per_m2: 353659, area: 41.0, rooms: 2, sold_date: '2026-04-01', days_in_exposition: 25, title: '2-к квартира 41 м²', house_id: 370010 },
      { id: 3, source: 'cian_active', external_id: '327863364', url: 'https://www.cian.ru/sale/flat/327863364/', price: 13000000, price_per_m2: 339426, area: 38.3, rooms: 1, sold_date: '2026-03-20', days_in_exposition: 33, title: '1-к квартира 38.3 м²', house_id: 370011 },
    ],
  },
  hidden: {
    total: 173536,
    rows: [
      { id: 1, source: 'cian_deactivated', external_id: '300000001', url: 'https://www.cian.ru/sale/flat/300000001/', price: 12500000, area: 42.0, rooms: 1, sold_date: '2025-12-15', house_id: 370020 },
      { id: 2, source: 'cian_deactivated', external_id: '300000002', url: 'https://www.cian.ru/sale/flat/300000002/', price: 18900000, area: 56.0, rooms: 2, sold_date: '2025-12-10', house_id: 370021 },
    ],
  },
  houses: {
    total: 30868,
    rows: [
      { id: 363094, source: 'flatinfo', address: 'Москва, проспект 60 летия Октября, 3к1', street: 'проспект 60 летия Октября', house_num: '3к1', year: 1985, type: 'панель', levels: 17, series: 'П-44', lat: 55.6811, lng: 37.5528, active_count: 1, deactivated_count: 7 },
      { id: 366178, source: 'flatinfo', address: 'Москва, улица 1812 года, 8к1', street: 'улица 1812 года', house_num: '8к1', year: 1972, type: 'кирпич', levels: 9, series: 'II-49', lat: 55.7375, lng: 37.5342, active_count: 1, deactivated_count: 8 },
      { id: 370001, source: 'flatinfo', address: 'Москва, улица Бакунинская, 5', street: 'улица Бакунинская', house_num: '5', year: 1975, type: 'кирпич', levels: 9, series: 'II-57', lat: 55.7735, lng: 37.6850, active_count: 1, deactivated_count: 12 },
    ],
  },
};

function getMockData(name: string, queryParams: Record<string, string>) {
  const m = MOCK[name] || { rows: [], total: 0 };
  let rows = m.rows.slice();

  const q = (queryParams.q || '').toLowerCase();
  if (q) {
    rows = rows.filter((r) =>
      Object.values(r).some((v) => String(v).toLowerCase().includes(q)),
    );
  }
  for (const [k, v] of Object.entries(queryParams)) {
    if (!v) continue;
    if (k === 'rooms') {
      const list = v.split(',').map((x) => parseInt(x, 10)).filter(Boolean);
      if (list.length) rows = rows.filter((r) => list.includes(r.rooms));
    } else if (k === 'source') {
      const list = v.split(',').map((x) => x.trim()).filter(Boolean);
      if (list.length) rows = rows.filter((r) => list.includes(r.source));
    } else if (k.endsWith('_min')) {
      const col = k.slice(0, -4);
      const n = parseInt(v, 10);
      if (!Number.isNaN(n)) rows = rows.filter((r) => (r[col] ?? 0) >= n);
    } else if (k.endsWith('_max')) {
      const col = k.slice(0, -4);
      const n = parseInt(v, 10);
      if (!Number.isNaN(n)) rows = rows.filter((r) => (r[col] ?? 0) <= n);
    }
  }

  return {
    rows,
    total: rows.length === m.rows.length ? m.total : rows.length,
    page: 1,
    page_size: 50,
    stats: {
      count: m.total,
      avg_price: rows.reduce((s, r) => s + (r.price || 0), 0) / Math.max(1, rows.length),
      avg_area: rows.reduce((s, r) => s + (r.area || 0), 0) / Math.max(1, rows.length),
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
    pageSize: initialPageSize = 50,
    pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
    queryParams: initialParams = {},
    apiBase = DEFAULT_API_BASE,
    totalLabel = 'строк',
    rowHref,
    idKey = 'id',
  } = props;

  const [params, setParams] = useState<Record<string, string>>(initialParams);
  const [sort, setSort] = useState<SortingState>(initialSort);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(initialPageSize);
  const [selected, setSelected] = useState<Set<string | number>>(new Set());
  const [columnVisibility, setColumnVisibility] = useState<Record<string, boolean>>({});
  const [density, setDensity] = useState<'comfortable' | 'compact'>('comfortable');
  const [searchInput, setSearchInput] = useState(params.q || '');
  const [filterPanelOpen, setFilterPanelOpen] = useState(false);

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

  // Query
  const queryKey = useMemo(() => {
    const q: Record<string, string> = { ...params };
    if (sort.length) {
      q.sort = String(sort[0].id);
      q.order = sort[0].desc ? 'desc' : 'asc';
    }
    q.page = String(page);
    q.page_size = String(pageSize);
    return ['table', name, q] as const;
  }, [name, params, sort, page, pageSize]);

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey,
    queryFn: async () => {
      const flat: Record<string, string> = { ...params };
      if (sort.length) {
        flat.sort = String(sort[0].id);
        flat.order = sort[0].desc ? 'desc' : 'asc';
      }
      flat.page = String(page);
      flat.page_size = String(pageSize);
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(flat)) {
        if (v != null && v !== '') qs.set(k, v);
      }
      try {
        const r = await fetch(`${apiBase}/api/tables/${name}?${qs.toString()}`, {
          cache: 'no-store',
        });
        if (!r.ok) throw new Error(`API ${r.status}`);
        return (await r.json()) as {
          rows: T[];
          total: number;
          page: number;
          page_size: number;
          stats: { count: number; avg_price: number; avg_area: number };
        };
      } catch (e) {
        return getMockData(name, { ...params, ...flat }) as any;
      }
    },
    staleTime: 15_000,
  });

  useEffect(() => {
    setPage(1);
  }, [params, sort, pageSize]);

  // Columns: prepend a checkbox column only (no row numbers).
  const allColumns = useMemo<ColumnDef<T, any>[]>(() => {
    const selCol: ColumnDef<T, any> = {
      id: '__select',
      header: ({ table }) => (
        <Checkbox
          size="sm"
          aria-label="Выбрать все на странице"
          isSelected={table.getRowModel().rows.length > 0 && table.getRowModel().rows.every((r) => selected.has(r.original[idKey]))}
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
      size: 40,
    };
    return [selCol, ...userColumns];
  }, [userColumns, selected, idKey]);

  const table = useReactTable<T>({
    data: data?.rows ?? [],
    columns: allColumns,
    state: {
      sorting: sort,
      columnVisibility: { ...columnVisibility, __select: true },
    },
    onSortingChange: setSort,
    manualSorting: true,
    manualFiltering: true,
    manualPagination: true,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row: any, idx) => String(row[idKey] ?? idx),
  });

  const parentRef = useRef<HTMLDivElement>(null);
  const rowHeight = density === 'compact' ? 40 : 48;
  const virtualizer = useVirtualizer({
    count: data?.rows.length ?? 0,
    getScrollElement: () => parentRef.current,
    estimateSize: () => rowHeight,
    overscan: 10,
  });

  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const activeFilters = countActiveFilters(filters, params);
  const hasSearch = !!params.q;
  const hasAnyFilter = hasSearch || activeFilters > 0;
  const rowCount = data?.rows.length ?? 0;

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
    setPage(1);
  }, [initialSort]);

  const exportCSV = useCallback(() => {
    const qs = new URLSearchParams({ ...params, page_size: '100000', page: '1' });
    window.open(`${apiBase}/api/tables/${name}/export?${qs.toString()}`, '_blank');
  }, [apiBase, name, params]);

  // '/' focuses search
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '/' && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
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
    return (data?.rows ?? []).filter((r: any) => selected.has(r[idKey]));
  }, [data, selected, idKey]);

  return (
    <div className="flex flex-col gap-4">
      {/* ========== Hero search ========== */}
      <div>
        <Input
          id="dt-search-input"
          value={searchInput}
          onValueChange={setSearchInput}
          placeholder="Поиск по адресу, ID, району…"
          size="lg"
          variant="bordered"
          radius="sm"
          startContent={<Search size={18} className="text-[var(--ink-mute)]" strokeWidth={2} />}
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
            base: 'w-full',
            mainWrapper: '!h-12',
            inputWrapper: '!h-12 !bg-[var(--paper-card)] data-[hover=true]:!bg-[var(--paper-card)] group-data-[focus=true]:!bg-[var(--paper-card)]',
            input: '!text-[15px] placeholder:!text-[var(--ink-faint)]',
          }}
        />
      </div>

      {/* ========== Filter row ========== */}
      <div className="flex items-center gap-2 flex-wrap min-h-[36px]">
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

        <ActiveFilterChips
          filters={filters}
          params={params}
          onChange={updateParam}
          onReset={resetAll}
        />

        <div className="flex-1" />

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

        <Tooltip content={density === 'comfortable' ? 'Компактная' : 'Обычная'} placement="bottom">
          <Button
            isIconOnly
            size="md"
            variant="bordered"
            onPress={() => setDensity((d) => (d === 'comfortable' ? 'compact' : 'comfortable'))}
            aria-label="Плотность"
          >
            <Rows3 size={14} strokeWidth={2} />
          </Button>
        </Tooltip>

        <Button
          size="md"
          variant="bordered"
          startContent={<Download size={14} strokeWidth={2} />}
          onPress={exportCSV}
        >
          Export
        </Button>
      </div>

      {/* ========== Stats line ========== */}
      <div className="flex items-baseline gap-3 flex-wrap text-[13px] text-[var(--ink-mute)] -mt-1">
        <span>
          Найдено{' '}
          <span className="font-semibold text-[var(--ink)] tabular-nums">
            {formatNum(total)}
          </span>{' '}
          {totalLabel}
        </span>
        {data?.stats?.avg_price ? (
          <>
            <span className="text-[var(--ink-faint)]">·</span>
            <span>
              ср. цена{' '}
              <span className="font-mono tabular-nums text-[var(--ink)]">
                {formatPriceShort(data.stats.avg_price)}
              </span>
            </span>
          </>
        ) : null}
        {data?.stats?.avg_area ? (
          <>
            <span className="text-[var(--ink-faint)]">·</span>
            <span>
              ср. площадь{' '}
              <span className="font-mono tabular-nums text-[var(--ink)]">
                {Math.round(data.stats.avg_area)} м²
              </span>
            </span>
          </>
        ) : null}
        {isFetching && !isLoading ? (
          <span className="text-[var(--accent)] ml-auto flex items-center gap-1.5">
            <span className="pulse-red" style={{ width: 6, height: 6 }} />
            обновляем…
          </span>
        ) : null}
      </div>

      {/* ========== Table ========== */}
      <div className="bg-[var(--paper-card)] border border-[var(--rule)] rounded-lg overflow-hidden">
        <div
          className="overflow-auto max-h-[calc(100vh-380px)]"
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
                          {canSort && (
                            <span className={sortDir ? 'text-[var(--accent)]' : 'text-[var(--ink-faint)]'}>
                              {sortDir === 'asc' ? (
                                <ArrowUp size={11} strokeWidth={2.5} />
                              ) : sortDir === 'desc' ? (
                                <ArrowDown size={11} strokeWidth={2.5} />
                              ) : (
                                <ArrowUpDown size={11} strokeWidth={1.5} />
                              )}
                            </span>
                          )}
                        </span>
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody style={{ height: `${virtualizer.getTotalSize()}px`, position: 'relative' }}>
              {isLoading && rowCount === 0 && (
                <tr>
                  <td colSpan={allColumns.length} className="text-center py-20">
                    <div className="flex flex-col items-center gap-2 text-[var(--ink-mute)]">
                      <Spinner size="md" />
                      <span className="text-[12px]">Загружаем…</span>
                    </div>
                  </td>
                </tr>
              )}

              {!isLoading && rowCount === 0 && (
                <tr>
                  <td colSpan={allColumns.length} className="p-0">
                    <EmptyState
                      variant={error ? 'error' : hasAnyFilter ? 'no-results' : 'no-data'}
                      errorMessage={(error as Error)?.message}
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
              )}

              {!isLoading && virtualizer.getVirtualItems().map((vr) => {
                const row = table.getRowModel().rows[vr.index];
                if (!row) return null;
                const isSelected = selected.has(row.original[idKey]);
                return (
                  <tr
                    key={row.id}
                    style={{
                      position: 'absolute',
                      top: 0, left: 0, right: 0,
                      height: `${vr.size}px`,
                      transform: `translateY(${vr.start}px)`,
                      display: 'table',
                      tableLayout: 'auto',
                      width: '100%',
                    }}
                    className={[
                      'border-b border-[var(--rule-soft)] transition-colors group/row',
                      isSelected
                        ? 'bg-[var(--highlight)]'
                        : 'hover:bg-[var(--paper-2)]',
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
                    {row.getVisibleCells().map((cell, i) => (
                      <td
                        key={cell.id}
                        className={[
                          'px-3 align-middle relative',
                          density === 'compact' ? 'py-1.5' : 'py-2.5',
                        ].join(' ')}
                      >
                        {isSelected && i === 0 && (
                          <span className="absolute left-0 top-0 bottom-0 w-[3px] bg-[var(--accent)]" />
                        )}
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ========== Pagination ========== */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <Pagination
          total={totalPages}
          page={page}
          onChange={setPage}
          size="sm"
          showControls
        />

        <div className="flex items-center gap-2">
          <span className="text-[12.5px] text-[var(--ink-mute)]">На стр.</span>
          <Select
            size="sm"
            variant="bordered"
            radius="sm"
            selectedKeys={new Set([String(pageSize)])}
            onSelectionChange={(keys) => {
              const v = Array.from(keys as Set<string>)[0];
              if (v) setPageSize(parseInt(v, 10));
            }}
            aria-label="Размер страницы"
            className="w-28"
            classNames={{
              trigger: '!h-8 !min-h-8 !bg-[var(--paper-card)]',
              value: '!text-[12.5px] !text-[var(--ink)]',
              selectorIcon: '!text-[var(--ink-mute)]',
            }}
          >
            {pageSizeOptions.map((n) => (
              <SelectItem key={String(n)} className="!text-[12.5px]">
                {n}
              </SelectItem>
            ))}
          </Select>
        </div>
      </div>

      {/* ========== Bulk action bar ========== */}
      {selectedRows.length > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[1000] bg-[var(--ink)] text-[var(--paper)] shadow-2xl rounded-lg pl-4 pr-1 py-1.5 flex items-center gap-2 text-[13px]">
          <span className="font-semibold tabular-nums">{selectedRows.length}</span>
          <span className="opacity-70">выбрано</span>
          <span className="w-px h-4 bg-white/20 mx-1" />
          {rowHref && (
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
          )}
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
      )}

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

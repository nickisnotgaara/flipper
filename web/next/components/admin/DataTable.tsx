'use client';

import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
  type ColumnFiltersState,
} from '@tanstack/react-table';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useQuery } from '@tanstack/react-query';
import {
  Spinner,
  Button,
  Input,
  Select,
  SelectItem,
  Pagination,
} from '@heroui/react';
import { ArrowUp, ArrowDown, ArrowUpDown, Search, X, Download } from 'lucide-react';

// ----------------------------------------------------------------
// Generic DataTable
// ----------------------------------------------------------------

export type DataTableProps<T extends Record<string, any>> = {
  /** table name on the API (e.g. "active", "sold", "hidden", "houses") */
  name: string;
  columns: ColumnDef<T, any>[];
  /** initial sort */
  initialSort?: SortingState;
  /** filter chip config — rendered above the table */
  filters?: FilterDef[];
  /** page size (default 50) */
  pageSize?: number;
  /** query alias: /api/tables/{name}? */
  queryParams?: Record<string, string>;
  /** API base — defaults to NEXT_PUBLIC_API_BASE or 127.0.0.1:8000 */
  apiBase?: string;
  /** total label, e.g. "объявлений" */
  totalLabel?: string;
};

export type FilterDef = {
  /** query-param key, e.g. "rooms", "price_min" */
  key: string;
  label: string;
  /** UI kind */
  kind: 'multi' | 'range-min' | 'range-max' | 'toggle' | 'select';
  /** options for `multi` and `select` kinds */
  options?: { value: string; label: string }[];
  /** for `toggle` */
  toggleOn?: string;
  /** placeholder for range inputs */
  placeholder?: string;
};

const DEFAULT_API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000';

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

  // Apply client-side search (since we can't SQL this)
  const q = (queryParams.q || '').toLowerCase();
  if (q) {
    rows = rows.filter((r) =>
      Object.values(r).some((v) => String(v).toLowerCase().includes(q)),
    );
  }
  // Apply client-side filters
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

// ---- Filter chip ---------------------------------------------------------

function FilterChip({
  def,
  value,
  onChange,
}: {
  def: FilterDef;
  value: string | undefined;
  onChange: (v: string | undefined) => void;
}) {
  if (def.kind === 'multi' && def.options) {
    const active = (value || '').split(',').filter(Boolean);
    return (
      <Select
        size="sm"
        variant="flat"
        selectionMode="multiple"
        selectedKeys={new Set(active)}
        onSelectionChange={(keys) => {
          const arr = Array.from(keys as Set<string>);
          onChange(arr.length ? arr.join(',') : undefined);
        }}
        className="min-w-[120px]"
        classNames={{ trigger: 'h-8 min-h-8 bg-zinc-100 data-[hover=true]:bg-zinc-50' }}
        placeholder={def.label}
      >
        {def.options.map((o) => (
          <SelectItem key={o.value}>{o.label}</SelectItem>
        ))}
      </Select>
    );
  }
  if (def.kind === 'range-min' || def.kind === 'range-max') {
    return (
      <Input
        size="sm"
        type="number"
        variant="flat"
        value={value || ''}
        onValueChange={(v) => onChange(v || undefined)}
        placeholder={def.placeholder || def.label}
        classNames={{
          base: 'w-24',
          inputWrapper: 'h-8 min-h-8 bg-zinc-100 data-[hover=true]:bg-zinc-50',
        }}
      />
    );
  }
  if (def.kind === 'toggle') {
    const on = value === (def.toggleOn || 'true');
    return (
      <Button
        size="sm"
        variant={on ? 'solid' : 'flat'}
        color={on ? 'success' : 'default'}
        onPress={() => onChange(on ? undefined : def.toggleOn || 'true')}
        className={on ? '' : 'bg-zinc-100 text-zinc-700 data-[hover=true]:bg-zinc-50'}
      >
        {def.label}
      </Button>
    );
  }
  return null;
}

// ---- Main component ------------------------------------------------------

export default function DataTable<T extends Record<string, any>>(props: DataTableProps<T>) {
  const {
    name,
    columns,
    initialSort = [],
    filters = [],
    pageSize = 50,
    queryParams: initialParams = {},
    apiBase = DEFAULT_API_BASE,
    totalLabel = 'строк',
  } = props;

  // URL state — search + filters + sort + page all live in the query string.
  const [params, setParams] = useState<Record<string, string>>(initialParams);
  const [sort, setSort] = useState<SortingState>(initialSort);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string | number>>(new Set());

  // Build query for TanStack Query
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

  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: async () => {
      const qs = new URLSearchParams();
      const flat: Record<string, string> = { ...params };
      if (sort.length) {
        flat.sort = String(sort[0].id);
        flat.order = sort[0].desc ? 'desc' : 'asc';
      }
      flat.page = String(page);
      flat.page_size = String(pageSize);
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
        // Offline / API down → use mock so the UI is still navigable
        return getMockData(name, { ...params, ...flat }) as any;
      }
    },
    staleTime: 15_000,
  });

  // Build TanStack table
  const table = useReactTable<T>({
    data: data?.rows ?? [],
    columns,
    state: { sorting: sort },
    onSortingChange: setSort,
    manualSorting: true,
    manualFiltering: true,
    manualPagination: true,
    getCoreRowModel: getCoreRowModel(),
  });

  // Virtualizer
  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: data?.rows.length ?? 0,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 44,
    overscan: 8,
  });

  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // Reset to page 1 when filters/sort change
  useEffect(() => {
    setPage(1);
  }, [params, sort]);

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
    setSort(initialSort);
    setPage(1);
  }, [initialSort]);

  const exportCSV = useCallback(() => {
    const qs = new URLSearchParams({ ...params, page_size: '100000', page: '1' });
    window.open(`${apiBase}/api/tables/${name}/export?${qs.toString()}`, '_blank');
  }, [apiBase, name, params]);

  const hasActive = Object.values(params).some((v) => v);

  return (
    <div className="space-y-4">
      {/* Search + actions bar */}
      <div className="flex items-center gap-2 flex-wrap">
        <Input
          value={params.q || ''}
          onValueChange={(v) => updateParam('q', v || undefined)}
          placeholder="Поиск по адресу, ID, району…"
          size="sm"
          variant="flat"
          startContent={<Search size={14} className="text-zinc-400" />}
          endContent={
            params.q ? (
              <Button
                isIconOnly
                size="sm"
                radius="full"
                variant="light"
                onPress={() => updateParam('q', undefined)}
                aria-label="Очистить"
                className="w-6 h-6 min-w-6 text-zinc-400 data-[hover=true]:text-zinc-700 data-[hover=true]:bg-zinc-100"
              >
                <X size={14} />
              </Button>
            ) : null
          }
          classNames={{
            base: 'w-80',
            inputWrapper:
              'h-8 bg-zinc-100 data-[hover=true]:bg-zinc-50 data-[focus=true]:bg-white data-[focus=true]:border-emerald-500',
          }}
        />

        {filters.map((f) => (
          <FilterChip
            key={f.key}
            def={f}
            value={params[f.key]}
            onChange={(v) => updateParam(f.key, v)}
          />
        ))}

        {hasActive && (
          <Button
            size="sm"
            variant="light"
            onPress={resetAll}
            className="text-zinc-500"
            startContent={<X size={12} />}
          >
            Сбросить
          </Button>
        )}

        <div className="flex-1" />

        <Button
          size="sm"
          variant="bordered"
          startContent={<Download size={14} />}
          onPress={exportCSV}
          className="border-zinc-200"
        >
          Export CSV
        </Button>
      </div>

      {/* Stats line */}
      <div className="flex items-center gap-3 text-[11px] text-zinc-500 px-1">
        <span>
          Найдено <span className="text-zinc-900 font-semibold tabular-nums">{total.toLocaleString('ru-RU')}</span> {totalLabel}
        </span>
        {data?.stats.avg_price ? (
          <>
            <span>·</span>
            <span>
              средняя <span className="text-zinc-700 tabular-nums">{Math.round(data.stats.avg_price).toLocaleString('ru-RU')} ₽</span>
            </span>
          </>
        ) : null}
        {data?.stats.avg_area ? (
          <>
            <span>·</span>
            <span>
              средняя <span className="text-zinc-700 tabular-nums">{Math.round(data.stats.avg_area * 10) / 10} м²</span>
            </span>
          </>
        ) : null}
      </div>

      {/* Table — virtualized */}
      <div className="rounded-xl border border-zinc-200 bg-white overflow-hidden">
        <div className="overflow-auto max-h-[calc(100vh-360px)]" ref={parentRef}>
          <table className="w-full text-[13px]">
            <thead className="sticky top-0 z-10 bg-zinc-50 border-b border-zinc-200">
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
                  {hg.headers.map((h) => {
                    const canSort = h.column.getCanSort();
                    const sortDir = h.column.getIsSorted();
                    return (
                      <th
                        key={h.id}
                        className={[
                          'px-3 py-2 text-left font-semibold text-[11px] uppercase tracking-wider text-zinc-500 select-none',
                          canSort ? 'cursor-pointer hover:text-zinc-900' : '',
                        ].join(' ')}
                        onClick={canSort ? h.column.getToggleSortingHandler() : undefined}
                      >
                        <span className="inline-flex items-center gap-1">
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {canSort && (
                            sortDir === 'asc' ? (
                              <ArrowUp size={11} className="text-zinc-900" />
                            ) : sortDir === 'desc' ? (
                              <ArrowDown size={11} className="text-zinc-900" />
                            ) : (
                              <ArrowUpDown size={11} className="text-zinc-300" />
                            )
                          )}
                        </span>
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody style={{ height: `${virtualizer.getTotalSize()}px`, position: 'relative' }}>
              {isLoading && (
                <tr>
                  <td colSpan={columns.length} className="text-center py-12 text-zinc-500">
                    <Spinner size="sm" /> Загрузка…
                  </td>
                </tr>
              )}
              {!isLoading && virtualizer.getVirtualItems().map((vr) => {
                const row = table.getRowModel().rows[vr.index];
                if (!row) return null;
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
                    className="border-b border-zinc-100 hover:bg-zinc-50"
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-3 py-2 align-middle">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                );
              })}
              {!isLoading && (data?.rows.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={columns.length} className="text-center py-12 text-zinc-500">
                    Ничего не нашлось
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      <div className="flex items-center gap-3 text-[12px] text-zinc-500">
        <span className="tabular-nums">
          {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} из {total.toLocaleString('ru-RU')}
        </span>
        <Pagination
          total={totalPages}
          page={page}
          onChange={setPage}
          size="sm"
          showControls
          color="default"
        />
        <div className="flex-1" />
        <span>по {pageSize} на стр.</span>
      </div>
    </div>
  );
}

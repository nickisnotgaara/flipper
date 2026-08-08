'use client';

import { useMemo } from 'react';
import DataTable from '@/components/admin/DataTable';
import type { FilterDef } from '@/components/admin/FilterPanel';

const FILTERS: FilterDef[] = [
  {
    key: 'source',
    label: 'Источник',
    group: 'Категории',
    kind: 'multi',
    options: [
      { value: 'flatinfo', label: 'Flatinfo' },
      { value: 'cian_ad', label: 'Циан ad' },
      { value: 'domclick_sold', label: 'ДомКлик' },
    ],
  },
  {
    key: 'year_min',
    label: 'Год',
    group: 'Год постройки',
    kind: 'range-min',
    placeholder: '1950',
  },
  {
    key: 'year_max',
    label: 'Год',
    group: 'Год постройки',
    kind: 'range-max',
    placeholder: '2020',
  },
];

function fmt(n: number | null | undefined): string {
  if (n == null) return '—';
  return n.toLocaleString('ru-RU');
}

export default function HousesPage() {
  const columns = useMemo(
    () => [
      {
        id: 'address',
        header: 'Адрес',
        accessorKey: 'address',
        meta: { editable: { type: 'text' } },
        cell: ({ row }: any) => (
          <div className="min-w-[280px] py-1">
            <div className="text-[var(--ink)] font-medium text-[13px] leading-tight truncate">
              {row.original.address || '—'}
            </div>
            <div className="text-[11px] text-[var(--ink-mute)] font-mono mt-0.5 truncate">
              {[row.original.street, row.original.house_num].filter(Boolean).join(', ') || '—'}
            </div>
          </div>
        ),
      },
      {
        id: 'source',
        header: 'источник',
        accessorKey: 'source',
        cell: ({ row }: any) => {
          const s = row.original.source;
          const color =
            s === 'flatinfo'
              ? 'border-[var(--ink)] text-[var(--ink)] bg-[var(--paper-card)]'
              : s === 'cian_ad'
                ? 'border-[var(--gain)] text-[var(--gain)] bg-[var(--gain-soft)]'
                : 'border-[var(--rule)] text-[var(--ink-mute)] bg-[var(--paper-card)]';
          return (
            <span
              className={`inline-flex items-center px-1.5 h-5 text-[10px] font-mono uppercase tracking-[0.10em] font-semibold border rounded-[1px] ${color}`}
            >
              {s}
            </span>
          );
        },
      },
      {
        id: 'year',
        header: 'год',
        accessorKey: 'year',
        meta: { editable: { type: 'integer' }, align: 'right' },
      },
      {
        id: 'type',
        header: 'тип',
        accessorKey: 'type',
        meta: {
          editable: {
            type: 'select',
            options: [
              { value: 'панель', label: 'панель' },
              { value: 'кирпич', label: 'кирпич' },
              { value: 'монолит', label: 'монолит' },
              { value: 'блочный', label: 'блочный' },
            ],
          },
        },
      },
      {
        id: 'series',
        header: 'серия',
        accessorKey: 'series',
        meta: { editable: { type: 'text' } },
      },
      {
        id: 'levels',
        header: 'этажей',
        accessorKey: 'levels',
        meta: { editable: { type: 'integer' }, align: 'right' },
      },
      {
        id: 'active_count',
        header: 'активных',
        accessorKey: 'active_count',
        cell: ({ row }: any) => (
          <div className="text-right">
            <span className="font-mono tabular-nums text-[var(--accent)] font-semibold text-[13px]">
              {fmt(row.original.active_count ?? 0)}
            </span>
          </div>
        ),
      },
      {
        id: 'deactivated_count',
        header: 'снято',
        accessorKey: 'deactivated_count',
        cell: ({ row }: any) => (
          <div className="text-right">
            <span className="font-mono tabular-nums text-[var(--ink-soft)] text-[12.5px]">
              {fmt(row.original.deactivated_count ?? 0)}
            </span>
          </div>
        ),
      },
    ],
    [],
  );

  return (
    <div className="space-y-4">
      <div>
        <h1 className="page-title">Дома</h1>
        <p className="page-sub">Здания с привязанными объявлениями</p>
      </div>
      <DataTable
        name="houses"
        columns={columns as any}
        filters={FILTERS}
        initialSort={[{ id: 'active_count', desc: true }]}
        totalLabel="домов"
      />
    </div>
  );
}

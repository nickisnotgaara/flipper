'use client';

import { useMemo } from 'react';
import Link from 'next/link';
import { Chip } from '@heroui/react';
import { ExternalLink } from 'lucide-react';
import DataTable from '@/components/admin/DataTable';
import type { FilterDef } from '@/components/admin/FilterPanel';

const FILTERS: FilterDef[] = [
  {
    key: 'rooms',
    label: 'Комнат',
    group: 'Категории',
    kind: 'multi',
    options: [
      { value: '1', label: '1' },
      { value: '2', label: '2' },
      { value: '3', label: '3' },
    ],
  },
  {
    key: 'price_min',
    label: 'Цена',
    group: 'Цена',
    kind: 'range-min',
    placeholder: '5 000 000',
    unit: '₽',
  },
  {
    key: 'price_max',
    label: 'Цена',
    group: 'Цена',
    kind: 'range-max',
    placeholder: '20 000 000',
    unit: '₽',
  },
  {
    key: 'days_max',
    label: 'Дней',
    group: 'Срок',
    kind: 'range-max',
    placeholder: '60',
    unit: 'дн.',
  },
  {
    key: 'source',
    label: 'Источник',
    group: 'Дополнительно',
    kind: 'multi',
    options: [{ value: 'cian_active', label: 'ЦИАН' }],
  },
];

function fmt(n: number | null | undefined): string {
  if (n == null) return '—';
  return n.toLocaleString('ru-RU');
}

export default function SoldPage() {
  const columns = useMemo(
    () => [
      {
        id: 'title',
        header: 'Адрес / ID',
        accessorKey: 'title',
        cell: ({ row }: any) => (
          <div className="min-w-[220px]">
            <div className="text-[var(--ink)] font-medium text-[13px] leading-tight truncate">
              {row.original.title || '—'}
            </div>
            <div className="text-[10.5px] text-[var(--ink-faint)] font-mono tabular-nums mt-0.5">
              id #{row.original.external_id}
            </div>
          </div>
        ),
      },
      {
        id: 'rooms',
        header: 'комн',
        accessorKey: 'rooms',
        cell: ({ row }: any) => (
          <span className="font-mono tabular-nums text-[var(--ink)] text-right block w-full">
            {row.original.rooms ?? '—'}
          </span>
        ),
      },
      {
        id: 'area',
        header: 'площадь',
        accessorKey: 'area',
        cell: ({ row }: any) => (
          <div className="text-right">
            <span className="font-mono tabular-nums text-[var(--ink)]">
              {row.original.area ?? '—'}
            </span>
            <span className="font-mono text-[10px] text-[var(--ink-faint)] ml-1">м²</span>
          </div>
        ),
      },
      {
        id: 'price',
        header: 'цена, ₽',
        accessorKey: 'price',
        cell: ({ row }: any) => (
          <div className="text-right">
            <span className="font-mono tabular-nums text-[var(--ink)] font-semibold text-[13px]">
              {fmt(row.original.price)}
            </span>
          </div>
        ),
      },
      {
        id: 'price_per_m2',
        header: '₽/м²',
        accessorKey: 'price_per_m2',
        cell: ({ row }: any) => (
          <div className="text-right">
            <span className="font-mono tabular-nums text-[var(--ink-soft)] text-[12.5px]">
              {row.original.price_per_m2 ? fmt(Math.round(row.original.price_per_m2)) : '—'}
            </span>
          </div>
        ),
      },
      {
        id: 'sold_date',
        header: 'снято',
        accessorKey: 'sold_date',
        cell: ({ row }: any) => (
          <span className="font-mono tabular-nums text-[12.5px] text-[var(--ink-mute)]">
            {row.original.sold_date || '—'}
          </span>
        ),
      },
      {
        id: 'days_in_exposition',
        header: 'дней',
        accessorKey: 'days_in_exposition',
        cell: ({ row }: any) => (
          <span className="font-mono tabular-nums text-[12.5px] text-[var(--ink-soft)] text-right block w-full">
            {row.original.days_in_exposition ?? '—'}
          </span>
        ),
      },
      {
        id: 'renovation',
        header: 'ремонт',
        accessorKey: 'renovation',
        meta: {
          editable: {
            type: 'select',
            options: [
              { value: 'Без ремонта', label: 'Без ремонта' },
              { value: 'Косметический', label: 'Косметический' },
              { value: 'Евроремонт', label: 'Евроремонт' },
              { value: 'Дизайнерский', label: 'Дизайнерский' },
            ],
          },
        },
      },
      {
        id: 'url',
        header: '',
        enableSorting: false,
        cell: ({ row }: any) => (
          <Link
            href={row.original.url || '#'}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[var(--ink-faint)] hover:text-[var(--accent)] transition-colors"
            onClick={(e) => e.stopPropagation()}
          >
            <ExternalLink size={13} strokeWidth={1.75} />
          </Link>
        ),
      },
    ],
    [],
  );

  return (
    <div className="space-y-4">
      <div>
        <h1 className="page-title">Снятые объявления</h1>
        <p className="page-sub">Недавние сделки с полным offerData</p>
      </div>
      <DataTable
        name="sold"
        columns={columns as any}
        filters={FILTERS}
        initialSort={[{ id: 'sold_date', desc: true }]}
        totalLabel="сделок"
        rowHref={(row) => row.url || null}
      />
    </div>
  );
}

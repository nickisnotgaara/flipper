'use client';

import { useMemo } from 'react';
import Link from 'next/link';
import { Chip } from '@heroui/react';
import { ExternalLink, Image as ImageIcon, AlertTriangle } from 'lucide-react';
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
      { value: '4', label: '4+' },
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
    key: 'area_min',
    label: 'Площадь',
    group: 'Площадь',
    kind: 'range-min',
    placeholder: '30',
    unit: 'м²',
  },
  {
    key: 'area_max',
    label: 'Площадь',
    group: 'Площадь',
    kind: 'range-max',
    placeholder: '80',
    unit: 'м²',
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
    key: 'has_avans',
    label: 'С авансом',
    group: 'Дополнительно',
    kind: 'toggle',
    toggleOn: 'true',
  },
  {
    key: 'source',
    label: 'Источник',
    group: 'Дополнительно',
    kind: 'multi',
    options: [
      { value: 'cian_active', label: 'ЦИАН' },
      { value: 'avans', label: 'Аванс' },
    ],
  },
];

function fmt(n: number | null | undefined): string {
  if (n == null) return '—';
  return n.toLocaleString('ru-RU');
}

export default function ActivePage() {
  const columns = useMemo(
    () => [
      {
        id: 'address',
        header: 'Адрес',
        accessorKey: 'district',
        cell: ({ row }: any) => (
          <div className="min-w-[220px]">
            <div className="text-zinc-900 font-medium truncate">{row.original.title || '—'}</div>
            <div className="text-[11px] text-zinc-500 truncate">
              {row.original.district || '—'}
              {row.original.okrug ? ` · ${row.original.okrug}` : ''}
            </div>
          </div>
        ),
      },
      {
        id: 'rooms',
        header: 'Комнат',
        accessorKey: 'rooms',
        cell: ({ row }: any) => (
          <span className="tabular-nums text-zinc-700">{row.original.rooms ?? '—'}</span>
        ),
      },
      {
        id: 'area',
        header: 'Площадь',
        accessorKey: 'area',
        cell: ({ row }: any) => (
          <span className="tabular-nums text-zinc-700">
            {row.original.area ? `${row.original.area} м²` : '—'}
          </span>
        ),
      },
      {
        id: 'floor_current',
        header: 'Этаж',
        accessorFn: (r: any) => r.floor_current,
        cell: ({ row }: any) => (
          <span className="tabular-nums text-zinc-700">
            {row.original.floor_current ?? '—'}
            {row.original.floor_total ? ` / ${row.original.floor_total}` : ''}
          </span>
        ),
      },
      {
        id: 'price',
        header: '₽',
        accessorKey: 'price',
        cell: ({ row }: any) => (
          <span className="tabular-nums text-zinc-900 font-semibold">
            {fmt(row.original.price)}
          </span>
        ),
      },
      {
        id: 'price_per_m2',
        header: '₽/м²',
        accessorKey: 'price_per_m2',
        cell: ({ row }: any) => (
          <span className="tabular-nums text-zinc-700">
            {row.original.price_per_m2 ? fmt(Math.round(row.original.price_per_m2)) : '—'}
          </span>
        ),
      },
      {
        id: 'days_in_exposition',
        header: 'Дней',
        accessorKey: 'days_in_exposition',
        cell: ({ row }: any) => {
          const d = row.original.days_in_exposition;
          const color = d != null && d > 60 ? 'warning' : d != null && d > 90 ? 'danger' : 'default';
          return (
            <Chip size="sm" variant="flat" color={color as any} classNames={{ base: 'h-5 px-1.5' }}>
              <span className="text-[11px] tabular-nums font-semibold">{d ?? '—'}</span>
            </Chip>
          );
        },
      },
      {
        id: 'renovation',
        header: 'Ремонт',
        accessorKey: 'renovation',
        cell: ({ row }: any) => (
          <span className="text-[12px] text-zinc-600">{row.original.renovation || '—'}</span>
        ),
      },
      {
        id: 'source',
        header: 'Источник',
        accessorKey: 'source',
        cell: ({ row }: any) => {
          const isAvans = row.original.source === 'avans';
          return (
            <Chip
              size="sm"
              variant="flat"
              color={isAvans ? 'warning' : 'success'}
              classNames={{ base: 'h-5 px-1.5' }}
            >
              <span className="text-[10px] uppercase font-semibold tracking-wider">
                {isAvans ? 'Аванс' : 'ЦИАН'}
              </span>
            </Chip>
          );
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
            className="text-zinc-400 hover:text-emerald-600"
            onClick={(e) => e.stopPropagation()}
          >
            <ExternalLink size={14} />
          </Link>
        ),
      },
    ],
    [],
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-bold tracking-tight">Активные объявления</h1>
        <p className="text-[13px] text-zinc-500 mt-0.5">
          5 227 живых объявлений · server-side pagination, sort, search, filters
        </p>
      </div>
      <DataTable
        name="active"
        columns={columns as any}
        filters={FILTERS}
        initialSort={[{ id: 'price_per_m2', desc: false }]}
        totalLabel="объявлений"
        pageSize={50}
        rowHref={(row) => row.url || null}
      />
    </div>
  );
}

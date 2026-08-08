'use client';

import { useMemo } from 'react';
import Link from 'next/link';
import { Chip } from '@heroui/react';
import { ExternalLink, Stamp } from 'lucide-react';
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

// "Freshness" stamp — color a small badge by days on market.
function daysTone(d: number | null | undefined): { color: string; label: string } {
  if (d == null) return { color: 'text-zinc-400', label: '—' };
  if (d <= 7) return { color: 'text-emerald-700', label: 'свежее' };
  if (d <= 30) return { color: 'text-amber-700', label: 'норма' };
  if (d <= 90) return { color: 'text-orange-700', label: 'залежалое' };
  return { color: 'text-rose-800', label: 'старое' };
}

export default function ActivePage() {
  const columns = useMemo(
    () => [
      {
        id: 'title',
        header: 'Адрес / район',
        accessorKey: 'title',
        cell: ({ row }: any) => (
          <div className="min-w-[220px] py-1">
            <div className="text-[var(--ink)] font-medium text-[13px] leading-tight truncate">
              {row.original.title || '—'}
            </div>
            <div className="text-[11px] text-[var(--ink-mute)] font-mono mt-0.5 truncate">
              {row.original.external_id ? `id #${row.original.external_id}` : '—'}
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
        id: 'floor_current',
        header: 'этаж',
        accessorFn: (r: any) => r.floor_current,
        cell: ({ row }: any) => (
          <div className="text-right font-mono tabular-nums text-[var(--ink-soft)] text-[12.5px]">
            {row.original.floor_current ?? '—'}
            <span className="text-[var(--ink-faint)]"> / </span>
            {row.original.floor_total ?? '—'}
          </div>
        ),
      },
      {
        id: 'price',
        header: 'цена, ₽',
        accessorKey: 'price',
        cell: ({ row }: any) => (
          <div className="text-right">
            <div className="font-mono tabular-nums text-[var(--ink)] font-semibold text-[13px]">
              {fmt(row.original.price)}
            </div>
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
        id: 'days_in_exposition',
        header: 'дней',
        accessorKey: 'days_in_exposition',
        cell: ({ row }: any) => {
          const d = row.original.days_in_exposition;
          const tone = daysTone(d);
          return (
            <div className="text-right">
              <span className={`font-mono tabular-nums text-[12.5px] font-semibold ${tone.color}`}>
                {d ?? '—'}
              </span>
            </div>
          );
        },
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
        id: 'district',
        header: 'район',
        accessorKey: 'district',
        meta: { editable: { type: 'text' } },
      },
      {
        id: 'metro_station',
        header: 'метро',
        accessorKey: 'metro_station',
        meta: { editable: { type: 'text' } },
      },
      {
        id: 'metro_walk_time',
        header: 'мин.',
        accessorKey: 'metro_walk_time',
        meta: { editable: { type: 'integer' }, align: 'right' },
      },
      {
        id: 'filter_id',
        header: 'фильтр',
        accessorKey: 'filter_id',
        meta: { editable: { type: 'integer' }, align: 'right' },
      },
      {
        id: 'source',
        header: 'источник',
        accessorKey: 'source',
        cell: ({ row }: any) => {
          const isAvans = row.original.source === 'avans';
          return (
            <span
              className={[
                'inline-flex items-center gap-1 px-1.5 h-5 text-[10px] font-mono uppercase tracking-[0.10em] font-semibold border rounded-[1px]',
                isAvans
                  ? 'border-[var(--gold)] text-[var(--gold)] bg-[var(--gold-soft)]'
                  : 'border-[var(--ink)] text-[var(--ink)] bg-[var(--paper-card)]',
              ].join(' ')}
            >
              {isAvans && <Stamp size={9} strokeWidth={2} />}
              {isAvans ? 'Аванс' : 'ЦИАН'}
            </span>
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
        <h1 className="page-title">Активные объявления</h1>
        <p className="page-sub">Живые объявления с ЦИАН и авансовые сигналы</p>
      </div>
      <DataTable
        name="active"
        columns={columns as any}
        filters={FILTERS}
        initialSort={[{ id: 'price_per_m2', desc: false }]}
        totalLabel="объявлений"
        rowHref={(row) => row.url || null}
      />
    </div>
  );
}

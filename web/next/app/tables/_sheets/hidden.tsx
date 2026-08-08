// Column defs + filter defs for the "Скрытые" sheet of the tables page.

import Link from 'next/link';
import { Image as ImageIcon, ExternalLink } from 'lucide-react';
import type { ColumnDef } from '@tanstack/react-table';
import type { FilterDef } from '@/components/admin/FilterPanel';

export const HIDDEN_TOTAL = 173_536;

export const hiddenFilters: FilterDef[] = [
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
    placeholder: '30 000 000',
    unit: '₽',
  },
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
];

function fmt(n: number | null | undefined): string {
  if (n == null) return '—';
  return n.toLocaleString('ru-RU');
}

export const hiddenColumns: ColumnDef<any, any>[] = [
  {
    id: 'thumb',
    header: 'фото',
    enableSorting: false,
    cell: ({ row }: any) => (
      <div className="w-9 h-7 border border-[var(--rule)] flex items-center justify-center text-[var(--ink-faint)] bg-[var(--paper-2)]">
        <ImageIcon size={11} strokeWidth={1.75} />
      </div>
    ),
  },
  {
    id: 'title',
    header: 'ID объявления',
    accessorKey: 'external_id',
    cell: ({ row }: any) => (
      <div className="min-w-[200px]">
        <div className="font-mono tabular-nums text-[var(--ink)] font-medium text-[13px]">
          #{row.original.external_id}
        </div>
        <div className="text-[10.5px] text-[var(--ink-faint)] font-mono mt-0.5">
          house #{row.original.house_id}
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
    id: 'source',
    header: 'источник',
    accessorKey: 'source',
    cell: ({ row }: any) => (
      <span className="inline-flex items-center px-1.5 h-5 text-[10px] font-mono uppercase tracking-[0.10em] font-semibold border border-[var(--ink)] bg-[var(--paper-card)] text-[var(--ink)] rounded-[1px]">
        ЦИАН
      </span>
    ),
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
];

'use client';

import { useMemo } from 'react';
import Link from 'next/link';
import { Chip } from '@heroui/react';
import { ExternalLink } from 'lucide-react';
import DataTable, { type FilterDef } from '@/components/admin/DataTable';

const FILTERS: FilterDef[] = [
  { key: 'rooms', label: 'Комнат', kind: 'multi', options: [
    { value: '1', label: '1' },
    { value: '2', label: '2' },
    { value: '3', label: '3' },
  ]},
  { key: 'price_min', label: 'Цена от', kind: 'range-min', placeholder: '5 000 000' },
  { key: 'price_max', label: 'до', kind: 'range-max', placeholder: '20 000 000' },
  { key: 'days_max', label: 'Дней', kind: 'range-max', placeholder: '60' },
  { key: 'source', label: 'Источник', kind: 'multi', options: [
    { value: 'cian_active', label: 'ЦИАН' },
  ]},
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
        header: 'Адрес',
        accessorKey: 'title',
        cell: ({ row }: any) => (
          <div className="min-w-[220px]">
            <div className="text-zinc-900 font-medium truncate">{row.original.title || '—'}</div>
            <div className="text-[11px] text-zinc-500">id #{row.original.external_id}</div>
          </div>
        ),
      },
      { id: 'rooms', header: 'Комнат', accessorKey: 'rooms', cell: ({ row }: any) => <span className="tabular-nums">{row.original.rooms ?? '—'}</span> },
      { id: 'area', header: 'Площадь', accessorKey: 'area', cell: ({ row }: any) => <span className="tabular-nums">{row.original.area ? `${row.original.area} м²` : '—'}</span> },
      { id: 'price', header: 'Цена', accessorKey: 'price', cell: ({ row }: any) => <span className="tabular-nums font-semibold text-zinc-900">{fmt(row.original.price)}</span> },
      { id: 'price_per_m2', header: '₽/м²', accessorKey: 'price_per_m2', cell: ({ row }: any) => <span className="tabular-nums text-zinc-700">{row.original.price_per_m2 ? fmt(Math.round(row.original.price_per_m2)) : '—'}</span> },
      { id: 'sold_date', header: 'Снято', accessorKey: 'sold_date', cell: ({ row }: any) => <span className="text-[12px] text-zinc-600">{row.original.sold_date || '—'}</span> },
      { id: 'days_in_exposition', header: 'Дней', accessorKey: 'days_in_exposition', cell: ({ row }: any) => <Chip size="sm" variant="flat" classNames={{ base: 'h-5 px-1.5' }}><span className="text-[11px] tabular-nums font-semibold">{row.original.days_in_exposition ?? '—'}</span></Chip> },
      {
        id: 'url',
        header: '',
        enableSorting: false,
        cell: ({ row }: any) => (
          <Link href={row.original.url || '#'} target="_blank" rel="noopener noreferrer" className="text-zinc-400 hover:text-emerald-600" onClick={(e) => e.stopPropagation()}>
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
        <h1 className="text-[22px] font-bold tracking-tight">Снятые объявления (comps)</h1>
        <p className="text-[13px] text-zinc-500 mt-0.5">
          18 375 недавних сделок с offerData · компы для оценки цены
        </p>
      </div>
      <DataTable
        name="sold"
        columns={columns as any}
        filters={FILTERS}
        initialSort={[{ id: 'sold_date', desc: true }]}
        totalLabel="сделок"
        pageSize={50}
      />
    </div>
  );
}

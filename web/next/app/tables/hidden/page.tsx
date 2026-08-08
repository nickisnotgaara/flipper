'use client';

import { useMemo } from 'react';
import Link from 'next/link';
import { Chip } from '@heroui/react';
import { ExternalLink, Image as ImageIcon } from 'lucide-react';
import DataTable, { type FilterDef } from '@/components/admin/DataTable';

const FILTERS: FilterDef[] = [
  { key: 'price_min', label: 'Цена от', kind: 'range-min', placeholder: '5 000 000' },
  { key: 'price_max', label: 'до', kind: 'range-max', placeholder: '30 000 000' },
  { key: 'rooms', label: 'Комнат', kind: 'multi', options: [
    { value: '1', label: '1' },
    { value: '2', label: '2' },
    { value: '3', label: '3' },
  ]},
];

function fmt(n: number | null | undefined): string {
  if (n == null) return '—';
  return n.toLocaleString('ru-RU');
}

export default function HiddenPage() {
  const columns = useMemo(
    () => [
      {
        id: 'thumb',
        header: 'Фото',
        enableSorting: false,
        cell: ({ row }: any) => (
          <div className="w-12 h-8 rounded bg-zinc-100 flex items-center justify-center text-zinc-400">
            <ImageIcon size={14} />
          </div>
        ),
      },
      {
        id: 'title',
        header: 'ID объявления',
        accessorKey: 'external_id',
        cell: ({ row }: any) => (
          <div className="min-w-[200px]">
            <div className="text-zinc-900 font-medium tabular-nums">#{row.original.external_id}</div>
            <div className="text-[11px] text-zinc-500">house #{row.original.house_id}</div>
          </div>
        ),
      },
      { id: 'rooms', header: 'Комнат', accessorKey: 'rooms', cell: ({ row }: any) => <span className="tabular-nums">{row.original.rooms ?? '—'}</span> },
      { id: 'area', header: 'Площадь', accessorKey: 'area', cell: ({ row }: any) => <span className="tabular-nums">{row.original.area ? `${row.original.area} м²` : '—'}</span> },
      { id: 'price', header: 'Цена', accessorKey: 'price', cell: ({ row }: any) => <span className="tabular-nums font-semibold text-zinc-900">{fmt(row.original.price)}</span> },
      { id: 'sold_date', header: 'Снято', accessorKey: 'sold_date', cell: ({ row }: any) => <span className="text-[12px] text-zinc-600">{row.original.sold_date || '—'}</span> },
      { id: 'source', header: 'Источник', accessorKey: 'source', cell: ({ row }: any) => <Chip size="sm" variant="flat" classNames={{ base: 'h-5 px-1.5' }}><span className="text-[10px] uppercase font-semibold tracking-wider">ЦИАН</span></Chip> },
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
        <h1 className="text-[22px] font-bold tracking-tight">Скрытые с фото</h1>
        <p className="text-[13px] text-zinc-500 mt-0.5">
          173 536 снятых публикаций с фотографиями · 75% имеют фото
        </p>
      </div>
      <DataTable
        name="hidden"
        columns={columns as any}
        filters={FILTERS}
        initialSort={[{ id: 'sold_date', desc: true }]}
        totalLabel="скрытых"
        pageSize={50}
      />
    </div>
  );
}

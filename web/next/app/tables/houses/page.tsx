'use client';

import { useMemo } from 'react';
import { Chip } from '@heroui/react';
import { Home, Layers } from 'lucide-react';
import DataTable, { type FilterDef } from '@/components/admin/DataTable';

const FILTERS: FilterDef[] = [
  { key: 'source', label: 'Источник', kind: 'multi', options: [
    { value: 'flatinfo', label: 'Flatinfo' },
    { value: 'cian_ad', label: 'Циан ad' },
    { value: 'domclick_sold', label: 'ДомКлик' },
  ]},
  { key: 'year_min', label: 'Год от', kind: 'range-min', placeholder: '1950' },
  { key: 'year_max', label: 'до', kind: 'range-max', placeholder: '2020' },
];

export default function HousesPage() {
  const columns = useMemo(
    () => [
      {
        id: 'address',
        header: 'Адрес',
        accessorKey: 'address',
        cell: ({ row }: any) => (
          <div className="min-w-[280px]">
            <div className="text-zinc-900 font-medium truncate">{row.original.address || '—'}</div>
          </div>
        ),
      },
      { id: 'source', header: 'Источник', accessorKey: 'source', cell: ({ row }: any) => {
          const s = row.original.source;
          const color = s === 'flatinfo' ? 'primary' : s === 'cian_ad' ? 'success' : 'default';
          return <Chip size="sm" variant="flat" color={color as any} classNames={{ base: 'h-5 px-1.5' }}><span className="text-[10px] uppercase font-semibold tracking-wider">{s}</span></Chip>;
        } },
      { id: 'year', header: 'Год', accessorKey: 'year', cell: ({ row }: any) => <span className="tabular-nums text-zinc-700">{row.original.year ?? '—'}</span> },
      { id: 'type', header: 'Тип', accessorKey: 'type', cell: ({ row }: any) => <span className="text-[12px] text-zinc-600">{row.original.type || '—'}</span> },
      { id: 'levels', header: 'Этажей', accessorKey: 'levels', cell: ({ row }: any) => <span className="tabular-nums text-zinc-700 flex items-center gap-1"><Layers size={11} className="text-zinc-400" />{row.original.levels ?? '—'}</span> },
      { id: 'active_count', header: 'Активных', accessorKey: 'active_count', cell: ({ row }: any) => <span className="tabular-nums font-semibold text-rose-600">{row.original.active_count ?? 0}</span> },
      { id: 'deactivated_count', header: 'Снято', accessorKey: 'deactivated_count', cell: ({ row }: any) => <span className="tabular-nums text-zinc-700">{row.original.deactivated_count ?? 0}</span> },
    ],
    [],
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-bold tracking-tight">Дома</h1>
        <p className="text-[13px] text-zinc-500 mt-0.5">
          30 868 зданий · точка входа для аналитики, drill-down по объявлениям
        </p>
      </div>
      <DataTable
        name="houses"
        columns={columns as any}
        filters={FILTERS}
        initialSort={[{ id: 'active_count', desc: true }]}
        totalLabel="домов"
        pageSize={50}
      />
    </div>
  );
}

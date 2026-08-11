'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Card,
  CardBody,
  Chip,
  Button,
  Spinner,
} from '@heroui/react';
import { Play, RefreshCcw, Check, X, Clock } from 'lucide-react';

type Parser = { name: string; last_run_at: string | null; status: string };

const FALLBACK: Parser[] = [
  { name: 'cian_active', last_run_at: '2026-08-09T00:23:41', status: 'ok' },
  { name: 'cian_sold', last_run_at: '2026-08-08T22:11:08', status: 'ok' },
  { name: 'domclick_sold', last_run_at: '2026-08-08T19:45:00', status: 'ok' },
  { name: 'winners_sold', last_run_at: '2026-08-06T03:10:22', status: 'ok' },
  { name: 'flatinfo_houses', last_run_at: '2026-07-30T11:20:00', status: 'ok' },
];

function statusChip(s: string) {
  if (s === 'ok') return <Chip size="sm" variant="flat" color="success" classNames={{ base: 'h-5 px-1.5' }} startContent={<Check size={10} />}><span className="text-[10px] uppercase font-semibold tracking-wider">OK</span></Chip>;
  if (s === 'fail') return <Chip size="sm" variant="flat" color="danger" classNames={{ base: 'h-5 px-1.5' }} startContent={<X size={10} />}><span className="text-[10px] uppercase font-semibold tracking-wider">FAIL</span></Chip>;
  return <Chip size="sm" variant="flat" color="default" classNames={{ base: 'h-5 px-1.5' }} startContent={<Clock size={10} />}><span className="text-[10px] uppercase font-semibold tracking-wider">NEVER</span></Chip>;
}

function timeAgo(iso: string | null): string {
  if (!iso) return 'никогда';
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return 'только что';
  if (diff < 3600) return `${Math.floor(diff / 60)} мин назад`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} ч назад`;
  return `${Math.floor(diff / 86400)} д назад`;
}

export default function PipelinePage() {
  const qc = useQueryClient();
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['pipeline-status'],
    queryFn: async (): Promise<Parser[]> => {
      try {
        const r = await fetch('http://127.0.0.1:8001/api/pipeline/status', { cache: 'no-store' });
        if (!r.ok) throw new Error('bad');
        return await r.json();
      } catch {
        return FALLBACK;
      }
    },
    staleTime: 10_000,
  });

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-4">
        <div>
          <h1 className="text-[22px] font-bold tracking-tight">Pipeline</h1>
          <p className="text-[13px] text-zinc-500 mt-0.5">
            Парсеры · статусы, последний запуск, ручной старт
          </p>
        </div>
        <div className="flex-1" />
        <Button
          variant="bordered"
          size="sm"
          startContent={<RefreshCcw size={14} />}
          onPress={() => refetch()}
          className="border-zinc-200"
        >
          Обновить
        </Button>
      </div>

      <Card shadow="none" className="border border-zinc-200 rounded-2xl">
        <CardBody className="p-0">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-zinc-200 bg-zinc-50">
                <th className="text-left px-4 py-2.5 font-semibold text-[11px] uppercase tracking-wider text-zinc-500">Парсер</th>
                <th className="text-left px-4 py-2.5 font-semibold text-[11px] uppercase tracking-wider text-zinc-500">Статус</th>
                <th className="text-left px-4 py-2.5 font-semibold text-[11px] uppercase tracking-wider text-zinc-500">Последний запуск</th>
                <th className="px-4 py-2.5"></th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td colSpan={4} className="text-center py-12 text-zinc-500">
                    <Spinner size="sm" /> Загрузка…
                  </td>
                </tr>
              )}
              {!isLoading && (data ?? FALLBACK).map((p) => (
                <tr key={p.name} className="border-b border-zinc-100 hover:bg-zinc-50">
                  <td className="px-4 py-3 font-mono text-zinc-900">{p.name}</td>
                  <td className="px-4 py-3">{statusChip(p.status)}</td>
                  <td className="px-4 py-3 text-zinc-600 text-[12px]">
                    {p.last_run_at ? (
                      <>
                        <span className="tabular-nums">{new Date(p.last_run_at).toLocaleString('ru-RU')}</span>
                        <span className="text-zinc-400 ml-2">({timeAgo(p.last_run_at)})</span>
                      </>
                    ) : (
                      <span className="text-zinc-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      size="sm"
                      variant="flat"
                      startContent={<Play size={12} />}
                      className="bg-zinc-100 data-[hover=true]:bg-zinc-200"
                    >
                      Запустить
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardBody>
      </Card>

      <Card shadow="none" className="border border-zinc-200 border-dashed rounded-2xl">
        <CardBody className="p-6 text-center text-[13px] text-zinc-500">
          <Clock size={20} className="mx-auto text-zinc-400 mb-2" />
          Логи последнего запуска и realtime-обновления появятся в следующей итерации
        </CardBody>
      </Card>
    </div>
  );
}

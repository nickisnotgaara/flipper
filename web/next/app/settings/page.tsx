'use client';

import { useQuery } from '@tanstack/react-query';
import {
  Card,
  CardBody,
  CardHeader,
  Divider,
  Chip,
  Spinner,
  Button,
} from '@heroui/react';
import { Settings as SettingsIcon, Database, Server, KeyRound, Cog, ExternalLink, Check, X } from 'lucide-react';

type Stats = {
  active_total?: number;
  houses?: number;
  houses_with_coords?: number;
  deactivated_total?: number;
};

export default function SettingsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['settings-stats'],
    queryFn: async (): Promise<Stats> => {
      try {
        const r = await fetch('http://127.0.0.1:8001/api/stats', { cache: 'no-store' });
        if (!r.ok) throw new Error('bad');
        return await r.json();
      } catch {
        return {};
      }
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-4">
        <div>
          <h1 className="text-[22px] font-bold tracking-tight">Настройки</h1>
          <p className="text-[13px] text-zinc-500 mt-0.5">
            Конфиг приложения, статусы инфраструктуры, env vars
          </p>
        </div>
        <div className="flex-1" />
        <Chip size="sm" variant="flat" color="default" startContent={<SettingsIcon size={11} />}>
          <span className="text-[10px] uppercase font-semibold tracking-wider">Read-only</span>
        </Chip>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card shadow="none" className="border border-zinc-200 rounded-2xl">
          <CardHeader className="flex items-center gap-2 p-4 pb-2">
            <Database size={16} className="text-emerald-600" />
            <span className="text-[14px] font-semibold">PostgreSQL</span>
            <div className="flex-1" />
            <Chip size="sm" variant="flat" color="success" classNames={{ base: 'h-5 px-1.5' }} startContent={<Check size={10} />}>
              <span className="text-[10px] uppercase font-semibold">OK</span>
            </Chip>
          </CardHeader>
          <Divider />
          <CardBody className="p-4 space-y-2 text-[12px]">
            <Row k="Хост" v="127.0.0.1:5432" />
            <Row k="DB" v="flipper" />
            <Row k="User" v="flipper" />
            <Row k="Houses" v={isLoading ? '…' : data?.houses?.toLocaleString('ru-RU') ?? '—'} />
            <Row k="Active ads" v={isLoading ? '…' : data?.active_total?.toLocaleString('ru-RU') ?? '—'} />
            <Row k="Deactivated" v={isLoading ? '…' : data?.deactivated_total?.toLocaleString('ru-RU') ?? '—'} />
          </CardBody>
        </Card>

        <Card shadow="none" className="border border-zinc-200 rounded-2xl">
          <CardHeader className="flex items-center gap-2 p-4 pb-2">
            <Server size={16} className="text-indigo-600" />
            <span className="text-[14px] font-semibold">flippercrawl</span>
            <div className="flex-1" />
            <Chip size="sm" variant="flat" color="success" classNames={{ base: 'h-5 px-1.5' }} startContent={<Check size={10} />}>
              <span className="text-[10px] uppercase font-semibold">OK</span>
            </Chip>
          </CardHeader>
          <Divider />
          <CardBody className="p-4 space-y-2 text-[12px]">
            <Row k="URL" v="http://127.0.0.1:3002" />
            <Row k="Mode" v="static (no LLM)" />
            <Row k="Rate limit" v="12 concurrent" />
            <Row k="Auth" v="cookie-based" />
            <Row k="Anti-bot filter" v="enabled" />
            <Row k="Last scrape" v="2026-08-09 00:23" />
          </CardBody>
        </Card>

        <Card shadow="none" className="border border-zinc-200 rounded-2xl">
          <CardHeader className="flex items-center gap-2 p-4 pb-2">
            <KeyRound size={16} className="text-amber-600" />
            <span className="text-[14px] font-semibold">Filter configs</span>
            <div className="flex-1" />
            <Chip size="sm" variant="flat" color="default" classNames={{ base: 'h-5 px-1.5' }}>
              <span className="text-[10px] uppercase font-semibold">6 active</span>
            </Chip>
          </CardHeader>
          <Divider />
          <CardBody className="p-4 space-y-1.5 text-[12px]">
            {[
              { id: 1, name: 'Фильтр 1', range: 'до 2000г · районы 23-132' },
              { id: 2, name: 'Фильтр 2', range: 'от 2000г · районы 23-132' },
              { id: 3, name: 'Фильтр 3', range: 'до 2000г · районы 13-22' },
              { id: 4, name: 'Фильтр 4', range: 'от 2000г · районы 13-22' },
              { id: 5, name: 'Сигналы', range: 'опека' },
              { id: 6, name: 'Аванс', range: 'Т-банк | запрет долги' },
            ].map((f) => (
              <div key={f.id} className="flex items-center justify-between py-1 border-b border-zinc-100 last:border-0">
                <span className="text-zinc-700">{f.id}. {f.name}</span>
                <span className="text-zinc-500 text-[11px]">{f.range}</span>
              </div>
            ))}
          </CardBody>
        </Card>

        <Card shadow="none" className="border border-zinc-200 rounded-2xl">
          <CardHeader className="flex items-center gap-2 p-4 pb-2">
            <Cog size={16} className="text-zinc-500" />
            <span className="text-[14px] font-semibold">Frontend</span>
          </CardHeader>
          <Divider />
          <CardBody className="p-4 space-y-2 text-[12px]">
            <Row k="Stack" v="Next.js 14 + HeroUI + TanStack" />
            <Row k="API base" v="http://127.0.0.1:8001" />
            <Row k="Default landing" v="/dashboard" />
            <Row k="Theme" v="light" />
            <Row k="Locale" v="ru-RU" />
            <div className="pt-2">
              <Button size="sm" variant="bordered" startContent={<ExternalLink size={12} />} className="border-zinc-200">
                Открыть DEVELOPMENT.md
              </Button>
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: any }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-zinc-500">{k}</span>
      <span className="text-zinc-900 font-mono text-[11px]">{v}</span>
    </div>
  );
}

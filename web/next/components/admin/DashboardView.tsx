'use client';

import React from 'react';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  Card,
  CardBody,
  CardHeader,
  Chip,
  Button,
  Divider,
  Spinner,
} from '@heroui/react';
import {
  TrendingUp,
  TrendingDown,
  Plus,
  RefreshCcw,
  Play,
  Flame,
  Clock,
  Map as MapIcon,
  BarChart3,
  Activity,
  type LucideIcon,
} from 'lucide-react';
import KpiCard from './KpiCard';
import { fetchStats, type Stats } from '@/lib/api';

type ActivityKind = 'new' | 'sold' | 'price' | 'pipeline';

const ACTIVITY: {
  kind: ActivityKind;
  icon: LucideIcon;
  cls: string;
  text: string;
  when: string;
}[] = [
  { kind: 'new', icon: Plus, cls: 'bg-emerald-50 text-emerald-700', text: '12 новых объявлений', when: '2 мин' },
  { kind: 'sold', icon: TrendingDown, cls: 'bg-zinc-100 text-zinc-700', text: '8 объявлений снято · фильтр 1, 2, 3', when: '14 мин' },
  { kind: 'price', icon: TrendingDown, cls: 'bg-amber-50 text-amber-700', text: '−150к ₽ · Хамовники, 3к, 80м²', when: '23 мин' },
  { kind: 'new', icon: Plus, cls: 'bg-emerald-50 text-emerald-700', text: '+3 новых дома через flippercrawl', when: '1 ч' },
  { kind: 'price', icon: TrendingUp, cls: 'bg-amber-50 text-amber-700', text: '+200к ₽ · Пресненский, 2к, 56м²', when: '2 ч' },
  { kind: 'pipeline', icon: Activity, cls: 'bg-indigo-50 text-indigo-700', text: 'парсер cian_active завершился · +34 новых, 23 антибот', when: '3 ч' },
];

const HOT_HOUSES = [
  { rank: 1, addr: 'Москва, ул. Льва Толстого, 7', count: 12 },
  { rank: 2, addr: 'Москва, Ленинский пр-кт, 32', count: 9 },
  { rank: 3, addr: 'Москва, ул. 1905 года, 9с1', count: 7 },
  { rank: 4, addr: 'Москва, Хорошёвское ш., 12а', count: 6 },
  { rank: 5, addr: 'Москва, пр-кт 60-летия Октября, 3к1', count: 5 },
  { rank: 6, addr: 'Москва, Зелёный пр-кт, 18', count: 4 },
  { rank: 7, addr: 'Москва, ул. Академика Королёва, 12', count: 4 },
];

const QUICK = [
  { label: 'Карта', sub: 'Все маркеры, drill-down', icon: MapIcon, cls: 'bg-rose-50 text-rose-600', href: '/map' },
  {
    label: 'Таблицы',
    sub: 'FILTERS, Offers, Balans и др.',
    icon: BarChart3,
    cls: 'bg-indigo-50 text-indigo-700',
    href: 'http://217.149.23.102:8484/o/flipper/em6piHbbtWXq3oyLYRahnd/p/1?table=Houses3',
    external: true,
  },
];

function formatNum(n: number): string {
  return n.toLocaleString('ru-RU');
}

export default function DashboardView() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchStats()
      .then((s) => {
        if (!cancelled) {
          setStats(s);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-start gap-4">
        <div>
          <h1 className="text-[22px] font-bold tracking-tight">Дашборд</h1>
          <p className="text-[13px] text-zinc-500 mt-0.5">
            Обзор активности и быстрый доступ к секциям
          </p>
        </div>
        <div className="flex-1" />
        <Button
          variant="bordered"
          size="sm"
          startContent={<RefreshCcw size={14} />}
          className="border-zinc-200"
        >
          Обновить
        </Button>
        <Button
          color="default"
          size="sm"
          startContent={<Play size={14} />}
          className="bg-zinc-900 text-white data-[hover=true]:bg-zinc-800"
        >
          Запустить парсер
        </Button>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          label="Активных объявлений"
          value={loading ? '…' : formatNum(stats?.active_total ?? 0)}
          accent="rose"
          meta={[
            { text: '↑ 12 за сегодня', tone: 'up' },
            { text: `с авансом ${formatNum(stats?.active_unlinked ?? 0)}` },
          ]}
          spark="0,20 10,18 20,22 30,15 40,17 50,12 60,14 70,8 80,10"
        />
        <KpiCard
          label="Снято за неделю"
          value="380"
          accent="ink"
          meta={[{ text: '↓ 24 vs прошлая неделя', tone: 'down' }]}
          spark="0,10 10,12 20,8 30,15 40,12 50,18 60,15 70,20 80,18"
        />
        <KpiCard
          label="Домов на карте"
          value={loading ? '…' : formatNum(stats?.houses_with_coords ?? 0)}
          accent="indigo"
          meta={[
            { text: `${formatNum(stats?.houses_with_coords ?? 0)} с координатами` },
            {
              text: stats
                ? `${Math.round(((stats.houses_with_coords || 0) / Math.max(1, stats.houses)) * 100)}%`
                : '—',
            },
          ]}
          spark="0,25 10,24 20,22 30,18 40,15 50,12 60,8 70,5 80,3"
        />
        <KpiCard
          label="Среднее дней на рынке"
          value="31"
          accent="warn"
          meta={[{ text: 'медиана 18' }, { text: 'P75 = 64' }]}
          spark="0,18 10,16 20,17 30,12 40,14 50,11 60,15 70,10 80,13"
        />
      </div>

      {/* Activity + Hot houses */}
      <div className="grid grid-cols-1 lg:grid-cols-[1.4fr_1fr] gap-5">
        <Card shadow="none" className="border border-zinc-200 rounded-2xl">
          <CardHeader className="flex items-center gap-2 p-5 pb-3">
            <Clock size={16} className="text-emerald-600" />
            <span className="text-[14px] font-semibold">Последние изменения</span>
            <div className="flex-1" />
            <Button size="sm" variant="light" className="text-zinc-500">
              Все →
            </Button>
          </CardHeader>
          <Divider />
          <CardBody className="p-2">
            <div className="space-y-0.5">
              {ACTIVITY.map((a, i) => {
                const Icon = a.icon;
                return (
                  <div
                    key={i}
                    className="flex items-center gap-2.5 py-2 px-3 rounded-lg hover:bg-zinc-50"
                  >
                    <div
                      className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${a.cls}`}
                    >
                      <Icon size={14} />
                    </div>
                    <div className="flex-1 min-w-0 text-[13px]">
                      <span className="text-zinc-900 font-medium">{a.text}</span>
                    </div>
                    <div className="text-[11px] text-zinc-400 shrink-0 tabular-nums">
                      {a.when}
                    </div>
                  </div>
                );
              })}
            </div>
          </CardBody>
        </Card>

        <Card shadow="none" className="border border-zinc-200 rounded-2xl">
          <CardHeader className="flex items-center gap-2 p-5 pb-3">
            <Flame size={16} className="text-rose-600" />
            <span className="text-[14px] font-semibold">Горячие дома</span>
            <div className="flex-1" />
            <Button size="sm" variant="light" className="text-zinc-500">
              Все →
            </Button>
          </CardHeader>
          <Divider />
          <CardBody className="p-2">
            <div className="space-y-0.5">
              {HOT_HOUSES.map((h) => (
                <div
                  key={h.rank}
                  className="flex items-center gap-2.5 px-3 py-1.5 rounded-lg cursor-pointer hover:bg-zinc-50"
                >
                  <div className="w-5 h-5 rounded-md bg-zinc-100 flex items-center justify-center text-[10px] font-bold text-zinc-500 tabular-nums">
                    {h.rank}
                  </div>
                  <div className="flex-1 min-w-0 text-[13px] font-medium truncate">
                    {h.addr}
                  </div>
                  <Chip
                    size="sm"
                    variant="flat"
                    color="danger"
                    classNames={{ base: 'h-5 px-2' }}
                  >
                    <span className="text-[10px] font-bold">{h.count}</span>
                  </Chip>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      </div>

      {/* Quick links */}
      <div>
        <div className="text-[11px] uppercase tracking-wider text-zinc-500 font-semibold mb-2">
          Быстрый доступ
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {QUICK.map((q) => {
            const Icon = q.icon;
            const sharedProps = q.external
              ? { as: 'a' as const, href: q.href, target: '_blank', rel: 'noopener noreferrer' }
              : { as: Link as React.ElementType, href: q.href };
            return (
              <Card
                key={q.label}
                shadow="none"
                isPressable
                {...sharedProps}
                className="border border-zinc-200 hover:border-zinc-900 transition-colors"
              >
                <CardBody className="p-3.5">
                  <div
                    className={`w-8 h-8 rounded-lg flex items-center justify-center mb-2 ${q.cls}`}
                  >
                    <Icon size={16} />
                  </div>
                  <div className="text-[13px] font-semibold">{q.label}</div>
                  <div className="text-[11px] text-zinc-500">{q.sub}</div>
                </CardBody>
              </Card>
            );
          })}
        </div>
      </div>

      {/* Footer */}
      {stats && (
        <div className="text-[11px] text-zinc-400 text-center pt-4">
          Данные обновлены {new Date().toLocaleTimeString('ru-RU')} ·{' '}
          {formatNum(stats.houses_with_deactivated)} домов с деактивированными
        </div>
      )}
    </div>
  );
}
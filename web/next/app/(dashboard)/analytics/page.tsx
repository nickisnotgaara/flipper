'use client';

import { useQuery } from '@tanstack/react-query';
import {
  Card,
  CardBody,
  CardHeader,
  Spinner,
  Chip,
} from '@heroui/react';
import { BarChart3, TrendingUp } from 'lucide-react';

// Simple inline-SVG bar chart (no chart library)
function BarChart({
  data,
  max,
  color = '#10b981',
  height = 120,
}: {
  data: { label: string; value: number }[];
  max?: number;
  color?: string;
  height?: number;
}) {
  const m = max ?? Math.max(...data.map((d) => d.value), 1);
  return (
    <div className="flex items-end gap-2" style={{ height }}>
      {data.map((d) => {
        const h = (d.value / m) * (height - 20);
        return (
          <div key={d.label} className="flex-1 flex flex-col items-center gap-1">
            <div className="text-[10px] text-zinc-500 tabular-nums">
              {d.value.toLocaleString('ru-RU')}
            </div>
            <div
              className="w-full rounded-t transition-all"
              style={{
                height: `${Math.max(2, h)}px`,
                background: color,
                opacity: 0.85,
              }}
            />
            <div className="text-[10px] text-zinc-500 truncate max-w-full">{d.label}</div>
          </div>
        );
      })}
    </div>
  );
}

// Donut chart
function Donut({
  segments,
  size = 140,
}: {
  segments: { label: string; value: number; color: string }[];
  size?: number;
}) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  const r = 50;
  const c = 2 * Math.PI * r;
  let off = 0;
  return (
    <div className="flex items-center gap-4">
      <svg width={size} height={size} viewBox="0 0 120 120" className="shrink-0">
        <circle cx="60" cy="60" r={r} fill="none" stroke="#f4f4f5" strokeWidth="14" />
        {segments.map((s) => {
          const len = (s.value / total) * c;
          const seg = (
            <circle
              key={s.label}
              cx="60"
              cy="60"
              r={r}
              fill="none"
              stroke={s.color}
              strokeWidth="14"
              strokeDasharray={`${len} ${c - len}`}
              strokeDashoffset={-off}
              transform="rotate(-90 60 60)"
            />
          );
          off += len;
          return seg;
        })}
        <text x="60" y="58" textAnchor="middle" className="text-zinc-900" fontSize="18" fontWeight="700">
          {total.toLocaleString('ru-RU')}
        </text>
        <text x="60" y="76" textAnchor="middle" className="text-zinc-500" fontSize="10">
          всего
        </text>
      </svg>
      <div className="space-y-1.5 flex-1 min-w-0">
        {segments.map((s) => (
          <div key={s.label} className="flex items-center gap-2 text-[12px]">
            <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: s.color }} />
            <span className="text-zinc-600 truncate flex-1">{s.label}</span>
            <span className="text-zinc-900 font-semibold tabular-nums">
              {s.value.toLocaleString('ru-RU')}
            </span>
            <span className="text-zinc-400 text-[10px] tabular-nums w-9 text-right">
              {((s.value / total) * 100).toFixed(0)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// Sparkline
function Sparkline({ data, color = '#6366f1', width = 280, height = 60 }: { data: number[]; color?: string; width?: number; height?: number }) {
  if (data.length < 2) return null;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * width;
      const y = height - ((v - min) / range) * (height - 8) - 4;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

export default function AnalyticsPage() {
  // Hardcoded sample data (mock) — Phase 6 will replace with /api/analytics/* endpoints
  const rooms = [
    { label: 'Студия', value: 142 },
    { label: '1к', value: 1820 },
    { label: '2к', value: 2105 },
    { label: '3к', value: 980 },
    { label: '4к+', value: 180 },
  ];

  const districts = [
    { label: 'ЦАО', value: 850, color: '#10b981' },
    { label: 'САО', value: 520, color: '#6366f1' },
    { label: 'ЮАО', value: 780, color: '#f59e0b' },
    { label: 'ЮЗАО', value: 460, color: '#f43f5e' },
    { label: 'ЗАО', value: 640, color: '#0ea5e9' },
    { label: 'СВАО', value: 590, color: '#a855f7' },
    { label: 'ВАО', value: 720, color: '#ec4899' },
    { label: 'СЗАО', value: 360, color: '#14b8a6' },
    { label: 'Новая Москва', value: 307, color: '#84cc16' },
  ];

  const daysDist = [
    { label: '1-7', value: 920 },
    { label: '8-14', value: 1480 },
    { label: '15-30', value: 1620 },
    { label: '31-60', value: 880 },
    { label: '61-90', value: 240 },
    { label: '90+', value: 87 },
  ];

  const priceBuckets = [
    { label: '<5М', value: 320 },
    { label: '5-8М', value: 1180 },
    { label: '8-12М', value: 1620 },
    { label: '12-20М', value: 1380 },
    { label: '20-30М', value: 520 },
    { label: '30М+', value: 207 },
  ];

  const weeklySold = [12, 18, 24, 31, 22, 28, 35, 41, 38, 33, 29, 36, 44, 52, 48];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-bold tracking-tight">Аналитика</h1>
        <p className="text-[13px] text-zinc-500 mt-0.5">
          Распределения и тренды по 5 227 активным объявлениям
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* By rooms */}
        <Card shadow="none" className="border border-zinc-200 rounded-2xl">
          <CardHeader className="flex items-center gap-2 p-4 pb-2">
            <BarChart3 size={16} className="text-emerald-600" />
            <span className="text-[14px] font-semibold">По комнатам</span>
            <div className="flex-1" />
            <Chip size="sm" variant="flat" color="success" classNames={{ base: 'h-5 px-1.5' }}>
              <span className="text-[10px] uppercase font-semibold">5 227</span>
            </Chip>
          </CardHeader>
          <CardBody className="p-4">
            <BarChart data={rooms} color="#10b981" />
          </CardBody>
        </Card>

        {/* By district donut */}
        <Card shadow="none" className="border border-zinc-200 rounded-2xl">
          <CardHeader className="flex items-center gap-2 p-4 pb-2">
            <BarChart3 size={16} className="text-indigo-600" />
            <span className="text-[14px] font-semibold">По округам</span>
          </CardHeader>
          <CardBody className="p-4">
            <Donut segments={districts} />
          </CardBody>
        </Card>

        {/* Days on market */}
        <Card shadow="none" className="border border-zinc-200 rounded-2xl">
          <CardHeader className="flex items-center gap-2 p-4 pb-2">
            <BarChart3 size={16} className="text-amber-600" />
            <span className="text-[14px] font-semibold">Дней на рынке</span>
            <div className="flex-1" />
            <Chip size="sm" variant="flat" color="warning" classNames={{ base: 'h-5 px-1.5' }}>
              <span className="text-[10px] uppercase font-semibold">медиана 18д</span>
            </Chip>
          </CardHeader>
          <CardBody className="p-4">
            <BarChart data={daysDist} color="#f59e0b" height={140} />
          </CardBody>
        </Card>

        {/* Price buckets */}
        <Card shadow="none" className="border border-zinc-200 rounded-2xl">
          <CardHeader className="flex items-center gap-2 p-4 pb-2">
            <BarChart3 size={16} className="text-rose-600" />
            <span className="text-[14px] font-semibold">Распределение по цене</span>
            <div className="flex-1" />
            <Chip size="sm" variant="flat" color="danger" classNames={{ base: 'h-5 px-1.5' }}>
              <span className="text-[10px] uppercase font-semibold">медиана 9.8М</span>
            </Chip>
          </CardHeader>
          <CardBody className="p-4">
            <BarChart data={priceBuckets} color="#f43f5e" height={140} />
          </CardBody>
        </Card>

        {/* Time series full width */}
        <Card shadow="none" className="border border-zinc-200 rounded-2xl lg:col-span-2">
          <CardHeader className="flex items-center gap-2 p-4 pb-2">
            <TrendingUp size={16} className="text-emerald-600" />
            <span className="text-[14px] font-semibold">Снято в неделю · последние 15 недель</span>
            <div className="flex-1" />
            <Chip size="sm" variant="flat" color="success" classNames={{ base: 'h-5 px-1.5' }}>
              <span className="text-[10px] uppercase font-semibold">тренд ↑</span>
            </Chip>
          </CardHeader>
          <CardBody className="p-4">
            <Sparkline data={weeklySold} color="#10b981" width={760} height={100} />
            <div className="mt-2 flex items-center justify-between text-[10px] text-zinc-400 px-1">
              <span>15 нед назад</span>
              <span>сейчас</span>
            </div>
          </CardBody>
        </Card>
      </div>

      <div className="text-[11px] text-zinc-400 text-center pt-2">
        Charts построены на mock-данных · в Phase 6 заменю на /api/analytics/* с реальной агрегацией из БД
      </div>
    </div>
  );
}

'use client';

import { ArrowUp, ArrowDown, type LucideIcon } from 'lucide-react';
import { Card, CardBody } from '@heroui/react';

type Accent = 'rose' | 'ink' | 'indigo' | 'warn' | 'emerald';

const ACCENT_BAR: Record<Accent, string> = {
  rose: 'bg-rose-500',
  ink: 'bg-zinc-700',
  indigo: 'bg-indigo-500',
  warn: 'bg-amber-500',
  emerald: 'bg-emerald-500',
};

const ACCENT_DOT: Record<Accent, string> = {
  rose: 'bg-rose-500',
  ink: 'bg-zinc-700',
  indigo: 'bg-indigo-500',
  warn: 'bg-amber-500',
  emerald: 'bg-emerald-500',
};

const ACCENT_STROKE: Record<Accent, string> = {
  rose: 'stroke-rose-500',
  ink: 'stroke-zinc-500',
  indigo: 'stroke-indigo-500',
  warn: 'stroke-amber-500',
  emerald: 'stroke-emerald-500',
};

export type KpiCardProps = {
  label: string;
  value: number | string;
  meta?: { text: string; tone?: 'up' | 'down' | 'neutral' }[];
  accent?: Accent;
  /** Inline SVG polyline points (viewBox 0 0 80 30, normalized). */
  spark?: string;
  loading?: boolean;
};

function fmtVal(v: number | string): string {
  if (typeof v === 'string') return v;
  return v.toLocaleString('ru-RU');
}

export default function KpiCard({
  label,
  value,
  meta = [],
  accent = 'ink',
  spark,
  loading,
}: KpiCardProps) {
  return (
    <Card
      shadow="none"
      className="relative border border-zinc-200 rounded-2xl overflow-hidden"
    >
      <div className={`absolute top-0 left-0 right-0 h-0.5 ${ACCENT_BAR[accent]}`} />

      <CardBody className="p-4">
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-zinc-500 font-semibold">
          <span className={`w-1.5 h-1.5 rounded-full ${ACCENT_DOT[accent]}`} />
          {label}
        </div>

        {loading ? (
          <div className="h-8 mt-2 w-24 bg-zinc-100 rounded animate-pulse" />
        ) : (
          <div className="text-[28px] font-bold tracking-tight mt-1.5 tabular-nums leading-none">
            {fmtVal(value)}
          </div>
        )}

        {meta.length > 0 && (
          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-zinc-500">
            {meta.map((m, i) => (
              <span key={i} className="flex items-center gap-0.5">
                {m.tone === 'up' && <ArrowUp size={10} className="text-emerald-600" />}
                {m.tone === 'down' && <ArrowDown size={10} className="text-rose-600" />}
                <span
                  className={
                    m.tone === 'up'
                      ? 'text-emerald-600 font-semibold'
                      : m.tone === 'down'
                      ? 'text-rose-600 font-semibold'
                      : ''
                  }
                >
                  {m.text}
                </span>
                {i < meta.length - 1 && (
                  <span className="text-zinc-300 ml-1.5">·</span>
                )}
              </span>
            ))}
          </div>
        )}
      </CardBody>

      {spark && (
        <svg
          className="absolute bottom-0 right-0 w-20 h-7 opacity-30 pointer-events-none"
          viewBox="0 0 80 30"
          preserveAspectRatio="none"
        >
          <polyline
            points={spark}
            fill="none"
            strokeWidth="1.5"
            className={ACCENT_STROKE[accent]}
          />
        </svg>
      )}
    </Card>
  );
}

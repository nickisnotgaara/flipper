'use client';

import { Button, Chip } from '@heroui/react';
import { X } from 'lucide-react';
import type { FilterDef } from './FilterPanel';
import { describeValue } from './FilterPanel';

type Params = Record<string, string>;

type Props = {
  filters: FilterDef[];
  params: Params;
  onChange: (key: string, value: string | undefined) => void;
  onReset: () => void;
};

/**
 * Renders one chip per active filter. For `multi` we explode the CSV
 * into N separate chips so the user can remove individual values
 * (e.g. "Комнат 2" without also dropping "Комнат 3").
 *
 * `range-min`/`range-max` are rendered as a single chip per axis that
 * mentions both ends, e.g. "Цена 5М — 15М".
 */
export default function ActiveFilterChips({ filters, params, onChange, onReset }: Props) {
  const chips: Array<{ key: string; subKey?: string; label: string; onRemove: () => void }> = [];

  for (const f of filters) {
    const v = params[f.key];
    if (v == null || v === '') continue;

    if (f.kind === 'multi' || f.kind === 'select') {
      const list = v.split(',').filter(Boolean);
      list.forEach((val, i) => {
        chips.push({
          key: `${f.key}-${i}`,
          subKey: val,
          label: `${f.label}: ${describeValue(f, val)}`,
          onRemove: () => {
            const next = list.filter((_, j) => j !== i);
            onChange(f.key, next.length ? next.join(',') : undefined);
          },
        });
      });
      continue;
    }

    if (f.kind === 'range-min' || f.kind === 'range-max') {
      // Pair up _min / _max into one chip per axis.
      if (f.key.endsWith('_min')) {
        const col = f.key.slice(0, -4);
        const partner = filters.find((x) => x.key === `${col}_max`);
        const minV = v;
        const maxV = partner ? params[partner.key] : undefined;
        const label = formatRangeLabel(f, minV, maxV);
        if (!label) continue;
        chips.push({
          key: col,
          label,
          onRemove: () => {
            onChange(f.key, undefined);
            if (partner) onChange(partner.key, undefined);
          },
        });
      }
      // skip _max (handled by _min partner)
      continue;
    }

    // toggle / single
    chips.push({
      key: f.key,
      label: `${f.label}: ${describeValue(f, v)}`,
      onRemove: () => onChange(f.key, undefined),
    });
  }

  if (chips.length === 0) return null;

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className="text-[11px] text-default-500 font-semibold uppercase tracking-wider mr-1">
        Фильтры
      </span>
      {chips.map((c) => (
        <Chip
          key={c.key}
          size="sm"
          variant="flat"
          color="primary"
          onClose={c.onRemove}
          classNames={{
            base: 'h-6 px-1.5 bg-primary-50',
            content: 'text-[11px] text-primary-700 font-medium pl-1 pr-0',
            closeButton: 'ml-1 mr-0.5 w-4 h-4 min-w-4 text-primary-400 data-[hover=true]:bg-primary-100 data-[hover=true]:text-primary-700',
          }}
        >
          {c.label}
        </Chip>
      ))}
      <Button
        size="sm"
        variant="light"
        onPress={onReset}
        className="text-default-500 data-[hover=true]:text-default-900 h-6 px-2 min-w-0 text-[11px]"
      >
        Сбросить все
      </Button>
    </div>
  );
}

function formatRangeLabel(f: FilterDef, minV: string | undefined, maxV: string | undefined): string | null {
  if (!minV && !maxV) return null;
  const fmt = (n: string) => {
    const num = Number(n);
    if (Number.isNaN(num)) return n;
    if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(num % 1_000_000 === 0 ? 0 : 1)}М`;
    if (num >= 1_000) return `${(num / 1_000).toFixed(0)}к`;
    return String(num);
  };
  const name =
    f.group === 'Цена' || f.label.toLowerCase().includes('цен')
      ? 'Цена'
      : f.group === 'Площадь' || f.label.toLowerCase().includes('площ')
        ? 'Площадь'
        : f.group === 'Срок' || f.label.toLowerCase().includes('дн')
          ? 'Дней'
          : f.label;
  const unit = f.unit || '';
  if (minV && maxV) return `${name} ${fmt(minV)} — ${fmt(maxV)}${unit ? ' ' + unit : ''}`;
  if (minV) return `${name} от ${fmt(minV)}${unit ? ' ' + unit : ''}`;
  return `${name} до ${fmt(maxV!)}${unit ? ' ' + unit : ''}`;
}

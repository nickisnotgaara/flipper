'use client';

import { Chip, Button } from '@heroui/react';
import { describeValue, type FilterDef } from './FilterPanel';

type Params = Record<string, string>;

type Props = {
  filters: FilterDef[];
  params: Params;
  onChange: (key: string, value: string | undefined) => void;
  onReset: () => void;
};

/**
 * Active filter chips. Each chip has an × to remove that filter.
 * Range filters (min/max pair) collapse into a single chip.
 * Multi filters explode into one chip per selected value so the user
 * can drop just one option (e.g. "Комнат 2" without also dropping "3").
 */
export default function ActiveFilterChips({ filters, params, onChange, onReset }: Props) {
  const chips: Array<{ key: string; label: string; onRemove: () => void }> = [];

  for (const f of filters) {
    const v = params[f.key];
    if (v == null || v === '') continue;

    if (f.kind === 'multi' || f.kind === 'select') {
      const list = v.split(',').filter(Boolean);
      list.forEach((val, i) => {
        chips.push({
          key: `${f.key}-${i}`,
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
      continue;
    }

    chips.push({
      key: f.key,
      label: `${f.label}: ${describeValue(f, v)}`,
      onRemove: () => onChange(f.key, undefined),
    });
  }

  if (chips.length === 0) return null;

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {chips.map((c) => (
        <Chip
          key={c.key}
          size="sm"
          variant="flat"
          color="primary"
          onClose={c.onRemove}
          classNames={{
            base: 'h-7',
            content: '!text-[12px] !font-medium !pl-1 !pr-0.5',
            closeButton: '!ml-1 !mr-0.5 !text-[var(--accent-ink)] data-[hover=true]:!bg-[var(--accent-soft)]',
          }}
        >
          {c.label}
        </Chip>
      ))}
      <Button
        size="sm"
        variant="light"
        onPress={onReset}
        className="!h-7 !px-2 !min-w-0 !text-[12px] !text-[var(--ink-mute)] data-[hover=true]:!text-[var(--accent)]"
      >
        Сбросить
      </Button>
    </div>
  );
}

function formatRangeLabel(f: FilterDef, minV: string | undefined, maxV: string | undefined): string | null {
  if (!minV && !maxV) return null;
  const fmt = (n: string) => {
    const num = Number(n);
    if (Number.isNaN(num)) return n;
    if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(num % 1_000_000 === 0 ? 0 : 1)} млн`;
    if (num >= 1_000) return `${(num / 1_000).toFixed(0)} тыс`;
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
  if (minV && maxV) return `${name} ${fmt(minV)} — ${fmt(maxV)}`;
  if (minV) return `${name} от ${fmt(minV)}`;
  return `${name} до ${fmt(maxV!)}`;
}

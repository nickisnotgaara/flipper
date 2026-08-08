'use client';

import { useMemo } from 'react';
import {
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerFooter,
  DrawerHeader,
  Button,
  Input,
  Switch,
  Checkbox,
  Divider,
  Chip,
} from '@heroui/react';
import { Sliders, RotateCcw, Check } from 'lucide-react';

// FilterDef — same shape as the DataTable expects. Re-export so
// pages that import from DataTable don't need a second import line.
export type FilterDef = {
  key: string;
  label: string;
  group?: string; // section header in the panel
  kind: 'multi' | 'range-min' | 'range-max' | 'toggle' | 'select';
  options?: { value: string; label: string }[];
  toggleOn?: string;
  placeholder?: string;
  /** for `range-min`/`range-max`: show as price/currency (₽ suffix) */
  unit?: string;
};

type Params = Record<string, string>;

type Props = {
  isOpen: boolean;
  onOpenChange: (v: boolean) => void;
  filters: FilterDef[];
  params: Params;
  onChange: (key: string, value: string | undefined) => void;
  onReset: () => void;
};

// Compute the active count for the badge on the toolbar button.
export function countActiveFilters(filters: FilterDef[], params: Params): number {
  let n = 0;
  for (const f of filters) {
    const v = params[f.key];
    if (v == null || v === '') continue;
    if (f.kind === 'multi' || f.kind === 'select') {
      const items = v.split(',').filter(Boolean);
      if (items.length) n += 1;
    } else {
      n += 1;
    }
  }
  return n;
}

// Pretty-print a filter value for the active-chip and panel headers.
function describeValue(def: FilterDef, v: string): string {
  if (def.kind === 'multi' || def.kind === 'select') {
    const list = v.split(',').filter(Boolean);
    if (def.options) {
      const labels = list.map((x) => {
        const o = def.options!.find((o) => o.value === x);
        return o ? o.label : x;
      });
      return labels.join(', ');
    }
    return list.join(', ');
  }
  if (def.kind === 'toggle') {
    return v === (def.toggleOn || 'true') ? 'да' : 'нет';
  }
  if (def.unit) return `${v} ${def.unit}`;
  return v;
}

// Find the "partner" of a range-min / range-max filter so they can
// be rendered as a single grouped control with two inputs.
function findRangePartner(
  filters: FilterDef[],
  key: string,
): { partner?: FilterDef; col?: string } {
  if (key.endsWith('_min')) {
    const col = key.slice(0, -4);
    const partner = filters.find((f) => f.key === `${col}_max`);
    return { partner, col };
  }
  if (key.endsWith('_max')) {
    const col = key.slice(0, -4);
    const partner = filters.find((f) => f.key === `${col}_min`);
    return { partner, col };
  }
  return {};
}

// Group filters by their `group` (or by kind fallback) and
// collapse `range-min`/`range-max` pairs into one logical group.
type Group = {
  title: string;
  controls: Array<
    | { kind: 'multi'; def: FilterDef }
    | { kind: 'toggle'; def: FilterDef }
    | { kind: 'range-pair'; min: FilterDef; max: FilterDef; col: string }
    | { kind: 'single'; def: FilterDef }
  >;
};

function buildGroups(filters: FilterDef[]): Group[] {
  const order: string[] = [];
  const buckets: Record<string, Group> = {};
  const seen = new Set<string>();

  for (const f of filters) {
    if (seen.has(f.key)) continue;
    const groupTitle = f.group || (f.kind === 'toggle' ? 'Дополнительно' : 'Параметры');
    if (!buckets[groupTitle]) {
      buckets[groupTitle] = { title: groupTitle, controls: [] };
      order.push(groupTitle);
    }

    if ((f.kind === 'range-min' || f.kind === 'range-max') && f.key.endsWith('_min')) {
      const col = f.key.slice(0, -4);
      const max = filters.find((x) => x.key === `${col}_max`);
      if (max) {
        seen.add(f.key);
        seen.add(max.key);
        buckets[groupTitle].controls.push({ kind: 'range-pair', min: f, max, col });
        continue;
      }
    }
    if ((f.kind === 'range-min' || f.kind === 'range-max') && f.key.endsWith('_max')) {
      const col = f.key.slice(0, -4);
      const min = filters.find((x) => x.key === `${col}_min`);
      if (min) {
        // already handled when we iterated `min`
        continue;
      }
    }

    seen.add(f.key);
    if (f.kind === 'multi') buckets[groupTitle].controls.push({ kind: 'multi', def: f });
    else if (f.kind === 'toggle') buckets[groupTitle].controls.push({ kind: 'toggle', def: f });
    else buckets[groupTitle].controls.push({ kind: 'single', def: f });
  }

  return order.map((t) => buckets[t]);
}

export default function FilterPanel({
  isOpen,
  onOpenChange,
  filters,
  params,
  onChange,
  onReset,
}: Props) {
  const groups = useMemo(() => buildGroups(filters), [filters]);
  const active = useMemo(() => countActiveFilters(filters, params), [filters, params]);

  return (
    <Drawer
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      placement="right"
      size="sm"
      backdrop="opaque"
      isDismissable
      classNames={{
        wrapper: 'z-[1100]',
        base: 'rounded-none',
        body: 'p-0',
      }}
    >
      <DrawerContent>
        {() => (
          <>
            <DrawerHeader className="flex items-center gap-2 border-b border-default-200 px-5 py-3.5">
              <Sliders size={16} className="text-default-700" />
              <span className="text-[14px] font-semibold">Фильтры</span>
              {active > 0 && (
                <Chip
                  size="sm"
                  variant="flat"
                  color="primary"
                  classNames={{ base: 'h-5 px-1.5 ml-1' }}
                >
                  <span className="text-[10px] font-bold">{active}</span>
                </Chip>
              )}
              <div className="flex-1" />
              {active > 0 && (
                <Button
                  size="sm"
                  variant="light"
                  startContent={<RotateCcw size={12} />}
                  onPress={onReset}
                  className="text-default-500 data-[hover=true]:text-default-900"
                >
                  Сбросить
                </Button>
              )}
            </DrawerHeader>

            <DrawerBody className="bg-default-50 p-0">
              <div className="divide-y divide-default-200 bg-white">
                {groups.map((g) => (
                  <div key={g.title} className="px-5 py-4">
                    <div className="text-[10px] uppercase tracking-wider text-default-500 font-semibold mb-3">
                      {g.title}
                    </div>
                    <div className="space-y-4">
                      {g.controls.map((c) => {
                        if (c.kind === 'range-pair') {
                          return (
                            <RangePair
                              key={c.col}
                              min={c.min}
                              max={c.max}
                              col={c.col}
                              params={params}
                              onChange={onChange}
                            />
                          );
                        }
                        if (c.kind === 'multi') {
                          return (
                            <MultiControl
                              key={c.def.key}
                              def={c.def}
                              value={params[c.def.key]}
                              onChange={(v) => onChange(c.def.key, v)}
                            />
                          );
                        }
                        if (c.kind === 'toggle') {
                          return (
                            <ToggleControl
                              key={c.def.key}
                              def={c.def}
                              value={params[c.def.key]}
                              onChange={(v) => onChange(c.def.key, v)}
                            />
                          );
                        }
                        return (
                          <SingleControl
                            key={c.def.key}
                            def={c.def}
                            value={params[c.def.key]}
                            onChange={(v) => onChange(c.def.key, v)}
                          />
                        );
                      })}
                    </div>
                  </div>
                ))}

                {groups.length === 0 && (
                  <div className="px-5 py-10 text-center text-[13px] text-default-500">
                    Нет доступных фильтров
                  </div>
                )}
              </div>
            </DrawerBody>

            <DrawerFooter className="border-t border-default-200 px-5 py-3 gap-2">
              <Button
                variant="light"
                onPress={onReset}
                isDisabled={active === 0}
                className="text-default-600"
              >
                Сбросить все
              </Button>
              <div className="flex-1" />
              <Button
                variant="flat"
                onPress={() => onOpenChange(false)}
                className="bg-default-100 data-[hover=true]:bg-default-200"
              >
                Закрыть
              </Button>
              <Button
                color="default"
                onPress={() => onOpenChange(false)}
                startContent={<Check size={14} />}
                className="bg-zinc-900 text-white data-[hover=true]:bg-zinc-800"
              >
                Применить
              </Button>
            </DrawerFooter>
          </>
        )}
      </DrawerContent>
    </Drawer>
  );
}

// ---------- individual controls -----------------------------------------

function MultiControl({
  def,
  value,
  onChange,
}: {
  def: FilterDef;
  value: string | undefined;
  onChange: (v: string | undefined) => void;
}) {
  const active = (value || '').split(',').filter(Boolean);
  const activeSet = new Set(active);
  return (
    <div>
      <div className="text-[12px] text-default-700 font-medium mb-1.5">{def.label}</div>
      <div className="flex flex-wrap gap-1.5">
        {def.options?.map((o) => {
          const on = activeSet.has(o.value);
          return (
            <button
              key={o.value}
              type="button"
              onClick={() => {
                const next = new Set(activeSet);
                if (on) next.delete(o.value);
                else next.add(o.value);
                onChange(next.size ? Array.from(next).join(',') : undefined);
              }}
              className={[
                'h-7 px-2.5 rounded-md text-[12px] font-medium border transition-colors',
                on
                  ? 'bg-zinc-900 text-white border-zinc-900'
                  : 'bg-white text-zinc-700 border-zinc-200 hover:border-zinc-400',
              ].join(' ')}
            >
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ToggleControl({
  def,
  value,
  onChange,
}: {
  def: FilterDef;
  value: string | undefined;
  onChange: (v: string | undefined) => void;
}) {
  const on = value === (def.toggleOn || 'true');
  return (
    <div className="flex items-center justify-between gap-3">
      <div>
        <div className="text-[12px] text-default-700 font-medium">{def.label}</div>
      </div>
      <Switch
        size="sm"
        isSelected={on}
        onValueChange={(v) => onChange(v ? def.toggleOn || 'true' : undefined)}
      />
    </div>
  );
}

function SingleControl({
  def,
  value,
  onChange,
}: {
  def: FilterDef;
  value: string | undefined;
  onChange: (v: string | undefined) => void;
}) {
  return (
    <div>
      <div className="text-[12px] text-default-700 font-medium mb-1.5">{def.label}</div>
      <Input
        size="sm"
        type="number"
        variant="flat"
        value={value || ''}
        onValueChange={(v) => onChange(v || undefined)}
        placeholder={def.placeholder || def.label}
        classNames={{
          inputWrapper:
            'h-8 min-h-8 bg-default-100 data-[hover=true]:bg-default-200/70 group-data-[focus=true]:bg-white border border-transparent group-data-[focus=true]:border-default-400',
        }}
      />
    </div>
  );
}

function RangePair({
  min,
  max,
  col,
  params,
  onChange,
}: {
  min: FilterDef;
  max: FilterDef;
  col: string;
  params: Params;
  onChange: (key: string, value: string | undefined) => void;
}) {
  const minV = params[min.key];
  const maxV = params[max.key];
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1.5">
        <div className="text-[12px] text-default-700 font-medium">
          {min.group === 'Цена' || min.label.toLowerCase().includes('цен')
            ? 'Цена'
            : min.group === 'Площадь' || min.label.toLowerCase().includes('площ')
              ? 'Площадь'
              : min.group === 'Срок' || min.label.toLowerCase().includes('дн')
                ? 'Дней на сайте'
                : min.label}
        </div>
        {min.unit && <div className="text-[10px] text-default-400">{min.unit}</div>}
      </div>
      <div className="flex items-center gap-1.5">
        <Input
          size="sm"
          type="number"
          variant="flat"
          value={minV || ''}
          onValueChange={(v) => onChange(min.key, v || undefined)}
          placeholder={min.placeholder || 'от'}
          classNames={{
            base: 'flex-1',
            inputWrapper:
              'h-8 min-h-8 bg-default-100 data-[hover=true]:bg-default-200/70 group-data-[focus=true]:bg-white border border-transparent group-data-[focus=true]:border-default-400',
          }}
        />
        <span className="text-default-300 text-[12px]">—</span>
        <Input
          size="sm"
          type="number"
          variant="flat"
          value={maxV || ''}
          onValueChange={(v) => onChange(max.key, v || undefined)}
          placeholder={max.placeholder || 'до'}
          classNames={{
            base: 'flex-1',
            inputWrapper:
              'h-8 min-h-8 bg-default-100 data-[hover=true]:bg-default-200/70 group-data-[focus=true]:bg-white border border-transparent group-data-[focus=true]:border-default-400',
          }}
        />
      </div>
    </div>
  );
}

export { describeValue, findRangePartner };

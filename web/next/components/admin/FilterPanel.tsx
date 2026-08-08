'use client';

import { useMemo } from 'react';
import {
  Drawer,
  DrawerBody,
  DrawerContent,
  Button,
  Input,
  Switch,
} from '@heroui/react';
import { X, RotateCcw } from 'lucide-react';

export type FilterDef = {
  key: string;
  label: string;
  group?: string;
  kind: 'multi' | 'range-min' | 'range-max' | 'toggle' | 'select';
  options?: { value: string; label: string }[];
  toggleOn?: string;
  placeholder?: string;
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

function findRangePartner(filters: FilterDef[], key: string) {
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
      if (min) continue;
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
        base: '!bg-[var(--paper-card)]',
      }}
    >
      <DrawerContent>
        {(onClose) => (
          <div className="flex flex-col h-full bg-[var(--paper-card)]">
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--rule)]">
              <div>
                <h2 className="text-[16px] font-semibold text-[var(--ink)]">Фильтры</h2>
                <p className="text-[12px] text-[var(--ink-mute)] mt-0.5">
                  {active > 0
                    ? `Активно: ${active}`
                    : 'Ничего не применено'}
                </p>
              </div>
              <Button
                isIconOnly
                size="sm"
                variant="light"
                onPress={onClose}
                aria-label="Закрыть"
              >
                <X size={16} />
              </Button>
            </div>

            {/* Body */}
            <DrawerBody className="flex-1 overflow-y-auto px-5 py-5">
              <div className="space-y-6">
                {groups.map((g) => (
                  <div key={g.title}>
                    <h3 className="text-[11px] uppercase tracking-wider text-[var(--ink-mute)] font-semibold mb-2.5">
                      {g.title}
                    </h3>
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
                  <div className="text-center text-[13px] text-[var(--ink-mute)] py-8">
                    Нет параметров для отбора
                  </div>
                )}
              </div>
            </DrawerBody>

            {/* Footer */}
            <div className="border-t border-[var(--rule)] px-5 py-3 flex items-center gap-2">
              <Button
                size="md"
                variant="light"
                startContent={<RotateCcw size={13} strokeWidth={2} />}
                onPress={onReset}
                isDisabled={active === 0}
              >
                Сбросить
              </Button>
              <div className="flex-1" />
              <Button size="md" color="primary" onPress={onClose}>
                Готово
              </Button>
            </div>
          </div>
        )}
      </DrawerContent>
    </Drawer>
  );
}

// ---------- individual controls -----------------------------------------

function MultiControl({ def, value, onChange }: { def: FilterDef; value: string | undefined; onChange: (v: string | undefined) => void }) {
  const active = (value || '').split(',').filter(Boolean);
  const activeSet = new Set(active);
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="text-[12px] text-[var(--ink-soft)] font-medium">{def.label}</span>
        {active.length > 0 && (
          <span className="text-[11px] text-[var(--ink-mute)] tabular-nums">
            {active.length} из {def.options?.length || 0}
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {def.options?.map((o) => {
          const on = activeSet.has(o.value);
          return (
            <Button
              key={o.value}
              size="sm"
              radius="sm"
              variant={on ? 'solid' : 'bordered'}
              onPress={() => {
                const next = new Set(activeSet);
                if (on) next.delete(o.value);
                else next.add(o.value);
                onChange(next.size ? Array.from(next).join(',') : undefined);
              }}
              aria-pressed={on}
              className={on
                ? '!min-w-[40px] !h-8 !px-3 !text-[13px] !font-medium !bg-[var(--ink)] !text-[var(--paper)] !border-[var(--ink)] data-[hover=true]:!bg-[var(--ink-soft)]'
                : '!min-w-[40px] !h-8 !px-3 !text-[13px] !font-medium !bg-[var(--paper-card)] !text-[var(--ink-soft)] !border-[var(--rule)] data-[hover=true]:!border-[var(--ink)] data-[hover=true]:!text-[var(--ink)]'}
            >
              {o.label}
            </Button>
          );
        })}
      </div>
    </div>
  );
}

function ToggleControl({ def, value, onChange }: { def: FilterDef; value: string | undefined; onChange: (v: string | undefined) => void }) {
  const on = value === (def.toggleOn || 'true');
  return (
    <div className="flex items-center justify-between gap-3 py-1">
      <span className="text-[13px] text-[var(--ink)]">{def.label}</span>
      <Switch
        size="sm"
        isSelected={on}
        onValueChange={(v) => onChange(v ? def.toggleOn || 'true' : undefined)}
      />
    </div>
  );
}

function SingleControl({ def, value, onChange }: { def: FilterDef; value: string | undefined; onChange: (v: string | undefined) => void }) {
  return (
    <div>
      <div className="text-[12px] text-[var(--ink-soft)] font-medium mb-1">{def.label}</div>
      <Input
        size="md"
        type="number"
        variant="bordered"
        radius="sm"
        value={value || ''}
        onValueChange={(v) => onChange(v || undefined)}
        placeholder={def.placeholder || def.label}
      />
    </div>
  );
}

function RangePair({ min, max, col, params, onChange }: { min: FilterDef; max: FilterDef; col: string; params: Params; onChange: (key: string, value: string | undefined) => void }) {
  const minV = params[min.key];
  const maxV = params[max.key];
  const label =
    min.group === 'Цена' || min.label.toLowerCase().includes('цен')
      ? 'Цена, ₽'
      : min.group === 'Площадь' || min.label.toLowerCase().includes('площ')
        ? 'Площадь, м²'
        : min.group === 'Срок' || min.label.toLowerCase().includes('дн')
          ? 'Дней'
          : min.label;
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-[12px] text-[var(--ink-soft)] font-medium">{label}</span>
        {(minV || maxV) && (
          <span className="text-[11px] text-[var(--ink-mute)] tabular-nums">
            {minV || '·'} — {maxV || '·'}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Input
          size="md"
          type="number"
          variant="bordered"
          radius="sm"
          value={minV || ''}
          onValueChange={(v) => onChange(min.key, v || undefined)}
          placeholder={min.placeholder || 'от'}
        />
        <span className="text-[12px] text-[var(--ink-faint)] select-none">—</span>
        <Input
          size="md"
          type="number"
          variant="bordered"
          radius="sm"
          value={maxV || ''}
          onValueChange={(v) => onChange(max.key, v || undefined)}
          placeholder={max.placeholder || 'до'}
        />
      </div>
    </div>
  );
}

export { describeValue, findRangePartner };

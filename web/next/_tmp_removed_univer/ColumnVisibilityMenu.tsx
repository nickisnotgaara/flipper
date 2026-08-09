'use client';

import {
  Button,
  Dropdown,
  DropdownTrigger,
  DropdownMenu,
  DropdownItem,
} from '@heroui/react';
import { Columns, Check, Minus } from 'lucide-react';
import type { ColumnDef } from '@tanstack/react-table';

type Props<T> = {
  columns: ColumnDef<T, any>[];
  visible: Record<string, boolean>;
  onChange: (next: Record<string, boolean>) => void;
};

/**
 * Linear-style column picker. Opens a DropdownMenu where each
 * column is a `DropdownItem` with a `startContent` checkbox. Clicking
 * toggles visibility; the icon on the right swaps between ✓ (visible)
 * and a blank circle.
 *
 * Styled as a printed checklist: paper background, sienna check, mono
 * font for column names. Each item has a tiny checkbox at left and a
 * ✓ icon at right.
 */
export default function ColumnVisibilityMenu<T extends Record<string, any>>({
  columns,
  visible,
  onChange,
}: Props<T>) {
  const items = columns
    .map((c) => ({
      id: (c.id as string) || (c as any).accessorKey,
      header: typeof c.header === 'string' ? c.header : c.id,
    }))
    .filter((x) => x.id && x.header);

  if (items.length === 0) return null;

  const visibleCount = items.filter((i) => visible[i.id] !== false).length;
  const someOff = visibleCount < items.length;

  return (
    <Dropdown placement="bottom-end" backdrop="opaque" closeOnSelect={false} radius="sm">
      <DropdownTrigger>
        <Button
          size="md"
          variant="bordered"
          radius="sm"
          startContent={<Columns size={14} strokeWidth={2} />}
        >
          Колонки{someOff ? ` · ${visibleCount}/${items.length}` : ''}
        </Button>
      </DropdownTrigger>
      <DropdownMenu
        aria-label="Видимые колонки"
        variant="flat"
        disallowEmptySelection
        selectionMode="multiple"
        selectedKeys={new Set(items.filter((i) => visible[i.id] !== false).map((i) => i.id))}
        onSelectionChange={(keys) => {
          const next: Record<string, boolean> = {};
          for (const i of items) {
            const present = (keys as Set<string>).has(i.id);
            next[i.id] = !present ? false : true;
          }
          onChange(next);
        }}
        classNames={{
          base: '!bg-[var(--paper-card)] !border !border-[var(--rule)] !rounded-md !shadow-xl !p-1 min-w-[240px]',
          list: '!gap-0',
        }}
        itemClasses={{
          base: '!rounded-md data-[hover=true]:!bg-[var(--paper-2)] data-[selected=true]:!bg-[var(--paper-2)] gap-2',
          title: '!text-[13px] !text-[var(--ink)]',
        }}
      >
        {items.map((i) => {
          const on = visible[i.id] !== false;
          return (
            <DropdownItem
              key={i.id}
              startContent={
                <span
                  className={[
                    'w-4 h-4 flex items-center justify-center border rounded transition-colors',
                    on
                      ? 'bg-[var(--ink)] border-[var(--ink)] text-[var(--paper)]'
                      : 'bg-[var(--paper-card)] border-[var(--rule)]',
                  ].join(' ')}
                >
                  {on && <Check size={10} strokeWidth={3} />}
                </span>
              }
              endContent={
                <span className="text-[11px] text-[var(--ink-faint)] tabular-nums">
                  {on ? 'вкл' : '—'}
                </span>
              }
            >
              {i.header}
            </DropdownItem>
          );
        })}
      </DropdownMenu>
    </Dropdown>
  );
}

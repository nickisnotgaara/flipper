'use client';

import {
  Button,
  Dropdown,
  DropdownTrigger,
  DropdownMenu,
  DropdownItem,
  Checkbox,
} from '@heroui/react';
import { Columns, Check, X } from 'lucide-react';
import type { ColumnDef } from '@tanstack/react-table';

type Props<T> = {
  columns: ColumnDef<T, any>[];
  visible: Record<string, boolean>;
  onChange: (next: Record<string, boolean>) => void;
};

/**
 * Linear/Vercel-style column picker. Opens a DropdownMenu where each
 * column is a `DropdownItem` with a `startContent` checkbox. Clicking
 * toggles visibility; the icon on the right swaps between ✓ (visible)
 * and a blank circle.
 *
 * Columns without a `header` and `id` are skipped (e.g. internal
 * "actions" or selection columns).
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

  const allOn = items.every((i) => visible[i.id] !== false);
  const someOff = items.some((i) => visible[i.id] === false);

  return (
    <Dropdown placement="bottom-end" backdrop="opaque" closeOnSelect={false}>
      <DropdownTrigger>
        <Button
          size="sm"
          variant="bordered"
          startContent={<Columns size={14} />}
          className="border-default-200 data-[hover=true]:bg-default-100"
        >
          Колонки{someOff ? ` · ${items.length - items.filter((i) => visible[i.id] === false).length}/${items.length}` : ''}
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
            // Keep the user's explicit `false` only if they hid it. Once
            // they re-enable, we drop the key so it falls back to the
            // default (true) — keeps the URL clean.
            next[i.id] = !present ? false : true;
          }
          onChange(next);
        }}
        className="min-w-[220px]"
      >
        {items.map((i) => (
          <DropdownItem
            key={i.id}
            // We render our own checkbox-like row, so suppress the
            // default DropdownItem startContent to avoid double icons.
            startContent={
              <span
                className={[
                  'w-4 h-4 rounded-[4px] border flex items-center justify-center transition-colors',
                  visible[i.id] !== false
                    ? 'bg-zinc-900 border-zinc-900 text-white'
                    : 'bg-white border-default-300',
                ].join(' ')}
              >
                {visible[i.id] !== false && <Check size={11} strokeWidth={3} />}
              </span>
            }
            classNames={{ base: 'rounded-md', title: 'text-[12.5px]' }}
          >
            {i.header}
          </DropdownItem>
        ))}
      </DropdownMenu>
    </Dropdown>
  );
}

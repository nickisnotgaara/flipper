'use client';

import { useEffect, useRef, useState } from 'react';
import { Input, Select, SelectItem, Spinner } from '@heroui/react';
import { Check, X } from 'lucide-react';

// ----------------------------------------------------------------
// EditableCell — inline cell editor à la Google Sheets.
// Click (or dblclick for numeric) → input → Enter / blur to save,
// Esc to cancel. Uses a `mutate(value)` callback for optimistic updates
// and a `isSaving` flag for visual feedback during PATCH.
// ----------------------------------------------------------------

export type EditableCellProps = {
  value: unknown;
  rowId: string | number;
  columnId: string;
  /** Where to send the PATCH. The DataTable wires this once for the table. */
  apiBase: string;
  tableName: string;
  /** While the PATCH is in flight the cell shows a spinner. */
  isSaving?: boolean;
  /** Optimistic update — DataTable updates the row in cache immediately. */
  mutate: (rowId: string | number, columnId: string, value: unknown) => void;
  type?: 'text' | 'number' | 'integer' | 'select';
  options?: { value: string; label: string }[];
  placeholder?: string;
  align?: 'left' | 'right' | 'center';
  /** Stop the cell from going into edit mode (read-only display). */
  disabled?: boolean;
};

export default function EditableCell({
  value,
  rowId,
  columnId,
  apiBase,
  tableName,
  isSaving,
  mutate,
  type = 'text',
  options,
  placeholder,
  align = 'left',
  disabled,
}: EditableCellProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string>(formatInitial(value, type));
  const inputRef = useRef<HTMLInputElement>(null);

  // Re-sync the draft if the cell value changes from outside (e.g. a refetch).
  useEffect(() => {
    if (!editing) setDraft(formatInitial(value, type));
  }, [value, editing, type]);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  const commit = async () => {
    const next = type === 'number' || type === 'integer' ? Number(draft) : draft;
    if (type === 'integer' && !Number.isInteger(next)) {
      // Bad input — revert.
      setEditing(false);
      return;
    }
    if (next === value) {
      setEditing(false);
      return;
    }
    setEditing(false);
    // Optimistic
    mutate(rowId, columnId, next);
    try {
      await fetch(`${apiBase}/api/tables/${tableName}/rows/${rowId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [columnId]: next }),
      });
    } catch {
      // The DataTable's mutate callback can decide whether to revert on error.
      // For now we leave the optimistic value in place; a refetch will fix it.
    }
  };

  const cancel = () => {
    setDraft(formatInitial(value, type));
    setEditing(false);
  };

  if (disabled) {
    return <Display value={value} align={align} placeholder={placeholder} />;
  }

  if (editing) {
    if (type === 'select' && options) {
      return (
        <div className="-mx-1">
          <Select
            size="sm"
            variant="bordered"
            radius="sm"
            selectedKeys={new Set([String(value ?? draft)])}
            onSelectionChange={(keys) => {
              const v = Array.from(keys as Set<string>)[0];
              if (v) {
                setDraft(v);
                // commit immediately on select
                mutate(rowId, columnId, v);
                fetch(`${apiBase}/api/tables/${tableName}/rows/${rowId}`, {
                  method: 'PATCH',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ [columnId]: v }),
                }).catch(() => {});
                setEditing(false);
              }
            }}
            aria-label="Редактирование"
            classNames={{
              trigger:
                '!h-7 !min-h-7 !bg-[var(--paper-card)] !border-[var(--accent)] data-[open=true]:!border-[var(--accent)]',
              value: '!text-[13px] !text-[var(--ink)] pr-2',
              selectorIcon: '!text-[var(--ink-mute)]',
              popoverContent: '!bg-[var(--paper-card)]',
            }}
          >
            {options.map((o) => (
              <SelectItem key={o.value} className="!text-[13px]">
                {o.label}
              </SelectItem>
            ))}
          </Select>
        </div>
      );
    }
    return (
      <div className="flex items-center gap-1 -mx-1">
        <Input
          ref={inputRef}
          size="sm"
          variant="bordered"
          radius="sm"
          type={type === 'number' || type === 'integer' ? 'number' : 'text'}
          value={draft}
          onValueChange={setDraft}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit();
            else if (e.key === 'Escape') cancel();
          }}
          onBlur={commit}
          aria-label="Редактирование"
          classNames={{
            base: 'w-full',
            mainWrapper: '!h-7',
            inputWrapper:
              '!h-7 !min-h-7 !bg-[var(--paper-card)] !border-[var(--accent)] data-[hover=true]:!bg-[var(--paper-card)] group-data-[focus=true]:!bg-[var(--paper-card)]',
            input: `!text-[13px] !text-[var(--ink)] ${align === 'right' ? '!text-right' : ''}`,
          }}
        />
        {isSaving ? (
          <Spinner size="sm" className="!w-3 !h-3" />
        ) : (
          <span className="text-[var(--ink-faint)] flex-shrink-0">
            <Check size={12} strokeWidth={2.5} />
          </span>
        )}
      </div>
    );
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={(e) => {
        e.stopPropagation();
        setEditing(true);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          setEditing(true);
        }
      }}
      className={[
        'w-full text-left px-1.5 -mx-1.5 py-0.5 rounded transition-colors cursor-text',
        'hover:bg-[var(--paper-2)] focus:bg-[var(--paper-2)] focus:outline-none',
        'min-h-[24px]',
        align === 'right' ? 'text-right tabular-nums' : '',
      ].join(' ')}
    >
      <Display value={value} align={align} placeholder={placeholder} />
    </div>
  );
}

function formatInitial(value: unknown, type: 'text' | 'number' | 'integer' | 'select'): string {
  if (value == null || value === '') return '';
  if (type === 'number' || type === 'integer') {
    return typeof value === 'number' ? String(value) : String(Number(value) || 0);
  }
  return String(value);
}

function Display({
  value,
  align,
  placeholder,
}: {
  value: unknown;
  align: 'left' | 'right' | 'center';
  placeholder?: string;
}) {
  if (value == null || value === '') {
    return <span className="text-[var(--ink-faint)] italic">{placeholder ?? '—'}</span>;
  }
  return (
    <span className={align === 'right' ? 'tabular-nums' : ''}>{String(value)}</span>
  );
}

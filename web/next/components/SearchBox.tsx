'use client';

import { useEffect, useRef, useState } from 'react';
import { Input, Spinner, Chip, ScrollShadow } from '@heroui/react';
import { fetchSuggest, type SuggestItem } from '@/lib/api';
import { useDebounce } from '@/lib/useDebounce';

// Wait this long after the last keystroke before firing the suggest
// request. 400ms is the UX sweet spot — feels instant but doesn't
// fire on every keystroke.
const SUGGEST_DEBOUNCE_MS = 400;

/** Yandex-suggest search input. On click of a row, parent decides what
 *  to do (fly the map, open the panel, show a toast). DB-matched rows
 *  (have a `house` from the backend) sort to the top so Enter on the
 *  first row opens a real house 99% of the time. */
export default function SearchBox({
  onPick,
}: {
  onPick: (item: SuggestItem) => void;
}) {
  const [q, setQ] = useState('');
  const [items, setItems] = useState<SuggestItem[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);
  const reqIdRef = useRef(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // The query that actually triggers a request. Lags behind `q` by
  // SUGGEST_DEBOUNCE_MS — the request only fires once the user has
  // stopped typing for that long.
  const debouncedQ = useDebounce(q, SUGGEST_DEBOUNCE_MS);

  // Race-safe suggest fetch. Driven by the debounced query.
  useEffect(() => {
    if (debouncedQ.trim().length < 2) {
      setItems([]);
      setOpen(false);
      setLoading(false);
      return;
    }
    setLoading(true);
    const myReq = ++reqIdRef.current;
    (async () => {
      try {
        const raw = await fetchSuggest(debouncedQ.trim());
        if (myReq !== reqIdRef.current) return;
        // DB hits first — same reason as before: pressing Enter on the
        // top row should open a real house, not a Yandex-only ghost.
        const data = [...raw].sort((a, b) => {
          const aHit = a.house && a.house.id ? 1 : 0;
          const bHit = b.house && b.house.id ? 1 : 0;
          return bHit - aHit;
        });
        setItems(data);
        setOpen(data.length > 0);
        setActiveIdx(0);
      } catch {
        if (myReq === reqIdRef.current) {
          setItems([]);
          setOpen(false);
        }
      } finally {
        if (myReq === reqIdRef.current) setLoading(false);
      }
    })();
  }, [debouncedQ]);

  // Close dropdown on outside click + ESC.
  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        inputRef.current?.blur();
      }
    };
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, []);

  const handlePick = (it: SuggestItem) => {
    onPick(it);
    setQ(it.title);
    setOpen(false);
    inputRef.current?.blur();
  };

  return (
    <div ref={wrapRef} className="relative flex-1 min-w-0 max-w-md">
      <Input
        ref={inputRef}
        value={q}
        onValueChange={setQ}
        onFocus={() => items.length > 0 && setOpen(true)}
        onKeyDown={(e: any) => {
          if (!open) return;
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActiveIdx((i) => Math.min(items.length - 1, i + 1));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActiveIdx((i) => Math.max(0, i - 1));
          } else if (e.key === 'Enter') {
            e.preventDefault();
            const it = items[activeIdx];
            if (it) handlePick(it);
          }
        }}
        placeholder="Поиск адреса…"
        size="sm"
        variant="flat"
        radius="md"
        startContent={
          <svg viewBox="0 0 24 24" width={16} height={16} fill="none" stroke="currentColor" strokeWidth={2} className="text-default-500">
            <circle cx="11" cy="11" r="7" />
            <path d="M21 21l-4.3-4.3" strokeLinecap="round" />
          </svg>
        }
        endContent={
          loading ? (
            <Spinner size="sm" color="primary" />
          ) : q ? (
            <button
              onClick={() => {
                setQ('');
                setItems([]);
                setOpen(false);
                inputRef.current?.focus();
              }}
              className="w-5 h-5 rounded-full text-default-500 hover:bg-default-100 hover:text-default-700 flex items-center justify-center text-xs"
              aria-label="очистить"
            >
              ✕
            </button>
          ) : null
        }
        classNames={{
          base: 'w-full',
          inputWrapper: 'bg-default-100 data-[hover=true]:bg-default-200 group-data-[focus=true]:bg-white transition-colors shadow-none',
          input: 'text-sm placeholder:text-default-500',
        }}
      />

      {open && items.length > 0 && (
        <div
          className={`
            absolute left-0 right-0 top-full mt-1.5 z-[1100]
            bg-white shadow-panel rounded-2xl border border-default-200
            overflow-hidden animate-fade-in
          `}
        >
          <ScrollShadow className="max-h-[min(420px,60vh)]" hideScrollBar>
            <ul className="py-1" role="listbox">
              {items.map((it, i) => {
                const hit = !!(it.house && it.house.id);
                return (
                  <li
                    key={`${it.formatted_address}-${i}`}
                    role="option"
                    aria-selected={i === activeIdx}
                    onMouseDown={(e) => {
                      // mousedown (not click) so the input blur doesn't
                      // race the click and close the dropdown first.
                      e.preventDefault();
                      handlePick(it);
                    }}
                    onMouseEnter={() => setActiveIdx(i)}
                    className={`
                      flex items-start gap-2.5 px-3 py-2 cursor-pointer transition
                      border-b border-default-100 last:border-b-0
                      ${i === activeIdx ? 'bg-primary-50' : 'hover:bg-default-100/60'}
                    `}
                  >
                    <div className="mt-0.5 shrink-0">
                      {hit ? (
                        <Chip
                          size="sm"
                          variant="flat"
                          color="success"
                          radius="full"
                          classNames={{ base: 'h-5 min-w-0 px-0', content: 'px-1 text-[10px] font-bold' }}
                          title="Есть в базе"
                        >
                          ✓
                        </Chip>
                      ) : (
                        <span
                          className="inline-flex w-5 h-5 items-center justify-center rounded-full bg-default-100 text-default-500 text-xs"
                          title="Только в Yandex"
                        >
                          ·
                        </span>
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm text-foreground leading-snug truncate">
                        {it.title}
                      </div>
                      <div className="text-[11px] text-default-500 truncate">
                        {it.subtitle}
                        {it.house && (
                          <span className="ml-1.5 text-default-400">· {it.house.address}</span>
                        )}
                      </div>
                    </div>
                    {it.distance_m != null && (
                      <div className="text-[10px] text-default-400 shrink-0 mt-1 tabular-nums">
                        {it.distance_m < 1000
                          ? `${Math.round(it.distance_m)} м`
                          : `${(it.distance_m / 1000).toFixed(1)} км`}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </ScrollShadow>
        </div>
      )}
    </div>
  );
}

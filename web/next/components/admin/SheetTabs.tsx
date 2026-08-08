'use client';

/**
 * SheetTabs — Excel / Google-Sheets style sheet tab strip.
 *
 * Renders at the BOTTOM of the workbook (the user explicitly asked for
 * tabs-down, not tabs-up). The active sheet visually "pops up" from the
 * strip — same idea as Excel: white face, no bottom border, sits on top
 * of the strip's top border; inactive tabs sit half a pixel lower with
 * a fully rounded box and a muted background.
 *
 * Tabs are stateful via `selected` + `onSelect` (the parent owns the
 * active id, the URL owns it via `?tab=X` in /tables). Each tab can
 * show a small count chip on the right.
 *
 * The "+" button at the start is decorative — the workbook has a fixed
 * set of sheets for now. The left/right scroll buttons appear when the
 * strip overflows (which won't happen with 4 sheets but is cheap to
 * keep for the future when we add more).
 */

import { useEffect, useRef, useState } from 'react';

export type SheetTab = {
  id: string;
  label: string;
  count?: number;
};

type Props = {
  sheets: SheetTab[];
  selected: string;
  onSelect: (id: string) => void;
  /** Optional right-side content (e.g. "всего N строк · 4 листа"). */
  rightAdornment?: React.ReactNode;
};

export default function SheetTabs({ sheets, selected, onSelect, rightAdornment }: Props) {
  const stripRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  // Recompute scroll arrows whenever the active tab changes (because
  // we auto-scroll the strip to keep the active tab visible) or when
  // the viewport changes.
  useEffect(() => {
    const el = stripRef.current;
    if (!el) return;
    const update = () => {
      setCanScrollLeft(el.scrollLeft > 4);
      setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 4);
    };
    update();
    el.addEventListener('scroll', update, { passive: true });
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => {
      el.removeEventListener('scroll', update);
      ro.disconnect();
    };
  }, [sheets.length]);

  // Scroll the active tab into view when it changes.
  useEffect(() => {
    const el = stripRef.current;
    if (!el) return;
    const active = el.querySelector<HTMLButtonElement>(`[data-sheet-id="${selected}"]`);
    if (!active) return;
    const a = active.offsetLeft;
    const w = active.offsetWidth;
    if (a < el.scrollLeft + 8) {
      el.scrollTo({ left: a - 8, behavior: 'smooth' });
    } else if (a + w > el.scrollLeft + el.clientWidth - 8) {
      el.scrollTo({ left: a + w - el.clientWidth + 8, behavior: 'smooth' });
    }
  }, [selected]);

  const scrollBy = (dx: number) => {
    stripRef.current?.scrollBy({ left: dx, behavior: 'smooth' });
  };

  return (
    <div className="relative shrink-0 h-10 bg-[var(--paper-2)] border-t border-[var(--rule)] flex items-stretch">
      {/* "+" add-sheet — decorative, future use. Sits on the same baseline
          as the tabs so the strip looks like one continuous element. */}
      <div className="flex items-center pl-2 pr-1 border-r border-[var(--rule-soft)]">
        <button
          type="button"
          aria-label="Добавить лист"
          title="Добавить лист"
          className="w-7 h-7 rounded-md text-[var(--ink-mute)] hover:text-[var(--ink)] hover:bg-[var(--paper-card)] transition-colors flex items-center justify-center text-[16px] leading-none"
        >
          +
        </button>
      </div>

      {/* The strip itself. We use flex + overflow-x-auto so many tabs
          can be added later without breaking layout. Each tab is a
          real <button> (not HeroUI Button) because the tab strip sits
          in a fixed-height footer and we need full control over the
          pixel-precise "active tab pops up" effect. */}
      <div
        ref={stripRef}
        className="flex-1 min-w-0 overflow-x-auto overflow-y-hidden scrollbar-none"
        style={{ scrollbarWidth: 'none' }}
      >
        <div className="flex items-end h-full px-1 gap-px">
          {sheets.map((s) => {
            const isActive = s.id === selected;
            return (
              <button
                key={s.id}
                data-sheet-id={s.id}
                type="button"
                onClick={() => onSelect(s.id)}
                className={[
                  'group relative shrink-0 h-8 px-3.5 inline-flex items-center gap-2',
                  'text-[12.5px] font-medium tracking-tight',
                  'transition-colors',
                  isActive
                    ? // Active tab: white face, rounded top corners,
                      // bottom edge MERGES with the strip's top border
                      // (negative margin-bottom pulls it down by 1px
                      // so the strip's top border disappears under it).
                      'bg-[var(--paper-card)] text-[var(--ink)] rounded-t-md border border-[var(--rule)] border-b-0 mb-[-1px] z-10'
                    : // Inactive tab: muted pill that sits half a pixel
                      // LOWER than the active one (the active one's
                      // -1px margin-bottom creates the visual "raise").
                      'bg-transparent text-[var(--ink-mute)] hover:text-[var(--ink)] hover:bg-[var(--paper-card)]/60 rounded-t-md mb-[-1px]',
                ].join(' ')}
              >
                <span className="truncate max-w-[160px]">{s.label}</span>
                {s.count != null && (
                  <span
                    className={[
                      'inline-flex items-center justify-center min-w-[20px] h-[16px] px-1 rounded-sm text-[10px] font-mono tabular-nums',
                      isActive
                        ? 'bg-[var(--accent-soft)] text-[var(--accent-ink)]'
                        : 'bg-[var(--paper-2)] text-[var(--ink-mute)] group-hover:bg-[var(--paper-card)]',
                    ].join(' ')}
                  >
                    {s.count.toLocaleString('ru-RU')}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Right-side adornment + scroll arrows. Kept on the same line so
          the strip looks like a real workbook footer. */}
      <div className="flex items-center pr-2 pl-2 gap-1 border-l border-[var(--rule-soft)]">
        {rightAdornment}
        <button
          type="button"
          aria-label="Прокрутить влево"
          onClick={() => scrollBy(-160)}
          disabled={!canScrollLeft}
          className="w-6 h-6 rounded-md text-[var(--ink-mute)] hover:text-[var(--ink)] hover:bg-[var(--paper-card)] disabled:opacity-30 disabled:hover:bg-transparent transition-colors flex items-center justify-center"
          title="←"
        >
          ‹
        </button>
        <button
          type="button"
          aria-label="Прокрутить вправо"
          onClick={() => scrollBy(160)}
          disabled={!canScrollRight}
          className="w-6 h-6 rounded-md text-[var(--ink-mute)] hover:text-[var(--ink)] hover:bg-[var(--paper-card)] disabled:opacity-30 disabled:hover:bg-transparent transition-colors flex items-center justify-center"
          title="→"
        >
          ›
        </button>
      </div>
    </div>
  );
}

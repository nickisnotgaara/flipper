'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Map,
  BarChart3,
  Bookmark,
  Activity,
  Settings,
  Home,
  ChevronDown,
  type LucideIcon,
} from 'lucide-react';
import { useState } from 'react';
import { Button } from '@heroui/react';

type NavItem = {
  label: string;
  href: string;
  icon: LucideIcon;
  badge?: number | string;
  /** "primary" → Карта/Аналитика, the two main views. "more" → the rest,
   *  visually demoted into a collapsible bottom group. */
  group: 'primary' | 'more';
};

// ---- Primary nav: just Карта + Аналитика (Grist iframe). -----------------
// Аналитика — iframe с двумя табами: "Данные парсинга" и "База архивов".
// Все таблицы (FILTERS, Аванс, Аванс_Продано, Продано, Balans, Offers_Parser,
// Signals_Parser + CianSold, DomclickSold, WinnersNovostroiki, WinnersVtorichka,
// FlatInfoHouses, HousesAll) живут в Grist.

const PRIMARY: NavItem[] = [
  { label: 'Карта', href: '/map', icon: Map, group: 'primary' },
  { label: 'Аналитика', href: '/analytics', icon: BarChart3, group: 'primary', badge: 'Grist' },
];

const MORE: NavItem[] = [
  { label: 'Дашборд', href: '/dashboard', icon: Home, group: 'more' },
  { label: 'Фильтры', href: '/filters', icon: Bookmark, group: 'more' },
  { label: 'Pipeline', href: '/pipeline', icon: Activity, group: 'more' },
  { label: 'Настройки', href: '/settings', icon: Settings, group: 'more' },
];

function fmt(n: number | string): string {
  if (typeof n === 'string') return n;
  return n.toLocaleString('ru-RU');
}

export default function Sidebar() {
  const pathname = usePathname() || '/';
  // "More" group: starts open only if the user is currently on a more-page.
  const [moreOpen, setMoreOpen] = useState(MORE.some((m) => pathname === m.href));

  const isActive = (item: NavItem) =>
    pathname === item.href || pathname.startsWith(item.href + '/');

  const renderItem = (item: NavItem) => {
    const Icon = item.icon;
    const active = isActive(item);
    return (
      <Button
        key={item.href}
        as={Link}
        href={item.href}
        variant="light"
        radius="sm"
        className={[
          'w-full justify-start gap-2.5 h-9 px-3 !rounded-md text-[13px]',
          active
            ? '!bg-[var(--ink)] !text-[var(--paper)] data-[hover=true]:!bg-[var(--ink-soft)] font-medium'
            : '!text-[var(--ink-soft)] data-[hover=true]:!bg-[var(--paper-2)] data-[hover=true]:!text-[var(--ink)]',
        ].join(' ')}
        startContent={<Icon size={15} strokeWidth={2} />}
      >
        <span className="flex-1 text-left">{item.label}</span>
        {item.badge != null && (
          <span
            className={[
              'text-[10.5px] tabular-nums',
              active ? 'text-[var(--paper)] opacity-70' : 'text-[var(--ink-faint)]',
            ].join(' ')}
          >
            {fmt(item.badge)}
          </span>
        )}
      </Button>
    );
  };

  return (
    <aside className="w-56 shrink-0 h-screen sticky top-0 bg-[var(--paper-card)] border-r border-[var(--rule)] flex flex-col">
      {/* Brand */}
      <Link href="/map" className="flex items-center gap-2.5 h-14 px-4 border-b border-[var(--rule)]">
        <div className="w-8 h-8 bg-[var(--ink)] rounded-md flex items-center justify-center">
          <span className="font-display text-[var(--paper)] text-[14px] font-bold leading-none">Ф</span>
        </div>
        <span className="font-display text-[15px] text-[var(--ink)] font-semibold">Flipper</span>
      </Link>

      {/* Primary nav (Карта + Аналитика) */}
      <nav className="flex-1 overflow-y-auto py-2">
        <div className="px-2 pb-1">
          {PRIMARY.map(renderItem)}
        </div>

        {/* Divider */}
        <div className="mx-3 my-2 border-t border-[var(--rule-soft)]" />

        {/* "Ещё" group — collapsed by default, opens if user is on a more-page */}
        <div className="px-2">
          <Button
            onPress={() => setMoreOpen((v) => !v)}
            variant="light"
            radius="sm"
            className="w-full justify-between gap-2 h-7 px-3 !rounded-md text-[11px] uppercase tracking-wider !text-[var(--ink-faint)] data-[hover=true]:!text-[var(--ink-soft)]"
            endContent={
              <ChevronDown
                size={11}
                strokeWidth={2}
                className={['transition-transform opacity-50', moreOpen ? 'rotate-180' : ''].join(' ')}
              />
            }
          >
            <span className="flex-1 text-left">Ещё</span>
          </Button>
          {moreOpen && (
            <div className="mt-0.5">
              {MORE.map(renderItem)}
            </div>
          )}
        </div>
      </nav>
    </aside>
  );
}

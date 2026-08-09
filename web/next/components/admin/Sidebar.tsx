'use client';

import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
import {
  Map,
  Table2,
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

type SubItem = { label: string; href: string; badge?: number | string };
type NavItem = {
  label: string;
  href: string;
  icon: LucideIcon;
  badge?: number | string;
  subItems?: SubItem[];
  /** "primary" → Карта/Таблицы, the two main views. "more" → the rest,
   *  visually demoted into a collapsible bottom group. */
  group: 'primary' | 'more';
};

// ---- Primary nav: just Карта + Таблицы (with sheet submenu). ---------------
// Everything else (Дашборд, Аналитика, Pipeline, Фильтры, Настройки) lives
// in the "more" group below, collapsed by default — they're still reachable
// but the user has to opt-in.

const PRIMARY: NavItem[] = [
  { label: 'Карта', href: '/map', icon: Map, group: 'primary' },
  {
    label: 'Таблицы',
    href: '/tables',
    icon: Table2,
    group: 'primary',
    subItems: [
      { label: 'Активные', href: '/tables?tab=active', badge: 5_227 },
      { label: 'Снято', href: '/tables?tab=sold', badge: 18_375 },
      { label: 'Скрытые', href: '/tables?tab=hidden', badge: 173_536 },
      { label: 'Дома', href: '/tables?tab=houses', badge: 30_868 },
      { label: 'FILTERS', href: '/tables?tab=filters' },
      { label: 'Аванс', href: '/tables?tab=avans' },
      { label: 'Offers_Parser', href: '/tables?tab=offers' },
    ],
  },
];

const MORE: NavItem[] = [
  { label: 'Дашборд', href: '/dashboard', icon: Home, group: 'more' },
  { label: 'Аналитика', href: '/analytics', icon: BarChart3, group: 'more' },
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
  const searchParams = useSearchParams();
  const currentTab = pathname === '/tables' ? searchParams.get('tab') || 'active' : null;
  const [tablesOpen, setTablesOpen] = useState(pathname.startsWith('/tables'));
  // "More" group: starts open only if the user is currently on a more-page.
  const [moreOpen, setMoreOpen] = useState(MORE.some((m) => pathname === m.href));

  const isActive = (item: NavItem) =>
    item.subItems
      ? pathname === '/tables' || pathname.startsWith('/tables/')
      : pathname === item.href || pathname.startsWith(item.href + '/');

  const isSubActive = (subHref: string) => {
    if (pathname !== '/tables') return false;
    const m = subHref.match(/[?&]tab=([^&]+)/);
    if (!m) return currentTab === null;
    return currentTab === m[1];
  };

  const renderItem = (item: NavItem) => {
    const Icon = item.icon;
    const active = isActive(item);

    if (item.subItems) {
      const subActive = item.subItems.some((s) => isSubActive(s.href));
      return (
        <div key={item.href}>
          <Button
            onPress={() => setTablesOpen((v) => !v)}
            variant="light"
            radius="sm"
            className={[
              'w-full justify-start gap-2.5 h-9 px-3 !rounded-md text-[13px]',
              subActive
                ? '!bg-[var(--ink)] !text-[var(--paper)] data-[hover=true]:!bg-[var(--ink-soft)] font-medium'
                : '!text-[var(--ink-soft)] data-[hover=true]:!bg-[var(--paper-2)] data-[hover=true]:!text-[var(--ink)]',
            ].join(' ')}
            startContent={<Icon size={15} strokeWidth={2} />}
            endContent={
              <ChevronDown
                size={13}
                strokeWidth={2}
                className={['transition-transform opacity-60', tablesOpen ? 'rotate-180' : ''].join(' ')}
              />
            }
          >
            {item.label}
          </Button>
          {tablesOpen && (
            <div className="ml-3 my-0.5 border-l border-[var(--rule)] pl-1">
              {item.subItems.map((sub) => {
                const subIsActive = isSubActive(sub.href);
                return (
                  <Link
                    key={sub.href}
                    href={sub.href}
                    className={[
                      'flex items-center gap-2 px-3 py-1.5 text-[12.5px] rounded-md transition-colors',
                      subIsActive
                        ? 'text-[var(--ink)] font-medium bg-[var(--paper-2)]'
                        : 'text-[var(--ink-mute)] hover:text-[var(--ink)] hover:bg-[var(--paper-2)]',
                    ].join(' ')}
                  >
                    {subIsActive && (
                      <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]" />
                    )}
                    <span className="flex-1 truncate">{sub.label}</span>
                    {sub.badge != null && (
                      <span className="text-[10.5px] text-[var(--ink-faint)] tabular-nums">
                        {fmt(sub.badge)}
                      </span>
                    )}
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      );
    }

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

      {/* Primary nav (Карта + Таблицы) */}
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

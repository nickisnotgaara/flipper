'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Home,
  Map,
  Table2,
  BarChart3,
  Bookmark,
  Activity,
  Settings,
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
  subItems?: { label: string; href: string; badge?: number | string }[];
};

const NAV: NavItem[] = [
  { label: 'Дашборд', href: '/dashboard', icon: Home },
  { label: 'Карта', href: '/map', icon: Map },
  {
    label: 'Таблицы',
    href: '/tables/active',
    icon: Table2,
    subItems: [
      { label: 'Активные', href: '/tables/active', badge: 5_227 },
      { label: 'Снято', href: '/tables/sold', badge: 18_375 },
      { label: 'Скрытые', href: '/tables/hidden', badge: 173_536 },
      { label: 'Дома', href: '/tables/houses', badge: 30_868 },
    ],
  },
  { label: 'Аналитика', href: '/analytics', icon: BarChart3 },
  { label: 'Сохранённые фильтры', href: '/filters', icon: Bookmark },
  { label: 'Pipeline', href: '/pipeline', icon: Activity },
  { label: 'Настройки', href: '/settings', icon: Settings },
];

function fmt(n: number | string): string {
  if (typeof n === 'string') return n;
  return n.toLocaleString('ru-RU');
}

export default function Sidebar() {
  const pathname = usePathname() || '/';
  const [tablesOpen, setTablesOpen] = useState(pathname.startsWith('/tables'));

  const isActive = (item: NavItem) => {
    if (item.href === '/tables/active' && pathname.startsWith('/tables')) return true;
    return pathname === item.href || pathname.startsWith(item.href + '/');
  };

  return (
    <aside className="w-60 shrink-0 h-screen sticky top-0 bg-[var(--paper-card)] border-r border-[var(--rule)] flex flex-col">
      {/* Brand */}
      <div className="px-4 pt-4 pb-3 border-b border-[var(--rule)]">
        <Link href="/dashboard" className="flex items-center gap-2.5 group">
          <div className="w-9 h-9 bg-[var(--ink)] rounded-md flex items-center justify-center group-hover:bg-[var(--ink-soft)] transition-colors">
            <span className="font-display text-[var(--paper)] text-[15px] font-bold leading-none">Ф</span>
          </div>
          <div className="flex-1 min-w-0">
            <div className="font-display text-[15px] text-[var(--ink)] font-semibold leading-none">
              Flipper
            </div>
            <div className="text-[11px] text-[var(--ink-mute)] mt-1">
              Панель управления
            </div>
          </div>
        </Link>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-2">
        {NAV.map((item) => {
          const Icon = item.icon;
          const active = isActive(item);

          if (item.subItems) {
            const subActive = item.subItems.some((s) => pathname === s.href);
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
                  <div className="ml-4 my-0.5 border-l border-[var(--rule)] pl-1">
                    {item.subItems.map((sub) => {
                      const subIsActive = pathname === sub.href;
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
        })}
      </nav>

      <div className="border-t border-[var(--rule)] px-4 py-3 flex items-center gap-2 text-[12px]">
        <span className="w-2 h-2 rounded-full bg-[var(--gain)]" />
        <span className="text-[var(--ink-soft)]">flippercrawl</span>
        <span className="flex-1" />
        <span className="text-[var(--gain)] font-medium">OK</span>
      </div>
    </aside>
  );
}

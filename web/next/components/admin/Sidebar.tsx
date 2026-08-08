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
import { Button, Chip, Divider } from '@heroui/react';

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
    <aside className="w-60 shrink-0 h-screen sticky top-0 bg-zinc-50 border-r border-zinc-200 flex flex-col">
      {/* Brand */}
      <div className="h-16 flex items-center gap-2.5 px-4 border-b border-zinc-200">
        <div className="w-8 h-8 rounded-lg bg-zinc-900 text-emerald-400 flex items-center justify-center">
          <Home size={18} strokeWidth={2.5} />
        </div>
        <div>
          <div className="text-[15px] font-bold tracking-tight leading-none">Flipper</div>
          <div className="text-[10px] text-zinc-500 mt-0.5">admin panel</div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-1">
        {NAV.map((item) => {
          const Icon = item.icon;
          const active = isActive(item);

          if (item.subItems) {
            const subActive = item.subItems.some((s) => pathname === s.href);
            return (
              <div key={item.href}>
                <Button
                  onPress={() => setTablesOpen((v) => !v)}
                  variant={subActive ? 'solid' : 'light'}
                  color={subActive ? 'default' : 'default'}
                  className={[
                    'w-full justify-start gap-2.5 h-9 px-2.5 text-[13px] font-medium',
                    subActive
                      ? 'bg-zinc-900 text-white data-[hover=true]:bg-zinc-800'
                      : 'text-zinc-700 data-[hover=true]:bg-zinc-100',
                  ].join(' ')}
                  startContent={<Icon size={16} />}
                  endContent={
                    <ChevronDown
                      size={14}
                      className={['transition-transform', tablesOpen ? 'rotate-180' : ''].join(' ')}
                    />
                  }
                >
                  {item.label}
                </Button>
                {tablesOpen && (
                  <div className="mt-1 ml-[26px] space-y-0.5">
                    {item.subItems.map((sub) => {
                      const subIsActive = pathname === sub.href;
                      return (
                        <Link
                          key={sub.href}
                          href={sub.href}
                          className={[
                            'flex items-center gap-2 px-2.5 py-1.5 rounded-md text-[12.5px]',
                            subIsActive
                              ? 'text-zinc-900 font-semibold bg-zinc-100'
                              : 'text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100',
                          ].join(' ')}
                        >
                          <span
                            className={[
                              'w-1.5 h-1.5 rounded-full',
                              subIsActive ? 'bg-emerald-500' : 'bg-zinc-300',
                            ].join(' ')}
                          />
                          <span className="flex-1">{sub.label}</span>
                          {sub.badge != null && (
                            <span className="text-[10px] text-zinc-400 font-mono tabular-nums">
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
              variant={active ? 'solid' : 'light'}
              className={[
                'w-full justify-start gap-2.5 h-9 px-2.5 text-[13px] font-medium',
                active
                  ? 'bg-zinc-900 text-white data-[hover=true]:bg-zinc-800'
                  : 'text-zinc-700 data-[hover=true]:bg-zinc-100',
              ].join(' ')}
              startContent={<Icon size={16} />}
            >
              <span className="flex-1 text-left">{item.label}</span>
              {item.badge != null && (
                <Chip
                  size="sm"
                  variant={active ? 'solid' : 'flat'}
                  className={[
                    'h-5 px-1.5 text-[10px] font-mono tabular-nums',
                    active ? 'bg-white/15 text-white' : 'bg-zinc-100 text-zinc-500',
                  ].join(' ')}
                >
                  {fmt(item.badge)}
                </Chip>
              )}
            </Button>
          );
        })}
      </nav>

      <Divider />

      {/* Status footer */}
      <div className="px-4 py-3 flex items-center gap-2 text-[11px] text-zinc-500">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shadow-[0_0_0_3px_rgba(16,185,129,0.15)]" />
        <span>flippercrawl · OK</span>
      </div>
    </aside>
  );
}

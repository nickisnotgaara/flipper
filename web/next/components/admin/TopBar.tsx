'use client';

import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ChevronRight } from 'lucide-react';
import { Navbar, NavbarContent, NavbarItem } from '@heroui/react';
import { fetchStats, type Stats } from '@/lib/api';

const ROUTE_LABELS: Record<string, string> = {
  '/dashboard': 'Дашборд',
  '/map': 'Карта',
  '/tables/active': 'Активные',
  '/tables/sold': 'Снято',
  '/tables/hidden': 'Скрытые',
  '/tables/houses': 'Дома',
  '/filters': 'Сохранённые фильтры',
  '/pipeline': 'Pipeline',
  '/settings': 'Настройки',
};

function normalize(pathname: string): string {
  return pathname.endsWith('/') && pathname.length > 1 ? pathname.slice(0, -1) : pathname;
}

function getCrumbs(pathname: string): { label: string; href: string }[] {
  const p = normalize(pathname);
  const crumbs: { label: string; href: string }[] = [
    { label: 'Flipper', href: '/dashboard' },
  ];
  if (p.startsWith('/tables')) {
    crumbs.push({ label: 'Таблицы', href: '/tables/active' });
  }
  const last = ROUTE_LABELS[p] || p;
  crumbs.push({ label: last, href: p });
  return crumbs;
}

function fmt(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toLocaleString('ru-RU');
}

export default function TopBar() {
  const pathname = usePathname() || '/';
  const [stats, setStats] = useState<Stats | null>(null);
  const crumbs = getCrumbs(pathname);

  useEffect(() => {
    let cancelled = false;
    fetchStats()
      .then((s) => {
        if (!cancelled) setStats(s);
      })
      .catch(() => {
        if (!cancelled) setStats(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Navbar
      maxWidth="full"
      isBordered
      classNames={{
        base: '!h-11 !bg-[var(--paper-card)] !border-b !border-[var(--rule)]',
        wrapper: '!h-11 !px-5 !gap-4',
      }}
    >
      <NavbarContent justify="start" className="!gap-1.5 !flex-grow-0">
        {crumbs.map((c, i) => {
          const isLast = i === crumbs.length - 1;
          return (
            <NavbarItem key={c.href} className="!flex-grow-0">
              <div className="flex items-center gap-1.5 text-[13px]">
                {isLast ? (
                  <span className="text-[var(--ink)] font-medium">{c.label}</span>
                ) : (
                  <Link
                    href={c.href}
                    className="text-[var(--ink-mute)] hover:text-[var(--ink)] transition-colors"
                  >
                    {c.label}
                  </Link>
                )}
                {!isLast && (
                  <ChevronRight size={13} className="text-[var(--ink-faint)]" strokeWidth={2} />
                )}
              </div>
            </NavbarItem>
          );
        })}
      </NavbarContent>

      <NavbarContent justify="end" className="!gap-3 !flex-grow-0">
        {stats ? (
          <NavbarItem className="!flex-grow-0">
            <div className="flex items-center gap-2.5 text-[12px]">
              <span className="flex items-center gap-1.5">
                <span className="text-[var(--ink-mute)]">Активных</span>
                <span className="text-[var(--ink)] font-semibold tabular-nums">
                  {fmt(stats.active_total)}
                </span>
              </span>
              <span className="w-px h-3 bg-[var(--rule)]" />
              <span className="flex items-center gap-1.5">
                <span className="text-[var(--ink-mute)]">Снято</span>
                <span className="text-[var(--ink-soft)] font-semibold tabular-nums">
                  {fmt(stats.deactivated_total)}
                </span>
              </span>
              <span className="w-px h-3 bg-[var(--rule)]" />
              <span className="flex items-center gap-1.5">
                <span className="text-[var(--ink-mute)]">Домов</span>
                <span className="text-[var(--ink)] font-semibold tabular-nums">
                  {fmt(stats.houses)}
                </span>
              </span>
            </div>
          </NavbarItem>
        ) : null}
      </NavbarContent>
    </Navbar>
  );
}

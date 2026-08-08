'use client';

import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Search, Bell, Home, ChevronRight } from 'lucide-react';
import { Input, Button, Chip, Navbar, NavbarContent, NavbarItem } from '@heroui/react';
import { fetchStats, type Stats } from '@/lib/api';

const ROUTE_LABELS: Record<string, string> = {
  '/dashboard': 'Дашборд',
  '/map': 'Карта',
  '/tables/active': 'Активные',
  '/tables/sold': 'Снято',
  '/tables/hidden': 'Скрытые',
  '/tables/houses': 'Дома',
  '/analytics': 'Аналитика',
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

export default function TopBar() {
  const pathname = usePathname() || '/';
  const [stats, setStats] = useState<Stats | null>(null);
  const [query, setQuery] = useState('');
  const crumbs = getCrumbs(pathname);

  useEffect(() => {
    let cancelled = false;
    fetchStats()
      .then((s) => {
        if (!cancelled) setStats(s);
      })
      .catch(() => {
        /* silent */
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
        base: 'h-12 border-b border-zinc-200 bg-white',
        wrapper: 'px-5 h-12 gap-3',
      }}
    >
      <NavbarContent justify="start" className="gap-1.5 !flex-grow-0">
        {crumbs.map((c, i) => {
          const isLast = i === crumbs.length - 1;
          return (
            <NavbarItem key={c.href} className="!flex-grow-0">
              <div className="flex items-center gap-1.5 text-[13px]">
                {i === 0 && <Home size={14} className="text-zinc-400" />}
                {isLast ? (
                  <span className="text-zinc-900 font-semibold">{c.label}</span>
                ) : (
                  <Link
                    href={c.href}
                    className="text-zinc-500 hover:text-zinc-900 transition-colors"
                  >
                    {c.label}
                  </Link>
                )}
                {!isLast && <ChevronRight size={12} className="text-zinc-300" />}
              </div>
            </NavbarItem>
          );
        })}
      </NavbarContent>

      <NavbarContent justify="end" className="gap-2 !flex-grow-0">
        <NavbarItem className="!flex-grow-0">
          <Input
            value={query}
            onValueChange={setQuery}
            placeholder="Поиск по адресу, ID, фильтру…"
            size="sm"
            radius="md"
            variant="flat"
            startContent={<Search size={14} className="text-zinc-400" />}
            classNames={{
              base: 'w-72',
              inputWrapper: 'h-8 bg-zinc-100 hover:bg-white data-[focus=true]:bg-white border border-transparent data-[focus=true]:border-emerald-500',
            }}
          />
        </NavbarItem>

        {stats && (
          <NavbarItem className="!flex-grow-0">
            <Chip
              size="sm"
              variant="flat"
              classNames={{ base: 'h-7 px-2 bg-zinc-100' }}
              startContent={
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              }
            >
              <span className="text-[11px] tabular-nums text-zinc-700">
                {stats.active_total.toLocaleString('ru-RU')} · {stats.houses.toLocaleString('ru-RU')}
              </span>
            </Chip>
          </NavbarItem>
        )}

        <NavbarItem className="!flex-grow-0">
          <Button
            isIconOnly
            size="sm"
            variant="light"
            aria-label="Уведомления"
            className="text-zinc-500 data-[hover=true]:bg-zinc-100 data-[hover=true]:text-zinc-900"
          >
            <Bell size={16} />
          </Button>
        </NavbarItem>

        <NavbarItem className="!flex-grow-0">
          <div className="w-7 h-7 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-[11px] font-bold">
            NE
          </div>
        </NavbarItem>
      </NavbarContent>
    </Navbar>
  );
}

'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Map,
  Database,
  Home,
  ExternalLink,
  type LucideIcon,
} from 'lucide-react';
import { Button } from '@heroui/react';

type NavItem = {
  label: string;
  href: string;
  icon: LucideIcon;
  badge?: number | string;
  /** External link (target=_blank) instead of Next Link. */
  external?: boolean;
};

// === Grist configuration ==================================================
// В Grist осталось 9 таблиц (см. packages/flipper_core/grist.py):
//   page 13: FILTERS (6)
//   page 14: Продано   Table1
//   page 15: Аванс     Table2
//   page 16: Balans
//   page 17: Offers_Parser
//   page 18: Signals_Parser
//   page 19: Аванс_Продано Table3
//   page 22: Активные  Active_ads
//   page 23: База домов Houses2
const GRIST_URL = 'http://localhost:8484';
const PARSING_DOC = 'mDaHoGD6yahtxaqugwr5mK';
/** Deep link to a specific Grist page (each page = one table in this doc). */
const gristLink = (docId: string, pageId: number) => `${GRIST_URL}/${docId}/flipping/p/${pageId}`;

// === Nav: Дашборд (home) + Карта + Таблицы (Grist) =========================
const NAV: NavItem[] = [
  { label: 'Дашборд', href: '/dashboard', icon: Home },
  { label: 'Карта', href: '/map', icon: Map },
  {
    label: 'Таблицы',
    href: gristLink(PARSING_DOC, 14),
    icon: Database,
    badge: 'Grist',
    external: true,
  },
];

function fmt(n: number | string): string {
  if (typeof n === 'string') return n;
  return n.toLocaleString('ru-RU');
}

export default function Sidebar() {
  const pathname = usePathname() || '/';

  const isActive = (item: NavItem) =>
    item.external ? false : pathname === item.href || pathname.startsWith(item.href + '/');

  const renderItem = (item: NavItem) => {
    const Icon = item.icon;
    const active = isActive(item);
    const className = [
      'w-full justify-start gap-2.5 h-9 px-3 !rounded-md text-[13px]',
      active
        ? '!bg-[var(--ink)] !text-[var(--paper)] data-[hover=true]:!bg-[var(--ink-soft)] font-medium'
        : '!text-[var(--ink-soft)] data-[hover=true]:!bg-[var(--paper-2)] data-[hover=true]:!text-[var(--ink)]',
    ].join(' ');
    const content = (
      <>
        <Icon size={15} strokeWidth={2} />
        <span className="flex-1 text-left">{item.label}</span>
        {item.badge != null && (
          <span
            className={[
              'text-[10.5px] tabular-nums flex items-center gap-0.5',
              active ? 'text-[var(--paper)] opacity-70' : 'text-[var(--ink-faint)]',
            ].join(' ')}
          >
            {fmt(item.badge)}
            {item.external && <ExternalLink size={9} strokeWidth={2.5} />}
          </span>
        )}
      </>
    );
    if (item.external) {
      return (
        <Button
          key={item.href}
          as="a"
          href={item.href}
          target="_blank"
          rel="noopener noreferrer"
          variant="light"
          radius="sm"
          className={className}
        >
          {content}
        </Button>
      );
    }
    return (
      <Button
        key={item.href}
        as={Link}
        href={item.href}
        variant="light"
        radius="sm"
        className={className}
      >
        {content}
      </Button>
    );
  };

  return (
    <aside className="w-56 shrink-0 h-screen sticky top-0 bg-[var(--paper-card)] border-r border-[var(--rule)] flex flex-col">
      {/* Brand */}
      <Link href="/dashboard" className="flex items-center gap-2.5 h-14 px-4 border-b border-[var(--rule)]">
        <div className="w-8 h-8 bg-[var(--ink)] rounded-md flex items-center justify-center">
          <span className="font-display text-[var(--paper)] text-[14px] font-bold leading-none">Ф</span>
        </div>
        <span className="font-display text-[15px] text-[var(--ink)] font-semibold">Flipper</span>
      </Link>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-2">
        <div className="px-2 pb-1">{NAV.map(renderItem)}</div>
      </nav>
    </aside>
  );
}

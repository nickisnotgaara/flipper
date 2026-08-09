'use client';

/**
 * /analytics — Grist self-host analytics UI.
 *
 * Вместо Univer-таблиц — две вкладки с iframe Grist:
 *   1) "Данные парсинга" — FILTERS, Аванс, Аванс_Продано, Продано, Balans, Offers_Parser, Signals_Parser
 *   2) "База архивов"   — CianSold, DomclickSold, WinnersNovostroiki, WinnersVtorichka, FlatInfoHouses, HousesAll
 *
 * `?style=singlePage` = editable, no toolbar/left menu/right creator panel.
 */

import { useState } from 'react';
import { Button } from '@heroui/react';
import {
  ExternalLink,
  RefreshCw,
  BarChart3,
  Database,
  Activity,
  Archive,
} from 'lucide-react';

const GRIST_BASE = process.env.NEXT_PUBLIC_GRIST_URL ?? 'http://127.0.0.1:8484';

const TABS = [
  {
    key: 'parsing',
    label: 'Данные парсинга',
    icon: Activity,
    docId: process.env.NEXT_PUBLIC_GRIST_DOC_PARSING ?? 'mDaHoGD6yahtxaqugwr5mK',
    badge: '7 таблиц',
  },
  {
    key: 'archives',
    label: 'База архивов',
    icon: Archive,
    docId: process.env.NEXT_PUBLIC_GRIST_DOC_ARCHIVES ?? 'kaBfATwGgUYjDa8doqMzk3',
    badge: '6 таблиц',
  },
] as const;

type TabKey = (typeof TABS)[number]['key'];

export default function AnalyticsPage() {
  const [active, setActive] = useState<TabKey>('parsing');
  const [reloadKey, setReloadKey] = useState(0);

  const current = TABS.find((t) => t.key === active) ?? TABS[0];
  const fullUrl = `${GRIST_BASE}/${current.docId}/p/1?style=singlePage&themeAppearance=light&embed=true&_=${reloadKey}`;
  const openUrl = `${GRIST_BASE}/${current.docId}`;

  return (
    <div className="flex h-screen w-screen flex-col bg-[var(--paper)]">
      <div className="flex items-center justify-between border-b border-[var(--rule)] bg-[var(--paper-card)] px-4 py-2">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-emerald-600" />
          <div className="text-sm font-medium text-[var(--ink)]">Аналитика</div>
          <span className="ml-2 rounded bg-[var(--paper-mute)] px-2 py-0.5 font-mono text-[10px] text-[var(--ink-mute)]">
            doc {current.docId.slice(0, 12)}…
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="flat"
            startContent={<Database className="h-3 w-3" />}
            onPress={() => window.open(GRIST_BASE, '_blank')}
          >
            Grist home
          </Button>
          <Button
            size="sm"
            variant="flat"
            startContent={<RefreshCw className="h-3 w-3" />}
            onPress={() => setReloadKey((k) => k + 1)}
          >
            Перезагрузить
          </Button>
          <Button
            size="sm"
            variant="flat"
            color="primary"
            startContent={<ExternalLink className="h-3 w-3" />}
            onPress={() => window.open(openUrl, '_blank')}
          >
            Открыть в Grist
          </Button>
        </div>
      </div>
      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-[var(--rule)] bg-[var(--paper-card)] px-4">
        {TABS.map((t) => {
          const Icon = t.icon;
          const isActive = t.key === active;
          return (
            <button
              key={t.key}
              onClick={() => setActive(t.key)}
              className={[
                'flex items-center gap-2 px-3 py-2 text-[13px] border-b-2 transition-colors',
                isActive
                  ? 'border-[var(--accent)] text-[var(--ink)] font-medium'
                  : 'border-transparent text-[var(--ink-mute)] hover:text-[var(--ink)]',
              ].join(' ')}
            >
              <Icon size={14} strokeWidth={2} />
              <span>{t.label}</span>
              <span className="text-[10.5px] text-[var(--ink-faint)] tabular-nums">
                {t.badge}
              </span>
            </button>
          );
        })}
      </div>
      <div className="flex-1 overflow-hidden">
        <iframe
          key={reloadKey + current.docId}
          src={fullUrl}
          title={`Grist Analytics — ${current.label}`}
          className="h-full w-full border-0"
          allow="clipboard-read; clipboard-write; fullscreen"
        />
      </div>
    </div>
  );
}

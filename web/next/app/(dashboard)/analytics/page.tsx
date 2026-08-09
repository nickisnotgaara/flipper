'use client';

/**
 * /analytics — Grist self-host analytics UI.
 *
 * Embeds the Grist document via `?style=singlePage` (editable, no chrome).
 * Doc ID is set via NEXT_PUBLIC_GRIST_DOC_ID (default = our local Flipper Main).
 *
 * NOTE: this file lives under app/(dashboard)/ so the existing admin
 * sidebar (which already links to /analytics) picks it up automatically.
 */

import { useState } from 'react';
import { Button } from '@heroui/react';
import { ExternalLink, RefreshCw, BarChart3, Database } from 'lucide-react';

const GRIST_BASE = process.env.NEXT_PUBLIC_GRIST_URL ?? 'http://127.0.0.1:8484';
const DOC_ID = process.env.NEXT_PUBLIC_GRIST_DOC_ID ?? 'rYyn6wJZihqm1TAgkBgPnY';
const PAGE_ID = process.env.NEXT_PUBLIC_GRIST_PAGE_ID ?? '1';

export default function AnalyticsPage() {
  const [reloadKey, setReloadKey] = useState(0);

  // style=singlePage = editable, no toolbar/left menu/right creator panel
  const fullUrl = `${GRIST_BASE}/${DOC_ID}/p/${PAGE_ID}?style=singlePage&themeAppearance=light&embed=true&_=${reloadKey}`;
  const openUrl = `${GRIST_BASE}/${DOC_ID}/p/${PAGE_ID}`;

  return (
    <div className="flex h-screen w-screen flex-col bg-[var(--paper)]">
      <div className="flex items-center justify-between border-b border-[var(--rule)] bg-[var(--paper-card)] px-4 py-2">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-emerald-600" />
          <div className="text-sm font-medium text-[var(--ink)]">Аналитика — Grist</div>
          <span className="ml-2 rounded bg-[var(--paper-mute)] px-2 py-0.5 font-mono text-[10px] text-[var(--ink-mute)]">
            doc {DOC_ID.slice(0, 12)}…
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
      <div className="flex-1 overflow-hidden">
        <iframe
          key={reloadKey}
          src={fullUrl}
          title="Grist Analytics"
          className="h-full w-full border-0"
          allow="clipboard-read; clipboard-write; fullscreen"
        />
      </div>
    </div>
  );
}

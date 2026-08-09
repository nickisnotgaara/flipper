// /analytics — server-rendered table view backed by Grist.
//
// Earlier this was an iframe embed of the Grist document. Grist 1.7.17
// no longer renders the document body inside a cross-origin iframe
// (WebSocket auth + SameSite cookies), so we read the data server-side
// via Grist's SQL API and render a TanStack table here. A button in
// the toolbar still opens the live Grist document in a new tab for
// editing, charts, and the rest.

import {
  GRIST_URL,
  listTables,
  sqlRecords,
  tableColumns,
  tableRecords,
} from '@/lib/grist';
import GristTable from '@/components/admin/GristTable';
import { Button } from '@heroui/react';
import { BarChart3, Database, ExternalLink } from 'lucide-react';
import Link from 'next/link';

// Force dynamic — page reads Grist via SQL API and uses searchParams.
export const dynamic = 'force-dynamic';

// === Tab config ============================================================
// Grist's REST API returns only tableIds (Table1, Table2, ...); the human
// view name (e.g. "Продано") is only available over the WebSocket subscribe
// API. We list tables by their tableId and use a static display-name map
// for the dropdown labels.
const TABS = [
  {
    key: 'parsing',
    label: 'Данные парсинга',
    docId: process.env.NEXT_PUBLIC_GRIST_DOC_PARSING ?? 'mDaHoGD6yahtxaqugwr5mK',
    defaultTable: 'Table1',
    badge: '5 000 строк',
    displayNames: {
      Table1: 'Продано',
      Table2: 'Аванс',
      Table3: 'Аванс_Продано',
      Balans: 'Balans',
      Offers_Parser: 'Offers_Parser',
      Signals_Parser: 'Signals_Parser',
      FILTERS: 'FILTERS',
    } as Record<string, string>,
  },
  {
    key: 'archives',
    label: 'База архивов',
    docId: process.env.NEXT_PUBLIC_GRIST_DOC_ARCHIVES ?? 'kaBfATwGgUYjDa8doqMzk3',
    defaultTable: 'HousesAll',
    badge: '20 000 строк',
    displayNames: {
      HousesAll: 'HousesAll',
      CianSold: 'CianSold',
      DomclickSold: 'DomclickSold',
      WinnersNovostroiki: 'WinnersNovostroiki',
      WinnersVtorichka: 'WinnersVtorichka',
      FlatInfoHouses: 'FlatInfoHouses',
    } as Record<string, string>,
  },
] as const;

type TabKey = (typeof TABS)[number]['key'];
type SearchParams = { [k: string]: string | string[] | undefined };

function paramStr(p: SearchParams, key: string, fallback: string): string {
  const v = p[key];
  if (Array.isArray(v)) return v[0] ?? fallback;
  return typeof v === 'string' && v ? v : fallback;
}

export default async function AnalyticsPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const tabKey = paramStr(searchParams, 'tab', 'parsing') as TabKey;
  const current = TABS.find((t) => t.key === tabKey) ?? TABS[0];
  const tableName = paramStr(searchParams, 'table', current.defaultTable);

  // Fetch available tables (for the dropdown) + the selected table's rows.
  const allTables = await listTables(current.docId).catch(() => []);

  // Compute the dynamic badge: sum of row counts across all tables in
  // this doc. One cheap SQL per table, only for the "active" tab.
  let totalRows = 0;
  if (allTables.length > 0) {
    const counts = await Promise.all(
      allTables.map((t) =>
        sqlRecords(current.docId, `SELECT COUNT(*) AS c FROM ${t.id}`)
          .then((rs) => rs[0]?.fields?.c ?? 0)
          .catch(() => 0),
      ),
    );
    totalRows = counts.reduce((a, b) => a + b, 0);
  }
  const dynamicBadge = totalRows.toLocaleString('ru-RU').replace(/,/g, ' ') + ' строк';
  // Accept either the tableId (Table1) or the display name (Продано)
  // as ?table=…, so links from outside don't need to know the tableId.
  const tableId =
    allTables.find(
      (t) =>
        t.id === tableName ||
        t.name === tableName ||
        current.displayNames[t.id] === tableName,
    )?.id ?? tableName;
  // Fallback: if user passed a name we don't recognise, but it's a known
  // tableId in the doc, use it as-is.
  const safeTableId = allTables.some((t) => t.id === tableId) ? tableId : current.defaultTable;

  const [columns, rows] = await Promise.all([
    tableColumns(current.docId, safeTableId).catch(() => []),
    tableRecords(current.docId, safeTableId, 5000).catch(() => []),
  ]);

  // Build the dropdown items (tableId + display name) in the same order
  // the user sees in the live Grist sidebar.
  const tableItems = allTables.map((t) => ({
    id: t.id,
    label: current.displayNames[t.id] ?? t.id,
  }));

  const openUrl = `${GRIST_URL}/${current.docId}/p/1?table=${safeTableId}`;

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
            onPress={undefined as never}
            as={Link as never}
            href={`/analytics?tab=${current.key}&table=${tableId}`}
          >
            Обновить
          </Button>
          <Button
            size="sm"
            variant="flat"
            color="primary"
            startContent={<ExternalLink className="h-3 w-3" />}
            as={Link as never}
            href={openUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            Открыть в Grist
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-[var(--rule)] bg-[var(--paper-card)] px-4">
        {TABS.map((t) => {
          const isActive = t.key === current.key;
          // Live row count for the active tab; static fallback for others.
          const badge = isActive ? dynamicBadge : t.badge;
          return (
            <Link
              key={t.key}
              href={`/analytics?tab=${t.key}`}
              className={[
                'flex items-center gap-2 px-3 py-2 text-[13px] border-b-2 transition-colors',
                isActive
                  ? 'border-[var(--accent)] text-[var(--ink)] font-medium'
                  : 'border-transparent text-[var(--ink-mute)] hover:text-[var(--ink)]',
              ].join(' ')}
            >
              <span>{t.label}</span>
              <span className="text-[10.5px] text-[var(--ink-faint)] tabular-nums">
                {badge}
              </span>
            </Link>
          );
        })}
      </div>

      <GristTable
        docId={current.docId}
        tableId={safeTableId}
        columns={columns}
        rows={rows}
        allTables={tableItems}
      />
    </div>
  );
}

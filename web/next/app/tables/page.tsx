'use client';

/**
 * /tables — Univer-backed Google-Sheets-style workbook.
 *
 * The actual spreadsheet engine is in `FlipperWorkbook.tsx`. This file is
 * a thin wrapper that lazy-loads it client-side only (`ssr: false` is
 * mandatory — Univer touches `window`/`document` at init time and would
 * crash during server rendering).
 *
 * `?tab=X` URL state is owned by FlipperWorkbook itself; the sidebar
 * links point at `/tables?tab=active` etc. for deep-linking.
 *
 * Univer's runtime can throw an unhandled exception when it loses
 * pieces of expected DOM (we strip most of the Office-style chrome and
 * the Next.js dev overlay occasionally adds elements that Univer tries
 * to query). We don't want a single harmless miss to crash the page,
 * so we wrap the workbook in an error boundary that keeps the rest of
 * the admin panel usable.
 */

import { Component, type ReactNode } from 'react';
import dynamic from 'next/dynamic';

const FlipperWorkbook = dynamic(
  () => import('@/components/admin/FlipperWorkbook'),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-screen w-screen items-center justify-center text-sm text-[var(--ink-mute)]">
        Загружаю таблицу…
      </div>
    ),
  },
);

class TablesErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error) {
    // Log to console so dev still sees it, but don't let the page
    // replace itself with a Next.js error overlay.
    // eslint-disable-next-line no-console
    console.error('[tables] workbook crashed:', error);
  }
  reset = () => this.setState({ error: null });
  render() {
    if (this.state.error) {
      return (
        <div className="flex h-screen w-screen flex-col items-center justify-center gap-3 bg-[var(--paper)] text-sm text-[var(--ink-soft)]">
          <div className="text-[var(--ink-mute)]">Ошибка рендера таблицы</div>
          <pre className="max-w-2xl whitespace-pre-wrap rounded border border-[var(--rule)] bg-[var(--paper-card)] p-3 font-mono text-[12px] text-[var(--ink)]">
            {String(this.state.error?.message ?? this.state.error)}
          </pre>
          <button
            type="button"
            onClick={this.reset}
            className="rounded border border-[var(--rule)] bg-[var(--paper-card)] px-3 py-1 text-[var(--ink)] hover:bg-[var(--paper-soft)]"
          >
            Перезагрузить
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function TablesPage() {
  return (
    <TablesErrorBoundary>
      <FlipperWorkbook />
    </TablesErrorBoundary>
  );
}

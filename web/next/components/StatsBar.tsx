'use client';
import { Card, CardBody, Tooltip, Chip } from '@heroui/react';
import { type Stats } from '@/lib/api';
import { useEffect, useMemo, useState } from 'react';

// Source → human label (must match backend SOURCE_LABEL in HousePanel).
// Держим в одном месте — UI должен подхватывать новые источники автоматически.
const SOURCE_LABEL: Record<string, string> = {
  cian_active: 'ЦИАН',
  cian_deactivated: 'ЦИАН',
  cian_sold: 'ЦИАН',
  cian_api: 'ЦИАН',
  domclick_sold: 'ДомКлик',
  winners_sold: 'Победители',
  flatinfo_houses: 'Flatinfo',
};

function sourceLabel(s: string): string {
  return SOURCE_LABEL[s] ?? s;
}

/** Format {source: count} dict into "ЦИАН 5 000 · ДомКлик 50 · Победители 200". */
function formatBySource(bySource: Record<string, number> | undefined): string {
  if (!bySource || Object.keys(bySource).length === 0) return '—';
  return Object.entries(bySource)
    .sort(([, a], [, b]) => b - a)
    .map(([src, n]) => `${sourceLabel(src)} ${n.toLocaleString('ru')}`)
    .join(' · ');
}

export default function StatsBar({
  stats,
  loading,
  count,
  compact = false,
}: {
  stats: Stats;
  loading: boolean;
  count: number;
  /** Compact mode: drop the "Домов" cell and shrink each cell's
   *  min-width so three numbers actually fit inside a 320px popover
   *  on a phone. Default = full layout for the original top-bar use. */
  compact?: boolean;
}) {
  const [progress, setProgress] = useState(0);
  useEffect(() => {
    if (loading) {
      setProgress(8);
      const t = setInterval(() => setProgress((p) => Math.min(92, p + 7)), 120);
      return () => clearInterval(t);
    } else {
      setProgress(100);
      const t = setTimeout(() => setProgress(0), 600);
      return () => clearInterval(t);
    }
  }, [loading]);

  // Two scenarios:
  //  1) No ads in DB yet (pipeline never ran / was wiped) → primary
  //     metric is "Houses on the map" (from houses.lat/lng), and we
  //     mark the active/sold cells as "—" with a hint to reparse.
  //  2) Ads present → original layout, primary is active count.
  const noAds = stats.active_total === 0 && stats.deactivated_total === 0;

  return (
    <Card
      shadow="sm"
      radius="lg"
      classNames={{
        // The StatsBar used to sit edge-to-edge in the top bar on
        // mobile, but the user found it too obtrusive (it occluded
        // the centre of the map). It now lives inside the "?" help
        // popover, so it just needs the regular floating-card look
        // (rounded, bordered, shadowed) and full width inside that
        // narrower container.
        base: 'pointer-events-auto bg-white shadow-card border border-default-200 rounded-large w-full overflow-hidden',
        body: 'p-0',
      }}
    >
      <CardBody>
        <div className="flex items-stretch divide-x divide-default-200">
          {noAds ? (
            <Stat
              label="На карте"
              value={stats.houses_with_coords.toLocaleString('ru')}
              hint={`из ${stats.houses.toLocaleString('ru')} домов в БД`}
              hintTitle={`В базе ${stats.houses.toLocaleString('ru')} адресов; ${stats.houses_with_coords.toLocaleString('ru')} с координатами (показаны точками на карте). Объявлений пока нет — нужен репарс cian_active / cian_sold.`}
              accent="brand"
              compact={compact}
            />
          ) : (
            <Stat
              label="Активных"
              value={stats.active_total.toLocaleString('ru')}
              hint={stats.active_unlinked > 0
                ? `${stats.active_unlinked} не привязано`
                : 'все привязаны к дому'}
              hintTitle={`${stats.active_linked} из ${stats.active_total} объявлений сопоставлены с конкретным домом и показаны точками на карте.${stats.active_unlinked ? ` Ещё ${stats.active_unlinked} пока без адреса.` : ''}\n\nПо источникам: ${formatBySource(stats.active_by_source)}`}
              accent="red"
              compact={compact}
            />
          )}
          <Stat
            label="Снято"
            value={noAds ? '—' : stats.deactivated_total.toLocaleString('ru')}
            hint={noAds ? 'запусти репарс' : 'публикаций'}
            hintTitle={noAds
              ? 'В таблицах active_ads / sold_ads сейчас 0 строк — репарсер ещё не запускался или данные были стёрты. Чтобы восстановить, выполни `docker compose run --rm cian_active` и `cian_sold` (часы).'
              : `${stats.deactivated_total.toLocaleString('ru')} снятых публикаций. ${stats.houses_with_deactivated.toLocaleString('ru')} домов имеют хотя бы одну.\n\nПо источникам: ${formatBySource(stats.sold_by_source)}`}
            accent={noAds ? 'muted' : 'ink'}
            compact={compact}
          />
          {!noAds && !compact && (
            <Stat
              label="Домов"
              value={stats.houses_with_coords.toLocaleString('ru')}
              hint={`с координатами из ${stats.houses.toLocaleString('ru')}`}
              hintTitle={`${stats.houses_with_coords.toLocaleString('ru')} домов с известной геопозицией — показаны на карте как точки / кластеры.`}
              accent="brand"
              compact={compact}
            />
          )}
        </div>
      </CardBody>
      {progress > 0 && (
        <div
          className="h-0.5 bg-gradient-to-r from-primary to-warning transition-all duration-200"
          style={{ width: `${progress}%`, opacity: progress === 100 ? 0 : 1 }}
        />
      )}
    </Card>
  );
}

function Stat({
  label,
  value,
  hint,
  hintTitle,
  accent = 'brand',
  compact = false,
}: {
  label: string;
  value: string;
  hint: string;
  hintTitle?: string;
  accent?: 'brand' | 'red' | 'ink' | 'muted';
  compact?: boolean;
}) {
  // Numbers use a small colored bottom-bar instead of a circular "sticker"
  // dot — cleaner 2GIS-style hierarchy. Color signals the metric's weight.
  const barColor =
    accent === 'red' ? 'bg-primary'
    : accent === 'ink' ? 'bg-default-400'
    : accent === 'muted' ? 'bg-default-300'
    : 'bg-primary';
  const valueColor =
    accent === 'red' ? 'text-foreground'
    : accent === 'ink' ? 'text-foreground/80'
    : accent === 'muted' ? 'text-default-300'
    : 'text-primary';
  return (
    <Tooltip content={hintTitle} placement="bottom" delay={300}>
      <div className={`relative ${compact ? 'px-2 py-1.5 min-w-0 flex-1' : 'px-3 py-2 min-w-[88px]'} overflow-hidden group`}>
        {/* Color accent strip on top — replaces the previous circle "sticker" */}
        <div className={`absolute top-0 left-0 right-0 h-[2px] ${barColor} opacity-80`} />
        <div className="text-[10px] uppercase tracking-wider text-default-500 font-semibold">
          {label}
        </div>
        <div className={`font-display font-bold ${compact ? 'text-base' : 'text-lg'} ${valueColor} leading-tight mt-0.5 tabular-nums truncate`}>
          {value}
        </div>
        <div className="text-[10px] text-default-500 leading-tight truncate max-w-[160px]">
          {hint}
        </div>
      </div>
    </Tooltip>
  );
}

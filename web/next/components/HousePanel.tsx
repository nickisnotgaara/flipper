'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Drawer,
  DrawerContent,
  DrawerHeader,
  DrawerBody,
  Chip,
  Button,
  Tooltip,
  ScrollShadow,
} from '@heroui/react';
import { type HouseDetail, type Ad } from '@/lib/api';
import PhotoCarousel from './PhotoCarousel';
import AdPhotosModal from './AdPhotosModal';
import { MetroIcon, WalkIcon, BuildingIcon, FloorsIcon, ExternalIcon } from './icons';

const fmtMoney = (v: number | null) =>
  v == null
    ? '—'
    : new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 }).format(v);

const fmtNum = (v: number | null) => (v == null ? '—' : new Intl.NumberFormat('ru-RU').format(v));

// Source → человекочитаемая метка (бейдж на карточке объявления).
// Держим в одном месте, чтобы фронт и линтер не разъезжались.
const SOURCE_LABEL: Record<string, string> = {
  cian_active: 'ЦИАН',
  cian_deactivated: 'ЦИАН',
  cian_sold: 'ЦИАН',
  cian_api: 'ЦИАН',
  domclick_sold: 'ДомКлик',
  winners_sold: 'Победители',
  flatinfo_houses: 'Flatinfo',
};

function sourceLabel(source: string | undefined | null): string {
  if (!source) return '—';
  return SOURCE_LABEL[source] ?? source;
}

// domclick photo URLs приходят как относительные пути ("/vitrina/...jpg"),
// а cian — как объекты с fullUrl/thumbnail2Url. Нормализуем оба формата
// в массив cian-shape объектов, который ожидает PhotoCarousel.
function domclickUrlsToCianPhotos(urls: string[]): Array<{
  id: string;
  fullUrl: string;
  thumbnail2Url: string;
  thumbnailUrl: string;
  miniUrl: string;
}> {
  return urls.map((u, i) => {
    // Если относительный — собираем абсолютный через img.dmclk.ru
    const abs = u.startsWith('http') ? u : `https://img.dmclk.ru${u}`;
    return {
      id: `dc_${i}`,
      fullUrl: abs,
      thumbnail2Url: abs,
      thumbnailUrl: abs,
      miniUrl: abs,
    };
  });
}

// Source-aware: достаём список фото из raw_data для разных источников.
function extractPhotos(ad: Ad): any[] | null {
  const rd = ad.raw_data;
  if (!rd || typeof rd !== 'object') return null;
  // cian: raw_data.offer.photos[] — массив объектов с fullUrl
  if (Array.isArray(rd.offer?.photos) && rd.offer.photos.length > 0) {
    return rd.offer.photos;
  }
  // cian_deactivated (legacy): фотки лежат в raw_data.details.images[] —
  // массив СТРОК-URL'ов. Плюс previewPhoto отдельным полем.
  if (Array.isArray(rd.details?.images) && rd.details.images.length > 0) {
    return domclickUrlsToCianPhotos(rd.details.images);
  }
  // domclick: наш parser кладёт photo_urls: list[str] рядом с originalProduct
  if (Array.isArray(rd.photo_urls) && rd.photo_urls.length > 0) {
    return domclickUrlsToCianPhotos(rd.photo_urls);
  }
  // domclick SSR: originalProduct.photos[] — массив {url: ...}
  if (Array.isArray(rd.originalProduct?.photos) && rd.originalProduct.photos.length > 0) {
    const urls = rd.originalProduct.photos
      .map((p: any) => (typeof p === 'object' && p ? p.url : p))
      .filter((u: any) => typeof u === 'string');
    if (urls.length > 0) {
      return domclickUrlsToCianPhotos(urls);
    }
  }
  // cian_deactivated (legacy): single previewPhoto как fallback (одна картинка)
  if (typeof rd.previewPhoto === 'string' && rd.previewPhoto.length > 0) {
    return domclickUrlsToCianPhotos([rd.previewPhoto]);
  }
  return null;
}

// Reactive media query — used to swap the Drawer's `placement` (and the
// few props that depend on it) when the user rotates the phone or resizes
// the window between mobile/desktop.
function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mq = window.matchMedia(query);
    const apply = () => setMatches(mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, [query]);
  return matches;
}

export default function HousePanel({
  open,
  houseId,
  detail,
  loading,
  onClose,
  /**
   * Если задан — после загрузки `detail` панель сама откроет
   * AdPhotosModal для объявления с этим external_id. Источник —
   * `?photoAd=` в URL карты (используется ссылкой из Grist Active_ads).
   * Один выстрел на монтирование панели: после того как модалка
   * открылась и юзер её закрыл, повторно не всплывает, даже если
   * detail перезагружается. Это чтобы клики по карте не открывали
   * фотки заново.
   */
  autoOpenPhotoAdId,
}: {
  open: boolean;
  houseId: number;
  detail: HouseDetail | null;
  loading: boolean;
  onClose: () => void;
  autoOpenPhotoAdId: string | null;
}) {
  const isMobile = useMediaQuery('(max-width: 767px)');

  // HeroUI's Drawer wraps the panel in a `fixed inset-0` div (the
  // "wrapper") that sits ABOVE the map. The default backdrop
  // (`opaque`) renders a full-viewport `bg-overlay/50` div that
  // BLOCKS clicks on the search input, stats, and the rest of the
  // map — even though we set `pointer-events-none` on the wrapper,
  // the backdrop is a separate child and still catches them.
  //
  // Desktop fix (all three are required):
  //   1) `backdrop="transparent"` — HeroUI doesn't render a click-
  //      eating overlay in the first place
  //   2) `!pointer-events-none` on classNames.backdrop — belt & braces
  //      for any inner pseudo-overlay
  //   3) `!bg-transparent` on classNames.backdrop — same
  //   4) `isDismissable={false}` — react-aria's useInteractOutside
  //      must not close the panel when the user clicks a house
  //      marker / pans the map
  //   5) `shouldBlockScroll={false}` — keep wheel-zoom on the map
  //
  // Mobile keeps the full default HeroUI behaviour: tap the dark
  // backdrop to close, scroll is blocked while the sheet is up.
  return (
    <Drawer
      isOpen={open}
      onOpenChange={(v) => { if (!v) onClose(); }}
      placement={isMobile ? 'bottom' : 'right'}
      size={isMobile ? 'lg' : 'sm'}
      backdrop={isMobile ? 'opaque' : 'transparent'}
      isDismissable={isMobile}
      isKeyboardDismissDisabled={false}
      hideCloseButton
      shouldBlockScroll={isMobile}
      classNames={{
        // `pointer-events-none` on the wrapper is the key fix — let
        // every click on the empty area of the overlay fall through to
        // the map behind. The panel itself re-enables pointer events
        // so the body / header / close button still receive clicks.
        wrapper: isMobile
          ? 'items-end z-[1100] pointer-events-none'
          : 'justify-end z-[1100] pointer-events-none',
        base: isMobile
          ? 'rounded-t-2xl max-h-[88vh] mb-0 z-[1100] pointer-events-auto'
          : 'rounded-none z-[1100] pointer-events-auto',
        body: 'p-0',
        // On desktop, kill both the visual overlay and the click
        // capture from the backdrop div HeroUI may still render.
        // `!` (important) wins over HeroUI's default `bg-overlay/50`
        // and any pointer-events-auto they put on it.
        backdrop: isMobile
          ? '!bg-black/80 !z-[1050]'
          : '!bg-transparent !pointer-events-none',
      }}
      style={
        !isMobile
          ? ({ '--drawer-width': '440px' } as React.CSSProperties)
          : undefined
      }
    >
      <DrawerContent>
        {() => (
          <PanelBody
            houseId={houseId}
            detail={detail}
            loading={loading}
            onClose={onClose}
            autoOpenPhotoAdId={autoOpenPhotoAdId}
          />
        )}
      </DrawerContent>
    </Drawer>
  );
}

function PanelBody({
  houseId,
  detail,
  loading,
  onClose,
  autoOpenPhotoAdId,
}: {
  houseId: number;
  detail: HouseDetail | null;
  loading: boolean;
  onClose: () => void;
  autoOpenPhotoAdId: string | null;
}) {
  const hasAds = !!(detail && (detail.active.length > 0 || detail.deactivated.length > 0));
  // Один photo-modal на всю панель. Открывается из deep-link
  // `?photoAd=…` (ссылка из Grist Active_ads → photos_url). На самой
  // карточке отдельной кнопки-иконки больше нет — модалка открывается
  // по клику на любой из 4 фото-превью (PhotoCarousel → onThumbClick).
  const [photosAd, setPhotosAd] = useState<Ad | null>(null);

  // Авто-открытие галереи, если в URL был `?photoAd=…` (deep-link из Grist).
  // `firedRef` гарантирует один выстрел за маунт PanelBody: после того как
  // юзер закрыл модалку вручную, она не вылезет снова при пере-выборке
  // дома (selectedId сменился и пришёл новый detail). Раньше тут ловил
  // re-open баг на каждом клике по карте после deep-link.
  const firedRef = useRef(false);
  useEffect(() => {
    if (firedRef.current) return;
    if (!detail || !autoOpenPhotoAdId) return;
    const allAds = [...detail.active, ...detail.deactivated];
    const found = allAds.find(
      (a) => String(a.external_id) === String(autoOpenPhotoAdId),
    );
    if (found) {
      firedRef.current = true;
      setPhotosAd(found);
    }
    // Намеренно только [detail, autoOpenPhotoAdId] — `photosAd`/`setPhotosAd`
    // стабильны, лишние перезапуски эффекта не нужны.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail, autoOpenPhotoAdId]);
  return (
    <>
      <DrawerHeader className="flex flex-col gap-0.5 border-b border-default-200 px-5 py-3">
        <div className="text-[10px] uppercase tracking-widest text-default-500 font-medium">
          Дом #{houseId}
        </div>
        {detail ? (
          <div className="flex items-start justify-between gap-3 w-full">
            <div className="min-w-0 flex-1">
              <div className="font-display text-lg font-semibold text-foreground leading-snug">
                {detail.house.address}
              </div>
              <div className="text-xs text-default-500 mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
                {detail.house.year && (
                  <span className="inline-flex items-center gap-1">
                    <BuildingIcon size={12} className="text-default-400" />
                    {detail.house.year}
                  </span>
                )}
                {detail.house.levels && (
                  <span className="inline-flex items-center gap-1">
                    <FloorsIcon size={12} className="text-default-400" />
                    {detail.house.levels} эт.
                  </span>
                )}
                {detail.house.type && <span>· {detail.house.type}</span>}
                {detail.house.series && <span>· {detail.house.series}</span>}
              </div>
            </div>
            <Tooltip content="Закрыть" placement="left">
              <Button
                isIconOnly
                size="sm"
                variant="light"
                radius="full"
                onPress={onClose}
                aria-label="закрыть"
                className="text-default-500 hover:text-foreground shrink-0"
              >
                ✕
              </Button>
            </Tooltip>
          </div>
        ) : (
          <div className="h-7 w-40 rounded-md bg-default-100 animate-pulse mt-1" />
        )}
      </DrawerHeader>

      <DrawerBody className="bg-default-50 p-0">
        {loading ? (
          <Skeleton />
        ) : !detail ? (
          <div className="p-6 text-default-500">Не удалось загрузить информацию о доме.</div>
        ) : (
          <Body detail={detail} onOpenPhotos={setPhotosAd} />
        )}
      </DrawerBody>

      {hasAds && detail && (
        <div className="shrink-0 border-t border-default-200 bg-white px-5 py-3 flex items-center justify-end gap-2 text-[11px] text-default-500">
          <div className="flex items-center gap-2 shrink-0">
            <Chip
              size="sm"
              variant="flat"
              radius="sm"
              classNames={{ base: 'h-5 px-1.5', content: 'text-[10px] text-default-700 font-medium px-0' }}
            >
              {detail.active.length + detail.deactivated.length} объявлений
            </Chip>
            {detail.house.lat != null && detail.house.lng != null && (
              <a
                href={`https://yandex.ru/maps/?pt=${detail.house.lng},${detail.house.lat}&z=17`}
                target="_blank"
                rel="noreferrer"
                className="text-primary hover:text-primary-600 transition"
                title="Открыть на Яндекс.Картах"
              >
                Я.Карты ↗
              </a>
            )}
          </div>
        </div>
      )}

      {/* Модалка с фотками + кнопкой "В Grist". Один экземпляр на
          панель — открывается из любой AdCard через onOpenPhotos. */}
      <AdPhotosModal
        isOpen={photosAd !== null}
        onOpenChange={(o) => { if (!o) setPhotosAd(null); }}
        ad={photosAd}
      />
    </>
  );
}

function Skeleton() {
  return (
    <div className="p-4 space-y-3 animate-pulse">
      {[...Array(6)].map((_, i) => (
        <div key={i} className="h-20 rounded-xl bg-white border border-default-200" />
      ))}
    </div>
  );
}

function Body({ detail, onOpenPhotos }: { detail: HouseDetail; onOpenPhotos: (ad: Ad) => void }) {
  const { house, active, deactivated } = detail;

  if (active.length === 0 && deactivated.length === 0) {
    return (
      <div className="p-4">
        <div className="bg-white rounded-2xl border border-default-200 p-7 text-center shadow-card">
          <div className="mx-auto w-14 h-14 rounded-2xl bg-default-100 flex items-center justify-center mb-4">
            <svg viewBox="0 0 24 24" width={28} height={28} fill="none" stroke="currentColor" strokeWidth={1.5} className="text-default-400">
              <path d="M3 12l9-9 9 9" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M5 10v10h14V10" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M10 20v-6h4v6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="font-display text-lg text-foreground font-semibold">В этом доме пока тихо</div>
          <p className="text-sm text-default-500 mt-2 leading-relaxed max-w-[300px] mx-auto">
            По адресу <span className="text-foreground font-medium">{house.address}</span> сейчас нет ни активных объявлений, ни архивных публикаций.
            Возможно, дом новый или ещё не появился на ЦИАН.
          </p>

          {(house.year || house.levels || house.type) && (
            <div className="mt-5 grid grid-cols-3 gap-2 max-w-[280px] mx-auto">
              {house.year && (
                <div className="bg-default-100 rounded-lg p-2">
                  <div className="text-[9px] uppercase text-default-500 tracking-wider">Год</div>
                  <div className="text-sm font-semibold text-foreground tabular-nums">{house.year}</div>
                </div>
              )}
              {house.levels && (
                <div className="bg-default-100 rounded-lg p-2">
                  <div className="text-[9px] uppercase text-default-500 tracking-wider">Этажей</div>
                  <div className="text-sm font-semibold text-foreground tabular-nums">{house.levels}</div>
                </div>
              )}
              {house.type && (
                <div className="bg-default-100 rounded-lg p-2">
                  <div className="text-[9px] uppercase text-default-500 tracking-wider">Тип</div>
                  <div className="text-sm font-semibold text-foreground truncate">{house.type}</div>
                </div>
              )}
            </div>
          )}

          {house.lat != null && house.lng != null && (
            <div className="mt-4 text-[11px] text-default-400 font-mono">
              {house.lat.toFixed(5)}, {house.lng.toFixed(5)}
            </div>
          )}

          <div className="mt-5 text-[11px] text-default-500 leading-relaxed max-w-[280px] mx-auto">
            Объявления появятся здесь автоматически, как только парсер ЦИАН найдёт их по этому адресу.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-2 gap-2">
        <SummaryCard tone="active" label="Активных" count={active.length} />
        <SummaryCard tone="deactivated" label="Снято" count={deactivated.length} />
      </div>

      {active.length > 0 && (
        <Section title="Активные объявления" count={active.length} tone="active">
          {active.map((ad) => (
            <AdCard key={ad.id} ad={ad} kind="active" onOpenPhotos={onOpenPhotos} />
          ))}
        </Section>
      )}

      {deactivated.length > 0 && (
        <Section title="Снятые публикации" count={deactivated.length} tone="deactivated">
          {deactivated.slice(0, 50).map((ad) => (
            <AdCard key={ad.id} ad={ad} kind="deactivated" onOpenPhotos={onOpenPhotos} />
          ))}
          {deactivated.length > 50 && (
            <div className="text-xs text-default-500 text-center py-2">
              показано 50 из {deactivated.length}
            </div>
          )}
        </Section>
      )}
    </div>
  );
}

function SummaryCard({
  tone,
  label,
  count,
}: {
  tone: 'active' | 'deactivated';
  label: string;
  count: number;
}) {
  const valueColor = tone === 'active' ? 'text-primary' : 'text-default-500';
  return (
    <div className="bg-white rounded-xl border border-default-200 p-3 shadow-card">
      <div className="text-[10px] uppercase tracking-wider text-default-500 font-medium">{label}</div>
      <div className="flex items-baseline gap-1.5 mt-1">
        <div className={`font-display text-3xl font-bold ${valueColor}`}>{count.toLocaleString('ru')}</div>
      </div>
      <div className="text-[10px] text-default-400 mt-0.5">объявлений в этом доме</div>
    </div>
  );
}

function Section({
  title,
  count,
  tone,
  children,
}: {
  title: string;
  count: number;
  tone: 'active' | 'deactivated';
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2 px-1">
        <h3 className="text-xs uppercase tracking-wider text-foreground/80 font-semibold flex-1">
          {title}
        </h3>
        <Chip
          size="sm"
          variant="flat"
          radius="sm"
          color={tone === 'active' ? 'primary' : 'default'}
          classNames={{
            base: 'h-5 px-1.5',
            content: tone === 'active'
              ? 'text-[10px] text-primary-600 font-bold px-0'
              : 'text-[10px] text-default-600 font-medium px-0',
          }}
        >
          {count}
        </Chip>
      </div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function AdCard({ ad, kind, onOpenPhotos }: { ad: Ad; kind: 'active' | 'deactivated'; onOpenPhotos: (ad: Ad) => void }) {
  const roomWord = useMemo(() => {
    const n = ad.rooms;
    if (n == null) return '—';
    if (n === 0) return 'Студия';
    if (n === 1) return '1-комн.';
    if (n >= 2 && n <= 4) return `${n}-комн.`;
    return `${n}-комн.`;
  }, [ad.rooms]);

  // Photo carousel — source-aware:
  //   cian_active    → raw_data.offer.photos[] (flippercrawl)
  //   domclick_sold  → raw_data.photo_urls[] (наш DomclickSource) ИЛИ
  //                    raw_data.originalProduct.photos[] (SSR fallback)
  // Раньше показывалось ТОЛЬКО для kind === 'active', потому что cian-историю
  // мы почти никогда не reparse'или до снятия. С domclick другая история —
  // мы сохраняем full raw_data в sold_ads (с photos), так что carousel
  // показывается и для deactivated, если источник — domclick.
  const photos = extractPhotos(ad);

  const isDeactivated = kind === 'deactivated';

  // Прячем иконки-действия, если есть фото — иконка 📷 стоит поверх
  // правого верхнего угла carousel, иначе — над пустым местом.
  const handleOpenPhotos = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onOpenPhotos(ad);
  };

  return (
    // <div> вместо <a>: раньше вся карточка была <a href={ad.url}>.
    // Чтобы <a> для контента был валидным (а внутри не было вложенного <a>),
    // карточка = <div>, а контентная часть обёрнута в <a> отдельно.
    // PhotoCarousel + кнопка-иконка лежат на div-уровне.
    <div
      className={`relative block bg-white rounded-2xl border border-default-200 shadow-card hover:shadow-card-lg transition-shadow group overflow-hidden ${
        isDeactivated ? 'opacity-80' : ''
      }`}
    >
      {/* Action-иконка в правом верхнем углу. Поверх carousel (если есть)
          или над пустым местом сверху. Native <button> + stopPropagation
          + data-stop-nav, чтобы клик НЕ открывал cian. */}
      <div className="absolute top-2 right-2 z-20 flex items-center gap-1.5">
        <button
          type="button"
          data-stop-nav
          onClick={handleOpenPhotos}
          // title показывает сколько фото уже в кеше raw_data (или "все фото")
          title={photos ? `${photos.length} фото · нажмите чтобы открыть все` : 'Открыть все фото'}
          aria-label="открыть все фото объявления"
          className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-white/95 hover:bg-white text-default-700 border border-default-200 shadow-card backdrop-blur-sm transition cursor-pointer"
        >
          <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
            <path d="M14.5 4h-5L8 6H5a2 2 0 00-2 2v10a2 2 0 002 2h14a2 2 0 002-2V8a2 2 0 00-2-2h-3l-1.5-2z" />
            <circle cx={12} cy={13} r={3.5} />
          </svg>
        </button>
      </div>

      <a
        href={ad.url || '#'}
        target="_blank"
        rel="noreferrer"
        // `draggable={false}` is the HTML-attribute kill switch for the
        // browser's built-in link-drag (the thing that shows a ghost URL
        // tooltip when you mousedown+move on an <a href>). Without it
        // the link-drag starts inside the <a> and steals pointer events
        // away from embla before the inner handlers can react.
        // `onDragStart` here is a belt-and-suspenders fallback for
        // browsers that ignore `draggable` on anchors.
        draggable={false}
        onDragStart={(e) => e.preventDefault()}
        // Safety net: if a click bubbles up from inside the photo
        // carousel ([data-photo-thumb] is set by PhotoCarousel on
        // each thumbnail button), don't follow the link. PhotoCarousel's
        // own onClick also calls stopPropagation + preventDefault, but
        // this is the second line of defense in case a browser-specific
        // path lets the click reach the anchor (e.g. keyboard activation
        // of the parent anchor via Enter while focus is on a thumb).
        // Также блокируем переход если клик пришёл с кнопки-иконки
        // (data-stop-nav — наш новый атрибут-маркер).
        onClick={(e) => {
          const t = e.target as HTMLElement | null;
          if (t && (t.closest('[data-photo-thumb]') || t.closest('[data-stop-nav]'))) {
            e.preventDefault();
          }
        }}
        className="block"
      >
        {photos && (
          <div className="p-2.5 pb-0">
            <PhotoCarousel photos={photos} adUrl={ad.url} />
          </div>
        )}

        <div className="p-4 pt-3.5">
          {/* Meta line: комнаты, площадь, этаж — как в 2gis одна строка. */}
          <div className="text-[13px] text-default-600 leading-snug">
            {roomWord}
            {ad.area != null && <span>, {fmtNum(ad.area)} м²</span>}
            {ad.floor_current != null && ad.floor_total != null && (
              <span>, {ad.floor_current} этаж</span>
            )}
          </div>

          {/* Цена крупно — главный акцент карточки. */}
          <div
            className={`font-display font-bold text-[22px] leading-tight mt-1.5 ${
              isDeactivated ? 'text-default-500 line-through' : 'text-foreground'
            }`}
          >
            {fmtMoney(ad.price)}
          </div>

          {/* Метро + пешком — с круглой иконкой M, как в 2gis. */}
          {ad.metro_station && (
            <div className="mt-2.5 flex items-center flex-wrap gap-x-3 gap-y-1.5 text-[12px]">
              <span className="inline-flex items-center gap-1.5">
                <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-success/15 text-success">
                  <MetroIcon size={11} />
                </span>
                <span className="text-foreground/90 font-medium">{ad.metro_station}</span>
              </span>
              {ad.metro_walk_time != null && (
                <span className="inline-flex items-center gap-1.5 text-default-500">
                  <WalkIcon size={13} className="text-default-400" />
                  {ad.metro_walk_time} мин
                </span>
              )}
            </div>
          )}

          {/* Нижняя строка: источник + (опц.) дни на сайте / снято. */}
          <div className="mt-3 pt-2.5 border-t border-default-100 flex items-center justify-between gap-2 text-[11px] text-default-500">
            <span className="inline-flex items-center gap-1 font-medium text-default-600">
              <ExternalIcon size={12} className="text-default-400" />
              {sourceLabel(ad.source)}
            </span>
            {kind === 'active' && ad.days_in_exposition != null && (
              <span>{ad.days_in_exposition} дн. на сайте</span>
            )}
            {isDeactivated && (ad.date_end || ad.exposition) && (
              <span className="inline-flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-primary inline-block" />
                снято {ad.date_end ? new Date(ad.date_end).toLocaleDateString('ru-RU') : ad.exposition}
              </span>
            )}
          </div>
        </div>
      </a>
    </div>
  );
}

'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { MapContainer, TileLayer, Marker, useMap, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import { Button, Chip, Popover, PopoverContent, PopoverTrigger } from '@heroui/react';
import HousePanel from './HousePanel';
import StatsBar from './StatsBar';
import SearchBox from './SearchBox';
import {
  fetchClusters,
  fetchStats,
  fetchCluster,
  fetchGeocode,
  type House,
  type Stats,
  type HouseDetail,
  type SuggestItem,
} from '@/lib/api';

const MOSCOW: [number, number] = [55.7558, 37.6173];

// Four states for a house (matches marker CSS classes):
//   - only active (live)        -> red, big active count
//   - both active + deactivated -> red, big active count + tiny gray dot
//   - only deactivated (sold)   -> white with gray border + tiny gray dot
//   - no ads (just exists in DB) -> tiny gray dot, no number
// At zoom < 15 the server returns grid clusters (`is_synthetic=true`)
// instead of individual houses — see `clusterIcon`/`ClusterMarker` below.
function houseClass(active: number, deact: number): string {
  if (active === 0 && deact === 0) return 'marker-house no-ads';
  if (active > 0 && deact > 0) return 'marker-house many-ads';
  if (active > 0) return 'marker-house only-active';
  if (deact > 0) return 'marker-house only-deact';
  return 'marker-house';
}

function makeHouseIcon(active: number, deact: number): L.DivIcon {
  const klass = houseClass(active, deact);
  // "No ads" houses get a tiny dot — 10x10 instead of 28x28.
  const isEmpty = active === 0 && deact === 0;
  const showNumber = active > 0 && !isEmpty;
  const mainText = active > 99 ? '99+' : active > 0 ? String(active) : '';
  let extra = '';
  if (deact > 0) {
    const label = deact > 99 ? '99+' : String(deact);
    extra = `<span class="deact-badge" title="${deact} снятых">${label}</span>`;
  }
  const size = isEmpty ? 10 : 28;
  return L.divIcon({
    className: '',
    html: `<div class="${klass}">${showNumber ? mainText : ''}${extra}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

// 2GIS-style cluster bubble: red circle with the count of houses inside.
const clusterIcon = (count: number) => {
  const size = Math.min(44, 22 + Math.log10(Math.max(count, 1)) * 8);
  const fontSize = Math.max(9, Math.min(13, Math.round(size / 3.2)));
  return L.divIcon({
    className: 'cluster-marker-wrap',
    html: `<div class="cluster-marker" style="width:${size}px;height:${size}px;line-height:${size - 4}px;font-size:${fontSize}px;">${count > 999 ? '999+' : count}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
};

function ClusterMarker({ lat, lng, count }: { lat: number; lng: number; count: number }) {
  const map = useMap();
  const handleClick = useCallback(() => {
    const target = Math.min(18, map.getZoom() + 3);
    map.flyTo([lat, lng], target, { duration: 0.6 });
  }, [map, lat, lng]);
  return (
    <Marker
      position={[lat, lng]}
      icon={clusterIcon(count)}
      eventHandlers={{ click: handleClick }}
    />
  );
}

function MapEvents({ onBoundsChange }: { onBoundsChange: (b: L.LatLngBounds, z: number) => void }) {
  const map = useMapEvents({
    moveend: () => onBoundsChange(map.getBounds(), map.getZoom()),
    zoomend: () => onBoundsChange(map.getBounds(), map.getZoom()),
  });
  return null;
}

function FitToMoscow() {
  const map = useMap();
  const flownRef = useRef(false);
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      const lat = Number(params.get('lat'));
      const lng = Number(params.get('lng'));
      const z = Number(params.get('zoom'));
      if (!Number.isNaN(lat) && !Number.isNaN(lng) && lat > 0 && lng > 0) {
        map.setView([lat, lng], Number.isNaN(z) ? 17 : z);
        flownRef.current = true;
        return;
      }
    }
    map.setView(MOSCOW, 12);
    flownRef.current = true;
  }, [map]);
  // Move the Leaflet zoom (+/-) control to the top-right so it
  // stops colliding with the top-left search row (used to hide
  // the brand "F" badge).
  useEffect(() => {
    map.zoomControl?.setPosition('topright');
  }, [map]);
  return null;
}

function MapFlyController({ flyRef }: { flyRef: React.MutableRefObject<((lat: number, lng: number, z?: number) => void) | null> }) {
  const map = useMap();
  useEffect(() => {
    flyRef.current = (lat, lng, z) => {
      const target = z ?? Math.min(18, Math.max(map.getZoom(), 16));
      map.flyTo([lat, lng], target, { duration: 0.6 });
    };
    return () => { flyRef.current = null; };
  }, [map, flyRef]);
  return null;
}

function CenterButton() {
  const map = useMap();
  const [show, setShow] = useState(false);
  useEffect(() => {
    const handler = () => {
      const c = map.getCenter();
      const far =
        Math.abs(c.lat - MOSCOW[0]) > 0.01 ||
        Math.abs(c.lng - MOSCOW[1]) > 0.01 ||
        map.getZoom() < 11;
      setShow(far);
    };
    map.on('moveend zoomend', handler);
    handler();
    return () => {
      map.off('moveend zoomend', handler);
    };
  }, [map]);
  if (!show) return null;
  return (
    // bottom-left to avoid colliding with the "?" help button
    // which lives in the bottom-right corner.
    <Button
      size="sm"
      variant="flat"
      color="primary"
      onPress={() => map.flyTo(MOSCOW, 12, { duration: 0.6 })}
      className="absolute bottom-3 left-3 z-[1000] bg-white shadow-card-lg font-medium"
      startContent={<span className="w-2 h-2 rounded-full bg-primary" />}
    >
      Центр Москвы
    </Button>
  );
}

// Tiny "?" button in the corner of the map. Tap → popover with the
// marker legend, quick how-to, and a hidden-until-needed stats panel.
// Always present (visible even when the side panel is open) so the
// user can re-check the legend at any time without us pinning a fat
// hint card to the canvas.
function MapHelpButton({
  stats,
  loading,
  count,
  isMobile,
}: {
  stats: Stats | null;
  loading: boolean;
  count: number;
  isMobile: boolean;
}) {
  return (
    // `backdrop="transparent"` (not "opaque") — the opaque backdrop
    // covered the whole viewport and blocked clicks on the search
    // input + map while the popover was open. We just want a
    // floating panel, not a modal that locks the page.
    <Popover
      placement={isMobile ? 'top' : 'top-end'}
      offset={isMobile ? 8 : 10}
      backdrop="transparent"
    >
      <PopoverTrigger>
        <Button
          isIconOnly
          size="sm"
          radius="full"
          variant="solid"
          aria-label="легенда, подсказки и статистика"
          className="absolute bottom-3 right-3 z-[1000] bg-white text-default-700 shadow-card-lg hover:bg-default-50 border border-default-200 w-9 h-9 text-sm font-semibold"
        >
          ?
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className={[
          'p-0 overflow-hidden',
          // Cap width by viewport so it never overflows on phones;
          // 360px on desktop is plenty for a 3-column stats grid.
          isMobile
            ? 'max-w-[calc(100vw-16px)] w-[calc(100vw-16px)]'
            : 'max-w-[360px]',
          // Cap height so the panel can't grow taller than the
          // viewport. Inner content scrolls.
          'max-h-[min(70vh,520px)]',
        ].join(' ')}
      >
        <div className="bg-white rounded-large border border-default-200 shadow-panel overflow-y-auto max-h-[inherit]">
          <div className="px-3.5 pt-3 pb-2 flex items-center gap-1.5 border-b border-default-100">
            <span className="w-1.5 h-1.5 rounded-full bg-primary" />
            <span className="text-[10px] uppercase tracking-wider text-default-500 font-semibold">
              Как пользоваться
            </span>
          </div>
          <div className="px-3.5 py-3 space-y-2.5">
            <HintRow
              icon={<span className="marker-house only-active" style={{ width: 16, height: 16 }} />}
              text="Красная — есть активные объявления"
            />
            <HintRow
              icon={<span className="marker-house only-deact" style={{ width: 16, height: 16 }} />}
              text="Серая — были, но сейчас сняты"
            />
            <HintRow
              icon={<span className="marker-house no-ads" style={{ width: 12, height: 12 }} />}
              text="Маленькая серая — дом без объявлений"
            />
            <HintRow
              icon={
                <svg viewBox="0 0 24 24" width={16} height={16} fill="none" stroke="currentColor" strokeWidth={2} className="text-primary">
                  <circle cx="11" cy="11" r="7" />
                  <path d="M21 21l-4.3-4.3" strokeLinecap="round" />
                </svg>
              }
              text="Поиск — найти дом по адресу"
            />
            <HintRow
              icon={
                <svg viewBox="0 0 24 24" width={16} height={16} fill="none" stroke="currentColor" strokeWidth={2} className="text-primary">
                  <path d="M9 11l3 3L22 4" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              }
              text="Клик по дому — открывает объявления"
            />
            <HintRow
              icon={
                // small inline swatch — same violet as the map pin.
                <span
                  className="block w-3 h-3 rounded-full"
                  style={{ background: 'linear-gradient(180deg, #a78bfa 0%, #7c3aed 100%)' }}
                />
              }
              text="Фиолетовая капля — выбранный дом"
            />
          </div>

          {/* Stats section — collapsed into the same popover so it
              lives off-canvas by default. The previous "always-visible
              top-bar stats row" ate vertical space and hid map
              content; this gives the same info at the cost of one
              tap when the user actually wants it. */}
          {stats && (
            <>
              <div className="px-3.5 pt-2.5 pb-2 flex items-center gap-1.5 border-t border-default-100">
                <span className="w-1.5 h-1.5 rounded-full bg-default-400" />
                <span className="text-[10px] uppercase tracking-wider text-default-500 font-semibold">
                  Статистика
                </span>
              </div>
              <div className="px-2 pb-2.5">
                <StatsBar
                  stats={stats}
                  loading={loading}
                  count={count}
                  // On phone, hide the "Домов" column — the popover
                  // is narrow and three big numbers don't fit
                  // legibly. Desktop keeps all three.
                  compact={isMobile}
                />
              </div>
            </>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function HintRow({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="flex items-start gap-2.5">
      <div className="mt-0.5 shrink-0 w-5 h-5 flex items-center justify-center">{icon}</div>
      <div className="text-[12px] text-foreground/80 leading-snug min-w-0 flex-1">{text}</div>
    </div>
  );
}

// 2GIS-style teardrop pin in the brand primary (red) — one shape, one
// colour, used both for the search result and for the currently-open
// house, so the user has a single visual language for "the map is
// pointing at this exact spot". The CSS lives in globals.css under
// `.location-pin*`; both components below reuse the same divIcon.
const locationPinIcon = () =>
  L.divIcon({
    className: 'location-pin-wrap',
    html: `
      <div class="location-pin">
        <div class="location-pin-pulse"></div>
        <div class="location-pin-dot"></div>
      </div>
    `,
    iconSize: [28, 40],
    iconAnchor: [14, 38],
  });

function SearchPin({ lat, lng }: { lat: number; lng: number }) {
  const map = useMap();
  return (
    <Marker
      position={[lat, lng]}
      icon={locationPinIcon()}
      zIndexOffset={1000}
      eventHandlers={{ click: () => map.flyTo([lat, lng], Math.max(map.getZoom(), 17)) }}
    />
  );
}

// Drawn on top of the currently-opened house so the user can always
// see which marker the side panel is about, even after panning away.
// Click on the pin → fly the map back to the house at street level,
// so the user has a one-tap "recentre on this house" shortcut.
// Survives drawer close on mobile so the user has a stable visual
// anchor for "the house I was just looking at".
function SelectedPin({ lat, lng }: { lat: number; lng: number }) {
  const map = useMap();
  return (
    <Marker
      position={[lat, lng]}
      icon={locationPinIcon()}
      zIndexOffset={1500}
      eventHandlers={{
        click: () => map.flyTo([lat, lng], Math.max(map.getZoom(), 17), { duration: 0.5 }),
      }}
    />
  );
}

export default function MapApp() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [items, setItems] = useState<House[]>([]);
  const [bounds, setBounds] = useState<{ b: L.LatLngBounds; z: number } | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<HouseDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [loading, setLoading] = useState(false);
  const [searchPinMsg, setSearchPinMsg] = useState<string | null>(null);

  /** Search pin separate from the panel — flying the map doesn't have
   * to also open the panel. On mobile especially, we just drop the pin
   * and let the user tap the floating "Open" button when they want. */
  const [searchPin, setSearchPin] = useState<{ lat: number; lng: number; houseId: number | null; address: string } | null>(null);

  const flyRef = useRef<((lat: number, lng: number, z?: number) => void) | null>(null);
  const [isMobile, setIsMobile] = useState(false);

  /** Внешний ID объявления из `?photoAd=…`. Когда задан и `detail` уже
   *  загрузился — HousePanel сама откроет AdPhotosModal. Используется
   *  ссылкой из Grist Active_ads → `photos_url`. */
  const [autoOpenPhotoAdId, setAutoOpenPhotoAdId] = useState<string | null>(null);

  useEffect(() => {
    fetchStats().then(setStats).catch(() => {});
  }, []);

  // Detect mobile vs desktop — drives the search UX (mobile = pin only,
  // desktop = fly + open panel).
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mq = window.matchMedia('(max-width: 767px)');
    const apply = () => setIsMobile(mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, []);

  // Auto-open house from ?house=ID query param.
  // NB: zoom-to-house — после openCluster() мы получим HouseDetail с
  // lat/lng и летим на координаты дома. Без этого юзер видел бы дефолтный
  // вид Москвы и только что открытую панель — не понятно, где этот дом.
  //
  // Также парсим `?photoAd=EXTERNAL_ID` (deep-link из Grist Active_ads) —
  // после загрузки дома панель сама откроет AdPhotosModal для этого
  // объявления, без ручного клика по 📷.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    const houseId = params.get('house');
    const photoAd = params.get('photoAd');
    if (photoAd) setAutoOpenPhotoAdId(photoAd);
    if (!houseId) return;
    const id = Number(houseId);
    if (Number.isNaN(id) || id <= 0) {
      const url = new URL(window.location.href);
      url.searchParams.delete('house');
      window.history.replaceState({}, '', url.toString());
      return;
    }
    let cancelled = false;
    (async () => {
      const detail = await openCluster(id);
      if (cancelled || !detail) return;
      const h = detail.house;
      if (h && h.lat != null && h.lng != null) {
        // Если дом без координат (редко) — оставляем дефолтный вид.
        const fly = flyRef.current;
        if (fly) {
          fly(h.lat, h.lng, 17);
        }
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadHouses = useCallback(
    async (b: { b: L.LatLngBounds; z: number } | null) => {
      if (!b) return;
      setLoading(true);
      try {
        const sw = b.b.getSouthWest();
        const ne = b.b.getNorthEast();
        const data = await fetchClusters({
          min_lat: sw.lat, max_lat: ne.lat,
          min_lng: sw.lng, max_lng: ne.lng,
          zoom: b.z,
          with_ads_only: false,
          limit: 50000,
        });
        setItems(data);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  // Initial fetch on mount
  useEffect(() => {
    const fakeBounds = {
      getSouthWest: () => ({ lat: 55.45, lng: 37.42 }),
      getNorthEast: () => ({ lat: 56.06, lng: 37.82 }),
    } as L.LatLngBounds;
    loadHouses({ b: fakeBounds, z: 12 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadHouses(bounds);
  }, [bounds, loadHouses]);

  const openCluster = useCallback(async (id: number): Promise<HouseDetail | null> => {
    setSelectedId(id);
    setLoadingDetail(true);
    setSelectedDetail(null);
    if (typeof window !== 'undefined') {
      const url = new URL(window.location.href);
      url.searchParams.set('house', String(id));
      window.history.replaceState({}, '', url.toString());
    }
    try {
      const d = await fetchCluster(id);
      setSelectedDetail(d);
      return d;
    } catch (e) {
      if (typeof window !== 'undefined') {
        const url = new URL(window.location.href);
        url.searchParams.delete('house');
        window.history.replaceState({}, '', url.toString());
      }
      setSelectedId(null);
      console.error('openCluster failed', e);
      return null;
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  const close = useCallback(() => {
    // Close the drawer (`selectedId` drives the Drawer's `isOpen`).
    // NOTE: we intentionally keep `selectedDetail` set so the
    // SelectedPin stays on the map after the user dismisses the
    // panel — especially on mobile, where the user often closes the
    // sheet to peek at the surrounding houses. The pin acts as a
    // visual anchor for "the house I was just looking at", and
    // disappears only when a different house is opened.
    setSelectedId(null);
    setSearchPin(null);
    setAutoOpenPhotoAdId(null);
    if (typeof window !== 'undefined') {
      const url = new URL(window.location.href);
      url.searchParams.delete('house');
      url.searchParams.delete('photoAd');
      window.history.replaceState({}, '', url.toString());
    }
  }, []);

  /** When the user picks a Yandex suggest entry:
   *  1) fly the map to the lat/lng (cyan pin appears)
   *  2) on mobile — DON'T auto-open the panel; show the floating "Open" button
   *  3) on desktop — also open the panel
   *  If address is Yandex-only (not in DB), show a toast. */
  const handleSearchPick = useCallback(async (item: SuggestItem) => {
    setSearchPinMsg(null);
    let lat: number | null = null;
    let lng: number | null = null;
    let houseId: number | null = null;

    if (item.house && item.house.lat != null && item.house.lng != null) {
      lat = item.house.lat;
      lng = item.house.lng;
      houseId = item.house.id;
    } else {
      try {
        const g = await fetchGeocode(item.formatted_address);
        if (g.house && g.house.lat != null && g.house.lng != null) {
          lat = g.house.lat;
          lng = g.house.lng;
          houseId = g.house.id;
        } else {
          setSearchPinMsg('Дом не найден в нашей базе');
          return;
        }
      } catch (e) {
        console.error('geocode failed', e);
        setSearchPinMsg('Не удалось получить координаты');
        return;
      }
    }

    if (lat == null || lng == null) {
      setSearchPinMsg('Адрес не найден');
      return;
    }

    // Drop the search pin and fly there. Don't clear the panel — the
    // user might already be looking at another house.
    setSearchPin({ lat, lng, houseId, address: item.title });

    const targetZoom = 18;
    const fly = flyRef.current;
    if (fly) {
      fly(lat, lng, targetZoom);
    } else if (typeof window !== 'undefined') {
      const url = new URL(window.location.href);
      url.searchParams.set('lat', String(lat));
      url.searchParams.set('lng', String(lng));
      url.searchParams.set('zoom', String(targetZoom));
      window.history.replaceState({}, '', url.toString());
    }

    // Desktop: also open the panel immediately (faster — they want to
    // see what's there). Mobile: leave it for the user to tap "Open".
    if (!isMobile && houseId != null) {
      openCluster(houseId);
    }
  }, [openCluster, isMobile]);

  return (
    <div className="relative h-screen w-screen overflow-hidden" data-react-aria-top-layer>
      {/* Top bar */}
      <div className="absolute top-0 left-0 right-0 z-[1000] p-2 sm:p-3 flex items-start gap-2 pointer-events-none flex-col sm:flex-row">
        <div className="pointer-events-auto bg-white shadow-card-lg rounded-2xl border border-default-200 px-2.5 sm:px-3 py-2 flex items-center gap-2 min-w-0 w-full sm:flex-1 sm:max-w-2xl">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center text-white font-display font-bold text-sm shadow-glow shrink-0">
            F
          </div>
          <div className="hidden md:block shrink-0">
            <div className="font-display font-semibold text-foreground text-sm leading-none">Flipper</div>
            <div className="text-[10px] text-default-500 mt-0.5 leading-none">Москва · недвижимость</div>
          </div>
          <div className="hidden md:block w-px h-7 bg-default-200 mx-1 shrink-0" />
          <SearchBox onPick={handleSearchPick} />
        </div>
        {/* StatsBar used to live right under the search input — it
            ate ~80px of vertical space across the entire top of the
            viewport, occluding markers near the centre of the map.
            Now it's tucked into the "?" help popover (see
            MapHelpButton below) so it's available when the user
            actually needs it, out of the way the rest of the time. */}
      </div>

      <MapContainer
        center={MOSCOW}
        zoom={11}
        className="h-full w-full"
        zoomControl={true}
        preferCanvas={true}
      >
        <FitToMoscow />
        <CenterButton />
        <MapFlyController flyRef={flyRef} />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &middot; &copy; <a href="https://carto.com/attributions">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"
          maxZoom={19}
        />
        <MapEvents onBoundsChange={(b, z) => setBounds({ b, z })} />

        {items.map((item, i) => {
          if (item.is_synthetic) {
            return (
              <ClusterMarker
                key={`c-${i}-${item.lat}-${item.lng}`}
                lat={item.lat!}
                lng={item.lng!}
                count={item.house_count ?? 0}
              />
            );
          }
          // The selected house's regular marker STAYS on the map (it
          // used to be hidden — now it isn't, so the user can see the
          // count badge even after the side panel opens). On top of it
          // we render a primary-colored "selected" pin so the user has
          // an obvious visual anchor for which house is currently open.
          return (
            <Marker
              key={`h-${item.id}-${i}`}
              position={[item.lat!, item.lng!]}
              icon={makeHouseIcon(item.active_count, item.deactivated_count)}
              eventHandlers={{
                click: () => openCluster(item.id),
              }}
            />
          );
        })}

        {/* Cyan search pin — drops when a search result is picked. */}
        {searchPin && (
          <SearchPin lat={searchPin.lat} lng={searchPin.lng} />
        )}

        {/* Primary "selected" pin — drawn on top of the currently-open
            house so the user can always see which house the side panel
            is about, even after panning away. Uses the house's own
            lat/lng from the loaded detail (NOT from the map items,
            which can scroll out of view). */}
        {selectedDetail &&
          selectedDetail.house.lat != null &&
          selectedDetail.house.lng != null && (
            <SelectedPin
              lat={selectedDetail.house.lat}
              lng={selectedDetail.house.lng}
            />
          )}
      </MapContainer>

      {/* Floating "Open" button — appears on mobile when a search
          result was picked. The map has flown to the location and the
          cyan pin is on the map, but the panel stays closed so the
          user can decide when to open it. */}
      {searchPin && searchPin.houseId != null && selectedId !== searchPin.houseId && (
        <div className="md:hidden absolute left-3 right-3 bottom-3 z-[1100] animate-fade-in pointer-events-none">
          <div className="bg-white shadow-panel rounded-2xl border border-default-200 p-3 flex items-center gap-3 pointer-events-auto">
            <div className="min-w-0 flex-1">
              <div className="text-[10px] uppercase tracking-wider text-default-500 font-semibold mb-0.5">
                Найдено
              </div>
              <div className="text-sm font-medium text-foreground truncate">
                {searchPin.address}
              </div>
            </div>
            <Button
              size="sm"
              color="primary"
              onPress={() => {
                if (searchPin.houseId != null) openCluster(searchPin.houseId);
              }}
            >
              Открыть
            </Button>
            <Button
              isIconOnly
              size="sm"
              variant="light"
              onPress={() => setSearchPin(null)}
              aria-label="убрать пин"
              className="text-default-500"
            >
              ✕
            </Button>
          </div>
        </div>
      )}

      <HousePanel
        open={selectedId !== null}
        houseId={selectedId ?? 0}
        detail={selectedDetail}
        loading={loadingDetail}
        onClose={close}
        autoOpenPhotoAdId={autoOpenPhotoAdId}
      />

      {/* Map help — small "?" button always present (works whether the
          side panel is open or not). Tap it for the marker legend,
          quick how-to, AND the stats panel (lives in the same popover
          now, since the user asked to keep it out of the canvas). */}
      <MapHelpButton stats={stats} loading={loading} count={items.length} isMobile={isMobile} />

      {/* Search-result toast */}
      {searchPinMsg && (
        <div
          className="absolute top-16 left-1/2 -translate-x-1/2 z-[1050] shadow-panel rounded-2xl border border-default-200 px-3.5 py-2 text-xs text-foreground bg-white flex items-center gap-2 animate-fade-in cursor-pointer"
          onClick={() => setSearchPinMsg(null)}
          role="status"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-warning" />
          {searchPinMsg}
          <span className="text-default-400 ml-1">✕</span>
        </div>
      )}
    </div>
  );
}

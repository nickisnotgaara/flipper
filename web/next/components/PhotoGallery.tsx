'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import useEmblaCarousel from 'embla-carousel-react';
import { Modal, ModalContent, ModalHeader, ModalBody, Button } from '@heroui/react';
import { CameraIcon, ChevronLeftIcon, ChevronRightIcon, FullscreenIcon } from './icons';

type Photo = {
  id?: string | number;
  fullUrl?: string;
  thumbnail2Url?: string;
  thumbnailUrl?: string;
  miniUrl?: string;
  isDefault?: boolean;
  isCianLayout?: boolean;
};

type Props = {
  /** Whether the gallery is open. */
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  /** All photos for this ad, in display order. */
  photos: Photo[];
  /** Which photo to start at when opening. */
  startIndex?: number;
  /**
   * If true, render the gallery CONTENT (main image, arrows, thumbnail
   * strip, photo count) without the surrounding <Modal>. Used when
   * the gallery is embedded in a parent modal (e.g. AdPhotosModal)
   * — nesting HeroUI <Modal>s is not supported and renders only the
   * outer one. In that case isOpen/onOpenChange are still observed
   * (we still apply wheel/keyboard listeners while the parent is up).
   */
  asContent?: boolean;
};

/**
 * 2GIS-style photo gallery modal.
 *
 * Layout (matches the reference screenshot):
 *   ┌──────────────────────────────────────────┐
 *   │                              [↗]  [×]    │  ← top-right actions
 *   │                                          │
 *   │   [‹]   ┌─────────────────────┐   [›]   │  ← main image + side arrows
 *   │        │                     │          │     (also draggable!)
 *   │        │     active photo    │          │
 *   │        │                     │          │
 *   │        └─────────────────────┘          │
 *   │                                          │
 *   │  ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐     │  ← thumbnail strip
 *   │  └──┘ └──┘ └──┘ └──┘ └──┘ └──┘ └──┘     │
 *   │                                          │
 *   │  [📷 N фото]                            │  ← photo count badge
 *   └──────────────────────────────────────────┘
 *
 * Interaction:
 *   - Drag the main image left/right with mouse or finger (embla)
 *   - Click the side arrows
 *   - Scroll the mouse wheel up/down (desktop)
 *   - Use ←/→ keys
 *   - Click a thumbnail to jump
 */
export default function PhotoGallery({ isOpen, onOpenChange, photos, startIndex = 0, asContent = false }: Props) {
  // Single source of truth for "which photo is shown". Updated by:
  //   - thumbnail click (external)
  //   - embla's `select` event (user dragged the main image)
  //   - prev/next buttons + wheel + keyboard (via `go`)
  const [active, setActive] = useState(startIndex);

  // embla drives the main image — gives us free drag/swipe on both
  // mouse (desktop) and touch (mobile). `loop:true` wraps the
  // navigation so dragging past the end lands on the first photo.
  const [emblaRef, emblaApi] = useEmblaCarousel({
    loop: true,
    align: 'center',
    startIndex,
    duration: 25,
  });

  const go = useCallback((delta: number) => {
    setActive((i) => {
      if (photos.length === 0) return 0;
      return (i + delta + photos.length) % photos.length;
    });
  }, [photos.length]);

  // Push external active changes (thumb click, prev/next, wheel,
  // keyboard) into embla. We skip the write when embla is already
  // showing that index — otherwise the select event would echo back
  // and we'd get an infinite loop with embla's snap animation.
  useEffect(() => {
    if (!emblaApi) return;
    if (active === emblaApi.selectedScrollSnap()) return;
    emblaApi.scrollTo(active);
  }, [active, emblaApi]);

  // Push embla drag changes back into active. Without this, dragging
  // the main image would update the carousel but leave the thumbnail
  // strip and counter showing the old photo.
  useEffect(() => {
    if (!emblaApi) return;
    const onSelect = () => {
      const newIndex = emblaApi.selectedScrollSnap();
      setActive((prev) => (prev === newIndex ? prev : newIndex));
    };
    emblaApi.on('select', onSelect);
    emblaApi.on('reInit', onSelect);
    return () => {
      emblaApi.off('select', onSelect);
      emblaApi.off('reInit', onSelect);
    };
  }, [emblaApi]);

  // Reset to startIndex every time the modal opens. Without this the
  // user would land on whatever they were last looking at.
  useEffect(() => {
    if (isOpen && emblaApi) emblaApi.scrollTo(startIndex, true);
  }, [isOpen, emblaApi, startIndex]);

  // Wheel handler — desktop-only. Mouse wheel (or trackpad two-finger
  // scroll) advances one photo. The 400ms lock prevents accidental
  // double-fires from a single fluid wheel gesture.
  useEffect(() => {
    if (!isOpen) return;
    let lock = false;
    const onWheel = (e: WheelEvent) => {
      if (lock) return;
      // Ignore tiny inertial deltas so the page can still scroll
      // slightly while the gallery is open (e.g. touchpad jitter).
      if (Math.abs(e.deltaY) < 16 && Math.abs(e.deltaX) < 16) return;
      e.preventDefault();
      lock = true;
      const dir = e.deltaY > 0 || e.deltaX > 0 ? 1 : -1;
      go(dir);
      window.setTimeout(() => { lock = false; }, 400);
    };
    window.addEventListener('wheel', onWheel, { passive: false });
    return () => window.removeEventListener('wheel', onWheel);
  }, [isOpen, go]);

  // Keyboard handler — Esc is handled by HeroUI; we just add ←/→.
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft') { e.preventDefault(); go(-1); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); go(1); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, go]);

  // The thumbnail strip auto-scrolls to keep the active thumb in
  // view. We do this with a ref + scrollIntoView rather than
  // re-rendering on every active change, so swiping the main
  // image stays smooth.
  const stripRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!isOpen) return;
    const el = stripRef.current?.querySelector<HTMLElement>(`[data-thumb-idx="${active}"]`);
    el?.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
  }, [active, isOpen]);

  if (photos.length === 0) return null;

  const thumbSrc = (p: Photo) => p.thumbnail2Url || p.fullUrl || p.thumbnailUrl || p.miniUrl || '';

  // Только контент карусели + ленты превью. Без оборачивающего
  // <Modal> и без top action row (fullscreen/close) — это на совести
  // родительского мода (PhotoGallery оборачивает сам, AdPhotosModal
  // берёт готовый контент и кладёт в свой <Modal> + свой action bar).
  const galleryContent = (
    <>
      <ModalHeader className="sr-only">
        Фотографии объявления
      </ModalHeader>

      <ModalBody>
            {/* Main image carousel. embla handles drag/swipe here —
                both mouse (desktop) and touch (mobile). The viewport
                is `embla-viewport` so the global CSS hardening rules
                (no link-drag, user-select:none, touch-action:pan-y)
                apply, and the cursor switches to grab on hover so
                the user can tell it's draggable. */}
            <div className="relative flex-1 min-h-0 flex items-center justify-center sm:px-16 pt-6">
              <div
                className="embla-viewport h-full w-full overflow-hidden cursor-grab active:cursor-grabbing"
                ref={emblaRef}
                style={{ touchAction: 'pan-y' }}
                onDragStart={(e) => e.preventDefault()}
              >
                <div className="flex h-full">
                  {photos.map((p, i) => {
                    const src = p.fullUrl || p.thumbnail2Url || p.thumbnailUrl;
                    if (!src) {
                      return (
                        <div
                          key={p.id ?? i}
                          className="shrink-0 basis-full flex items-center justify-center px-2"
                        >
                          <div className="text-default-400 text-sm">Нет изображения</div>
                        </div>
                      );
                    }
                    return (
                      <div
                        key={p.id ?? i}
                        className="shrink-0 basis-full flex items-center justify-center px-2"
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={src}
                          alt={p.isCianLayout ? 'Планировка' : `Фото ${i + 1}`}
                          className="max-h-full max-w-full object-contain rounded-xl shadow-card select-none"
                          draggable={false}
                        />
                      </div>
                    );
                  })}
                </div>
              </div>

              <Button
                isIconOnly
                size="sm"
                radius="full"
                variant="solid"
                aria-label="Предыдущее фото"
                onPress={() => go(-1)}
                className="absolute left-2 sm:left-4 top-1/2 -translate-y-1/2 w-10 h-10 min-w-10 !p-0 bg-white text-default-700 border border-default-200 shadow-card data-[hover=true]:bg-default-50 transition"
              >
                <ChevronLeftIcon size={20} />
              </Button>
              <Button
                isIconOnly
                size="sm"
                radius="full"
                variant="solid"
                aria-label="Следующее фото"
                onPress={() => go(1)}
                className="absolute right-2 sm:right-4 top-1/2 -translate-y-1/2 w-10 h-10 min-w-10 !p-0 bg-white text-default-700 border border-default-200 shadow-card data-[hover=true]:bg-default-50 transition"
              >
                <ChevronRightIcon size={20} />
              </Button>
            </div>

            {/* Bottom row: thumbnail strip + photo count.
                `shrink-0` is critical — without it the main image's
                flex-1 would happily eat the strip's space and push
                it off the bottom of the modal. `pt-1` gives the
                active thumb's `outline` room to render. */}
            <div className="shrink-0 sm:px-6 pb-3 sm:pb-5 pt-1 flex flex-col gap-3">
              <div
                ref={stripRef}
                // Drag the strip with mouse / finger:
                //   - touch-action:pan-x  → browser only claims
                //     horizontal swipes
                //   - select-none         → no text selection
                //   - cursor-grab/active → desktop hint
                className="flex gap-1.5 overflow-x-auto px-3 py-2 snap-x snap-mandatory select-none cursor-grab active:cursor-grabbing"
                style={{ touchAction: 'pan-x' }}
                onDragStart={(e) => e.preventDefault()}
              >
                {photos.map((p, i) => {
                  const src = thumbSrc(p);
                  if (!src) return null;
                  const isActive = i === active;
                  return (
                    <Button
                      key={p.id ?? i}
                      isIconOnly
                      radius="md"
                      variant="flat"
                      data-thumb-idx={i}
                      onPress={() => setActive(i)}
                      // `outline` instead of `ring` so the focus
                      // ring isn't clipped by the parent
                      // overflow-x-auto.
                      className={`shrink-0 snap-start relative w-14 h-14 sm:w-20 sm:h-20 min-w-14 sm:min-w-20 !p-0 overflow-hidden transition-all ${
                        isActive
                          ? '!outline !outline-[2.5px] !outline-primary !outline-offset-2 bg-default-100'
                          : 'opacity-65 hover:opacity-100 !outline !outline-1 !outline-default-300 !outline-offset-0 bg-default-100'
                      }`}
                      aria-label={`Фото ${i + 1}`}
                      aria-current={isActive ? 'true' : undefined}
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={src}
                        alt=""
                        loading="lazy"
                        draggable={false}
                        className="w-full h-full object-cover"
                      />
                      {p.isCianLayout && (
                        <span className="absolute bottom-0.5 right-0.5 inline-flex items-center justify-center w-4 h-4 rounded-sm bg-white/95 text-default-700 border border-default-200">
                          <svg width={9} height={9} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.6}>
                            <rect x="2" y="2.5" width="12" height="11" rx="1" />
                            <path d="M5.5 2.5v11M10.5 6.5h3.5M2 6.5h3.5" />
                          </svg>
                        </span>
                      )}
                    </Button>
                  );
                })}
              </div>

              <div className="flex items-center justify-center">
                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white text-default-700 text-[12px] font-medium border border-default-200 shadow-card">
                  <CameraIcon size={13} className="text-default-500" />
                  {photos.length} фото
                </span>
              </div>
            </div>
          </ModalBody>
    </>
  );

  // Если вызвали в режиме asContent (встроено в родительский Modal,
  // например AdPhotosModal) — отдаём только содержимое, без обёртки.
  // Иначе оборачиваем в свой <Modal> с top action row (fullscreen +
  // close) сверху.
  if (asContent) return galleryContent;

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      // Plain dark backdrop — the modal itself is white now, so we
      // want a strong contrast behind it (not a frosted blur which
      // would clash with the white surface).
      backdrop="opaque"
      isDismissable
      // Largest preset; the actual "cover" geometry is emulated via
      // classNames below.
      size="5xl"
      hideCloseButton
      classNames={{
        wrapper: 'z-[1300]',
        backdrop: 'z-[1300] bg-black/55',
        // "cover" emulation: full width minus 8/40px margins, max-
        // height so the dialog never overflows the viewport. h-full
        // + flex flex-col lets ModalBody's inner layout own the
        // vertical space, and overflow-hidden guarantees the
        // thumbnail strip never bleeds outside the rounded corners.
        base: 'm-2 sm:m-10 bg-white rounded-2xl border border-default-200 shadow-card-lg max-w-none w-[calc(100vw-1rem)] sm:w-[calc(100vw-5rem)] h-full max-h-[calc(100vh-1rem)] sm:max-h-[calc(100vh-5rem)] p-0 flex flex-col overflow-hidden',
        body: 'p-0 flex-1 min-h-0 flex flex-col overflow-hidden',
      }}
    >
      <ModalContent>
        <div className="relative flex flex-col h-full">
          {/* Top action row: fullscreen + close. White pill so it
              reads on the white modal surface (sits over the photo,
              where a dark pill would be invisible on light photos). */}
          <div className="absolute top-3 right-3 z-20 flex items-center gap-2">
            <Button
              isIconOnly
              size="sm"
              radius="full"
              variant="solid"
              aria-label="открыть фото в полный размер"
              className="bg-white text-default-700 border border-default-200 shadow-card hover:bg-default-50 w-9 h-9"
              onPress={() => {
                const cur = photos[active];
                const href = cur?.fullUrl || cur?.thumbnail2Url || cur?.thumbnailUrl;
                if (href) window.open(href, '_blank', 'noopener,noreferrer');
              }}
            >
              <FullscreenIcon size={16} />
            </Button>
            <Button
              isIconOnly
              size="sm"
              radius="full"
              variant="solid"
              aria-label="закрыть"
              onPress={() => onOpenChange(false)}
              className="bg-white text-default-700 border border-default-200 shadow-card hover:bg-default-50 w-9 h-9"
            >
              <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </Button>
          </div>

          {galleryContent}
        </div>
      </ModalContent>
    </Modal>
  );
}

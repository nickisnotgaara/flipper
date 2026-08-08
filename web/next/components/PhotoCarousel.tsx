'use client';

import { useCallback, useEffect, useState } from 'react';
import useEmblaCarousel from 'embla-carousel-react';
import { Button } from '@heroui/react';
import { PlanIcon, ChevronLeftIcon, ChevronRightIcon } from './icons';
import PhotoGallery from './PhotoGallery';

type Photo = {
  /** Stable id from cian ("235324311" as string). */
  id?: string | number;
  fullUrl?: string;
  thumbnail2Url?: string;
  thumbnailUrl?: string;
  miniUrl?: string;
  isDefault?: boolean;
  isCianLayout?: boolean;
};

/**
 * Pick the best thumbnail URL we have. CIAN sends fullUrl (big),
 * thumbnail2Url (medium, used here), thumbnailUrl (small), miniUrl (tiny).
 * Fall back down the chain.
 */
function pickThumb(p: Photo): string | null {
  return p.thumbnail2Url || p.fullUrl || p.thumbnailUrl || p.miniUrl || null;
}

/**
 * 2GIS-style image carousel:
 *   - 3 thumbnails visible at once, ~110x110, 4px gap, rounded 12px
 *   - Left/right circular arrow buttons overlaid on the edges
 *     (only when there is more to scroll in that direction)
 *   - Click any image → open fullUrl in a new tab
 *   - Stops propagation on click so it doesn't trigger the parent <a> card link
 *
 * Renders nothing if `photos` is empty / not an array. This keeps the rest
 * of the card layout stable — the image area simply collapses.
 */
export default function PhotoCarousel({
  photos,
  adUrl,
}: {
  photos: unknown;
  adUrl?: string;
}) {
  // Normalize: only accept array of objects with at least one URL field.
  const list: Photo[] = Array.isArray(photos)
    ? (photos.filter((p) => p && typeof p === 'object' && pickThumb(p as Photo)) as Photo[])
    : [];

  // 3 thumbs visible, scroll one slide at a time. align='start' so the first
  // slide sits flush against the left edge after a prev-click. `dragFree=false`
  // (the default) so snaps are clean.
  const [emblaRef, emblaApi] = useEmblaCarousel({
    align: 'start',
    slidesToScroll: 1,
    containScroll: 'trimSnaps',
  });

  const [canPrev, setCanPrev] = useState(false);
  const [canNext, setCanNext] = useState(false);
  const [selected, setSelected] = useState(0);
  const [scrollSnaps, setScrollSnaps] = useState<number[]>([]);

  // Photo gallery modal state. The carousel itself only opens it; the
  // gallery manages the rest (active index, keyboard nav, etc).
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [galleryStart, setGalleryStart] = useState(0);

  const onSelect = useCallback(() => {
    if (!emblaApi) return;
    setCanPrev(emblaApi.canScrollPrev());
    setCanNext(emblaApi.canScrollNext());
    setSelected(emblaApi.selectedScrollSnap());
  }, [emblaApi]);

  useEffect(() => {
    if (!emblaApi) return;
    onSelect();
    setScrollSnaps(emblaApi.scrollSnapList());
    emblaApi.on('select', onSelect);
    emblaApi.on('reInit', onSelect);
  }, [emblaApi, onSelect]);

  if (list.length === 0) return null;

  const scrollPrev = () => {
    emblaApi?.scrollPrev();
  };
  const scrollNext = () => {
    emblaApi?.scrollNext();
  };
  const onThumbClick = (e: React.MouseEvent, _p: Photo, i: number) => {
    // Open the in-app photo gallery at the clicked photo. We stop
    // propagation so the parent <a> card (which wraps the whole
    // carousel) doesn't navigate to the cian offer.
    e.preventDefault();
    e.stopPropagation();
    setGalleryStart(i);
    setGalleryOpen(true);
  };

  return (
    <div
      className="relative -mx-1 select-none"
      // Card-level <a> wraps the whole carousel — see AdCard.tsx for
      // the anchor-level drag hardening. Here we also kill any
      // bubbling HTML5 dragstart and stop click propagation so the
      // card link doesn't fire on a quick mousedown+up.
      //
      // `onPointerDown` / `onMouseDown` with stopPropagation() are
      // explicit "let embla see this first" hints — without them some
      // browsers bubble the pointer down to the parent <a> which can
      // then steal focus and confuse embla's drag tracking. Cost is
      // ~nothing because we only stop bubbling, not default behavior.
      onDragStart={(e) => e.preventDefault()}
      onPointerDown={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    >
      <div
        // The embla viewport is the actual element that receives
        // pointer events. The `embla-viewport` class + inline style
        // both apply:
        //   - touch-action:pan-y tells the browser "I claim horizontal
        //     swipes, you can keep vertical scrolling" (mobile)
        //   - user-select:none stops long-press / iOS callout from
        //     stealing the gesture on touch devices
        //   - the .embla-viewport class (in globals.css) also kills
        //     image drag and link drag on the parent <a>
        //   - cursor-grab / active:cursor-grabbing gives desktop
        //     users a clear "you can drag this" hint
        //   - draggable={false} on the viewport itself stops
        //     Chrome from initiating a link-drag ghost from inside
        //     the embla box (some versions of Chromium ignore the
        //     `draggable={false}` on the parent <a> when the drag
        //     origin is the inner <button> or the empty <div> gap).
        className="embla-viewport overflow-hidden cursor-grab active:cursor-grabbing"
        ref={emblaRef}
        draggable={false}
        style={{
          touchAction: 'pan-y',
          userSelect: 'none',
          WebkitUserSelect: 'none',
          WebkitTouchCallout: 'none',
        }}
      >
        <div className="flex gap-1">
          {list.map((p, i) => {
            const thumb = pickThumb(p);
            return (
              <div
                // Slide width: container width minus the small horizontal
                // padding (-mx-1 + px-1) divided into 3 thumbs + 2 gaps of
                // 4px each. min-w-0 keeps it from overflowing the flex math.
                key={p.id ?? i}
                className="embla-slide shrink-0 basis-[calc((100%-8px)/3)] min-w-0"
              >
                {/* Use a HeroUI <Button> (rendered as <button>) so the
                    thumbnail click can sit inside the card-level <a> in
                    HousePanel without nesting anchors (invalid HTML).
                    The button opens the in-app gallery. */}
                <Button
                  isIconOnly
                  radius="lg"
                  variant="flat"
                  onPress={(e) => onThumbClick(e as any, p, i)}
                  className="relative aspect-square w-full !p-0 !min-w-0 overflow-hidden rounded-xl bg-default-100 group/thumb cursor-pointer data-[hover=true]:bg-default-100"
                  title={p.isCianLayout ? 'Планировка' : `Фото ${i + 1}`}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={thumb!}
                    alt={p.isCianLayout ? 'Планировка' : `Фото ${i + 1}`}
                    loading="lazy"
                    className="h-full w-full object-cover transition-transform duration-200 group-hover/thumb:scale-105"
                    draggable={false}
                  />
                  {p.isCianLayout && (
                    <span
                      className="absolute bottom-1 right-1 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium bg-white/95 text-default-700 backdrop-blur-sm shadow-card"
                      title="Планировка"
                    >
                      <PlanIcon size={11} className="text-primary" />
                      план
                    </span>
                  )}
                </Button>
              </div>
            );
          })}
        </div>
      </div>

      {canPrev && (
        <Button
          isIconOnly
          size="sm"
          radius="full"
          variant="solid"
          aria-label="Предыдущие фото"
          onPress={scrollPrev}
          className="absolute left-1 top-1/2 -translate-y-1/2 z-10 w-7 h-7 min-w-7 !p-0 bg-white/95 hover:bg-white shadow-card text-default-700 transition data-[hover=true]:bg-white"
        >
          <ChevronLeftIcon />
        </Button>
      )}
      {canNext && (
        <Button
          isIconOnly
          size="sm"
          radius="full"
          variant="solid"
          aria-label="Следующие фото"
          onPress={scrollNext}
          className="absolute right-1 top-1/2 -translate-y-1/2 z-10 w-7 h-7 min-w-7 !p-0 bg-white/95 hover:bg-white shadow-card text-default-700 transition data-[hover=true]:bg-white"
        >
          <ChevronRightIcon />
        </Button>
      )}

      {/* Dot indicators only if there are 4+ photos (3 is the visible
          count, so dots make sense when there's at least one hidden slide). */}
      {scrollSnaps.length > 3 && (
        <div className="absolute bottom-1 left-0 right-0 flex justify-center gap-1 pointer-events-none">
          {scrollSnaps.map((_, i) => (
            <span
              key={i}
              className={`h-1 rounded-full transition-all ${
                i === selected ? 'w-4 bg-white' : 'w-1 bg-white/50'
              }`}
            />
          ))}
        </div>
      )}

      {/* Full-screen photo gallery. Opens when the user taps any
          thumbnail; click on a thumbnail stops propagation so the
          card-level <a> doesn't navigate to cian. HeroUI Modal portals
          out to <body>, so it sits above the Drawer (z-1100) and the
          map even though it lives inside the carousel subtree. */}
      <PhotoGallery
        isOpen={galleryOpen}
        onOpenChange={setGalleryOpen}
        photos={list}
        startIndex={galleryStart}
      />
    </div>
  );
}

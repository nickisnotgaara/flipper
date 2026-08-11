'use client';

import { useEffect, useState } from 'react';
import { Modal, ModalContent, ModalHeader, ModalBody, Button, Spinner } from '@heroui/react';
import PhotoGallery from './PhotoGallery';
import { fetchAdPhotos, type Ad } from '@/lib/api';

type Props = {
  /** Whether the modal is open. */
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  /** The ad whose photos we want to see. We need external_id to call
   *  the API and url/raw_data for the gallery + "open in CIAN" button. */
  ad: Ad | null;
};

/**
 * Универсальная модалка "все фото объявления".
 *
 * - Тянет фото через /api/ads/{external_id}/photos (источник-агностик,
 *   работает даже если в raw_data фоток нет — fallback в sold_ads).
 * - Использует PhotoGallery для самой карусели/превью.
 * - Внизу: "↗ В ЦИАН" (если есть url) + "Закрыть" в error-состоянии.
 *
 * Создана потому что существующий PhotoCarousel живёт внутри карточки
 * и не имеет отдельной fullscreen-галереи, а PhotoGallery принимает
 * только массив фото — нужен load-aside-state контейнер.
 */
export default function AdPhotosModal({ isOpen, onOpenChange, ad }: Props) {
  const [photos, setPhotos] = useState<Array<{
    id: string;
    fullUrl: string;
    thumbnail2Url: string;
    thumbnailUrl: string;
    miniUrl: string;
  }> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // При каждом открытии — загружаем фото. Можно было бы кешировать,
  // но при текущем UX (один показ за сессию) это лишняя сложность.
  useEffect(() => {
    if (!isOpen || !ad) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPhotos(null);
    fetchAdPhotos(ad.external_id)
      .then((resp) => {
        if (cancelled) return;
        if (resp.photos && resp.photos.length > 0) {
          setPhotos(resp.photos);
        } else {
          setError('Фото не найдены');
        }
      })
      .catch((e) => {
        if (cancelled) return;
        console.error('fetchAdPhotos failed', e);
        setError('Не удалось загрузить фото');
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [isOpen, ad]);

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      backdrop="opaque"
      isDismissable
      size="5xl"
      hideCloseButton
      classNames={{
        wrapper: 'z-[1300]',
        backdrop: 'z-[1300] bg-black/55',
        base: 'm-2 sm:m-10 bg-white rounded-2xl border border-default-200 shadow-card-lg max-w-none w-[calc(100vw-1rem)] sm:w-[calc(100vw-5rem)] h-full max-h-[calc(100vh-1rem)] sm:max-h-[calc(100vh-5rem)] p-0 flex flex-col overflow-hidden',
        body: 'p-0 flex-1 min-h-0 flex flex-col overflow-hidden',
      }}
    >
      <ModalContent>
        <div className="relative flex flex-col h-full">
          <ModalHeader className="sr-only">
            {ad ? `Фото объявления ${ad.external_id}` : 'Фото объявления'}
          </ModalHeader>

          <ModalBody>
            {loading ? (
              <div className="flex-1 min-h-0 flex flex-col items-center justify-center text-default-500 gap-3">
                <Spinner size="lg" color="primary" />
                <div className="text-sm">Загружаем фото…</div>
                {ad && (
                  <div className="text-[11px] font-mono text-default-400">
                    external_id = {ad.external_id}
                  </div>
                )}
              </div>
            ) : error ? (
              <div className="flex-1 min-h-0 flex flex-col items-center justify-center text-default-500 gap-2 px-6 text-center">
                <div className="text-4xl">📷</div>
                <div className="text-sm font-medium text-default-700">{error}</div>
                {ad?.external_id && (
                  <div className="text-[11px] font-mono text-default-400">
                    external_id = {ad.external_id}
                  </div>
                )}
                <div className="text-[11px] text-default-500 max-w-[320px] mt-1 leading-relaxed">
                  Возможно объявление уже снято, и его полная страница с фотками не сохранилась.
                </div>
                <div className="flex items-center gap-2 mt-3">
                  <Button
                    size="sm"
                    variant="flat"
                    color="primary"
                    onPress={() => onOpenChange(false)}
                  >
                    Закрыть
                  </Button>
                </div>
              </div>
            ) : photos && photos.length > 0 ? (
              <div className="flex-1 min-h-0 flex flex-col">
                {/* Контент галереи без оборачивающего Modal (мы уже
                    внутри своего <Modal>). Свой action bar ниже +
                    top action row с fullscreen/close идёт через
                    relative-позиционированный div. */}
                <div className="relative flex-1 min-h-0 flex flex-col">
                  <PhotoGallery
                    isOpen={isOpen}
                    onOpenChange={onOpenChange}
                    photos={photos}
                    asContent
                  />
                  {/* Top-right close — оверлей над галереей. */}
                  <div className="absolute top-3 right-3 z-20 flex items-center gap-2">
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
                </div>

                {/* Action bar: external_id + ЦИАН. Внизу модалки, над
                    border-t чтобы визуально отделить. */}
                <div className="shrink-0 flex flex-wrap items-center justify-between gap-2 px-3 sm:px-6 py-2.5 sm:py-3 border-t border-default-200 bg-default-50/60">
                  <div className="flex items-center gap-2 text-[11px] text-default-500 font-mono min-w-0">
                    <span className="truncate">id: {ad?.external_id}</span>
                    {ad?.source && <span>· {ad.source}</span>}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {ad?.url && (
                      <Button
                        as="a"
                        href={ad.url}
                        target="_blank"
                        rel="noreferrer"
                        size="sm"
                        variant="flat"
                        className="font-medium"
                      >
                        ↗ В ЦИАН
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            ) : null}
          </ModalBody>
        </div>
      </ModalContent>
    </Modal>
  );
}

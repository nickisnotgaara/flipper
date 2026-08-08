'use client';

import dynamic from 'next/dynamic';

// Leaflet must be client-only.
const MapApp = dynamic(() => import('@/components/MapApp'), {
  ssr: false,
  loading: () => (
    <div className="h-[calc(100vh-49px)] flex items-center justify-center text-zinc-500">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
        <div className="text-sm">Загружаем карту…</div>
      </div>
    </div>
  ),
});

export default function MapPage() {
  return <MapApp />;
}

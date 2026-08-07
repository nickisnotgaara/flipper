'use client';

import dynamic from 'next/dynamic';

// Leaflet must be client-only
const MapApp = dynamic(() => import('@/components/MapApp'), {
  ssr: false,
  loading: () => (
    <div className="h-screen w-screen flex items-center justify-center text-default-500">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        <div className="text-sm text-default-500">Загружаем карту…</div>
      </div>
    </div>
  ),
});

export default function Home() {
  return <MapApp />;
}

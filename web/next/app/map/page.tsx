'use client';

import dynamic from 'next/dynamic';
import Link from 'next/link';
import { Button } from '@heroui/react';
import { ArrowLeft } from 'lucide-react';

// Leaflet must be client-only.
const MapApp = dynamic(() => import('@/components/MapApp'), {
  ssr: false,
  loading: () => (
    <div className="h-screen w-screen flex items-center justify-center text-zinc-500">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
        <div className="text-sm">Загружаем карту…</div>
      </div>
    </div>
  ),
});

export default function MapPage() {
  return (
    <div className="relative h-screen w-screen overflow-hidden">
      <MapApp />

      {/* Floating top bar — minimal, semi-transparent */}
      <div className="absolute top-0 left-0 right-0 z-[1000] pointer-events-none">
        <div className="flex items-center justify-between px-4 py-3">
          <Button
            as={Link}
            href="/dashboard"
            size="sm"
            variant="flat"
            color="default"
            radius="md"
            startContent={<ArrowLeft className="w-4 h-4" />}
            className="pointer-events-auto bg-white/90 backdrop-blur shadow-sm"
          >
            В панель
          </Button>
          <div className="text-sm font-medium px-3 py-1.5 rounded-md bg-white/90 backdrop-blur shadow-sm pointer-events-auto">
            Карта · Москва
          </div>
        </div>
      </div>
    </div>
  );
}

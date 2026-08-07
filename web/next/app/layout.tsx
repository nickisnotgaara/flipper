import './globals.css';
import 'leaflet/dist/leaflet.css';
import type { Metadata } from 'next';
import { HeroUIProvider } from '@heroui/react';

export const metadata: Metadata = {
  title: 'Flipper · Москва',
  description: 'Карта объявлений недвижимости Москвы',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" className="light">
      <body className="min-h-screen overflow-hidden text-foreground bg-background">
        <HeroUIProvider>
          {children}
        </HeroUIProvider>
      </body>
    </html>
  );
}

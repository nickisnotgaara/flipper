import './globals.css';
import 'leaflet/dist/leaflet.css';
import type { Metadata } from 'next';
import { Providers } from '@/components/admin/Providers';

export const metadata: Metadata = {
  title: 'Flipper · Admin',
  description: 'Панель управления флиппера',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" className="light">
      <body className="h-screen overflow-hidden text-[var(--ink)] bg-[var(--paper)] antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}

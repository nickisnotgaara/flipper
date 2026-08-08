import './globals.css';
import 'leaflet/dist/leaflet.css';
import type { Metadata } from 'next';
import { Providers } from '@/components/admin/Providers';
import Sidebar from '@/components/admin/Sidebar';
import TopBar from '@/components/admin/TopBar';

export const metadata: Metadata = {
  title: 'Flipper · Admin',
  description: 'Панель управления флиппера',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" className="light">
      <body className="h-screen overflow-hidden text-zinc-900 bg-zinc-50 antialiased">
        <Providers>
          <div className="flex h-screen">
            <Sidebar />
            <div className="flex-1 flex flex-col min-w-0">
              <TopBar />
              <main className="flex-1 overflow-y-auto">
                <div className="max-w-7xl mx-auto px-6 py-6 lg:px-8 lg:py-8">
                  {children}
                </div>
              </main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}

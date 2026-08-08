'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HeroUIProvider } from '@heroui/react';
import { useState, type ReactNode } from 'react';

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            retry: (failureCount, error) => {
              const status = (error as Error & { status?: number })?.status;
              if (status && status < 500) return false;
              return failureCount < 2;
            },
          },
        },
      }),
  );
  return (
    <HeroUIProvider>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </HeroUIProvider>
  );
}

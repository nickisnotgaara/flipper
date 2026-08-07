'use client';

import { useEffect, useState } from 'react';

/**
 * useDebounce — defers `value` updates until the user has stopped
 * changing it for `delay` ms. Useful for search inputs that should
 * only fire a request once the user has finished typing, not on
 * every keystroke.
 *
 * Returns the latest "settled" value, lagging behind the input
 * during bursts of activity. Race-safe: if `value` changes again
 * before `delay` elapses, the previous in-flight timer is cleared.
 */
export function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState<T>(value);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);

  return debounced;
}

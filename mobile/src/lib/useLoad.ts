import { useCallback, useEffect, useRef, useState } from 'react';
import { ShopifyError } from './shopify';

type Settled<T> = { key: string; run: number; data: T | undefined; error: string | null };

/**
 * Loads for `key` (e.g. a product handle) and again on reload(). A request
 * superseded by a newer one, or by leaving the screen, is aborted and never
 * lands. A reload keeps the last data on screen while it runs; a new key
 * does not show the previous key's data.
 */
export function useLoad<T>(load: (signal: AbortSignal) => Promise<T>, key: string) {
  const [run, setRun] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const loader = useRef(load);
  useEffect(() => {
    loader.current = load;
  });

  useEffect(() => {
    const c = new AbortController();
    loader.current(c.signal).then(
      (data) => {
        if (!c.signal.aborted) setSettled({ key, run, data, error: null });
      },
      (e: unknown) => {
        if (c.signal.aborted) return;
        const error = e instanceof ShopifyError ? e.message : 'Something went wrong. Try again.';
        setSettled((prev) => ({ key, run, data: prev?.key === key ? prev.data : undefined, error }));
      },
    );
    return () => c.abort();
  }, [key, run]);

  const reload = useCallback(() => setRun((n) => n + 1), []);
  const same = settled?.key === key;
  return {
    data: same ? settled.data : undefined,
    error: same && settled.run === run ? settled.error : null,
    loading: !same || settled.run !== run,
    reload,
  };
}

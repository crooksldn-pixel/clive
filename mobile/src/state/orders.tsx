/**
 * Orders placed in this app, remembered on the device so the Orders tab has
 * something to show without an account. Full history across the website and
 * the app is in the shopper's Shopify account, which the tab links to.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { KEYS, readJSON, writeJSON } from '@/lib/storage';

export type PlacedOrder = {
  /** Numeric Shopify order id; null when completion was inferred, not reported. */
  id: string | null;
  placedAt: string;
  total: string | null;
  items: number | null;
  /** This order is registered for shipping notifications. */
  notify: boolean;
};

type OrdersContext = {
  orders: PlacedOrder[];
  record: (o: PlacedOrder) => Promise<void>;
  markNotify: (id: string) => Promise<void>;
};

const Ctx = createContext<OrdersContext | null>(null);
const KEEP = 50;

export function OrdersProvider({ children }: { children: ReactNode }) {
  const [orders, setOrders] = useState<PlacedOrder[]>([]);

  useEffect(() => {
    readJSON<PlacedOrder[]>(KEYS.orders, []).then((o) => setOrders(Array.isArray(o) ? o : []));
  }, []);

  const save = useCallback(async (next: PlacedOrder[]) => {
    setOrders(next);
    await writeJSON(KEYS.orders, next);
  }, []);

  const record = useCallback(
    async (o: PlacedOrder) => {
      const current = await readJSON<PlacedOrder[]>(KEYS.orders, []);
      if (o.id && current.some((x) => x.id === o.id)) return;
      await save([o, ...current].slice(0, KEEP));
    },
    [save],
  );

  const markNotify = useCallback(
    async (id: string) => {
      const current = await readJSON<PlacedOrder[]>(KEYS.orders, []);
      await save(current.map((x) => (x.id === id ? { ...x, notify: true } : x)));
    },
    [save],
  );

  const value = useMemo(() => ({ orders, record, markNotify }), [orders, record, markNotify]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useOrders(): OrdersContext {
  const v = useContext(Ctx);
  if (!v) throw new Error('useOrders outside OrdersProvider');
  return v;
}

/**
 * The bag. The cart lives at Shopify — this only remembers its id on the
 * device, so a bag survives the app being closed, and keeps one copy of it
 * in memory for the screens.
 *
 * Changes run one at a time, in order. Two quick taps on "+" must add two,
 * not race each other and leave the count at one.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AppState } from 'react-native';
import { addLine, createCart, fetchCart, removeLine, setLineQuantity } from '@/lib/cart-api';
import { ShopifyError } from '@/lib/shopify';
import { KEYS, readJSON, writeJSON } from '@/lib/storage';
import type { Cart } from '@/lib/types';

type CartContext = {
  cart: Cart | null;
  /** The saved bag has been read back from Shopify (or there was none). */
  ready: boolean;
  /** Line ids with a change in flight; "add" while adding. */
  pending: ReadonlySet<string>;
  add: (variantId: string, quantity?: number) => Promise<void>;
  setQuantity: (lineId: string, quantity: number) => Promise<void>;
  remove: (lineId: string) => Promise<void>;
  /** Re-reads from Shopify. Resolves null if the cart has gone (checked out or expired). */
  refresh: () => Promise<Cart | null>;
  /** Forgets the cart — after an order, or when Shopify has discarded it. */
  clear: () => Promise<void>;
};

const Ctx = createContext<CartContext | null>(null);

export function messageOf(e: unknown): string {
  if (e instanceof ShopifyError) return e.message;
  return 'Something went wrong. Try again.';
}

export function CartProvider({ children }: { children: ReactNode }) {
  const [cart, setCart] = useState<Cart | null>(null);
  const [ready, setReady] = useState(false);
  const [pending, setPending] = useState<ReadonlySet<string>>(new Set());
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const idRef = useRef<string | null>(null);

  const keep = useCallback(async (next: Cart | null) => {
    idRef.current = next?.id ?? null;
    setCart(next);
    await writeJSON(KEYS.cartId, next?.id ?? null);
  }, []);

  /** Serialises every change behind the one before it; errors still reach the caller. */
  const run = useCallback(<T,>(key: string, job: () => Promise<T>): Promise<T> => {
    const next = queue.current.catch(() => undefined).then(async () => {
      setPending((p) => new Set(p).add(key));
      try {
        return await job();
      } finally {
        setPending((p) => {
          const n = new Set(p);
          n.delete(key);
          return n;
        });
      }
    });
    queue.current = next;
    return next;
  }, []);

  const refresh = useCallback(
    () =>
      run('refresh', async () => {
        const id = idRef.current;
        if (!id) return null;
        const fresh = await fetchCart(id);
        await keep(fresh);
        return fresh;
      }),
    [run, keep],
  );

  useEffect(() => {
    let live = true;
    (async () => {
      const id = await readJSON<string | null>(KEYS.cartId, null);
      if (id) {
        try {
          const saved = await fetchCart(id);
          if (live) await keep(saved);
        } catch {
          /* offline at launch: keep the id, try again when the bag is opened */
          idRef.current = id;
        }
      }
      if (live) setReady(true);
    })();
    return () => {
      live = false;
    };
  }, [keep]);

  /* Coming back to the app (e.g. from a browser checkout) re-reads the bag. */
  useEffect(() => {
    const sub = AppState.addEventListener('change', (s) => {
      if (s === 'active' && idRef.current) refresh().catch(() => undefined);
    });
    return () => sub.remove();
  }, [refresh]);

  const add = useCallback(
    (variantId: string, quantity = 1) =>
      run('add', async () => {
        const id = idRef.current;
        if (!id) return void (await keep(await createCart(variantId, quantity)));
        try {
          await keep(await addLine(id, variantId, quantity));
        } catch (e) {
          /* The saved cart may have expired or been checked out elsewhere. */
          if (e instanceof ShopifyError && e.code !== 'NETWORK' && !(await fetchCart(id))) {
            await keep(await createCart(variantId, quantity));
          } else throw e;
        }
      }),
    [run, keep],
  );

  const setQuantity = useCallback(
    (lineId: string, quantity: number) =>
      run(lineId, async () => {
        const id = idRef.current;
        if (!id) return;
        await keep(quantity <= 0 ? await removeLine(id, lineId) : await setLineQuantity(id, lineId, quantity));
      }),
    [run, keep],
  );

  const remove = useCallback(
    (lineId: string) =>
      run(lineId, async () => {
        const id = idRef.current;
        if (id) await keep(await removeLine(id, lineId));
      }),
    [run, keep],
  );

  const clear = useCallback(() => run('clear', () => keep(null)), [run, keep]);

  const value = useMemo(
    () => ({ cart, ready, pending, add, setQuantity, remove, refresh, clear }),
    [cart, ready, pending, add, setQuantity, remove, refresh, clear],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCart(): CartContext {
  const v = useContext(Ctx);
  if (!v) throw new Error('useCart outside CartProvider');
  return v;
}

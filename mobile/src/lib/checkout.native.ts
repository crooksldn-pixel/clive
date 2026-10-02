/**
 * Checkout inside the app with Shopify Checkout Kit: Shopify's real checkout
 * — Shop Pay, Apple Pay, discount codes, the store's checkout branding —
 * presented as a sheet over the bag, so the shopper never leaves the app.
 *
 * Checkout Kit is native code. Expo Go does not contain it and importing it
 * there throws, so it is loaded lazily and the browser fallback takes over.
 */
import type { CheckoutCompletedEvent, CheckoutException, ShopifyCheckoutSheet } from '@shopify/checkout-sheet-kit';
import { colour } from '@/theme/tokens';
import { openInBrowser } from './checkout-browser';
import { formatMoney } from './money';
import type { CheckoutResult } from './checkout-types';

let kit: ShopifyCheckoutSheet | null | undefined;
let Codes: typeof import('@shopify/checkout-sheet-kit').CheckoutErrorCode | undefined;

function sheet(): ShopifyCheckoutSheet | null {
  if (kit !== undefined) return kit;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const mod = require('@shopify/checkout-sheet-kit') as typeof import('@shopify/checkout-sheet-kit');
    Codes = mod.CheckoutErrorCode;
    kit = new mod.ShopifyCheckoutSheet({
      /* The checkout keeps the branding set in Shopify admin, as on the website. */
      colorScheme: mod.ColorScheme.web,
      preloading: true,
      title: 'Checkout',
      colors: {
        ios: { tintColor: colour.purple, closeButtonColor: colour.text },
        android: {
          progressIndicator: colour.purple,
          backgroundColor: colour.ground,
          headerBackgroundColor: colour.ground,
          headerTextColor: colour.text,
          closeButtonColor: colour.text,
        },
      },
    });
  } catch {
    kit = null;
  }
  return kit;
}

export const checkoutKind: 'sheet' | 'browser' = sheet() ? 'sheet' : 'browser';

/** Warms the checkout while the shopper is still looking at the bag. */
export function preloadCheckout(url: string): void {
  try {
    sheet()?.preload(url);
  } catch {
    /* preloading is an optimisation; failing it changes nothing */
  }
}

/**
 * `onCompleted` fires the moment Shopify confirms the order — while the
 * thank-you page is still showing — so the order can be registered for
 * shipping updates before the shopper even closes the sheet.
 */
export function openCheckout(url: string, onCompleted?: (orderGid: string | null) => void): Promise<CheckoutResult> {
  const k = sheet();
  if (!k) return openInBrowser(url);

  return new Promise<CheckoutResult>((resolve) => {
    let completed: CheckoutResult | null = null;
    let settled = false;
    const subs = [
      /* 'completed' arrives while the sheet still shows the thank-you page;
         the result is reported when the shopper closes it. */
      k.addEventListener('completed', (e: CheckoutCompletedEvent) => {
        const d = e.orderDetails;
        completed = {
          status: 'completed',
          orderId: d?.id ?? null,
          total:
            d?.cart?.price?.total?.amount != null && d.cart.price.total.currencyCode
              ? formatMoney({ amount: String(d.cart.price.total.amount), currencyCode: d.cart.price.total.currencyCode })
              : null,
          items: d?.cart?.lines?.reduce((n: number, l) => n + (l.quantity ?? 0), 0) ?? null,
        };
        try {
          onCompleted?.(d?.id ?? null);
        } catch {
          /* the order stands whatever a listener does */
        }
      }),
      k.addEventListener('close', () => finish(completed ?? { status: 'closed' })),
      k.addEventListener('error', (err: CheckoutException) => {
        if (err.recoverable) return; /* Checkout Kit recovers these itself */
        if (Codes && err.code === Codes.cartCompleted) {
          finish(completed ?? { status: 'completed', orderId: null, total: null, items: null });
          return;
        }
        const gone = Boolean(Codes && (err.code === Codes.cartExpired || err.code === Codes.invalidCart));
        finish({
          status: 'failed',
          cartGone: gone,
          message: gone
            ? 'That bag expired at Shopify. It has been cleared — add the pieces again.'
            : 'Checkout could not load. Check your connection and try again.',
        });
      }),
    ];

    function finish(r: CheckoutResult) {
      if (settled) return;
      settled = true;
      for (const s of subs) s?.remove();
      if (r.status === 'failed') {
        try { k!.dismiss(); } catch { /* already gone */ }
      }
      resolve(r);
    }

    try {
      k.present(url);
    } catch {
      finish({ status: 'failed', message: 'Checkout would not open. Try again.', cartGone: false });
    }
  });
}

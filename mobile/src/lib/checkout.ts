/** Web build: checkout opens in the browser. Phones use checkout.native.ts. */
import { openInBrowser } from './checkout-browser';
import type { CheckoutResult } from './checkout-types';

export const checkoutKind: 'sheet' | 'browser' = 'browser';

export function preloadCheckout(_url: string): void {}

export function openCheckout(url: string, _onCompleted?: (orderGid: string | null) => void): Promise<CheckoutResult> {
  return openInBrowser(url);
}

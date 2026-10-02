/**
 * Shopify's own checkout page in the system browser — used on web, and on
 * a phone wherever the native sheet is missing (Expo Go). Completion cannot
 * be observed from here, so the bag re-reads the cart when the app returns
 * to the foreground: a cart that vanished just after checkout opened was
 * paid for.
 */
import * as WebBrowser from 'expo-web-browser';
import { colour } from '@/theme/tokens';
import type { CheckoutResult } from './checkout-types';

export async function openInBrowser(url: string): Promise<CheckoutResult> {
  try {
    await WebBrowser.openBrowserAsync(url, {
      controlsColor: colour.accent,
      toolbarColor: colour.ground,
      presentationStyle: WebBrowser.WebBrowserPresentationStyle.FULL_SCREEN,
    });
    return { status: 'closed' };
  } catch {
    return { status: 'failed', message: 'Checkout would not open. Try again.', cartGone: false };
  }
}

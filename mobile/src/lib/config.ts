/**
 * Store configuration.
 *
 * None of this is secret. The Storefront API is the public, customer-facing
 * API — the same data the website shows — and a Storefront token is designed
 * to ship inside apps. EXPO_PUBLIC_ variables are inlined at build time.
 *
 * WITHOUT A TOKEN the app still browses, carts and checks out: Shopify allows
 * tokenless access to products, collections and carts. What it refuses
 * without one is metafields (size charts, subtitles) and stock counts. Set
 * EXPO_PUBLIC_SHOPIFY_STOREFRONT_TOKEN — from the Headless sales channel —
 * and those switch on with no other change.
 */
export const SHOP_DOMAIN =
  process.env.EXPO_PUBLIC_SHOPIFY_DOMAIN ?? 'crooksldn.com';

export const STOREFRONT_API_VERSION =
  process.env.EXPO_PUBLIC_SHOPIFY_API_VERSION ?? '2026-07';

export const STOREFRONT_TOKEN: string | undefined =
  process.env.EXPO_PUBLIC_SHOPIFY_STOREFRONT_TOKEN || undefined;

/** Prices and availability are resolved for this market. */
export const COUNTRY = process.env.EXPO_PUBLIC_SHOPIFY_COUNTRY ?? 'GB';

const SITE = `https://${SHOP_DOMAIN}`;

/**
 * Order lookup — the same AfterShip page the website's tracking page links
 * to (order number + email), so tracking works with or without an account.
 */
export const ORDER_LOOKUP_URL =
  process.env.EXPO_PUBLIC_ORDER_LOOKUP_URL ?? 'https://5wn03tnm.aftership.com';

/** The shopper's Shopify account: every order, from the website or the app. */
export const ACCOUNT_URL = `${SITE}/account`;

export const HELP_PAGES = [
  { label: 'Contact', url: `${SITE}/pages/contact` },
  { label: 'FAQ', url: `${SITE}/pages/faq` },
  { label: 'Terms', url: `${SITE}/pages/terms` },
] as const;

/** Where the push service lives once deployed (see backend/README.md). */
export const PUSH_API_URL: string | undefined =
  process.env.EXPO_PUBLIC_PUSH_API_URL || undefined;

export const hasToken = (): boolean => Boolean(STOREFRONT_TOKEN);

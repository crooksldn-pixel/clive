import { COUNTRY, SHOP_DOMAIN, STOREFRONT_API_VERSION, STOREFRONT_TOKEN } from './config';

/** A failure Shopify explained. The message is Shopify's own and is safe to show. */
export class ShopifyError extends Error {
  constructor(message: string, readonly code?: string) {
    super(message);
    this.name = 'ShopifyError';
  }
}

const ENDPOINT = `https://${SHOP_DOMAIN}/api/${STOREFRONT_API_VERSION}/graphql.json`;

/**
 * One Storefront API request.
 *
 * Every query is wrapped in @inContext(country:) so prices come back in the
 * market's own currency from Shopify, rather than being converted here.
 *
 * `withMeta` gates the fields tokenless access refuses (metafields). It is
 * sent only to documents that declare it, and without a token those fields
 * are not requested at all — so the request succeeds instead of failing.
 */
export async function storefront<T>(
  query: string,
  variables: Record<string, unknown> = {},
  signal?: AbortSignal,
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  };
  if (STOREFRONT_TOKEN) headers['X-Shopify-Storefront-Access-Token'] = STOREFRONT_TOKEN;

  let res: Response;
  try {
    res = await fetch(ENDPOINT, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        query,
        variables: {
          country: COUNTRY,
          ...(query.includes('$withMeta') ? { withMeta: Boolean(STOREFRONT_TOKEN) } : {}),
          ...variables,
        },
      }),
      signal,
    });
  } catch (e) {
    if ((e as Error)?.name === 'AbortError') throw e;
    throw new ShopifyError('No connection. Check your signal and try again.', 'NETWORK');
  }

  if (res.status === 429) throw new ShopifyError('The shop is busy. Try again in a moment.', 'THROTTLED');
  if (!res.ok) throw new ShopifyError(`The shop did not answer (${res.status}).`, 'HTTP');

  const json = (await res.json()) as { data?: T; errors?: { message: string; extensions?: { code?: string } }[] };
  if (json.errors?.length) {
    const first = json.errors[0];
    throw new ShopifyError(first.message, first.extensions?.code);
  }
  if (!json.data) throw new ShopifyError('The shop sent back nothing.', 'EMPTY');
  return json.data;
}

/** Throws Shopify's own explanation when a cart mutation is refused. */
export function assertNoUserErrors(errors: { message: string }[] | undefined): void {
  if (errors && errors.length) throw new ShopifyError(errors[0].message, 'USER_ERROR');
}

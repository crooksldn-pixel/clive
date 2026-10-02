/**
 * Cart operations against the Storefront API. Pure — no React, no storage —
 * so the same functions run in the app and in scripts/verify-api.ts.
 */
import { CART_ADD, CART_CREATE, CART_GET, CART_REMOVE, CART_UPDATE } from './queries';
import { assertNoUserErrors, storefront } from './shopify';
import type { Cart, CartLine } from './types';

type RawCart = Omit<Cart, 'lines' | 'notice'> & { lines: { nodes: CartLine[] } };
type Payload = {
  cart: RawCart | null;
  userErrors: { message: string }[];
  /** Shopify adjusted the request rather than refusing it — e.g. capped a quantity at what is in stock. */
  warnings?: { code: string; message: string }[];
};

function toCart(raw: RawCart): Cart {
  return { ...raw, lines: raw.lines.nodes, notice: null };
}

function unwrap(p: Payload): Cart {
  assertNoUserErrors(p.userErrors);
  if (!p.cart) throw new Error('The shop did not return a cart.');
  return { ...toCart(p.cart), notice: p.warnings?.[0]?.message ?? null };
}

/** null when the cart has expired or been checked out — the caller starts a new one. */
export async function fetchCart(id: string): Promise<Cart | null> {
  const d = await storefront<{ cart: RawCart | null }>(CART_GET, { id });
  return d.cart ? toCart(d.cart) : null;
}

export async function createCart(variantId: string, quantity = 1): Promise<Cart> {
  const d = await storefront<{ cartCreate: Payload }>(CART_CREATE, {
    lines: [{ merchandiseId: variantId, quantity }],
  });
  return unwrap(d.cartCreate);
}

export async function addLine(cartId: string, variantId: string, quantity = 1): Promise<Cart> {
  const d = await storefront<{ cartLinesAdd: Payload }>(CART_ADD, {
    id: cartId, lines: [{ merchandiseId: variantId, quantity }],
  });
  return unwrap(d.cartLinesAdd);
}

export async function setLineQuantity(cartId: string, lineId: string, quantity: number): Promise<Cart> {
  const d = await storefront<{ cartLinesUpdate: Payload }>(CART_UPDATE, {
    id: cartId, lines: [{ id: lineId, quantity }],
  });
  return unwrap(d.cartLinesUpdate);
}

export async function removeLine(cartId: string, lineId: string): Promise<Cart> {
  const d = await storefront<{ cartLinesRemove: Payload }>(CART_REMOVE, { id: cartId, lineIds: [lineId] });
  return unwrap(d.cartLinesRemove);
}

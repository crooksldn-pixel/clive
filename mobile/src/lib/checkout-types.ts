export type CheckoutResult =
  /** orderId is null when the order was inferred (the cart disappeared) rather than reported. */
  | { status: 'completed'; orderId: string | null; total: string | null; items: number | null }
  | { status: 'closed' }
  /** cartGone: Shopify says this cart can no longer be checked out — start a fresh one. */
  | { status: 'failed'; message: string; cartGone: boolean };

/** Shopify's order GIDs end in the numeric order id the webhooks carry. */
export function orderNumberFromGid(id: string | undefined | null): string | null {
  const m = id ? /(\d+)(?:\?.*)?$/.exec(id) : null;
  return m ? m[1] : null;
}

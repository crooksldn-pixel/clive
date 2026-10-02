import type { Money } from './types';

/**
 * Formats an amount the Storefront API already priced in the market's
 * currency. Nothing is converted here — @inContext did that at Shopify.
 * Whole amounts drop the pence ("£60", not "£60.00"), as the website does.
 */
export function formatMoney(m: Money | null | undefined): string {
  if (!m) return '';
  const n = Number(m.amount);
  if (!Number.isFinite(n)) return '';
  const whole = Number.isInteger(n);
  try {
    return new Intl.NumberFormat('en-GB', {
      style: 'currency',
      currency: m.currencyCode,
      minimumFractionDigits: whole ? 0 : 2,
      maximumFractionDigits: 2,
    }).format(n);
  } catch {
    return `${m.currencyCode} ${n.toFixed(whole ? 0 : 2)}`;
  }
}

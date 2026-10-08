import { DISCOUNT_ORDERS, DISCOUNT_USAGE } from "./queries.ts";
import { listAll } from "./records.ts";
import type { Shopify } from "./shopify.ts";
import type { Deps } from "./types.ts";

export interface UsageSummary {
  codes: number;
  updated: number;
  notInShopify: string[];
  errors: string[];
}

/** Refreshes each affiliate code's use count and attributed revenue from Shopify. Read-only on Shopify. */
export async function syncUsage(deps: Deps, shopify: Shopify): Promise<UsageSummary> {
  const db = deps.base44.asServiceRole.entities;
  const codes = await listAll(db.AffiliateCode);
  const summary: UsageSummary = { codes: codes.length, updated: 0, notInShopify: [], errors: [] };

  for (const c of codes) {
    if (!c.code || !/^[A-Za-z0-9_-]+$/.test(c.code)) continue;
    try {
      const node = await shopify.graphql<{ codeDiscountNodeByCode: { codeDiscount: { asyncUsageCount?: number } } | null }>(
        DISCOUNT_USAGE,
        { code: c.code },
      );
      if (!node.codeDiscountNodeByCode) {
        summary.notInShopify.push(c.code);
        continue;
      }
      const usageCount = node.codeDiscountNodeByCode.codeDiscount?.asyncUsageCount ?? 0;

      let revenue = 0;
      let cursor: string | null = null;
      for (let page = 0; page < 20; page++) {
        const res: {
          orders: {
            pageInfo: { hasNextPage: boolean; endCursor: string | null };
            nodes: { cancelledAt: string | null; test: boolean; currentSubtotalPriceSet: { shopMoney: { amount: string } } }[];
          };
        } = await shopify.graphql(DISCOUNT_ORDERS, { query: `discount_code:${c.code}`, cursor });
        for (const o of res.orders.nodes) {
          if (!o.cancelledAt && !o.test) revenue += Number(o.currentSubtotalPriceSet.shopMoney.amount) || 0;
        }
        if (!res.orders.pageInfo.hasNextPage) break;
        cursor = res.orders.pageInfo.endCursor;
      }
      const revenueGbp = Math.round(revenue * 100) / 100;
      if (c.usageCount !== usageCount || c.revenueGbp !== revenueGbp) {
        await db.AffiliateCode.update(c.id, { usageCount, revenueGbp });
        summary.updated++;
      }
    } catch (e) {
      summary.errors.push(`${c.code}: ${(e as Error).message}`);
    }
  }
  return summary;
}

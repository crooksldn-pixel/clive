import { json, readJson, requireAdminOrKey, wrap } from "../lib/http.ts";
import { syncPromotions as run } from "../lib/promotions.ts";
import { createShopify } from "../lib/shopify.ts";

/**
 * syncPromotions: pauses/unpauses creator codes to match each influencer's
 * status and writes the gift rules the bag script reads. Admin or
 * PARTNER_API_KEY. Returns { codes, updatedAt, ... }.
 */
export const syncPromotions = wrap(async (req, deps) => {
  const body = await readJson(req);
  await requireAdminOrKey(req, body, deps);
  return json(await run(deps, createShopify(deps)));
});

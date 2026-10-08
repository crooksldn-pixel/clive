import { json, readJson, requireAdminOrKey, wrap } from "../lib/http.ts";
import { createShopify } from "../lib/shopify.ts";
import { syncUsage } from "../lib/usage.ts";

/** shopifySyncUsage: affiliate code use counts and revenue. */
export const shopifySyncUsage = wrap(async (req, deps) => {
  const body = await readJson(req);
  await requireAdminOrKey(req, body, deps);
  return json({ ok: true, ...(await syncUsage(deps, createShopify(deps))) });
});

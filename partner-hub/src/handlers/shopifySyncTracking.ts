import { json, readJson, requireAdminOrKey, wrap } from "../lib/http.ts";
import { createShopify } from "../lib/shopify.ts";
import { syncTracking } from "../lib/tracking.ts";

/** shopifySyncTracking: pulls fulfilment, tracking and cancellations for every open send. */
export const shopifySyncTracking = wrap(async (req, deps) => {
  const body = await readJson(req);
  await requireAdminOrKey(req, body, deps);
  return json({ ok: true, ...(await syncTracking(deps, createShopify(deps))) });
});

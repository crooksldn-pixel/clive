import { markShipped, parseMarkShipped } from "../lib/fulfil.ts";
import { json, readJson, requireAdmin, wrap } from "../lib/http.ts";
import { createShopify } from "../lib/shopify.ts";

/** sendMarkShipped: { sendId, trackingNumber, carrier, trackingUrl?, notifyCustomer? } */
export const sendMarkShipped = wrap(async (req, deps) => {
  const body = await readJson(req);
  await requireAdmin(deps);
  return json(await markShipped(deps, createShopify(deps), parseMarkShipped(body)));
});

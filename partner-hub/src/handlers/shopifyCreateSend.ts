import { HttpError, json, readJson, requireAdmin, wrap } from "../lib/http.ts";
import { asString } from "../lib/records.ts";
import { createSend, parseItems } from "../lib/sends.ts";
import { createShopify } from "../lib/shopify.ts";

/**
 * shopifyCreateSend: called by the admin CREATE SEND dialog with
 * { influencerId, items: [{ variantId, name, size, quantity? }], note?, dryRun? }.
 * Returns { orderName, ... }; the dialog shows `orderName`.
 */
export const shopifyCreateSend = wrap(async (req, deps) => {
  const body = await readJson(req);
  const admin = await requireAdmin(deps);
  const influencerId = asString(body.influencerId);
  if (!influencerId) throw new HttpError(400, "Missing influencerId.", "bad_request");
  const result = await createSend(deps, createShopify(deps), {
    influencerId,
    items: parseItems(body.items),
    note: asString(body.note).slice(0, 500) || undefined,
    dryRun: body.dryRun === true,
    createdBy: admin.email,
  });
  return json(result);
});

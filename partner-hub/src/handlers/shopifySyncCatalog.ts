import { syncCatalog } from "../lib/catalog.ts";
import { json, readJson, requireAdminOrKey, wrap } from "../lib/http.ts";
import { createShopify } from "../lib/shopify.ts";

/** shopifySyncCatalog: refreshes products, sizes, prices and stock from Shopify. */
export const shopifySyncCatalog = wrap(async (req, deps) => {
  const body = await readJson(req);
  await requireAdminOrKey(req, body, deps);
  return json({ ok: true, ...(await syncCatalog(deps, createShopify(deps))) });
});

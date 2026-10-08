import { json, readJson, requireAdmin, wrap } from "../lib/http.ts";
import { asString } from "../lib/records.ts";
import { checkConnection } from "../lib/setup.ts";
import { createShopify } from "../lib/shopify.ts";

/** shopifyCheckConnection: { registerWebhooks?: boolean, webhookUrl?: string } */
export const shopifyCheckConnection = wrap(async (req, deps) => {
  const body = await readJson(req);
  await requireAdmin(deps);
  return json(
    await checkConnection(deps, createShopify(deps), {
      registerWebhooks: body.registerWebhooks === true,
      webhookUrl: asString(body.webhookUrl) || undefined,
    }),
  );
});

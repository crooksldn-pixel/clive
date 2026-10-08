import { HttpError, json, wrap } from "../lib/http.ts";
import { verifyShopifyHmac } from "../lib/setup.ts";
import { createShopify, orderGid } from "../lib/shopify.ts";
import { syncTracking } from "../lib/tracking.ts";

/**
 * shopifyWebhook: Shopify calls this when an order is fulfilled, its tracking
 * changes, or it is cancelled. Signed with the app's client secret.
 */
export const shopifyWebhook = wrap(async (req, deps) => {
  if (req.method !== "POST") throw new HttpError(405, "POST only.", "method_not_allowed");
  const raw = await req.arrayBuffer();
  const secret = deps.secret("SHOPIFY_WEBHOOK_SECRET") || deps.secret("SHOPIFY_CLIENT_SECRET") || "";
  if (!(await verifyShopifyHmac(raw, req.headers.get("x-shopify-hmac-sha256"), secret))) {
    throw new HttpError(401, "Bad or missing Shopify signature.", "bad_signature");
  }
  const shopify = createShopify(deps);
  const shopDomain = (req.headers.get("x-shopify-shop-domain") ?? "").toLowerCase();
  if (shopDomain && shopDomain !== shopify.config.domain) {
    return json({ ok: true, ignored: "other shop" });
  }
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(new TextDecoder().decode(raw));
  } catch {
    throw new HttpError(400, "Webhook body isn't JSON.", "bad_json");
  }
  const topic = req.headers.get("x-shopify-topic") ?? "";
  const orderId = topic.startsWith("orders/")
    ? orderGid(payload.admin_graphql_api_id) ?? orderGid(payload.id)
    : orderGid(payload.order_id);
  if (!orderId) return json({ ok: true, ignored: "no order id" });

  const sends = await deps.base44.asServiceRole.entities.Send.filter({ shopifyOrderId: orderId });
  if (!sends.length) return json({ ok: true, ignored: "not a seeding order" });
  const summary = await syncTracking(deps, shopify, { sendIds: sends.map((s) => s.id) });
  return json({ ok: true, topic, orderId, updated: summary.updated, changes: summary.changes });
});

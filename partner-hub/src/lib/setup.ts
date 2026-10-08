import { timingSafeEqual } from "./http.ts";
import { SHOP_CHECK, WEBHOOK_CREATE, WEBHOOKS } from "./queries.ts";
import type { Shopify } from "./shopify.ts";
import type { Deps } from "./types.ts";

/** Scopes the Shopify app needs. A write scope includes its read scope. */
export const REQUIRED_SCOPES = [
  { scope: "read_products", why: "catalogue sync and stock checks" },
  { scope: "read_inventory", why: "stock checks" },
  { scope: "write_orders", why: "creating the gifted orders" },
  { scope: "write_merchant_managed_fulfillment_orders", why: "MARK SHIPPED with a tracking number" },
  { scope: "read_discounts", why: "affiliate code usage" },
];

export const WEBHOOK_TOPICS = ["FULFILLMENTS_CREATE", "FULFILLMENTS_UPDATE", "ORDERS_CANCELLED"];

export function missingScopes(granted: string[]): typeof REQUIRED_SCOPES {
  const set = new Set(granted);
  return REQUIRED_SCOPES.filter(
    ({ scope }) => !set.has(scope) && !(scope.startsWith("read_") && set.has(scope.replace(/^read_/, "write_"))),
  );
}

export function functionUrl(deps: Deps, name: string): string | null {
  const base = (deps.secret("HUB_PUBLIC_URL") || "https://crooks-partner-hub.base44.app").replace(/\/+$/, "");
  return deps.appId ? `${base}/api/apps/${deps.appId}/functions/${name}` : null;
}

export async function checkConnection(deps: Deps, shopify: Shopify, opts: { registerWebhooks?: boolean; webhookUrl?: string }) {
  const started = Date.now();
  const data = await shopify.graphql<{
    shop: { name: string; myshopifyDomain: string; currencyCode: string };
    currentAppInstallation: { accessScopes: { handle: string }[] };
    locations: { nodes: { id: string; name: string; isActive: boolean; fulfillsOnlineOrders: boolean }[] };
  }>(SHOP_CHECK);
  const granted = data.currentAppInstallation.accessScopes.map((s) => s.handle);
  const missing = missingScopes(granted);
  const warnings: string[] = [];
  if (data.shop.currencyCode !== (deps.secret("SHOP_CURRENCY") || "GBP")) {
    warnings.push(`The shop's currency is ${data.shop.currencyCode}; set the SHOP_CURRENCY secret to match.`);
  }
  if (!data.locations.nodes.some((l) => l.isActive && l.fulfillsOnlineOrders)) {
    warnings.push("No active location fulfils online orders, so Shopify can't allocate stock to new orders.");
  }

  const webhookUrl = opts.webhookUrl || functionUrl(deps, "shopifyWebhook");
  const webhooks: { topic: string; status: "ok" | "created" | "missing" | "error"; detail?: string }[] = [];
  let existing: { id: string; topic: string; uri: string }[] = [];
  try {
    existing = (await shopify.graphql<{ webhookSubscriptions: { nodes: { id: string; topic: string; uri: string }[] } }>(
      WEBHOOKS,
    )).webhookSubscriptions.nodes;
  } catch (e) {
    warnings.push(`Couldn't list webhooks: ${(e as Error).message}`);
  }
  for (const topic of WEBHOOK_TOPICS) {
    if (existing.some((w) => w.topic === topic && w.uri === webhookUrl)) {
      webhooks.push({ topic, status: "ok" });
      continue;
    }
    if (!opts.registerWebhooks || !webhookUrl) {
      webhooks.push({ topic, status: "missing" });
      continue;
    }
    try {
      const res = await shopify.graphql<{
        webhookSubscriptionCreate: { webhookSubscription: { id: string } | null; userErrors: { message: string }[] };
      }>(WEBHOOK_CREATE, { topic, sub: { uri: webhookUrl, format: "JSON" } }, { idempotent: false });
      const errs = res.webhookSubscriptionCreate.userErrors;
      webhooks.push(errs.length ? { topic, status: "error", detail: errs.map((e) => e.message).join("; ") } : { topic, status: "created" });
    } catch (e) {
      webhooks.push({ topic, status: "error", detail: (e as Error).message });
    }
  }

  return {
    ok: missing.length === 0,
    shop: data.shop,
    auth: shopify.config.staticToken ? "admin access token" : "client credentials (auto-refreshing)",
    apiVersion: shopify.config.apiVersion,
    scopes: { granted, missing },
    locations: data.locations.nodes,
    webhookUrl,
    webhooks,
    partnerApi: (deps.secret("PARTNER_API_KEY") ?? "").length >= 24 ? "enabled" : "disabled (set PARTNER_API_KEY, 24+ characters)",
    partnerApiWrites: deps.secret("PARTNER_API_ALLOW_WRITES") === "true" ? "enabled" : "disabled",
    warnings,
    tookMs: Date.now() - started,
  };
}

function b64(bytes: ArrayBuffer): string {
  let s = "";
  for (const b of new Uint8Array(bytes)) s += String.fromCharCode(b);
  return btoa(s);
}

/** Checks Shopify's X-Shopify-Hmac-Sha256 header against the raw body. */
export async function verifyShopifyHmac(raw: ArrayBuffer, header: string | null, secret: string): Promise<boolean> {
  if (!header || !secret) return false;
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, raw);
  return timingSafeEqual(b64(sig), header.trim());
}

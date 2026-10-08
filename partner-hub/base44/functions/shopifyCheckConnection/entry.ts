// CROOKS Partner Hub — Base44 function "shopifyCheckConnection".
// GENERATED from partner-hub/src by `npm run build`. Edit the source, not this file.


// src/lib/http.ts
var HttpError = class extends Error {
  constructor(status, message, code = "error", details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.name = "HttpError";
  }
};
function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" }
  });
}
function errorResponse(err) {
  if (err instanceof HttpError) {
    return json({ ok: false, error: err.message, code: err.code, details: err.details }, err.status);
  }
  const e = err;
  if (e?.name === "ShopifyError") {
    return json(
      { ok: false, error: `Shopify: ${e.message}`, code: `shopify_${e.kind ?? "error"}`, details: e.details },
      502
    );
  }
  console.error(err);
  return json({ ok: false, error: `Unexpected error: ${e?.message ?? String(err)}`, code: "internal" }, 500);
}
async function readJson(req) {
  if (req.method === "GET" || req.method === "HEAD") return {};
  const text = await req.text();
  if (!text.trim()) return {};
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
  } catch {
  }
  throw new HttpError(400, "The request body must be a JSON object.", "bad_json");
}
async function currentUser(deps) {
  try {
    return await deps.base44.auth.me() ?? null;
  } catch {
    return null;
  }
}
async function requireAdmin(deps) {
  const user = await currentUser(deps);
  if (!user) throw new HttpError(401, "Sign in to the Partner Hub as an admin first.", "unauthenticated");
  if (user.role !== "admin") throw new HttpError(403, "Only Partner Hub admins can do this.", "forbidden");
  return user;
}
function wrap(handler) {
  return async (req, deps) => {
    if (req.method === "OPTIONS") return new Response(null, { status: 204 });
    try {
      return await handler(req, deps);
    } catch (e) {
      return errorResponse(e);
    }
  };
}

// src/lib/records.ts
function asString(v) {
  return typeof v === "string" ? v.trim() : "";
}

// src/lib/queries.ts
var SHOP_CHECK = (
  /* GraphQL */
  `
query PartnerHubShopCheck {
  shop { name myshopifyDomain currencyCode }
  currentAppInstallation { accessScopes { handle } }
  locations(first: 5) { nodes { id name isActive fulfillsOnlineOrders } }
}`
);
var WEBHOOKS = (
  /* GraphQL */
  `
query PartnerHubWebhooks {
  webhookSubscriptions(first: 50) {
    nodes { id topic uri }
  }
}`
);
var WEBHOOK_CREATE = (
  /* GraphQL */
  `
mutation PartnerHubWebhookCreate($topic: WebhookSubscriptionTopic!, $sub: WebhookSubscriptionInput!) {
  webhookSubscriptionCreate(topic: $topic, webhookSubscription: $sub) {
    webhookSubscription { id topic uri }
    userErrors { field message }
  }
}`
);

// src/lib/setup.ts
var REQUIRED_SCOPES = [
  { scope: "read_products", why: "catalogue sync and stock checks" },
  { scope: "read_inventory", why: "stock checks" },
  { scope: "write_orders", why: "creating the gifted orders" },
  { scope: "write_merchant_managed_fulfillment_orders", why: "MARK SHIPPED with a tracking number" },
  { scope: "read_discounts", why: "affiliate code usage" }
];
var WEBHOOK_TOPICS = ["FULFILLMENTS_CREATE", "FULFILLMENTS_UPDATE", "ORDERS_CANCELLED"];
function missingScopes(granted) {
  const set = new Set(granted);
  return REQUIRED_SCOPES.filter(
    ({ scope }) => !set.has(scope) && !(scope.startsWith("read_") && set.has(scope.replace(/^read_/, "write_")))
  );
}
function functionUrl(deps, name) {
  const base = (deps.secret("HUB_PUBLIC_URL") || "https://crooks-partner-hub.base44.app").replace(/\/+$/, "");
  return deps.appId ? `${base}/api/apps/${deps.appId}/functions/${name}` : null;
}
async function checkConnection(deps, shopify, opts) {
  const started = Date.now();
  const data = await shopify.graphql(SHOP_CHECK);
  const granted = data.currentAppInstallation.accessScopes.map((s) => s.handle);
  const missing = missingScopes(granted);
  const warnings = [];
  if (data.shop.currencyCode !== (deps.secret("SHOP_CURRENCY") || "GBP")) {
    warnings.push(`The shop's currency is ${data.shop.currencyCode}; set the SHOP_CURRENCY secret to match.`);
  }
  if (!data.locations.nodes.some((l) => l.isActive && l.fulfillsOnlineOrders)) {
    warnings.push("No active location fulfils online orders, so Shopify can't allocate stock to new orders.");
  }
  const webhookUrl = opts.webhookUrl || functionUrl(deps, "shopifyWebhook");
  const webhooks = [];
  let existing = [];
  try {
    existing = (await shopify.graphql(
      WEBHOOKS
    )).webhookSubscriptions.nodes;
  } catch (e) {
    warnings.push(`Couldn't list webhooks: ${e.message}`);
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
      const res = await shopify.graphql(WEBHOOK_CREATE, { topic, sub: { uri: webhookUrl, format: "JSON" } }, { idempotent: false });
      const errs = res.webhookSubscriptionCreate.userErrors;
      webhooks.push(errs.length ? { topic, status: "error", detail: errs.map((e) => e.message).join("; ") } : { topic, status: "created" });
    } catch (e) {
      webhooks.push({ topic, status: "error", detail: e.message });
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
    tookMs: Date.now() - started
  };
}

// src/lib/shopify.ts
var DEFAULT_STORE_DOMAIN = "5wn03t-nm.myshopify.com";
var DEFAULT_API_VERSION = "2026-07";
var ShopifyError = class extends Error {
  constructor(message, kind, details) {
    super(message);
    this.kind = kind;
    this.details = details;
    this.name = "ShopifyError";
  }
};
function shopifyConfig(secret) {
  const raw = (secret("SHOPIFY_STORE_DOMAIN") || DEFAULT_STORE_DOMAIN).trim().toLowerCase();
  const domain = raw.replace(/^https?:\/\//, "").replace(/\/.*$/, "");
  if (!/^[a-z0-9][a-z0-9-]*\.myshopify\.com$/.test(domain)) {
    throw new HttpError(
      500,
      `SHOPIFY_STORE_DOMAIN must be the store's .myshopify.com address (got "${raw}").`,
      "shopify_not_configured"
    );
  }
  const cfg = {
    domain,
    apiVersion: secret("SHOPIFY_API_VERSION") || DEFAULT_API_VERSION,
    staticToken: secret("SHOPIFY_ADMIN_ACCESS_TOKEN") || void 0,
    clientId: secret("SHOPIFY_CLIENT_ID") || void 0,
    clientSecret: secret("SHOPIFY_CLIENT_SECRET") || void 0
  };
  if (!cfg.staticToken && !(cfg.clientId && cfg.clientSecret)) {
    throw new HttpError(
      500,
      "Shopify isn't connected yet: add the SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET secrets in Base44 (or SHOPIFY_ADMIN_ACCESS_TOKEN for an older custom app).",
      "shopify_not_configured"
    );
  }
  return cfg;
}
var tokenCache = /* @__PURE__ */ new Map();
async function accessToken(cfg, deps, force = false) {
  if (cfg.staticToken) return cfg.staticToken;
  const key = `${cfg.domain}:${cfg.clientId}`;
  const cached = tokenCache.get(key);
  const now = deps.now().getTime();
  if (!force && cached && cached.expiresAt - 5 * 6e4 > now) return cached.token;
  let res;
  try {
    res = await deps.fetch(`https://${cfg.domain}/admin/oauth/access_token`, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded", accept: "application/json" },
      body: new URLSearchParams({
        grant_type: "client_credentials",
        client_id: cfg.clientId,
        client_secret: cfg.clientSecret
      }).toString()
    });
  } catch (e) {
    throw new ShopifyError(`couldn't reach ${cfg.domain} for an access token (${e.message}).`, "network");
  }
  const text = await res.text();
  if (!res.ok) {
    throw new ShopifyError(
      `the access token request was refused (HTTP ${res.status}). Check SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET, and that the app is installed on ${cfg.domain}.`,
      "auth",
      text.slice(0, 300)
    );
  }
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    throw new ShopifyError("the access token response wasn't JSON.", "auth", text.slice(0, 300));
  }
  if (!body.access_token) throw new ShopifyError("the access token response had no token.", "auth");
  tokenCache.set(key, { token: body.access_token, expiresAt: now + (body.expires_in ?? 86399) * 1e3 });
  return body.access_token;
}
var MAX_ATTEMPTS = 5;
function createShopify(deps, cfg = shopifyConfig(deps.secret)) {
  const url = `https://${cfg.domain}/admin/api/${cfg.apiVersion}/graphql.json`;
  async function graphql(query, variables = {}, opts = {}) {
    const idempotent = opts.idempotent ?? !/^\s*mutation\b/.test(query);
    let refreshedToken = false;
    for (let attempt = 1; ; attempt++) {
      const token = await accessToken(cfg, deps);
      let res;
      try {
        res = await deps.fetch(url, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            accept: "application/json",
            "x-shopify-access-token": token
          },
          body: JSON.stringify({ query, variables })
        });
      } catch (e) {
        if (idempotent && attempt < MAX_ATTEMPTS) {
          await deps.sleep(backoff(attempt));
          continue;
        }
        throw new ShopifyError(
          `no response from Shopify (${e.message}).`,
          idempotent ? "network" : "uncertain"
        );
      }
      if (res.status === 401 && !cfg.staticToken && !refreshedToken) {
        refreshedToken = true;
        await accessToken(cfg, deps, true);
        continue;
      }
      if (res.status === 401) {
        throw new ShopifyError("the access token was refused (HTTP 401). Reinstall the app or rotate its credentials.", "auth");
      }
      if (res.status === 403) {
        throw new ShopifyError(
          "the app isn't allowed to do this (HTTP 403). Add the missing access scopes to the Shopify app and reinstall it.",
          "scope"
        );
      }
      if (res.status === 429 && attempt < MAX_ATTEMPTS) {
        const retryAfter = Number(res.headers.get("retry-after"));
        await deps.sleep(Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1e3 : backoff(attempt));
        continue;
      }
      if (res.status >= 500) {
        if (idempotent && attempt < MAX_ATTEMPTS) {
          await deps.sleep(backoff(attempt));
          continue;
        }
        throw new ShopifyError(
          `Shopify returned HTTP ${res.status}.`,
          idempotent ? "http" : "uncertain"
        );
      }
      if (!res.ok) {
        throw new ShopifyError(`Shopify returned HTTP ${res.status}.`, "http", (await res.text()).slice(0, 500));
      }
      let body;
      try {
        body = await res.json();
      } catch {
        throw new ShopifyError("Shopify's response couldn't be read.", idempotent ? "http" : "uncertain");
      }
      const errors = body.errors ?? [];
      if (errors.some((e) => e.extensions?.code === "THROTTLED") && attempt < MAX_ATTEMPTS) {
        const cost = body.extensions?.cost;
        const need = (cost?.requestedQueryCost ?? 100) - (cost?.throttleStatus?.currentlyAvailable ?? 0);
        const rate = cost?.throttleStatus?.restoreRate || 50;
        await deps.sleep(Math.max(1e3, Math.ceil(need / rate * 1e3)));
        continue;
      }
      if (errors.some((e) => e.extensions?.code === "ACCESS_DENIED")) {
        throw new ShopifyError(
          `access denied: ${errors.map((e) => e.message).join("; ")}. Add the missing access scopes to the Shopify app.`,
          "scope",
          errors
        );
      }
      if (errors.length) {
        const internal = errors.some((e) => e.extensions?.code === "INTERNAL_SERVER_ERROR");
        throw new ShopifyError(
          errors.map((e) => e.message).join("; "),
          internal && !idempotent ? "uncertain" : "graphql",
          errors
        );
      }
      if (body.data === void 0) throw new ShopifyError("the response had no data.", "graphql");
      return body.data;
    }
  }
  return { config: cfg, graphql };
}
function backoff(attempt) {
  return Math.min(8e3, 500 * 2 ** (attempt - 1));
}

// src/handlers/shopifyCheckConnection.ts
var shopifyCheckConnection = wrap(async (req, deps) => {
  const body = await readJson(req);
  await requireAdmin(deps);
  return json(
    await checkConnection(deps, createShopify(deps), {
      registerWebhooks: body.registerWebhooks === true,
      webhookUrl: asString(body.webhookUrl) || void 0
    })
  );
});

// src/lib/runtime.ts
import { createClientFromRequest } from "npm:@base44/sdk@0.8.49";
function readSecret(name) {
  try {
    const bridge = globalThis.Base44;
    const v = bridge?.secrets?.get(name);
    if (v) return v;
  } catch {
  }
  try {
    return Deno.env.get(name);
  } catch {
    return void 0;
  }
}
function serve(handler) {
  Deno.serve(async (req) => {
    let base44;
    try {
      base44 = createClientFromRequest(req);
    } catch (e) {
      return Response.json({ ok: false, error: `Not called through Base44: ${e.message}` }, { status: 400 });
    }
    return handler(req, {
      base44,
      secret: readSecret,
      fetch: (input, init) => fetch(input, init),
      now: () => /* @__PURE__ */ new Date(),
      sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
      appId: req.headers.get("Base44-App-Id")
    });
  });
}

// src/functions/shopifyCheckConnection.ts
serve(shopifyCheckConnection);

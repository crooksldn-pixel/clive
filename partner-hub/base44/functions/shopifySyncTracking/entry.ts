// CROOKS Partner Hub — Base44 function "shopifySyncTracking".
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
function timingSafeEqual(a, b) {
  const enc = new TextEncoder();
  const x = enc.encode(a);
  const y = enc.encode(b);
  let diff = x.length ^ y.length;
  const n = Math.max(x.length, y.length);
  for (let i = 0; i < n; i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
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
var PARTNER_KEY_HEADER = "x-partner-key";
var MIN_KEY_LENGTH = 24;
function hasPartnerKey(req, body, deps) {
  const expected = deps.secret("PARTNER_API_KEY") ?? "";
  if (expected.length < MIN_KEY_LENGTH) return false;
  const given = req.headers.get(PARTNER_KEY_HEADER) ?? (typeof body.key === "string" ? body.key : "");
  return given.length > 0 && timingSafeEqual(given, expected);
}
async function requireAdminOrKey(req, body, deps) {
  if (hasPartnerKey(req, body, deps)) return { kind: "key" };
  const user = await requireAdmin(deps);
  return { kind: "admin", email: user.email };
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
function storeHandle(cfg) {
  return cfg.domain.replace(/\.myshopify\.com$/, "");
}
function orderAdminUrl(cfg, orderGid2) {
  const id = orderGid2.split("/").pop();
  return `https://admin.shopify.com/store/${storeHandle(cfg)}/orders/${id}`;
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
function orderGid(id) {
  if (typeof id === "number" && Number.isInteger(id) && id > 0) return `gid://shopify/Order/${id}`;
  if (typeof id !== "string") return null;
  const s = id.trim();
  if (/^gid:\/\/shopify\/Order\/\d+$/.test(s)) return s;
  if (/^\d+$/.test(s)) return `gid://shopify/Order/${s}`;
  return null;
}
function chunk(items, size) {
  const out = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

// src/lib/queries.ts
var ORDERS_BY_QUERY = (
  /* GraphQL */
  `
query PartnerHubOrdersByQuery($query: String!) {
  orders(first: 5, query: $query) {
    nodes { id name createdAt cancelledAt }
  }
}`
);
var ORDERS_TRACKING = (
  /* GraphQL */
  `
query PartnerHubOrdersTracking($ids: [ID!]!) {
  nodes(ids: $ids) {
    __typename
    ... on Order {
      id
      name
      cancelledAt
      displayFulfillmentStatus
      fulfillments(first: 10) {
        id
        status
        displayStatus
        createdAt
        deliveredAt
        inTransitAt
        estimatedDeliveryAt
        trackingInfo(first: 5) { company number url }
      }
    }
  }
}`
);

// src/lib/records.ts
var PAGE = 500;
async function listAll(entity, query, sort = "-created_date") {
  const out = [];
  for (let skip = 0; ; skip += PAGE) {
    const page = query ? await entity.filter(query, sort, PAGE, skip) : await entity.list(sort, PAGE, skip);
    out.push(...page);
    if (page.length < PAGE) return out;
  }
}
function parseRecordDate(value) {
  if (!value) return NaN;
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  return Date.parse(hasZone ? value : `${value}Z`);
}

// src/lib/sends.ts
var DUPLICATE_WINDOW_MS = 10 * 6e4;
function sendTag(sendId) {
  return `hub-send-${sendId}`;
}

// src/lib/tracking.ts
var DEFAULT_POST_WINDOW_DAYS = 21;
var TRACKED_STATUSES = ["preparing", "dispatched", "delivered", "overdue"];
var DEAD_FULFILLMENT = /* @__PURE__ */ new Set(["CANCELLED", "ERROR", "FAILURE"]);
var DEAD_DISPLAY = /* @__PURE__ */ new Set(["LABEL_VOIDED", "CANCELED", "FAILURE"]);
var ORPHAN_TTL_MS = 30 * 6e4;
function normaliseCarrier(company) {
  if (!company) return null;
  const c = company.trim();
  if (/^royal\s*mail/i.test(c)) return "Royal Mail";
  if (/^dpd/i.test(c)) return "DPD";
  return c;
}
function addDays(iso, days) {
  return new Date(Date.parse(iso) + days * 864e5).toISOString();
}
function sameValue(a, b) {
  if ((a ?? null) === (b ?? null)) return true;
  if (typeof a === "string" && typeof b === "string") {
    const ta = Date.parse(a);
    const tb = Date.parse(b);
    return !Number.isNaN(ta) && ta === tb && /\d{4}-\d{2}-\d{2}T/.test(a) && /\d{4}-\d{2}-\d{2}T/.test(b);
  }
  return false;
}
function deriveSendUpdate(send, order, now, postWindowDays = DEFAULT_POST_WINDOW_DAYS) {
  if (send.status === "cancelled" || send.status === "posted") return null;
  let next;
  if (!order) {
    next = { status: "cancelled", cancelledAt: send.cancelledAt ?? now.toISOString() };
  } else if (order.cancelledAt) {
    next = { status: "cancelled", cancelledAt: order.cancelledAt };
  } else {
    const live = (order.fulfillments ?? []).filter((f) => !DEAD_FULFILLMENT.has(f.status) && !DEAD_DISPLAY.has(f.displayStatus ?? "")).sort((a, b) => Date.parse(a.createdAt) - Date.parse(b.createdAt));
    if (!live.length) {
      next = {
        status: send.postedUrl ? "posted" : "preparing",
        dispatchedAt: null,
        postByDate: null,
        trackingNumber: null,
        trackingUrl: null,
        carrier: null,
        deliveredAt: null
      };
    } else {
      const dispatchedAt = live[0].createdAt;
      const withNumber = live.filter((f) => f.trackingInfo?.some((t2) => t2.number));
      const t = withNumber.length ? withNumber[withNumber.length - 1].trackingInfo.find((x) => x.number) : void 0;
      const delivered = live.every((f) => f.displayStatus === "DELIVERED" || !!f.deliveredAt);
      const deliveredTimes = live.map((f) => f.deliveredAt).filter((d) => !!d).sort();
      const deliveredAt = delivered ? deliveredTimes[deliveredTimes.length - 1] ?? send.deliveredAt ?? now.toISOString() : null;
      const postByDate = addDays(dispatchedAt, postWindowDays);
      let status = send.postedUrl ? "posted" : delivered ? "delivered" : "dispatched";
      if (status !== "posted" && now.getTime() > Date.parse(postByDate)) status = "overdue";
      next = {
        status,
        dispatchedAt,
        postByDate,
        deliveredAt,
        trackingNumber: t?.number ?? null,
        trackingUrl: t?.url ?? null,
        carrier: normaliseCarrier(t?.company)
      };
    }
  }
  const changed = {};
  for (const [k, v] of Object.entries(next)) {
    if (!sameValue(send[k], v)) {
      changed[k] = v;
    }
  }
  return Object.keys(changed).length ? changed : null;
}
async function syncTracking(deps, shopify, opts = {}) {
  const db = deps.base44.asServiceRole.entities;
  const now = deps.now();
  const windowDays = Number(deps.secret("POST_WINDOW_DAYS")) || DEFAULT_POST_WINDOW_DAYS;
  let sends;
  if (opts.sendIds) {
    sends = (await Promise.all(opts.sendIds.map((id) => db.Send.get(id).catch(() => null)))).filter(
      (s) => !!s
    );
  } else {
    sends = await listAll(db.Send);
  }
  const summary = { checked: 0, updated: 0, linked: 0, removed: 0, statuses: {}, changes: [], errors: [] };
  for (const s of sends.filter((x) => !x.influencerEmail && x.influencerId)) {
    try {
      const inf = await db.Influencer.get(s.influencerId);
      if (inf?.email) {
        await db.Send.update(s.id, { influencerEmail: inf.email });
        s.influencerEmail = inf.email;
      }
    } catch {
    }
  }
  const active = sends.filter((s) => TRACKED_STATUSES.includes(s.status) || !!s.postedUrl && s.status !== "posted");
  for (const s of active.filter((s2) => !s2.shopifyOrderId && s2.createdByEmail)) {
    const age = now.getTime() - parseRecordDate(s.created_date);
    if (!(age > 2 * 6e4)) continue;
    try {
      const res = await shopify.graphql(ORDERS_BY_QUERY, {
        query: `tag:'${sendTag(s.id)}'`
      });
      const found = res.orders.nodes[0];
      if (found) {
        Object.assign(s, {
          shopifyOrderId: found.id,
          shopifyOrderName: found.name,
          shopifyOrderUrl: orderAdminUrl(shopify.config, found.id)
        });
        await db.Send.update(s.id, {
          shopifyOrderId: found.id,
          shopifyOrderName: found.name,
          shopifyOrderUrl: s.shopifyOrderUrl
        });
        summary.linked++;
      } else if (age > ORPHAN_TTL_MS) {
        await db.Send.delete(s.id);
        summary.removed++;
      }
    } catch (e) {
      summary.errors.push(`send ${s.id}: ${e.message}`);
    }
  }
  const withOrder = active.filter((s) => orderGid(s.shopifyOrderId));
  for (const group of chunk(withOrder, 50)) {
    const ids = group.map((s) => orderGid(s.shopifyOrderId));
    let nodes;
    try {
      nodes = (await shopify.graphql(ORDERS_TRACKING, { ids })).nodes;
    } catch (e) {
      summary.errors.push(e.message);
      continue;
    }
    const byId = new Map(nodes.filter((n) => n?.__typename === "Order").map((n) => [n.id, n]));
    for (const s of group) {
      summary.checked++;
      const order = byId.get(orderGid(s.shopifyOrderId)) ?? null;
      const update = deriveSendUpdate(s, order, now, windowDays);
      const finalStatus = update?.status ?? s.status;
      summary.statuses[finalStatus] = (summary.statuses[finalStatus] ?? 0) + 1;
      if (!update) continue;
      try {
        await db.Send.update(s.id, { ...update, lastSyncedAt: now.toISOString() });
        summary.updated++;
        if (update.status && update.status !== s.status) {
          summary.changes.push({ sendId: s.id, orderName: s.shopifyOrderName, from: s.status, to: update.status });
        }
      } catch (e) {
        summary.errors.push(`send ${s.id}: ${e.message}`);
      }
    }
  }
  return summary;
}

// src/handlers/shopifySyncTracking.ts
var shopifySyncTracking = wrap(async (req, deps) => {
  const body = await readJson(req);
  await requireAdminOrKey(req, body, deps);
  return json({ ok: true, ...await syncTracking(deps, createShopify(deps)) });
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

// src/functions/shopifySyncTracking.ts
serve(shopifySyncTracking);

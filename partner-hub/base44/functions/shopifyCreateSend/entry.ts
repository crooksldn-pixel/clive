// CROOKS Partner Hub — Base44 function "shopifyCreateSend".
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
var PAGE = 500;
async function listAll(entity, query, sort = "-created_date") {
  const out = [];
  for (let skip = 0; ; skip += PAGE) {
    const page = query ? await entity.filter(query, sort, PAGE, skip) : await entity.list(sort, PAGE, skip);
    out.push(...page);
    if (page.length < PAGE) return out;
  }
}
async function getOr404(entity, id, what) {
  if (!id) throw new HttpError(400, `Missing ${what} id.`, "bad_request");
  try {
    const rec = await entity.get(id);
    if (rec) return rec;
  } catch {
  }
  throw new HttpError(404, `${what} not found (${id}).`, "not_found");
}
function asString(v) {
  return typeof v === "string" ? v.trim() : "";
}
function parseRecordDate(value) {
  if (!value) return NaN;
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  return Date.parse(hasZone ? value : `${value}Z`);
}

// src/lib/address.ts
var PROVINCES = {
  US: {
    alabama: "AL",
    alaska: "AK",
    arizona: "AZ",
    arkansas: "AR",
    california: "CA",
    colorado: "CO",
    connecticut: "CT",
    delaware: "DE",
    "district of columbia": "DC",
    "washington dc": "DC",
    florida: "FL",
    georgia: "GA",
    hawaii: "HI",
    idaho: "ID",
    illinois: "IL",
    indiana: "IN",
    iowa: "IA",
    kansas: "KS",
    kentucky: "KY",
    louisiana: "LA",
    maine: "ME",
    maryland: "MD",
    massachusetts: "MA",
    michigan: "MI",
    minnesota: "MN",
    mississippi: "MS",
    missouri: "MO",
    montana: "MT",
    nebraska: "NE",
    nevada: "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    ohio: "OH",
    oklahoma: "OK",
    oregon: "OR",
    pennsylvania: "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    tennessee: "TN",
    texas: "TX",
    utah: "UT",
    vermont: "VT",
    virginia: "VA",
    washington: "WA",
    "west virginia": "WV",
    wisconsin: "WI",
    wyoming: "WY",
    "puerto rico": "PR"
  },
  CA: {
    alberta: "AB",
    "british columbia": "BC",
    manitoba: "MB",
    "new brunswick": "NB",
    "newfoundland and labrador": "NL",
    newfoundland: "NL",
    "northwest territories": "NT",
    "nova scotia": "NS",
    nunavut: "NU",
    ontario: "ON",
    "prince edward island": "PE",
    quebec: "QC",
    "québec": "QC",
    saskatchewan: "SK",
    yukon: "YT"
  },
  AU: {
    "australian capital territory": "ACT",
    "new south wales": "NSW",
    "northern territory": "NT",
    queensland: "QLD",
    "south australia": "SA",
    tasmania: "TAS",
    victoria: "VIC",
    "western australia": "WA"
  }
};
function provinceCode(country, region) {
  const table = PROVINCES[country];
  if (!table || !region) return void 0;
  const r = region.trim();
  const upper = r.toUpperCase();
  if (Object.values(table).includes(upper)) return upper;
  return table[r.toLowerCase().replace(/\s+/g, " ")];
}
function splitName(fullName) {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  if (parts.length <= 1) return { firstName: "", lastName: parts[0] ?? "" };
  return { firstName: parts.slice(0, -1).join(" "), lastName: parts[parts.length - 1] };
}
function toShippingAddress(addr) {
  if (!addr) throw new HttpError(422, "This influencer has no shipping address on file.", "address_missing");
  const missing = ["fullName", "line1", "city", "postcode", "country"].filter(
    (k) => !String(addr[k] ?? "").trim()
  );
  if (missing.length) {
    throw new HttpError(
      422,
      `The shipping address is incomplete (missing ${missing.join(", ")}). Ask the influencer to update it.`,
      "address_incomplete",
      { missing }
    );
  }
  const country = String(addr.country).trim().toUpperCase();
  if (!/^[A-Z]{2}$/.test(country)) {
    throw new HttpError(422, `The address country "${addr.country}" isn't a two-letter country code.`, "address_invalid");
  }
  const province = provinceCode(country, addr.region);
  if (PROVINCES[country] && !province) {
    throw new HttpError(
      422,
      `Shopify needs a valid state/province for ${country} addresses, but the region is "${addr.region ?? ""}". Fix the influencer's address first.`,
      "address_invalid"
    );
  }
  const { firstName, lastName } = splitName(String(addr.fullName));
  const out = {
    firstName,
    lastName,
    address1: String(addr.line1).trim(),
    city: String(addr.city).trim(),
    zip: String(addr.postcode).trim(),
    countryCode: country
  };
  if (addr.line2?.trim()) out.address2 = addr.line2.trim();
  if (province) out.provinceCode = province;
  return out;
}

// src/lib/queries.ts
var VARIANTS_FOR_SEND = (
  /* GraphQL */
  `
query PartnerHubVariantsForSend($ids: [ID!]!) {
  nodes(ids: $ids) {
    __typename
    ... on ProductVariant {
      id
      title
      displayName
      sku
      price
      inventoryQuantity
      inventoryPolicy
      requiresComponents
      inventoryItem { tracked }
      product { id title handle status }
      productVariantComponents(first: 10) {
        nodes {
          quantity
          productVariant {
            id
            title
            displayName
            sku
            price
            inventoryQuantity
            inventoryPolicy
            requiresComponents
            inventoryItem { tracked }
            product { id title handle status }
          }
        }
      }
    }
  }
}`
);
var ORDER_CREATE = (
  /* GraphQL */
  `
mutation PartnerHubOrderCreate($order: OrderCreateOrderInput!, $options: OrderCreateOptionsInput) {
  orderCreate(order: $order, options: $options) {
    order {
      id
      name
      legacyResourceId
      createdAt
      displayFinancialStatus
      totalPriceSet { shopMoney { amount currencyCode } }
    }
    userErrors { field message code }
  }
}`
);
var ORDERS_BY_QUERY = (
  /* GraphQL */
  `
query PartnerHubOrdersByQuery($query: String!) {
  orders(first: 5, query: $query) {
    nodes { id name createdAt cancelledAt }
  }
}`
);

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
function orderAdminUrl(cfg, orderGid) {
  const id = orderGid.split("/").pop();
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
var VARIANT_GID = /^gid:\/\/shopify\/ProductVariant\/(\d+)$/;
function variantGid(id) {
  if (typeof id === "number" && Number.isInteger(id) && id > 0) return `gid://shopify/ProductVariant/${id}`;
  if (typeof id !== "string") return null;
  const s = id.trim();
  if (VARIANT_GID.test(s)) return s;
  if (/^\d+$/.test(s)) return `gid://shopify/ProductVariant/${s}`;
  return null;
}

// src/lib/sends.ts
var MAX_ITEMS = 25;
var MAX_QUANTITY = 10;
var DUPLICATE_WINDOW_MS = 10 * 6e4;
function parseItems(raw) {
  if (!Array.isArray(raw) || raw.length === 0) {
    throw new HttpError(400, "Pick at least one item to send.", "no_items");
  }
  if (raw.length > MAX_ITEMS) throw new HttpError(400, `At most ${MAX_ITEMS} items per send.`, "too_many_items");
  const merged = /* @__PURE__ */ new Map();
  raw.forEach((item, i) => {
    const it = item ?? {};
    const id = variantGid(it.variantId);
    if (!id) {
      throw new HttpError(
        400,
        `Item ${i + 1}${it.name ? ` (${it.name})` : ""} has no Shopify variant id. Run SYNC SHOPIFY on the catalogue and try again.`,
        "bad_variant"
      );
    }
    const q = it.quantity === void 0 ? 1 : Number(it.quantity);
    if (!Number.isInteger(q) || q < 1 || q > MAX_QUANTITY) {
      throw new HttpError(400, `Item ${i + 1} quantity must be a whole number from 1 to ${MAX_QUANTITY}.`, "bad_quantity");
    }
    merged.set(id, (merged.get(id) ?? 0) + q);
  });
  return [...merged].map(([variantId, quantity]) => ({ variantId, quantity }));
}
function sizeLabel(v) {
  return v.title === "Default Title" ? "ONE" : v.title;
}
async function planSend(shopify, requested) {
  const data = await shopify.graphql(VARIANTS_FOR_SEND, {
    ids: requested.map((r) => r.variantId)
  });
  const byId = /* @__PURE__ */ new Map();
  for (const n of data.nodes) if (n && n.__typename === "ProductVariant") byId.set(n.id, n);
  const problems = [];
  const warnings = [];
  const items = [];
  const lines = [];
  const need = /* @__PURE__ */ new Map();
  const addNeed = (v, qty) => {
    const cur = need.get(v.id);
    need.set(v.id, { v, qty: (cur?.qty ?? 0) + qty });
  };
  for (const req of requested) {
    const v = byId.get(req.variantId);
    if (!v) {
      problems.push({
        variantId: req.variantId,
        code: "not_found",
        message: `${req.variantId} no longer exists in Shopify (deleted or replaced). Run SYNC SHOPIFY and pick it again.`
      });
      continue;
    }
    if (v.product.status === "ARCHIVED") {
      problems.push({ variantId: v.id, code: "archived", message: `${v.displayName} is archived in Shopify.` });
      continue;
    }
    if (v.product.status === "DRAFT") warnings.push(`${v.displayName} is a draft in Shopify (not on sale yet).`);
    const item = {
      name: v.product.title,
      size: sizeLabel(v),
      variantId: v.id,
      quantity: req.quantity,
      sku: v.sku
    };
    if (v.requiresComponents) {
      const parts = v.productVariantComponents.nodes;
      if (!parts.length) {
        problems.push({
          variantId: v.id,
          code: "bundle_empty",
          message: `${v.displayName} is a bundle with no pieces set up in Shopify.`
        });
        continue;
      }
      item.components = [];
      for (const part of parts) {
        const pv = part.productVariant;
        const qty = part.quantity * req.quantity;
        if (pv.product.status === "ARCHIVED") {
          problems.push({
            variantId: pv.id,
            code: "archived",
            message: `${pv.displayName} (part of ${v.displayName}) is archived in Shopify.`
          });
          continue;
        }
        lines.push({ variantId: pv.id, quantity: qty, unitPrice: pv.price, title: pv.displayName, partOf: v.displayName });
        item.components.push({ name: pv.displayName, variantId: pv.id, quantity: qty });
        addNeed(pv, qty);
      }
    } else {
      lines.push({ variantId: v.id, quantity: req.quantity, unitPrice: v.price, title: v.displayName });
      addNeed(v, req.quantity);
    }
    items.push(item);
  }
  const stock = [];
  for (const { v, qty } of need.values()) {
    const tracked = v.inventoryItem?.tracked !== false;
    const onHand = v.inventoryQuantity ?? 0;
    stock.push({ variantId: v.id, title: v.displayName, needed: qty, inStock: tracked ? onHand : null, tracked });
    if (tracked && qty > onHand) {
      problems.push({
        variantId: v.id,
        code: "out_of_stock",
        message: `${v.displayName}: ${Math.max(onHand, 0)} in stock, ${qty} needed`
      });
    }
  }
  const retailValue = round2(lines.reduce((sum, l) => sum + Number(l.unitPrice) * l.quantity, 0));
  return { items, lines, stock, problems, warnings, retailValue };
}
function assertSendable(plan) {
  if (!plan.problems.length) return;
  throw new HttpError(
    409,
    `Can't create the order: ${plan.problems.map((p) => p.message).join("; ")}.`,
    "stock_check_failed",
    { problems: plan.problems, stock: plan.stock }
  );
}
function round2(n) {
  return Math.round(n * 100) / 100;
}
function tagSafe(s) {
  return s.toLowerCase().replace(/[^a-z0-9._-]/g, "").slice(0, 28);
}
function sendTag(sendId) {
  return `hub-send-${sendId}`;
}
function buildOrderInput(plan, ctx) {
  const money = (amount) => ({ shopMoney: { amount, currencyCode: ctx.currency } });
  const social = (p) => ctx.socials.find((s) => s.platform === p);
  const tt = social("tiktok");
  const ig = social("instagram");
  const note = [
    `Influencer seeding for @${ctx.influencer.username}`,
    tt?.profileUrl ? `TikTok: ${tt.profileUrl}` : null,
    ig?.profileUrl ? `Instagram: ${ig.profileUrl}` : null,
    `Created in the CROOKS Partner Hub by ${ctx.createdBy}.`,
    ctx.note ? `Note: ${ctx.note}` : null
  ].filter(Boolean).join("\n");
  return {
    order: {
      email: ctx.influencer.email || void 0,
      shippingAddress: ctx.shippingAddress,
      lineItems: plan.lines.map((l) => ({
        variantId: l.variantId,
        quantity: l.quantity,
        priceSet: money(l.unitPrice),
        ...l.partOf ? { properties: [{ name: "Part of", value: l.partOf }] } : {}
      })),
      discountCode: { itemPercentageDiscountCode: { code: ctx.discountCode, percentage: 100 } },
      shippingLines: [{ title: "Influencer seeding (free)", code: "SEEDING", priceSet: money("0.00") }],
      financialStatus: "PAID",
      tags: ["SEEDING", "partner-hub", `influencer-${tagSafe(ctx.influencer.username)}`, sendTag(ctx.sendId)],
      note,
      sourceIdentifier: ctx.sendId,
      customAttributes: [
        { key: "partner_hub_send_id", value: ctx.sendId },
        { key: "influencer", value: `@${ctx.influencer.username}` }
      ]
    },
    options: {
      inventoryBehaviour: "DECREMENT_OBEYING_POLICY",
      sendReceipt: false,
      sendFulfillmentReceipt: false
    }
  };
}
function sameItems(a, b) {
  if (!b?.length) return false;
  const sig = (xs) => xs.map((x) => `${x.variantId}x${x.quantity ?? 1}`).sort().join(",");
  return sig(a) === sig(b);
}
async function createSend(deps, shopify, input) {
  const db = deps.base44.asServiceRole.entities;
  const influencer = await getOr404(db.Influencer, input.influencerId, "Influencer");
  if (influencer.status === "blocked") {
    throw new HttpError(409, `@${influencer.username} is blocked, so nothing can be sent to them.`, "influencer_blocked");
  }
  const [addresses, socials, previous] = await Promise.all([
    db.Address.filter({ influencerId: influencer.id }),
    db.SocialAccount.filter({ influencerId: influencer.id }),
    listAll(db.Send, { influencerId: influencer.id })
  ]);
  const shippingAddress = toShippingAddress(addresses[0]);
  if (!input.dryRun) {
    const now = deps.now().getTime();
    const recent = previous.find(
      (s) => s.status !== "cancelled" && s.created_date && now - parseRecordDate(s.created_date) < DUPLICATE_WINDOW_MS && sameItems(input.items, s.items)
    );
    if (recent?.shopifyOrderName) {
      return {
        ok: true,
        duplicate: true,
        sendId: recent.id,
        orderId: recent.shopifyOrderId ?? void 0,
        orderName: recent.shopifyOrderName,
        orderAdminUrl: recent.shopifyOrderUrl ?? void 0,
        items: recent.items ?? [],
        stock: [],
        warnings: [`Already created ${recent.shopifyOrderName} for these items a few minutes ago; not creating another.`],
        retailValue: recent.retailValueGbp ?? 0
      };
    }
    if (recent) {
      throw new HttpError(
        409,
        "An order for these exact items is still being confirmed with Shopify. Press SYNC in a few minutes before trying again.",
        "send_pending",
        { sendId: recent.id }
      );
    }
  }
  const plan = await planSend(shopify, input.items);
  assertSendable(plan);
  const discountCode = deps.secret("SEEDING_DISCOUNT_CODE") || "INFLUENCER-SEEDING";
  const currency = deps.secret("SHOP_CURRENCY") || "GBP";
  const ctxBase = {
    influencer,
    shippingAddress,
    socials,
    createdBy: input.createdBy,
    note: input.note,
    discountCode,
    currency
  };
  if (input.dryRun) {
    return {
      ok: true,
      dryRun: true,
      items: plan.items,
      stock: plan.stock,
      warnings: plan.warnings,
      retailValue: plan.retailValue,
      orderInput: buildOrderInput(plan, { ...ctxBase, sendId: "DRY-RUN" })
    };
  }
  const send = await db.Send.create({
    influencerId: influencer.id,
    influencerEmail: influencer.email,
    status: "preparing",
    items: plan.items,
    retailValueGbp: plan.retailValue,
    createdByEmail: input.createdBy
  });
  const vars = buildOrderInput(plan, { ...ctxBase, sendId: send.id });
  let order;
  try {
    const res = await shopify.graphql(ORDER_CREATE, vars, { idempotent: false });
    const errs = res.orderCreate.userErrors;
    if (errs.length || !res.orderCreate.order) {
      await db.Send.delete(send.id).catch(() => {
      });
      throw new HttpError(
        422,
        `Shopify refused the order: ${errs.map((e) => e.message).join("; ") || "no order returned"}.`,
        "shopify_rejected",
        { userErrors: errs }
      );
    }
    order = res.orderCreate.order;
  } catch (e) {
    if (!(e instanceof ShopifyError) || e.kind !== "uncertain") {
      if (!(e instanceof HttpError)) await db.Send.delete(send.id).catch(() => {
      });
      throw e;
    }
    const found = await findOrderByTag(deps, shopify, send.id);
    if (!found) {
      throw new HttpError(
        502,
        `Shopify didn't confirm the order. Don't retry yet: press SYNC in a few minutes and the hub will link the order if Shopify created it (tag ${sendTag(send.id)}).`,
        "shopify_uncertain",
        { sendId: send.id }
      );
    }
    order = found;
  }
  const adminUrl = orderAdminUrl(shopify.config, order.id);
  const warnings = [...plan.warnings];
  try {
    await db.Send.update(send.id, {
      shopifyOrderId: order.id,
      shopifyOrderName: order.name,
      shopifyOrderUrl: adminUrl,
      lastSyncedAt: deps.now().toISOString()
    });
  } catch {
    warnings.push(`Order ${order.name} was created, but the hub record didn't save; the next SYNC will link it.`);
  }
  return {
    ok: true,
    sendId: send.id,
    orderId: order.id,
    orderName: order.name,
    orderAdminUrl: adminUrl,
    items: plan.items,
    stock: plan.stock,
    warnings,
    retailValue: plan.retailValue
  };
}
async function findOrderByTag(deps, shopify, sendId) {
  for (let i = 0; i < 2; i++) {
    await deps.sleep(2e3);
    try {
      const res = await shopify.graphql(
        ORDERS_BY_QUERY,
        { query: `tag:'${sendTag(sendId)}'` }
      );
      if (res.orders.nodes[0]) return res.orders.nodes[0];
    } catch {
    }
  }
  return null;
}

// src/handlers/shopifyCreateSend.ts
var shopifyCreateSend = wrap(async (req, deps) => {
  const body = await readJson(req);
  const admin = await requireAdmin(deps);
  const influencerId = asString(body.influencerId);
  if (!influencerId) throw new HttpError(400, "Missing influencerId.", "bad_request");
  const result = await createSend(deps, createShopify(deps), {
    influencerId,
    items: parseItems(body.items),
    note: asString(body.note).slice(0, 500) || void 0,
    dryRun: body.dryRun === true,
    createdBy: admin.email
  });
  return json(result);
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

// src/functions/shopifyCreateSend.ts
serve(shopifyCreateSend);

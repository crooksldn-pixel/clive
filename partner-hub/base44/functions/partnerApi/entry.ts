// CROOKS Partner Hub — Base44 function "partnerApi".
// GENERATED from partner-hub/src by `npm run build`. Edit the source, not this file.


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
var CATALOG = (
  /* GraphQL */
  `
query PartnerHubCatalog($cursor: String, $query: String) {
  products(first: 8, after: $cursor, query: $query, sortKey: ID) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      handle
      title
      productType
      tags
      status
      featuredMedia { preview { image { url } } }
      options { name position }
      variants(first: 50) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          title
          sku
          price
          inventoryQuantity
          inventoryPolicy
          requiresComponents
          inventoryItem { tracked }
          selectedOptions { name value }
        }
      }
    }
  }
}`
);
var MORE_VARIANTS = (
  /* GraphQL */
  `
query PartnerHubMoreVariants($id: ID!, $cursor: String) {
  product(id: $id) {
    variants(first: 50, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        title
        sku
        price
        inventoryQuantity
        inventoryPolicy
        requiresComponents
        inventoryItem { tracked }
        selectedOptions { name value }
      }
    }
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
var FULFILLMENT_ORDERS = (
  /* GraphQL */
  `
query PartnerHubFulfillmentOrders($id: ID!) {
  order(id: $id) {
    id
    name
    cancelledAt
    fulfillmentOrders(first: 10) {
      nodes { id status supportedActions { action } }
    }
  }
}`
);
var FULFILLMENT_CREATE = (
  /* GraphQL */
  `
mutation PartnerHubFulfillmentCreate($fulfillment: FulfillmentInput!) {
  fulfillmentCreate(fulfillment: $fulfillment) {
    fulfillment {
      id
      status
      createdAt
      trackingInfo(first: 5) { company number url }
    }
    userErrors { field message }
  }
}`
);
var DISCOUNT_USAGE = (
  /* GraphQL */
  `
query PartnerHubDiscountUsage($code: String!) {
  codeDiscountNodeByCode(code: $code) {
    id
    codeDiscount {
      __typename
      ... on DiscountCodeBasic { asyncUsageCount }
      ... on DiscountCodeBxgy { asyncUsageCount }
      ... on DiscountCodeFreeShipping { asyncUsageCount }
      ... on DiscountCodeApp { asyncUsageCount }
    }
  }
}`
);
var DISCOUNT_ORDERS = (
  /* GraphQL */
  `
query PartnerHubDiscountOrders($query: String!, $cursor: String) {
  orders(first: 100, after: $cursor, query: $query) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      cancelledAt
      test
      currentSubtotalPriceSet { shopMoney { amount currencyCode } }
    }
  }
}`
);

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
var PARTNER_KEY_HEADER = "x-partner-key";
var MIN_KEY_LENGTH = 24;
function hasPartnerKey(req, body, deps) {
  const expected = deps.secret("PARTNER_API_KEY") ?? "";
  if (expected.length < MIN_KEY_LENGTH) return false;
  const given = req.headers.get(PARTNER_KEY_HEADER) ?? (typeof body.key === "string" ? body.key : "");
  return given.length > 0 && timingSafeEqual(given, expected);
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

// src/lib/catalog.ts
var UNTRACKED_STOCK = 999;
var has = (text, re) => re.test(text);
function classify(p) {
  const type = (p.productType || "").toLowerCase();
  const tags = (p.tags || []).map((t) => t.toLowerCase());
  const text = `${type} ${(p.title || "").toLowerCase()} ${tags.join(" ")}`;
  const sized = (p.options || []).some((o) => /size/i.test(o.name));
  const bottom = has(text, /\b(jogger|joggers|sweatpants?|pants?|trousers?|jeans?|jorts?|shorts?|baggies)\b/);
  const sizeCategory = !sized ? "onesize" : bottom ? "bottom" : "top";
  if (type === "sets" || type === "set" || tags.includes("set")) return { type: "set", sizeCategory: sized ? "top" : "onesize" };
  if (has(text, /\b(jeans?|denim|jorts?)\b/)) return { type: "denim", sizeCategory: sized ? "bottom" : "onesize" };
  if (has(text, /\b(t-shirts?|tees?|t-shirt)\b/)) return { type: "tee", sizeCategory };
  if (has(text, /\b(socks?|caps?|hats?|beanies?|balaclavas?|bags?|duffle|tote|keyrings?|accessories)\b/)) {
    return { type: "accessories", sizeCategory };
  }
  if (has(text, /\b(outerwear|jackets?|windbreakers?|puffa|puffer|coats?|gilet)\b/)) return { type: "outerwear", sizeCategory };
  if (has(text, /\b(hoodies?|sweatshirts?|crewnecks?|joggers?|sweats|fleece|shorts?)\b/)) return { type: "sweats", sizeCategory };
  return { type: sized ? "sweats" : "accessories", sizeCategory };
}
function variantSize(product, v) {
  const sizeOptions = [...product.options || []].sort((a, b) => a.position - b.position).filter((o) => /size/i.test(o.name)).map((o) => o.name);
  if (sizeOptions.length) {
    const value = v.selectedOptions.find((o) => o.name === sizeOptions[0])?.value;
    if (value) return value;
  }
  return "ONE";
}
function toVariantRecord(product, v) {
  const tracked = v.inventoryItem?.tracked !== false;
  return {
    variantId: v.id,
    label: v.title === "Default Title" ? "ONE" : v.title,
    size: variantSize(product, v),
    stock: tracked ? Math.max(0, v.inventoryQuantity ?? 0) : UNTRACKED_STOCK,
    price: Number(v.price),
    sku: v.sku,
    tracked,
    isBundle: v.requiresComponents || void 0
  };
}
function syncedFields(p, nowIso) {
  const variants = p.variants.nodes.map((v) => toVariantRecord(p, v));
  const prices = variants.map((v) => v.price ?? 0).filter((n) => n > 0);
  const { type, sizeCategory } = classify(p);
  return {
    handle: p.handle,
    name: p.title,
    type,
    sizeCategory,
    imageUrl: p.featuredMedia?.preview?.image?.url ?? void 0,
    priceGbp: prices.length ? Math.min(...prices) : void 0,
    variants,
    shopifyProductId: p.id,
    shopifyStatus: p.status,
    syncedAt: nowIso
  };
}
function planCatalog(existing, products, now) {
  const nowIso = now.toISOString();
  const plan = { creates: [], updates: [], missing: [] };
  const claimed = /* @__PURE__ */ new Set();
  let nextSort = Math.max(-1, ...existing.map((r) => typeof r.sortOrder === "number" ? r.sortOrder : -1)) + 1;
  const find = (p) => {
    const free = existing.filter((r) => !claimed.has(r.id));
    const ids = new Set(p.variants.nodes.map((v) => v.id));
    return free.find((r) => r.handle === p.handle) ?? free.find((r) => r.shopifyProductId === p.id) ?? free.find((r) => (r.variants || []).some((v) => ids.has(v.variantId)));
  };
  for (const p of products) {
    if (p.status === "ARCHIVED") continue;
    const fields = syncedFields(p, nowIso);
    const rec = find(p);
    if (rec) {
      claimed.add(rec.id);
      const data = { ...fields };
      if (!data.imageUrl) delete data.imageUrl;
      plan.updates.push({ id: rec.id, data, handleMovedFrom: rec.handle !== p.handle ? rec.handle : void 0 });
    } else {
      plan.creates.push({ ...fields, available: p.status === "ACTIVE", sortOrder: nextSort++ });
    }
  }
  for (const r of existing) {
    if (claimed.has(r.id)) continue;
    plan.missing.push({
      id: r.id,
      data: {
        available: false,
        shopifyStatus: "MISSING",
        syncedAt: nowIso,
        variants: (r.variants || []).map((v) => ({ ...v, stock: 0 }))
      }
    });
  }
  return plan;
}
async function fetchCatalog(shopify) {
  const out = [];
  let cursor = null;
  for (let page = 0; page < 100; page++) {
    const data = await shopify.graphql(CATALOG, { cursor, query: "status:active OR status:draft" });
    for (const p of data.products.nodes) {
      let more = p.variants.pageInfo;
      while (more?.hasNextPage) {
        const extra = await shopify.graphql(MORE_VARIANTS, {
          id: p.id,
          cursor: more.endCursor
        });
        if (!extra.product) break;
        p.variants.nodes.push(...extra.product.variants.nodes);
        more = extra.product.variants.pageInfo;
      }
      out.push(p);
    }
    if (!data.products.pageInfo.hasNextPage) break;
    cursor = data.products.pageInfo.endCursor;
  }
  return out;
}
async function syncCatalog(deps, shopify) {
  const db = deps.base44.asServiceRole.entities;
  const [products, existing] = await Promise.all([fetchCatalog(shopify), listAll(db.Product, void 0, "name")]);
  const plan = planCatalog(existing, products, deps.now());
  for (const c of plan.creates) await db.Product.create(c);
  const renamed = [];
  for (const u of plan.updates) {
    await db.Product.update(u.id, u.data);
    if (u.handleMovedFrom && u.data.handle) {
      const interests = await listAll(db.Interest, { productHandle: u.handleMovedFrom });
      for (const i of interests) await db.Interest.update(i.id, { productHandle: u.data.handle });
      renamed.push({ from: u.handleMovedFrom, to: u.data.handle, interestsMoved: interests.length });
    }
  }
  for (const m of plan.missing) await db.Product.update(m.id, m.data);
  return {
    products: products.length,
    created: plan.creates.length,
    updated: plan.updates.length,
    hiddenMissing: plan.missing.length,
    renamed
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
var VARIANT_GID = /^gid:\/\/shopify\/ProductVariant\/(\d+)$/;
function variantGid(id) {
  if (typeof id === "number" && Number.isInteger(id) && id > 0) return `gid://shopify/ProductVariant/${id}`;
  if (typeof id !== "string") return null;
  const s = id.trim();
  if (VARIANT_GID.test(s)) return s;
  if (/^\d+$/.test(s)) return `gid://shopify/ProductVariant/${s}`;
  return null;
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
  const social2 = (p) => ctx.socials.find((s) => s.platform === p);
  const tt = social2("tiktok");
  const ig = social2("instagram");
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

// src/lib/fulfil.ts
function parseMarkShipped(body) {
  const sendId = typeof body.sendId === "string" ? body.sendId.trim() : "";
  const trackingNumber = typeof body.trackingNumber === "string" ? body.trackingNumber.replace(/\s+/g, "").trim() : "";
  const carrier = typeof body.carrier === "string" ? body.carrier.trim() : "";
  const trackingUrl = typeof body.trackingUrl === "string" && body.trackingUrl.trim() ? body.trackingUrl.trim() : void 0;
  if (!sendId) throw new HttpError(400, "Missing sendId.", "bad_request");
  if (!/^[A-Za-z0-9-]{4,60}$/.test(trackingNumber)) {
    throw new HttpError(400, "Enter the tracking number (letters and digits only).", "bad_tracking_number");
  }
  if (!carrier || carrier.length > 60) throw new HttpError(400, "Enter the carrier (e.g. Royal Mail, DPD, Evri).", "bad_carrier");
  if (trackingUrl && !/^https:\/\/\S+$/.test(trackingUrl)) {
    throw new HttpError(400, "The tracking link must start with https://", "bad_tracking_url");
  }
  return { sendId, trackingNumber, carrier, trackingUrl, notifyCustomer: body.notifyCustomer === true };
}
async function markShipped(deps, shopify, input) {
  const db = deps.base44.asServiceRole.entities;
  const send = await getOr404(db.Send, input.sendId, "Send");
  if (send.status === "cancelled") throw new HttpError(409, "This send was cancelled.", "send_cancelled");
  const orderId = orderGid(send.shopifyOrderId);
  if (!orderId) throw new HttpError(409, "This send has no Shopify order yet.", "no_order");
  const data = await shopify.graphql(FULFILLMENT_ORDERS, { id: orderId });
  if (!data.order) throw new HttpError(404, `Shopify order ${send.shopifyOrderName ?? orderId} no longer exists.`, "order_missing");
  if (data.order.cancelledAt) throw new HttpError(409, `${data.order.name} is cancelled in Shopify.`, "order_cancelled");
  const open = data.order.fulfillmentOrders.nodes.filter(
    (fo) => fo.supportedActions.some((a) => a.action === "CREATE_FULFILLMENT")
  );
  const warnings = [];
  if (open.length) {
    const res = await shopify.graphql(
      FULFILLMENT_CREATE,
      {
        fulfillment: {
          lineItemsByFulfillmentOrder: open.map((fo) => ({ fulfillmentOrderId: fo.id })),
          trackingInfo: {
            number: input.trackingNumber,
            company: input.carrier,
            ...input.trackingUrl ? { url: input.trackingUrl } : {}
          },
          notifyCustomer: input.notifyCustomer ?? false
        }
      },
      { idempotent: false }
    );
    if (res.fulfillmentCreate.userErrors.length || !res.fulfillmentCreate.fulfillment) {
      throw new HttpError(
        422,
        `Shopify refused the fulfilment: ${res.fulfillmentCreate.userErrors.map((e) => e.message).join("; ")}`,
        "shopify_rejected"
      );
    }
    await syncTracking(deps, shopify, { sendIds: [send.id] });
  } else {
    warnings.push(`${data.order.name} is already fulfilled in Shopify, so the tracking number was saved in the hub only.`);
    const now = deps.now();
    const dispatchedAt = send.dispatchedAt ?? now.toISOString();
    const days = Number(deps.secret("POST_WINDOW_DAYS")) || DEFAULT_POST_WINDOW_DAYS;
    const update = {
      trackingNumber: input.trackingNumber,
      carrier: normaliseCarrier(input.carrier),
      trackingUrl: input.trackingUrl ?? null,
      dispatchedAt,
      postByDate: new Date(Date.parse(dispatchedAt) + days * 864e5).toISOString(),
      status: send.status === "preparing" ? "dispatched" : send.status,
      lastSyncedAt: now.toISOString()
    };
    await db.Send.update(send.id, update);
  }
  return { ok: true, send: await db.Send.get(send.id), warnings };
}

// src/lib/partner.ts
function social(accounts, platform) {
  const a = accounts.find((s) => s.platform === platform);
  if (!a) return null;
  return {
    handle: a.handle ?? null,
    url: a.profileUrl ?? (a.handle ? profileUrl(platform, a.handle) : null),
    followers: a.followers ?? null
  };
}
function profileUrl(platform, handle) {
  const h = handle.replace(/^@/, "");
  return platform === "tiktok" ? `https://www.tiktok.com/@${h}` : `https://www.instagram.com/${h}/`;
}
function sendView(s, username) {
  return {
    id: s.id,
    influencerId: s.influencerId,
    influencer: username ? `@${username}` : void 0,
    status: s.status,
    items: s.items ?? [],
    orderName: s.shopifyOrderName ?? null,
    orderId: s.shopifyOrderId ?? null,
    orderAdminUrl: s.shopifyOrderUrl ?? null,
    carrier: s.carrier ?? null,
    trackingNumber: s.trackingNumber ?? null,
    trackingUrl: s.trackingUrl ?? null,
    dispatchedAt: s.dispatchedAt ?? null,
    deliveredAt: s.deliveredAt ?? null,
    postByDate: s.postByDate ?? null,
    postedUrl: s.postedUrl ?? null,
    createdAt: s.created_date ?? null
  };
}
function interestView(i, products) {
  const p = products.get(i.productHandle);
  const v = p?.variants?.find((x) => x.variantId === i.variantId) ?? p?.variants?.find((x) => x.size === (i.size || "ONE") && x.stock > 0);
  return {
    productHandle: i.productHandle,
    productName: p?.name ?? null,
    size: i.size ?? null,
    variantId: v?.variantId ?? i.variantId ?? null,
    variantLabel: v?.label ?? null,
    stock: v?.stock ?? 0,
    flaggedAt: i.created_date ?? null
  };
}
async function loadWorld(deps) {
  const db = deps.base44.asServiceRole.entities;
  const [influencers, socials, interests, sends, codes, products] = await Promise.all([
    listAll(db.Influencer),
    listAll(db.SocialAccount),
    listAll(db.Interest),
    listAll(db.Send),
    listAll(db.AffiliateCode),
    listAll(db.Product, void 0, "name")
  ]);
  return { influencers, socials, interests, sends, codes, products: new Map(products.map((p) => [p.handle, p])) };
}
function influencerView(inf, w) {
  const mine = (xs) => xs.filter((x) => x.influencerId === inf.id);
  const accounts = mine(w.socials);
  const sends = mine(w.sends);
  const codes = mine(w.codes);
  const last = sends[0];
  return {
    id: inf.id,
    username: inf.username,
    status: inf.status ?? null,
    country: inf.country ?? null,
    joinedAt: inf.joinedAt ?? null,
    tiktok: social(accounts, "tiktok"),
    instagram: social(accounts, "instagram"),
    interests: mine(w.interests).map((i) => interestView(i, w.products)),
    affiliateCode: codes.find((c) => c.isPrimary)?.code ?? null,
    codeUses: codes.reduce((n, c) => n + (c.usageCount ?? 0), 0),
    sends: {
      total: sends.length,
      active: sends.filter((s) => ["preparing", "dispatched", "delivered", "overdue"].includes(s.status)).length,
      owesPost: sends.some((s) => ["dispatched", "delivered", "overdue"].includes(s.status)),
      last: last ? { orderName: last.shopifyOrderName ?? null, status: last.status, createdAt: last.created_date ?? null } : null
    }
  };
}
async function listInfluencers(deps, opts) {
  const w = await loadWorld(deps);
  let list = w.influencers.map((i) => influencerView(i, w));
  if (opts.status) list = list.filter((i) => i.status === opts.status);
  if (opts.hasInterests) list = list.filter((i) => i.interests.length > 0);
  if (opts.neverSent) list = list.filter((i) => i.sends.total === 0);
  return list;
}
async function getInfluencer(deps, opts) {
  const db = deps.base44.asServiceRole.entities;
  let inf;
  if (opts.influencerId) inf = await getOr404(db.Influencer, opts.influencerId, "Influencer");
  else if (opts.username) {
    inf = (await db.Influencer.filter({ username: opts.username.replace(/^@/, "").toLowerCase() }))[0];
  }
  if (!inf) throw new HttpError(404, "Influencer not found.", "not_found");
  const w = await loadWorld(deps);
  const addr = (await db.Address.filter({ influencerId: inf.id }))[0];
  const sizes = (await db.SizeProfile.filter({ influencerId: inf.id }))[0];
  return {
    ...influencerView(inf, w),
    email: inf.email,
    shipsTo: addr ? { city: addr.city ?? null, country: addr.country ?? null } : null,
    sizes: sizes ? { top: sizes.topSize ?? null, bottom: sizes.bottomSize ?? null } : null,
    sendHistory: w.sends.filter((s) => s.influencerId === inf.id).map((s) => sendView(s))
  };
}
async function listSends(deps, opts) {
  const db = deps.base44.asServiceRole.entities;
  const [sends, influencers] = await Promise.all([
    listAll(db.Send, opts.influencerId ? { influencerId: opts.influencerId } : void 0),
    listAll(db.Influencer)
  ]);
  const names = new Map(influencers.map((i) => [i.id, i.username]));
  return sends.filter((s) => !opts.status || s.status === opts.status).map((s) => sendView(s, names.get(s.influencerId)));
}
async function listProducts(deps) {
  const products = await listAll(deps.base44.asServiceRole.entities.Product, void 0, "name");
  return products.sort((a, b) => (a.sortOrder ?? 999) - (b.sortOrder ?? 999)).map((p) => ({
    handle: p.handle,
    name: p.name,
    type: p.type ?? null,
    availableToInfluencers: p.available !== false,
    shopifyStatus: p.shopifyStatus ?? null,
    syncedAt: p.syncedAt ?? null,
    variants: (p.variants ?? []).map((v) => ({ variantId: v.variantId, label: v.label, size: v.size, stock: v.stock }))
  }));
}
async function recordPost(deps, body) {
  const db = deps.base44.asServiceRole.entities;
  const sendId = typeof body.sendId === "string" ? body.sendId : "";
  const postedUrl = typeof body.postedUrl === "string" ? body.postedUrl.trim() : "";
  if (!/^https:\/\/\S+$/.test(postedUrl)) throw new HttpError(400, "postedUrl must be an https:// link to the post.", "bad_url");
  const send = await getOr404(db.Send, sendId, "Send");
  if (send.status === "cancelled") throw new HttpError(409, "This send was cancelled.", "send_cancelled");
  const updated = await db.Send.update(send.id, { postedUrl, postedAt: deps.now().toISOString(), status: "posted" });
  return sendView({ ...send, ...updated });
}

// src/lib/usage.ts
async function syncUsage(deps, shopify) {
  const db = deps.base44.asServiceRole.entities;
  const codes = await listAll(db.AffiliateCode);
  const summary = { codes: codes.length, updated: 0, notInShopify: [], errors: [] };
  for (const c of codes) {
    if (!c.code || !/^[A-Za-z0-9_-]+$/.test(c.code)) continue;
    try {
      const node = await shopify.graphql(
        DISCOUNT_USAGE,
        { code: c.code }
      );
      if (!node.codeDiscountNodeByCode) {
        summary.notInShopify.push(c.code);
        continue;
      }
      const usageCount = node.codeDiscountNodeByCode.codeDiscount?.asyncUsageCount ?? 0;
      let revenue = 0;
      let cursor = null;
      for (let page = 0; page < 20; page++) {
        const res = await shopify.graphql(DISCOUNT_ORDERS, { query: `discount_code:${c.code}`, cursor });
        for (const o of res.orders.nodes) {
          if (!o.cancelledAt && !o.test) revenue += Number(o.currentSubtotalPriceSet.shopMoney.amount) || 0;
        }
        if (!res.orders.pageInfo.hasNextPage) break;
        cursor = res.orders.pageInfo.endCursor;
      }
      const revenueGbp = Math.round(revenue * 100) / 100;
      if (c.usageCount !== usageCount || c.revenueGbp !== revenueGbp) {
        await db.AffiliateCode.update(c.id, { usageCount, revenueGbp });
        summary.updated++;
      }
    } catch (e) {
      summary.errors.push(`${c.code}: ${e.message}`);
    }
  }
  return summary;
}

// src/handlers/partnerApi.ts
var WRITE_ACTIONS = /* @__PURE__ */ new Set(["createSend", "markShipped", "recordPost"]);
var partnerApi = wrap(async (req, deps) => {
  if (req.method !== "POST") throw new HttpError(405, "POST a JSON body with an action.", "method_not_allowed");
  const body = await readJson(req);
  if (!hasPartnerKey(req, body, deps)) {
    throw new HttpError(401, "Missing or wrong X-Partner-Key header.", "unauthenticated");
  }
  const action = asString(body.action);
  const writesEnabled = deps.secret("PARTNER_API_ALLOW_WRITES") === "true";
  const isDryRun = action === "createSend" && body.dryRun === true;
  if (WRITE_ACTIONS.has(action) && !writesEnabled && !isDryRun) {
    throw new HttpError(
      403,
      `"${action}" changes orders or records, and Partner API writes are off. Set PARTNER_API_ALLOW_WRITES=true to allow it.`,
      "writes_disabled"
    );
  }
  const data = await runAction(action, body, deps, writesEnabled);
  return json({ ok: true, action, data });
});
async function runAction(action, body, deps, writesEnabled) {
  switch (action) {
    case "ping":
      return { app: "crooks-partner-hub", writesEnabled, time: deps.now().toISOString() };
    case "listInfluencers":
      return await listInfluencers(deps, {
        status: asString(body.status) || void 0,
        hasInterests: body.hasInterests === true,
        neverSent: body.neverSent === true
      });
    case "getInfluencer":
      return await getInfluencer(deps, {
        influencerId: asString(body.influencerId) || void 0,
        username: asString(body.username) || void 0
      });
    case "listSends":
      return await listSends(deps, {
        status: asString(body.status) || void 0,
        influencerId: asString(body.influencerId) || void 0
      });
    case "listProducts":
      return await listProducts(deps);
    case "checkStock": {
      const plan = await planSend(createShopify(deps), parseItems(body.items));
      return { sendable: plan.problems.length === 0, items: plan.items, stock: plan.stock, problems: plan.problems, warnings: plan.warnings };
    }
    case "createSend": {
      const influencerId = asString(body.influencerId);
      if (!influencerId) throw new HttpError(400, "Missing influencerId.", "bad_request");
      return await createSend(deps, createShopify(deps), {
        influencerId,
        items: parseItems(body.items),
        note: asString(body.note).slice(0, 500) || void 0,
        dryRun: body.dryRun === true,
        createdBy: "CLIVE (Partner API)"
      });
    }
    case "markShipped":
      return await markShipped(deps, createShopify(deps), parseMarkShipped(body));
    case "recordPost":
      return await recordPost(deps, body);
    case "syncTracking":
      return await syncTracking(deps, createShopify(deps));
    case "syncCatalog":
      return await syncCatalog(deps, createShopify(deps));
    case "syncUsage":
      return await syncUsage(deps, createShopify(deps));
    default:
      throw new HttpError(400, `Unknown action "${action}". See CLIVE_API.md for the list.`, "unknown_action");
  }
}

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

// src/functions/partnerApi.ts
serve(partnerApi);

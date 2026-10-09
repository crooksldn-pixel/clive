// CROOKS Partner Hub — Base44 function "shopifyCreateDiscount".
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

// src/lib/queries.ts
var DISCOUNT_BY_CODE = (
  /* GraphQL */
  `
query PartnerHubDiscountByCode($code: String!) {
  codeDiscountNodeByCode(code: $code) {
    id
    codeDiscount {
      __typename
      ... on DiscountCodeBasic {
        title
        status
        customerGets { value { __typename ... on DiscountPercentage { percentage } } }
      }
      ... on DiscountCodeBxgy {
        title
        status
        customerBuys { items { __typename ... on DiscountCollections { collections(first: 10) { nodes { id } } } } }
        customerGets { items { __typename ... on DiscountProducts { products(first: 20) { nodes { id } } productVariants(first: 20) { nodes { id } } } } }
      }
      ... on DiscountCodeFreeShipping { title status }
      ... on DiscountCodeApp { title status }
    }
  }
}`
);
var BXGY_CREATE = (
  /* GraphQL */
  `
mutation PartnerHubBxgyCreateV($input: DiscountCodeBxgyInput!) {
  discountCodeBxgyCreate(bxgyCodeDiscount: $input) { codeDiscountNode { id } userErrors { field message code } }
}`
);
var BXGY_UPDATE = (
  /* GraphQL */
  `
mutation PartnerHubBxgyUpdate($id: ID!, $input: DiscountCodeBxgyInput!) {
  discountCodeBxgyUpdate(id: $id, bxgyCodeDiscount: $input) { codeDiscountNode { id } userErrors { field message code } }
}`
);
var BASIC_CREATE = (
  /* GraphQL */
  `
mutation PartnerHubBasicCreateV($input: DiscountCodeBasicInput!) {
  discountCodeBasicCreate(basicCodeDiscount: $input) { codeDiscountNode { id } userErrors { field message code } }
}`
);
var BASIC_UPDATE = (
  /* GraphQL */
  `
mutation PartnerHubBasicUpdate($id: ID!, $input: DiscountCodeBasicInput!) {
  discountCodeBasicUpdate(id: $id, basicCodeDiscount: $input) { codeDiscountNode { id } userErrors { field message code } }
}`
);
var DISCOUNT_DELETE = (
  /* GraphQL */
  `
mutation PartnerHubDiscountDelete($id: ID!) {
  discountCodeDelete(id: $id) { deletedCodeDiscountId userErrors { field message code } }
}`
);
var DISCOUNT_ACTIVATE = (
  /* GraphQL */
  `
mutation PartnerHubDiscountActivate($id: ID!) {
  discountCodeActivate(id: $id) { codeDiscountNode { id } userErrors { field message code } }
}`
);
var DISCOUNT_DEACTIVATE = (
  /* GraphQL */
  `
mutation PartnerHubDiscountDeactivate($id: ID!) {
  discountCodeDeactivate(id: $id) { codeDiscountNode { id } userErrors { field message code } }
}`
);
var DISCOUNT_STATUSES = (
  /* GraphQL */
  `
query PartnerHubDiscountStatuses($ids: [ID!]!) {
  nodes(ids: $ids) {
    __typename
    ... on DiscountCodeNode {
      id
      codeDiscount { __typename ... on DiscountCodeBasic { status } ... on DiscountCodeBxgy { status } }
    }
  }
}`
);
var COLLECTION = (
  /* GraphQL */
  `
query PartnerHubCollection($id: ID!) {
  collection(id: $id) { id title }
}`
);
var APP_INSTALLATION = (
  /* GraphQL */
  `
query PartnerHubAppInstallation {
  currentAppInstallation { id }
}`
);
var GIFT_VARIANTS = (
  /* GraphQL */
  `
query PartnerHubGiftVariants($ids: [ID!]!) {
  nodes(ids: $ids) {
    __typename
    ... on ProductVariant { id title product { title handle productType } }
  }
}`
);
var METAFIELDS_SET = (
  /* GraphQL */
  `
mutation PartnerHubMetafieldsSet($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) { metafields { id key namespace } userErrors { field message code } }
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
function chunk(items, size) {
  const out = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

// src/lib/promotions.ts
var DISCOUNT_TYPES = ["free_socks", "percentage"];
var GIFT_LABEL = "MOTIONTEC socks";
var RULES_NAMESPACE = "creator_gift";
var RULES_KEY = "rules";
var COMBINES_WITH = { orderDiscounts: false, productDiscounts: false, shippingDiscounts: false };
function normaliseCode(v) {
  return typeof v === "string" ? v.toUpperCase().replace(/[^A-Z0-9]/g, "") : "";
}
function discountTitle(code) {
  return `SEEDING ${code}`;
}
function collectionGid(input) {
  if (typeof input === "number" && Number.isInteger(input) && input > 0) return `gid://shopify/Collection/${input}`;
  if (typeof input !== "string") return null;
  const s = input.trim();
  if (/^\d+$/.test(s)) return `gid://shopify/Collection/${s}`;
  if (/^gid:\/\/shopify\/Collection\/\d+$/.test(s)) return s;
  const m = s.match(/\/collections\/(\d+)(?:[/?#]|$)/);
  return m ? `gid://shopify/Collection/${m[1]}` : null;
}
function giftVariantNumbers(p) {
  const ids = (p.giftVariantIds ?? []).map((v) => String(v).trim().replace(/^gid:\/\/shopify\/ProductVariant\//, "")).filter((v) => /^\d+$/.test(v)).map(Number);
  if (!ids.length) {
    throw new HttpError(422, "The Creator socks promotion has no gift variants. Add them in the Promotions tab.", "promotion_incomplete");
  }
  return ids;
}
var variantGidOf = (n) => `gid://shopify/ProductVariant/${n}`;
async function activePromotion(deps) {
  const rows = await listAll(deps.base44.asServiceRole.entities.Promotion);
  const p = rows.find((r) => r.active === true) ?? rows[0];
  if (!p) {
    throw new HttpError(422, "Set up the Creator socks promotion in the Promotions tab first.", "no_promotion");
  }
  return p;
}
function bxgyInput(code, collection, variants, startsAt) {
  const products = { productVariantsToAdd: variants.add };
  if (variants.remove?.length) products.productVariantsToRemove = variants.remove;
  if (variants.removeProducts?.length) products.productsToRemove = variants.removeProducts;
  const collections = { add: collection.add };
  if (collection.remove?.length) collections.remove = collection.remove;
  return {
    title: discountTitle(code),
    code,
    ...startsAt ? { startsAt } : {},
    context: { all: "ALL" },
    appliesOncePerCustomer: true,
    usesPerOrderLimit: 1,
    combinesWith: COMBINES_WITH,
    customerBuys: { items: { collections }, value: { quantity: "1" } },
    customerGets: {
      items: { products },
      value: { discountOnQuantity: { quantity: "1", effect: { percentage: 1 } } }
    }
  };
}
function basicInput(code, percent, startsAt) {
  return {
    title: discountTitle(code),
    code,
    ...startsAt ? { startsAt } : {},
    context: { all: "ALL" },
    appliesOncePerCustomer: true,
    combinesWith: COMBINES_WITH,
    customerGets: { items: { all: true }, value: { percentage: percent / 100 } }
  };
}
async function findDiscount(shopify, code) {
  const res = await shopify.graphql(DISCOUNT_BY_CODE, { code });
  const n = res.codeDiscountNodeByCode;
  if (!n) return null;
  const d = n.codeDiscount ?? {};
  const kind = d.__typename === "DiscountCodeBasic" ? "basic" : d.__typename === "DiscountCodeBxgy" ? "bxgy" : "other";
  const buys = d.customerBuys?.items?.collections?.nodes ?? [];
  const gets = d.customerGets?.items ?? {};
  const pct = d.customerGets?.value?.percentage;
  return {
    id: n.id,
    kind,
    title: d.title ?? "",
    status: d.status ?? "",
    percentage: typeof pct === "number" ? pct : null,
    collections: buys.map((x) => x.id),
    variants: (gets.productVariants?.nodes ?? []).map((x) => x.id),
    products: (gets.products?.nodes ?? []).map((x) => x.id)
  };
}
function userErrorsOrThrow(errs, what) {
  if (errs?.length) {
    throw new HttpError(422, `Shopify refused the ${what}: ${errs.map((e) => e.message).join("; ")}`, "shopify_rejected", {
      userErrors: errs
    });
  }
}
async function createDiscount(shopify, kind, input) {
  const op = kind === "bxgy" ? BXGY_CREATE : BASIC_CREATE;
  const field = kind === "bxgy" ? "discountCodeBxgyCreate" : "discountCodeBasicCreate";
  const res = await shopify.graphql(
    op,
    { input },
    { idempotent: false }
  );
  userErrorsOrThrow(res[field].userErrors, "discount");
  const id = res[field].codeDiscountNode?.id;
  if (!id) throw new HttpError(502, "Shopify didn't return the new discount.", "shopify_rejected");
  return id;
}
async function updateDiscount(shopify, kind, id, input) {
  const op = kind === "bxgy" ? BXGY_UPDATE : BASIC_UPDATE;
  const field = kind === "bxgy" ? "discountCodeBxgyUpdate" : "discountCodeBasicUpdate";
  const res = await shopify.graphql(op, { id, input }, { idempotent: false });
  userErrorsOrThrow(res[field].userErrors, "discount update");
}
async function upsertDiscount(deps, shopify, o) {
  const code = normaliseCode(o.code);
  if (!code) throw new HttpError(400, "Missing code.", "bad_request");
  const want = o.type === "free_socks" ? "bxgy" : "basic";
  const value = o.type === "free_socks" ? 100 : o.value;
  let collection = "";
  let gifts = [];
  if (want === "bxgy") {
    if (!o.promotion) throw new HttpError(422, "Set up the Creator socks promotion first.", "no_promotion");
    const gid = collectionGid(o.promotion.qualifyingCollectionId);
    if (!gid) {
      throw new HttpError(
        422,
        "Free-socks codes need the qualifying collection. Create it in Shopify and paste its ID in the Promotions tab.",
        "no_collection"
      );
    }
    const found = await shopify.graphql(COLLECTION, { id: gid });
    if (!found.collection) {
      throw new HttpError(422, `The qualifying collection ${gid.split("/").pop()} isn't in Shopify. Check the ID in Promotions.`, "no_collection");
    }
    collection = gid;
    gifts = giftVariantNumbers(o.promotion).map(variantGidOf);
  } else if (!(value > 0 && value <= 100)) {
    throw new HttpError(400, "A percentage code needs a value from 1 to 100.", "bad_value");
  }
  const existing = await findDiscount(shopify, code);
  const ours = existing && (o.storedId && existing.id === o.storedId || existing.title === discountTitle(code));
  if (existing && !ours) {
    throw new HttpError(
      409,
      `Shopify already has a discount with the code ${code} that the Hub didn't make. Rename or delete it in Shopify, or pick another code.`,
      "code_taken_in_shopify"
    );
  }
  const now = deps.now().toISOString();
  const createInput = () => want === "bxgy" ? bxgyInput(code, { add: [collection] }, { add: gifts }, now) : basicInput(code, value, now);
  if (!existing) {
    return { discountId: await createDiscount(shopify, want, createInput()), type: o.type, value, action: "created" };
  }
  if (existing.kind === want) {
    const input = want === "bxgy" ? bxgyInput(
      code,
      { add: [collection], remove: existing.collections.filter((c) => c !== collection) },
      {
        add: gifts,
        remove: existing.variants.filter((v) => !gifts.includes(v)),
        removeProducts: existing.products
      }
    ) : basicInput(code, value);
    await updateDiscount(shopify, want, existing.id, input);
    return { discountId: existing.id, type: o.type, value, action: "updated" };
  }
  if (!o.override) {
    throw new HttpError(
      409,
      `${code} is already a different kind of discount in Shopify. Change its type with the admin override.`,
      "type_change_needs_override"
    );
  }
  const del = await shopify.graphql(
    DISCOUNT_DELETE,
    { id: existing.id },
    { idempotent: false }
  );
  userErrorsOrThrow(del.discountCodeDelete.userErrors, "removal of the old discount");
  try {
    return { discountId: await createDiscount(shopify, want, createInput()), type: o.type, value, action: "replaced" };
  } catch (e) {
    throw new HttpError(
      502,
      `The old ${code} discount was removed but the new one couldn't be created (${e.message}). ${code} is currently off in Shopify; try the override again.`,
      "code_off_in_shopify"
    );
  }
}
async function termsForInfluencer(shopify, influencer, theirCodes, newCode) {
  const previous = theirCodes.filter((c) => normaliseCode(c.code) !== newCode && c.shopifyDiscountId).sort((a, b) => (parseRecordDate(b.created_date) || 0) - (parseRecordDate(a.created_date) || 0));
  for (const p of previous) {
    const d = await findDiscount(shopify, normaliseCode(p.code));
    if (!d || d.title !== discountTitle(normaliseCode(p.code))) continue;
    if (d.kind === "bxgy") return { type: "free_socks", value: 100 };
    if (d.kind === "basic" && d.percentage) return { type: "percentage", value: Math.round(d.percentage * 1e4) / 100 };
  }
  return influencer.country === "GB" ? { type: "free_socks", value: 100 } : { type: "percentage", value: 15 };
}
function colourName(productTitle) {
  const head = productTitle.split(/MOTIONTEC/i)[0].trim() || productTitle.trim();
  return head.toLowerCase().split("/").map((w) => w.trim().replace(/(^|[\s-])([a-z])/g, (_m, a, b) => a + b.toUpperCase())).join("/");
}
async function syncPromotions(deps, shopify) {
  const db = deps.base44.asServiceRole.entities;
  const promotion = await activePromotion(deps);
  const variantIds = giftVariantNumbers(promotion);
  const [codes, influencers] = await Promise.all([listAll(db.AffiliateCode), listAll(db.Influencer)]);
  const infById = new Map(influencers.map((i) => [i.id, i]));
  const withDiscount = codes.filter((c) => c.shopifyDiscountId);
  const statuses = /* @__PURE__ */ new Map();
  for (const ids of chunk([...new Set(withDiscount.map((c) => c.shopifyDiscountId))], 50)) {
    const res = await shopify.graphql(
      DISCOUNT_STATUSES,
      { ids }
    );
    for (const n of res.nodes) if (n?.__typename === "DiscountCodeNode") statuses.set(n.id, n.codeDiscount?.status ?? "");
  }
  const activated = [];
  const deactivated = [];
  const missingInShopify = [];
  const live = [];
  for (const c of withDiscount) {
    const status = statuses.get(c.shopifyDiscountId);
    if (status === void 0) {
      missingInShopify.push(normaliseCode(c.code));
      continue;
    }
    const inf = infById.get(c.influencerId);
    const wanted = inf?.status === "active" && (c.type !== "free_socks" || promotion.active !== false);
    if (wanted && status === "EXPIRED") {
      const r = await shopify.graphql(
        DISCOUNT_ACTIVATE,
        { id: c.shopifyDiscountId },
        { idempotent: false }
      );
      userErrorsOrThrow(r.discountCodeActivate.userErrors, `reactivation of ${c.code}`);
      activated.push(normaliseCode(c.code));
    } else if (!wanted && (status === "ACTIVE" || status === "SCHEDULED")) {
      const r = await shopify.graphql(
        DISCOUNT_DEACTIVATE,
        { id: c.shopifyDiscountId },
        { idempotent: false }
      );
      userErrorsOrThrow(r.discountCodeDeactivate.userErrors, `pause of ${c.code}`);
      deactivated.push(normaliseCode(c.code));
    }
    if (wanted) live.push(c);
  }
  const ruleCodes = [...new Set(live.filter((c) => c.type === "free_socks").map((c) => normaliseCode(c.code)).filter(Boolean))].sort();
  const gv = await shopify.graphql(GIFT_VARIANTS, { ids: variantIds.map(variantGidOf) });
  const variants = variantIds.map((id) => {
    const n = gv.nodes.find((x) => x?.__typename === "ProductVariant" && x.id === variantGidOf(id));
    return { id, handle: n?.product.handle ?? null, name: n ? colourName(n.product.title) : null };
  });
  const updatedAt = deps.now().toISOString();
  const rules = {
    v: 1,
    gift: {
      variantIds,
      excludeProductTypes: promotion.excludeProductTypes?.length ? promotion.excludeProductTypes : ["Socks"],
      label: GIFT_LABEL,
      variants
    },
    codes: ruleCodes,
    updatedAt
  };
  const inst = await shopify.graphql(APP_INSTALLATION);
  const set = await shopify.graphql(METAFIELDS_SET, {
    metafields: [{
      ownerId: inst.currentAppInstallation.id,
      namespace: RULES_NAMESPACE,
      key: RULES_KEY,
      type: "json",
      value: JSON.stringify(rules)
    }]
  });
  userErrorsOrThrow(set.metafieldsSet.userErrors, "gift rules");
  return {
    ok: true,
    codes: ruleCodes,
    updatedAt,
    activated,
    deactivated,
    missingInShopify,
    metafieldId: set.metafieldsSet.metafields?.[0]?.id ?? null,
    rules
  };
}

// src/handlers/shopifyCreateDiscount.ts
var shopifyCreateDiscount = wrap(async (req, deps) => {
  const body = await readJson(req);
  const user = await currentUser(deps);
  if (!user) throw new HttpError(401, "Sign in first.", "unauthenticated");
  const code = normaliseCode(body.code);
  if (!code) throw new HttpError(400, "Missing code.", "bad_request");
  const db = deps.base44.asServiceRole.entities;
  const shopify = createShopify(deps);
  const records = (await db.AffiliateCode.filter({ code })).sort(
    (a, b) => (parseRecordDate(b.created_date) || 0) - (parseRecordDate(a.created_date) || 0)
  );
  let record;
  let result;
  if (body.override === true) {
    if (user.role !== "admin") throw new HttpError(403, "Only Partner Hub admins can override a code.", "forbidden");
    const type = asString(body.type);
    if (!DISCOUNT_TYPES.includes(type)) throw new HttpError(400, `type must be one of ${DISCOUNT_TYPES.join(", ")}.`, "bad_type");
    const influencerId = asString(body.influencerId);
    record = records.find((r) => r.influencerId === influencerId) ?? records[0];
    if (!record) throw new HttpError(404, `The Hub has no code ${code}.`, "not_found");
    result = await upsertDiscount(deps, shopify, {
      code,
      type,
      value: Number(body.value),
      promotion: type === "free_socks" ? await activePromotion(deps) : void 0,
      storedId: record.shopifyDiscountId,
      override: true
    });
  } else {
    if (user.role === "admin") {
      record = records[0];
    } else {
      const mine = (await db.Influencer.filter({ email: user.email }))[0];
      record = mine ? records.find((r) => r.influencerId === mine.id) : void 0;
    }
    if (!record) throw new HttpError(404, `No code ${code} belongs to you in the Hub.`, "not_found");
    const owner = await getOr404(db.Influencer, record.influencerId, "Influencer");
    if (owner.status === "blocked") throw new HttpError(409, "This account is blocked.", "influencer_blocked");
    if (records.some((r) => r.influencerId !== owner.id && r.shopifyDiscountId)) {
      throw new HttpError(409, `${code} is already someone else's code.`, "code_taken");
    }
    const terms = await termsForInfluencer(
      shopify,
      owner,
      await listAll(db.AffiliateCode, { influencerId: owner.id }),
      code
    );
    result = await upsertDiscount(deps, shopify, {
      code,
      type: terms.type,
      value: terms.value,
      promotion: terms.type === "free_socks" ? await activePromotion(deps) : void 0,
      storedId: record.shopifyDiscountId,
      override: false
    });
  }
  await db.AffiliateCode.update(record.id, { shopifyDiscountId: result.discountId, type: result.type, value: result.value });
  const warnings = [];
  try {
    await syncPromotions(deps, shopify);
  } catch (e) {
    warnings.push(`The discount is set, but the gift rules weren't refreshed: ${e.message}`);
  }
  return json({ ok: true, discountId: result.discountId, type: result.type, value: result.value, action: result.action, warnings });
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

// src/functions/shopifyCreateDiscount.ts
serve(shopifyCreateDiscount);

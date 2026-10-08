// End-to-end smoke test of the BUILT functions (base44/functions/*/entry.ts)
// under Deno with the real @base44/sdk: a local stand-in for the Base44 API
// serves entity requests, and Shopify calls are answered by a fake. Proves the
// bundles load, the SDK is used correctly (service-role entity calls, user
// auth), and the main flows work end to end.
//
//   npm run build && npm run smoke

type Row = Record<string, unknown> & { id: string };

const realServe = Deno.serve.bind(Deno);
const realFetch = globalThis.fetch.bind(globalThis);
const failures: string[] = [];
const check = (ok: unknown, label: string) => {
  console.log(`${ok ? "  ok  " : "  FAIL"} ${label}`);
  if (!ok) failures.push(label);
};

// ---------- stand-in Base44 API ----------
const USER_TOKEN = "user-jwt";
const SERVICE_TOKEN = "service-jwt";
let seq = 0;
const db: Record<string, Row[]> = {
  Influencer: [{ id: "inf1", email: "maya@example.com", username: "maya.fits", status: "active", country: "GB" }],
  Address: [{ id: "a1", influencerId: "inf1", fullName: "Maya Okafor", line1: "12 Brick Lane", city: "London", postcode: "E1 6RF", country: "GB" }],
  SocialAccount: [{ id: "s1", influencerId: "inf1", platform: "tiktok", handle: "maya.fits", profileUrl: "https://www.tiktok.com/@maya.fits" }],
  Interest: [{ id: "i1", influencerId: "inf1", productHandle: "cb1-wash-jeans", size: "M" }],
  SizeProfile: [],
  Send: [],
  AffiliateCode: [],
  Product: [{ id: "p1", handle: "cb1-wash-jeans", name: "GREY WASH YARD JEANS", available: true, sortOrder: 10, variants: [{ variantId: "gid://shopify/ProductVariant/53639819231575", label: "XS", size: "XS", stock: 21 }] }],
};
const entityAuth: { entity: string; method: string; auth: string | null }[] = [];

const api = realServe({ port: 0, hostname: "127.0.0.1", onListen() {} }, async (req) => {
  const url = new URL(req.url);
  const m = url.pathname.match(/^\/api\/apps\/([^/]+)\/entities\/([^/]+)(?:\/([^/]+))?$/);
  if (!m) return Response.json({}, { status: 200 });
  const [, , entity, id] = m;
  const auth = req.headers.get("authorization");
  if (entity === "User" && id === "me") {
    return auth === `Bearer ${USER_TOKEN}`
      ? Response.json({ id: "u1", email: "owner@example.com", role: "admin" })
      : Response.json({ detail: "unauthenticated" }, { status: 401 });
  }
  entityAuth.push({ entity, method: req.method, auth });
  const rows = (db[entity] ??= []);
  if (req.method === "GET" && !id) {
    const q = url.searchParams.get("q");
    const query = q ? JSON.parse(q) : {};
    const limit = Number(url.searchParams.get("limit") ?? 50);
    const skip = Number(url.searchParams.get("skip") ?? 0);
    const hit = rows.filter((r) => Object.entries(query).every(([k, v]) => r[k] === v));
    return Response.json(hit.slice(skip, skip + limit));
  }
  if (req.method === "GET") {
    const r = rows.find((x) => x.id === id);
    return r ? Response.json(r) : Response.json({ detail: "not found" }, { status: 404 });
  }
  if (req.method === "POST") {
    const row = { ...(await req.json()), id: `rec${++seq}`, created_date: new Date().toISOString().replace("Z", "000") };
    rows.push(row);
    return Response.json(row);
  }
  if (req.method === "PUT") {
    const i = rows.findIndex((x) => x.id === id);
    if (i < 0) return Response.json({ detail: "not found" }, { status: 404 });
    rows[i] = { ...rows[i], ...(await req.json()) };
    return Response.json(rows[i]);
  }
  if (req.method === "DELETE") {
    db[entity] = rows.filter((x) => x.id !== id);
    return Response.json({ success: true });
  }
  return Response.json({ detail: "unsupported" }, { status: 405 });
});
const apiUrl = `http://127.0.0.1:${(api.addr as Deno.NetAddr).port}`;

// ---------- fake Shopify ----------
const shopifyOps: string[] = [];
const fixtures = JSON.parse(await Deno.readTextFile(new URL("../test/fixtures/variants-for-send.json", import.meta.url)));
const tracking = JSON.parse(await Deno.readTextFile(new URL("../test/fixtures/orders-tracking.json", import.meta.url)));
const catalog = JSON.parse(await Deno.readTextFile(new URL("../test/fixtures/catalog-live.json", import.meta.url)));
let createdOrderId = "";

globalThis.fetch = async (input: string | URL | Request, init?: RequestInit) => {
  const url = input instanceof Request ? input.url : String(input);
  if (!url.includes(".myshopify.com")) return realFetch(input, init);
  if (url.endsWith("/admin/oauth/access_token")) {
    return Response.json({ access_token: "shpat_smoke", expires_in: 86399 });
  }
  const body = JSON.parse(String(init?.body));
  const op = /(PartnerHub\w+)/.exec(body.query)?.[1] ?? "?";
  shopifyOps.push(op);
  switch (op) {
    case "PartnerHubVariantsForSend":
      return Response.json({ data: { nodes: body.variables.ids.map((id: string) => fixtures.data.nodes.find((n: any) => n?.id === id) ?? null) } });
    case "PartnerHubOrderCreate":
      createdOrderId = "gid://shopify/Order/8400000000042";
      return Response.json({ data: { orderCreate: { order: { id: createdOrderId, name: "CROOKS-2242" }, userErrors: [] } } });
    case "PartnerHubOrdersTracking":
      return Response.json({ data: { nodes: body.variables.ids.map((id: string) => (id === createdOrderId ? { ...tracking.royalMail, id, name: "CROOKS-2242" } : null)) } });
    case "PartnerHubCatalog":
      return Response.json({ data: { products: { pageInfo: { hasNextPage: false, endCursor: null }, nodes: catalog.products } } });
    default:
      return Response.json({ errors: [{ message: `smoke: no fake for ${op}` }] });
  }
};

// ---------- load built functions ----------
const secrets: Record<string, string> = {
  SHOPIFY_CLIENT_ID: "smoke-id",
  SHOPIFY_CLIENT_SECRET: "smoke-secret",
  PARTNER_API_KEY: "smoke-partner-key-0123456789abcdef",
};
for (const [k, v] of Object.entries(secrets)) Deno.env.set(k, v);

async function load(name: string): Promise<(req: Request) => Promise<Response>> {
  let captured: ((req: Request) => Promise<Response>) | undefined;
  Object.defineProperty(Deno, "serve", {
    value: (h: (req: Request) => Promise<Response>) => {
      captured = h;
      return {};
    },
    configurable: true,
    writable: true,
  });
  await import(new URL(`../base44/functions/${name}/entry.ts`, import.meta.url).href);
  Object.defineProperty(Deno, "serve", { value: realServe, configurable: true, writable: true });
  if (!captured) throw new Error(`${name} did not call Deno.serve`);
  return captured;
}

function invoke(fn: (req: Request) => Promise<Response>, body: unknown, headers: Record<string, string> = {}) {
  return fn(new Request("https://crooks-partner-hub.base44.app/api/apps/app1/functions/x", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "Base44-App-Id": "app1",
      "Base44-Api-Url": apiUrl,
      "Base44-Service-Authorization": `Bearer ${SERVICE_TOKEN}`,
      ...headers,
    },
    body: JSON.stringify(body),
  }));
}
const asAdmin = { Authorization: `Bearer ${USER_TOKEN}` };

try {
  console.log("shopifyCreateSend");
  const createSend = await load("shopifyCreateSend");
  const denied = await invoke(createSend, { influencerId: "inf1", items: [{ variantId: fixtures.ids[0] }] });
  check(denied.status === 401, "refuses a caller who isn't signed in");
  const res = await invoke(createSend, { influencerId: "inf1", items: [{ name: "GREY CONVICT SWEATS", size: "XS", variantId: fixtures.ids[0] }] }, asAdmin);
  const out = await res.json();
  check(res.status === 200 && out.orderName === "CROOKS-2242", `creates the order (${res.status} ${out.orderName ?? out.error})`);
  check(db.Send.length === 1 && db.Send[0].shopifyOrderName === "CROOKS-2242", "records the send in Base44");
  const sold = await invoke(createSend, { influencerId: "inf1", items: [{ variantId: fixtures.ids[3] }] }, asAdmin);
  check(sold.status === 409 && /0 in stock/.test((await sold.json()).error), "blocks a sold-out item");
  check(
    entityAuth.filter((c) => c.entity !== "User").every((c) => c.auth === `Bearer ${SERVICE_TOKEN}`),
    "every entity call used the service role",
  );

  console.log("shopifySyncTracking");
  const syncTracking = await load("shopifySyncTracking");
  const t = await (await invoke(syncTracking, {}, asAdmin)).json();
  check(t.updated === 1 && db.Send[0].trackingNumber === "VU000000001GB", `picks up the Royal Mail tracking number (${JSON.stringify(t.statuses ?? t.error)})`);

  console.log("shopifySyncCatalog");
  const syncCatalog = await load("shopifySyncCatalog");
  const c = await (await invoke(syncCatalog, {}, asAdmin)).json();
  check(c.products === 25, `reads the catalogue (${c.products ?? c.error})`);
  check(db.Interest[0].productHandle === "grey-wash-yard-jeans", "moves picks off the renamed handle");
  check(db.Product.find((p) => p.id === "p1")?.sortOrder === 10, "keeps the admin's ordering");

  console.log("partnerApi");
  const partner = await load("partnerApi");
  const noKey = await invoke(partner, { action: "ping" });
  check(noKey.status === 401, "refuses calls without the key");
  const list = await (await invoke(partner, { action: "listInfluencers" }, { "X-Partner-Key": secrets.PARTNER_API_KEY })).json();
  check(list.ok && list.data[0].tiktok.url === "https://www.tiktok.com/@maya.fits", "lists influencers with their TikTok link");
  const write = await invoke(partner, { action: "recordPost", sendId: db.Send[0].id, postedUrl: "https://www.tiktok.com/@maya.fits/video/1" }, { "X-Partner-Key": secrets.PARTNER_API_KEY });
  check(write.status === 403, "keeps writes off by default");

  console.log("shopifyWebhook / portalCheckAvailable / shopifyCheckConnection / sendMarkShipped / shopifySyncUsage");
  for (const name of ["shopifyWebhook", "portalCheckAvailable", "shopifyCheckConnection", "sendMarkShipped", "shopifySyncUsage"]) {
    const fn = await load(name);
    const r = await invoke(fn, {});
    check([400, 401, 403].includes(r.status), `${name} loads and rejects an empty/unauthenticated call (${r.status})`);
  }
  console.log(`\nShopify operations called: ${[...new Set(shopifyOps)].join(", ")}`);
} finally {
  await api.shutdown();
}

if (failures.length) {
  console.error(`\n${failures.length} smoke check(s) failed`);
  Deno.exit(1);
}
console.log("\nall smoke checks passed");
Deno.exit(0);

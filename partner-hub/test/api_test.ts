import { assert, assertEquals, assertMatch } from "jsr:@std/assert@1.0.13";
import { partnerApi } from "../src/handlers/partnerApi.ts";
import { shopifyWebhook } from "../src/handlers/shopifyWebhook.ts";
import { portalCheckAvailable } from "../src/handlers/portalCheckAvailable.ts";
import { shopifyCheckConnection } from "../src/handlers/shopifyCheckConnection.ts";
import { ADMIN, fakeBase44, FakeShopify, fixture, INFLUENCER_USER, makeDeps, post, readBody } from "./fakes.ts";

const KEY = "pk_" + "a".repeat(40);
const live = await fixture("orders-tracking.json");
const variants = await fixture("variants-for-send.json");

function seeded() {
  const { base44, entities } = fakeBase44(null, {
    Influencer: [
      { email: "maya@example.com", username: "maya.fits", status: "active", country: "GB", joinedAt: "2026-09-02T10:00:00Z" },
      { email: "dre@example.com", username: "dre", status: "pending", country: "US" },
    ],
    Product: [{
      handle: "v2-baggies", name: "GREY CONVICT SWEATS", available: true,
      variants: [{ variantId: "gid://shopify/ProductVariant/53075854197079", label: "XS", size: "XS", stock: 79 }],
    }],
  });
  const [maya, dre] = entities.Influencer.rows;
  entities.SocialAccount.rows.push(
    { id: "s1", influencerId: maya.id, platform: "tiktok", handle: "maya.fits", profileUrl: "https://www.tiktok.com/@maya.fits", followers: 12400 },
    { id: "s2", influencerId: maya.id, platform: "instagram", handle: "mayafits", profileUrl: "https://www.instagram.com/mayafits" },
    { id: "s3", influencerId: dre.id, platform: "tiktok", handle: "dre" },
  );
  entities.Interest.rows.push({ id: "i1", influencerId: maya.id, productHandle: "v2-baggies", size: "XS" });
  entities.Address.rows.push({ id: "a1", influencerId: maya.id, fullName: "Maya Okafor", line1: "12 Brick Lane", city: "London", postcode: "E1 6RF", country: "GB" });
  entities.Send.rows.push({ id: "send1", influencerId: maya.id, status: "dispatched", shopifyOrderName: "CROOKS-9001", trackingNumber: "VU000000001GB", carrier: "Royal Mail" });
  return { base44, entities, maya, dre };
}

const call = (body: unknown, key: string | null = KEY) => post(body, key ? { "x-partner-key": key } : {});

Deno.test("partner API: wrong, missing, or too-short keys are refused", async () => {
  const { base44 } = seeded();
  assertEquals((await partnerApi(call({ action: "ping" }, null), makeDeps({ base44, secrets: { PARTNER_API_KEY: KEY } }))).status, 401);
  assertEquals((await partnerApi(call({ action: "ping" }, KEY + "x"), makeDeps({ base44, secrets: { PARTNER_API_KEY: KEY } }))).status, 401);
  // A weak key configured in Base44 disables the API rather than accepting it
  assertEquals((await partnerApi(call({ action: "ping" }, "short"), makeDeps({ base44, secrets: { PARTNER_API_KEY: "short" } }))).status, 401);
  const ok = await partnerApi(call({ action: "ping" }), makeDeps({ base44, secrets: { PARTNER_API_KEY: KEY } }));
  assertEquals(ok.status, 200);
  assertEquals((await readBody(ok)).data.writesEnabled, false);
});

Deno.test("partner API: influencers come with clickable TikTok/Instagram links, picks and send status, no street address", async () => {
  const { base44 } = seeded();
  const body = await readBody(await partnerApi(call({ action: "listInfluencers" }), makeDeps({ base44, secrets: { PARTNER_API_KEY: KEY } })));
  const maya = body.data.find((i: any) => i.username === "maya.fits");
  assertEquals(maya.tiktok, { handle: "maya.fits", url: "https://www.tiktok.com/@maya.fits", followers: 12400 });
  assertEquals(maya.instagram.url, "https://www.instagram.com/mayafits");
  assertEquals(maya.interests[0].productName, "GREY CONVICT SWEATS");
  assertEquals(maya.interests[0].variantId, "gid://shopify/ProductVariant/53075854197079");
  assertEquals(maya.sends.owesPost, true);
  const dre = body.data.find((i: any) => i.username === "dre");
  assertEquals(dre.tiktok.url, "https://www.tiktok.com/@dre"); // built from the handle when no URL was saved
  assertEquals(dre.instagram, null);
  assert(!JSON.stringify(body).includes("Brick Lane"));
  assert(!JSON.stringify(body).includes("maya@example.com"));

  const filtered = await readBody(await partnerApi(call({ action: "listInfluencers", neverSent: true }), makeDeps({ base44, secrets: { PARTNER_API_KEY: KEY } })));
  assertEquals(filtered.data.map((i: any) => i.username), ["dre"]);
});

Deno.test("partner API: getInfluencer by username includes send history and city/country only", async () => {
  const { base44 } = seeded();
  const body = await readBody(await partnerApi(call({ action: "getInfluencer", username: "@maya.fits" }), makeDeps({ base44, secrets: { PARTNER_API_KEY: KEY } })));
  assertEquals(body.data.shipsTo, { city: "London", country: "GB" });
  assertEquals(body.data.sendHistory[0].trackingNumber, "VU000000001GB");
});

Deno.test("partner API: writes are off unless PARTNER_API_ALLOW_WRITES=true; dry runs are always allowed", async () => {
  const { base44, maya } = seeded();
  const shopify = new FakeShopify().on("PartnerHubVariantsForSend", (v) => ({
    data: { nodes: v.ids.map((id: string) => variants.data.nodes.find((n: any) => n?.id === id) ?? null) },
  }));
  const items = [{ variantId: "gid://shopify/ProductVariant/53075854197079" }];
  const off = await partnerApi(call({ action: "createSend", influencerId: maya.id, items }), makeDeps({ base44, shopify, secrets: { PARTNER_API_KEY: KEY } }));
  assertEquals(off.status, 403);
  assertMatch((await readBody(off)).error, /PARTNER_API_ALLOW_WRITES/);
  const dry = await partnerApi(call({ action: "createSend", influencerId: maya.id, items, dryRun: true }), makeDeps({ base44, shopify, secrets: { PARTNER_API_KEY: KEY } }));
  assertEquals(dry.status, 200);
  assertEquals((await readBody(dry)).data.dryRun, true);
  const recordPost = await partnerApi(call({ action: "recordPost", sendId: "send1", postedUrl: "https://www.tiktok.com/@maya.fits/video/1" }), makeDeps({ base44, secrets: { PARTNER_API_KEY: KEY } }));
  assertEquals(recordPost.status, 403);
});

Deno.test("partner API: with writes on, CLIVE can record a post and create a send", async () => {
  const { base44, entities, maya } = seeded();
  const secrets = { PARTNER_API_KEY: KEY, PARTNER_API_ALLOW_WRITES: "true" };
  const posted = await readBody(await partnerApi(call({ action: "recordPost", sendId: "send1", postedUrl: "https://www.tiktok.com/@maya.fits/video/1" }), makeDeps({ base44, secrets })));
  assertEquals(posted.data.status, "posted");
  assertEquals(entities.Send.rows.find((s) => s.id === "send1")!.postedUrl, "https://www.tiktok.com/@maya.fits/video/1");

  const shopify = new FakeShopify()
    .on("PartnerHubVariantsForSend", (v) => ({ data: { nodes: v.ids.map((id: string) => variants.data.nodes.find((n: any) => n?.id === id) ?? null) } }))
    .on("PartnerHubOrderCreate", () => ({ data: { orderCreate: { order: { id: "gid://shopify/Order/9", name: "CROOKS-2301" }, userErrors: [] } } }));
  const created = await readBody(await partnerApi(call({ action: "createSend", influencerId: maya.id, items: [{ variantId: "53075854197079" }] }), makeDeps({ base44, shopify, secrets })));
  assertEquals(created.data.orderName, "CROOKS-2301");
  const { order } = shopify.calls.find((c) => c.op === "PartnerHubOrderCreate")!.variables;
  assertMatch(order.note, /by CLIVE \(Partner API\)/);
});

Deno.test("partner API: checkStock reports per-piece stock without an influencer", async () => {
  const { base44 } = seeded();
  const shopify = new FakeShopify().on("PartnerHubVariantsForSend", (v) => ({
    data: { nodes: v.ids.map((id: string) => variants.data.nodes.find((n: any) => n?.id === id) ?? null) },
  }));
  const body = await readBody(await partnerApi(call({ action: "checkStock", items: [{ variantId: variants.ids[1] }, { variantId: variants.ids[3] }] }), makeDeps({ base44, shopify, secrets: { PARTNER_API_KEY: KEY } })));
  assertEquals(body.data.sendable, false);
  assertEquals(body.data.problems.map((p: any) => p.code), ["out_of_stock"]);
  assertEquals(body.data.stock.length, 3);
});

Deno.test("partner API: unknown actions are named", async () => {
  const { base44 } = seeded();
  const res = await partnerApi(call({ action: "deleteEverything" }), makeDeps({ base44, secrets: { PARTNER_API_KEY: KEY } }));
  assertEquals(res.status, 400);
  assertMatch((await readBody(res)).error, /Unknown action "deleteEverything"/);
});

async function sign(body: string, secret: string) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body)));
  return btoa(String.fromCharCode(...sig));
}

function webhook(body: string, headers: Record<string, string>) {
  return new Request("https://x/api/apps/x/functions/shopifyWebhook", { method: "POST", body, headers: { "content-type": "application/json", ...headers } });
}

Deno.test("webhook: a signed fulfilment for a seeding order updates its send", async () => {
  const { base44, entities } = fakeBase44(null, {
    Send: [{ influencerId: "inf1", status: "preparing", shopifyOrderId: live.royalMail.id, shopifyOrderName: "CROOKS-9001" }],
  });
  const shopify = new FakeShopify().on("PartnerHubOrdersTracking", () => ({ data: { nodes: [live.royalMail] } }));
  const raw = JSON.stringify({ id: 7600000000001, order_id: 8300000000001, tracking_number: "VU000000001GB" });
  const res = await shopifyWebhook(
    webhook(raw, {
      "x-shopify-hmac-sha256": await sign(raw, "client-secret"),
      "x-shopify-topic": "fulfillments/create",
      "x-shopify-shop-domain": "5wn03t-nm.myshopify.com",
    }),
    makeDeps({ base44, shopify }),
  );
  const body = await readBody(res);
  assertEquals(res.status, 200, JSON.stringify(body));
  assertEquals(body.updated, 1);
  assertEquals(entities.Send.rows[0].trackingNumber, "VU000000001GB");
  assertEquals(entities.Send.rows[0].status, "dispatched");
});

Deno.test("webhook: orders that aren't seeding orders are ignored without calling Shopify", async () => {
  const { base44 } = fakeBase44(null, {});
  const shopify = new FakeShopify();
  const raw = JSON.stringify({ id: 1, admin_graphql_api_id: "gid://shopify/Order/1" });
  const res = await shopifyWebhook(webhook(raw, { "x-shopify-hmac-sha256": await sign(raw, "client-secret"), "x-shopify-topic": "orders/cancelled" }), makeDeps({ base44, shopify }));
  assertEquals((await readBody(res)).ignored, "not a seeding order");
  assertEquals(shopify.calls.length, 0);
});

Deno.test("webhook: unsigned or tampered requests are rejected", async () => {
  const { base44 } = fakeBase44(null, {});
  const raw = JSON.stringify({ order_id: 1 });
  const sig = await sign(raw, "client-secret");
  assertEquals((await shopifyWebhook(webhook(raw, {}), makeDeps({ base44 }))).status, 401);
  assertEquals((await shopifyWebhook(webhook(raw + " ", { "x-shopify-hmac-sha256": sig }), makeDeps({ base44 }))).status, 401);
  assertEquals((await shopifyWebhook(webhook(raw, { "x-shopify-hmac-sha256": await sign(raw, "other") }), makeDeps({ base44 }))).status, 401);
  // A dedicated webhook secret (older custom apps) takes precedence
  const ok = await shopifyWebhook(
    webhook(raw, { "x-shopify-hmac-sha256": await sign(raw, "whsec"), "x-shopify-topic": "fulfillments/update" }),
    makeDeps({ base44, secrets: { SHOPIFY_WEBHOOK_SECRET: "whsec" } }),
  );
  assertEquals(ok.status, 200);
});

Deno.test("portal: username and code checks work for signed-in influencers only", async () => {
  const { base44, entities } = fakeBase44(INFLUENCER_USER, {
    Influencer: [{ email: "someone@else.com", username: "taken" }, { email: INFLUENCER_USER.email, username: "maya.fits" }],
  });
  const [other, me] = entities.Influencer.rows;
  entities.AffiliateCode.rows.push({ id: "c1", influencerId: other.id, code: "TAKEN" }, { id: "c2", influencerId: me.id, code: "MAYA" });
  const ask = async (body: unknown) => readBody(await portalCheckAvailable(post(body), makeDeps({ base44 })));
  assertEquals((await ask({ username: "Taken" })).available, false);
  assertEquals((await ask({ username: "maya.fits" })).available, true); // their own
  assertEquals((await ask({ username: "new.name" })).available, true);
  assertEquals(await ask({ code: "taken" }), { available: false, code: "TAKEN", suggestion: "TAKEN2" });
  assertEquals((await ask({ code: "MAYA" })).available, true);
  base44.auth.me = async () => null;
  assertEquals((await portalCheckAvailable(post({ username: "x" }), makeDeps({ base44 }))).status, 401);
});

Deno.test("connection check reports missing scopes and registers webhooks at the function URL", async () => {
  const { base44 } = fakeBase44(ADMIN, {});
  const shopify = new FakeShopify()
    .on("PartnerHubShopCheck", () => ({
      data: {
        shop: { name: "CROOKSLDN", myshopifyDomain: "5wn03t-nm.myshopify.com", currencyCode: "GBP" },
        currentAppInstallation: { accessScopes: [{ handle: "read_products" }, { handle: "write_orders" }, { handle: "read_inventory" }] },
        locations: { nodes: [{ id: "gid://shopify/Location/119717593431", name: "Shop location", isActive: true, fulfillsOnlineOrders: true }] },
      },
    }))
    .on("PartnerHubWebhooks", () => ({ data: { webhookSubscriptions: { nodes: [] } } }))
    .on("PartnerHubWebhookCreate", () => ({ data: { webhookSubscriptionCreate: { webhookSubscription: { id: "w" }, userErrors: [] } } }));
  const body = await readBody(await shopifyCheckConnection(post({ registerWebhooks: true }), makeDeps({ base44, shopify })));
  assertEquals(body.ok, false);
  assertEquals(body.scopes.missing.map((m: any) => m.scope), ["write_merchant_managed_fulfillment_orders", "write_discounts"]);
  assertEquals(body.webhookUrl, "https://crooks-partner-hub.base44.app/api/apps/6a96ee08b3aefa8357c55ed7/functions/shopifyWebhook");
  assertEquals(body.webhooks.map((w: any) => w.status), ["created", "created", "created"]);
  const created = shopify.calls.filter((c) => c.op === "PartnerHubWebhookCreate").map((c) => c.variables.topic);
  assertEquals(created, ["FULFILLMENTS_CREATE", "FULFILLMENTS_UPDATE", "ORDERS_CANCELLED"]);
  assertEquals(body.partnerApi, "disabled (set PARTNER_API_KEY, 24+ characters)");
});

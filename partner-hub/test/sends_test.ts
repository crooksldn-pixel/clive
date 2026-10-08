import { assert, assertEquals, assertMatch } from "jsr:@std/assert@1.0.13";
import { shopifyCreateSend } from "../src/handlers/shopifyCreateSend.ts";
import { ADMIN, fakeBase44, FakeShopify, fixture, INFLUENCER_USER, makeDeps, NOW, post, readBody } from "./fakes.ts";

const live = await fixture("variants-for-send.json");
const [GREY_SWEATS_XS, GREY_SET_XS_S, EXPRESS_TEE_WHITE_XS, BLACK_HOODIE_M, BALACLAVA, DELETED] = live.ids as string[];
const liveNodes = live.data.nodes as any[];

/** Answers PartnerHubVariantsForSend from the captured live response. */
function variantsResponder(vars: { ids: string[] }) {
  return { data: { nodes: vars.ids.map((id) => liveNodes.find((n) => n?.id === id) ?? null) } };
}

function orderCreated(name = "CROOKS-2200", id = "gid://shopify/Order/8400000000001") {
  return () => ({
    data: {
      orderCreate: {
        order: { id, name, legacyResourceId: id.split("/").pop(), createdAt: NOW.toISOString(), displayFinancialStatus: "PAID", totalPriceSet: { shopMoney: { amount: "0.0", currencyCode: "GBP" } } },
        userErrors: [],
      },
    },
  });
}

function world(overrides: { influencer?: Record<string, unknown>; address?: Record<string, unknown> | null } = {}) {
  const inf = { id: "inf1", email: "maya@example.com", username: "maya.fits", status: "active", country: "GB", ...overrides.influencer };
  const { base44, entities } = fakeBase44(ADMIN, {
    Influencer: [inf],
    Address: overrides.address === null ? [] : [{
      influencerId: "inf1",
      fullName: "Maya Okafor",
      line1: "12 Brick Lane",
      line2: "Flat 3",
      city: "London",
      region: "England",
      postcode: "E1 6RF",
      country: "GB",
      ...overrides.address,
    }],
    SocialAccount: [
      { influencerId: "inf1", platform: "tiktok", handle: "maya.fits", profileUrl: "https://www.tiktok.com/@maya.fits" },
      { influencerId: "inf1", platform: "instagram", handle: "mayafits", profileUrl: "https://www.instagram.com/mayafits" },
    ],
  }, () => NOW);
  // the fake assigns ids; pin the influencer's
  entities.Influencer.rows[0].id = "inf1";
  return { base44, entities };
}

Deno.test("creates a gifted order for in-stock items and records the send", async () => {
  const { base44, entities } = world();
  const shopify = new FakeShopify().on("PartnerHubVariantsForSend", variantsResponder).on("PartnerHubOrderCreate", orderCreated());
  const deps = makeDeps({ base44, shopify });

  const res = await shopifyCreateSend(post({
    influencerId: "inf1",
    items: [{ name: "GREY CONVICT SWEATS", size: "XS", variantId: GREY_SWEATS_XS }],
  }), deps);
  const body = await readBody(res);

  assertEquals(res.status, 200, JSON.stringify(body));
  assertEquals(body.orderName, "CROOKS-2200");
  assertEquals(body.orderAdminUrl, "https://admin.shopify.com/store/5wn03t-nm/orders/8400000000001");
  assertEquals(body.retailValue, 60);

  // The order Shopify was asked to create
  const call = shopify.calls.find((c) => c.op === "PartnerHubOrderCreate")!;
  const { order, options } = call.variables;
  assertEquals(order.lineItems, [{ variantId: GREY_SWEATS_XS, quantity: 1, priceSet: { shopMoney: { amount: "60.00", currencyCode: "GBP" } } }]);
  assertEquals(order.discountCode, { itemPercentageDiscountCode: { code: "INFLUENCER-SEEDING", percentage: 100 } });
  assertEquals(order.financialStatus, "PAID");
  assertEquals(order.shippingLines[0].priceSet.shopMoney.amount, "0.00");
  assertEquals(order.shippingAddress, {
    firstName: "Maya", lastName: "Okafor", address1: "12 Brick Lane", address2: "Flat 3",
    city: "London", zip: "E1 6RF", countryCode: "GB",
  });
  assertEquals(order.email, "maya@example.com");
  assert(order.tags.includes("SEEDING"));
  assert(order.tags.includes("influencer-maya.fits"));
  assert(order.tags.every((t: string) => t.length <= 40));
  assertMatch(order.note, /TikTok: https:\/\/www\.tiktok\.com\/@maya\.fits/);
  assertMatch(order.note, /by owner@example\.com/);
  assertEquals(options, { inventoryBehaviour: "DECREMENT_OBEYING_POLICY", sendReceipt: false, sendFulfillmentReceipt: false });

  // The hub's record of who was sent what
  const send = entities.Send.rows[0];
  assertEquals(send.status, "preparing");
  assertEquals(send.influencerId, "inf1");
  assertEquals(send.shopifyOrderName, "CROOKS-2200");
  assertEquals(send.shopifyOrderId, "gid://shopify/Order/8400000000001");
  assertEquals(send.items, [{ name: "GREY CONVICT SWEATS", size: "XS", variantId: GREY_SWEATS_XS, quantity: 1, sku: null }]);
  assertEquals(send.createdByEmail, "owner@example.com");
  assert(order.tags.includes(`hub-send-${send.id}`));
  assertEquals(order.sourceIdentifier, send.id);

  // Token came from the client-credentials grant and was reused
  assertEquals(shopify.tokenRequests.length, 1);
  assertEquals(shopify.tokenRequests[0].get("grant_type"), "client_credentials");
  assert(shopify.calls.every((c) => c.token === "shpat_test_1"));
});

Deno.test("a set is sent as its hoodie and sweats, with stock checked on each piece", async () => {
  const { base44, entities } = world();
  const shopify = new FakeShopify().on("PartnerHubVariantsForSend", variantsResponder).on("PartnerHubOrderCreate", orderCreated());
  const res = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: GREY_SET_XS_S }] }), makeDeps({ base44, shopify }));
  const body = await readBody(res);
  assertEquals(res.status, 200, JSON.stringify(body));

  const { order } = shopify.calls.find((c) => c.op === "PartnerHubOrderCreate")!.variables;
  assertEquals(order.lineItems.map((l: any) => [l.variantId, l.quantity, l.properties?.[0]?.value]), [
    ["gid://shopify/ProductVariant/53075854360919", 1, "GREY SET - XS / S"],
    ["gid://shopify/ProductVariant/53075854229847", 1, "GREY SET - XS / S"],
  ]);
  assertEquals(body.retailValue, 120);
  const item = entities.Send.rows[0].items![0];
  assertEquals(item.name, "GREY SET");
  assertEquals(item.size, "XS / S");
  assertEquals(item.components!.map((c) => c.name), ["GREY CONVICT HOODIE - XS", "GREY CONVICT SWEATS - S"]);
});

Deno.test("refuses sold-out and oversold items before touching Shopify orders, and says which", async () => {
  const { base44, entities } = world();
  const shopify = new FakeShopify().on("PartnerHubVariantsForSend", variantsResponder);
  const res = await shopifyCreateSend(post({
    influencerId: "inf1",
    items: [{ variantId: GREY_SWEATS_XS }, { variantId: BLACK_HOODIE_M }, { variantId: EXPRESS_TEE_WHITE_XS }],
  }), makeDeps({ base44, shopify }));
  const body = await readBody(res);

  assertEquals(res.status, 409);
  assertEquals(body.code, "stock_check_failed");
  assertMatch(body.error, /BLACK CONVICT HOODIE - M: 0 in stock, 1 needed/);
  // Shopify would accept this one (oversell allowed) but there's nothing to ship
  assertMatch(body.error, /CROOKS EXPRESS TEE - White \/ XS: 0 in stock, 1 needed/);
  assert(!body.error.includes("GREY CONVICT SWEATS"));
  assertEquals(shopify.ops(), ["PartnerHubVariantsForSend"]);
  assertEquals(entities.Send.rows.length, 0);
});

Deno.test("stock is counted across a set and a single of the same piece", async () => {
  const S_ID = "gid://shopify/ProductVariant/53075854229847";
  const sweatsS = { ...liveNodes[0], id: S_ID, title: "S", displayName: "GREY CONVICT SWEATS - S", inventoryQuantity: 3 };
  const set = structuredClone(liveNodes[1]);
  set.productVariantComponents.nodes[1].productVariant.inventoryQuantity = 3;
  const responder = (vars: { ids: string[] }) => ({
    data: { nodes: vars.ids.map((id) => (id === S_ID ? sweatsS : id === GREY_SET_XS_S ? set : null)) },
  });

  const tooMany = await shopifyCreateSend(
    post({ influencerId: "inf1", items: [{ variantId: GREY_SET_XS_S }, { variantId: S_ID, quantity: 3 }] }),
    makeDeps({ base44: world().base44, shopify: new FakeShopify().on("PartnerHubVariantsForSend", responder) }),
  );
  assertEquals(tooMany.status, 409);
  assertMatch((await readBody(tooMany)).error, /GREY CONVICT SWEATS - S: 3 in stock, 4 needed/);

  const shopify = new FakeShopify().on("PartnerHubVariantsForSend", responder).on("PartnerHubOrderCreate", orderCreated());
  const justEnough = await shopifyCreateSend(
    post({ influencerId: "inf1", items: [{ variantId: GREY_SET_XS_S }, { variantId: S_ID, quantity: 2 }] }),
    makeDeps({ base44: world().base44, shopify }),
  );
  assertEquals(justEnough.status, 200);
  const { order } = shopify.calls.find((c) => c.op === "PartnerHubOrderCreate")!.variables;
  assertEquals(order.lineItems.length, 3);
});

Deno.test("a deleted variant gives a clear message", async () => {
  const { base44 } = world();
  const shopify = new FakeShopify().on("PartnerHubVariantsForSend", variantsResponder);
  const res = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: DELETED }] }), makeDeps({ base44, shopify }));
  const body = await readBody(res);
  assertEquals(res.status, 409);
  assertMatch(body.error, /no longer exists in Shopify/);
});

Deno.test("draft products can be gifted but come with a warning; out-of-stock drafts still fail", async () => {
  const { base44 } = world();
  const node = { ...liveNodes[4], inventoryQuantity: 4 };
  const shopify = new FakeShopify()
    .on("PartnerHubVariantsForSend", () => ({ data: { nodes: [node] } }))
    .on("PartnerHubOrderCreate", orderCreated());
  const res = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: BALACLAVA }] }), makeDeps({ base44, shopify }));
  const body = await readBody(res);
  assertEquals(res.status, 200);
  assertMatch(body.warnings[0], /draft/);

  const res2 = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: BALACLAVA }] }), makeDeps({
    base44: world().base44,
    shopify: new FakeShopify().on("PartnerHubVariantsForSend", variantsResponder),
  }));
  assertEquals(res2.status, 409);
});

Deno.test("only admins can create orders", async () => {
  const { base44 } = world();
  base44.auth.me = async () => INFLUENCER_USER;
  const res = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: GREY_SWEATS_XS }] }), makeDeps({ base44, shopify: new FakeShopify() }));
  assertEquals(res.status, 403);
  base44.auth.me = async () => null;
  const res2 = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: GREY_SWEATS_XS }] }), makeDeps({ base44, shopify: new FakeShopify() }));
  assertEquals(res2.status, 401);
});

Deno.test("bad requests are explained", async () => {
  const shopify = new FakeShopify();
  const cases: [unknown, number, RegExp][] = [
    [{ influencerId: "inf1", items: [] }, 400, /at least one item/],
    [{ influencerId: "inf1", items: [{ name: "OG JEANS", size: "M" }] }, 400, /OG JEANS.*no Shopify variant id/],
    [{ influencerId: "inf1", items: [{ variantId: GREY_SWEATS_XS, quantity: 0 }] }, 400, /quantity/],
    [{ items: [{ variantId: GREY_SWEATS_XS }] }, 400, /influencerId/],
    [{ influencerId: "nobody", items: [{ variantId: GREY_SWEATS_XS }] }, 404, /Influencer not found/],
  ];
  for (const [body, status, msg] of cases) {
    const res = await shopifyCreateSend(post(body), makeDeps({ base44: world().base44, shopify }));
    const out = await readBody(res);
    assertEquals(res.status, status, JSON.stringify(out));
    assertMatch(out.error, msg);
  }
  assertEquals(shopify.calls.length, 0);
});

Deno.test("blocked influencers and bad addresses stop the order before Shopify", async () => {
  const shopify = new FakeShopify();
  const r1 = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: GREY_SWEATS_XS }] }), makeDeps({ base44: world({ influencer: { status: "blocked" } }).base44, shopify }));
  assertEquals(r1.status, 409);
  const r2 = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: GREY_SWEATS_XS }] }), makeDeps({ base44: world({ address: null }).base44, shopify }));
  assertMatch((await readBody(r2)).error, /no shipping address/);
  const r3 = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: GREY_SWEATS_XS }] }), makeDeps({ base44: world({ address: { postcode: "" } }).base44, shopify }));
  assertMatch((await readBody(r3)).error, /missing postcode/);
  const r4 = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: GREY_SWEATS_XS }] }), makeDeps({ base44: world({ address: { country: "US", region: "Narnia" } }).base44, shopify }));
  assertMatch((await readBody(r4)).error, /state\/province/);
  assertEquals(shopify.calls.length, 0);
});

Deno.test("US addresses get a province code", async () => {
  const { base44 } = world({ address: { country: "US", region: "new york", postcode: "10001", city: "New York" } });
  const shopify = new FakeShopify().on("PartnerHubVariantsForSend", variantsResponder).on("PartnerHubOrderCreate", orderCreated());
  const res = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: GREY_SWEATS_XS }] }), makeDeps({ base44, shopify }));
  assertEquals(res.status, 200);
  const { order } = shopify.calls.find((c) => c.op === "PartnerHubOrderCreate")!.variables;
  assertEquals(order.shippingAddress.provinceCode, "NY");
  assertEquals(order.shippingAddress.countryCode, "US");
});

Deno.test("a double click returns the first order instead of creating a second", async () => {
  const { base44 } = world();
  const shopify = new FakeShopify().on("PartnerHubVariantsForSend", variantsResponder).on("PartnerHubOrderCreate", orderCreated());
  const deps = makeDeps({ base44, shopify });
  const req = () => post({ influencerId: "inf1", items: [{ variantId: GREY_SWEATS_XS }] });
  const first = await readBody(await shopifyCreateSend(req(), deps));
  const second = await readBody(await shopifyCreateSend(req(), deps));
  assertEquals(second.orderName, first.orderName);
  assertEquals(second.duplicate, true);
  assertEquals(shopify.ops().filter((o) => o === "PartnerHubOrderCreate").length, 1);

  // different items are a different send
  const third = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: GREY_SET_XS_S }] }), deps);
  assertEquals(third.status, 200);
  assertEquals(shopify.ops().filter((o) => o === "PartnerHubOrderCreate").length, 2);
});

Deno.test("Shopify's own refusal is shown and the send record is removed", async () => {
  const { base44, entities } = world();
  const shopify = new FakeShopify()
    .on("PartnerHubVariantsForSend", variantsResponder)
    .on("PartnerHubOrderCreate", () => ({
      data: { orderCreate: { order: null, userErrors: [{ field: ["order", "lineItems", "0"], message: "Unable to reserve inventory", code: "INVENTORY_NOT_AVAILABLE" }] } },
    }));
  const res = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: GREY_SWEATS_XS }] }), makeDeps({ base44, shopify }));
  const body = await readBody(res);
  assertEquals(res.status, 422);
  assertMatch(body.error, /Shopify refused the order: Unable to reserve inventory/);
  assertEquals(entities.Send.rows.length, 0);
});

Deno.test("an unanswered orderCreate is never retried blindly; a created order is found by its tag", async () => {
  const { base44, entities } = world();
  const shopify = new FakeShopify()
    .on("PartnerHubVariantsForSend", variantsResponder)
    .on("PartnerHubOrderCreate", () => new Response("upstream timeout", { status: 504 }))
    .on("PartnerHubOrdersByQuery", (vars) => ({
      data: { orders: { nodes: [{ id: "gid://shopify/Order/8400000000009", name: "CROOKS-2209", createdAt: NOW.toISOString(), cancelledAt: null }] } },
      _q: vars,
    }));
  const res = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: GREY_SWEATS_XS }] }), makeDeps({ base44, shopify }));
  const body = await readBody(res);
  assertEquals(res.status, 200, JSON.stringify(body));
  assertEquals(body.orderName, "CROOKS-2209");
  assertEquals(shopify.ops().filter((o) => o === "PartnerHubOrderCreate").length, 1);
  const search = shopify.calls.find((c) => c.op === "PartnerHubOrdersByQuery")!;
  assertEquals(search.variables.query, `tag:'hub-send-${entities.Send.rows[0].id}'`);
  assertEquals(entities.Send.rows[0].shopifyOrderName, "CROOKS-2209");
});

Deno.test("an unanswered orderCreate with no order found keeps the send for the next sync and says not to retry", async () => {
  const { base44, entities } = world();
  const shopify = new FakeShopify()
    .on("PartnerHubVariantsForSend", variantsResponder)
    .on("PartnerHubOrderCreate", () => {
      throw new TypeError("connection reset");
    })
    .on("PartnerHubOrdersByQuery", () => ({ data: { orders: { nodes: [] } } }));
  const deps = makeDeps({ base44, shopify });
  const res = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: GREY_SWEATS_XS }] }), deps);
  const body = await readBody(res);
  assertEquals(res.status, 502);
  assertMatch(body.error, /Don't retry yet/);
  assertEquals(entities.Send.rows.length, 1);
  assertEquals(entities.Send.rows[0].shopifyOrderId, undefined);

  // Pressing the button again straight away doesn't create a second order
  const again = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: GREY_SWEATS_XS }] }), deps);
  assertEquals(again.status, 409);
  assertEquals(shopify.ops().filter((o) => o === "PartnerHubOrderCreate").length, 1);
});

Deno.test("throttling is waited out, and an expired token is replaced once", async () => {
  const { base44 } = world();
  let first = true;
  const shopify = new FakeShopify()
    .on(
      "PartnerHubVariantsForSend",
      () => ({ errors: [{ message: "Throttled", extensions: { code: "THROTTLED" } }], extensions: { cost: { requestedQueryCost: 120, throttleStatus: { currentlyAvailable: 20, restoreRate: 100 } } } }),
      (v: any) => variantsResponder(v),
    )
    .on("PartnerHubOrderCreate", () => {
      if (first) {
        first = false;
        return new Response("", { status: 401 });
      }
      return orderCreated()();
    });
  const deps = makeDeps({ base44, shopify });
  const res = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: GREY_SWEATS_XS }] }), deps);
  assertEquals(res.status, 200, JSON.stringify(await readBody(res.clone())));
  assertEquals(deps.slept[0], 1000);
  assertEquals(shopify.tokenRequests.length, 2);
  assertEquals(shopify.calls.filter((c) => c.op === "PartnerHubOrderCreate").map((c) => c.token), ["shpat_test_1", "shpat_test_2"]);
});

Deno.test("a static admin token (older custom app) works without client credentials", async () => {
  const { base44 } = world();
  const shopify = new FakeShopify().on("PartnerHubVariantsForSend", variantsResponder).on("PartnerHubOrderCreate", orderCreated());
  const deps = makeDeps({ base44, shopify, secrets: { SHOPIFY_CLIENT_ID: "", SHOPIFY_CLIENT_SECRET: "", SHOPIFY_ADMIN_ACCESS_TOKEN: "shpat_static" } });
  const res = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: GREY_SWEATS_XS }] }), deps);
  assertEquals(res.status, 200);
  assertEquals(shopify.tokenRequests.length, 0);
  assert(shopify.calls.every((c) => c.token === "shpat_static"));
});

Deno.test("missing Shopify secrets give setup instructions", async () => {
  const { base44 } = world();
  const res = await shopifyCreateSend(
    post({ influencerId: "inf1", items: [{ variantId: GREY_SWEATS_XS }] }),
    makeDeps({ base44, secrets: { SHOPIFY_CLIENT_ID: "", SHOPIFY_CLIENT_SECRET: "" } }),
  );
  const body = await readBody(res);
  assertEquals(res.status, 500);
  assertMatch(body.error, /SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET/);
});

Deno.test("dry run checks stock and shows the order without creating anything", async () => {
  const { base44, entities } = world();
  const shopify = new FakeShopify().on("PartnerHubVariantsForSend", variantsResponder);
  const res = await shopifyCreateSend(post({ influencerId: "inf1", items: [{ variantId: GREY_SET_XS_S }], dryRun: true }), makeDeps({ base44, shopify }));
  const body = await readBody(res);
  assertEquals(res.status, 200);
  assertEquals(body.dryRun, true);
  assertEquals(body.orderInput.order.lineItems.length, 2);
  assertEquals(entities.Send.rows.length, 0);
  assertEquals(shopify.ops(), ["PartnerHubVariantsForSend"]);
});

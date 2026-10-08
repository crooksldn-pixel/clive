import { assert, assertEquals, assertMatch } from "jsr:@std/assert@1.0.13";
import { shopifySyncTracking } from "../src/handlers/shopifySyncTracking.ts";
import { sendMarkShipped } from "../src/handlers/sendMarkShipped.ts";
import { deriveSendUpdate, type OrderTracking } from "../src/lib/tracking.ts";
import type { SendRecord } from "../src/lib/types.ts";
import { ADMIN, fakeBase44, FakeShopify, fixture, makeDeps, NOW, post, readBody } from "./fakes.ts";

const live = await fixture("orders-tracking.json");

const send = (over: Partial<SendRecord> = {}): SendRecord => ({
  id: "s1",
  influencerId: "inf1",
  status: "preparing",
  shopifyOrderId: "gid://shopify/Order/8300000000001",
  shopifyOrderName: "CROOKS-9001",
  ...over,
});

const fulfilled = (over: Partial<OrderTracking["fulfillments"][0]> = {}): OrderTracking => ({
  ...live.royalMail,
  fulfillments: [{ ...live.royalMail.fulfillments[0], ...over }],
});

Deno.test("the hub's existing send for cancelled order CROOKS-1869 becomes cancelled", () => {
  const update = deriveSendUpdate(
    send({ shopifyOrderId: live.cancelled.id, shopifyOrderName: "CROOKS-1869" }),
    live.cancelled,
    NOW,
  );
  assertEquals(update, { status: "cancelled", cancelledAt: "2026-09-02T18:35:45Z" });
});

Deno.test("a Royal Mail label from Click & Drop dispatches the send with its tracking number", () => {
  const update = deriveSendUpdate(send(), live.royalMail, NOW)!;
  assertEquals(update.status, "dispatched");
  assertEquals(update.trackingNumber, "VU000000001GB");
  assertEquals(update.carrier, "Royal Mail");
  assertEquals(update.trackingUrl, "https://www.royalmail.com/portal/rm/track?trackNumber=VU000000001GB");
  assertEquals(update.dispatchedAt, "2026-10-08T12:15:15Z");
  assertEquals(update.postByDate, "2026-10-29T12:15:15.000Z");
});

Deno.test("nothing changes when the send already matches Shopify", () => {
  const first = deriveSendUpdate(send(), live.royalMail, NOW)!;
  // Base44 may hand dates back in its own format
  const stored = send({ ...first, dispatchedAt: "2026-10-08T12:15:15.000000", postByDate: "2026-10-29T12:15:15.000Z" });
  assertEquals(deriveSendUpdate(stored, live.royalMail, NOW), null);
});

Deno.test("delivered, then overdue 21 days after dispatch, unless posted", () => {
  const delivered = deriveSendUpdate(send(), fulfilled({ displayStatus: "DELIVERED", deliveredAt: "2026-10-10T09:00:00Z" }), NOW)!;
  assertEquals(delivered.status, "delivered");
  assertEquals(delivered.deliveredAt, "2026-10-10T09:00:00Z");

  const later = new Date("2026-10-30T00:00:00Z");
  assertEquals(deriveSendUpdate(send(), fulfilled({ displayStatus: "DELIVERED" }), later)!.status, "overdue");
  assertEquals(deriveSendUpdate(send({ postedUrl: "https://www.tiktok.com/@maya/video/1" }), live.royalMail, later)!.status, "posted");
  assertEquals(deriveSendUpdate(send({ status: "posted" }), live.royalMail, later), null);
});

Deno.test("a voided label puts the send back to preparing", () => {
  const dispatched = send({ status: "dispatched", trackingNumber: "VU1", carrier: "Royal Mail", dispatchedAt: "2026-10-08T12:15:15Z" });
  const update = deriveSendUpdate(dispatched, fulfilled({ status: "CANCELLED", displayStatus: "LABEL_VOIDED" }), NOW)!;
  assertEquals(update.status, "preparing");
  assertEquals(update.trackingNumber, null);
});

Deno.test("an order deleted from Shopify cancels the send", () => {
  assertEquals(deriveSendUpdate(send(), null, NOW)!.status, "cancelled");
});

Deno.test("DPD UK is stored as DPD so the portal's tracking link works", () => {
  const order = fulfilled({ trackingInfo: [{ company: "DPD UK", number: "15501234567890", url: null }] });
  assertEquals(deriveSendUpdate(send(), order, NOW)!.carrier, "DPD");
});

Deno.test("sync updates every open send in one batch and reports the changes", async () => {
  const { base44, entities } = fakeBase44(ADMIN, {
    Send: [
      { id: "a", influencerId: "inf1", status: "preparing", shopifyOrderId: live.royalMail.id, shopifyOrderName: "CROOKS-9001" },
      { id: "b", influencerId: "inf2", status: "preparing", shopifyOrderId: live.cancelled.id, shopifyOrderName: "CROOKS-1869" },
      { id: "c", influencerId: "inf3", status: "posted", shopifyOrderId: "gid://shopify/Order/1", postedUrl: "https://x" },
    ],
  });
  entities.Send.rows.forEach((r, i) => (r.id = ["a", "b", "c"][i]));
  const shopify = new FakeShopify().on("PartnerHubOrdersTracking", (vars) => ({
    data: { nodes: vars.ids.map((id: string) => [live.royalMail, live.cancelled].find((o) => o.id === id) ?? null) },
  }));
  const res = await shopifySyncTracking(post({}), makeDeps({ base44, shopify }));
  const body = await readBody(res);
  assertEquals(res.status, 200, JSON.stringify(body));
  assertEquals(body.checked, 2);
  assertEquals(body.updated, 2);
  assertEquals(shopify.calls.length, 1);
  assertEquals(shopify.calls[0].variables.ids.length, 2);
  assertEquals(entities.Send.rows.find((r) => r.id === "a")!.trackingNumber, "VU000000001GB");
  assertEquals(entities.Send.rows.find((r) => r.id === "b")!.status, "cancelled");
  assertEquals(body.changes.map((c: any) => `${c.orderName}:${c.to}`).sort(), ["CROOKS-1869:cancelled", "CROOKS-9001:dispatched"]);
});

Deno.test("sync links an order Shopify created without answering, and clears sends that never became orders", async () => {
  const old = new Date(NOW.getTime() - 45 * 60_000).toISOString().replace("Z", "");
  const recent = new Date(NOW.getTime() - 5 * 60_000).toISOString().replace("Z", "");
  const { base44, entities } = fakeBase44(ADMIN, {
    Send: [
      { influencerId: "inf1", status: "preparing", createdByEmail: ADMIN.email, created_date: recent },
      { influencerId: "inf2", status: "preparing", createdByEmail: ADMIN.email, created_date: old },
      { influencerId: "inf3", status: "preparing", created_date: old }, // not made by this hub: left alone
    ],
  });
  const [linked, ghost, legacy] = entities.Send.rows;
  const shopify = new FakeShopify()
    .on("PartnerHubOrdersByQuery", (vars) => ({
      data: {
        orders: {
          nodes: vars.query.includes(linked.id) ? [{ id: "gid://shopify/Order/77", name: "CROOKS-2300", createdAt: recent, cancelledAt: null }] : [],
        },
      },
    }))
    .on("PartnerHubOrdersTracking", () => ({ data: { nodes: [{ ...live.royalMail, id: "gid://shopify/Order/77", name: "CROOKS-2300", fulfillments: [] }] } }));
  const body = await readBody(await shopifySyncTracking(post({}), makeDeps({ base44, shopify })));
  assertEquals(body.linked, 1);
  assertEquals(body.removed, 1);
  assertEquals(entities.Send.rows.find((r) => r.id === linked.id)!.shopifyOrderName, "CROOKS-2300");
  assert(!entities.Send.rows.some((r) => r.id === ghost.id));
  assert(entities.Send.rows.some((r) => r.id === legacy.id));
});

Deno.test("sync can be run by a scheduled automation holding the partner key, not by the public", async () => {
  const { base44 } = fakeBase44(null, {});
  const shopify = new FakeShopify().on("PartnerHubOrdersTracking", () => ({ data: { nodes: [] } }));
  const key = "k".repeat(32);
  const anon = await shopifySyncTracking(post({}), makeDeps({ base44, shopify, secrets: { PARTNER_API_KEY: key } }));
  assertEquals(anon.status, 401);
  const viaBody = await shopifySyncTracking(post({ key }), makeDeps({ base44, shopify, secrets: { PARTNER_API_KEY: key } }));
  assertEquals(viaBody.status, 200);
  const viaHeader = await shopifySyncTracking(post({}, { "x-partner-key": key }), makeDeps({ base44, shopify, secrets: { PARTNER_API_KEY: key } }));
  assertEquals(viaHeader.status, 200);
  const wrong = await shopifySyncTracking(post({ key: "x".repeat(32) }), makeDeps({ base44, shopify, secrets: { PARTNER_API_KEY: key } }));
  assertEquals(wrong.status, 401);
});

Deno.test("MARK SHIPPED fulfils the Shopify order with the tracking number, then syncs", async () => {
  const { base44, entities } = fakeBase44(ADMIN, {
    Send: [{ influencerId: "inf1", status: "preparing", shopifyOrderId: "gid://shopify/Order/55", shopifyOrderName: "CROOKS-2201" }],
  });
  const id = entities.Send.rows[0].id;
  const shopify = new FakeShopify()
    .on("PartnerHubFulfillmentOrders", () => ({
      data: {
        order: {
          id: "gid://shopify/Order/55", name: "CROOKS-2201", cancelledAt: null,
          fulfillmentOrders: { nodes: [{ id: "gid://shopify/FulfillmentOrder/9", status: "OPEN", supportedActions: [{ action: "CREATE_FULFILLMENT" }] }] },
        },
      },
    }))
    .on("PartnerHubFulfillmentCreate", () => ({ data: { fulfillmentCreate: { fulfillment: { id: "gid://shopify/Fulfillment/1" }, userErrors: [] } } }))
    .on("PartnerHubOrdersTracking", () => ({
      data: {
        nodes: [{
          __typename: "Order", id: "gid://shopify/Order/55", name: "CROOKS-2201", cancelledAt: null,
          fulfillments: [{ id: "f", status: "SUCCESS", displayStatus: "FULFILLED", createdAt: NOW.toISOString(), deliveredAt: null, trackingInfo: [{ company: "Evri", number: "H01ABC", url: null }] }],
        }],
      },
    }));
  const res = await sendMarkShipped(post({ sendId: id, trackingNumber: "H01 ABC", carrier: "Evri" }), makeDeps({ base44, shopify }));
  const body = await readBody(res);
  assertEquals(res.status, 200, JSON.stringify(body));
  const create = shopify.calls.find((c) => c.op === "PartnerHubFulfillmentCreate")!.variables.fulfillment;
  assertEquals(create.lineItemsByFulfillmentOrder, [{ fulfillmentOrderId: "gid://shopify/FulfillmentOrder/9" }]);
  assertEquals(create.trackingInfo, { number: "H01ABC", company: "Evri" });
  assertEquals(create.notifyCustomer, false);
  assertEquals(body.send.status, "dispatched");
  assertEquals(body.send.trackingNumber, "H01ABC");
});

Deno.test("MARK SHIPPED on an order already fulfilled in Shopify saves the number in the hub only", async () => {
  const { base44, entities } = fakeBase44(ADMIN, {
    Send: [{ influencerId: "inf1", status: "preparing", shopifyOrderId: "gid://shopify/Order/56", shopifyOrderName: "CROOKS-2202" }],
  });
  const id = entities.Send.rows[0].id;
  const shopify = new FakeShopify().on("PartnerHubFulfillmentOrders", () => ({
    data: { order: { id: "gid://shopify/Order/56", name: "CROOKS-2202", cancelledAt: null, fulfillmentOrders: { nodes: [{ id: "fo", status: "CLOSED", supportedActions: [] }] } } },
  }));
  const body = await readBody(await sendMarkShipped(post({ sendId: id, trackingNumber: "VU1234GB", carrier: "Royal Mail" }), makeDeps({ base44, shopify })));
  assertMatch(body.warnings[0], /already fulfilled/);
  assertEquals(body.send.status, "dispatched");
  assertEquals(body.send.postByDate, "2026-10-29T21:00:00.000Z");
  assert(!shopify.ops().includes("PartnerHubFulfillmentCreate"));
});

Deno.test("MARK SHIPPED rejects bad input", async () => {
  const { base44 } = fakeBase44(ADMIN, {});
  for (const body of [{ sendId: "x", trackingNumber: "", carrier: "Evri" }, { sendId: "x", trackingNumber: "AB12345", carrier: "" }, { sendId: "x", trackingNumber: "AB12345", carrier: "Evri", trackingUrl: "http://insecure" }]) {
    const res = await sendMarkShipped(post(body), makeDeps({ base44, shopify: new FakeShopify() }));
    assertEquals(res.status, 400);
  }
});

Deno.test("sync fills in influencerEmail on older sends, for the Send security rule", async () => {
  const { base44, entities } = fakeBase44(ADMIN, {
    Influencer: [{ email: "maya@example.com", username: "maya.fits" }],
  });
  const inf = entities.Influencer.rows[0];
  entities.Send.rows.push({ id: "old", influencerId: inf.id, status: "posted" });
  const shopify = new FakeShopify();
  await shopifySyncTracking(post({}), makeDeps({ base44, shopify }));
  assertEquals(entities.Send.rows[0].influencerEmail, "maya@example.com");
  assertEquals(shopify.calls.length, 0);
});

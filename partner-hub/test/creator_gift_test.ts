import { assert, assertEquals, assertMatch } from "jsr:@std/assert@1.0.13";
import "../shopify-app/extensions/creator-gift/assets/creator-gift.js";
import { shopifyCreateDiscount } from "../src/handlers/shopifyCreateDiscount.ts";
import { syncPromotions } from "../src/handlers/syncPromotions.ts";
import { colourName, collectionGid } from "../src/lib/promotions.ts";
import { ADMIN, fakeBase44, FakeShopify, INFLUENCER_USER, makeDeps, NOW, post, readBody } from "./fakes.ts";

// deno-lint-ignore no-explicit-any
const G = (globalThis as any).CrooksGift;

const BLACK = 53455222964567;
const WHITE = 53456567238999;
const RULES = {
  v: 1,
  gift: {
    variantIds: [BLACK, WHITE],
    excludeProductTypes: ["Socks"],
    label: "MOTIONTEC socks",
    variants: [
      { id: BLACK, handle: "black-socks", name: "Black/Blue" },
      { id: WHITE, handle: "white-socks", name: "White/Red" },
    ],
  },
  codes: ["BILLYJPEG", "E1LISSPAM", "KATE"],
  updatedAt: "2026-10-09T16:30:00Z",
};

const hoodie = { key: "h:1", variant_id: 53075854360919, quantity: 1, product_type: "Hoodies", properties: {} };
const paidSocks = { key: "s:1", variant_id: BLACK, quantity: 1, product_type: "Socks", properties: {} };
const gift = (variant = BLACK, qty = 1, key = `g:${variant}`) => ({
  key,
  variant_id: variant,
  quantity: qty,
  product_type: "Socks",
  properties: { _crooks_gift: "BILLYJPEG" },
});
const cart = (items: unknown[], codes: string[] = []) => ({
  items,
  item_count: items.length,
  discount_codes: codes.map((code) => ({ code, applicable: true })),
});

// ---------------------------------------------------------------- reconcile

Deno.test("gift code + a piece + no gift line: add the first gift variant, qty 1", () => {
  assertEquals(G.reconcile(cart([hoodie], ["BILLYJPEG"]), RULES), [
    { type: "add", code: "BILLYJPEG", variantIds: [BLACK, WHITE] },
  ]);
});

Deno.test("a lowercase code still counts", () => {
  assertEquals(G.reconcile(cart([hoodie], ["billyjpeg"]), RULES)[0].code, "BILLYJPEG");
});

Deno.test("a code that isn't in the rules (paused, or a 15% code) adds nothing", () => {
  assertEquals(G.reconcile(cart([hoodie], ["CROOKSLDN"]), RULES), []);
  assertEquals(G.reconcile(cart([hoodie], ["ALESSIA"]), RULES), []);
});

Deno.test("only socks in the bag: no free socks, and an existing gift is removed", () => {
  assertEquals(G.reconcile(cart([paidSocks], ["BILLYJPEG"]), RULES), []);
  assertEquals(G.reconcile(cart([paidSocks, gift()], ["BILLYJPEG"]), RULES), [{ type: "remove", key: `g:${BLACK}` }]);
});

Deno.test("gift line without the code, or after the piece is removed: remove it", () => {
  assertEquals(G.reconcile(cart([hoodie, gift()], []), RULES), [{ type: "remove", key: `g:${BLACK}` }]);
  assertEquals(G.reconcile(cart([gift()], ["BILLYJPEG"]), RULES), [{ type: "remove", key: `g:${BLACK}` }]);
});

Deno.test("gift quantity 2 is set back to 1", () => {
  assertEquals(G.reconcile(cart([hoodie, gift(BLACK, 2)], ["BILLYJPEG"]), RULES), [
    { type: "setQty", key: `g:${BLACK}`, quantity: 1 },
  ]);
});

Deno.test("two gift lines: keep the first, remove the rest", () => {
  assertEquals(G.reconcile(cart([hoodie, gift(BLACK), gift(WHITE)], ["BILLYJPEG"]), RULES), [
    { type: "remove", key: `g:${WHITE}` },
  ]);
});

Deno.test("nothing to do when the bag is already right", () => {
  assertEquals(G.reconcile(cart([hoodie, gift(WHITE)], ["BILLYJPEG"]), RULES), []);
  assertEquals(G.reconcile(cart([hoodie], []), RULES), []);
  assertEquals(G.reconcile(cart([], ["BILLYJPEG"]), RULES), []);
});

Deno.test("missing rules never add socks, and clear any left behind", () => {
  assertEquals(G.reconcile(cart([hoodie], ["BILLYJPEG"]), null), []);
  assertEquals(G.reconcile(cart([hoodie, gift()], ["BILLYJPEG"]), null), [{ type: "remove", key: `g:${BLACK}` }]);
});

Deno.test("sold-out fallback: tries the next colour on 422, reports sold out when none are left", async () => {
  const tried: number[] = [];
  const api = (statuses: Record<number, number>) => ({
    add: (id: number) => {
      tried.push(id);
      const status = statuses[id] ?? 200;
      return Promise.resolve({ ok: status === 200, status });
    },
    change: () => Promise.resolve({ ok: true, status: 200 }),
  });
  const actions = G.reconcile(cart([hoodie], ["BILLYJPEG"]), RULES);

  const fellBack = await G.applyActions(actions, api({ [BLACK]: 422 }));
  assertEquals(tried, [BLACK, WHITE]);
  assertEquals(fellBack, { soldOut: false, changed: true, addedVariantId: WHITE });

  tried.length = 0;
  const none = await G.applyActions(actions, api({ [BLACK]: 422, [WHITE]: 422 }));
  assertEquals(tried, [BLACK, WHITE]);
  assertEquals(none.soldOut, true);
  assertEquals(G.message(cart([hoodie], ["BILLYJPEG"]), RULES, true).text, "Free socks are sold out right now");
});

Deno.test("bag messages and the swap target", () => {
  assertEquals(G.message(cart([hoodie], []), RULES, false), { where: "above", text: "Creator code? Enter it here for free socks." });
  assertEquals(
    G.message(cart([paidSocks], ["BILLYJPEG"]), RULES, false).text,
    "Add any CROOKS piece to your bag to unlock free socks with BILLYJPEG.",
  );
  assertEquals(G.message(cart([hoodie, gift()], ["BILLYJPEG"]), RULES, false), {
    where: "below",
    text: "Free MOTIONTEC socks added with BILLYJPEG",
    swap: true,
  });
  assertEquals(G.swapTarget(cart([hoodie, gift(BLACK)], ["BILLYJPEG"]), RULES).name, "White/Red");
  assertEquals(G.swapTarget(cart([hoodie, gift(WHITE)], ["BILLYJPEG"]), RULES).name, "Black/Blue");
  assertEquals(G.message(cart([hoodie], ["ALESSIA"]), { ...RULES, codes: [] }, false), null);
});

// ------------------------------------------------------------ discounts

const COLLECTION = "gid://shopify/Collection/700000000001";
const PROMO = {
  name: "Creator socks",
  active: true,
  giftVariantIds: [BLACK, WHITE],
  qualifyingCollectionId: "700000000001",
  excludeProductTypes: ["Socks"],
};

function hub(user = ADMIN, extra: Record<string, unknown[]> = {}) {
  const { base44, entities } = fakeBase44(user, {
    Promotion: [PROMO],
    Influencer: [
      { email: "billy@example.com", username: "billyjpeg", status: "active", country: "GB" },
      { email: "alessia@example.com", username: "alessia", status: "active", country: "IT" },
      { email: INFLUENCER_USER.email, username: "maya.fits", status: "active", country: "GB" },
    ],
    ...extra,
  }, () => NOW);
  const [billy, alessia, maya] = entities.Influencer.rows;
  return { base44, entities, billy, alessia, maya };
}

interface Existing {
  id: string;
  type: "DiscountCodeBasic" | "DiscountCodeBxgy";
  title: string;
  percentage?: number;
  collections?: string[];
  variants?: string[];
  products?: string[];
}

function shop(existing: Record<string, Existing> = {}, opts: { collection?: boolean; failCreate?: boolean } = {}) {
  const s = new FakeShopify();
  s.on("PartnerHubCollection", () => ({ data: { collection: opts.collection === false ? null : { id: COLLECTION, title: "Creator gift – qualifying" } } }));
  s.on("PartnerHubDiscountByCode", (v) => {
    const e = existing[v.code];
    if (!e) return { data: { codeDiscountNodeByCode: null } };
    const codeDiscount: Record<string, unknown> = { __typename: e.type, title: e.title, status: "ACTIVE" };
    if (e.type === "DiscountCodeBasic") codeDiscount.customerGets = { value: { __typename: "DiscountPercentage", percentage: e.percentage ?? 0.15 } };
    else {
      codeDiscount.customerBuys = { items: { __typename: "DiscountCollections", collections: { nodes: (e.collections ?? []).map((id) => ({ id })) } } };
      codeDiscount.customerGets = {
        items: {
          __typename: "DiscountProducts",
          products: { nodes: (e.products ?? []).map((id) => ({ id })) },
          productVariants: { nodes: (e.variants ?? []).map((id) => ({ id })) },
        },
      };
    }
    return { data: { codeDiscountNodeByCode: { id: e.id, codeDiscount } } };
  });
  const created = (field: string, id: string) => () =>
    opts.failCreate
      ? { data: { [field]: { codeDiscountNode: null, userErrors: [{ field: ["code"], message: "Code is invalid", code: "INVALID" }] } } }
      : { data: { [field]: { codeDiscountNode: { id }, userErrors: [] } } };
  s.on("PartnerHubBxgyCreateV", created("discountCodeBxgyCreate", "gid://shopify/DiscountCodeNode/9001"));
  s.on("PartnerHubBasicCreateV", created("discountCodeBasicCreate", "gid://shopify/DiscountCodeNode/9002"));
  s.on("PartnerHubBxgyUpdate", () => ({ data: { discountCodeBxgyUpdate: { codeDiscountNode: { id: "x" }, userErrors: [] } } }));
  s.on("PartnerHubBasicUpdate", () => ({ data: { discountCodeBasicUpdate: { codeDiscountNode: { id: "x" }, userErrors: [] } } }));
  s.on("PartnerHubDiscountDelete", (v) => ({ data: { discountCodeDelete: { deletedCodeDiscountId: v.id, userErrors: [] } } }));
  // the gift rules refresh after every create
  s.on("PartnerHubDiscountStatuses", (v) => ({
    data: { nodes: v.ids.map((id: string) => ({ __typename: "DiscountCodeNode", id, codeDiscount: { status: "ACTIVE" } })) },
  }));
  s.on("PartnerHubDiscountDeactivate", () => ({ data: { discountCodeDeactivate: { codeDiscountNode: { id: "x" }, userErrors: [] } } }));
  s.on("PartnerHubDiscountActivate", () => ({ data: { discountCodeActivate: { codeDiscountNode: { id: "x" }, userErrors: [] } } }));
  s.on("PartnerHubGiftVariants", (v) => ({
    data: {
      nodes: v.ids.map((id: string) => ({
        __typename: "ProductVariant",
        id,
        title: "1pc",
        product: id.endsWith(String(BLACK))
          ? { title: "BLACK/BLUE MOTIONTEC™️ SOCKS", handle: "black-socks", productType: "Socks" }
          : { title: "WHITE/RED MOTIONTEC™️ SOCKS", handle: "white-socks", productType: "Socks" },
      })),
    },
  }));
  s.on("PartnerHubAppInstallation", () => ({ data: { currentAppInstallation: { id: "gid://shopify/AppInstallation/42" } } }));
  s.on("PartnerHubMetafieldsSet", () => ({ data: { metafieldsSet: { metafields: [{ id: "gid://shopify/Metafield/1" }], userErrors: [] } } }));
  return s;
}

const vars = (s: FakeShopify, op: string) => s.calls.filter((c) => c.op === op).map((c) => c.variables);

Deno.test("free socks: exactly the Buy X Get Y input from the spec, variants not products", async () => {
  const { base44, entities, billy } = hub();
  entities.AffiliateCode.rows.push({ id: "c1", influencerId: billy.id, code: "BILLYJPEG", type: "free_socks", value: 100, isPrimary: true });
  const s = shop();
  const res = await shopifyCreateDiscount(
    post({ code: "BILLYJPEG", type: "free_socks", value: 100, influencerId: billy.id, override: true }),
    makeDeps({ base44, shopify: s }),
  );
  const body = await readBody(res);
  assertEquals(res.status, 200, JSON.stringify(body));
  assertEquals({ discountId: body.discountId, type: body.type, value: body.value }, {
    discountId: "gid://shopify/DiscountCodeNode/9001",
    type: "free_socks",
    value: 100,
  });
  const [{ input }] = vars(s, "PartnerHubBxgyCreateV");
  assertEquals(input, {
    title: "SEEDING BILLYJPEG",
    code: "BILLYJPEG",
    startsAt: NOW.toISOString(),
    context: { all: "ALL" },
    appliesOncePerCustomer: true,
    usesPerOrderLimit: 1,
    combinesWith: { orderDiscounts: false, productDiscounts: false, shippingDiscounts: false },
    customerBuys: { items: { collections: { add: [COLLECTION] } }, value: { quantity: "1" } },
    customerGets: {
      items: { products: { productVariantsToAdd: [`gid://shopify/ProductVariant/${BLACK}`, `gid://shopify/ProductVariant/${WHITE}`] } },
      value: { discountOnQuantity: { quantity: "1", effect: { percentage: 1.0 } } },
    },
  });
  assert(!JSON.stringify(s.calls).includes("productsToAdd"));
  // saved on the record before the gift rules are written
  assertEquals(entities.AffiliateCode.rows[0].shopifyDiscountId, "gid://shopify/DiscountCodeNode/9001");
  const [rules] = vars(s, "PartnerHubMetafieldsSet");
  assertEquals(JSON.parse(rules.metafields[0].value).codes, ["BILLYJPEG"]);
});

Deno.test("percentage: exactly the basic input from the spec", async () => {
  const { base44, entities, alessia } = hub();
  entities.AffiliateCode.rows.push({ id: "c2", influencerId: alessia.id, code: "ALESSIA", type: "percentage", value: 15 });
  const s = shop();
  const body = await readBody(await shopifyCreateDiscount(
    post({ code: "alessia", type: "percentage", value: 15, influencerId: alessia.id, override: true }),
    makeDeps({ base44, shopify: s }),
  ));
  assertEquals([body.type, body.value], ["percentage", 15]);
  assertEquals(vars(s, "PartnerHubBasicCreateV")[0].input, {
    title: "SEEDING ALESSIA",
    code: "ALESSIA",
    startsAt: NOW.toISOString(),
    context: { all: "ALL" },
    appliesOncePerCustomer: true,
    combinesWith: { orderDiscounts: false, productDiscounts: false, shippingDiscounts: false },
    customerGets: { items: { all: true }, value: { percentage: 0.15 } },
  });
  assertEquals(vars(s, "PartnerHubBxgyCreateV").length, 0);
});

Deno.test("override, same type: updates in place", async () => {
  const { base44, entities, alessia } = hub();
  entities.AffiliateCode.rows.push({ id: "c2", influencerId: alessia.id, code: "ALESSIA", type: "percentage", value: 15, shopifyDiscountId: "gid://shopify/DiscountCodeNode/55" });
  const s = shop({ ALESSIA: { id: "gid://shopify/DiscountCodeNode/55", type: "DiscountCodeBasic", title: "SEEDING ALESSIA" } });
  const body = await readBody(await shopifyCreateDiscount(
    post({ code: "ALESSIA", type: "percentage", value: 20, influencerId: alessia.id, override: true }),
    makeDeps({ base44, shopify: s }),
  ));
  assertEquals([body.action, body.discountId, body.value], ["updated", "gid://shopify/DiscountCodeNode/55", 20]);
  const [upd] = vars(s, "PartnerHubBasicUpdate");
  assertEquals(upd.id, "gid://shopify/DiscountCodeNode/55");
  assertEquals(upd.input.customerGets.value.percentage, 0.2);
  assert(!("startsAt" in upd.input));
  assertEquals(vars(s, "PartnerHubDiscountDelete").length + vars(s, "PartnerHubBasicCreateV").length, 0);
});

Deno.test("override, same type (socks): moves the collection and gift variants with add/remove", async () => {
  const { base44, entities, billy } = hub();
  entities.AffiliateCode.rows.push({ id: "c1", influencerId: billy.id, code: "BILLYJPEG", type: "free_socks", shopifyDiscountId: "gid://shopify/DiscountCodeNode/56" });
  const s = shop({
    BILLYJPEG: {
      id: "gid://shopify/DiscountCodeNode/56",
      type: "DiscountCodeBxgy",
      title: "SEEDING BILLYJPEG",
      collections: ["gid://shopify/Collection/1"],
      variants: [`gid://shopify/ProductVariant/${BLACK}`, "gid://shopify/ProductVariant/99"],
      products: ["gid://shopify/Product/7"],
    },
  });
  await shopifyCreateDiscount(post({ code: "BILLYJPEG", type: "free_socks", value: 100, influencerId: billy.id, override: true }), makeDeps({ base44, shopify: s }));
  const [upd] = vars(s, "PartnerHubBxgyUpdate");
  assertEquals(upd.input.customerBuys.items.collections, { add: [COLLECTION], remove: ["gid://shopify/Collection/1"] });
  assertEquals(upd.input.customerGets.items.products, {
    productVariantsToAdd: [`gid://shopify/ProductVariant/${BLACK}`, `gid://shopify/ProductVariant/${WHITE}`],
    productVariantsToRemove: ["gid://shopify/ProductVariant/99"],
    productsToRemove: ["gid://shopify/Product/7"],
  });
});

Deno.test("override, type change: deletes the stored discount, then creates the new one", async () => {
  const { base44, entities, alessia } = hub();
  entities.AffiliateCode.rows.push({ id: "c2", influencerId: alessia.id, code: "ALESSIA", type: "percentage", value: 15, shopifyDiscountId: "gid://shopify/DiscountCodeNode/55" });
  const s = shop({ ALESSIA: { id: "gid://shopify/DiscountCodeNode/55", type: "DiscountCodeBasic", title: "SEEDING ALESSIA" } });
  const body = await readBody(await shopifyCreateDiscount(
    post({ code: "ALESSIA", type: "free_socks", value: 100, influencerId: alessia.id, override: true }),
    makeDeps({ base44, shopify: s }),
  ));
  assertEquals([body.action, body.discountId], ["replaced", "gid://shopify/DiscountCodeNode/9001"]);
  const ops = s.ops().filter((o) => /Delete|Create/.test(o));
  assertEquals(ops, ["PartnerHubDiscountDelete", "PartnerHubBxgyCreateV"]);
  assertEquals(vars(s, "PartnerHubDiscountDelete")[0].id, "gid://shopify/DiscountCodeNode/55");
  assertEquals(entities.AffiliateCode.rows[0].shopifyDiscountId, "gid://shopify/DiscountCodeNode/9001");
});

Deno.test("override, type change that fails after the delete says the code is off in Shopify", async () => {
  const { base44, entities, alessia } = hub();
  entities.AffiliateCode.rows.push({ id: "c2", influencerId: alessia.id, code: "ALESSIA", type: "percentage", value: 15, shopifyDiscountId: "gid://shopify/DiscountCodeNode/55" });
  const s = shop({ ALESSIA: { id: "gid://shopify/DiscountCodeNode/55", type: "DiscountCodeBasic", title: "SEEDING ALESSIA" } }, { failCreate: true });
  const res = await shopifyCreateDiscount(
    post({ code: "ALESSIA", type: "free_socks", value: 100, influencerId: alessia.id, override: true }),
    makeDeps({ base44, shopify: s }),
  );
  const body = await readBody(res);
  assertEquals(res.status, 502);
  assertMatch(body.error, /ALESSIA is currently off in Shopify/);
  assertEquals(body.code, "code_off_in_shopify");
});

Deno.test("a type change without the override is refused, nothing deleted", async () => {
  const { base44, entities, billy } = hub(INFLUENCER_USER);
  const maya = entities.Influencer.rows[2];
  entities.AffiliateCode.rows.push({ id: "c3", influencerId: maya.id, code: "MAYA", type: "free_socks" });
  const s = shop({ MAYA: { id: "gid://shopify/DiscountCodeNode/57", type: "DiscountCodeBasic", title: "SEEDING MAYA" } });
  const res = await shopifyCreateDiscount(post({ code: "MAYA" }), makeDeps({ base44, shopify: s }));
  assertEquals(res.status, 409);
  assertEquals(vars(s, "PartnerHubDiscountDelete").length, 0);
  assert(billy);
});

Deno.test("a Shopify discount the Hub didn't make is never changed", async () => {
  const { base44, entities, alessia } = hub();
  entities.AffiliateCode.rows.push({ id: "c2", influencerId: alessia.id, code: "ALESSIA", type: "percentage", value: 15 });
  const s = shop({ ALESSIA: { id: "gid://shopify/DiscountCodeNode/1", type: "DiscountCodeBasic", title: "Summer sale" } });
  const res = await shopifyCreateDiscount(post({ code: "ALESSIA", type: "percentage", value: 15, influencerId: alessia.id, override: true }), makeDeps({ base44, shopify: s }));
  assertEquals(res.status, 409);
  assertEquals(s.ops().filter((o) => /Update|Delete|Create/.test(o)), []);
});

Deno.test("influencer's own code: UK default is free socks, whatever the record says", async () => {
  const { base44, entities, maya } = hub(INFLUENCER_USER);
  // an influencer can edit their own record; a forged 100% is ignored
  entities.AffiliateCode.rows.push({ id: "c3", influencerId: maya.id, code: "MAYA", type: "percentage", value: 100 });
  const s = shop();
  const body = await readBody(await shopifyCreateDiscount(post({ code: "maya" }), makeDeps({ base44, shopify: s })));
  assertEquals([body.type, body.value], ["free_socks", 100]);
  assertEquals(vars(s, "PartnerHubBasicCreateV").length, 0);
});

Deno.test("influencer's new code copies the terms of their previous code in Shopify", async () => {
  const { base44, entities, maya } = hub(INFLUENCER_USER);
  entities.AffiliateCode.rows.push(
    { id: "old", influencerId: maya.id, code: "MAYAOLD", type: "percentage", value: 100, shopifyDiscountId: "gid://shopify/DiscountCodeNode/60", created_date: "2026-09-01T10:00:00.000000" },
    { id: "new", influencerId: maya.id, code: "MAYA2", type: "percentage", value: 100, created_date: "2026-10-09T10:00:00.000000" },
  );
  const s = shop({ MAYAOLD: { id: "gid://shopify/DiscountCodeNode/60", type: "DiscountCodeBasic", title: "SEEDING MAYAOLD", percentage: 0.2 } });
  const body = await readBody(await shopifyCreateDiscount(post({ code: "MAYA2" }), makeDeps({ base44, shopify: s })));
  assertEquals([body.type, body.value], ["percentage", 20]);
  assertEquals(vars(s, "PartnerHubBasicCreateV")[0].input.customerGets.value.percentage, 0.2);
});

Deno.test("influencers can't make discounts for someone else's code; overrides are admin-only", async () => {
  const { base44, entities, billy } = hub(INFLUENCER_USER);
  entities.AffiliateCode.rows.push({ id: "c1", influencerId: billy.id, code: "BILLYJPEG", type: "free_socks" });
  const s = shop();
  assertEquals((await shopifyCreateDiscount(post({ code: "BILLYJPEG" }), makeDeps({ base44, shopify: s }))).status, 404);
  assertEquals(
    (await shopifyCreateDiscount(post({ code: "BILLYJPEG", type: "percentage", value: 90, influencerId: billy.id, override: true }), makeDeps({ base44, shopify: s }))).status,
    403,
  );
  base44.auth.me = async () => null;
  assertEquals((await shopifyCreateDiscount(post({ code: "BILLYJPEG" }), makeDeps({ base44, shopify: s }))).status, 401);
  assertEquals(s.ops().filter((o) => /Create|Update|Delete/.test(o)), []);
});

Deno.test("free socks need the qualifying collection, and it must exist", async () => {
  const noId = hub(ADMIN, { Promotion: [{ ...PROMO, qualifyingCollectionId: "" }] });
  noId.entities.AffiliateCode.rows.push({ id: "c1", influencerId: noId.billy.id, code: "BILLYJPEG", type: "free_socks" });
  const r1 = await shopifyCreateDiscount(post({ code: "BILLYJPEG", type: "free_socks", value: 100, influencerId: noId.billy.id, override: true }), makeDeps({ base44: noId.base44, shopify: shop() }));
  assertEquals(r1.status, 422);
  assertMatch((await readBody(r1)).error, /qualifying collection/);

  const gone = hub();
  gone.entities.AffiliateCode.rows.push({ id: "c1", influencerId: gone.billy.id, code: "BILLYJPEG", type: "free_socks" });
  const s = shop({}, { collection: false });
  const r2 = await shopifyCreateDiscount(post({ code: "BILLYJPEG", type: "free_socks", value: 100, influencerId: gone.billy.id, override: true }), makeDeps({ base44: gone.base44, shopify: s }));
  assertEquals(r2.status, 422);
  assertEquals(vars(s, "PartnerHubBxgyCreateV").length, 0);
});

// -------------------------------------------------------- syncPromotions

Deno.test("syncPromotions: only active influencers' free-socks codes with a Shopify discount go in the rules", async () => {
  const { base44, entities, billy, alessia } = hub();
  const paused = { email: "crooks@example.com", username: "crooksldn", status: "paused", country: "GB", id: "inf-paused" };
  entities.Influencer.rows.push(paused as never);
  entities.AffiliateCode.rows.push(
    { id: "a", influencerId: billy.id, code: "billyjpeg", type: "free_socks", shopifyDiscountId: "gid://shopify/DiscountCodeNode/1" },
    { id: "b", influencerId: billy.id, code: "KATE", type: "free_socks", shopifyDiscountId: "gid://shopify/DiscountCodeNode/2" },
    { id: "c", influencerId: alessia.id, code: "ALESSIA", type: "percentage", value: 15, shopifyDiscountId: "gid://shopify/DiscountCodeNode/3" },
    { id: "d", influencerId: "inf-paused", code: "CROOKSLDN", type: "free_socks", shopifyDiscountId: "gid://shopify/DiscountCodeNode/4" },
    { id: "e", influencerId: billy.id, code: "NODISCOUNT", type: "free_socks" },
    { id: "f", influencerId: billy.id, code: "DELETEDINSHOPIFY", type: "free_socks", shopifyDiscountId: "gid://shopify/DiscountCodeNode/5" },
  );
  const s = shop();
  s.on("PartnerHubDiscountStatuses", (v) => ({
    data: {
      nodes: v.ids.map((id: string) =>
        id.endsWith("/5") ? null : { __typename: "DiscountCodeNode", id, codeDiscount: { status: id.endsWith("/2") ? "EXPIRED" : "ACTIVE" } }
      ),
    },
  }));
  const res = await syncPromotions(post({}), makeDeps({ base44, shopify: s }));
  const body = await readBody(res);
  assertEquals(res.status, 200, JSON.stringify(body));
  assertEquals(body.codes, ["BILLYJPEG", "KATE"]);
  assertEquals(body.deactivated, ["CROOKSLDN"]); // paused influencer
  assertEquals(body.activated, ["KATE"]); // active influencer, discount had expired
  assertEquals(body.missingInShopify, ["DELETEDINSHOPIFY"]);
  assertEquals(vars(s, "PartnerHubDiscountDeactivate")[0].id, "gid://shopify/DiscountCodeNode/4");

  const [set] = vars(s, "PartnerHubMetafieldsSet");
  const mf = set.metafields[0];
  assertEquals([mf.ownerId, mf.namespace, mf.key, mf.type], ["gid://shopify/AppInstallation/42", "creator_gift", "rules", "json"]);
  assertEquals(JSON.parse(mf.value), {
    v: 1,
    gift: {
      variantIds: [BLACK, WHITE],
      excludeProductTypes: ["Socks"],
      label: "MOTIONTEC socks",
      variants: [
        { id: BLACK, handle: "black-socks", name: "Black/Blue" },
        { id: WHITE, handle: "white-socks", name: "White/Red" },
      ],
    },
    codes: ["BILLYJPEG", "KATE"],
    updatedAt: NOW.toISOString(),
  });
});

Deno.test("syncPromotions: switching the promotion off pauses the sock codes and empties the rules", async () => {
  const { base44, entities, billy, alessia } = hub(ADMIN, { Promotion: [{ ...PROMO, active: false }] });
  entities.AffiliateCode.rows.push(
    { id: "a", influencerId: billy.id, code: "BILLYJPEG", type: "free_socks", shopifyDiscountId: "gid://shopify/DiscountCodeNode/1" },
    { id: "c", influencerId: alessia.id, code: "ALESSIA", type: "percentage", shopifyDiscountId: "gid://shopify/DiscountCodeNode/3" },
  );
  const s = shop();
  const body = await readBody(await syncPromotions(post({}), makeDeps({ base44, shopify: s })));
  assertEquals(body.codes, []);
  assertEquals(body.deactivated, ["BILLYJPEG"]);
});

Deno.test("syncPromotions is admin or partner key only", async () => {
  const { base44 } = hub(INFLUENCER_USER);
  assertEquals((await syncPromotions(post({}), makeDeps({ base44, shopify: shop() }))).status, 403);
  const key = "k".repeat(32);
  const ok = await syncPromotions(post({}, { "x-partner-key": key }), makeDeps({ base44, shopify: shop(), secrets: { PARTNER_API_KEY: key } }));
  assertEquals(ok.status, 200);
});

Deno.test("helpers: collection ids and colour names", () => {
  assertEquals(collectionGid("700000000001"), COLLECTION);
  assertEquals(collectionGid(COLLECTION), COLLECTION);
  assertEquals(collectionGid("https://admin.shopify.com/store/5wn03t-nm/collections/700000000001"), COLLECTION);
  assertEquals(collectionGid("creator-gift"), null);
  assertEquals(colourName("BLACK/BLUE MOTIONTEC™️ SOCKS"), "Black/Blue");
  assertEquals(colourName("WHITE/RED MOTIONTEC™️ SOCKS"), "White/Red");
});

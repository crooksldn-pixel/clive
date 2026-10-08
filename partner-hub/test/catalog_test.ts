import { assert, assertEquals } from "jsr:@std/assert@1.0.13";
import { classify, planCatalog, type ShopifyProduct, toVariantRecord } from "../src/lib/catalog.ts";
import { shopifySyncCatalog } from "../src/handlers/shopifySyncCatalog.ts";
import { ADMIN, fakeBase44, FakeShopify, fixture, makeDeps, NOW, post, readBody } from "./fakes.ts";

const shop = await fixture("catalog-live.json");
const hub = await fixture("hub-products.json");
const products = shop.products as ShopifyProduct[];
const byHandle = (h: string) => products.find((p) => p.handle === h)!;

Deno.test("real products land in the portal's categories, sized by the right half of the size profile", () => {
  const got = Object.fromEntries(products.map((p) => [p.handle, `${classify(p).type}/${classify(p).sizeCategory}`]));
  assertEquals(got["v2-baggies"], "sweats/bottom"); // joggers: was stored as "top"
  assertEquals(got["v1-hoodie"], "sweats/top");
  assertEquals(got["crooks-express-t-shirt"], "tee/top");
  assertEquals(got["black-socks"], "accessories/onesize");
  assertEquals(got["og-jeans"], "denim/bottom");
  assertEquals(got["blue-wash-yard-jorts"], "denim/bottom");
  assertEquals(got["charcoal-cellblock-shorts"], "sweats/bottom");
  assertEquals(got["charcoal-cellblock-crewneck"], "sweats/top");
  assertEquals(got["hydrocuff-windbreaker"], "outerwear/top");
  assertEquals(got["double-agent-puffa"], "outerwear/top");
  assertEquals(got["grey-set"], "set/top");
  assertEquals(got["major-league-crooks-cap-cream"], "accessories/onesize");
});

Deno.test("variants keep the portal's size/label shape; oversold stock shows as 0", () => {
  const tee = byHandle("crooks-express-t-shirt");
  const whiteXs = toVariantRecord(tee, tee.variants.nodes[0]);
  assertEquals(whiteXs, {
    variantId: "gid://shopify/ProductVariant/53099604246871",
    label: "White / XS",
    size: "XS",
    stock: 0, // -3 in Shopify
    price: 25,
    sku: null,
    tracked: true,
    isBundle: undefined,
  });
  const set = byHandle("pink-set");
  const v = toVariantRecord(set, set.variants.nodes[0]);
  assertEquals(v.size, "XS"); // the hoodie size, as the portal stored sets
  assertEquals(v.label, "XS / V1 / XS");
  assertEquals(v.isBundle, true);
  const socks = byHandle("black-socks");
  assertEquals(toVariantRecord(socks, socks.variants.nodes[1]).size, "ONE");
  assertEquals(toVariantRecord(socks, socks.variants.nodes[1]).label, "3pc");
});

Deno.test("planning against the real hub catalogue: renamed handles match by variant id; admin choices kept", () => {
  const plan = planCatalog(hub.products, products, NOW);
  const moved = Object.fromEntries(plan.updates.filter((u) => u.handleMovedFrom).map((u) => [u.handleMovedFrom, u.data.handle]));
  assertEquals(moved, {
    "cb1-wash-jeans": "grey-wash-yard-jeans",
    "cb2-wash-jeans": "blue-wash-yard-jeans",
    "cb1-wash-jorts": "blue-wash-yard-jorts",
    "cb2-wash-jorts": "grey-wash-yard-jorts",
    "hyrdocuff-windbreaker": "hydrocuff-windbreaker",
  });
  // Every stored product is matched except the duffle, which isn't on sale any more
  assertEquals(plan.missing.map((m) => hub.products.find((p: any) => p.id === m.id).handle), ["large-duffle-bag"]);
  assertEquals(plan.missing[0].data.available, false);
  assert(plan.missing[0].data.variants!.every((v) => v.stock === 0));
  // New in Shopify since the first load
  assertEquals(plan.creates.map((c) => c.handle).sort(), ["double-agent-puffa", "major-league-crooks-cap-cream"]);
  assert(plan.creates.every((c) => c.available === true && typeof c.sortOrder === "number" && c.sortOrder >= 24));
  // Sync never overwrites what the admin set
  for (const u of plan.updates) {
    assert(!("available" in u.data) && !("sortOrder" in u.data) && !("measurementsJson" in u.data));
  }
  // Stock is the live figure: CRX GARMS showed ~100 per size in the hub, Shopify has 0
  const crx = plan.updates.find((u) => u.data.handle === "crx-garms-t-shirt")!;
  assert(crx.data.variants!.every((v) => v.stock === 0));
});

Deno.test("sync writes products and moves influencers' picks from renamed handles", async () => {
  const { base44, entities } = fakeBase44(ADMIN, {
    Product: hub.products.map((p: any) => ({ ...p })),
    Interest: [
      { influencerId: "inf1", productHandle: "cb1-wash-jeans", size: "M" },
      { influencerId: "inf2", productHandle: "v2-baggies", size: "S" },
    ],
  });
  // keep the stored ids
  entities.Product.rows.forEach((r, i) => (r.id = hub.products[i].id));
  const pages = [products.slice(0, 13), products.slice(13)];
  const shopify = new FakeShopify().on(
    "PartnerHubCatalog",
    () => ({ data: { products: { pageInfo: { hasNextPage: true, endCursor: "c1" }, nodes: structuredClone(pages[0]) } } }),
    () => ({ data: { products: { pageInfo: { hasNextPage: false, endCursor: null }, nodes: structuredClone(pages[1]) } } }),
  );
  const res = await shopifySyncCatalog(post({}), makeDeps({ base44, shopify }));
  const body = await readBody(res);
  assertEquals(res.status, 200, JSON.stringify(body));
  assertEquals(body.products, 25);
  assertEquals(body.created, 2);
  assertEquals(body.hiddenMissing, 1);
  assertEquals(shopify.calls[1].variables.cursor, "c1");
  assertEquals(entities.Interest.rows.find((i) => i.influencerId === "inf1")!.productHandle, "grey-wash-yard-jeans");
  assertEquals(entities.Interest.rows.find((i) => i.influencerId === "inf2")!.productHandle, "v2-baggies");
  const jeans = entities.Product.rows.find((p) => p.handle === "grey-wash-yard-jeans")!;
  assertEquals(jeans.name, "GREY WASH YARD JEANS");
  assertEquals(jeans.sortOrder, 10); // the admin's order survives
  assertEquals(entities.Product.rows.length, 26);
});

Deno.test("products with more than 50 variants are fetched in full", async () => {
  const big = structuredClone(byHandle("pink-set"));
  const firstPage = big.variants.nodes.slice(0, 20);
  const rest = big.variants.nodes.slice(20);
  big.variants = { pageInfo: { hasNextPage: true, endCursor: "v1" }, nodes: firstPage };
  const { base44, entities } = fakeBase44(ADMIN, {});
  const shopify = new FakeShopify()
    .on("PartnerHubCatalog", () => ({ data: { products: { pageInfo: { hasNextPage: false, endCursor: null }, nodes: [big] } } }))
    .on("PartnerHubMoreVariants", () => ({ data: { product: { variants: { pageInfo: { hasNextPage: false, endCursor: null }, nodes: rest } } } }));
  await shopifySyncCatalog(post({}), makeDeps({ base44, shopify }));
  assertEquals(entities.Product.rows[0].variants!.length, 30);
});

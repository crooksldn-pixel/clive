import { CATALOG, MORE_VARIANTS } from "./queries.ts";
import { listAll } from "./records.ts";
import type { Shopify } from "./shopify.ts";
import type { Deps, ProductRecord, ProductVariantRecord } from "./types.ts";

export interface ShopifyVariant {
  id: string;
  title: string;
  sku: string | null;
  price: string;
  inventoryQuantity: number | null;
  inventoryPolicy: string;
  requiresComponents: boolean;
  inventoryItem: { tracked: boolean } | null;
  selectedOptions: { name: string; value: string }[];
}

export interface ShopifyProduct {
  id: string;
  handle: string;
  title: string;
  productType: string;
  tags: string[];
  status: "ACTIVE" | "DRAFT" | "ARCHIVED" | string;
  featuredMedia: { preview: { image: { url: string } | null } | null } | null;
  options: { name: string; position: number }[];
  variants: { pageInfo?: { hasNextPage: boolean; endCursor: string | null }; nodes: ShopifyVariant[] };
}

/** Stock shown for a variant whose inventory Shopify doesn't track. */
export const UNTRACKED_STOCK = 999;

const has = (text: string, re: RegExp) => re.test(text);

/**
 * Maps a Shopify product onto the portal's categories (the filter chips and
 * size charts) and says whether it is sized by the top or bottom size.
 */
export function classify(p: Pick<ShopifyProduct, "productType" | "title" | "tags" | "options">): {
  type: string;
  sizeCategory: "top" | "bottom" | "onesize";
} {
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

/**
 * `size` is what the portal groups by and compares to the influencer's size
 * profile; `label` is the full variant title. For a set, `size` is the first
 * sized piece (the top), matching how the portal already stored sets.
 */
export function variantSize(product: Pick<ShopifyProduct, "options">, v: ShopifyVariant): string {
  const sizeOptions = [...(product.options || [])]
    .sort((a, b) => a.position - b.position)
    .filter((o) => /size/i.test(o.name))
    .map((o) => o.name);
  if (sizeOptions.length) {
    const value = v.selectedOptions.find((o) => o.name === sizeOptions[0])?.value;
    if (value) return value;
  }
  return "ONE";
}

export function toVariantRecord(product: ShopifyProduct, v: ShopifyVariant): ProductVariantRecord {
  const tracked = v.inventoryItem?.tracked !== false;
  return {
    variantId: v.id,
    label: v.title === "Default Title" ? "ONE" : v.title,
    size: variantSize(product, v),
    stock: tracked ? Math.max(0, v.inventoryQuantity ?? 0) : UNTRACKED_STOCK,
    price: Number(v.price),
    sku: v.sku,
    tracked,
    isBundle: v.requiresComponents || undefined,
  };
}

/** The fields a sync owns. `available`, `sortOrder` and measurements stay the admin's. */
export function syncedFields(p: ShopifyProduct, nowIso: string): Omit<ProductRecord, "id" | "available" | "sortOrder"> {
  const variants = p.variants.nodes.map((v) => toVariantRecord(p, v));
  const prices = variants.map((v) => v.price ?? 0).filter((n) => n > 0);
  const { type, sizeCategory } = classify(p);
  return {
    handle: p.handle,
    name: p.title,
    type,
    sizeCategory,
    imageUrl: p.featuredMedia?.preview?.image?.url ?? undefined,
    priceGbp: prices.length ? Math.min(...prices) : undefined,
    variants,
    shopifyProductId: p.id,
    shopifyStatus: p.status,
    syncedAt: nowIso,
  };
}

export interface CatalogPlan {
  creates: Omit<ProductRecord, "id">[];
  updates: { id: string; data: Partial<ProductRecord>; handleMovedFrom?: string }[];
  missing: { id: string; data: Partial<ProductRecord> }[];
}

/**
 * Matches Shopify products to the stored records by handle, then Shopify id,
 * then any shared variant id (handles have been renamed in Shopify since the
 * catalogue was first loaded, and influencers' picks point at the old ones).
 */
export function planCatalog(existing: ProductRecord[], products: ShopifyProduct[], now: Date): CatalogPlan {
  const nowIso = now.toISOString();
  const plan: CatalogPlan = { creates: [], updates: [], missing: [] };
  const claimed = new Set<string>();
  let nextSort = Math.max(-1, ...existing.map((r) => (typeof r.sortOrder === "number" ? r.sortOrder : -1))) + 1;

  const find = (p: ShopifyProduct): ProductRecord | undefined => {
    const free = existing.filter((r) => !claimed.has(r.id));
    const ids = new Set(p.variants.nodes.map((v) => v.id));
    return (
      free.find((r) => r.handle === p.handle) ??
      free.find((r) => r.shopifyProductId === p.id) ??
      free.find((r) => (r.variants || []).some((v) => ids.has(v.variantId)))
    );
  };

  for (const p of products) {
    if (p.status === "ARCHIVED") continue;
    const fields = syncedFields(p, nowIso);
    const rec = find(p);
    if (rec) {
      claimed.add(rec.id);
      const data: Partial<ProductRecord> = { ...fields };
      if (!data.imageUrl) delete data.imageUrl;
      plan.updates.push({ id: rec.id, data, handleMovedFrom: rec.handle !== p.handle ? rec.handle : undefined });
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
        variants: (r.variants || []).map((v) => ({ ...v, stock: 0 })),
      },
    });
  }
  return plan;
}

export async function fetchCatalog(shopify: Shopify): Promise<ShopifyProduct[]> {
  const out: ShopifyProduct[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < 100; page++) {
    const data: { products: { pageInfo: { hasNextPage: boolean; endCursor: string | null }; nodes: ShopifyProduct[] } } =
      await shopify.graphql(CATALOG, { cursor, query: "status:active OR status:draft" });
    for (const p of data.products.nodes) {
      let more = p.variants.pageInfo;
      while (more?.hasNextPage) {
        const extra: { product: { variants: ShopifyProduct["variants"] } | null } = await shopify.graphql(MORE_VARIANTS, {
          id: p.id,
          cursor: more.endCursor,
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

export interface CatalogSummary {
  products: number;
  created: number;
  updated: number;
  hiddenMissing: number;
  renamed: { from: string; to: string; interestsMoved: number }[];
}

export async function syncCatalog(deps: Deps, shopify: Shopify): Promise<CatalogSummary> {
  const db = deps.base44.asServiceRole.entities;
  const [products, existing] = await Promise.all([fetchCatalog(shopify), listAll(db.Product, undefined, "name")]);
  const plan = planCatalog(existing, products, deps.now());

  for (const c of plan.creates) await db.Product.create(c);
  const renamed: CatalogSummary["renamed"] = [];
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
    renamed,
  };
}

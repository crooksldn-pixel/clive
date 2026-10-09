// Creator codes and the free-socks gift (partner-hub/CREATOR_GIFT.md).
import { HttpError } from "./http.ts";
import {
  APP_INSTALLATION,
  BASIC_CREATE,
  BASIC_UPDATE,
  BXGY_CREATE,
  BXGY_UPDATE,
  COLLECTION,
  DISCOUNT_ACTIVATE,
  DISCOUNT_BY_CODE,
  DISCOUNT_DEACTIVATE,
  DISCOUNT_DELETE,
  DISCOUNT_STATUSES,
  GIFT_VARIANTS,
  METAFIELDS_SET,
} from "./queries.ts";
import { listAll, parseRecordDate } from "./records.ts";
import { chunk, type Shopify } from "./shopify.ts";
import type { AffiliateCode, Deps, Influencer, Promotion } from "./types.ts";

export type DiscountType = "free_socks" | "percentage";
export const DISCOUNT_TYPES: DiscountType[] = ["free_socks", "percentage"];
export const GIFT_LABEL = "MOTIONTEC socks";
export const RULES_NAMESPACE = "creator_gift";
export const RULES_KEY = "rules";

const COMBINES_WITH = { orderDiscounts: false, productDiscounts: false, shippingDiscounts: false };

/** Codes are uppercase letters and digits, as the portal makes them. */
export function normaliseCode(v: unknown): string {
  return typeof v === "string" ? v.toUpperCase().replace(/[^A-Z0-9]/g, "") : "";
}

export function discountTitle(code: string): string {
  return `SEEDING ${code}`;
}

/** Accepts a numeric id, a Collection GID, or an admin URL ending in /collections/<id>. */
export function collectionGid(input: unknown): string | null {
  if (typeof input === "number" && Number.isInteger(input) && input > 0) return `gid://shopify/Collection/${input}`;
  if (typeof input !== "string") return null;
  const s = input.trim();
  if (/^\d+$/.test(s)) return `gid://shopify/Collection/${s}`;
  if (/^gid:\/\/shopify\/Collection\/\d+$/.test(s)) return s;
  const m = s.match(/\/collections\/(\d+)(?:[/?#]|$)/);
  return m ? `gid://shopify/Collection/${m[1]}` : null;
}

export function giftVariantNumbers(p: Promotion): number[] {
  const ids = (p.giftVariantIds ?? [])
    .map((v) => String(v).trim().replace(/^gid:\/\/shopify\/ProductVariant\//, ""))
    .filter((v) => /^\d+$/.test(v))
    .map(Number);
  if (!ids.length) {
    throw new HttpError(422, "The Creator socks promotion has no gift variants. Add them in the Promotions tab.", "promotion_incomplete");
  }
  return ids;
}

const variantGidOf = (n: number) => `gid://shopify/ProductVariant/${n}`;

/** The active promotion (the first active one, else the first one). */
export async function activePromotion(deps: Deps): Promise<Promotion> {
  const rows = await listAll(deps.base44.asServiceRole.entities.Promotion);
  const p = rows.find((r) => r.active === true) ?? rows[0];
  if (!p) {
    throw new HttpError(422, "Set up the Creator socks promotion in the Promotions tab first.", "no_promotion");
  }
  return p;
}

/** discountCodeBxgyCreate input: buy any qualifying piece, get one 1-pair pack free. */
export function bxgyInput(
  code: string,
  collection: { add: string[]; remove?: string[] },
  variants: { add: string[]; remove?: string[]; removeProducts?: string[] },
  startsAt?: string,
) {
  const products: Record<string, string[]> = { productVariantsToAdd: variants.add };
  if (variants.remove?.length) products.productVariantsToRemove = variants.remove;
  if (variants.removeProducts?.length) products.productsToRemove = variants.removeProducts;
  const collections: Record<string, string[]> = { add: collection.add };
  if (collection.remove?.length) collections.remove = collection.remove;
  return {
    title: discountTitle(code),
    code,
    ...(startsAt ? { startsAt } : {}),
    context: { all: "ALL" },
    appliesOncePerCustomer: true,
    usesPerOrderLimit: 1,
    combinesWith: COMBINES_WITH,
    customerBuys: { items: { collections }, value: { quantity: "1" } },
    customerGets: {
      items: { products },
      value: { discountOnQuantity: { quantity: "1", effect: { percentage: 1.0 } } },
    },
  };
}

/** discountCodeBasicCreate input: value% off everything. */
export function basicInput(code: string, percent: number, startsAt?: string) {
  return {
    title: discountTitle(code),
    code,
    ...(startsAt ? { startsAt } : {}),
    context: { all: "ALL" },
    appliesOncePerCustomer: true,
    combinesWith: COMBINES_WITH,
    customerGets: { items: { all: true }, value: { percentage: percent / 100 } },
  };
}

export interface ExistingDiscount {
  id: string;
  kind: "basic" | "bxgy" | "other";
  title: string;
  status: string;
  percentage: number | null;
  collections: string[];
  variants: string[];
  products: string[];
}

type Node = { id: string; codeDiscount: Record<string, any> } | null;

export async function findDiscount(shopify: Shopify, code: string): Promise<ExistingDiscount | null> {
  const res = await shopify.graphql<{ codeDiscountNodeByCode: Node }>(DISCOUNT_BY_CODE, { code });
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
    collections: buys.map((x: { id: string }) => x.id),
    variants: (gets.productVariants?.nodes ?? []).map((x: { id: string }) => x.id),
    products: (gets.products?.nodes ?? []).map((x: { id: string }) => x.id),
  };
}

function userErrorsOrThrow(errs: { message: string }[] | undefined, what: string) {
  if (errs?.length) {
    throw new HttpError(422, `Shopify refused the ${what}: ${errs.map((e) => e.message).join("; ")}`, "shopify_rejected", {
      userErrors: errs,
    });
  }
}

async function createDiscount(shopify: Shopify, kind: "basic" | "bxgy", input: unknown): Promise<string> {
  const op = kind === "bxgy" ? BXGY_CREATE : BASIC_CREATE;
  const field = kind === "bxgy" ? "discountCodeBxgyCreate" : "discountCodeBasicCreate";
  const res = await shopify.graphql<Record<string, { codeDiscountNode: { id: string } | null; userErrors: { message: string }[] }>>(
    op,
    { input },
    { idempotent: false },
  );
  userErrorsOrThrow(res[field].userErrors, "discount");
  const id = res[field].codeDiscountNode?.id;
  if (!id) throw new HttpError(502, "Shopify didn't return the new discount.", "shopify_rejected");
  return id;
}

async function updateDiscount(shopify: Shopify, kind: "basic" | "bxgy", id: string, input: unknown) {
  const op = kind === "bxgy" ? BXGY_UPDATE : BASIC_UPDATE;
  const field = kind === "bxgy" ? "discountCodeBxgyUpdate" : "discountCodeBasicUpdate";
  const res = await shopify.graphql<Record<string, { userErrors: { message: string }[] }>>(op, { id, input }, { idempotent: false });
  userErrorsOrThrow(res[field].userErrors, "discount update");
}

export interface UpsertOptions {
  code: string;
  type: DiscountType;
  value: number;
  promotion?: Promotion;
  /** AffiliateCode.shopifyDiscountId, when the Hub already made one. */
  storedId?: string | null;
  /** Admin override: may change a code's type (delete, then create). */
  override: boolean;
}

export interface UpsertResult {
  discountId: string;
  type: DiscountType;
  value: number;
  action: "created" | "updated" | "replaced";
}

/**
 * Creates the code's Shopify discount, or updates the one the Hub made.
 * Never touches a discount the Hub didn't make.
 */
export async function upsertDiscount(deps: Deps, shopify: Shopify, o: UpsertOptions): Promise<UpsertResult> {
  const code = normaliseCode(o.code);
  if (!code) throw new HttpError(400, "Missing code.", "bad_request");
  const want: "bxgy" | "basic" = o.type === "free_socks" ? "bxgy" : "basic";
  const value = o.type === "free_socks" ? 100 : o.value;

  let collection = "";
  let gifts: string[] = [];
  if (want === "bxgy") {
    if (!o.promotion) throw new HttpError(422, "Set up the Creator socks promotion first.", "no_promotion");
    const gid = collectionGid(o.promotion.qualifyingCollectionId);
    if (!gid) {
      throw new HttpError(
        422,
        "Free-socks codes need the qualifying collection. Create it in Shopify and paste its ID in the Promotions tab.",
        "no_collection",
      );
    }
    const found = await shopify.graphql<{ collection: { id: string } | null }>(COLLECTION, { id: gid });
    if (!found.collection) {
      throw new HttpError(422, `The qualifying collection ${gid.split("/").pop()} isn't in Shopify. Check the ID in Promotions.`, "no_collection");
    }
    collection = gid;
    gifts = giftVariantNumbers(o.promotion).map(variantGidOf);
  } else if (!(value > 0 && value <= 100)) {
    throw new HttpError(400, "A percentage code needs a value from 1 to 100.", "bad_value");
  }

  const existing = await findDiscount(shopify, code);
  const ours = existing && ((o.storedId && existing.id === o.storedId) || existing.title === discountTitle(code));
  if (existing && !ours) {
    throw new HttpError(
      409,
      `Shopify already has a discount with the code ${code} that the Hub didn't make. Rename or delete it in Shopify, or pick another code.`,
      "code_taken_in_shopify",
    );
  }
  const now = deps.now().toISOString();
  const createInput = () =>
    want === "bxgy" ? bxgyInput(code, { add: [collection] }, { add: gifts }, now) : basicInput(code, value, now);

  if (!existing) {
    return { discountId: await createDiscount(shopify, want, createInput()), type: o.type, value, action: "created" };
  }

  if (existing.kind === want) {
    const input = want === "bxgy"
      ? bxgyInput(
        code,
        { add: [collection], remove: existing.collections.filter((c) => c !== collection) },
        {
          add: gifts,
          remove: existing.variants.filter((v) => !gifts.includes(v)),
          removeProducts: existing.products,
        },
      )
      : basicInput(code, value);
    await updateDiscount(shopify, want, existing.id, input);
    return { discountId: existing.id, type: o.type, value, action: "updated" };
  }

  if (!o.override) {
    throw new HttpError(
      409,
      `${code} is already a different kind of discount in Shopify. Change its type with the admin override.`,
      "type_change_needs_override",
    );
  }
  const del = await shopify.graphql<{ discountCodeDelete: { userErrors: { message: string }[] } }>(
    DISCOUNT_DELETE,
    { id: existing.id },
    { idempotent: false },
  );
  userErrorsOrThrow(del.discountCodeDelete.userErrors, "removal of the old discount");
  try {
    return { discountId: await createDiscount(shopify, want, createInput()), type: o.type, value, action: "replaced" };
  } catch (e) {
    throw new HttpError(
      502,
      `The old ${code} discount was removed but the new one couldn't be created (${(e as Error).message}). ` +
        `${code} is currently off in Shopify; try the override again.`,
      "code_off_in_shopify",
    );
  }
}

/**
 * The terms an influencer's own code gets: whatever their previous Hub code
 * has in Shopify (only an admin can set anything else), otherwise the default
 * for their country. Never the type/value on the new record, which the
 * influencer can edit.
 */
export async function termsForInfluencer(
  shopify: Shopify,
  influencer: Influencer,
  theirCodes: AffiliateCode[],
  newCode: string,
): Promise<{ type: DiscountType; value: number }> {
  const previous = theirCodes
    .filter((c) => normaliseCode(c.code) !== newCode && c.shopifyDiscountId)
    .sort((a, b) => (parseRecordDate(b.created_date) || 0) - (parseRecordDate(a.created_date) || 0));
  for (const p of previous) {
    const d = await findDiscount(shopify, normaliseCode(p.code));
    if (!d || d.title !== discountTitle(normaliseCode(p.code))) continue;
    if (d.kind === "bxgy") return { type: "free_socks", value: 100 };
    if (d.kind === "basic" && d.percentage) return { type: "percentage", value: Math.round(d.percentage * 10000) / 100 };
  }
  return influencer.country === "GB" ? { type: "free_socks", value: 100 } : { type: "percentage", value: 15 };
}

/** "BLACK/BLUE MOTIONTEC™️ SOCKS" → "Black/Blue" for the swap link. */
export function colourName(productTitle: string): string {
  const head = productTitle.split(/MOTIONTEC/i)[0].trim() || productTitle.trim();
  return head
    .toLowerCase()
    .split("/")
    .map((w) => w.trim().replace(/(^|[\s-])([a-z])/g, (_m, a, b) => a + b.toUpperCase()))
    .join("/");
}

export interface PromotionsSummary {
  ok: true;
  codes: string[];
  updatedAt: string;
  activated: string[];
  deactivated: string[];
  missingInShopify: string[];
  metafieldId: string | null;
  rules: unknown;
}

/**
 * Pauses/unpauses codes to match each influencer's status, then writes the
 * gift rules the bag script reads (an app-data metafield on this app's
 * installation).
 */
export async function syncPromotions(deps: Deps, shopify: Shopify): Promise<PromotionsSummary> {
  const db = deps.base44.asServiceRole.entities;
  const promotion = await activePromotion(deps);
  const variantIds = giftVariantNumbers(promotion);
  const [codes, influencers] = await Promise.all([listAll(db.AffiliateCode), listAll(db.Influencer)]);
  const infById = new Map(influencers.map((i) => [i.id, i]));
  const withDiscount = codes.filter((c) => c.shopifyDiscountId);

  const statuses = new Map<string, string>();
  for (const ids of chunk([...new Set(withDiscount.map((c) => c.shopifyDiscountId!))], 50)) {
    const res = await shopify.graphql<{ nodes: ({ __typename: string; id: string; codeDiscount?: { status?: string } } | null)[] }>(
      DISCOUNT_STATUSES,
      { ids },
    );
    for (const n of res.nodes) if (n?.__typename === "DiscountCodeNode") statuses.set(n.id, n.codeDiscount?.status ?? "");
  }

  const activated: string[] = [];
  const deactivated: string[] = [];
  const missingInShopify: string[] = [];
  const live: AffiliateCode[] = [];
  for (const c of withDiscount) {
    const status = statuses.get(c.shopifyDiscountId!);
    if (status === undefined) {
      missingInShopify.push(normaliseCode(c.code));
      continue;
    }
    const inf = infById.get(c.influencerId);
    const wanted = inf?.status === "active" && (c.type !== "free_socks" || promotion.active !== false);
    if (wanted && status === "EXPIRED") {
      const r = await shopify.graphql<{ discountCodeActivate: { userErrors: { message: string }[] } }>(
        DISCOUNT_ACTIVATE,
        { id: c.shopifyDiscountId },
        { idempotent: false },
      );
      userErrorsOrThrow(r.discountCodeActivate.userErrors, `reactivation of ${c.code}`);
      activated.push(normaliseCode(c.code));
    } else if (!wanted && (status === "ACTIVE" || status === "SCHEDULED")) {
      const r = await shopify.graphql<{ discountCodeDeactivate: { userErrors: { message: string }[] } }>(
        DISCOUNT_DEACTIVATE,
        { id: c.shopifyDiscountId },
        { idempotent: false },
      );
      userErrorsOrThrow(r.discountCodeDeactivate.userErrors, `pause of ${c.code}`);
      deactivated.push(normaliseCode(c.code));
    }
    if (wanted) live.push(c);
  }

  const ruleCodes = [...new Set(live.filter((c) => c.type === "free_socks").map((c) => normaliseCode(c.code)).filter(Boolean))].sort();

  const gv = await shopify.graphql<{
    nodes: ({ __typename: string; id: string; product: { title: string; handle: string } } | null)[];
  }>(GIFT_VARIANTS, { ids: variantIds.map(variantGidOf) });
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
      variants,
    },
    codes: ruleCodes,
    updatedAt,
  };

  const inst = await shopify.graphql<{ currentAppInstallation: { id: string } }>(APP_INSTALLATION);
  const set = await shopify.graphql<{
    metafieldsSet: { metafields: { id: string }[] | null; userErrors: { message: string }[] };
  }>(METAFIELDS_SET, {
    metafields: [{
      ownerId: inst.currentAppInstallation.id,
      namespace: RULES_NAMESPACE,
      key: RULES_KEY,
      type: "json",
      value: JSON.stringify(rules),
    }],
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
    rules,
  };
}

import { toShippingAddress } from "./address.ts";
import { HttpError } from "./http.ts";
import { ORDER_CREATE, ORDERS_BY_QUERY, VARIANTS_FOR_SEND } from "./queries.ts";
import { getOr404, listAll, parseRecordDate } from "./records.ts";
import { orderAdminUrl, type Shopify, ShopifyError, variantGid } from "./shopify.ts";
import type { Deps, Influencer, SendItem, SendRecord, SocialAccount } from "./types.ts";

export const MAX_ITEMS = 25;
export const MAX_QUANTITY = 10;
/** A second identical send inside this window is treated as a double-click. */
export const DUPLICATE_WINDOW_MS = 10 * 60_000;

export interface RequestedItem {
  variantId: string;
  quantity: number;
}

export function parseItems(raw: unknown): RequestedItem[] {
  if (!Array.isArray(raw) || raw.length === 0) {
    throw new HttpError(400, "Pick at least one item to send.", "no_items");
  }
  if (raw.length > MAX_ITEMS) throw new HttpError(400, `At most ${MAX_ITEMS} items per send.`, "too_many_items");
  const merged = new Map<string, number>();
  raw.forEach((item, i) => {
    const it = (item ?? {}) as Record<string, unknown>;
    const id = variantGid(it.variantId);
    if (!id) {
      throw new HttpError(
        400,
        `Item ${i + 1}${it.name ? ` (${it.name})` : ""} has no Shopify variant id. Run SYNC SHOPIFY on the catalogue and try again.`,
        "bad_variant",
      );
    }
    const q = it.quantity === undefined ? 1 : Number(it.quantity);
    if (!Number.isInteger(q) || q < 1 || q > MAX_QUANTITY) {
      throw new HttpError(400, `Item ${i + 1} quantity must be a whole number from 1 to ${MAX_QUANTITY}.`, "bad_quantity");
    }
    merged.set(id, (merged.get(id) ?? 0) + q);
  });
  return [...merged].map(([variantId, quantity]) => ({ variantId, quantity }));
}

interface VariantCore {
  id: string;
  title: string;
  displayName: string;
  sku: string | null;
  price: string;
  inventoryQuantity: number | null;
  inventoryPolicy: "DENY" | "CONTINUE";
  requiresComponents: boolean;
  inventoryItem: { tracked: boolean };
  product: { id: string; title: string; handle: string; status: "ACTIVE" | "DRAFT" | "ARCHIVED" | string };
}

interface VariantNode extends VariantCore {
  __typename: "ProductVariant";
  productVariantComponents: { nodes: { quantity: number; productVariant: VariantCore }[] };
}

export interface PlannedLine {
  variantId: string;
  quantity: number;
  unitPrice: string;
  title: string;
  /** The set this piece belongs to, when a bundle was expanded. */
  partOf?: string;
}

export interface Problem {
  variantId: string;
  code: "not_found" | "archived" | "out_of_stock" | "bundle_empty";
  message: string;
}

export interface StockLine {
  variantId: string;
  title: string;
  needed: number;
  inStock: number | null;
  tracked: boolean;
}

export interface SendPlan {
  items: SendItem[];
  lines: PlannedLine[];
  stock: StockLine[];
  problems: Problem[];
  warnings: string[];
  retailValue: number;
}

function sizeLabel(v: VariantCore): string {
  return v.title === "Default Title" ? "ONE" : v.title;
}

/**
 * Checks the requested variants against live Shopify data. Sets (bundles)
 * are expanded into their pieces, because the pieces are what get picked and
 * what carry the stock. Stock is checked against what is physically on hand,
 * even for variants Shopify lets you oversell: a gifted parcel can't ship
 * from negative stock.
 */
export async function planSend(shopify: Shopify, requested: RequestedItem[]): Promise<SendPlan> {
  const data = await shopify.graphql<{ nodes: (VariantNode | null)[] }>(VARIANTS_FOR_SEND, {
    ids: requested.map((r) => r.variantId),
  });
  const byId = new Map<string, VariantNode>();
  for (const n of data.nodes) if (n && n.__typename === "ProductVariant") byId.set(n.id, n);

  const problems: Problem[] = [];
  const warnings: string[] = [];
  const items: SendItem[] = [];
  const lines: PlannedLine[] = [];
  const need = new Map<string, { v: VariantCore; qty: number }>();
  const addNeed = (v: VariantCore, qty: number) => {
    const cur = need.get(v.id);
    need.set(v.id, { v, qty: (cur?.qty ?? 0) + qty });
  };

  for (const req of requested) {
    const v = byId.get(req.variantId);
    if (!v) {
      problems.push({
        variantId: req.variantId,
        code: "not_found",
        message: `${req.variantId} no longer exists in Shopify (deleted or replaced). Run SYNC SHOPIFY and pick it again.`,
      });
      continue;
    }
    if (v.product.status === "ARCHIVED") {
      problems.push({ variantId: v.id, code: "archived", message: `${v.displayName} is archived in Shopify.` });
      continue;
    }
    if (v.product.status === "DRAFT") warnings.push(`${v.displayName} is a draft in Shopify (not on sale yet).`);

    const item: SendItem = {
      name: v.product.title,
      size: sizeLabel(v),
      variantId: v.id,
      quantity: req.quantity,
      sku: v.sku,
    };

    if (v.requiresComponents) {
      const parts = v.productVariantComponents.nodes;
      if (!parts.length) {
        problems.push({
          variantId: v.id,
          code: "bundle_empty",
          message: `${v.displayName} is a bundle with no pieces set up in Shopify.`,
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
            message: `${pv.displayName} (part of ${v.displayName}) is archived in Shopify.`,
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

  const stock: StockLine[] = [];
  for (const { v, qty } of need.values()) {
    const tracked = v.inventoryItem?.tracked !== false;
    const onHand = v.inventoryQuantity ?? 0;
    stock.push({ variantId: v.id, title: v.displayName, needed: qty, inStock: tracked ? onHand : null, tracked });
    if (tracked && qty > onHand) {
      problems.push({
        variantId: v.id,
        code: "out_of_stock",
        message: `${v.displayName}: ${Math.max(onHand, 0)} in stock, ${qty} needed`,
      });
    }
  }

  const retailValue = round2(lines.reduce((sum, l) => sum + Number(l.unitPrice) * l.quantity, 0));
  return { items, lines, stock, problems, warnings, retailValue };
}

export function assertSendable(plan: SendPlan) {
  if (!plan.problems.length) return;
  throw new HttpError(
    409,
    `Can't create the order: ${plan.problems.map((p) => p.message).join("; ")}.`,
    "stock_check_failed",
    { problems: plan.problems, stock: plan.stock },
  );
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

function tagSafe(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9._-]/g, "").slice(0, 28);
}

export function sendTag(sendId: string): string {
  return `hub-send-${sendId}`;
}

export interface OrderContext {
  sendId: string;
  influencer: Influencer;
  shippingAddress: ReturnType<typeof toShippingAddress>;
  socials: SocialAccount[];
  createdBy: string;
  note?: string;
  discountCode: string;
  currency: string;
}

/**
 * The gifted order: real line items at full price (so Shopify reports the
 * value of what was gifted), a 100% discount, free shipping, marked paid,
 * stock decremented while honouring each variant's oversell policy, and no
 * customer emails.
 */
export function buildOrderInput(plan: SendPlan, ctx: OrderContext) {
  const money = (amount: string) => ({ shopMoney: { amount, currencyCode: ctx.currency } });
  const social = (p: string) => ctx.socials.find((s) => s.platform === p);
  const tt = social("tiktok");
  const ig = social("instagram");
  const note = [
    `Influencer seeding for @${ctx.influencer.username}`,
    tt?.profileUrl ? `TikTok: ${tt.profileUrl}` : null,
    ig?.profileUrl ? `Instagram: ${ig.profileUrl}` : null,
    `Created in the CROOKS Partner Hub by ${ctx.createdBy}.`,
    ctx.note ? `Note: ${ctx.note}` : null,
  ].filter(Boolean).join("\n");

  return {
    order: {
      email: ctx.influencer.email || undefined,
      shippingAddress: ctx.shippingAddress,
      lineItems: plan.lines.map((l) => ({
        variantId: l.variantId,
        quantity: l.quantity,
        priceSet: money(l.unitPrice),
        ...(l.partOf ? { properties: [{ name: "Part of", value: l.partOf }] } : {}),
      })),
      discountCode: { itemPercentageDiscountCode: { code: ctx.discountCode, percentage: 100 } },
      shippingLines: [{ title: "Influencer seeding (free)", code: "SEEDING", priceSet: money("0.00") }],
      financialStatus: "PAID",
      tags: ["SEEDING", "partner-hub", `influencer-${tagSafe(ctx.influencer.username)}`, sendTag(ctx.sendId)],
      note,
      sourceIdentifier: ctx.sendId,
      customAttributes: [
        { key: "partner_hub_send_id", value: ctx.sendId },
        { key: "influencer", value: `@${ctx.influencer.username}` },
      ],
    },
    options: {
      inventoryBehaviour: "DECREMENT_OBEYING_POLICY",
      sendReceipt: false,
      sendFulfillmentReceipt: false,
    },
  };
}

function sameItems(a: RequestedItem[], b: SendItem[] | undefined): boolean {
  if (!b?.length) return false;
  const sig = (xs: { variantId?: string; quantity?: number }[]) =>
    xs.map((x) => `${x.variantId}x${x.quantity ?? 1}`).sort().join(",");
  return sig(a) === sig(b);
}

export interface CreateSendInput {
  influencerId: string;
  items: RequestedItem[];
  note?: string;
  dryRun?: boolean;
  createdBy: string;
}

export interface CreateSendResult {
  ok: true;
  dryRun?: boolean;
  duplicate?: boolean;
  sendId?: string;
  orderId?: string;
  orderName?: string;
  orderAdminUrl?: string;
  items: SendItem[];
  stock: StockLine[];
  warnings: string[];
  retailValue: number;
  orderInput?: unknown;
}

type OrderCreated = { id: string; name: string };

export async function createSend(deps: Deps, shopify: Shopify, input: CreateSendInput): Promise<CreateSendResult> {
  const db = deps.base44.asServiceRole.entities;
  const influencer = await getOr404(db.Influencer, input.influencerId, "Influencer");
  if (influencer.status === "blocked") {
    throw new HttpError(409, `@${influencer.username} is blocked, so nothing can be sent to them.`, "influencer_blocked");
  }
  const [addresses, socials, previous] = await Promise.all([
    db.Address.filter({ influencerId: influencer.id }),
    db.SocialAccount.filter({ influencerId: influencer.id }),
    listAll(db.Send, { influencerId: influencer.id }),
  ]);
  const shippingAddress = toShippingAddress(addresses[0]);

  if (!input.dryRun) {
    const now = deps.now().getTime();
    const recent = previous.find(
      (s) =>
        s.status !== "cancelled" &&
        s.created_date &&
        now - parseRecordDate(s.created_date) < DUPLICATE_WINDOW_MS &&
        sameItems(input.items, s.items),
    );
    if (recent?.shopifyOrderName) {
      return {
        ok: true,
        duplicate: true,
        sendId: recent.id,
        orderId: recent.shopifyOrderId ?? undefined,
        orderName: recent.shopifyOrderName,
        orderAdminUrl: recent.shopifyOrderUrl ?? undefined,
        items: recent.items ?? [],
        stock: [],
        warnings: [`Already created ${recent.shopifyOrderName} for these items a few minutes ago; not creating another.`],
        retailValue: recent.retailValueGbp ?? 0,
      };
    }
    if (recent) {
      throw new HttpError(
        409,
        "An order for these exact items is still being confirmed with Shopify. Press SYNC in a few minutes before trying again.",
        "send_pending",
        { sendId: recent.id },
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
    currency,
  };

  if (input.dryRun) {
    return {
      ok: true,
      dryRun: true,
      items: plan.items,
      stock: plan.stock,
      warnings: plan.warnings,
      retailValue: plan.retailValue,
      orderInput: buildOrderInput(plan, { ...ctxBase, sendId: "DRY-RUN" }),
    };
  }

  // The Send exists before the order so a double submit is caught, and so an
  // order Shopify creates without answering can still be found by its tag.
  const send = await db.Send.create({
    influencerId: influencer.id,
    influencerEmail: influencer.email,
    status: "preparing",
    items: plan.items,
    retailValueGbp: plan.retailValue,
    createdByEmail: input.createdBy,
  });

  const vars = buildOrderInput(plan, { ...ctxBase, sendId: send.id });
  let order: OrderCreated;
  try {
    const res = await shopify.graphql<{
      orderCreate: { order: OrderCreated | null; userErrors: { field?: string[]; message: string; code?: string }[] };
    }>(ORDER_CREATE, vars, { idempotent: false });
    const errs = res.orderCreate.userErrors;
    if (errs.length || !res.orderCreate.order) {
      await db.Send.delete(send.id).catch(() => {});
      throw new HttpError(
        422,
        `Shopify refused the order: ${errs.map((e) => e.message).join("; ") || "no order returned"}.`,
        "shopify_rejected",
        { userErrors: errs },
      );
    }
    order = res.orderCreate.order;
  } catch (e) {
    if (!(e instanceof ShopifyError) || e.kind !== "uncertain") {
      if (!(e instanceof HttpError)) await db.Send.delete(send.id).catch(() => {});
      throw e;
    }
    const found = await findOrderByTag(deps, shopify, send.id);
    if (!found) {
      throw new HttpError(
        502,
        `Shopify didn't confirm the order. Don't retry yet: press SYNC in a few minutes and the hub will link the ` +
          `order if Shopify created it (tag ${sendTag(send.id)}).`,
        "shopify_uncertain",
        { sendId: send.id },
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
      lastSyncedAt: deps.now().toISOString(),
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
    retailValue: plan.retailValue,
  };
}

/** Looks for the order a send created, by the send's unique tag. */
export async function findOrderByTag(deps: Deps, shopify: Shopify, sendId: string): Promise<OrderCreated | null> {
  for (let i = 0; i < 2; i++) {
    await deps.sleep(2000);
    try {
      const res = await shopify.graphql<{ orders: { nodes: (OrderCreated & { cancelledAt: string | null })[] } }>(
        ORDERS_BY_QUERY,
        { query: `tag:'${sendTag(sendId)}'` },
      );
      if (res.orders.nodes[0]) return res.orders.nodes[0];
    } catch {
      // keep trying; the caller reports the uncertainty
    }
  }
  return null;
}

export function influencerSendSummary(sends: SendRecord[]) {
  return {
    total: sends.length,
    active: sends.filter((s) => ["preparing", "dispatched", "delivered", "overdue"].includes(s.status)).length,
    owesPost: sends.some((s) => ["dispatched", "delivered", "overdue"].includes(s.status)),
  };
}

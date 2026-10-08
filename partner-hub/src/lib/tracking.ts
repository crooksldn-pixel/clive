import { ORDERS_BY_QUERY, ORDERS_TRACKING } from "./queries.ts";
import { listAll, parseRecordDate } from "./records.ts";
import { sendTag } from "./sends.ts";
import { chunk, orderAdminUrl, orderGid, type Shopify } from "./shopify.ts";
import type { Deps, SendRecord } from "./types.ts";

export const DEFAULT_POST_WINDOW_DAYS = 21;
const TRACKED_STATUSES = ["preparing", "dispatched", "delivered", "overdue"];
const DEAD_FULFILLMENT = new Set(["CANCELLED", "ERROR", "FAILURE"]);
const DEAD_DISPLAY = new Set(["LABEL_VOIDED", "CANCELED", "FAILURE"]);
/** A send whose order never appeared in Shopify is removed after this long. */
const ORPHAN_TTL_MS = 30 * 60_000;

export interface FulfillmentInfo {
  id: string;
  status: string;
  displayStatus: string | null;
  createdAt: string;
  deliveredAt: string | null;
  inTransitAt?: string | null;
  estimatedDeliveryAt?: string | null;
  trackingInfo: { company: string | null; number: string | null; url: string | null }[];
}

export interface OrderTracking {
  __typename?: string;
  id: string;
  name: string;
  cancelledAt: string | null;
  displayFulfillmentStatus?: string;
  fulfillments: FulfillmentInfo[];
}

/** Names the portal's tracking-link helper recognises. */
export function normaliseCarrier(company: string | null | undefined): string | null {
  if (!company) return null;
  const c = company.trim();
  if (/^royal\s*mail/i.test(c)) return "Royal Mail";
  if (/^dpd/i.test(c)) return "DPD";
  return c;
}

function addDays(iso: string, days: number): string {
  return new Date(Date.parse(iso) + days * 86_400_000).toISOString();
}

function sameValue(a: unknown, b: unknown): boolean {
  if ((a ?? null) === (b ?? null)) return true;
  if (typeof a === "string" && typeof b === "string") {
    const ta = Date.parse(a);
    const tb = Date.parse(b);
    return !Number.isNaN(ta) && ta === tb && /\d{4}-\d{2}-\d{2}T/.test(a) && /\d{4}-\d{2}-\d{2}T/.test(b);
  }
  return false;
}

/**
 * Works out a send's status and tracking from its Shopify order. Returns only
 * the fields that changed, or null when nothing did.
 */
export function deriveSendUpdate(
  send: SendRecord,
  order: OrderTracking | null,
  now: Date,
  postWindowDays = DEFAULT_POST_WINDOW_DAYS,
): Partial<SendRecord> | null {
  if (send.status === "cancelled" || send.status === "posted") return null;

  let next: Partial<SendRecord>;
  if (!order) {
    next = { status: "cancelled", cancelledAt: send.cancelledAt ?? now.toISOString() };
  } else if (order.cancelledAt) {
    next = { status: "cancelled", cancelledAt: order.cancelledAt };
  } else {
    const live = (order.fulfillments ?? [])
      .filter((f) => !DEAD_FULFILLMENT.has(f.status) && !DEAD_DISPLAY.has(f.displayStatus ?? ""))
      .sort((a, b) => Date.parse(a.createdAt) - Date.parse(b.createdAt));
    if (!live.length) {
      next = {
        status: send.postedUrl ? "posted" : "preparing",
        dispatchedAt: null,
        postByDate: null,
        trackingNumber: null,
        trackingUrl: null,
        carrier: null,
        deliveredAt: null,
      };
    } else {
      const dispatchedAt = live[0].createdAt;
      const withNumber = live.filter((f) => f.trackingInfo?.some((t) => t.number));
      const t = withNumber.length ? withNumber[withNumber.length - 1].trackingInfo.find((x) => x.number) : undefined;
      const delivered = live.every((f) => f.displayStatus === "DELIVERED" || !!f.deliveredAt);
      const deliveredTimes = live.map((f) => f.deliveredAt).filter((d): d is string => !!d).sort();
      const deliveredAt = delivered
        ? deliveredTimes[deliveredTimes.length - 1] ?? send.deliveredAt ?? now.toISOString()
        : null;
      const postByDate = addDays(dispatchedAt, postWindowDays);
      let status: string = send.postedUrl ? "posted" : delivered ? "delivered" : "dispatched";
      if (status !== "posted" && now.getTime() > Date.parse(postByDate)) status = "overdue";
      next = {
        status,
        dispatchedAt,
        postByDate,
        deliveredAt,
        trackingNumber: t?.number ?? null,
        trackingUrl: t?.url ?? null,
        carrier: normaliseCarrier(t?.company),
      };
    }
  }

  const changed: Partial<SendRecord> = {};
  for (const [k, v] of Object.entries(next)) {
    if (!sameValue((send as unknown as Record<string, unknown>)[k], v)) {
      (changed as Record<string, unknown>)[k] = v;
    }
  }
  return Object.keys(changed).length ? changed : null;
}

export interface TrackingSummary {
  checked: number;
  updated: number;
  linked: number;
  removed: number;
  statuses: Record<string, number>;
  changes: { sendId: string; orderName?: string | null; from: string; to: string }[];
  errors: string[];
}

export async function syncTracking(
  deps: Deps,
  shopify: Shopify,
  opts: { sendIds?: string[] } = {},
): Promise<TrackingSummary> {
  const db = deps.base44.asServiceRole.entities;
  const now = deps.now();
  const windowDays = Number(deps.secret("POST_WINDOW_DAYS")) || DEFAULT_POST_WINDOW_DAYS;

  let sends: SendRecord[];
  if (opts.sendIds) {
    sends = (await Promise.all(opts.sendIds.map((id) => db.Send.get(id).catch(() => null)))).filter(
      (s): s is SendRecord => !!s,
    );
  } else {
    sends = await listAll(db.Send);
  }

  const summary: TrackingSummary = { checked: 0, updated: 0, linked: 0, removed: 0, statuses: {}, changes: [], errors: [] };

  // Sends made before this version have no influencerEmail, which the
  // row-level security rule for Send needs. Fill it in once.
  for (const s of sends.filter((x) => !x.influencerEmail && x.influencerId)) {
    try {
      const inf = await db.Influencer.get(s.influencerId);
      if (inf?.email) {
        await db.Send.update(s.id, { influencerEmail: inf.email });
        s.influencerEmail = inf.email;
      }
    } catch {
      // influencer deleted; nothing to fill in
    }
  }

  const active = sends.filter((s) => TRACKED_STATUSES.includes(s.status) || (!!s.postedUrl && s.status !== "posted"));

  // Sends this hub created whose order Shopify never confirmed.
  for (const s of active.filter((s) => !s.shopifyOrderId && s.createdByEmail)) {
    const age = now.getTime() - parseRecordDate(s.created_date);
    if (!(age > 2 * 60_000)) continue;
    try {
      const res = await shopify.graphql<{ orders: { nodes: { id: string; name: string }[] } }>(ORDERS_BY_QUERY, {
        query: `tag:'${sendTag(s.id)}'`,
      });
      const found = res.orders.nodes[0];
      if (found) {
        Object.assign(s, {
          shopifyOrderId: found.id,
          shopifyOrderName: found.name,
          shopifyOrderUrl: orderAdminUrl(shopify.config, found.id),
        });
        await db.Send.update(s.id, {
          shopifyOrderId: found.id,
          shopifyOrderName: found.name,
          shopifyOrderUrl: s.shopifyOrderUrl,
        });
        summary.linked++;
      } else if (age > ORPHAN_TTL_MS) {
        await db.Send.delete(s.id);
        summary.removed++;
      }
    } catch (e) {
      summary.errors.push(`send ${s.id}: ${(e as Error).message}`);
    }
  }

  const withOrder = active.filter((s) => orderGid(s.shopifyOrderId));
  for (const group of chunk(withOrder, 50)) {
    const ids = group.map((s) => orderGid(s.shopifyOrderId)!);
    let nodes: (OrderTracking | null)[];
    try {
      nodes = (await shopify.graphql<{ nodes: (OrderTracking | null)[] }>(ORDERS_TRACKING, { ids })).nodes;
    } catch (e) {
      summary.errors.push((e as Error).message);
      continue;
    }
    const byId = new Map(nodes.filter((n): n is OrderTracking => n?.__typename === "Order").map((n) => [n.id, n]));
    for (const s of group) {
      summary.checked++;
      const order = byId.get(orderGid(s.shopifyOrderId)!) ?? null;
      const update = deriveSendUpdate(s, order, now, windowDays);
      const finalStatus = (update?.status ?? s.status) as string;
      summary.statuses[finalStatus] = (summary.statuses[finalStatus] ?? 0) + 1;
      if (!update) continue;
      try {
        await db.Send.update(s.id, { ...update, lastSyncedAt: now.toISOString() });
        summary.updated++;
        if (update.status && update.status !== s.status) {
          summary.changes.push({ sendId: s.id, orderName: s.shopifyOrderName, from: s.status, to: update.status });
        }
      } catch (e) {
        summary.errors.push(`send ${s.id}: ${(e as Error).message}`);
      }
    }
  }
  return summary;
}

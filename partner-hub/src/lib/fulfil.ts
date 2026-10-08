import { HttpError } from "./http.ts";
import { FULFILLMENT_CREATE, FULFILLMENT_ORDERS } from "./queries.ts";
import { getOr404 } from "./records.ts";
import { orderGid, type Shopify } from "./shopify.ts";
import { DEFAULT_POST_WINDOW_DAYS, normaliseCarrier, syncTracking } from "./tracking.ts";
import type { Deps, SendRecord } from "./types.ts";

export interface MarkShippedInput {
  sendId: string;
  trackingNumber: string;
  carrier: string;
  trackingUrl?: string;
  notifyCustomer?: boolean;
}

export function parseMarkShipped(body: Record<string, unknown>): MarkShippedInput {
  const sendId = typeof body.sendId === "string" ? body.sendId.trim() : "";
  const trackingNumber = typeof body.trackingNumber === "string" ? body.trackingNumber.replace(/\s+/g, "").trim() : "";
  const carrier = typeof body.carrier === "string" ? body.carrier.trim() : "";
  const trackingUrl = typeof body.trackingUrl === "string" && body.trackingUrl.trim() ? body.trackingUrl.trim() : undefined;
  if (!sendId) throw new HttpError(400, "Missing sendId.", "bad_request");
  if (!/^[A-Za-z0-9-]{4,60}$/.test(trackingNumber)) {
    throw new HttpError(400, "Enter the tracking number (letters and digits only).", "bad_tracking_number");
  }
  if (!carrier || carrier.length > 60) throw new HttpError(400, "Enter the carrier (e.g. Royal Mail, DPD, Evri).", "bad_carrier");
  if (trackingUrl && !/^https:\/\/\S+$/.test(trackingUrl)) {
    throw new HttpError(400, "The tracking link must start with https://", "bad_tracking_url");
  }
  return { sendId, trackingNumber, carrier, trackingUrl, notifyCustomer: body.notifyCustomer === true };
}

/**
 * For parcels shipped outside Shopify's label flow: fulfils the order in
 * Shopify with the tracking number, then refreshes the send from Shopify.
 */
export async function markShipped(deps: Deps, shopify: Shopify, input: MarkShippedInput) {
  const db = deps.base44.asServiceRole.entities;
  const send = await getOr404(db.Send, input.sendId, "Send");
  if (send.status === "cancelled") throw new HttpError(409, "This send was cancelled.", "send_cancelled");
  const orderId = orderGid(send.shopifyOrderId);
  if (!orderId) throw new HttpError(409, "This send has no Shopify order yet.", "no_order");

  const data = await shopify.graphql<{
    order: {
      id: string;
      name: string;
      cancelledAt: string | null;
      fulfillmentOrders: { nodes: { id: string; status: string; supportedActions: { action: string }[] }[] };
    } | null;
  }>(FULFILLMENT_ORDERS, { id: orderId });
  if (!data.order) throw new HttpError(404, `Shopify order ${send.shopifyOrderName ?? orderId} no longer exists.`, "order_missing");
  if (data.order.cancelledAt) throw new HttpError(409, `${data.order.name} is cancelled in Shopify.`, "order_cancelled");

  const open = data.order.fulfillmentOrders.nodes.filter((fo) =>
    fo.supportedActions.some((a) => a.action === "CREATE_FULFILLMENT")
  );
  const warnings: string[] = [];

  if (open.length) {
    const res = await shopify.graphql<{
      fulfillmentCreate: { fulfillment: { id: string } | null; userErrors: { message: string }[] };
    }>(
      FULFILLMENT_CREATE,
      {
        fulfillment: {
          lineItemsByFulfillmentOrder: open.map((fo) => ({ fulfillmentOrderId: fo.id })),
          trackingInfo: {
            number: input.trackingNumber,
            company: input.carrier,
            ...(input.trackingUrl ? { url: input.trackingUrl } : {}),
          },
          notifyCustomer: input.notifyCustomer ?? false,
        },
      },
      { idempotent: false },
    );
    if (res.fulfillmentCreate.userErrors.length || !res.fulfillmentCreate.fulfillment) {
      throw new HttpError(
        422,
        `Shopify refused the fulfilment: ${res.fulfillmentCreate.userErrors.map((e) => e.message).join("; ")}`,
        "shopify_rejected",
      );
    }
    await syncTracking(deps, shopify, { sendIds: [send.id] });
  } else {
    // Already fulfilled in Shopify (e.g. marked fulfilled without a number):
    // keep Shopify as it is and record the number in the hub.
    warnings.push(`${data.order.name} is already fulfilled in Shopify, so the tracking number was saved in the hub only.`);
    const now = deps.now();
    const dispatchedAt = send.dispatchedAt ?? now.toISOString();
    const days = Number(deps.secret("POST_WINDOW_DAYS")) || DEFAULT_POST_WINDOW_DAYS;
    const update: Partial<SendRecord> = {
      trackingNumber: input.trackingNumber,
      carrier: normaliseCarrier(input.carrier),
      trackingUrl: input.trackingUrl ?? null,
      dispatchedAt,
      postByDate: new Date(Date.parse(dispatchedAt) + days * 86_400_000).toISOString(),
      status: send.status === "preparing" ? "dispatched" : send.status,
      lastSyncedAt: now.toISOString(),
    };
    await db.Send.update(send.id, update);
  }
  return { ok: true as const, send: await db.Send.get(send.id), warnings };
}

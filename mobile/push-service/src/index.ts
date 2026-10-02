/**
 * CROOKSLDN push service — a Cloudflare Worker.
 *
 * Two jobs:
 *  1. Shipping updates. Shopify calls /v1/shopify/webhooks when an order is
 *     created and when it ships; the worker finds the phone that placed the
 *     order and sends "on its way" (then "out for delivery", "delivered" if
 *     the carrier reports them).
 *  2. Drop alerts. You POST /v1/broadcast with the secret; every phone that
 *     switched drop alerts on gets it.
 *
 * What it stores (Workers KV): random install ids, Expo push tokens, numeric
 * order ids. No names, emails, addresses or order contents — the webhook
 * bodies that carry those are read and dropped.
 *
 * Who can tie an order to a phone: the first install to claim it, and only
 * while the order is fresh (Shopify reported it created within CLAIM_WINDOW).
 * The app claims within seconds of checkout, so an old order can never be
 * claimed by anyone, and a new one only by guessing its id before the buyer
 * does.
 */

export interface Env {
  PUSH: KVNamespace;
  SHOPIFY_WEBHOOK_SECRET: string;
  BROADCAST_SECRET: string;
  EXPO_ACCESS_TOKEN?: string;
  SHOP_NAME?: string;
  /** Tests point this at a fake; production leaves it unset. */
  EXPO_PUSH_URL?: string;
}

const CLAIM_WINDOW_S = 6 * 60 * 60;
const CLAIM_KEEP_S = 120 * 24 * 60 * 60;
const DEDUPE_S = 3 * 24 * 60 * 60;
const EXPO_PUSH = 'https://exp.host/--/api/v2/push/send';

const INSTALL_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const TOKEN_RE = /^Expo(nent)?PushToken\[[A-Za-z0-9_-]{10,100}\]$/;
const ORDER_RE = /^\d{1,20}$/;

type Device = { token: string; platform: 'ios' | 'android'; updatedAt: string };
type Claim = { installId: string; confirmed: boolean };
type DropMeta = { token: string };
type Message = { to: string; title: string; body: string; data: { url: string }; channelId: 'orders' | 'drops' };

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const empty = (status = 204): Response => new Response(null, { status });

export default {
  async fetch(req: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(req.url);
    const route = `${req.method} ${url.pathname}`;
    try {
      switch (route) {
        case 'GET /v1/health':
          return json({ ok: true });
        case 'POST /v1/devices':
          return await registerDevice(req, env);
        case 'POST /v1/orders/claim':
          return await claimOrder(req, env);
        case 'PUT /v1/topics/drops':
          return await setDrops(req, env);
        case 'POST /v1/shopify/webhooks':
          return await shopifyWebhook(req, env, ctx);
        case 'POST /v1/broadcast':
          return await broadcast(req, env);
        default:
          return json({ error: 'not found' }, 404);
      }
    } catch (e) {
      if (e instanceof BadRequest) return json({ error: e.message }, 400);
      console.error('unhandled', route, (e as Error)?.message);
      return json({ error: 'server error' }, 500);
    }
  },
};

class BadRequest extends Error {}

async function body<T>(req: Request, max = 4096): Promise<T> {
  const text = await req.text();
  if (text.length > max) throw new BadRequest('body too large');
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new BadRequest('invalid json');
  }
}

function need(ok: boolean, message: string): void {
  if (!ok) throw new BadRequest(message);
}

/* ── app endpoints ───────────────────────────────────────────────────── */

async function registerDevice(req: Request, env: Env): Promise<Response> {
  const b = await body<{ installId?: string; token?: string; platform?: string }>(req);
  need(typeof b.installId === 'string' && INSTALL_RE.test(b.installId), 'installId');
  need(typeof b.token === 'string' && TOKEN_RE.test(b.token), 'token');
  need(b.platform === 'ios' || b.platform === 'android', 'platform');
  const device: Device = { token: b.token!, platform: b.platform as Device['platform'], updatedAt: new Date().toISOString() };
  await env.PUSH.put(`device:${b.installId}`, JSON.stringify(device));
  /* Tokens rotate. A drop subscriber's copy is kept in step. */
  if (await env.PUSH.get(`drops:${b.installId}`)) {
    await env.PUSH.put(`drops:${b.installId}`, '1', { metadata: { token: device.token } satisfies DropMeta });
  }
  return empty();
}

async function claimOrder(req: Request, env: Env): Promise<Response> {
  const b = await body<{ installId?: string; orderId?: string }>(req);
  need(typeof b.installId === 'string' && INSTALL_RE.test(b.installId), 'installId');
  need(typeof b.orderId === 'string' && ORDER_RE.test(b.orderId), 'orderId');
  const key = `claim:${b.orderId}`;

  const existing = await env.PUSH.get<Claim>(key, 'json');
  if (existing && existing.installId !== b.installId) return json({ error: 'already claimed' }, 409);
  if (existing?.confirmed) return json({ state: 'claimed' }, 200);

  const seen = await env.PUSH.get(`seen:${b.orderId}`);
  const claim: Claim = { installId: b.installId!, confirmed: Boolean(seen) };
  await env.PUSH.put(key, JSON.stringify(claim), { expirationTtl: seen ? CLAIM_KEEP_S : CLAIM_WINDOW_S });
  console.log('claim', b.orderId, claim.confirmed ? 'confirmed' : 'pending');
  return json({ state: claim.confirmed ? 'claimed' : 'pending' }, 202);
}

async function setDrops(req: Request, env: Env): Promise<Response> {
  const b = await body<{ installId?: string; on?: boolean }>(req);
  need(typeof b.installId === 'string' && INSTALL_RE.test(b.installId), 'installId');
  need(typeof b.on === 'boolean', 'on');
  const key = `drops:${b.installId}`;
  if (!b.on) {
    await env.PUSH.delete(key);
    return empty();
  }
  const device = await env.PUSH.get<Device>(`device:${b.installId}`, 'json');
  if (!device) return json({ error: 'register the device first' }, 409);
  await env.PUSH.put(key, '1', { metadata: { token: device.token } satisfies DropMeta });
  return empty();
}

/* ── Shopify ─────────────────────────────────────────────────────────── */

function b64ToBytes(b64: string): Uint8Array<ArrayBuffer> | null {
  try {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  } catch {
    return null;
  }
}

/** Shopify signs the raw body with HMAC-SHA256; verify() compares in constant time. */
export async function verifyShopify(raw: ArrayBuffer, header: string | null, secret: string): Promise<boolean> {
  if (!header || !secret) return false;
  const sig = b64ToBytes(header);
  if (!sig || sig.length !== 32) return false;
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['verify']);
  return crypto.subtle.verify('HMAC', key, sig, raw);
}

type Fulfillment = {
  id?: number;
  order_id?: number;
  name?: string;
  shipment_status?: string | null;
  tracking_company?: string | null;
  tracking_url?: string | null;
  tracking_urls?: string[] | null;
};

async function shopifyWebhook(req: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  const raw = await req.arrayBuffer();
  if (!(await verifyShopify(raw, req.headers.get('x-shopify-hmac-sha256'), env.SHOPIFY_WEBHOOK_SECRET))) {
    return json({ error: 'bad signature' }, 401);
  }

  /* Shopify retries until it gets a 200, so the same event can arrive twice.
     Marked as handled only once it has been — a failed attempt is retried. */
  const eventId = req.headers.get('x-shopify-event-id') ?? req.headers.get('x-shopify-webhook-id');
  if (eventId && (await env.PUSH.get(`hook:${eventId}`))) return empty(200);
  const handled = async (): Promise<Response> => {
    if (eventId) await env.PUSH.put(`hook:${eventId}`, '1', { expirationTtl: DEDUPE_S });
    return empty(200);
  };

  const topic = req.headers.get('x-shopify-topic') ?? '';
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(new TextDecoder().decode(raw));
  } catch {
    return json({ error: 'invalid json' }, 400);
  }

  if (topic === 'orders/create') {
    const id = String(payload.id ?? '');
    if (ORDER_RE.test(id)) await orderSeen(env, id);
    return handled();
  }

  if (topic === 'fulfillments/create' || topic === 'fulfillments/update') {
    const f = payload as Fulfillment;
    const status = topic === 'fulfillments/create' ? 'shipped' : f.shipment_status ?? '';
    if (!['shipped', 'out_for_delivery', 'delivered'].includes(status)) return handled();
    /* Answer Shopify now; the push goes out after. */
    ctx.waitUntil(notifyFulfillment(env, f, status as Stage).catch((e) => console.error('notify', e?.message)));
    return handled();
  }

  return handled();
}

async function orderSeen(env: Env, orderId: string): Promise<void> {
  await env.PUSH.put(`seen:${orderId}`, '1', { expirationTtl: CLAIM_WINDOW_S });
  const key = `claim:${orderId}`;
  const pending = await env.PUSH.get<Claim>(key, 'json');
  if (pending && !pending.confirmed) {
    await env.PUSH.put(key, JSON.stringify({ ...pending, confirmed: true }), { expirationTtl: CLAIM_KEEP_S });
    console.log('claim', orderId, 'confirmed by webhook');
  }
}

type Stage = 'shipped' | 'out_for_delivery' | 'delivered';

export function shippingMessage(shop: string, f: Fulfillment, stage: Stage): Omit<Message, 'to'> {
  const order = f.name ? ` ${f.name.replace(/\.\d+$/, '')}` : '';
  const carrier = f.tracking_company ? ` with ${f.tracking_company}` : '';
  const tracking = [f.tracking_url, ...(f.tracking_urls ?? [])].find((u) => typeof u === 'string' && u.startsWith('https://'));
  const url = tracking ?? '/orders';
  const text: Record<Stage, [string, string]> = {
    shipped: ['On its way', `Your ${shop} order${order} has shipped${carrier}.${tracking ? ' Tap to track it.' : ''}`],
    out_for_delivery: ['Out for delivery', `Your ${shop} order${order} is out for delivery.`],
    delivered: ['Delivered', `Your ${shop} order${order} has been delivered.`],
  };
  const [title, bodyText] = text[stage];
  return { title, body: bodyText, data: { url }, channelId: 'orders' };
}

async function notifyFulfillment(env: Env, f: Fulfillment, stage: Stage): Promise<void> {
  const orderId = String(f.order_id ?? '');
  if (!ORDER_RE.test(orderId)) return;
  const claim = await env.PUSH.get<Claim>(`claim:${orderId}`, 'json');
  if (!claim?.confirmed) return;

  const sentKey = `sent:${f.id ?? orderId}:${stage}`;
  if (await env.PUSH.get(sentKey)) return;
  const device = await env.PUSH.get<Device>(`device:${claim.installId}`, 'json');
  if (!device) {
    console.log('fulfillment', orderId, stage, 'claimed but notifications not on');
    return;
  }
  await env.PUSH.put(sentKey, '1', { expirationTtl: CLAIM_KEEP_S });
  const msg = shippingMessage(env.SHOP_NAME || 'CROOKSLDN', f, stage);
  const r = await sendExpo(env, [{ ...msg, to: device.token }], [claim.installId]);
  console.log('fulfillment', orderId, stage, r.sent ? 'sent' : 'failed');
}

/* ── drop alerts ─────────────────────────────────────────────────────── */

async function constantTimeEqual(a: string, b: string): Promise<boolean> {
  const enc = new TextEncoder();
  const [ha, hb] = await Promise.all([
    crypto.subtle.digest('SHA-256', enc.encode(a)),
    crypto.subtle.digest('SHA-256', enc.encode(b)),
  ]);
  const x = new Uint8Array(ha);
  const y = new Uint8Array(hb);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

async function broadcast(req: Request, env: Env): Promise<Response> {
  const auth = req.headers.get('authorization') ?? '';
  const given = auth.startsWith('Bearer ') ? auth.slice(7) : '';
  if (!env.BROADCAST_SECRET || env.BROADCAST_SECRET.length < 24 || !(await constantTimeEqual(given, env.BROADCAST_SECRET))) {
    return json({ error: 'unauthorised' }, 401);
  }
  const b = await body<{ title?: string; body?: string; path?: string }>(req);
  need(typeof b.title === 'string' && b.title.trim().length > 0 && b.title.length <= 60, 'title (1–60 characters)');
  need(typeof b.body === 'string' && b.body.trim().length > 0 && b.body.length <= 180, 'body (1–180 characters)');
  need(b.path === undefined || (typeof b.path === 'string' && /^\/[A-Za-z0-9/_-]{0,200}$/.test(b.path)), 'path must be an app path like /products/v1-hoodie');

  const targets: { installId: string; token: string }[] = [];
  let cursor: string | undefined;
  do {
    const page = await env.PUSH.list<DropMeta>({ prefix: 'drops:', cursor });
    for (const k of page.keys) if (k.metadata?.token) targets.push({ installId: k.name.slice(6), token: k.metadata.token });
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);

  const msgs: Message[] = targets.map((t) => ({
    to: t.token,
    title: b.title!.trim(),
    body: b.body!.trim(),
    data: { url: b.path ?? '/' },
    channelId: 'drops',
  }));
  const r = await sendExpo(env, msgs, targets.map((t) => t.installId));
  return json({ subscribers: targets.length, ...r });
}

/* ── Expo push ───────────────────────────────────────────────────────── */

type Ticket = { status: 'ok' | 'error'; message?: string; details?: { error?: string } };

/**
 * Sends in batches of 100 (Expo's limit). A phone that uninstalled the app
 * comes back as DeviceNotRegistered and is forgotten, so the list does not
 * fill with dead tokens.
 */
async function sendExpo(env: Env, msgs: Message[], owners: string[]): Promise<{ sent: number; failed: number; removed: number }> {
  let sent = 0;
  let failed = 0;
  let removed = 0;
  for (let i = 0; i < msgs.length; i += 100) {
    const batch = msgs.slice(i, i + 100).map((m) => ({ ...m, sound: 'default', priority: 'high' }));
    const headers: Record<string, string> = { 'content-type': 'application/json', accept: 'application/json' };
    if (env.EXPO_ACCESS_TOKEN) headers.authorization = `Bearer ${env.EXPO_ACCESS_TOKEN}`;
    let tickets: Ticket[] = [];
    try {
      const res = await fetch(env.EXPO_PUSH_URL || EXPO_PUSH, { method: 'POST', headers, body: JSON.stringify(batch) });
      if (!res.ok) {
        failed += batch.length;
        console.error('expo push http', res.status);
        continue;
      }
      tickets = ((await res.json()) as { data?: Ticket[] }).data ?? [];
    } catch (e) {
      failed += batch.length;
      console.error('expo push', (e as Error)?.message);
      continue;
    }
    for (let j = 0; j < batch.length; j++) {
      const t = tickets[j];
      if (t?.status === 'ok') sent++;
      else {
        failed++;
        if (t?.details?.error === 'DeviceNotRegistered') {
          const owner = owners[i + j];
          await env.PUSH.delete(`device:${owner}`);
          await env.PUSH.delete(`drops:${owner}`);
          removed++;
        }
      }
    }
  }
  return { sent, failed, removed };
}

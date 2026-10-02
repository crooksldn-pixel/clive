/**
 * Runs the worker in Node against an in-memory KV and a fake Expo endpoint.
 * `npm test` — no Cloudflare account needed.
 */
import { createHmac, randomUUID } from 'node:crypto';
import { beforeEach, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import worker, { shippingMessage, type Env } from '../src/index.ts';

type Entry = { value: string; metadata?: unknown };

class MemoryKV {
  map = new Map<string, Entry>();
  async get(key: string, type?: 'json' | 'text') {
    const e = this.map.get(key);
    if (!e) return null;
    return type === 'json' ? JSON.parse(e.value) : e.value;
  }
  async put(key: string, value: string, opts?: { metadata?: unknown; expirationTtl?: number }) {
    this.map.set(key, { value, metadata: opts?.metadata });
  }
  async delete(key: string) {
    this.map.delete(key);
  }
  async list(opts: { prefix?: string; cursor?: string }) {
    const keys = [...this.map.entries()]
      .filter(([k]) => k.startsWith(opts.prefix ?? ''))
      .map(([name, e]) => ({ name, metadata: e.metadata }));
    return { keys, list_complete: true, cursor: undefined };
  }
}

const SECRET = 'shpss_test_webhook_secret';
const BROADCAST = 'b'.repeat(40);
let kv: MemoryKV;
let env: Env;
let sentToExpo: Record<string, unknown>[][];
let expoReply: (batch: Record<string, unknown>[]) => unknown;

const realFetch = globalThis.fetch;
globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input instanceof Request ? input.url : input);
  if (url === 'https://expo.test/send') {
    const batch = JSON.parse(String(init?.body)) as Record<string, unknown>[];
    sentToExpo.push(batch);
    return new Response(JSON.stringify(expoReply(batch)), { status: 200 });
  }
  return realFetch(input, init);
}) as typeof fetch;

beforeEach(() => {
  kv = new MemoryKV();
  sentToExpo = [];
  expoReply = (batch) => ({ data: batch.map(() => ({ status: 'ok', id: randomUUID() })) });
  env = {
    PUSH: kv as unknown as KVNamespace,
    SHOPIFY_WEBHOOK_SECRET: SECRET,
    BROADCAST_SECRET: BROADCAST,
    SHOP_NAME: 'CROOKSLDN',
    EXPO_PUSH_URL: 'https://expo.test/send',
  };
});

async function call(method: string, path: string, body?: unknown, headers: Record<string, string> = {}) {
  const waits: Promise<unknown>[] = [];
  const ctx = { waitUntil: (p: Promise<unknown>) => waits.push(p), passThroughOnException() {} } as unknown as ExecutionContext;
  const req = new Request(`https://push.test${path}`, {
    method,
    headers: { 'content-type': 'application/json', ...headers },
    body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body),
  });
  const res = await worker.fetch(req, env, ctx);
  await Promise.all(waits);
  return res;
}

function signed(topic: string, payload: unknown, eventId = randomUUID(), secret = SECRET) {
  const raw = JSON.stringify(payload);
  const hmac = createHmac('sha256', secret).update(raw).digest('base64');
  return call('POST', '/v1/shopify/webhooks', raw, {
    'x-shopify-topic': topic,
    'x-shopify-hmac-sha256': hmac,
    'x-shopify-event-id': eventId,
  });
}

const PHONE = '1b4e28ba-2fa1-41d2-883f-0016d3cca427';
const OTHER = '6fa459ea-ee8a-4ca4-894e-db77e160355e';
const TOKEN = 'ExponentPushToken[abcdefghijklmnop]';
const ORDER = '6123456789012';
const SHIPPED = {
  id: 99001,
  order_id: Number(ORDER),
  name: '#1042.1',
  tracking_company: 'Royal Mail',
  tracking_url: 'https://www.royalmail.com/track-your-item#/tracking-results/AB123456789GB',
};

async function register(installId = PHONE, token = TOKEN) {
  return call('POST', '/v1/devices', { installId, token, platform: 'ios' });
}

describe('app endpoints', () => {
  it('answers health', async () => {
    assert.equal((await call('GET', '/v1/health')).status, 200);
  });

  it('rejects malformed devices and stores a good one', async () => {
    assert.equal((await call('POST', '/v1/devices', { installId: 'nope', token: TOKEN, platform: 'ios' })).status, 400);
    assert.equal((await call('POST', '/v1/devices', { installId: PHONE, token: 'not-a-token', platform: 'ios' })).status, 400);
    assert.equal((await call('POST', '/v1/devices', { installId: PHONE, token: TOKEN, platform: 'web' })).status, 400);
    assert.equal((await call('POST', '/v1/devices', '{bad json')).status, 400);
    assert.equal((await register()).status, 204);
    assert.equal((await kv.get(`device:${PHONE}`, 'json')).token, TOKEN);
  });

  it('will not switch on drop alerts for an unregistered phone', async () => {
    assert.equal((await call('PUT', '/v1/topics/drops', { installId: PHONE, on: true })).status, 409);
    await register();
    assert.equal((await call('PUT', '/v1/topics/drops', { installId: PHONE, on: true })).status, 204);
    assert.ok(await kv.get(`drops:${PHONE}`));
    assert.equal((await call('PUT', '/v1/topics/drops', { installId: PHONE, on: false })).status, 204);
    assert.equal(await kv.get(`drops:${PHONE}`), null);
  });

  it('keeps a drop subscriber in step when the push token rotates', async () => {
    await register();
    await call('PUT', '/v1/topics/drops', { installId: PHONE, on: true });
    await register(PHONE, 'ExponentPushToken[rotatedtoken0001]');
    assert.deepEqual(kv.map.get(`drops:${PHONE}`)?.metadata, { token: 'ExponentPushToken[rotatedtoken0001]' });
  });
});

describe('Shopify webhook signature', () => {
  it('refuses unsigned, wrongly signed and tampered requests', async () => {
    const unsigned = await call('POST', '/v1/shopify/webhooks', { id: 1 }, { 'x-shopify-topic': 'orders/create' });
    assert.equal(unsigned.status, 401);
    assert.equal((await signed('orders/create', { id: Number(ORDER) }, undefined, 'wrong-secret')).status, 401);

    const raw = JSON.stringify({ id: Number(ORDER) });
    const hmac = createHmac('sha256', SECRET).update(raw).digest('base64');
    const tampered = await call('POST', '/v1/shopify/webhooks', raw.replace('6', '7'), {
      'x-shopify-topic': 'orders/create',
      'x-shopify-hmac-sha256': hmac,
    });
    assert.equal(tampered.status, 401);
    assert.equal(await kv.get(`seen:${ORDER}`), null);
  });

  it('accepts a correctly signed request', async () => {
    assert.equal((await signed('orders/create', { id: Number(ORDER) })).status, 200);
    assert.ok(await kv.get(`seen:${ORDER}`));
  });
});

describe('shipping notifications', () => {
  it('claim first, then Shopify reports the order: confirmed, and the shipment is pushed', async () => {
    await register();
    const claim = await call('POST', '/v1/orders/claim', { installId: PHONE, orderId: ORDER });
    assert.equal(claim.status, 202);
    assert.equal(((await claim.json()) as { state: string }).state, 'pending');

    await signed('orders/create', { id: Number(ORDER) });
    assert.equal((await kv.get(`claim:${ORDER}`, 'json')).confirmed, true);

    await signed('fulfillments/create', SHIPPED);
    assert.equal(sentToExpo.length, 1);
    const [msg] = sentToExpo[0];
    assert.equal(msg.to, TOKEN);
    assert.equal(msg.title, 'On its way');
    assert.equal(msg.body, 'Your CROOKSLDN order #1042 has shipped with Royal Mail. Tap to track it.');
    assert.deepEqual(msg.data, { url: SHIPPED.tracking_url });
    assert.equal(msg.channelId, 'orders');
  });

  it('Shopify reports the order first, then the claim: confirmed immediately', async () => {
    await signed('orders/create', { id: Number(ORDER) });
    const claim = await call('POST', '/v1/orders/claim', { installId: PHONE, orderId: ORDER });
    assert.equal(((await claim.json()) as { state: string }).state, 'claimed');
  });

  it('first claim wins; a second phone is refused', async () => {
    await signed('orders/create', { id: Number(ORDER) });
    await call('POST', '/v1/orders/claim', { installId: PHONE, orderId: ORDER });
    assert.equal((await call('POST', '/v1/orders/claim', { installId: OTHER, orderId: ORDER })).status, 409);
    /* The rightful phone re-claiming is fine. */
    assert.equal((await call('POST', '/v1/orders/claim', { installId: PHONE, orderId: ORDER })).status, 200);
  });

  it('an old order (no fresh orders/create) can be claimed but never notifies', async () => {
    await register(OTHER);
    await call('POST', '/v1/orders/claim', { installId: OTHER, orderId: ORDER });
    await signed('fulfillments/create', SHIPPED);
    assert.equal(sentToExpo.length, 0);
  });

  it('a retried webhook and a repeated event push once', async () => {
    await register();
    await signed('orders/create', { id: Number(ORDER) });
    await call('POST', '/v1/orders/claim', { installId: PHONE, orderId: ORDER });
    const id = randomUUID();
    await signed('fulfillments/create', SHIPPED, id);
    await signed('fulfillments/create', SHIPPED, id);
    await signed('fulfillments/create', SHIPPED);
    assert.equal(sentToExpo.length, 1);
  });

  it('carrier updates: in transit is quiet, delivered is pushed', async () => {
    await register();
    await signed('orders/create', { id: Number(ORDER) });
    await call('POST', '/v1/orders/claim', { installId: PHONE, orderId: ORDER });
    await signed('fulfillments/update', { ...SHIPPED, shipment_status: 'in_transit' });
    assert.equal(sentToExpo.length, 0);
    await signed('fulfillments/update', { ...SHIPPED, shipment_status: 'delivered' });
    assert.equal(sentToExpo.length, 1);
    assert.equal(sentToExpo[0][0].title, 'Delivered');
  });

  it('claimed but notifications never switched on: nothing is sent', async () => {
    await signed('orders/create', { id: Number(ORDER) });
    await call('POST', '/v1/orders/claim', { installId: PHONE, orderId: ORDER });
    await signed('fulfillments/create', SHIPPED);
    assert.equal(sentToExpo.length, 0);
  });

  it('without a tracking link the tap opens the Orders tab, and the copy does not promise one', () => {
    const m = shippingMessage('CROOKSLDN', { order_id: 1, name: '#1001.1' }, 'shipped');
    assert.equal(m.body, 'Your CROOKSLDN order #1001 has shipped.');
    assert.equal(m.data.url, '/orders');
  });
});

describe('drop broadcast', () => {
  const auth = { authorization: `Bearer ${BROADCAST}` };

  it('needs the secret', async () => {
    assert.equal((await call('POST', '/v1/broadcast', { title: 'x', body: 'y' })).status, 401);
    assert.equal((await call('POST', '/v1/broadcast', { title: 'x', body: 'y' }, { authorization: 'Bearer wrong' })).status, 401);
  });

  it('validates the message', async () => {
    assert.equal((await call('POST', '/v1/broadcast', { title: '', body: 'y' }, auth)).status, 400);
    assert.equal((await call('POST', '/v1/broadcast', { title: 'x', body: 'y', path: 'https://evil.example' }, auth)).status, 400);
  });

  it('reaches drop subscribers only, and forgets uninstalled phones', async () => {
    await register(PHONE);
    await register(OTHER, 'ExponentPushToken[othertoken000001]');
    await call('PUT', '/v1/topics/drops', { installId: PHONE, on: true });
    await call('PUT', '/v1/topics/drops', { installId: OTHER, on: true });
    const third = 'a3bb189e-8bf9-4888-9912-ace4e6543002';
    await register(third, 'ExponentPushToken[thirdtoken000001]'); /* registered, alerts off */

    expoReply = (batch) => ({
      data: batch.map((m) =>
        m.to === 'ExponentPushToken[othertoken000001]'
          ? { status: 'error', message: 'gone', details: { error: 'DeviceNotRegistered' } }
          : { status: 'ok', id: 'x' },
      ),
    });
    const res = await call('POST', '/v1/broadcast', { title: 'Drop 02 is live', body: 'Pink set is back.', path: '/products/pink-crsdr-hoodie' }, auth);
    assert.equal(res.status, 200);
    assert.deepEqual(await res.json(), { subscribers: 2, sent: 1, failed: 1, removed: 1 });
    assert.equal(sentToExpo[0].length, 2);
    assert.equal(sentToExpo[0][0].channelId, 'drops');
    assert.deepEqual(sentToExpo[0][0].data, { url: '/products/pink-crsdr-hoodie' });
    assert.equal(await kv.get(`device:${OTHER}`), null);
    assert.equal(await kv.get(`drops:${OTHER}`), null);
    assert.ok(await kv.get(`device:${third}`));
  });
});

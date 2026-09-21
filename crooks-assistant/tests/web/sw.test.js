/* The service worker, run under Node against a small stand-in for the worker globals.
 *
 * What is proved: it keeps the shell and nothing else; it never intercepts a POST, a call to
 * the Mac's endpoints, or anything from another origin; a navigation while the Mac is away
 * opens from the cached shell; a 5xx from the Tailscale proxy counts as "away" and a 4xx does
 * not; and a new build waits to be told before taking over.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ORIGIN = 'https://crooks.test';
const SOURCE = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'sw.js'), 'utf8').replace('__BUILD__', 'testbuild');

function boot() {
  const handlers = {};
  const fetched = [];
  const network = { mode: 'ok' };     // 'ok' | 'fail' | 'hang' | a numeric status
  const cacheStore = new Map();
  class FakeCache {
    constructor() { this.entries = new Map(); }
    async addAll(paths) { for (const p of paths) { const r = await sandbox.fetch({ url: ORIGIN + p, method: 'GET' }); if (!r.ok) throw new Error(`addAll ${p}`); this.entries.set(p, r); } }
    async put(key, response) { this.entries.set(key, response); }
    async match(key) { const r = this.entries.get(key); return r ? r.clone() : undefined; }
    keys() { return [...this.entries.keys()]; }
  }
  const caches = {
    async open(name) { if (!cacheStore.has(name)) cacheStore.set(name, new FakeCache()); return cacheStore.get(name); },
    async keys() { return [...cacheStore.keys()]; },
    async delete(name) { return cacheStore.delete(name); },
  };
  const calls = { skipWaiting: 0, claim: 0 };
  const sandbox = {
    console,
    Response,
    URL,
    caches,
    network,
    location: { origin: ORIGIN },
    clients: { claim: async () => { calls.claim += 1; } },
    skipWaiting: () => { calls.skipWaiting += 1; },
    addEventListener: (type, fn) => { handlers[type] = fn; },
    setTimeout: (fn, ms) => setTimeout(fn, Math.min(ms, 30)),   // the 4 s bound, shortened
    clearTimeout,
    fetch: async (request) => {
      const p = new URL(request.url).pathname;
      fetched.push(p);
      if (network.mode === 'fail') throw new TypeError('network down');
      if (network.mode === 'hang') return new Promise(() => {});
      const status = typeof network.mode === 'number' ? network.mode : 200;
      const type = network.type || (p.endsWith('.js') ? 'text/javascript' : 'text/html');
      return new Response(`${status === 200 ? 'fresh' : 'status'}:${p}`, { status, headers: { 'content-type': type } });
    },
  };
  sandbox.self = sandbox;
  vm.runInNewContext(SOURCE, sandbox, { filename: 'sw.js' });
  const fire = (type, request) => {
    const event = { request, response: null, waited: null, respondWith(p) { this.response = p; }, waitUntil(p) { this.waited = p; } };
    handlers[type](event);
    return event;
  };
  return { handlers, fetched, network, cacheStore, calls, fire, sandbox };
}

const SHELL = ['/', '/static/style.css', '/static/app.js', '/static/ui.js', '/static/action-state.js', '/static/live-state.js', '/static/telemetry.js', '/static/collide.js', '/static/touch.js', '/static/notify.js', '/static/orb.js', '/static/audio-viz.js',
  '/manifest.webmanifest', '/static/icon-192.png', '/static/icon-512.png', '/static/icon-maskable-192.png', '/static/icon-maskable-512.png'];

async function installed() {
  const w = boot();
  await w.fire('install').waited;
  return w;
}

test('install keeps exactly the shell, and does not push itself in front of the running page', async () => {
  const w = await installed();
  assert.deepEqual([...w.cacheStore.keys()], ['crooks-shell-testbuild']);
  assert.deepEqual(w.cacheStore.get('crooks-shell-testbuild').keys().sort(), [...SHELL].sort());
  assert.equal(w.calls.skipWaiting, 0);
});

test('activate drops older shells and claims the pages', async () => {
  const w = await installed();
  await w.sandbox.caches.open('crooks-shell-old');
  await w.fire('activate').waited;
  assert.deepEqual([...w.cacheStore.keys()], ['crooks-shell-testbuild']);
  assert.equal(w.calls.claim, 1);
});

test('a new build takes over only when the page says so', async () => {
  const w = await installed();
  w.handlers.message({ data: { type: 'something else' } });
  assert.equal(w.calls.skipWaiting, 0);
  w.handlers.message({ data: { type: 'SKIP_WAITING' } });
  assert.equal(w.calls.skipWaiting, 1);
});

test('nothing but the shell is ever intercepted', async () => {
  const w = await installed();
  const untouched = [
    { method: 'POST', url: `${ORIGIN}/turn` },
    { method: 'POST', url: `${ORIGIN}/speak` },
    { method: 'POST', url: `${ORIGIN}/cancel` },
    { method: 'POST', url: `${ORIGIN}/audio-test` },
    { method: 'GET', url: `${ORIGIN}/turn` },
    { method: 'GET', url: `${ORIGIN}/speak` },
    { method: 'GET', url: `${ORIGIN}/tts` },
    { method: 'GET', url: `${ORIGIN}/health` },
    { method: 'GET', url: `${ORIGIN}/health?fresh=1` },
    { method: 'GET', url: `${ORIGIN}/state/abc123` },
    { method: 'GET', url: `${ORIGIN}/ping` },
    { method: 'GET', url: `${ORIGIN}/voices` },
    { method: 'GET', url: `${ORIGIN}/tools` },
    { method: 'POST', url: `${ORIGIN}/actions/prop_abc123/commit` },
    { method: 'GET', url: `${ORIGIN}/actions/prop_abc123?session_id=s1` },
    { method: 'GET', url: `${ORIGIN}/whoami` },
    { method: 'GET', url: `${ORIGIN}/static/fixtures.js` },          // dev only, not shell
    { method: 'GET', url: `${ORIGIN}/static/app.js`, mode: 'cors', cross: true },
    { method: 'GET', url: 'https://api.example.com/static/app.js' },
    { method: 'POST', url: `${ORIGIN}/` },
  ];
  for (const request of untouched) {
    if (request.cross) request.url = 'https://elsewhere.test/static/app.js';
    const event = w.fire('fetch', request);
    assert.equal(event.response, null, `${request.method} ${request.url} must go straight to the network`);
  }
  assert.deepEqual(w.fetched.filter((p) => !SHELL.includes(p)), [], 'the worker never fetched anything but the shell');
});

test('shell files come fresh from the Mac and refresh the copy kept for later', async () => {
  const w = await installed();
  const event = w.fire('fetch', { method: 'GET', url: `${ORIGIN}/static/app.js` });
  const response = await event.response;
  assert.equal(await response.text(), 'fresh:/static/app.js');
  const cached = await (await w.sandbox.caches.open('crooks-shell-testbuild')).match('/static/app.js');
  assert.equal(await cached.text(), 'fresh:/static/app.js');
});

test('a navigation while the Mac is away opens from the shell', async () => {
  const w = await installed();
  w.network.mode = 'fail';
  const event = w.fire('fetch', { method: 'GET', url: `${ORIGIN}/?dev=1`, mode: 'navigate' });
  const response = await event.response;
  assert.equal(response.status, 200);
  assert.equal(await response.text(), 'fresh:/');
});

test('a hanging Mac is treated as away after the bound', async () => {
  const w = await installed();
  w.network.mode = 'hang';
  const event = w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' });
  assert.equal(await (await event.response).text(), 'fresh:/');
});

test('a 5xx from the proxy is "away"; a 4xx is an answer and is passed through untouched', async () => {
  const w = await installed();
  w.network.mode = 502;
  assert.equal(await (await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response).text(), 'fresh:/');
  w.network.mode = 403;
  const refused = await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response;
  assert.equal(refused.status, 403);
  const cache = await w.sandbox.caches.open('crooks-shell-testbuild');
  assert.equal(await (await cache.match('/')).text(), 'fresh:/', 'a refusal is never cached as the shell');
});

test('with no shell cached at all, a navigation still gets a CROOKS page, not a browser error', async () => {
  const w = boot();                 // never installed
  w.network.mode = 'fail';
  const response = await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response;
  const html = await response.text();
  assert.ok(html.includes('CLIVE') && html.includes('System offline') && html.includes('Waiting for CLIVE'));
  assert.ok(!/order|customer|email|@/.test(html), 'the fallback page carries nothing from any session');
});

test('the caches never hold anything but shell paths, whatever was asked for', async () => {
  const w = await installed();
  for (const p of ['/state/abc', '/health', '/turn', '/static/fixtures.js']) w.fire('fetch', { method: 'GET', url: ORIGIN + p });
  w.fire('fetch', { method: 'GET', url: `${ORIGIN}/static/ui.js` });
  await new Promise((r) => setTimeout(r, 10));
  for (const cache of w.cacheStore.values()) {
    for (const key of cache.keys()) assert.ok(SHELL.includes(key), `${key} must never be cached`);
  }
});

test('a commit is never queued, synced or replayed by the worker', () => {
  assert.ok(!/\b(sync|periodicsync|push|indexedDB|localStorage|BackgroundSync)\b/.test(SOURCE), 'no queue, no replay');
  const w = boot();
  const event = w.fire('fetch', { method: 'POST', url: `${ORIGIN}/actions/prop_1/commit` });
  assert.equal(event.response, null, 'a commit goes straight to the Mac, or nowhere');
  assert.deepEqual(w.fetched, [], 'the worker itself never sent it');
});

test('a page of its own — /whoami, /health, /docs — is never the shell, and never poisons it', async () => {
  const w = await installed();
  await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response;   // the real shell is cached
  for (const path of ['/whoami', '/health', '/docs', '/openapi.json', '/actions/prop_1']) {
    const event = w.fire('fetch', { method: 'GET', url: `${ORIGIN}${path}`, mode: 'navigate' });
    assert.equal(event.response, null, `${path} goes straight to the Mac`);
  }
  const cache = [...w.cacheStore.values()][0];
  assert.equal(await (await cache.match('/')).text(), 'fresh:/');
  // And whatever answers at '/' with something other than HTML is passed on, not kept.
  w.network.type = 'application/json';
  const odd = await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response;
  assert.equal(await odd.text(), 'fresh:/');
  w.network.type = null;
  w.network.mode = 'fail';
  const offline = await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response;
  assert.equal(offline.headers.get('content-type').indexOf('text/html'), 0, 'the shell slot still holds the app');
});

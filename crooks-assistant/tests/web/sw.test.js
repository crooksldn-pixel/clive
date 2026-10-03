/* The service worker, run under Node against a small stand-in for the worker globals.
 *
 * What is proved: it keeps the shell and nothing else; it never intercepts a POST, a call to
 * the Mac's endpoints, or anything from another origin; a navigation while the Mac is away
 * opens from the cached shell; a 5xx from the Tailscale proxy counts as "away" and a 4xx does
 * not; and a new build waits to be told before taking over.
 *
 * Round 10 (B-07): the page it keeps at '/' is only ever this build's own page as the Mac serves
 * it (app/main.py `index`: web/index.html with the build id written in) — anything else that
 * answers there, however it looks, is passed on and never kept, and never opened offline.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ORIGIN = 'https://crooks.test';
const RAW = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'sw.js'), 'utf8');
const SOURCE = RAW.replace('__BUILD__', 'testbuild');

// A Response of our own rather than Node's. Node's comes from its bundled undici, and loading
// that starts compiling an HTTP parser as WebAssembly in the background; a checker with a
// capped address space cannot reserve the memory for it, and the run then fails on a rejection
// that has nothing to do with the worker. This keeps what the worker relies on: a status,
// headers read case-insensitively, and a body that is read once and must be cloned to be kept.
class FakeResponse {
  constructor(body, init) {
    const options = init || {};
    this.status = options.status === undefined ? 200 : options.status;
    this.ok = this.status >= 200 && this.status < 300;
    this.type = 'default';
    const fields = new Map(Object.entries(options.headers || {}).map(([k, v]) => [k.toLowerCase(), String(v)]));
    this.headers = { get: (name) => (fields.has(String(name).toLowerCase()) ? fields.get(String(name).toLowerCase()) : null) };
    this.body = body === undefined || body === null ? '' : String(body);
    this.bodyUsed = false;
  }
  static error() {
    const response = new FakeResponse(null, { status: 0 });
    response.type = 'error';
    return response;
  }
  clone() {
    if (this.bodyUsed) throw new TypeError('Response.clone: the body has already been read');
    const copy = new FakeResponse(this.body, { status: this.status });
    copy.headers = this.headers;
    copy.type = this.type;
    return copy;
  }
  async text() {
    if (this.bodyUsed) throw new TypeError('Body is unusable: it has already been read');
    this.bodyUsed = true;
    return this.body;
  }
}

// The page the Mac serves at '/' for a build (app/main.py `index`): web/index.html with the
// build's id written into its `crooks-build` meta. `tag` tells one serving from another.
function shellPage(build, tag) {
  return '<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="crooks-build" content="'
    + (build || 'testbuild') + '"></head><body>' + (tag || '') + 'fresh:/</body></html>';
}

// One browser can run one worker after another: `shared` is the browser's own cache storage,
// kept across builds, and `build` is the id the Mac wrote into the worker it served. The Mac
// serves its own build's page at '/' (`network.build`, the worker's build unless a test moves the
// Mac on), or whatever `network.page` says instead.
function boot(options) {
  const opts = options || {};
  const handlers = {};
  const fetched = [];
  const network = opts.network || { mode: 'ok' };     // 'ok' | 'fail' | 'hang' | a numeric status
  const cacheStore = opts.shared || new Map();
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
    Response: FakeResponse,
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
      const p = new URL(typeof request === 'string' ? request : request.url).pathname;
      fetched.push(p);
      if (network.mode === 'fail') throw new TypeError('network down');
      if (network.mode === 'hang') return new Promise(() => {});
      const status = typeof network.mode === 'number' ? network.mode : 200;
      const type = network.type || (p.endsWith('.js') ? 'text/javascript' : 'text/html');
      const tag = network.tag ? `${network.tag}:` : '';
      if (p === '/' && status === 200) {
        const said = network.page || shellPage(network.build || opts.build || 'testbuild', tag);
        const response = new FakeResponse(said, { status, headers: { 'content-type': type } });
        if (network.redirected) response.redirected = true;
        return response;
      }
      return new FakeResponse(`${tag}${status === 200 ? 'fresh' : 'status'}:${p}`, { status, headers: { 'content-type': type } });
    },
  };
  sandbox.self = sandbox;
  vm.runInNewContext(opts.build ? RAW.replace('__BUILD__', opts.build) : SOURCE, sandbox, { filename: 'sw.js' });
  const fire = (type, request) => {
    const event = { request, response: null, waited: null, respondWith(p) { this.response = p; }, waitUntil(p) { this.waited = p; } };
    handlers[type](event);
    return event;
  };
  return { handlers, fetched, network, cacheStore, calls, fire, sandbox };
}

const SHELL = ['/', '/static/style.css', '/static/app.js', '/static/ui.js', '/static/action-state.js', '/static/live-state.js', '/static/jobs.js', '/static/telemetry.js', '/static/collide.js', '/static/touch.js', '/static/notify.js', '/static/orb.js', '/static/dots.js', '/static/startup.js', '/static/startup.css', '/static/audio-viz.js', '/static/live-voice.js', '/static/alpha.js', '/static/alpha.css',
  // Round 9: the remote for the owner's screens (web/remote.js).
  '/static/remote.js', '/static/remote.css',
  // Round 12: an objective in the shape of its kind (web/objective-cards.js).
  '/static/objective-cards.js', '/static/objective-cards.css',
  // Objectives by touch: the gestures and the bar the two above share (web/objective-touch.js).
  '/static/objective-touch.js',
  // Objectives by touch, part C: a number to reach (web/objective-number.js).
  '/static/objective-number.js',
  // Round 12: holding a record to put it on a screen (web/lift.js).
  '/static/lift.js', '/static/lift.css',
  // Round 12: soft scroll edges (web/edges.js) and cards formed of dots (web/dots-app.js).
  '/static/edges.js', '/static/edges.css', '/static/dots-app.js', '/static/dots-app.css',
  // Objectives by touch, part B: the next six weeks (web/horizon.js) and the three distances (web/distances.js).
  '/static/horizon.js', '/static/horizon.css', '/static/distances.js',
  // The Builds screen: every build in plain words, and the decisions it needs (web/builds.js).
  '/static/builds.js', '/static/builds.css',
  // Customers: the order he meant, their story, a refund landing (web/customers.js).
  '/static/customers.js', '/static/customers.css',
  // The design pass of 3 Oct (web/design.css).
  '/static/design.css',
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
  assert.equal(await response.text(), shellPage());
});

test('a hanging Mac is treated as away after the bound', async () => {
  const w = await installed();
  w.network.mode = 'hang';
  const event = w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' });
  assert.equal(await (await event.response).text(), shellPage());
});

test('a 5xx from the proxy is "away"; a 4xx is an answer and is passed through untouched', async () => {
  const w = await installed();
  w.network.mode = 502;
  assert.equal(await (await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response).text(), shellPage());
  w.network.mode = 403;
  const refused = await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response;
  assert.equal(refused.status, 403);
  const cache = await w.sandbox.caches.open('crooks-shell-testbuild');
  assert.equal(await (await cache.match('/')).text(), shellPage(), 'a refusal is never cached as the shell');
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
  assert.equal(await (await cache.match('/')).text(), shellPage());
  // And whatever answers at '/' with something other than HTML is passed on, not kept.
  w.network.type = 'application/json';
  w.network.page = '{"detail":"a proxy said this"}';
  const odd = await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response;
  assert.equal(await odd.text(), '{"detail":"a proxy said this"}');
  assert.equal(await (await cache.match('/')).text(), shellPage(), 'the app is still the one kept');
  w.network.page = null;
  w.network.type = null;
  w.network.mode = 'fail';
  const offline = await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response;
  assert.equal(offline.headers.get('content-type').indexOf('text/html'), 0, 'the shell slot still holds the app');
});


// --- the screens, a new build, and a change of login (the 2026-09-27 deploy review, B-07) ---

test('a screen is never the worker\'s business: /display, its files and every /displays call go to the Mac', async () => {
  const w = await installed();
  await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response;
  const before = w.fetched.length;
  const untouched = [
    { method: 'GET', url: `${ORIGIN}/display`, mode: 'navigate' },
    { method: 'GET', url: `${ORIGIN}/display?name=office`, mode: 'navigate' },
    { method: 'GET', url: `${ORIGIN}/static/display.js` },
    { method: 'GET', url: `${ORIGIN}/static/display.css` },
    { method: 'GET', url: `${ORIGIN}/static/display-dots.js` },
    { method: 'GET', url: `${ORIGIN}/displays` },
    { method: 'POST', url: `${ORIGIN}/displays/register` },
    { method: 'GET', url: `${ORIGIN}/displays/scr_000000000000/poll`, headers: { 'X-Screen-Key': 'k' } },
    { method: 'POST', url: `${ORIGIN}/displays/scr_000000000000/done`, headers: { 'X-Screen-Key': 'k' } },
    { method: 'GET', url: `${ORIGIN}/objectives` },
    { method: 'POST', url: `${ORIGIN}/pad/heartbeat` },
    { method: 'GET', url: `${ORIGIN}/pad` },
  ];
  for (const request of untouched) {
    const event = w.fire('fetch', request);
    assert.equal(event.response, null, `${request.method} ${request.url} must go straight to the network`);
  }
  assert.equal(w.fetched.length, before, 'the worker itself fetched none of them');
  const cache = await w.sandbox.caches.open('crooks-shell-testbuild');
  for (const key of cache.keys()) assert.ok(SHELL.includes(key), `${key} must never be cached`);
  assert.ok(!SHELL.some((p) => p.includes('display')), 'nothing of the screens is in the shell');
  assert.ok(!/display/.test(RAW.slice(RAW.indexOf('const SHELL'), RAW.indexOf('];', RAW.indexOf('const SHELL')))),
    'the worker as served lists no screen file');
});

test('a new build replaces the old shell: the old copy is dropped and never served again', async () => {
  const shared = new Map();
  const network = { mode: 'ok', tag: 'build-a' };
  const a = boot({ build: 'a', shared, network });
  await a.fire('install').waited;
  await a.fire('activate').waited;
  assert.equal(await (await a.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response).text(), shellPage('a', 'build-a:'));

  // The Mac moves on. The browser installs the new worker beside the old one...
  network.tag = 'build-b';
  network.build = 'b';
  const b = boot({ build: 'b', shared, network });
  await b.fire('install').waited;
  assert.deepEqual([...shared.keys()].sort(), ['crooks-shell-a', 'crooks-shell-b']);
  // ...and when it takes over, only its own shell is left.
  await b.fire('activate').waited;
  assert.deepEqual([...shared.keys()], ['crooks-shell-b']);
  network.mode = 'fail';
  for (const p of ['/', '/static/app.js', '/static/startup.js']) {
    const request = p === '/' ? { method: 'GET', url: ORIGIN + p, mode: 'navigate' } : { method: 'GET', url: ORIGIN + p };
    const text = await (await b.fire('fetch', request).response).text();
    assert.equal(text, p === '/' ? shellPage('b', 'build-b:') : 'build-b:fresh:' + p, `${p} offline is the new build's copy, not the old one's (${text})`);
  }
  // An unrelated cache the page might hold is not the worker's to delete.
  shared.set('someone-elses', new Map());
  await b.fire('activate').waited;
  assert.ok(shared.has('someone-elses'));
});

test('offline, the shell opens and nothing else is answered from the cache', async () => {
  const w = await installed();
  await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response;
  w.network.mode = 'fail';
  const page = await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response;
  assert.equal(await page.text(), shellPage());
  for (const p of ['/displays/scr_000000000000/poll', '/state/s1', '/health', '/whoami', '/objectives']) {
    assert.equal(w.fire('fetch', { method: 'GET', url: ORIGIN + p }).response, null, `${p} is not answered offline by the worker`);
  }
  // A shell file that was never cached is an error, not something made up.
  const cache = await w.sandbox.caches.open('crooks-shell-testbuild');
  cache.entries.delete('/static/orb.js');
  const missing = await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/static/orb.js` }).response;
  assert.equal(missing.type, 'error');
});

test('a change of login on the same browser: nothing the last login saw is kept or replayed', async () => {
  // The owner uses the app: the shell is kept, and his calls go to the Mac and are not kept.
  const w = await installed();
  w.network.tag = 'owner';
  await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response;
  for (const p of ['/state/s1', '/displays', '/objectives', '/whoami']) w.fire('fetch', { method: 'GET', url: ORIGIN + p });
  await new Promise((r) => setTimeout(r, 10));

  // The browser is now signed in to the tailnet as someone who is not on the allow-list. The Mac
  // refuses every call of theirs; the worker neither answers for the Mac nor softens a refusal.
  w.network.tag = 'stranger';
  w.network.mode = 403;
  for (const p of ['/state/s1', '/displays', '/objectives', '/displays/scr_000000000000/poll']) {
    assert.equal(w.fire('fetch', { method: 'GET', url: ORIGIN + p }).response, null, `${p} is the Mac's to answer`);
  }
  // The page itself: the Mac's answer is passed through, and a refusal is never kept as the app.
  const refused = await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response;
  assert.equal(refused.status, 403);
  const cache = await w.sandbox.caches.open('crooks-shell-testbuild');
  assert.equal(await (await cache.match('/')).text(), shellPage('testbuild', 'owner:'), 'the kept page is the code the owner was served');
  for (const store of w.cacheStore.values()) {
    for (const key of store.keys()) assert.ok(SHELL.includes(key), `${key} must never be cached`);
  }
  // What is kept is code: the page, its scripts and styles, its icons. The Mac's side of this —
  // that the page served at '/' is the same for every login — is tests/test_displays.py.
  assert.ok(SHELL.every((p) => p === '/' || p === '/manifest.webmanifest' || p.startsWith('/static/')));
  assert.ok(!/credentials|Authorization|Tailscale-User/i.test(RAW), 'the worker never looks at who is asking');
});


// --- round 10 (B-07): the page kept at '/' is this build's own page and nothing else ---

// Closes B-07 (round 10): an owner load, then others at '/', then an offline load.
test('the page kept at / is only ever this build’s own: nothing else that answers there is kept or opened offline', async () => {
  // What '/' is (app/main.py `index`): web/index.html with the build id written in, the same for
  // every login. The owner opens the app: that page is kept.
  const w = await installed();
  w.network.tag = 'owner';
  const owner = await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response;
  assert.equal(await owner.text(), shellPage('testbuild', 'owner:'));
  const cache = await w.sandbox.caches.open('crooks-shell-testbuild');
  const kept = () => cache.match('/').then((r) => r.text());
  assert.equal(await kept(), shellPage('testbuild', 'owner:'));
  // Whatever else answers at '/' is passed on as it is, and never kept: a sign-in page in front
  // of the Mac, a page with someone's things on it, the end of a redirect (even to a page that
  // looks like the app), another build's page, a refusal.
  const others = [
    { page: '<!doctype html><html><body><form>Sign in to your tailnet</form></body></html>' },
    { page: '<!doctype html><html><body>Order #1047 · Sam Carter · 14 Sample Road</body></html>' },
    { page: shellPage('testbuild', 'elsewhere:'), redirected: true },
    { page: shellPage('another-build', 'next:') },
    { mode: 403 },
  ];
  for (const other of others) {
    Object.assign(w.network, { mode: 'ok', page: null, redirected: false }, other);
    const response = await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response;
    if (other.page) assert.equal(await response.text(), other.page, 'passed on as it is');
    else assert.equal(response.status, 403);
    assert.equal(await kept(), shellPage('testbuild', 'owner:'), `not kept: ${other.page || other.mode}`);
  }
  // Then a load with the Mac out of reach (whoever makes it): the app's own page, and only that.
  Object.assign(w.network, { mode: 'fail', page: null, redirected: false });
  const offline = await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response;
  assert.equal(await offline.text(), shellPage('testbuild', 'owner:'));
  for (const store of w.cacheStore.values()) {
    for (const key of store.keys()) assert.ok(SHELL.includes(key), `${key} must never be cached`);
  }
});

// Closes B-07 (round 10): the install keeps the page only if it is this build's own.
test('an install keeps nothing when the page at / is not this build’s own, and tries again later', async () => {
  const w = boot({ network: { mode: 'ok', page: '<!doctype html><html><body>Sign in to your tailnet</body></html>' } });
  await assert.rejects(w.fire('install').waited, /not this build/);
  assert.deepEqual(w.cacheStore.get('crooks-shell-testbuild').keys(), [], 'nothing kept from a failed install');
  // The next try, with the Mac serving the app: the whole shell.
  w.network.page = null;
  await w.fire('install').waited;
  assert.deepEqual(w.cacheStore.get('crooks-shell-testbuild').keys().sort(), [...SHELL].sort());
  assert.equal(await (await w.cacheStore.get('crooks-shell-testbuild').match('/')).text(), shellPage());
});

// B-07 (round 10): the worker's mark matches the real web/index.html.
test('the page the Mac really serves at / is the page the worker keeps', async () => {
  // app/main.py `index`: web/index.html with every __BUILD__ written as the build's id.
  const served = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8').split('__BUILD__').join('testbuild');
  const w = boot({ network: { mode: 'ok', page: served } });
  await w.fire('install').waited;
  const cache = w.cacheStore.get('crooks-shell-testbuild');
  assert.equal(await (await cache.match('/')).text(), served, 'kept at install');
  w.network.mode = 'fail';
  const offline = await w.fire('fetch', { method: 'GET', url: `${ORIGIN}/`, mode: 'navigate' }).response;
  assert.equal(await offline.text(), served, 'and opened offline');
  // The same file served for another build is not this worker's page.
  const other = boot({ build: 'another', network: { mode: 'ok', page: served } });
  await assert.rejects(other.fire('install').waited, /not this build/);
});

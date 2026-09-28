/* The screen page, run under Node against a stand-in for the page and for CLIVE (the 2026-09-27
 * deploy review, rounds 8 to 10).
 *
 * What is proved, with the page's own code:
 * - NEW-B-LOCAL-SLIP: a customer's slip leaves an open screen at once when CLIVE refuses the
 *   screen (403) — on its ask or on any other of its calls — the page, the dots engine that drew
 *   it and what the page keeps of it, and the screen says so plainly; after two minutes out of
 *   reach it goes the same way (not before); and a slip older than CLIVE's own limit comes down
 *   even while CLIVE answers "nothing new", and while CLIVE cannot be reached at all.
 * - B-02: a screen waiting for approval shows its code and the words to say, and keeps the code
 *   off the device's storage.
 * - B-04: "done" is sent only from the Mark packed tap, with confirm, and waits when CLIVE says
 *   it came too soon.
 * - Round 10, B2-01: the screen's key is CLIVE's cookie, never the page's: no ask carries a key,
 *   and nothing key-shaped is ever written to the device; a screen named before then hands its
 *   old key back once, stays approved, and forgets it.
 * - Round 10, B2-03: an answer to an ask sent before a refusal never puts anything back.
 * - Round 10, B2-04: a slip marked packed shows only the order's number and when it was packed.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { Element, Text, Fragment } = require('./dom-shim.js');

const WEB = path.join(__dirname, '..', '..', 'web');
const DISPLAY = fs.readFileSync(path.join(WEB, 'display.js'), 'utf8');

const REFUSED_LINE = 'This screen isn’t allowed to show CLIVE’s things any more.';
const OFFLINE_LINE = 'CLIVE can’t be reached, so this screen has taken down what it showed.';
// What a screen keeps on its device since round 10 (B2-01): its id and name. Its key is CLIVE's
// cookie, which the browser alone holds; `LEGACY` is a record kept before then, key and all.
const SCREEN = { id: 'scr_0123456789ab', name: 'Packing screen' };
const LEGACY = Object.assign({ key: 'key-one-legacy-0123456789' }, SCREEN);

// What the page's own drawing asks of an element, beyond what the shared stand-in has.
Element.prototype.getBoundingClientRect = function () { return { left: 0, top: 0, width: 10, height: 10, right: 10, bottom: 10 }; };
Element.prototype.getContext = function () { return context(); };
Element.prototype.remove = function () { if (this.parentNode) this.parentNode.removeChild(this); };
Element.prototype.closest = function () { return null; };
// The start-up with the dots (not the calm one) reads a letter's text node as the DOM has it.
if (!Object.getOwnPropertyDescriptor(Text.prototype, 'nodeValue')) Object.defineProperty(Text.prototype, 'nodeValue', { get() { return this.data; } });

function context() {
  return {
    font: '', fillStyle: '', strokeStyle: '', textBaseline: '', textAlign: '', globalAlpha: 1, lineWidth: 1, lineCap: '', lineJoin: '',
    measureText: () => ({ width: 12, fontBoundingBoxAscent: 10, fontBoundingBoxDescent: 3 }),
    getImageData: (x, y, w, h) => ({ data: new Uint8ClampedArray(Math.max(4, w * h * 4)) }),
    clearRect() {}, fillText() {}, beginPath() {}, rect() {}, roundRect() {}, fill() {}, stroke() {}, moveTo() {}, lineTo() {}, arc() {},
  };
}

// The dots engine: records what it is asked, and runs what it was asked to run later only when told.
function engines() {
  const made = [];
  const create = () => {
    let T = 0;
    const due = [];
    const e = { calls: [], destroyed: false };
    e.time = () => T;
    e.at = (t, fn) => { due.push({ t, fn }); };
    e.simulate = (t) => { T = Math.max(T, t); };
    e.destroy = () => { e.destroyed = true; due.length = 0; };
    e.runDue = () => {
      for (let guard = 0; guard < 100 && due.length; guard++) {
        due.sort((a, b) => a.t - b.t);
        const next = due.shift();
        T = Math.max(T, next.t);
        next.fn();
      }
    };
    for (const name of ['idleIntro', 'idleNow', 'clockTo', 'push', 'sweepOut', 'place', 'packOut', 'packIn', 'clear', 'nameIntro',
      'nameTo', 'nameToOrb', 'boot', 'quick', 'setHome', 'handoff', 'stillGlint', 'freeze', 'setSpeed']) {
      e[name] = () => { e.calls.push(name); };
    }
    made.push(e);
    return e;
  };
  return { made, CliveDots: { create, textTargets: () => [] } };
}

const IDS = ['board', 'ui', 'idle', 'namer', 'mark', 'pairing', 'scan', 'status', 'hint', 'bloom', 'dots', 'fx', 'meta', 'online',
  'bar-name', 'line', 'date', 'clock-said', 'name-input', 'name-save', 'name-error', 'name-replace', 'status-text', 'status-pct',
  'mark-line', 'mark-wait', 'pair-code', 'pair-say', 'pair-note'];

// One screen page: its elements, a clock and timers that move only when told, a stored screen,
// and CLIVE answering as `answer(request)` says.
function page({ stored = SCREEN, answer, start = Date.UTC(2026, 8, 27, 12, 0, 0), calm = true } = {}) {
  const clock = { now: start };
  const timers = [];
  let seq = 0;
  const frames = [];
  const requests = [];
  const els = {};
  for (const id of IDS) els[id] = new Element(id === 'name-input' ? 'input' : 'div');
  els['name-input'].value = '';
  els.namer.hidden = true;
  els.pairing.hidden = true;
  const storage = {};
  const writes = [];            // every value the page ever wrote to the device's storage
  const docListeners = {};
  const winListeners = {};
  if (stored) storage['clive.screen'] = JSON.stringify(stored);
  const dots = engines();
  const RealDate = Date;
  class FakeDate extends RealDate {
    constructor(...a) { if (a.length) super(...a); else super(clock.now); }
    static now() { return clock.now; }
  }
  const document = {
    getElementById: (id) => els[id] || null,
    querySelector: () => null,
    createElement: (tag) => new Element(tag),
    createElementNS: (ns, tag) => new Element(tag, ns),
    createTextNode: (data) => new Text(data),
    createDocumentFragment: () => new Fragment(),
    createTreeWalker: () => ({ nextNode: () => null }),
    createRange: () => ({ setStart() {}, setEnd() {}, getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) }),
    addEventListener: (type, fn) => { (docListeners[type] = docListeners[type] || []).push(fn); },
    visibilityState: 'visible',
    fullscreenEnabled: false,
    fullscreenElement: null,
    documentElement: {},
  };
  const response = (status, body) => ({
    status, ok: status >= 200 && status < 300,
    json: async () => (body === undefined ? {} : JSON.parse(JSON.stringify(body))),
    clone() { return this; },
  });
  // CLIVE's answer, at once, or when a test lets it go (`held`): what an answer that is still on
  // its way, while others arrive, looks like.
  const fetch = (url, opts = {}) => {
    const request = { url, method: opts.method || 'GET', headers: opts.headers || {}, credentials: opts.credentials,
      body: opts.body ? JSON.parse(opts.body) : null, at: clock.now };
    requests.push(request);
    const said = answer(request);
    const give = (s) => (s === 'network' ? Promise.reject(new TypeError('Failed to fetch')) : response(s.status, s.body));
    if (said && typeof said.then === 'function') return said.then(give);
    return said === 'network' ? give(said) : Promise.resolve(give(said));
  };
  const schedule = (fn, ms, every) => { timers.push({ id: ++seq, at: clock.now + Math.max(0, Number(ms) || 0), fn, every }); return seq; };
  const cancel = (id) => { const t = timers.find((x) => x.id === id); if (t) t.fn = null; };
  const window = { innerWidth: 1920, innerHeight: 1080, matchMedia: () => ({ matches: calm }),
    addEventListener: (type, fn) => { (winListeners[type] = winListeners[type] || []).push(fn); } };
  const sandbox = {
    window, document, console, Math, JSON, Date: FakeDate, Promise, Set, Map, Array, Number, Object, String, Error, TypeError,
    Uint8ClampedArray, isNaN, parseFloat, encodeURIComponent, AbortController,
    navigator: { hardwareConcurrency: 8 },
    location: { search: '', origin: 'https://clive.example' },
    NodeFilter: { SHOW_TEXT: 4 },
    localStorage: {
      getItem: (k) => (Object.prototype.hasOwnProperty.call(storage, k) ? storage[k] : null),
      setItem: (k, v) => { storage[k] = String(v); writes.push(String(v)); },
      removeItem: (k) => { delete storage[k]; },
    },
    getComputedStyle: () => ({ opacity: '1', borderTopLeftRadius: '0px', fontStyle: 'normal', fontWeight: '600', fontSize: '30px', fontFamily: 'x', color: '#fff', textTransform: 'none' }),
    requestAnimationFrame: (fn) => { frames.push(fn); return frames.length; },
    fetch,
    setTimeout: (fn, ms) => schedule(fn, ms, 0),
    setInterval: (fn, ms) => schedule(fn, ms, Math.max(1, Number(ms) || 1)),
    clearTimeout: cancel,
    clearInterval: cancel,
  };
  window.CliveDots = dots.CliveDots;
  sandbox.self = window;
  vm.createContext(sandbox);

  const flush = async () => { for (let i = 0; i < 30; i++) await new Promise((r) => setImmediate(r)); };
  const frame = async () => { for (let i = 0; i < 4; i++) { const list = frames.splice(0); list.forEach((fn) => fn(clock.now)); } await flush(); };
  const engine = () => dots.made[dots.made.length - 1];
  // Everything the page asked to happen by then happens, in order: timers, the engine's own
  // schedule, the next frames, and whatever CLIVE's answers set going.
  const advance = async (ms) => {
    const until = clock.now + ms;
    for (let guard = 0; guard < 10000; guard++) {
      const due = timers.filter((t) => t.fn && t.at <= until).sort((a, b) => a.at - b.at || a.id - b.id)[0];
      if (!due) break;
      clock.now = due.at;
      const fn = due.fn;
      if (due.every) due.at += due.every; else due.fn = null;
      fn();
      await flush();
      await frame();
      if (engine()) engine().runDue();
      await flush();
    }
    clock.now = until;
  };
  // The page's own state, read by the tests alone (the page itself puts nothing on `window`).
  const load = async () => {
    vm.runInContext(DISPLAY.replace('const S = {', 'const S = window.__screen = {'), sandbox, { filename: 'display.js' });
    await flush();
    await frame();
    engine().runDue();
    await flush();
    await frame();
    engine().runDue();
    await flush();
  };
  return { els, clock, requests, storage, writes, dots, load, advance, flush, frame, engine, docListeners, winListeners,
    state: () => window.__screen };
}

// An answer CLIVE gives only when the test says: `let` it go with what it says.
function held() {
  let give;
  const promise = new Promise((resolve) => { give = resolve; });
  return { promise, let: (said) => give(said) };
}

function slip(at) {
  return {
    kind: 'order', ref: 'gid://shopify/Order/1047', title: 'Order #1047', at, by: 'clive',
    order: {
      number: '#1047', customer: 'Sam Carter', address: ['14 Sample Road', 'London', 'E8 1AA'], phone: null, note: null, tags: [],
      items: [
        { title: 'Heavyweight Tee', variant: 'Black / L', sku: 'HW-TEE', quantity: 2, to_send: 2, image: null },
        { title: 'Canvas Tote', variant: 'Natural', sku: 'CV-TOTE', quantity: 1, to_send: 1, image: null },
      ],
    },
  };
}

// CLIVE, for one screen showing one slip: in full when asked afresh, "nothing new" otherwise,
// and whatever `mode()` says instead when it is not 'ok'.
function clive(pg, { at, mode, done }) {
  return (request) => {
    const m = mode();
    if (m !== 'ok') return m === 'network' ? 'network' : { status: m, body: { code: 'refused', detail: 'not allowed' } };
    if (request.url.endsWith('/seen')) return { status: 200, body: { seen: request.body.end } };
    if (request.url.endsWith('/done')) return done ? done(request) : { status: 409, body: { code: 'stale' } };
    if (request.url.includes('?v=1')) return { status: 204 };
    return { status: 200, body: { id: SCREEN.id, name: SCREEN.name, version: 1, showing: slip(at()), pending: false,
      now: new Date(pg.clock.now).toISOString(), last_done: null } };
  };
}

async function shown({ age = 60 * 1000, done, calm = true } = {}) {
  let mode = 'ok';
  const box = {};
  const pg = page({ answer: (r) => box.answer(r), calm });
  box.answer = clive(pg, { at: () => new Date(pg.clock.now - age).toISOString(), mode: () => mode, done });
  await pg.load();
  await pg.advance(3000);
  return { pg, setMode: (m) => { mode = m; }, sam: () => pg.els.ui.allText().includes('Sam Carter') };
}

test('a 403 takes the customer off the screen at once: page, dots and memory, and says why', async () => {
  const { pg, setMode, sam } = await shown();
  assert.ok(sam(), 'the slip is up: ' + pg.els.ui.allText().slice(0, 80));
  const before = pg.dots.made.length;
  const drewWith = pg.engine();
  setMode(403);
  await pg.advance(2100);
  assert.ok(!sam() && pg.els.ui.allText() === '', 'nothing of the slip is left on the page');
  assert.ok(drewWith.destroyed, 'the dots that carried the slip are gone');
  assert.equal(pg.dots.made.length, before + 1, 'a new engine');
  assert.ok(pg.engine().calls.includes('idleNow'), 'straight to the clock, no journey');
  assert.equal(pg.els.line.textContent, REFUSED_LINE);
  // Asked again later, from nothing: what comes back is only what CLIVE sends again.
  setMode('ok');
  await pg.advance(15000);
  const again = pg.requests.filter((r) => r.method === 'GET').pop();
  assert.ok(again.url.endsWith('?v=-1'), again.url);
});

test('two minutes out of reach takes the slip down, and not a moment before', async () => {
  const { pg, setMode, sam } = await shown();
  assert.ok(sam());
  setMode('network');
  const lost = pg.clock.now;
  await pg.advance(110 * 1000);
  assert.ok(sam(), 'still up after 110 seconds without CLIVE');
  await pg.advance(15 * 1000);
  assert.ok(pg.clock.now - lost >= 120 * 1000);
  assert.equal(pg.els.ui.allText(), '', 'gone after two minutes');
  assert.equal(pg.els.line.textContent, OFFLINE_LINE);
  assert.ok(pg.dots.made.some((e) => e.destroyed), 'with the dots that drew it');
});

test('a slip older than CLIVE keeps anything comes down even while CLIVE says nothing new', async () => {
  const { pg, sam } = await shown({ age: 12 * 3600 * 1000 - 50 * 1000 });
  assert.ok(sam(), 'fifty seconds left to run');
  await pg.advance(30 * 1000);
  assert.ok(sam());
  await pg.advance(30 * 1000);
  assert.equal(pg.els.ui.allText(), '', 'past twelve hours from when it was put up: down');
  assert.ok(pg.requests.filter((r) => r.method === 'GET').slice(-3).every((r) => r.url.endsWith('?v=1')), 'CLIVE was saying nothing new');
});

test('done is sent only from the Mark packed tap, with confirm, and waits when told it came too soon', async () => {
  const answers = [{ status: 409, body: { code: 'too_soon', retry_after_ms: 400 } }];
  const { pg, sam } = await shown({
    done: (request) => answers.shift() || { status: 200, body: { id: SCREEN.id, name: SCREEN.name, version: 2, pending: false,
      showing: { kind: 'order', ref: 'gid://shopify/Order/1047', title: 'Order #1047', at: request.body && new Date(pg.clock.now).toISOString(), by: 'clive', done_at: new Date(pg.clock.now).toISOString() },
      now: new Date(pg.clock.now).toISOString(), last_done: null } },
  });
  assert.ok(sam());
  const seen = pg.requests.filter((r) => r.url.endsWith('/seen'));
  assert.deepEqual(seen.map((r) => [r.body.start, r.body.end]), [[0, 2]], 'the one page, told once');
  assert.equal(pg.requests.filter((r) => r.url.endsWith('/done')).length, 0, 'nothing said done without the tap');
  const btn = pg.els.ui.querySelector('.cs-btn');
  assert.ok(btn && !btn.disabled, 'Mark packed is there');
  btn.listeners.click[0]({ stopPropagation() {}, currentTarget: btn });
  await pg.flush();
  await pg.advance(1000);
  const done = pg.requests.filter((r) => r.url.endsWith('/done'));
  assert.equal(done.length, 2, 'asked again after the wait CLIVE named');
  assert.ok(done.every((r) => r.body.confirm === true && r.body.version === 1));
  assert.ok(done[1].at - done[0].at >= 400);
});

test('a screen waiting for approval shows its code and the words to say, and never stores the code', async () => {
  let approved = false;
  const pg = page({
    answer: (request) => {
      if (request.url === '/displays/register') {
        // Round 10 (B2-01): asked for with its own key, which is its cookie: the browser sends it
        // and nothing of it is in the page's request.
        assert.equal(request.headers['X-Screen-Key'], undefined, 'no key from the page');
        assert.equal(request.credentials, 'same-origin', 'the cookie goes with it');
        return { status: 200, body: { id: SCREEN.id, name: SCREEN.name, pending: true, code: '480913', code_expires_in: 900 } };
      }
      return { status: 200, body: { id: SCREEN.id, name: SCREEN.name, version: 0, showing: null, pending: !approved,
        now: new Date(pg.clock.now).toISOString(), last_done: null, code_expires_in: 800 } };
    },
  });
  await pg.load();
  await pg.advance(1000);
  assert.equal(pg.els.pairing.hidden, false, 'the approval panel is up');
  assert.equal(pg.els['pair-code'].textContent, '480 913');
  assert.equal(pg.els['pair-say'].textContent, 'Tell CLIVE: “approve the packing screen, code 480 913”');
  assert.equal(pg.els.ui.allText(), '');
  assert.ok(!JSON.stringify(pg.storage).includes('480913'), 'the code is not written down on the device');
  assert.deepEqual(JSON.parse(pg.storage['clive.screen']), SCREEN, 'the id and the name, and nothing else');
  assert.ok(pg.requests.some((r) => r.url === '/displays/register'), 'the code was asked for');
  approved = true;
  await pg.advance(3000);
  assert.equal(pg.els.pairing.hidden, true, 'approved: the panel goes');
  assert.equal(pg.els['pair-code'].textContent, '480 913', 'shown until then, and nothing else was');
});

/* Round 9: two things at once, and the owner's remote.
 *
 * - Two panes are drawn side by side, and each tells CLIVE its own pages, under its own version.
 * - A tick from the remote shows on the next ask as a check and a dimmed row, in place: the page
 *   is not formed again.
 * - A page the remote turns goes up here, and is acknowledged as the screen's own button would.
 * - A touched screen ticks an item through the same owner route, naming the pane and its version.
 * - Turned off, the screen goes back to its clock; a 403 takes both panes down at once.
 */

function list(at, v) {
  return { kind: 'list', ref: '', title: 'Sam Carter’s alterations', at, by: 'clive', v, list: { lines: ['Hem the trousers', 'Take in the waist'] } };
}
function many(at, v, n) {
  const s = slip(at);
  s.v = v;
  s.order.items = Array.from({ length: n }, (x, i) => ({ title: 'Tee ' + i, variant: 'Black / L', sku: 'T' + i, quantity: 1, to_send: 1, image: null }));
  return s;
}

// CLIVE answering with whatever `now()` says the screen shows, as a full answer when asked afresh
// or when the version moved, and "nothing new" otherwise.
function screenOf(pg, now, extra) {
  return (request) => {
    const said = extra && extra(request);
    if (said) return said;
    if (request.url.endsWith('/seen')) return { status: 200, body: { seen: request.body.end } };
    const state = now();
    if (state.status) return state;
    if (request.url.includes('?v=' + state.version)) return { status: 204 };
    return { status: 200, body: Object.assign({ id: SCREEN.id, name: SCREEN.name, pending: false, now: new Date(pg.clock.now).toISOString(), last_done: null, beside: null }, state) };
  };
}

async function upWith(state, extra, options) {
  const box = { state };
  const pg = page(Object.assign({ answer: (r) => box.answer(r) }, options || {}));
  const at = new Date(pg.clock.now - 60 * 1000).toISOString();
  box.answer = screenOf(pg, () => (typeof box.state === 'function' ? box.state(at) : box.state), extra);
  await pg.load();
  await pg.advance(3000);
  return { pg, box, at };
}

test('two panes are drawn side by side, and each tells CLIVE its own pages under its own version', async () => {
  const { pg } = await upWith((at) => ({ version: 2, showing: Object.assign(slip(at), { v: 1 }), beside: list(at, 2) }));
  assert.ok(pg.els.ui.classList.contains('cs-two'), 'laid out for two');
  assert.equal(pg.els.ui.querySelectorAll('.cs-pane').length, 2);
  const text = pg.els.ui.allText();
  assert.ok(text.includes('Order #1047') && text.includes('Hem the trousers'), text.slice(0, 120));
  await pg.advance(3000);
  const seen = pg.requests.filter((r) => r.url.endsWith('/seen')).map((r) => [r.body.pane, r.body.version, r.body.start, r.body.end]);
  assert.deepEqual(seen.sort(), [[0, 1, 0, 2], [1, 2, 0, 2]], 'each pane, under its own version');
  assert.equal(pg.els.ui.querySelectorAll('.cs-btn').length, 2, 'a Mark packed and a Mark done');
});

test('a tick from the remote shows here at once as a check and a dimmed row, without forming the page again', async () => {
  let ticked = [];
  let version = 1;
  const { pg } = await upWith((at) => ({ version, showing: Object.assign(slip(at), { v: 1, ticked }) }));
  const drew = pg.engine().calls.filter((c) => c === 'push').length;
  assert.equal(pg.els.ui.querySelectorAll('.is-ticked').length, 0);
  assert.equal(pg.els.ui.querySelector('.cs-count-n').textContent, '3', 'three to pack');
  ticked = [0]; version = 2;                        // the owner ticks the tees on his phone
  await pg.advance(2100);
  const rows = pg.els.ui.querySelectorAll('.cs-item');
  assert.ok(rows[0].classList.contains('is-ticked') && rows[0].querySelector('.cs-tick'), 'a check on the row');
  assert.ok(!rows[1].classList.contains('is-ticked'));
  assert.equal(pg.els.ui.querySelector('.cs-count-n').textContent, '1', 'one left to pack');
  assert.equal(pg.engine().calls.filter((c) => c === 'push').length, drew, 'drawn in place, not formed again');
  assert.ok(!pg.engine().calls.includes('clear'));
  ticked = []; version = 3;                         // and unticked
  await pg.advance(2100);
  assert.equal(pg.els.ui.querySelectorAll('.is-ticked').length, 0);
});

test('a page the remote turns goes up here and is acknowledged as the screen’s own button would', async () => {
  let turned = 0;
  let version = 1;
  const { pg } = await upWith((at) => ({ version, showing: Object.assign(many(at, 1, 12), { page: turned }) }));
  await pg.advance(1500);
  assert.ok(pg.els.ui.allText().includes('In the box · 1–10 of 12'));
  turned = 1; version = 2;
  await pg.advance(2100);
  assert.ok(pg.els.ui.allText().includes('In the box · 11–12 of 12'), pg.els.ui.allText().slice(0, 200));
  await pg.advance(1500);
  const seen = pg.requests.filter((r) => r.url.endsWith('/seen')).map((r) => [r.body.start, r.body.end]);
  assert.deepEqual(seen, [[0, 10], [10, 12]]);
});

test('a touched screen ticks an item through the owner’s route, naming the pane and its version', async () => {
  const ticks = [];
  const { pg } = await upWith((at) => ({ version: 2, showing: Object.assign(slip(at), { v: 1 }), beside: list(at, 2) }), (request) => {
    if (!request.url.endsWith('/remote/tick')) return null;
    ticks.push(request.body);
    return { status: 200, body: { version: 3, v: request.body.version, ticked: [request.body.item], page: 0 } };
  });
  const lines = pg.els.ui.querySelectorAll('.cs-task');
  assert.equal(lines.length, 2);
  lines[1].listeners.click[0]({ stopPropagation() {} });
  await pg.flush();
  assert.deepEqual(ticks, [{ pane: 1, item: 1, packed: true, version: 2 }]);
  const now = pg.els.ui.querySelectorAll('.cs-task');
  assert.ok(now[1].classList.contains('is-ticked') && !now[0].classList.contains('is-ticked'), 'crossed off here at once');
  assert.ok(!pg.requests.some((r) => r.url.endsWith('/done')), 'a tick marks nothing done');
});

test('turned off, the screen goes back to its clock; a 403 takes both panes down at once', async () => {
  let state = null;
  const { pg, at } = await upWith((when) => state || { version: 2, showing: Object.assign(slip(when), { v: 1 }), beside: list(when, 2) });
  assert.ok(pg.els.ui.allText().includes('Sam Carter'));
  state = { version: 3, showing: null, beside: null };
  await pg.advance(6000);
  assert.equal(pg.els.ui.allText(), '', 'nothing left of either pane');
  assert.ok(pg.engine().calls.includes('clear'), 'dissolved back to the clock');
  assert.ok(!pg.els.ui.classList.contains('cs-two'));
  // Both up again, then CLIVE refuses the screen.
  state = { version: 4, showing: Object.assign(slip(at), { v: 4 }), beside: list(at, 4) };
  await pg.advance(8000);
  assert.ok(pg.els.ui.allText().includes('Hem the trousers'));
  const drewWith = pg.engine();
  state = { status: 403, body: { code: 'refused', detail: 'not allowed' } };
  await pg.advance(2100);
  assert.equal(pg.els.ui.allText(), '');
  assert.ok(drewWith.destroyed, 'with the dots that drew them');
  assert.equal(pg.els.line.textContent, REFUSED_LINE);
});

/* YouTube on a screen.
 *
 * - The video plays in YouTube's own privacy-enhanced player, built from its id and nothing else,
 *   and only messages from that player, from that frame, are listened to.
 * - Every command the owner gives it is applied once, however many arrive between two asks.
 * - How it is playing is told to CLIVE with the screen's key (its cookie since round 10), at a
 *   change, and not too often.
 * - A browser that will not start it with sound: it plays muted, says so, and the first press
 *   on the screen brings the sound back.
 * - The TV's own remote works it through CLIVE, as the owner's remote does.
 * - Drawn again around it, it does not start over; taken off, it is paused at once and dropped;
 *   a 403 takes it down at once. A video YouTube will not let play says so.
 */
const VID = 'dQw4w9WgXcQ';
const YT = 'https://www.youtube-nocookie.com';

function clip(at, v, player) {
  return { kind: 'video', ref: VID, title: 'Heat | Official Trailer', at, by: 'clive', v,
    video: { id: VID, channel: 'Warner', duration_s: 151, live: null, start: 0 }, player: player || undefined };
}

// The player in its frame: what the page posts to it, and a way to answer as YouTube's player does.
function player(pg) {
  const host = pg.els.board.querySelector('.cs-vhost');
  assert.ok(host, 'the player is on the board');
  const frame = host.querySelector('iframe');
  const sent = [];
  frame.contentWindow = { postMessage: (message, origin) => sent.push({ message: JSON.parse(message), origin }) };
  const say = (data, extra) => {
    for (const fn of pg.winListeners.message || []) fn(Object.assign({ origin: YT, source: frame.contentWindow, data: JSON.stringify(data) }, extra || {}));
  };
  const commands = () => sent.filter((m) => m.message.event === 'command').map((m) => [m.message.func, ...(m.message.args || [])]);
  return { host, frame, sent, say, commands };
}

test('a video plays in YouTube’s own player, built from its id, and only that player is listened to', async () => {
  const { pg } = await upWith((at) => ({ version: 1, showing: clip(at, 1) }));
  const yt = player(pg);
  const src = yt.frame.src;
  assert.ok(src.startsWith(YT + '/embed/' + VID + '?'), src);
  assert.ok(src.includes('enablejsapi=1') && src.includes('origin=' + encodeURIComponent('https://clive.example')), src);
  assert.equal(yt.frame.getAttribute('tabindex'), '-1');
  assert.equal(yt.frame.getAttribute('referrerpolicy'), 'strict-origin-when-cross-origin');
  assert.ok(pg.els.ui.allText().includes('Heat | Official Trailer') && pg.els.ui.allText().includes('Warner · 2:31 · YouTube'));
  yt.frame.dispatch('load');
  await pg.advance(300);
  assert.ok(yt.sent.some((m) => m.message.event === 'listening' && m.origin === YT), 'it asks the player to talk');
  // Nobody else is listened to: another origin, or another frame, saying it is ready changes nothing.
  yt.say({ event: 'onReady' }, { origin: 'https://evil.example' });
  yt.say({ event: 'onReady' }, { source: {} });
  yt.say('not json');
  assert.deepEqual(yt.commands(), []);
  yt.say({ event: 'onReady' });
  const said = yt.commands();
  assert.deepEqual(said.slice(0, 2), [['addEventListener', 'onStateChange'], ['addEventListener', 'onError']]);
  assert.deepEqual(said.slice(2), [['unMute'], ['playVideo']], 'shown, so it plays');
  assert.ok(yt.host.classList.contains('is-in'));
});

test('every command is applied once, however many arrive between two asks', async () => {
  let version = 1, p = { n: 0, paused: false, muted: false, volume: null, skip: 0, jump: null };
  const { pg } = await upWith((at) => ({ version, showing: clip(at, 1, p) }));
  const yt = player(pg);
  yt.frame.dispatch('load');
  yt.say({ event: 'onReady' });
  yt.say({ event: 'infoDelivery', info: { playerState: 1, currentTime: 10, duration: 151 } });
  yt.sent.length = 0;
  // Three commands between two asks: a jump to 60, a skip of 20 after it, a pause, a volume.
  p = { n: 4, paused: true, muted: false, volume: 30, skip: 25, jump: { n: 2, to: 60, skip: 5 } };
  version = 5;
  await pg.advance(800);
  const got = yt.commands();
  assert.deepEqual(got.filter((c) => c[0] === 'seekTo').map((c) => Math.round(c[1])), [60, 80]);
  assert.ok(got.some((c) => c[0] === 'setVolume' && c[1] === 30));
  assert.ok(got.some((c) => c[0] === 'pauseVideo'));
  // The same commands again (the screen changed elsewhere): nothing new happens.
  yt.sent.length = 0;
  version = 6;
  await pg.advance(800);
  assert.deepEqual(yt.commands(), []);
});

test('how it plays is told to CLIVE with the screen’s key (its cookie), at a change, and not too often', async () => {
  const { pg } = await upWith((at) => ({ version: 1, showing: clip(at, 1) }), (request) => (request.url.endsWith('/video') ? { status: 200, body: { heard: true } } : null));
  const yt = player(pg);
  yt.frame.dispatch('load');
  yt.say({ event: 'onReady' });
  yt.say({ event: 'infoDelivery', info: { playerState: 3, currentTime: 0, duration: 151, volume: 80, muted: false } });
  yt.say({ event: 'infoDelivery', info: { playerState: 1, currentTime: 0.4 } });
  await pg.flush();
  let told = pg.requests.filter((r) => r.url.endsWith('/video'));
  assert.equal(told.length, 1, 'the second change waits for the gap');
  assert.equal(told[0].headers['X-Screen-Key'], undefined, 'no key from the page (round 10, B2-01)');
  assert.equal(told[0].credentials, 'same-origin', 'the screen’s cookie goes with it');
  assert.deepEqual(Object.keys(told[0].body).sort(), ['at', 'blocked', 'duration', 'error', 'muted', 'pane', 'state', 'version', 'volume']);
  assert.equal(told[0].body.state, 'buffering');
  await pg.advance(1100);
  told = pg.requests.filter((r) => r.url.endsWith('/video'));
  assert.equal(told.length, 2);
  assert.equal(told[1].body.state, 'playing');
  await pg.advance(4100);
  assert.ok(pg.requests.filter((r) => r.url.endsWith('/video')).length >= 3, 'and every couple of seconds while it plays');
});

test('no sound until someone presses: it plays muted, says so, and the first press brings the sound back', async () => {
  const { pg } = await upWith((at) => ({ version: 1, showing: clip(at, 1) }), (request) => (request.url.endsWith('/video') ? { status: 200, body: { heard: true } } : null));
  const yt = player(pg);
  yt.frame.dispatch('load');
  yt.say({ event: 'onReady' });
  yt.sent.length = 0;
  await pg.advance(3600);   // the browser never let it start
  assert.deepEqual(yt.commands(), [['mute'], ['playVideo']]);
  assert.equal(pg.els.ui.querySelector('.cs-vstate').textContent, 'Sound off · press OK or tap the screen');
  assert.ok(pg.requests.some((r) => r.url.endsWith('/video') && r.body.blocked === true));
  yt.sent.length = 0;
  for (const fn of pg.docListeners.keydown || []) fn({ key: 'Shift', target: null, preventDefault() {} });
  assert.deepEqual(yt.commands(), [['unMute']]);
  assert.equal(pg.els.ui.querySelector('.cs-vstate').textContent, '');
});

test('the TV’s own remote works it through CLIVE, as the owner’s remote does', async () => {
  const asked = [];
  const { pg } = await upWith((at) => ({ version: 1, showing: clip(at, 1) }), (request) => {
    if (!request.url.endsWith('/remote/video')) return request.url.endsWith('/video') ? { status: 200, body: { heard: true } } : null;
    asked.push(request.body);
    const paused = request.body.action === 'pause';
    return { status: 200, body: { version: 2, v: 1, player: { n: asked.length, paused, muted: false, volume: null,
      skip: request.body.action === 'skip' ? request.body.value : 0, jump: null }, playing: null } };
  });
  const yt = player(pg);
  yt.frame.dispatch('load');
  yt.say({ event: 'onReady' });
  yt.say({ event: 'infoDelivery', info: { playerState: 1, currentTime: 30, duration: 151 } });
  yt.sent.length = 0;
  const press = (key) => { for (const fn of pg.docListeners.keydown || []) fn({ key, target: null, preventDefault() {} }); };
  press('Enter');
  await pg.flush();
  assert.deepEqual(asked[0], { pane: 0, version: 1, action: 'pause' });
  assert.ok(yt.commands().some((c) => c[0] === 'pauseVideo'), 'applied from CLIVE’s answer');
  press('ArrowRight');
  await pg.flush();
  assert.deepEqual(asked[1], { pane: 0, version: 1, action: 'skip', value: 10 });
  assert.ok(yt.commands().some((c) => c[0] === 'seekTo' && Math.round(c[1]) === 40));
  press('q');
  await pg.flush();
  assert.equal(asked.length, 2, 'a key it does not use asks nothing');
});

test('drawn again around it, the video does not start over; taken off, it is paused at once and dropped', async () => {
  let state = null;
  const { pg, at } = await upWith((when) => state || { version: 2, showing: clip(when, 1), beside: list(when, 2) });
  const yt = player(pg);
  yt.frame.dispatch('load');
  yt.say({ event: 'onReady' });
  // The list beside it is marked done: the page is drawn again, the player is the same player.
  state = { version: 3, showing: clip(at, 1), beside: Object.assign(list(at, 3), { done_at: new Date(pg.clock.now).toISOString() }) };
  await pg.advance(8000);
  assert.equal(pg.els.board.querySelector('.cs-vhost'), yt.host, 'the same player');
  assert.equal(yt.host.querySelector('iframe'), yt.frame);
  assert.ok(yt.host.parentNode, 'still on the board');
  // Turned off: paused at once, then dropped.
  yt.sent.length = 0;
  state = { version: 4, showing: null, beside: null };
  await pg.advance(2100);
  assert.ok(yt.commands().some((c) => c[0] === 'pauseVideo'));
  assert.ok(!yt.host.classList.contains('is-in'));
  await pg.advance(12000);
  assert.equal(yt.host.parentNode, null, 'dropped');
  assert.equal(pg.els.board.querySelector('.cs-vhost'), null);
});

test('a 403 takes a video down at once, and one YouTube will not let play says so', async () => {
  let state = null;
  const { pg } = await upWith((when) => state || { version: 1, showing: clip(when, 1) }, (request) => (request.url.endsWith('/video') ? { status: 200, body: { heard: true } } : null));
  const yt = player(pg);
  yt.frame.dispatch('load');
  yt.say({ event: 'onReady' });
  yt.say({ event: 'onError', info: 150 });
  await pg.flush();
  assert.equal(yt.host.querySelector('.cs-vnote').textContent, 'YouTube won’t let this video play outside YouTube. Ask CLIVE for another.');
  assert.equal(yt.host.querySelector('.cs-vnote').hidden, false);
  assert.equal(pg.els.ui.querySelector('.cs-vstate').textContent, 'Can’t play');
  assert.ok(pg.requests.some((r) => r.url.endsWith('/video') && r.body.error === 150));
  state = { status: 403, body: { code: 'refused', detail: 'not allowed' } };
  await pg.advance(1000);
  assert.equal(yt.host.parentNode, null, 'gone at once');
});


/* Round 10 of the deploy review.
 *
 * - B2-01: the screen's key is an HttpOnly cookie CLIVE sets; no ask the page makes carries a key,
 *   every one goes with the cookie (same origin), and the device keeps the screen's id and name and
 *   nothing else, whatever CLIVE's answer carries. A screen named before then hands its old key
 *   back to CLIVE once (X-Screen-Key, to /displays/register), stays approved, and forgets it; one
 *   opened while CLIVE is away keeps it until CLIVE answers; one whose key or name CLIVE no longer
 *   takes is named again.
 * - B2-03: an answer to an ask sent before a refusal never puts anything back — the screen's ask,
 *   a "done", a video's report — and only a fresh ask can.
 * - B2-04: a slip marked packed shows its number and when it was packed, never the customer's
 *   details, from the moment CLIVE says it is done, on the page and in what the page keeps.
 * - NEW-B-LOCAL-SLIP: a slip past CLIVE's own limit comes down while CLIVE cannot be reached at
 *   all, and a refusal of any of the screen's calls takes it down as the ask's own refusal does.
 */
const CUSTOMER = ['Sam Carter', '14 Sample Road', 'E8 1AA'];

// Every value the page wrote to the device is the screen's id and name, or when its start-up last
// played: never a key, whatever it was called.
function keptOnlyIdAndName(pg, secrets) {
  for (const written of pg.writes) {
    for (const secret of secrets) assert.ok(!written.includes(secret), 'a key was written down: ' + written);
    const value = JSON.parse(written);
    const keys = Object.keys(value).sort().join(',');
    assert.ok(keys === 'id,name' || keys === 'build,day', 'only the id and name are kept: ' + written);
  }
}

// Closes B2-01 (round 10): the cookie, never a key, on every ask of the screen's own.
test('no ask a screen makes carries its key: the cookie goes with each, and the device keeps its id and name', async () => {
  const told = [];
  const { pg } = await upWith((at) => ({ version: 2, showing: Object.assign(slip(at), { v: 1 }), beside: clip(at, 2) }), (request) => {
    if (request.url.endsWith('/video')) { told.push(request); return { status: 200, body: { heard: true } }; }
    if (request.url.endsWith('/done')) return { status: 409, body: { code: 'stale' } };
    return null;
  });
  const yt = player(pg);
  yt.frame.dispatch('load');
  yt.say({ event: 'onReady' });
  yt.say({ event: 'infoDelivery', info: { playerState: 1, currentTime: 1, duration: 151 } });
  await pg.flush();
  const btn = pg.els.ui.querySelector('.cs-btn');
  btn.listeners.click[0]({ stopPropagation() {}, currentTarget: btn });
  await pg.flush();
  await pg.advance(3000);
  const own = pg.requests.filter((r) => r.url.startsWith('/displays/' + SCREEN.id));
  for (const kind of ['?v=', '/seen', '/done', '/video']) assert.ok(own.some((r) => r.url.includes(kind)), 'asked ' + kind);
  for (const r of pg.requests) assert.equal(r.headers['X-Screen-Key'], undefined, 'no key in ' + r.method + ' ' + r.url);
  for (const r of own.filter((x) => !x.url.includes('/remote/'))) assert.equal(r.credentials, 'same-origin', r.url + ' goes with the cookie');
  assert.ok(told.length >= 1);
  keptOnlyIdAndName(pg, [LEGACY.key]);
});

// Closes B2-01 (round 10): nothing key-shaped is ever written to the device.
test('a screen named here keeps its id and name only, whatever CLIVE’s answer carries', async () => {
  const pg = page({
    stored: null,
    answer: (request) => {
      if (request.url === '/displays/register') {
        // An answer that still carried a key (as CLIVE's did before round 10): it is not kept.
        return { status: 200, body: { id: SCREEN.id, name: SCREEN.name, key: 'server-key-0123456789', pending: true, code: '480913', code_expires_in: 900 } };
      }
      return { status: 200, body: { id: SCREEN.id, name: SCREEN.name, version: 0, showing: null, pending: true, now: new Date(pg.clock.now).toISOString(), last_done: null, code_expires_in: 800 } };
    },
  });
  await pg.load();
  assert.equal(pg.els.namer.hidden, false, 'asked for its name');
  pg.els['name-input'].value = 'Packing screen';
  pg.els.namer.dispatch('submit');
  await pg.flush();
  await pg.advance(3000);
  const named = pg.requests.find((r) => r.url === '/displays/register');
  assert.deepEqual(named.body, { name: 'Packing screen' });
  assert.equal(named.headers['X-Screen-Key'], undefined);
  assert.equal(named.credentials, 'same-origin', 'so the browser keeps the cookie CLIVE sets with its answer');
  assert.equal(pg.els['pair-code'].textContent, '480 913', 'waiting for approval, with its code');
  assert.deepEqual(JSON.parse(pg.storage['clive.screen']), SCREEN);
  keptOnlyIdAndName(pg, ['server-key-0123456789', '480913']);
  assert.equal(pg.state().screen.key, undefined, 'nor held in the page');
});

// CLIVE for a screen named before round 10: `register` answers the one hand-back of its key, and
// the screen's ask shows one slip.
function legacyClive(pg, register) {
  return (request) => {
    if (request.url === '/displays/register') return register(request);
    if (request.url.endsWith('/seen')) return { status: 200, body: { seen: request.body.end } };
    if (request.url.includes('?v=1')) return { status: 204 };
    return { status: 200, body: { id: SCREEN.id, name: SCREEN.name, version: 1, showing: slip(new Date(pg.clock.now - 60000).toISOString()),
      pending: false, now: new Date(pg.clock.now).toISOString(), last_done: null } };
  };
}

// Closes B2-01 (round 10): the one-time hand-back of a key kept before, and the key dropped.
test('a screen named before round 10 hands its key back once, stays approved, and forgets it', async () => {
  const box = {};
  const pg = page({ stored: LEGACY, answer: (r) => box.answer(r) });
  box.answer = legacyClive(pg, () => ({ status: 200, body: { id: SCREEN.id, name: SCREEN.name, pending: false, key: 'rotated-key-0123456789' } }));
  await pg.load();
  await pg.advance(3000);
  const handed = pg.requests.filter((r) => r.url === '/displays/register');
  assert.equal(handed.length, 1, 'once');
  assert.equal(pg.requests[0], handed[0], 'before anything else is asked');
  assert.equal(handed[0].headers['X-Screen-Key'], LEGACY.key, 'its old key, the way a screen always named itself again');
  assert.equal(handed[0].credentials, 'same-origin', 'so the browser keeps the cookie CLIVE sets with its answer');
  assert.deepEqual(handed[0].body, { name: SCREEN.name });
  assert.deepEqual(JSON.parse(pg.storage['clive.screen']), SCREEN, 'the key is gone from the device');
  keptOnlyIdAndName(pg, [LEGACY.key, 'rotated-key-0123456789']);
  assert.ok(pg.els.ui.allText().includes('Sam Carter'), 'still approved: its slip is up');
  assert.equal(pg.els.namer.hidden, true, 'never asked for its name again');
  await pg.advance(20000);
  assert.equal(pg.requests.filter((r) => r.url === '/displays/register').length, 1, 'and never again');
  for (const r of pg.requests.slice(1)) assert.equal(r.headers['X-Screen-Key'], undefined, 'no key after it: ' + r.url);
});

// Closes B2-01 (round 10): the hand-back when CLIVE is away, or no longer takes the key or name.
test('an old key is kept until CLIVE answers; one CLIVE no longer takes is named again', async () => {
  // CLIVE away when the screen opens: the old record stays as it was, and nothing is asked without its key.
  let away = true;
  const box = {};
  const pg = page({ stored: LEGACY, answer: (r) => box.answer(r) });
  box.answer = legacyClive(pg, () => (away ? 'network' : { status: 200, body: { id: SCREEN.id, name: SCREEN.name, pending: false } }));
  await pg.load();
  await pg.advance(2500);
  assert.deepEqual(JSON.parse(pg.storage['clive.screen']), LEGACY, 'kept while CLIVE is away');
  assert.ok(!pg.requests.some((r) => r.method === 'GET'), 'no ask without its key');
  assert.equal(pg.els.namer.hidden, true);
  away = false;
  await pg.advance(10000);
  assert.deepEqual(JSON.parse(pg.storage['clive.screen']), SCREEN);
  assert.ok(pg.els.ui.allText().includes('Sam Carter'));
  // A name gone to another device, or a key CLIVE no longer knows: named again, as today.
  for (const refusal of [{ status: 409, body: { code: 'name_taken', detail: 'There is already a screen called Packing screen.' } },
    { status: 403, body: { code: 'not_this_screen', detail: 'Not this screen.' } }]) {
    const b = {};
    const again = page({ stored: LEGACY, answer: (r) => b.answer(r) });
    b.answer = legacyClive(again, () => refusal);
    await again.load();
    await again.advance(3000);
    assert.equal(again.storage['clive.screen'], undefined, 'the old record is forgotten');
    assert.equal(again.els.namer.hidden, false, 'asked for its name again');
    assert.equal(again.els['name-input'].value, SCREEN.name);
    if (refusal.status === 409) assert.equal(again.els['name-error'].textContent, refusal.body.detail, 'and says why');
    assert.equal(again.requests.filter((r) => r.url === '/displays/register').length, 1);
    assert.ok(!again.requests.some((r) => r.method === 'GET'), 'never asked what to show');
    assert.equal(again.els.ui.allText(), '');
  }
});

// Closes B2-03 (round 10): the screen's ask, answered after a refusal of another call.
test('an ask sent before a refusal never puts the slip back; only a fresh one can', async () => {
  const gate = { hold: null };
  const { pg } = await upWith((at) => ({ version: 1, showing: Object.assign(slip(at), { v: 1 }) }), (request) => {
    if (request.method === 'GET' && gate.hold) { const h = gate.hold; gate.hold = null; return h.promise; }
    if (request.url.endsWith('/remote/tick')) return { status: 403, body: { code: 'refused', detail: 'not allowed' } };
    return null;
  });
  assert.ok(pg.els.ui.allText().includes('Sam Carter'));
  const late = held();
  gate.hold = late;
  await pg.advance(2100);                          // the screen's ask goes, and is still on its way...
  const asks = pg.requests.filter((r) => r.method === 'GET').length;
  const row = pg.els.ui.querySelectorAll('.cs-item')[0];
  row.listeners.click[0]({ stopPropagation() {} });  // ...when CLIVE refuses a tick on this screen
  await pg.flush();
  assert.equal(pg.els.ui.allText(), '', 'taken down at once');
  assert.equal(pg.els.line.textContent, REFUSED_LINE);
  const pushes = pg.engine().calls.filter((c) => c === 'push').length;
  // The older ask's answer arrives now, with the slip in full: it is not read.
  late.let({ status: 200, body: { id: SCREEN.id, name: SCREEN.name, version: 2, pending: false, beside: null, last_done: null,
    showing: Object.assign(slip(new Date(pg.clock.now - 60000).toISOString()), { v: 2 }), now: new Date(pg.clock.now).toISOString() } });
  await pg.flush();
  await pg.advance(500);
  assert.equal(pg.els.ui.allText(), '', 'nothing came back from the older answer');
  assert.equal(pg.state().showing, null);
  assert.equal(pg.engine().calls.filter((c) => c === 'push').length, pushes);
  // The next ask is afresh, and what it brings is what CLIVE sends now.
  await pg.advance(2100);
  const fresh = pg.requests.filter((r) => r.method === 'GET').slice(asks);
  assert.ok(fresh.length >= 1 && fresh[0].url.endsWith('?v=-1'), fresh.map((r) => r.url).join(' '));
  await pg.advance(3000);
  assert.ok(pg.els.ui.allText().includes('Sam Carter'), 'up again only from a fresh answer');
});

// Closes B2-03 (round 10): "done", answered after the screen's ask was refused.
test('a done answered after a refusal puts nothing back, not even the other pane', async () => {
  let refuse = false;
  const gate = { done: null };
  const { pg, at } = await upWith((when) => (refuse ? { status: 403, body: { code: 'refused', detail: 'not allowed' } }
    : { version: 2, showing: Object.assign(slip(when), { v: 1 }), beside: list(when, 2) }), (request) => {
    if (request.url.endsWith('/done')) { gate.done = held(); return gate.done.promise; }
    return null;
  });
  await pg.advance(3000);                           // every page of both told to CLIVE
  const btns = pg.els.ui.querySelectorAll('.cs-btn');
  btns[1].listeners.click[0]({ stopPropagation() {}, currentTarget: btns[1] });   // the list: Mark done
  await pg.flush();
  assert.ok(gate.done, 'done was asked');
  refuse = true;
  await pg.advance(2100);
  assert.equal(pg.els.ui.allText(), '', 'refused: both panes down');
  gate.done.let({ status: 200, body: { id: SCREEN.id, name: SCREEN.name, version: 3, pending: false, last_done: null,
    showing: Object.assign(slip(at), { v: 1 }), beside: { kind: 'list', ref: '', title: 'List', at, by: 'clive', v: 3, done_at: new Date(pg.clock.now).toISOString() },
    now: new Date(pg.clock.now).toISOString() } });
  await pg.flush();
  await pg.advance(3000);
  assert.equal(pg.els.ui.allText(), '', 'the slip beside it did not come back with the late answer');
  assert.equal(pg.state().showing, null);
  assert.equal(pg.els.line.textContent, REFUSED_LINE);
});

// Closes B2-03 (round 10): the video pane's report, answered after a refusal and a fresh ask.
test('a video’s report answered after the screen was taken down and put up afresh changes nothing', async () => {
  let refuse = false;
  const gate = { report: null };
  const { pg } = await upWith((at) => (refuse ? { status: 403, body: { code: 'refused', detail: 'not allowed' } } : { version: 1, showing: clip(at, 1) }), (request) => {
    if (!request.url.endsWith('/video')) return null;
    if (!gate.report) { gate.report = held(); return gate.report.promise; }
    return { status: 200, body: { heard: true } };
  });
  const yt = player(pg);
  yt.frame.dispatch('load');
  yt.say({ event: 'onReady' });
  yt.say({ event: 'infoDelivery', info: { playerState: 1, currentTime: 2, duration: 151 } });
  await pg.flush();
  assert.ok(gate.report, 'a report is on its way');
  refuse = true;
  await pg.advance(800);
  assert.equal(yt.host.parentNode, null, 'refused: the video is down');
  refuse = false;
  await pg.advance(15100);
  assert.ok(pg.els.board.querySelector('.cs-vhost'), 'up again from a fresh ask');
  // The old report's answer: "not this screen", from before. It is not read.
  gate.report.let({ status: 403, body: { code: 'not_this_screen', detail: 'Not this screen.' } });
  await pg.flush();
  await pg.advance(100);
  assert.ok(pg.storage['clive.screen'], 'the screen is not forgotten on an old answer');
  assert.deepEqual(JSON.parse(pg.storage['clive.screen']), SCREEN, 'the screen is still this one');
  assert.equal(pg.els.namer.hidden, true);
  assert.ok(pg.els.board.querySelector('.cs-vhost'), 'and the video is still up');
});

// Closes B2-04 (round 10): the packed view is CLIVE's done summary alone, on the page and in memory.
for (const calm of [true, false]) {
  test('a slip marked packed shows only its number and when, from the moment it is marked' + (calm ? '' : ' (with the dots)'), async () => {
    // CLIVE as the store is: once done, the slip is cut to its done summary (app/displays/store.py
    // _finish), and that is what every answer carries from then on.
    const box = { state: null };
    const { pg, at } = await upWith((when) => box.state || { version: 1, showing: Object.assign(slip(when), { v: 1 }) }, (request) => {
      if (!request.url.endsWith('/done')) return null;
      box.state = { version: 2, showing: { kind: 'order', ref: 'gid://shopify/Order/1047', title: 'Order #1047', at: box.at, by: 'clive',
        done_at: new Date(pg.clock.now).toISOString(), v: 2 } };
      return { status: 200, body: Object.assign({ id: SCREEN.id, name: SCREEN.name, pending: false, beside: null, last_done: null,
        now: new Date(pg.clock.now).toISOString() }, box.state) };
    }, { calm });
    box.at = at;
    assert.ok(pg.els.ui.allText().includes('Sam Carter'));
    const btn = pg.els.ui.querySelector('.cs-btn');
    btn.listeners.click[0]({ stopPropagation() {}, currentTarget: btn });
    await pg.flush();
    assert.equal(pg.requests.filter((r) => r.url.endsWith('/done')).length, 1);
    // At once, before the dots have moved: the order's number and when, and nothing of the customer's.
    const now = pg.els.ui.allText();
    for (const detail of CUSTOMER.concat(['Heavyweight Tee', 'Canvas Tote', 'Ship to'])) assert.ok(!now.includes(detail), detail + ' is still on the page: ' + now);
    assert.ok(now.includes('Order #1047') && now.includes('Packed at'), now);
    const kept = pg.state().drawnView;
    assert.equal(kept.length, 1);
    assert.ok(kept[0].packed);
    assert.deepEqual(Object.keys(kept[0].view).sort(), ['at', 'by', 'done_at', 'kind', 'ref', 'title', 'v']);
    assert.equal(kept[0].page.fill, null, 'nothing of its pages is kept either');
    for (const detail of CUSTOMER) assert.ok(!JSON.stringify(kept[0].view).includes(detail));
    // And so it stays, for as long as it is up, and then the screen rests.
    await pg.advance(8000);
    const later = pg.els.ui.allText();
    assert.ok(later.includes('Order #1047') && later.includes('Packed at') && !CUSTOMER.some((d) => later.includes(d)), later);
    assert.ok(pg.els.ui.classList.contains('is-shown'));
    await pg.advance(45000);
    assert.equal(pg.els.ui.allText(), '', 'rested after the moment it is kept up');
  });
}

// Evidence for NEW-B-LOCAL-SLIP (round 10): the limit holds with CLIVE out of reach.
test('a slip past CLIVE’s own limit comes down even while CLIVE cannot be reached at all', async () => {
  const { pg, setMode, sam } = await shown({ age: 12 * 3600 * 1000 - 40 * 1000 });
  assert.ok(sam());
  setMode('network');
  const lost = pg.clock.now;
  await pg.advance(30 * 1000);
  assert.ok(sam(), 'ten seconds left to run');
  await pg.advance(30 * 1000);
  assert.equal(pg.els.ui.allText(), '', 'down at the limit');
  assert.ok(pg.clock.now - lost < 120 * 1000, 'before the two minutes out of reach');
  assert.equal(pg.state().showing, null, 'nor kept in memory');
  assert.equal(pg.state().drawnView, null);
  assert.ok(pg.engine().calls.includes('clear'), 'the dots that drew it went back to the clock');
});

// Evidence for NEW-B-LOCAL-SLIP (round 10): a refusal of any call, not only the ask.
test('a refusal of any call of the screen’s own takes the slip down as the ask’s own refusal does', async () => {
  const { pg } = await upWith((at) => ({ version: 1, showing: Object.assign(slip(at), { v: 1 }) }),
    (request) => (request.url.endsWith('/seen') ? { status: 403, body: { code: 'refused', detail: 'not allowed' } } : null));
  assert.ok(pg.requests.some((r) => r.url.endsWith('/seen')), 'a page was told');
  assert.equal(pg.els.ui.allText(), '');
  assert.equal(pg.els.line.textContent, REFUSED_LINE);
  assert.ok(pg.dots.made.some((e) => e.destroyed), 'with the dots that drew it');
  assert.equal(pg.state().showing, null, 'and what the page kept of it');
  assert.equal(pg.state().drawnView, null);
  assert.equal(pg.state().version, -1, 'the next ask starts afresh');
});

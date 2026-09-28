/* The screen page, run under Node against a stand-in for the page and for CLIVE (the 2026-09-27
 * deploy review, round 8).
 *
 * What is proved, with the page's own code:
 * - NEW-B-LOCAL-SLIP: a customer's slip leaves an open screen at once when CLIVE refuses the
 *   screen (403) — the page, the dots engine that drew it and what the page keeps of it — and the
 *   screen says so plainly; after two minutes out of reach it goes the same way (not before); and
 *   a slip older than CLIVE's own limit comes down even while CLIVE answers "nothing new".
 * - B-02: a screen waiting for approval shows its code and the words to say, and keeps the code
 *   off the device's storage.
 * - B-04: "done" is sent only from the Mark packed tap, with confirm, and waits when CLIVE says
 *   it came too soon.
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
const SCREEN = { id: 'scr_0123456789ab', name: 'Packing screen', key: 'key-one' };

// What the page's own drawing asks of an element, beyond what the shared stand-in has.
Element.prototype.getBoundingClientRect = function () { return { left: 0, top: 0, width: 10, height: 10, right: 10, bottom: 10 }; };
Element.prototype.getContext = function () { return context(); };
Element.prototype.remove = function () { if (this.parentNode) this.parentNode.removeChild(this); };
Element.prototype.closest = function () { return null; };

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
function page({ stored = SCREEN, answer, start = Date.UTC(2026, 8, 27, 12, 0, 0) } = {}) {
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
    addEventListener() {},
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
  const fetch = (url, opts = {}) => {
    const request = { url, method: opts.method || 'GET', headers: opts.headers || {}, body: opts.body ? JSON.parse(opts.body) : null, at: clock.now };
    requests.push(request);
    const said = answer(request);
    if (said === 'network') return Promise.reject(new TypeError('Failed to fetch'));
    return Promise.resolve(response(said.status, said.body));
  };
  const schedule = (fn, ms, every) => { timers.push({ id: ++seq, at: clock.now + Math.max(0, Number(ms) || 0), fn, every }); return seq; };
  const cancel = (id) => { const t = timers.find((x) => x.id === id); if (t) t.fn = null; };
  const window = { innerWidth: 1920, innerHeight: 1080, matchMedia: () => ({ matches: true }), addEventListener() {} };
  const sandbox = {
    window, document, console, Math, JSON, Date: FakeDate, Promise, Set, Map, Array, Number, Object, String, Error, TypeError,
    Uint8ClampedArray, isNaN, parseFloat, encodeURIComponent, AbortController,
    navigator: { hardwareConcurrency: 8 },
    location: { search: '' },
    NodeFilter: { SHOW_TEXT: 4 },
    localStorage: {
      getItem: (k) => (Object.prototype.hasOwnProperty.call(storage, k) ? storage[k] : null),
      setItem: (k, v) => { storage[k] = String(v); },
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
  const load = async () => {
    vm.runInContext(DISPLAY, sandbox, { filename: 'display.js' });
    await flush();
    await frame();
    engine().runDue();
    await flush();
    await frame();
    engine().runDue();
    await flush();
  };
  return { els, clock, requests, storage, dots, load, advance, flush, frame, engine };
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

async function shown({ age = 60 * 1000, done } = {}) {
  let mode = 'ok';
  const box = {};
  const pg = page({ answer: (r) => box.answer(r) });
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
        assert.equal(request.headers['X-Screen-Key'], SCREEN.key, 'asked for with its own key');
        return { status: 200, body: { id: SCREEN.id, name: SCREEN.name, key: 'key-two', pending: true, code: '480913', code_expires_in: 900 } };
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
  assert.equal(JSON.parse(pg.storage['clive.screen']).key, 'key-two');
  approved = true;
  await pg.advance(3000);
  assert.equal(pg.els.pairing.hidden, true, 'approved: the panel goes');
  assert.equal(pg.els['pair-code'].textContent, '480 913', 'shown until then, and nothing else was');
});

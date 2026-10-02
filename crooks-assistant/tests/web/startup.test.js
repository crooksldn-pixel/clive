/* The start-up overlay, run under Node against a small stand-in for the page (the 2026-09-27
 * deploy review, round 6, B-06).
 *
 * What is proved: whatever fails while the start-up is being built — no Canvas 2D context at
 * all, the dots engine throwing, a context that gives up part-way — the overlay is taken away
 * at once and never left covering the app; and if nothing throws but nothing ever finishes
 * either, it is taken away by its own timer, which exists before anything that can fail runs.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const WEB = path.join(__dirname, '..', '..', 'web');
const STARTUP = fs.readFileSync(path.join(WEB, 'startup.js'), 'utf8');
const DOTS = fs.readFileSync(path.join(WEB, 'dots.js'), 'utf8');

class Classes {
  constructor() { this.set = new Set(); }
  add(...n) { n.forEach((x) => this.set.add(x)); }
  remove(...n) { n.forEach((x) => this.set.delete(x)); }
  contains(n) { return this.set.has(n); }
}

class El {
  constructor(tag, page) {
    this.tag = tag;
    this.page = page;
    this.classList = new Classes();
    this.dataset = {};
    this.style = { setProperty() {} };
    this.children = [];
    this.listeners = {};
    this.removed = false;
    this.width = 0;
    this.height = 0;
  }
  set className(v) { this.classList = new Classes(); String(v).split(/\s+/).filter(Boolean).forEach((c) => this.classList.add(c)); }
  get className() { return [...this.classList.set].join(' '); }
  getContext() { return this.page.context(this); }
  appendChild(c) { this.children.push(c); return c; }
  insertBefore(c) { this.children.push(c); return c; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  getBoundingClientRect() { return { left: 0, top: 0, width: 10, height: 10, right: 10, bottom: 10 }; }
  remove() { this.removed = true; }
  get firstChild() { return this.children[0] || null; }
}

// A 2D context good enough for the engine and the name's measurements.
function goodContext() {
  return {
    font: '', fillStyle: '', textBaseline: '', globalAlpha: 1, globalCompositeOperation: '', filter: '',
    measureText: () => ({ width: 12, fontBoundingBoxAscent: 10, fontBoundingBoxDescent: 3 }),
    createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h }),
    putImageData() {}, drawImage() {}, clearRect() {}, fillRect() {}, fillText() {}, save() {}, restore() {},
    getImageData: (x, y, w, h) => ({ data: new Uint8ClampedArray(Math.max(1, w * h * 4)) }),
    setTransform() {}, beginPath() {}, arc() {}, fill() {},
  };
}

// One page: the overlay and what it reads, timers that run only when told, and a Canvas whose
// 2D context is whatever the test says (`contexts` is called once per getContext).
function page({ contexts, dots, engine }) {
  const timers = [];
  let now = 0;
  const frames = [];
  const els = {};
  const p = {};
  p.context = (el) => contexts(el);
  for (const id of ['startup', 'startup-dots', 'startup-bloom', 'startup-fx', 'startup-mark', 'startup-line', 'startup-wait', 'system', 'orb']) {
    els[id] = new El(id === 'startup-dots' || id === 'startup-bloom' || id === 'startup-fx' ? 'canvas' : 'div', p);
  }
  els.system.dataset.phase = 'connecting';
  const document = {
    getElementById: (id) => els[id] || null,
    querySelector: () => ({ getAttribute: () => 'build-1' }),
    createElement: (tag) => new El(tag, p),
    createRange: () => ({ setStart() {}, setEnd() {}, getBoundingClientRect: () => ({ left: 0, top: 0, width: 10, height: 10 }) }),
  };
  const window = {
    innerWidth: 390, innerHeight: 844, devicePixelRatio: 1,
    matchMedia: () => ({ matches: false }),
  };
  const sandbox = {
    window, document, console, Math, JSON, Date, Uint8ClampedArray, Uint32Array, Float32Array, Array, Number, Object,
    navigator: { hardwareConcurrency: 8, deviceMemory: 8, userAgent: 'test' },
    location: { search: '?startup=full' },
    URLSearchParams,
    localStorage: { getItem: () => null, setItem() {} },
    getComputedStyle: () => ({ fontStyle: 'normal', fontWeight: '600', fontSize: '30px', fontFamily: 'x' }),
    requestAnimationFrame: (fn) => { frames.push(fn); return frames.length; },
    cancelAnimationFrame() {},
    performance: { now: () => now },
    setTimeout: (fn, ms) => { timers.push({ at: now + ms, fn }); return timers.length; },
    clearTimeout: (id) => { if (timers[id - 1]) timers[id - 1].fn = null; },
    MutationObserver: class { observe() {} },
  };
  sandbox.self = window;
  Object.assign(window, sandbox);
  vm.createContext(sandbox);
  if (dots === 'real') vm.runInContext(DOTS, sandbox, { filename: 'dots.js' });
  else if (dots) window.CliveDots = dots;
  if (engine) window.CliveDots = { create: engine };
  const run = () => vm.runInContext(STARTUP, sandbox, { filename: 'startup.js' });
  const advance = (ms) => {
    const until = now + ms;
    for (;;) {
      const due = timers.filter((t) => t.fn && t.at <= until).sort((a, b) => a.at - b.at)[0];
      if (!due) break;
      now = due.at;
      const fn = due.fn;
      due.fn = null;
      fn();
    }
    now = until;
  };
  const frame = () => { const list = frames.splice(0); list.forEach((fn) => fn(now)); };
  return { run, advance, frame, root: els.startup, sandbox };
}

const gone = (root) => root.classList.contains('is-gone');

test('no Canvas 2D context at all: the overlay goes at once and is removed', () => {
  const pg = page({ contexts: () => null, dots: 'real' });
  pg.run();
  assert.ok(gone(pg.root), 'faded out immediately');
  assert.ok(!pg.root.classList.contains('is-live'), 'never marked live, so the stylesheet\'s own give-way still holds');
  pg.advance(700);
  assert.ok(pg.root.removed, 'and taken off the page');
});

test('the dots engine throws while it is being built: the overlay goes at once', () => {
  const pg = page({ contexts: goodContext, engine: () => { throw new Error('boom'); } });
  pg.run();
  assert.ok(gone(pg.root));
  pg.advance(700);
  assert.ok(pg.root.removed);
});

test('the engine starts but the next 2D context is refused: the overlay goes at once', () => {
  let calls = 0;
  const engine = () => ({ time: () => 0, destroy() {}, at() {}, boot() {}, quick() {}, setHome() {}, handoff() {}, simulate() {} });
  const pg = page({ contexts: () => (++calls === 1 ? null : goodContext()), engine });
  pg.run();
  assert.ok(pg.root.classList.contains('is-live'), 'the engine was running');
  assert.ok(gone(pg.root), 'but the name could not be measured, so the start-up stepped aside');
  pg.advance(700);
  assert.ok(pg.root.removed);
});

test('a step that fails on the first frame takes the overlay away too', () => {
  const engine = () => ({ time: () => 0, destroy() {}, at() {}, boot() { throw new Error('frame'); }, quick() { throw new Error('frame'); }, setHome() {}, handoff() {}, simulate() {} });
  const pg = page({ contexts: goodContext, engine });
  pg.run();
  assert.ok(!gone(pg.root), 'built fine');
  pg.frame(); pg.frame();
  assert.ok(gone(pg.root), 'and gone as soon as the first step threw');
});

test('nothing throws but CLIVE never answers: the overlay still goes by itself', () => {
  const engine = () => ({ time: () => 0, destroy() {}, at() {}, boot() {}, quick() {}, setHome() {}, handoff() {}, simulate() {} });
  const pg = page({ contexts: goodContext, engine });
  pg.run();
  pg.frame(); pg.frame();
  assert.ok(pg.root.classList.contains('is-live') && !gone(pg.root), 'running and waiting');
  pg.advance(19000);
  assert.ok(!gone(pg.root));
  pg.advance(1000);
  assert.ok(gone(pg.root), 'twenty seconds, whatever happened');
  pg.advance(700);
  assert.ok(pg.root.removed);
});

// 2 October (the owner: the gear did nothing for several seconds after a full start-up): once CLIVE
// is there, a tap ends the start-up at once; before that, a tap still only hurries the animation.
test('a tap once CLIVE is online ends the start-up at once', () => {
  const at = STARTUP.indexOf("root.addEventListener('pointerdown'");
  assert.notEqual(at, -1);
  const handler = STARTUP.slice(at, STARTUP.indexOf('\n  });', at));
  const online = handler.indexOf('if (ready()) { finish(); return; }');
  const hurry = handler.indexOf('E.simulate(T0 + 5.15)');
  assert.ok(online !== -1 && hurry !== -1 && online < hurry, 'online is asked first');
});

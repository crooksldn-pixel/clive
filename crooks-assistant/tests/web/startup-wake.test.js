/* The start-up's first seconds (round 12), run under Node with canvases that keep what is drawn on
 * them.
 *
 * The owner, 29 September: "the startup of clive is good except the start flash/star — that looks
 * terrible and needs to be improved or removed." The flash was a gradient filling the whole screen
 * grey; the star was a cross flare, two lines drawn from edge to edge through the orb's centre, on
 * the start-up's light canvas (web/dots.js, boot). What is proved, with the engine's own code:
 *
 * - no fill on the light canvas ever reaches past the orb's own neighbourhood, and nothing is
 *   stroked across it, until the name's glints (which the owner kept) three seconds in;
 * - the orb wakes in the app's blue, and gathers: its dots are first seen out round it and end up
 *   on it, where the old start-up burst them out of a point at its centre.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SOURCE = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'dots.js'), 'utf8');
const W = 390, H = 844;
const S = { x: W / 2, y: H * 0.46 }, R = 104;
const L = { u: 1, cell: 18, uiStep: 3, dot: 1.4, orb: { cx: S.x, cy: S.y, R }, mini: { cx: S.x, cy: S.y, R: 20 }, check: { cx: W / 2, cy: H / 2, k: 0.6, label: 40, ly: H * 0.7, step: 3 } };

// The light canvas: every fill and stroke, with the time it was drawn at and the gradient's size.
function lightCanvas(clock) {
  const c = { width: 0, height: 0, fills: [], strokes: [], gradients: [] };
  let path = [], grad = null, transform = 1;
  const ctx = {
    globalCompositeOperation: '', lineWidth: 1, filter: '',
    set fillStyle(g) { grad = g; }, get fillStyle() { return grad; },
    set strokeStyle(g) { /* a line is a line whatever its colour */ }, get strokeStyle() { return null; },
    setTransform(a) { transform = a; }, clearRect() {},
    createRadialGradient(x0, y0, r0, x1, y1, r1) { const g = { kind: 'radial', x: x1, y: y1, r: r1, stops: [] , addColorStop(k, col) { this.stops.push(col); } }; c.gradients.push(Object.assign(g, { t: clock() })); return g; },
    createLinearGradient() { return { kind: 'linear', stops: [], addColorStop(k, col) { this.stops.push(col); } }; },
    beginPath() { path = []; }, moveTo(x, y) { path.push([x, y]); }, lineTo(x, y) { path.push([x, y]); },
    arc(x, y, r) { path.push({ arc: [x, y, r] }); },
    fill() { c.fills.push({ t: clock(), shapes: path.slice(), grad }); },
    stroke() { c.strokes.push({ t: clock(), pts: path.slice() }); },
    fillRect(x, y, w, h) { c.fills.push({ t: clock(), rect: [x, y, w, h], grad }); },
  };
  c.getContext = () => ctx;
  return c;
}
// The dots canvas: what each frame put on it, kept as how much light is on the orb (core) and how
// much out round it where the gathering starts (ring: 1.3 to 4 times its radius).
function dotsCanvas(clock) {
  const c = { width: 0, height: 0, frames: [] };
  const ctx = {
    createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h }),
    putImageData(img) {
      const d = img.data, w = img.width;
      let core = 0, ring = 0;
      for (let j = 0; j < d.length; j += 4) {
        const lit = d[j] + d[j + 1] + d[j + 2];
        if (!lit) continue;
        const i = j / 4, dist = Math.hypot((i % w) - S.x, Math.floor(i / w) - S.y);
        if (dist <= R * 1.25) core += lit; else if (dist >= R * 1.3 && dist <= R * 4) ring += lit;
      }
      c.frames.push({ t: clock(), core, ring });
    },
    drawImage() {}, clearRect() {}, setTransform() {},
  };
  c.getContext = () => ctx;
  return c;
}

function boot() {
  const frames = [];
  let now = 1000;
  const sandbox = { Math, Set, Map, Array, Uint8ClampedArray, Uint32Array, Date, console, window: { devicePixelRatio: 1 },
    requestAnimationFrame: (fn) => { frames.push(fn); return frames.length; }, cancelAnimationFrame: () => {} };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(SOURCE.replace("typeof window !== 'undefined' ? window : globalThis", 'window'), sandbox, { filename: 'dots.js' });
  let E = null;
  const clock = () => (E ? E.time() : 0);
  const fx = lightCanvas(clock), dots = dotsCanvas(clock), bloom = { width: 0, height: 0, getContext: () => ({ drawImage() {}, clearRect() {} }) };
  const host = { getBoundingClientRect: () => ({ width: W, height: H }) };
  E = sandbox.window.CliveDots.create({ canvas: dots, bloom, fx, root: host, W, H, L, density: 5000, speed: 1, calm: false, maxScale: 1 });
  const glints = [{ t: 3.0, y: S.y - 60, x0: 60, x1: 330, len: 240, xi: S.x }];
  E.boot({ S, R, home: { cx: S.x, cy: 120, R: 30 }, homeBody: 0.9, endTint: 0, markBox: { x0: 100, x1: 290, y0: S.y - 15, y1: S.y + 15 }, quick: false, handoffAt: null, clock: [], glints, rows: [], markTargets: () => [] });
  const play = (ms) => { for (let t = 0; t < ms; t += 33) { now += 33; for (const fn of frames.splice(0)) fn(now); } };
  return { E, fx, dots, play };
}

const reach = (f) => {
  if (f.rect) {
    const [x, y, w, h] = f.rect;
    return Math.max(Math.hypot(x - S.x, y - S.y), Math.hypot(x + w - S.x, y + h - S.y), Math.hypot(x + w - S.x, y - S.y), Math.hypot(x - S.x, y + h - S.y));
  }
  let most = 0;
  for (const s of f.shapes) if (s.arc) most = Math.max(most, Math.hypot(s.arc[0] - S.x, s.arc[1] - S.y) + s.arc[2]);
  return most;
};

test('the start-up draws no flash and no flare: no light past the orb\'s neighbourhood, nothing stroked, before the glints', () => {
  const b = boot();
  b.play(2900);
  const early = b.fx.fills.filter((f) => f.t < 2.9);
  assert.ok(early.length > 10, 'the light canvas was drawn on during the waking');
  const worst = Math.max(...early.map(reach));
  assert.ok(worst <= R * 2.6, `a fill reached ${Math.round(worst)}px from the orb's centre (the orb is ${R}px): the old flash filled the screen`);
  const lines = b.fx.strokes.filter((s) => s.t < 2.9 && s.pts.length >= 2 && Array.isArray(s.pts[0]) && Math.hypot(s.pts[1][0] - s.pts[0][0], s.pts[1][1] - s.pts[0][1]) > R * 1.2);
  assert.equal(lines.length, 0, 'no line is drawn across the screen (the old cross flare)');
  // Only the orb's own glass and its light: no gradient bigger than its neighbourhood.
  const big = b.fx.gradients.filter((g) => g.kind === 'radial' && g.t < 2.9 && g.r > R * 2.6);
  assert.equal(big.length, 0, `a light ${big.length ? Math.round(big[0].r) : 0}px across was made`);
});

test('the orb wakes in the app\'s blue, and its dots gather in to it rather than burst out of a point', () => {
  const b = boot();
  b.play(2600);
  const blue = b.fx.gradients.filter((g) => g.kind === 'radial' && g.stops.some((c) => /^rgba\((10,132,255|64,156,255),/.test(c)));
  assert.ok(blue.length > 5, 'the waking light is iOS blue');
  // Early on, the light on the dots canvas is out round the orb; by the end, it is on it. The old
  // start-up had no dots at all before its flash, then burst them out of the centre.
  const at = (t) => b.dots.frames.filter((f) => f.t <= t).pop();
  const early = at(0.8), late = at(2.4);
  assert.ok(early && late, 'frames were drawn');
  assert.ok(early.ring > late.ring * 2, `the light out round the orb goes in (${early.ring} early, ${late.ring} late)`);
  assert.ok(late.core > early.core * 3, `and gathers on the orb (${early.core} early, ${late.core} late)`);
});

test('the glints across the name are kept: the one long line drawn is the glint, three seconds in', () => {
  const b = boot();
  b.play(3500);
  // Long straight lines only: the orb's glass has a rim (an arc) and its network short strands.
  const lines = b.fx.strokes.filter((s) => s.pts.length >= 2 && Array.isArray(s.pts[0]) && Math.hypot(s.pts[1][0] - s.pts[0][0], s.pts[1][1] - s.pts[0][1]) > R * 1.2);
  assert.ok(lines.length > 0, 'the glint is drawn');
  assert.ok(lines.every((s) => s.t >= 3.0), 'and nothing long before it');
});

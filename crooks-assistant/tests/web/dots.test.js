/* CLIVE's dots (web/dots.js), run under Node with canvases that keep what is put on them (the
 * deploy review, round 11).
 *
 * On a screen the page the dots form can carry a customer's details, as the shapes of its letters
 * (web/display.js samples the page into dot targets). What is proved, with the engine's own code,
 * by looking at every frame it draws: the page here is drawn in pure red, and nothing else the
 * engine draws is, so a frame with a pure red pixel is a frame showing the page in dots.
 *
 * - forget: the dots let go of the page at once — the frame drawn there and then has none of it,
 *   and no later frame does.
 * - packOut (B2-04): marked done, the check never forms out of the page; not one frame after it
 *   shows the page, and the check does come.
 * - destroy (NEW-B-LOCAL-SLIP): its canvases are emptied there and then, and nothing is drawn by
 *   it again, not even the frame it was destroyed in.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SOURCE = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'dots.js'), 'utf8');
const W = 400, H = 300;
const L = {
  u: 1, cell: 12, uiStep: 3, dot: 1.7,
  orb: { cx: 110, cy: 150, R: 60 }, mini: { cx: 30, cy: 24, R: 8 },
  check: { cx: 200, cy: 140, k: 0.3, label: 20, ly: 250, step: 3 },
};

// A canvas: what each frame put on it holds, counted as it is put.
function canvas() {
  const c = { width: 0, height: 0, frames: [], cleared: 0 };
  const ctx = {
    filter: '', globalCompositeOperation: '', fillStyle: '', strokeStyle: '', lineWidth: 1,
    createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h }),
    putImageData(img) {
      const d = img.data;
      let red = 0, green = 0, lit = 0;
      for (let j = 0; j < d.length; j += 4) {
        if (d[j] || d[j + 1] || d[j + 2]) lit++;
        if (d[j] >= 24 && d[j + 1] === 0 && d[j + 2] === 0) red++;
        if (d[j + 1] >= 24 && d[j + 1] > d[j] * 2) green++;
      }
      c.frames.push({ red, green, lit });
    },
    clearRect() { c.cleared++; },
    drawImage() {}, setTransform() {}, beginPath() {}, arc() {}, fill() {}, stroke() {}, moveTo() {}, lineTo() {}, fillRect() {},
    createLinearGradient: () => ({ addColorStop() {} }), createRadialGradient: () => ({ addColorStop() {} }),
  };
  c.getContext = () => ctx;
  return c;
}

// One engine, its canvases, and its frames, which run only when the test says.
function engine() {
  const frames = [];
  let now = 1000;
  const sandbox = {
    Math, Set, Map, Array, Uint8ClampedArray, Uint32Array, Date, console,
    window: { devicePixelRatio: 1 },
    requestAnimationFrame: (fn) => { frames.push(fn); return frames.length; },
    cancelAnimationFrame: () => {},
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(SOURCE.replace("typeof window !== 'undefined' ? window : globalThis", 'window'), sandbox, { filename: 'dots.js' });
  const dots = canvas(), bloom = canvas(), fx = canvas();
  const host = { getBoundingClientRect: () => ({ width: W, height: H }) };
  const E = sandbox.window.CliveDots.create({ canvas: dots, bloom, fx, root: host, W, H, L, density: 3000, speed: 1, calm: false, palette: 'steel' });
  // Engine time passes a frame at a time (15 a second), each frame drawn.
  const play = (ms) => {
    for (let t = 0; t < ms; t += 66) { now += 66; for (const fn of frames.splice(0)) fn(now); }
  };
  return { E, dots, bloom, fx, play, frames };
}

// A page, as a screen samples it: a block of text, in pure red.
function page() {
  const out = [];
  for (let y = 60; y < 120; y += 3) for (let x = 180; x < 360; x += 3) out.push({ x, y, r: 255, g: 0, b: 0, a: 0.9, s: 1.7 });
  return out;
}
// The check, in the design's green.
function check() {
  const out = [];
  for (let i = 0; i < 400; i++) out.push({ x: 150 + (i % 40) * 3, y: 120 + Math.floor(i / 40) * 3, r: 48, g: 209, b: 88, a: 0.9, s: 1.9 });
  return out;
}
const red = (frames) => frames.filter((f) => f.red > 0).length;

// The page landed and resting in dots, as a screen's page is while its dots are still showing it.
function landed() {
  const d = engine();
  d.play(100);
  d.E.push(page());
  d.play(3600);
  assert.ok(d.dots.frames[d.dots.frames.length - 1].red > 50, 'the page is drawn in dots: the test can see it');
  return d;
}

// Round 11 (NEW-B-LOCAL-SLIP and B2-04).
test('forget: the dots let go of the page at once, in the frame drawn there and then and every one after', () => {
  const d = landed();
  const from = d.dots.frames.length;
  d.E.forget();
  assert.equal(d.dots.frames.length, from + 1, 'drawn again at once, not at the next frame');
  assert.equal(d.dots.frames[from].red, 0, 'without the page');
  d.play(3000);
  assert.equal(red(d.dots.frames.slice(from)), 0, 'and no frame after shows it');
  assert.ok(d.dots.frames[d.dots.frames.length - 1].lit > 0, 'the orb and its dust are still drawn');
});

// Round 11 (B2-04).
test('packOut: marked done, the check comes out of the orb and not one frame after shows the page again', () => {
  const d = landed();
  d.E.sweepOut(d.E.time(), 0.4);                  // revealed, as a screen's page is once it is shown
  d.play(1500);
  const from = d.dots.frames.length;
  d.E.packOut(check());
  d.play(2600);
  const after = d.dots.frames.slice(from);
  assert.equal(red(after), 0, 'the page is never formed again on the way to the check');
  assert.ok(after.some((f) => f.green > 50), 'and the check comes');
  // The page it goes back into is the done page, sampled anew: here, a white one.
  d.E.packIn(page().map((t) => Object.assign({}, t, { r: 255, g: 255, b: 255 })), d.E.time() + 0.2);
  d.play(2000);
  assert.equal(red(d.dots.frames.slice(from)), 0);
});

// Round 11 (NEW-B-LOCAL-SLIP).
test('destroy: the canvases are emptied there and then, and nothing is drawn by it again', () => {
  const d = landed();
  const from = d.dots.frames.length, cleared = d.bloom.cleared + d.fx.cleared;
  d.E.destroy();
  assert.equal(d.dots.frames.length, from + 1, 'the canvas is put blank at once');
  assert.equal(d.dots.frames[from].lit, 0, 'nothing on it at all');
  assert.ok(d.bloom.cleared + d.fx.cleared >= cleared + 2, 'and the bloom and light canvases are emptied');
  d.play(2000);
  assert.equal(d.dots.frames.length, from + 1, 'and it never draws again');
  // Asked for anything after (a page callback that was on its way), it draws nothing either.
  d.E.forget();
  assert.equal(d.dots.frames.length, from + 1);
});

// Round 11 (NEW-B-LOCAL-SLIP): destroyed from inside one of its own frames (a page callback it
// runs), that frame is not drawn.
test('destroyed from inside its own frame, that frame is not drawn', () => {
  const d = landed();
  d.E.at(d.E.time() + 0.01, () => d.E.destroy());
  const from = d.dots.frames.length;
  d.play(200);
  assert.equal(d.dots.frames.length, from + 1, 'only the blank the destroy put');
  assert.equal(d.dots.frames[from].lit, 0);
});

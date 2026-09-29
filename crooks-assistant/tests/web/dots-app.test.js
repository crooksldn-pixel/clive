/* Cards that form out of CLIVE's dots (web/dots-app.js), run under Node against a stand-in page
 * whose canvases keep what is drawn on them.
 *
 * The owner, 29 September: "the dots that currently make up the tv screen in text and animation
 * work well and i want to see that used elsewhere such as on clive as an active animation instead
 * of boxes just appearing." What is proved, on the engine's own clock:
 *
 * - a card put in the deck is hidden at once (before it is ever painted), forms out of dots that
 *   leave the orb, and hands over: the dots are gone by 430ms and the canvas is emptied and put
 *   away; the stylesheet shows the card from 190ms and fully by 340ms whatever the dots do;
 * - a card taken away mid-forming: every dot drawing its words is dropped there and then, the
 *   canvas is drawn again at once without them, and what goes back to the orb is its outline;
 * - a card replaced in place (a patch, an action's result) neither forms nor goes;
 * - reduced motion: nothing at all; the weak path: at most 700 dots, no letter shapes read back
 *   from a canvas, and a canvas no finer than the tablet's own pixels;
 * - the page hidden: everything stops and the canvas is emptied.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const D = require('../../web/dots-app.js');

const WORDS = 'rgb(240,244,250)', SHAPE = 'rgb(178,188,206)';

// ---- a stand-in page ------------------------------------------------------------------------

class Classes {
  constructor() { this.set = new Set(); }
  add(...n) { n.forEach((x) => this.set.add(x)); }
  remove(...n) { n.forEach((x) => this.set.delete(x)); }
  contains(n) { return this.set.has(n); }
  toggle(n, on) { if (on === undefined ? !this.set.has(n) : on) this.set.add(n); else this.set.delete(n); }
}
// A canvas whose 2D context records every square it fills, the colour it filled it with, and how
// often it was emptied. As the letter-shape canvas, what fillText writes reads back as solid ink.
function canvasEl() {
  const c = { width: 0, height: 0, classList: new Classes(), attrs: {}, fills: [], clears: 0, reads: 0, texts: [] };
  c.setAttribute = (k, v) => { c.attrs[k] = v; };
  let ink = new Uint8ClampedArray(0);
  let tf = [1, 0, 0, 1, 0, 0];
  const ctx = {
    fillStyle: '', globalAlpha: 1, globalCompositeOperation: '', font: '', textBaseline: '', letterSpacing: '0px',
    setTransform(...m) { tf = m; }, clearRect() { c.clears++; },
    fillRect(x, y, w, h) { c.fills.push({ x, y, w, h, style: ctx.fillStyle, a: ctx.globalAlpha }); },
    measureText: (t) => ({ width: String(t).length * 8, fontBoundingBoxAscent: 16, fontBoundingBoxDescent: 4 }),
    fillText(t, x0, y0) {
      // Where the text lands with the transform it was drawn under, at 8px a letter in its size.
      const x = tf[0] * x0 + tf[4], y = tf[3] * y0 + tf[5];
      c.texts.push({ t, x, y });
      if (ink.length !== c.width * c.height * 4) ink = new Uint8ClampedArray(c.width * c.height * 4);
      const w = String(t).length * 8 * tf[0] * 1.3;
      for (let yy = Math.max(0, Math.floor(y - 14)); yy < Math.min(c.height, Math.floor(y)); yy++) {
        for (let xx = Math.max(0, Math.floor(x)); xx < Math.min(c.width, Math.floor(x + w)); xx++) ink[(yy * c.width + xx) * 4 + 3] = 255;
      }
    },
    getImageData(x, y, w, h) {
      c.reads++;
      const out = new Uint8ClampedArray(w * h * 4);
      if (ink.length !== c.width * c.height * 4) return { data: out };
      for (let yy = 0; yy < h; yy++) for (let xx = 0; xx < w; xx++) out[(yy * w + xx) * 4 + 3] = ink[((y + yy) * c.width + x + xx) * 4 + 3];
      return { data: out };
    },
  };
  c.getContext = () => ctx;
  return c;
}
class TextNode { constructor(value, parent) { this.nodeType = 3; this.nodeValue = value; this.parentNode = parent; } }
// A card: a box on the glass and lines of text inside it, each a box of its own.
function card(rect, lines, extra) {
  const el = {
    nodeType: 1, classList: new Classes(), dataset: Object.assign({}, (extra || {}).dataset), connected: true,
    rect: Object.assign({}, rect), lines: [],
    get isConnected() { return this.connected; },
    getBoundingClientRect() { const r = this.rect; return { left: r.x, top: r.y, width: r.w, height: r.h, right: r.x + r.w, bottom: r.y + r.h }; },
  };
  el.classList.add('card');
  for (const [dx, dy, w, h, text] of lines) el.lines.push(new TextNode(text, { rel: [dx, dy, w, h], owner: el }));
  return el;
}
function world(opts) {
  const o = opts || {};
  let clock = 1000;
  const frames = [];
  const canvases = [];
  const deck = { children: [], scrollTop: 0, addEventListener() {}, get firstElementChild() { return this.children[0] || null; }, offsetHeight: 700 };
  const orb = { getBoundingClientRect: () => ({ left: 20, top: 20, width: 60, height: 60, right: 80, bottom: 80 }) };
  const docListeners = {};
  const doc = {
    hidden: false,
    body: { appendChild(c) { return c; } },
    documentElement: { dataset: o.lite ? { lite: '1' } : {} },
    getElementById: (id) => (id === 'orb-frame' ? orb : null),
    createElement: () => { const c = canvasEl(); canvases.push(c); return c; },
    addEventListener: (t, fn) => { docListeners[t] = fn; },
    createTreeWalker(root) {
      const list = root.lines.slice();
      let i = 0;
      return { nextNode: () => list[i++] || null };
    },
    createRange() {
      let node = null;
      const box = () => { const [dx, dy, w, h] = node.parentNode.rel; const r = node.parentNode.owner.rect; return { left: r.x + dx, top: r.y + dy, width: w, height: h, right: r.x + dx + w, bottom: r.y + dy + h }; };
      return {
        selectNodeContents(n) { node = n; },
        setStart(n) { node = n; }, setEnd() {},
        getClientRects: () => [box()],
        getBoundingClientRect: () => box(),
      };
    },
  };
  const win = {
    innerWidth: 601, innerHeight: 889, devicePixelRatio: 1.33,
    navigator: { hardwareConcurrency: o.cores || 8 },
    getComputedStyle: () => ({ borderTopLeftRadius: '26px', fontStyle: 'normal', fontWeight: '600', fontSize: '24px', fontFamily: 'system-ui', letterSpacing: 'normal', textTransform: 'none' }),
    matchMedia: () => ({ matches: !!o.reduced, addEventListener() {} }),
    addEventListener() {},
  };
  const E = D.create({
    win, doc, deck,
    now: () => clock,
    raf: (fn) => { frames.push(fn); return frames.length; },
    random: (() => { let s = 7; return () => { s = (s * 16807) % 2147483647; return s / 2147483647; }; })(),
  });
  // One frame at a time, 16ms apart, each drawn.
  const play = (ms) => { for (let t = 0; t < ms; t += 16) { clock += 16; for (const fn of frames.splice(0)) fn(); } };
  const put = (c) => { deck.children.push(c); E.onMutations([{ addedNodes: [c], removedNodes: [] }]); };
  const take = (c) => { c.connected = false; deck.children = deck.children.filter((x) => x !== c); E.onMutations([{ addedNodes: [], removedNodes: [c] }]); };
  return { E, win, doc, deck, canvases, play, put, take, docListeners, time: () => clock, frames };
}
const order = () => card({ x: 14, y: 180, w: 573, h: 320 }, [
  [18, 18, 70, 12, 'ORDER'], [18, 36, 140, 28, '#1957'], [18, 72, 230, 18, 'Mia Jones, 12 Park Road'], [18, 100, 180, 18, '£89.00 paid'],
]);
const overlay = (w) => w.canvases.find((c) => c.classList && c.attrs['aria-hidden'] === 'true');

// ---- forming ---------------------------------------------------------------------------------

test('a card put in the deck is hidden at once, forms out of the orb\'s dots, and hands over by 430ms', () => {
  const w = world();
  const c = order();
  w.put(c);
  assert.ok(c.classList.contains('dots-forming'), 'hidden by the stylesheet before any frame is painted');
  assert.ok(w.E.isForming(c));
  w.play(16);
  const cv = overlay(w);
  assert.ok(cv && cv.classList.contains('is-on'), 'the canvas is shown while there are dots on it');
  assert.ok(w.E.dotCount() > 200, `the card's outline and words are dots (${w.E.dotCount()})`);
  assert.ok(w.E.wordsFor(c) > 50, 'its words among them');
  // The first dots seen leave from the orb (its centre is 50,50).
  w.play(32);
  const first = cv.fills.slice(0, 50);
  assert.ok(first.length === 50 && first.every((f) => Math.hypot(f.x - 50, f.y - 50) < 120), 'they come out of the orb');
  w.play(190);
  const landed = cv.fills.slice(-200);
  assert.ok(landed.every((f) => f.x > 10 && f.x < 590 && f.y > 170 && f.y < 505), 'by 240ms they are on the card');
  w.play(220);
  assert.equal(w.E.dotCount(), 0, 'gone by 430ms');
  assert.ok(!cv.classList.contains('is-on'), 'the canvas is put away');
  assert.ok(!w.E.isForming(c), 'the card is formed');
  assert.ok(c.classList.contains('dots-forming'), 'its class stays, so no entrance replays');
});

test('the stylesheet shows the card from 190ms and fully by 340ms, and holds nothing after', () => {
  const css = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'dots-app.css'), 'utf8');
  const rule = css.match(/#cards > \.card\.dots-forming\{animation:dots-card-in (\d+)ms linear (\w+)\}/);
  assert.ok(rule, 'the forming card has its own entrance');
  const runs = Number(rule[1]);
  assert.ok(runs <= 400, `fully shown by ${runs}ms: readable within about 400ms`);
  assert.equal(rule[2], 'backwards', 'nothing held after it ends (an archived thread keeps its own dimming)');
  const hidden = Number(css.match(/0%,([\d.]+)%\{opacity:0/)[1]);
  assert.ok(Math.abs(runs * hidden / 100 - D.TIMING.SHOW_FROM) < 2, 'hidden while the dots fly, on the same clock as the dots');
  assert.equal(D.TIMING.SHOWN_BY, runs);
  assert.match(css, /prefers-reduced-motion:reduce\)\{#cards > \.card\.dots-forming\{animation:none\}/);
  // The weak path's brisker clock: the same entrance in 0.7 of the time, on both sides.
  const brisk = Number(css.match(/\.dots-forming\.dots-brisk\{animation-duration:(\d+)ms\}/)[1]);
  assert.equal(brisk, Math.round(runs * D.BRISK));
});

test('the dots follow the card while the deck moves under it', () => {
  const w = world();
  const c = order();
  w.put(c);
  w.play(32);
  c.rect.y -= 14;                       // the orb's band shrinking as the screen changes
  w.play(230);
  const cv = overlay(w);
  const last = cv.fills.slice(-150);
  assert.ok(last.every((f) => f.y > 156 && f.y < 492), 'they land where the card is now, not where it was');
});

// ---- going ---------------------------------------------------------------------------------

test('a card taken away mid-forming: its words are dropped at once and never drawn again', () => {
  const w = world();
  const c = order();
  w.put(c);
  w.play(120);
  const cv = overlay(w);
  assert.ok(w.E.wordsFor(c) > 0);
  const clears = cv.clears, drawn = cv.fills.length;
  w.take(c);
  assert.equal(w.E.wordsFor(c), 0, 'no dot of its words is left');
  assert.ok(cv.clears > clears, 'the canvas was drawn again there and then, not at the next frame');
  assert.ok(cv.fills.slice(drawn).every((f) => f.style !== WORDS), 'and that drawing has none of its words');
  w.play(600);
  assert.ok(cv.fills.slice(drawn).every((f) => f.style !== WORDS), 'nor does any drawing after');
  assert.ok(!c.classList.contains('dots-forming'), 'the card is let go of');
  assert.equal(w.E.dotCount(), 0, 'and the canvas is empty');
  assert.ok(!cv.classList.contains('is-on'));
});

test('a card taken away after it formed goes back towards the orb as its shape, and is gone', () => {
  const w = world();
  const c = order();
  w.put(c);
  w.play(500);
  const cv = overlay(w);
  const drawn = cv.fills.length;
  w.take(c);
  assert.equal(w.E.stats().dissolved, 1);
  w.play(48);
  const going = cv.fills.slice(drawn);
  assert.ok(going.length > 50, 'it goes as dots');
  assert.ok(going.every((f) => f.style === SHAPE), 'its outline and body, never its words');
  w.play(600);
  assert.equal(w.E.dotCount(), 0);
  assert.ok(!cv.classList.contains('is-on'), 'and the canvas is put away');
});

test('a card replaced in place (a patch, an action\'s result) neither forms nor goes', () => {
  const w = world();
  const old = order();
  w.put(old);
  w.play(500);
  const fresh = order();
  fresh.dataset.patched = '1';
  old.connected = false;
  w.deck.children = [fresh];
  w.E.onMutations([{ addedNodes: [fresh], removedNodes: [old] }]);
  assert.ok(!fresh.classList.contains('dots-forming'), 'the new words simply appear in the same card');
  assert.equal(w.E.stats().dissolved, 0, 'and the old one does not go as dots');
  // And a card shown again in the same breath (moved, or its deck brought back) is left alone.
  w.E.onMutations([{ addedNodes: [], removedNodes: [fresh] }, { addedNodes: [fresh], removedNodes: [] }]);
  assert.ok(!fresh.classList.contains('dots-forming'));
});

// ---- when it does not run ---------------------------------------------------------------------

test('reduced motion: no card forms from dots and no canvas is ever made', () => {
  const w = world({ reduced: true });
  const c = order();
  w.put(c);
  w.play(500);
  assert.ok(!c.classList.contains('dots-forming'));
  assert.equal(w.canvases.length, 0);
  w.take(c);
  assert.equal(w.canvases.length, 0);
});

test('the weak path: at most 700 dots, no letter shapes read back, a canvas at the tablet\'s own pixels, a brisker clock', () => {
  const w = world({ cores: 4 });
  const many = [order(), order(), order()];
  many[1].rect.y = 520; many[2].rect.y = 860;
  for (const c of many) w.put(c);
  assert.ok(many.every((c) => c.classList.contains('dots-brisk')), 'the stylesheet runs the brisker clock for these cards');
  w.play(16);
  assert.ok(w.E.stats().weak);
  assert.ok(w.E.dotCount() <= 700 && w.E.dotCount() > 100, `${w.E.dotCount()} dots`);
  assert.ok(w.canvases.every((c) => c.reads === 0 && c.texts.length === 0), 'no text drawn to be read back');
  const cv = overlay(w);
  assert.ok(cv.width <= Math.round(601 * 1.34) && cv.height <= Math.round(889 * 1.34));
  w.play(300);
  assert.equal(w.E.dotCount(), 0, 'gone by 0.7 of 430ms');
  assert.ok(many.every((c) => !w.E.isForming(c)));
});

test('the strong path draws the words as letter shapes', () => {
  const w = world();
  w.put(order());
  w.play(16);
  const glyphs = w.canvases.find((c) => c.texts.length);
  assert.ok(glyphs, 'the words were drawn as the browser drew them');
  assert.deepEqual(glyphs.texts.map((t) => t.t).sort(), ['#1957', 'ORDER', '£89.00 paid', 'Mia Jones, 12 Park Road'].sort());
  assert.ok(w.E.dotCount() <= 2200);
});

test('the page hidden: everything stops and the canvas is emptied', () => {
  const w = world();
  const c = order();
  w.put(c);
  w.play(64);
  const cv = overlay(w);
  w.doc.hidden = true;
  w.E.stopAll();
  assert.equal(w.E.dotCount(), 0);
  assert.ok(!cv.classList.contains('is-on'));
  assert.ok(!w.E.isForming(c));
  // Put in while hidden: shown as it is, no dots.
  const d = order();
  w.put(d);
  assert.ok(!d.classList.contains('dots-forming'));
});

test('a card below the fold forms no dots but is still shown on the stylesheet\'s clock', () => {
  const w = world();
  const c = order();
  c.rect.y = 1200;
  w.put(c);
  w.play(16);
  assert.equal(w.E.dotCount(), 0);
  assert.ok(c.classList.contains('dots-forming'));
  w.play(500);
  assert.ok(!w.E.isForming(c));
});

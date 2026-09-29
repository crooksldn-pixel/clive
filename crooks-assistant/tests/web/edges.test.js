/* Soft scroll edges (web/edges.js), run under Node against stand-in scrolling areas.
 *
 * The owner, 29 September: "when text scrolls out of view it should not be clipped but gradually
 * blur, same as at the bottom row. text that appears from no where or hidden behind an invisible
 * barrier looks cheap and unintentional." What is proved:
 *
 * - an edge fades only while there is content beyond it, and by how much there is, up to its size:
 *   at the top of a list no top fade, ten pixels down a ten-pixel fade, at the end no bottom fade;
 * - an area that fits carries no mask at all (it costs nothing);
 * - the sideways strips (the trail of chips, a card's tabs, a table) do the same left and right;
 * - the blur band is laid over a big area's fading edges only where the device is not lite, and
 *   goes when its area goes;
 * - every scrolling area the app has is named, so none is left with a hard edge.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const E = require('../../web/edges.js');

// ---- the arithmetic -------------------------------------------------------------------------

test('fadeFor: an edge fades only by as much as there is beyond it, up to its size', () => {
  assert.deepEqual(E.fadeFor(0, 400, 1000, 44), { start: 0, end: 44 }, 'at the top: no top fade');
  assert.deepEqual(E.fadeFor(10, 400, 1000, 44), { start: 10, end: 44 }, 'ten pixels down: a ten-pixel fade');
  assert.deepEqual(E.fadeFor(300, 400, 1000, 44), { start: 44, end: 44 }, 'in the middle: both, full');
  assert.deepEqual(E.fadeFor(590, 400, 1000, 44), { start: 44, end: 10 }, 'ten pixels from the end');
  assert.deepEqual(E.fadeFor(600, 400, 1000, 44), { start: 44, end: 0 }, 'at the end: the last line is not faded');
  assert.deepEqual(E.fadeFor(0, 400, 400, 44), { start: 0, end: 0 }, 'a list that fits: nothing');
  assert.deepEqual(E.fadeFor(-30, 400, 1000, 44), { start: 0, end: 44 }, 'pulled past the top (iOS bounce): no top fade');
  assert.deepEqual(E.fadeFor(50, 100, 1000, 44), { start: 25, end: 25 }, 'never more than a quarter of what the area shows');
});

test('maskFor: nothing when neither edge fades; an eased ramp on each edge that does', () => {
  assert.equal(E.maskFor('y', 0, 0), '');
  const both = E.maskFor('y', 40, 20);
  assert.match(both, /^linear-gradient\(to bottom, /);
  assert.match(both, /rgba\(0,0,0,0\) 0px/, 'transparent at the very top edge');
  assert.match(both, /#000 40px/, 'solid from the end of the top fade');
  assert.match(both, /#000 calc\(100% - 20px\)/, 'solid until the bottom fade starts');
  assert.match(both, /rgba\(0,0,0,0\) 100%/, 'transparent at the very bottom edge');
  assert.match(both, /rgba\(0,0,0,0.5\) 20px/, 'eased: half way at half the fade');
  const top = E.maskFor('y', 12, 0);
  assert.match(top, /#000 12px, #000 100%\)$/, 'no fade at a bottom with nothing beyond it');
  assert.match(E.maskFor('y', 0, 12), /^linear-gradient\(to bottom, #000 0px, #000 calc\(100% - 12px\)/, 'nor at a top with nothing above it');
  assert.match(E.maskFor('x', 0, 30), /^linear-gradient\(to right, /);
});

// ---- the engine, against stand-in areas ------------------------------------------------------

class Stub {
  constructor(id, cls, box) {
    this.id = id || ''; this.className = cls || ''; this.nodeType = 1;
    this.style = {}; this.attrs = {}; this.children = []; this.parentNode = null; this.listeners = {};
    Object.assign(this, { scrollTop: 0, scrollLeft: 0, clientHeight: 0, scrollHeight: 0, clientWidth: 0, scrollWidth: 0,
      offsetTop: 0, offsetLeft: 0, clientTop: 0, clientLeft: 0, connected: true }, box || {});
  }
  get isConnected() { return this.connected; }
  get dataset() {
    const out = {};
    for (const [k, v] of Object.entries(this.attrs)) if (k.startsWith('data-')) out[k.slice(5).replace(/-(\w)/g, (m, c) => c.toUpperCase())] = v;
    return out;
  }
  matches(sel) {
    return sel.split(',').some((one) => {
      const s = one.trim();
      if (s.startsWith('#')) return this.id === s.slice(1);
      if (s.startsWith('.')) return this.className.split(/\s+/).includes(s.slice(1));
      return false;
    });
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, fn) { this.listeners[t] = fn; }
  removeEventListener(t) { delete this.listeners[t]; }
  get firstElementChild() { return this.children[0] || null; }
  get nextElementSibling() { const p = this.parentNode; if (!p) return null; const i = p.children.indexOf(this); return p.children[i + 1] || null; }
  get previousSibling() { const p = this.parentNode; if (!p) return null; const i = p.children.indexOf(this); return p.children[i - 1] || null; }
  get nextSibling() { return this.nextElementSibling; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  insertBefore(c, before) {
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this;
    const i = before ? this.children.indexOf(before) : -1;
    if (i === -1) this.children.push(c); else this.children.splice(i, 0, c);
    return c;
  }
  removeChild(c) { const i = this.children.indexOf(c); if (i !== -1) this.children.splice(i, 1); c.parentNode = null; return c; }
  querySelectorAll(sel) {
    const out = [];
    const walk = (n) => { for (const c of n.children) { if (c.matches(sel)) out.push(c); walk(c); } };
    walk(this);
    return out;
  }
  scroll(to) { this.scrollTop = to; if (this.listeners.scroll) this.listeners.scroll(); }
}

function page(opts) {
  const o = opts || {};
  const body = new Stub('', 'body');
  const frames = [];
  const doc = {
    body, documentElement: { dataset: o.lite ? { lite: '1' } : {} },
    createElement: () => new Stub('', ''),
    addEventListener() {},
  };
  const win = {
    requestAnimationFrame: (fn) => { frames.push(fn); return frames.length; },
    addEventListener() {},
    CSS: { supports: (p) => /backdrop-filter/.test(p) && !o.noBlur },
  };
  const edges = E.create(win, doc);
  const flush = () => { for (const fn of frames.splice(0)) fn(); };
  return { body, doc, win, edges, flush };
}
// What the engine drew on an area: its top (or left) and bottom (or right) fade, in px.
const fades = (p, el) => { const st = p.edges.state(el); return st ? [st.start, st.end] : null; };
function area(p, id, cls, box) {
  const wrap = p.body.appendChild(new Stub('', 'wrap'));
  const el = wrap.appendChild(new Stub(id, cls, box));
  p.edges.adopt(el);
  p.flush();
  return el;
}

test('a long list: no top fade at the top, both edges once scrolled, no bottom fade at the end', () => {
  const p = page();
  const home = area(p, 'alpha-home', 'alpha-home', { clientHeight: 600, scrollHeight: 1400 });
  assert.deepEqual(fades(p, home), [0, 44], 'at the top of the list no top fade; the bottom fades, there is more below');
  assert.ok(home.style.maskImage && home.style.webkitMaskImage, 'the mask is written for Chrome and Safari alike');
  home.scroll(12); p.flush();
  assert.deepEqual(fades(p, home), [12, 44], 'twelve pixels down: the top fade has grown to twelve');
  home.scroll(300); p.flush();
  assert.deepEqual(fades(p, home), [44, 44]);
  home.scroll(800); p.flush();
  assert.deepEqual(fades(p, home), [44, 0], 'at the end, the last row is whole');
  assert.doesNotMatch(home.style.maskImage, /calc\(100% - \d/, 'and the mask has no bottom ramp');
});

test('an area that fits carries no mask at all', () => {
  const p = page();
  const deck = area(p, 'cards', 'cards', { clientHeight: 700, scrollHeight: 700 });
  assert.equal(deck.style.maskImage, undefined, 'never written');
  assert.deepEqual(fades(p, deck), [0, 0]);
  assert.deepEqual(deck.attrs, {}, 'and nothing else is written on it');
  // It grows past the screen (a card added): the bottom fade comes; it shrinks back: it goes.
  deck.scrollHeight = 1100; p.edges.touch(deck); p.flush();
  assert.deepEqual(fades(p, deck), [0, 44]);
  deck.scrollHeight = 700; p.edges.touch(deck); p.flush();
  assert.equal(deck.style.maskImage, '', 'taken off again');
  assert.deepEqual(fades(p, deck), [0, 0]);
});

test('the sideways strips fade left and right the same way', () => {
  const p = page();
  const nav = area(p, 'context-nav', 'context-nav', { clientWidth: 573, scrollWidth: 900 });
  assert.deepEqual(fades(p, nav), [0, 32], 'at the start of the trail, no left fade');
  assert.match(nav.style.maskImage, /to right/);
  nav.scrollLeft = 327; nav.listeners.scroll(); p.flush();
  assert.deepEqual(fades(p, nav), [32, 0], 'scrolled to the end: the chips gone off the left fade');
});

test('the blur band: laid over a big area\'s fading edges where the device is not lite, and gone with the area', () => {
  const p = page();
  const deck = area(p, 'cards', 'cards', { clientHeight: 600, scrollHeight: 1400, offsetTop: 120, offsetLeft: 0, clientWidth: 601 });
  const veils = deck.parentNode.children.filter((c) => /^edge-veil /.test(c.className));
  assert.equal(veils.length, 2, 'two bands, beside the area');
  const [start, end] = veils;
  assert.equal(start.className, 'edge-veil edge-veil-start');
  assert.equal(end.className, 'edge-veil edge-veil-end');
  assert.equal(start.style.top, '120px');
  assert.equal(start.style.opacity, '0', 'no band at the top of the list');
  assert.equal(end.style.top, `${120 + 600 - 44}px`);
  assert.equal(end.style.opacity, '1');
  deck.scroll(22); p.flush();
  assert.equal(start.style.opacity, '0.5', 'the band follows the fade');
  // The area is taken off the page: its bands go too.
  deck.connected = false;
  p.edges.touch(deck); p.flush();
  assert.equal(deck.parentNode.children.filter((c) => /^edge-veil /.test(c.className)).length, 0);
  assert.equal(p.edges.size(), 0);
});

test('the weak tablet keeps the fade and does without the blur band', () => {
  const lite = page({ lite: true });
  const deck = area(lite, 'cards', 'cards', { clientHeight: 600, scrollHeight: 1400 });
  assert.deepEqual(fades(lite, deck), [0, 44], 'the fade is there');
  assert.equal(deck.parentNode.children.filter((c) => /^edge-veil /.test(c.className)).length, 0, 'no band');
  const old = page({ noBlur: true });
  const d2 = area(old, 'cards', 'cards', { clientHeight: 600, scrollHeight: 1400 });
  assert.equal(d2.parentNode.children.filter((c) => /^edge-veil /.test(c.className)).length, 0, 'nor where backdrop-filter is not there');
});

test('areas added later are found as they are put on the page', () => {
  const p = page();
  const sheet = new Stub('', 'sheet');
  const scroll = sheet.appendChild(new Stub('', 'sheet-scroll alpha-scroll', { clientHeight: 700, scrollHeight: 1500 }));
  p.body.appendChild(sheet);
  p.edges.scan();
  p.flush();
  assert.deepEqual(fades(p, scroll), [0, 36]);
});

// ---- every scrolling area of the app is named ------------------------------------------------

test('every area the stylesheets let scroll is one the edges know', () => {
  const web = path.join(__dirname, '..', '..', 'web');
  const known = E.AREAS.map((a) => a.sel);
  // The scrolling rules in the app's own stylesheets, by the selector that opens them.
  const scrolling = [];
  for (const file of ['style.css', 'alpha.css', 'remote.css']) {
    const css = fs.readFileSync(path.join(web, file), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
    const re = /([^{}]+)\{([^{}]*overflow(?:-[xy])?\s*:\s*(?:auto|scroll)[^{}]*)\}/g;
    let m;
    while ((m = re.exec(css))) for (const sel of m[1].split(',')) scrolling.push(sel.trim());
  }
  // The body text inside an input field scrolls in the field's own frame; that is the field's.
  const own = scrolling.filter((sel) => !/textarea|input/.test(sel));
  assert.ok(own.length >= 8, `found the app's scrolling areas (${own.length})`);
  const missing = own.filter((sel) => !known.some((k) => sel === k || sel.endsWith(k) || sel.includes(k)));
  assert.deepEqual(missing, [], 'a scrolling area with no soft edge');
});

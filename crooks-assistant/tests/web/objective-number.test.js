/* Objectives by touch, part C: a number to reach (web/objective-number.js with web/objective-cards.js,
 * web/objective-touch.js, web/horizon.js and web/distances.js), under Node.
 *
 * "Loopback Hoodie · a number", as the design draws it, from the card the Mac sends: 138 of 200 sold,
 * the pace in the Mac's own words, the chart of dots (a dot is ten in total, one a day per day), the
 * matrix faint, the target a row of light and where the pace meets it. What is held, on a DOM
 * stand-in with a clock moved by hand: a double-tap on the chart or the two buttons switch Total and
 * Per day and say so without touching the record; a tap says what a day holds; two fingers on the
 * chart show more or fewer days and are never the sheet's pinch; the target dragged a dot at a time,
 * red before the finger lets go when the pace falls short, sent on release, with Undo; the slider from
 * the keyboard; a count that could not be read draws no chart and says why; a card that came without a
 * count asks the owner's route once; the ring of twenty on the home row and the day the pace lands on
 * the next six weeks; and every word from the Mac as text, never in an attribute. Every name and
 * figure is invented.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
const WEB = path.join(__dirname, '..', '..', 'web');
const T = require(path.join(WEB, 'objective-touch.js'));
const N = require(path.join(WEB, 'objective-number.js'));
const OC = require(path.join(WEB, 'objective-cards.js'));
const HZ = require(path.join(WEB, 'horizon.js'));
const D = require(path.join(WEB, 'distances.js'));

shim.Element.prototype.getBoundingClientRect = function () { return this.rect || { left: 0, top: 0, width: 0, height: 0 }; };

const NOW = new Date(2026, 8, 29, 15, 0);   // Tue 29 September 2026, the design's own today
const HOSTILE = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
const NID = 'obj_7c8d9e0f';
// Hoodies sold a day, 1 Sep to today: 138 in all (the design's figures).
const SOLD = [4, 3, 5, 6, 10, 8, 3, 4, 3, 4, 6, 9, 7, 2, 3, 4, 3, 5, 8, 6, 3, 2, 3, 4, 5, 7, 7, 2, 2];

function handClock() {
  let t = 1000;
  let seq = 0;
  const due = [];
  return {
    now: () => t,
    later: (fn, ms) => { seq += 1; due.push({ id: seq, at: t + ms, fn }); return seq; },
    cancel: (id) => { const i = due.findIndex((x) => x.id === id); if (i >= 0) due.splice(i, 1); },
    advance(ms) {
      const end = t + ms;
      for (;;) {
        due.sort((a, b) => a.at - b.at || a.id - b.id);
        if (!due.length || due[0].at > end) break;
        const next = due.shift();
        t = next.at;
        next.fn();
      }
      t = end;
    },
  };
}
let C;
let felt;
test.beforeEach(() => {
  C = handClock();
  T.clock = C;
  felt = [];
  T.vibrate = (pattern) => felt.push(pattern);
});

const flush = async () => { for (let i = 0; i < 12; i += 1) await new Promise((r) => setImmediate(r)); };
// An SVG element's class is an attribute (a browser's SVG className cannot be assigned): both are read.
const classes = (el) => `${el.className || ''} ${(el.attributes && el.attributes.class) || ''}`.split(/\s+/).filter(Boolean);
const has = (el, cls) => Boolean(el && classes(el).includes(cls));
function all(node, cls) {
  const out = [];
  const walk = (el) => { for (const c of el.childNodes || []) { if (c.nodeType === 1) { if (has(c, cls)) out.push(c); walk(c); } } };
  if (node) walk(node);
  return out;
}
const one = (node, cls) => all(node, cls)[0] || null;
const words = (node) => (node ? node.allText() : '');
const clone = (x) => JSON.parse(JSON.stringify(x));
function pointer(el, type, x, y, id, extra) {
  el.dispatch(type, Object.assign({ pointerId: id || 7, clientX: x, clientY: y, button: 0, isPrimary: (id || 7) === 7, pointerType: 'touch', cancelable: true }, extra || {}));
}
function barOf(node) {
  const bar = one(node, 'ot-bar');
  return { text: words(one(bar, 'ot-bar-text')), kind: bar.dataset.kind, undo: !one(bar, 'ot-undo').hidden, shown: !bar.hidden };
}
// Every attribute in the tree, for "no attribute carries what the Mac sent".
function attributes(node, out = []) {
  if (node.attributes) for (const k of Object.keys(node.attributes)) out.push(`${k}=${node.attributes[k]}`);
  for (const c of node.childNodes || []) attributes(c, out);
  return out;
}

function hoodie(over) {
  return clone(Object.assign({
    objective_id: NID, kind: 'business', title: 'Loopback Hoodie', attention: 'idle', attention_reason: 'nothing open',
    deadline: '2026-10-18', days_left: 19, purpose: null, done_when: null, check_in: null, people: [], needs_you: [],
    blocked_by: [], doing: null, next: [],
    number: { of: 'Loopback Hoodie', target: 200, since: '2026-09-01', unit: 'hoodies' },
    count: { counted: true, per_day: SOLD, total: 138, pace: 4.43, pace_days: 14, today: '2026-09-29', lands: '2026-10-13',
      reached_on: null, far: false, days_early: 5, by_deadline: null, short: null, counted_at: '2026-09-29T13:58:00Z', age_s: 120 },
  }, over || {}));
}

// The Mac, as far as the target goes: it keeps the card and answers with it and an undo offer.
function mac(start) {
  const M = { card: clone(start), asked: [], before: null, n: 0 };
  M.send = async (url, body) => {
    M.asked.push([url, body]);
    const tail = url.slice(`/objectives/${NID}`.length);
    if (tail === '/undo') { M.card = M.before; return { card: clone(M.card), said: `Target ${M.card.number.target} again` }; }
    M.before = clone(M.card);
    M.card.number.target = body.target;
    M.n += 1;
    return { card: clone(M.card), undo: { token: `tok-${M.n}`, ttl_s: 6, says: `Target ${body.target}` }, said: null };
  };
  return M;
}
function drawn(card, opts) {
  const node = OC.card(card, Object.assign({ now: NOW, send: async () => ({}) }, opts || {}));
  const svg = one(node, 'on-svg');
  if (svg) svg.rect = { left: 0, top: 0, width: 540, height: 232 };   // a pixel to a unit of the chart
  return node;
}
const chartOf = (node) => one(node, 'on-chart');
const sayOf = (node) => words(one(node, 'on-pace'));

// ---------------------------------------------------------------- the words, as the Mac says them

test('the pace, worked out here exactly as the Mac does, in the same words', () => {
  const m = N.model(hoodie());
  assert.equal(m.total, 138);
  assert.ok(Math.abs(m.pace - 62 / 14) < 1e-12, 'the last 14 whole days, today not among them');
  assert.equal(N.paceLine(m, 200).text, 'At this pace: 200 by Tue 13 Oct, 5 days early');
  const short = N.paceLine(m, 250);
  assert.equal(short.text, 'At this pace: 222 by Sun 18 Oct, 28 short');
  assert.equal(short.late, true);
  assert.equal(N.paceLine(m, 100).text, '100 reached on Sun 20 Sep');
  assert.equal(N.paceLine(N.model(hoodie({ deadline: null })), 200).text, 'At this pace: 200 by Tue 13 Oct');
  const quiet = N.model(hoodie({ count: Object.assign(hoodie().count, { per_day: SOLD.map(() => 0) }) }));
  assert.equal(N.paceLine(quiet, 200).text, 'At this pace: 0 by Sun 18 Oct, 200 short', 'nothing sold: short by all of it, no day invented');
  assert.equal(N.paceLine(N.model(hoodie({ deadline: null, count: Object.assign(hoodie().count, { per_day: SOLD.map(() => 0) }) })), 200).text,
    'Nothing sold in the last 14 days, so no pace to go by');
  assert.equal(N.model(hoodie({ number: null })), null, 'no number, no shape');
  const first = N.model(hoodie({ number: { of: 'Loopback Hoodie', target: 200, since: '2026-09-29', unit: null },
    count: Object.assign(hoodie().count, { per_day: [2] }) }));
  assert.deepEqual([N.paceLine(first, 200).text, N.paceLine(first, 200).late], ['No whole day counted yet, so no pace to go by', false],
    'a first day is not called short');
});

// ---------------------------------------------------------------- the shape

test('138 of 200, the pace, and the chart: a dot for each ten, the matrix faint, the target a row of light', () => {
  const card = drawn(hoodie());
  const shape = one(card, 'on-number');
  assert.ok(shape, 'drawn on the card of a business objective');
  assert.equal(words(one(card, 'on-sold')), '138');
  assert.equal(words(one(card, 'on-of')), 'of 200 sold');
  assert.equal(sayOf(card), 'At this pace: 200 by Tue 13 Oct, 5 days early');
  assert.ok(!has(one(card, 'on-pace'), 'is-late'));
  assert.equal(words(one(card, 'oc-status')), '138 of 200 sold · Due 18 Oct · 19 days left');
  assert.equal(words(one(card, 'on-source')), 'From Shopify, counted 2 min ago. Each dot is ten hoodies.');
  const svg = one(card, 'on-svg');
  assert.equal(svg.getAttribute('aria-hidden'), 'true');
  assert.ok(one(svg, 'on-matrix') && svg.querySelector('pattern'), 'the matrix: one dot a place, faint');
  const today = all(svg, 'is-today');
  assert.equal(today.length, 14, '138 is thirteen dots of ten and a smaller one for the eight');
  assert.equal(today.filter((c) => has(c, 'is-part')).length, 1);
  assert.equal(all(svg, 'is-target').length, 1, 'the target, a row of light');
  assert.equal(all(svg, 'on-meet').length, 2, 'and where the pace meets it, ringed');
  assert.ok(all(svg, 'is-ahead').length > 0 && !all(svg, 'is-short').length, 'the days ahead at the pace, and nothing short');
  assert.deepEqual(all(card, 'on-label').map(words), ['1 Sep', 'Today', '18 Oct']);
  const handle = one(card, 'on-target');
  assert.equal(handle.tagName, 'BUTTON');
  assert.equal(handle.getAttribute('role'), 'slider');
  assert.equal(handle.getAttribute('aria-valuenow'), '200');
  assert.equal(handle.getAttribute('aria-valuetext'), 'Target 200. At this pace: 200 by Tue 13 Oct, 5 days early');
  assert.equal(words(one(card, 'on-pill')), 'Target 200');
  assert.ok(Number(handle.style.getPropertyValue('--y')) > 0 && Number(handle.style.getPropertyValue('--y')) < 100);
  assert.equal(one(card, 'oc-work'), null);
});

test('the design\'s homepage suggestion is not drawn: nothing here can act on the shop', () => {
  const card = drawn(hoodie());
  assert.ok(!/homepage|Hold to feature|Checked live|suggests/i.test(words(card)));
  assert.equal(all(card, 'hold').length + all(card, 'action-surface').length, 0);
});

// ---------------------------------------------------------------- total and per day

test('a double-tap on the chart is per day, a dot for each one sold, and says so without changing anything', () => {
  const sent = [];
  const card = drawn(hoodie(), { send: async (...a) => { sent.push(a); return {}; } });
  const chart = chartOf(card);
  chart.dispatch('click', { clientX: 300, detail: 1 });
  C.advance(100);
  chart.dispatch('click', { clientX: 300, detail: 1 });
  C.advance(1000);
  assert.ok(has(chart, 'is-day'));
  assert.equal(one(card, 'on-target').hidden, true, 'the target is the total\'s');
  const [totalB, dayB] = all(card, 'on-mode');
  assert.equal(dayB.getAttribute('aria-pressed'), 'true');
  assert.equal(totalB.getAttribute('aria-pressed'), 'false');
  assert.equal(all(one(card, 'on-svg'), 'is-today').length, 2, 'today: two sold, two dots');
  assert.equal(words(one(card, 'on-source')), 'From Shopify, counted 2 min ago. Each dot is one sold that day.');
  assert.equal(all(one(card, 'on-svg'), 'is-need').length, 1, 'what each day needs from here');
  assert.deepEqual(barOf(card), { text: 'Per day: 4.4 a day over the last 14 days. 3.3 a day gets you to 200 by Sun 18 Oct.', kind: 'info', undo: false, shown: true });
  assert.deepEqual(felt, [[8]], 'one short snap');
  totalB.dispatch('click');
  assert.ok(!has(chart, 'is-day'));
  assert.equal(barOf(card).text, 'In total: 138 of 200 sold.');
  assert.deepEqual(sent, [], 'a view is not a change: nothing is sent');
});

test('a tap says what that day holds, once it is clear no second tap is coming', () => {
  const card = drawn(hoodie());
  const chart = chartOf(card);
  const col = (540 - 78) / 50;
  chart.dispatch('click', { clientX: col * 14 + 2, detail: 1 });
  assert.equal(barOf(card).shown, false);
  C.advance(T.TAP_MS);
  assert.equal(barOf(card).text, 'Tue 15 Sep: 3 sold, 77 by then.');
  chart.dispatch('click', { clientX: col * 40 + 2, detail: 1 });
  C.advance(T.TAP_MS);
  assert.equal(barOf(card).text, 'Sun 11 Oct: about 191 by then, at 4.4 a day.');
});

// ---------------------------------------------------------------- more or fewer days

test('two fingers spread on the chart show fewer days, pinched more; a tick at each, and the bar says which', () => {
  const card = drawn(hoodie());
  const chart = chartOf(card);
  pointer(chart, 'pointerdown', 100, 100, 1);
  pointer(chart, 'pointerdown', 200, 100, 2);
  assert.ok(has(chart, 'is-pinching'), 'the chart has the fingers: the sheet does not close (web/distances.js `busy`)');
  pointer(chart, 'pointermove', 300, 100, 2);
  assert.deepEqual(all(card, 'on-label').map(words), ['23 Sep', 'Today', '18 Oct'], 'spread: the first days go');
  pointer(chart, 'pointerup', 300, 100, 2);
  pointer(chart, 'pointerup', 100, 100, 1);
  assert.ok(!has(chart, 'is-pinching'));
  assert.equal(barOf(card).text, 'From 23 Sep: the last 7 days, and the rest of the run.');
  assert.deepEqual(felt, [12, 6], 'lifted, a detent');
  chart.dispatch('click', { clientX: 10, detail: 1 });
  C.advance(T.TAP_MS);
  assert.equal(barOf(card).text, 'From 23 Sep: the last 7 days, and the rest of the run.', 'the lift that ends a pinch is not a tap');
  C.advance(1000);
  pointer(chart, 'pointerdown', 100, 100, 3);
  pointer(chart, 'pointerdown', 300, 100, 4);
  pointer(chart, 'pointermove', 200, 100, 4);
  pointer(chart, 'pointerup', 200, 100, 4);
  pointer(chart, 'pointerup', 100, 100, 3);
  assert.deepEqual(all(card, 'on-label').map(words), ['1 Sep', 'Today', '18 Oct']);
  assert.equal(barOf(card).text, 'Since 1 Sep: everything it has sold.');
});

test('the chart\'s fingers are its own: the three distances never pinch the sheet from it', () => {
  const at = (cls, parent) => node({ cls }, parent);
  const sheet = node({ tag: 'dialog', id: 'alpha-sheet' });
  const line = at(['alpha-line'], sheet);
  const chart = at(['on-chart'], at(['on-number'], sheet));
  const dot = node({ tag: 'svg', cls: ['on-svg'] }, chart);
  assert.equal(D.hitOf(dot).own, true);
  assert.equal(D.pairs(D.hitOf(dot), D.hitOf(line), false), false, 'one finger on the chart: not the sheet\'s pinch');
  assert.equal(D.pairs(D.hitOf(line), D.hitOf(line), false), true, 'elsewhere on the sheet it still is');
  assert.equal(D.emptyAt(dot), false, 'a double-tap on the chart is the chart\'s, not home');
  const css = fs.readFileSync(path.join(WEB, 'objective-cards.css'), 'utf8');
  assert.ok(/\.on-chart\{[^}]*touch-action:none/.test(css), 'the page never pans or zooms from the chart');
  const src = fs.readFileSync(path.join(WEB, 'distances.js'), 'utf8');
  assert.ok(src.includes('.on-chart.is-pinching') && src.includes('.on-target.is-moving'), 'and nothing pinches while the chart or the target has a finger');
});

// ---------------------------------------------------------------- the target

test('the target is dragged a dot at a time, red before the finger lets go; let go, it is sent, with Undo', async () => {
  const M = mac(hoodie());
  const card = drawn(hoodie(), { send: M.send });
  const handle = one(card, 'on-target');
  pointer(handle, 'pointerdown', 500, 100);
  pointer(handle, 'pointermove', 500, 85);
  assert.equal(handle.getAttribute('aria-valuenow'), '220', 'up two dots of ten');
  assert.equal(sayOf(card), 'At this pace: 220 by Sun 18 Oct, on the day');
  assert.equal(words(one(card, 'on-of')), 'of 220 sold');
  pointer(handle, 'pointermove', 500, 63);
  assert.equal(handle.getAttribute('aria-valuenow'), '250');
  assert.equal(sayOf(card), 'At this pace: 222 by Sun 18 Oct, 28 short');
  assert.ok(has(one(card, 'on-pace'), 'is-late') && has(handle, 'is-late'), 'red while the finger is still down');
  assert.ok(all(one(card, 'on-svg'), 'is-short').length > 0, 'and what would be short, red at the deadline');
  assert.deepEqual(felt, [12, 6, [8]], 'lifted, a detent, and a snap where it turns short');
  assert.deepEqual(M.asked, [], 'nothing is asked while the finger is down');
  pointer(handle, 'pointerup', 500, 63);
  await flush();
  assert.deepEqual(M.asked, [[`/objectives/${NID}/target`, { target: 250 }]]);
  assert.deepEqual(barOf(card), { text: 'Target 250', kind: 'did', undo: true, shown: true });
  assert.equal(one(card, 'on-target').getAttribute('aria-valuenow'), '250', 'drawn again from the answer');
  // A switch of view says its line and leaves the Undo alone.
  const chart = chartOf(card);
  chart.dispatch('click', { clientX: 300, detail: 1 });
  C.advance(100);
  chart.dispatch('click', { clientX: 300, detail: 1 });
  assert.equal(barOf(card).undo, true);
  await one(one(card, 'ot-bar'), 'ot-undo').dispatch('click');
  await flush();
  assert.deepEqual(M.asked[1], [`/objectives/${NID}/undo`, { token: 'tok-1' }]);
  assert.equal(barOf(card).text, 'Target 200 again');
  assert.equal(one(card, 'on-target').getAttribute('aria-valuenow'), '200');
});

test('a drag let go where it started, or lost, changes nothing', async () => {
  const M = mac(hoodie());
  const card = drawn(hoodie(), { send: M.send });
  const handle = one(card, 'on-target');
  pointer(handle, 'pointerdown', 500, 100);
  pointer(handle, 'pointermove', 500, 60);
  pointer(handle, 'pointermove', 500, 99);
  pointer(handle, 'pointerup', 500, 99);
  pointer(handle, 'pointerdown', 500, 100);
  pointer(handle, 'pointermove', 500, 40);
  pointer(handle, 'pointercancel', 500, 40);
  await flush();
  assert.deepEqual(M.asked, []);
  assert.equal(handle.getAttribute('aria-valuenow'), '200');
  assert.equal(sayOf(card), 'At this pace: 200 by Tue 13 Oct, 5 days early');
});

test('the target from the keyboard: a slider, Escape puts it back, Enter keeps it', async () => {
  const M = mac(hoodie());
  const card = drawn(hoodie(), { send: M.send });
  const handle = one(card, 'on-target');
  handle.dispatch('keydown', { key: 'ArrowUp' });
  assert.equal(handle.getAttribute('aria-valuenow'), '210');
  handle.dispatch('keydown', { key: 'Escape' });
  assert.equal(handle.getAttribute('aria-valuenow'), '200');
  handle.dispatch('keydown', { key: 'PageDown' });
  assert.equal(handle.getAttribute('aria-valuetext'), 'Target 150. At this pace: 150 by Fri 2 Oct, 16 days early');
  handle.dispatch('keydown', { key: 'Home' });
  assert.equal(handle.getAttribute('aria-valuenow'), '10', 'one dot, the least');
  handle.dispatch('keydown', { key: 'End' });
  assert.equal(handle.getAttribute('aria-valuenow'), handle.getAttribute('aria-valuemax'));
  handle.dispatch('keydown', { key: 'Escape' });
  handle.dispatch('keydown', { key: 'ArrowUp' });
  handle.dispatch('keydown', { key: 'ArrowUp' });
  assert.deepEqual(M.asked, []);
  handle.dispatch('keydown', { key: 'Enter' });
  await flush();
  assert.deepEqual(M.asked, [[`/objectives/${NID}/target`, { target: 220 }]]);
  // Total and Per day are two buttons, each a 44-pixel control.
  const css = fs.readFileSync(path.join(WEB, 'objective-cards.css'), 'utf8');
  assert.ok(/\.on-mode\{[^}]*min-height:44px/.test(css) && /\.on-target\{[^}]*height:44px/.test(css));
  assert.ok(/prefers-reduced-motion:reduce\)\{\.on-mode,\.on-pill\{transition:none\}/.test(css), 'with motion turned down nothing travels');
});

test('a refused target goes back and says so in the Mac\'s words', async () => {
  const card = drawn(hoodie(), { send: async () => { throw new Error('A target is between 1 and 100,000.'); } });
  const handle = one(card, 'on-target');
  handle.dispatch('keydown', { key: 'ArrowUp' });
  handle.dispatch('keydown', { key: 'Enter' });
  await flush();
  assert.equal(handle.getAttribute('aria-valuenow'), '200');
  assert.deepEqual(barOf(card), { text: 'Not saved: A target is between 1 and 100,000.', kind: 'error', undo: false, shown: true });
});

// ---------------------------------------------------------------- not counted

test('a count that could not be read draws no chart and says why, in the Mac\'s words', () => {
  const card = drawn(hoodie({ count: { counted: false, why: 'Shopify could not be read just now, so nothing is counted.' } }));
  assert.equal(one(card, 'on-svg'), null);
  assert.equal(one(card, 'on-sold'), null, 'no figure');
  assert.equal(words(one(card, 'on-what')), '200 Loopback Hoodie, counted from 1 Sep');
  assert.equal(words(one(card, 'on-source')), 'Shopify could not be read just now, so nothing is counted.');
  assert.ok(has(one(card, 'on-source'), 'is-unread'));
  assert.equal(words(one(card, 'oc-status')), 'Due 18 Oct · 19 days left', 'and no count in the line under the title');
});

test('the model\'s card comes without a count: it asks the owner\'s route once, and draws the answer', async () => {
  const asked = [];
  const bare = hoodie();
  delete bare.count;
  const card = drawn(bare, { get: async (url) => { asked.push(url); return { card: hoodie() }; } });
  assert.equal(words(one(card, 'on-source')), 'Counting from Shopify…');
  await flush();
  assert.deepEqual(asked, [`/objectives/${NID}`]);
  assert.equal(words(one(card, 'on-sold')), '138', 'drawn from the answer');
  const lost = drawn(bare, { get: async () => { throw new Error('CLIVE could not be reached'); } });
  await flush();
  assert.equal(words(one(lost, 'on-source')), 'It could not be counted: CLIVE could not be reached.');
  const shown = drawn(bare, { readOnly: true });
  assert.equal(words(one(shown, 'on-source')), 'Counted from Shopify where the objective is opened.');
});

// ---------------------------------------------------------------- the home and the next six weeks

function summary(over) {
  return Object.assign({
    id: NID, title: 'Loopback Hoodie', kind: 'business', attention: 'idle', deadline: '2026-10-18', stages: [], stage: null,
    people_tasks: [], needs_you: [], blocked_by: [], next: [],
    number: { of: 'Loopback Hoodie', target: 200, since: '2026-09-01', unit: 'hoodies', counted: true, sold: 138,
      lands: '2026-10-13', reached_on: null, far: false, late: false, days_early: 5, by_deadline: null, short: null },
  }, over || {});
}

test('the home row: a ring of twenty, each a twentieth of the target, lit for the share sold', () => {
  const dots = HZ.markDots(summary(), [], { lite: false });
  assert.equal(dots.length, 21, 'twenty and the one at its heart');
  assert.equal(dots.filter((d) => d.cls === 'is-lit').length, 14, '138 of 200 is fourteen twentieths');
  const late = HZ.markDots(summary({ number: Object.assign(summary().number, { late: true, short: 28, by_deadline: 222, target: 250 }) }), []);
  assert.ok(late.filter((d) => d.cls.includes('is-lit')).every((d) => d.cls.includes('is-late')), 'red when the pace falls short');
  assert.equal(HZ.markDots(summary({ number: { of: 'Loopback Hoodie', target: 200, counted: false, why: 'x' } }), []), null,
    'not counted: no ring, since nothing lit would be true');
  const row = OC.row(summary(), NOW);
  assert.deepEqual(row, { sub: 'On pace for 200 by Tue 13 Oct', track: null, meta: '138 of 200' });
  const mark = HZ.rowMark(summary({ number: Object.assign(summary().number, { late: true, short: 28, by_deadline: 222, target: 250 }) }), [], null, { now: NOW });
  assert.equal(mark.late, '222 by Sun 18 Oct, 28 short', 'lateness first on the row, as the design orders it');
  assert.ok(mark.glyph);
  assert.deepEqual(OC.row(summary({ number: { of: 'Loopback Hoodie', target: 200, counted: false, why: 'Shopify could not be read just now, so nothing is counted.' } }), NOW),
    { sub: 'Shopify could not be read just now, so nothing is counted.', track: null, meta: null });
});

test('the next six weeks: the deadline as it is, and the day the pace lands ringed, the days up to it blue', () => {
  const model = HZ.layout([summary()], { now: NOW });
  const r = model.rows[0];
  assert.equal(r.detail, 'Due Sun 18 Oct');
  assert.equal(r.line, 'Lands Tue 13 Oct');
  assert.equal(r.late, false);
  assert.equal(r.days[19].ring, 'hz-ring', 'the deadline, ringed as any deadline is');
  assert.equal(r.days[14].ring, 'hz-ring is-land', 'and the day the pace lands');
  assert.ok(r.days.slice(1, 14).every((d) => d.cls === 'hz-d is-pace'), 'the days up to it, a faint blue');
  assert.equal(r.days[15].cls, 'hz-d', 'and after it nothing is invented');
  const late = HZ.layout([summary({ number: Object.assign(summary().number, { target: 250, lands: '2026-10-25', late: true, short: 28, by_deadline: 222, days_early: -7 }) })], { now: NOW }).rows[0];
  assert.equal(late.late, true);
  assert.equal(late.line, '222 by Sun 18 Oct, 28 short');
  assert.equal(late.days[26].ring, 'hz-ring is-land is-late');
  assert.ok(late.days.slice(20, 26).every((d) => d.cls === 'hz-d is-late'), 'the days from the deadline to where it lands, red');
  assert.equal(HZ.layout([summary()], { now: NOW }).summary, 'Loopback Hoodie lands last, Sun 18 Oct.');
  const undated = HZ.layout([summary({ deadline: null })], { now: NOW }).rows[0];
  assert.equal(undated.detail, 'Lands Tue 13 Oct', 'no deadline: where the pace lands is its day');
});

// ---------------------------------------------------------------- words, never markup

test('every word from the Mac lands as text, and no attribute carries it', () => {
  const card = drawn(hoodie({ title: HOSTILE, number: { of: HOSTILE, target: 200, since: '2026-09-01', unit: HOSTILE } }));
  assert.ok(words(card).includes(HOSTILE), 'shown, as text');
  assert.equal(card.querySelectorAll('script, img').length, 0);
  assert.ok(attributes(card).every((a) => !a.includes('onerror') && !a.includes('<')), 'no attribute built from data');
  const unread = drawn(hoodie({ count: { counted: false, why: HOSTILE }, number: { of: HOSTILE, target: 200, since: '2026-09-01', unit: null } }));
  assert.ok(words(unread).includes(HOSTILE) && attributes(unread).every((a) => !a.includes('<')));
  const row = OC.row(summary({ number: { of: HOSTILE, target: 200, counted: false, why: HOSTILE } }), NOW);
  assert.equal(row.sub, HOSTILE);
  const src = fs.readFileSync(path.join(WEB, 'objective-number.js'), 'utf8');
  assert.ok(!/innerHTML|insertAdjacentHTML|outerHTML|document\.write|eval\(|fetch\(/.test(src));
  // It changes one thing, through the owner's own route for the objective: the target.
  assert.deepEqual([...new Set([...src.matchAll(/commit\([`']([^`'$]*)/g)].map((m) => m[1]))], ['/target']);
  // The card asks the objective's own record (a read) only for a count it came without.
  const cards = fs.readFileSync(path.join(WEB, 'objective-cards.js'), 'utf8');
  assert.equal([...cards.matchAll(/ctx\.get\(ctx\.url\(''\)\)/g)].length, 1);
});

test('the page loads the Number shape before the cards that draw with it, and the shell keeps it', () => {
  const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
  const at = (name) => html.indexOf(`/static/${name}`);
  assert.ok(at('objective-touch.js') < at('objective-number.js') && at('objective-number.js') < at('objective-cards.js'));
  assert.ok(fs.readFileSync(path.join(WEB, 'sw.js'), 'utf8').includes("'/static/objective-number.js'"));
});

/* A stand-in element with just enough of `closest` for the selectors distances.js asks about, as
   tests/web/horizon.test.js has it. */
function node(spec, parent) {
  const n = { tag: (spec.tag || 'div').toLowerCase(), id: spec.id || '', cls: spec.cls || [], attrs: spec.attrs || {}, parent: parent || null };
  const match = (el, sel) => {
    const m = /^([a-z][a-z0-9-]*)?((?:#[\w-]+|\.[\w-]+|\[[^\]]+\])*)$/i.exec(sel.trim());
    if (!m) return false;
    if (m[1] && m[1].toLowerCase() !== el.tag) return false;
    for (const part of m[2].match(/#[\w-]+|\.[\w-]+|\[[^\]]+\]/g) || []) {
      if (part[0] === '#' && el.id !== part.slice(1)) return false;
      if (part[0] === '.' && !el.cls.includes(part.slice(1))) return false;
      if (part[0] === '[') {
        const a = /^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(part);
        if (!a || !(a[1] in el.attrs) || (a[2] !== undefined && el.attrs[a[1]] !== a[2])) return false;
      }
    }
    return true;
  };
  n.closest = (selector) => {
    const list = selector.split(',').map((s) => s.trim());
    for (let el = n; el; el = el.parent) if (list.some((s) => match(el, s))) return el;
    return null;
  };
  return n;
}

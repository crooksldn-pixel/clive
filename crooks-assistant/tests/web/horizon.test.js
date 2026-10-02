/* The next six weeks and the three distances (objectives by touch, part B), run under Node.
 *
 * What is proved, with the page's own code (web/horizon.js, web/distances.js):
 * - the pinch's arithmetic: halving the distance between two fingers is one level down, doubling
 *   one up; a quarter of a level settles on the next, a level and a quarter two; past the last
 *   level the view only stretches; into an objective only over a row of one;
 * - whose fingers a pinch is: both on the home, the horizon or an objective's sheet (the same
 *   one), never one on the orb, the voice target, an action surface, a field, the ask bar, the
 *   Displays tray or a handle the objective's own touch layer drags, and never while something is
 *   held; and web/touch.js's machine never pairs those fingers, so the orb's division is untouched;
 * - the horizon from fixtures: 42 days from today, the deadline ringed, each stage's date marked,
 *   the days a late stage overruns the deadline red, a deadline already gone red from today, a build
 *   drawing no days but what it waits on, an objective with no date saying so, late rows first;
 * - each objective's mark in dots, every dot a stage or a task, fewer on the Tab A;
 * - every word from the Mac lands as text, even a hostile one, and no attribute carries it.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const shim = require('./dom-shim.js');

const WEB = path.join(__dirname, '..', '..', 'web');
globalThis.document = shim.document;
const HZ = require(path.join(WEB, 'horizon.js'));
const D = require(path.join(WEB, 'distances.js'));
const TOUCH = require(path.join(WEB, 'touch.js'));

// Tuesday 29 September 2026, the design's own today, at mid-afternoon.
const NOW = new Date(2026, 8, 29, 15, 0);
const near = (a, b) => Math.abs(a - b) < 1e-9;

// ---------------------------------------------------------------- the pinch's arithmetic

test('halving the distance between two fingers is one level down, doubling it one up', () => {
  assert.ok(near(D.levelOf(1, 0.5), 0), 'pinched to half on the home: the next six weeks');
  assert.ok(near(D.levelOf(0, 2), 1), 'spread to double on the horizon: home');
  assert.ok(near(D.levelOf(1, 2), 2), 'spread to double over a row: the objective');
  assert.ok(near(D.levelOf(2, 0.5), 1), 'pinched to half on a sheet: home');
  assert.ok(near(D.levelOf(2, 0.25), 0), 'to a quarter: two levels');
  assert.ok(near(D.levelOf(1, 1), 1), 'no change, no move');
  assert.ok(Number.isFinite(D.levelOf(1, 0)) && Number.isFinite(D.levelOf(1, NaN)), 'a nonsense scale never breaks the view');
});

test('a quarter of a level settles on the next, a level and a quarter two, and never past the reach', () => {
  assert.equal(D.settle(1, 0.8, 0, 1), 1, 'a fifth of a level goes back');
  assert.equal(D.settle(1, 0.75, 0, 1), 0, 'a quarter of a level goes on');
  assert.equal(D.settle(1, 1.25, 0, 2), 2, 'spread a quarter over a row: in');
  assert.equal(D.settle(1, 1.25, 0, 1), 1, 'not over a row: nowhere to go in to');
  assert.equal(D.settle(2, 0.7, 0, 2), 0, 'a sheet pinched a level and a quarter: past home to the horizon');
  assert.equal(D.settle(2, 1.6, 0, 2), 1, 'a sheet pinched almost half a level: home');
  assert.equal(D.settle(0, -0.25, 0, 1), 0, 'the horizon is as far out as it goes');
  assert.equal(D.settle(0.6, 0.4, 0, 1), 1, 'caught mid-settle, it settles from the level it was nearest');
});

test('past the last level the view stretches a little and no further', () => {
  assert.equal(D.rubber(0.5, 0, 1), 0.5);
  assert.ok(near(D.rubber(1.4, 0, 1), 1.1), 'a quarter as much');
  assert.ok(near(D.rubber(9, 0, 1), 1.25), 'never more than a quarter level');
  assert.ok(near(D.rubber(-9, 0, 1), -0.25));
});

test('into an objective only over a row of one; a sheet reaches back to the horizon', () => {
  assert.deepEqual(D.reach('home', false), { min: 0, max: 1 });
  assert.deepEqual(D.reach('home', true), { min: 0, max: 2 });
  assert.deepEqual(D.reach('horizon', false), { min: 0, max: 1 });
  assert.deepEqual(D.reach('horizon', true), { min: 0, max: 2 });
  assert.deepEqual(D.reach('sheet', false), { min: 0, max: 2 });
  assert.deepEqual(D.reach(null, false), { min: 1, max: 1 }, 'anywhere else, nowhere');
});

test('a tick at each level the fingers cross, and none between', () => {
  assert.equal(D.crossed(1, 0.6, 0, 1), false);
  assert.equal(D.crossed(1, 0.4, 0, 1), true, 'past half way to the horizon');
  assert.equal(D.crossed(0.4, 0.2, 0, 1), false);
  assert.equal(D.crossed(1.2, 1.6, 0, 2), true, 'past half way into the objective');
  assert.equal(D.crossed(1, 1.4, 0, 1), false, 'a stretch past the last level is not a level');
});

test('each level is 1.8 times the next and fades as it goes, as the design draws it', () => {
  assert.deepEqual(D.layer(1, 1), { scale: 1, opacity: 1 });
  const out = D.layer(0, 1);
  assert.ok(near(out.scale, 1 / 1.8) && out.opacity === 0, 'the home from the horizon: small and gone');
  const half = D.layer(0.5, 0);
  assert.ok(near(half.scale, Math.sqrt(1.8)) && near(half.opacity, 1 - 0.5 * 1.45));
});

// ---------------------------------------------------------------- whose fingers

/* A stand-in element with just enough of `closest` for the selectors distances.js asks about:
   tag, #id, .class and [attr] or [attr="value"], in compound, in comma lists. */
function node(spec, parent) {
  const n = { tag: (spec.tag || 'div').toLowerCase(), id: spec.id || '', cls: spec.cls || [], attrs: spec.attrs || {}, parent: parent || null };
  const one = (el, sel) => {
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
    for (let el = n; el; el = el.parent) if (list.some((s) => one(el, s))) return el;
    return null;
  };
  return n;
}
const app = node({ id: 'app' });
const home = node({ id: 'alpha-home', cls: ['alpha-home'] }, app);
const homeRow = node({ tag: 'button', cls: ['alpha-row'], attrs: { 'data-alpha': 'objective', 'data-objective': 'obj_0000000a' } }, home);
const homeTitle = node({ tag: 'span', cls: ['alpha-row-title'] }, homeRow);
const homeGround = node({ tag: 'p', cls: ['alpha-summary'] }, node({ cls: ['alpha-hello'] }, home));
const horizon = node({ tag: 'section', id: 'alpha-horizon' }, app);
const horizonHead = node({ tag: 'h1', cls: ['hz-h1'] }, node({ cls: ['hz-head'] }, horizon));
const horizonRow = node({ tag: 'button', cls: ['hz-row'], attrs: { 'data-hz': 'row', 'data-objective': 'obj_0000000a' } }, horizon);
const sheet = node({ tag: 'dialog', id: 'alpha-sheet' });
const sheetScroll = node({ cls: ['sheet-scroll'] }, sheet);
const sheetLine = node({ tag: 'p', cls: ['alpha-line'] }, sheetScroll);
const stage = node({ tag: 'li', cls: ['oc-step'] }, node({ tag: 'ol', cls: ['oc-steps'] }, sheetScroll));
const ring = node({ tag: 'button', cls: ['ot-ring'] }, sheetScroll);
const grip = node({ tag: 'button', cls: ['ot-grip'] }, sheetScroll);
const sheetField = node({ tag: 'input', cls: ['alpha-field'] }, node({ tag: 'form' }, sheetScroll));
const orb = node({ tag: 'canvas', id: 'orb' }, node({ id: 'orb-frame' }, node({ tag: 'section', id: 'orb-zone' }, app)));
const talk = node({ tag: 'button', id: 'talk' }, app);
const askBar = node({ tag: 'span', cls: ['ask-text'] }, node({ tag: 'button', id: 'ask-bar', cls: ['ask-bar'] }, node({ tag: 'form', cls: ['alpha-composer'] }, app)));
const surface = node({ cls: ['action-handle'] }, node({ cls: ['action-surface'] }, node({ id: 'cards' }, app)));
const tray = node({ tag: 'button', cls: ['lift-tile'] }, node({ cls: ['lift-tray'] }));

test('a finger is read by what it came down on, and only the three views are zones', () => {
  assert.deepEqual(D.hitOf(homeTitle), { zone: 'home', voice: false, approval: false, field: false, own: false });
  assert.equal(D.hitOf(horizonRow).zone, 'horizon');
  assert.equal(D.hitOf(sheetLine).zone, 'sheet');
  assert.deepEqual(D.hitOf(orb), { zone: null, voice: true, approval: false, field: false, own: false });
  assert.equal(D.hitOf(talk).voice, true);
  assert.equal(D.hitOf(surface).approval, true);
  assert.equal(D.hitOf(sheetField).field, true);
  assert.equal(D.hitOf(askBar).own, true, 'the bar: a hold there is the microphone');
  assert.equal(D.hitOf(tray).own, true, 'the Displays tray');
  assert.equal(D.hitOf(ring).own && D.hitOf(grip).own, true, 'the objective\'s own drags');
  assert.equal(D.hitOf(null).zone, null);
});

test('two fingers are this pinch only on the same view, and never on the orb or anything given to someone else', () => {
  const h = (n) => D.hitOf(n);
  assert.equal(D.pairs(h(homeRow), h(homeGround), false), true, 'two on the home, one on a row');
  assert.equal(D.pairs(h(horizonRow), h(horizonHead), false), true, 'two on the horizon');
  assert.equal(D.pairs(h(sheetLine), h(stage), false), true, 'two on an objective\'s sheet, one on a stage');
  assert.equal(D.pairs(h(orb), h(orb), false), false, 'two on the orb divide or merge it: not ours');
  assert.equal(D.pairs(h(orb), h(homeRow), false), false, 'one on the orb');
  assert.equal(D.pairs(h(talk), h(homeRow), false), false, 'one on the voice target');
  assert.equal(D.pairs(h(homeRow), h(surface), false), false, 'one on an action surface');
  assert.equal(D.pairs(h(sheetField), h(sheetLine), false), false, 'one in a field');
  assert.equal(D.pairs(h(askBar), h(homeRow), false), false, 'one on the bar');
  assert.equal(D.pairs(h(ring), h(sheetLine), false), false, 'one on the date ring');
  assert.equal(D.pairs(h(grip), h(sheetLine), false), false, 'one on "now"');
  assert.equal(D.pairs(h(homeRow), h(horizonRow), false), false, 'two different views');
  assert.equal(D.pairs(h(homeRow), h(homeGround), true), false, 'something is held (a lift, a drag)');
});

test('the touch machine never makes a pair of the home\'s fingers, so the orb is never divided by this pinch', () => {
  const machine = TOUCH.create({});
  const asPage = (n, id) => ({ pointerId: id, x: 10 * id, y: 300, voice: Boolean(n.closest('#talk, #orb-frame')),
    control: n.closest('button, [role="button"]') ? 'button' : '', approval: n.closest('.action-surface,.action-handle') ? 'x' : '', scroll: false });
  const a = machine.down(asPage(homeRow, 1));
  const b = machine.down(asPage(homeGround, 2));
  assert.equal(a.owner, TOUCH.OWNER.CONTROL);
  assert.equal(b.owner, TOUCH.OWNER.NONE);
  assert.equal(machine.pairing(), false, 'no split gesture');
  assert.equal(machine.move({ pointerId: 2, x: 400, y: 300 }), null, 'a spread here is never a divide');
  assert.equal(machine.up({ pointerId: 1 }).submit, false);
  assert.equal(machine.up({ pointerId: 2 }).submit, false);
});

test('a double-tap goes home only from empty space on the horizon or a sheet', () => {
  assert.equal(D.emptyAt(horizonHead), true, 'the horizon\'s heading');
  assert.equal(D.emptyAt(sheetLine), true, 'a line of the sheet');
  assert.equal(D.emptyAt(horizonRow), false, 'a row: a tap opens it');
  assert.equal(D.emptyAt(stage), false, 'a stage: a double-tap makes it now');
  assert.equal(D.emptyAt(ring), false);
  assert.equal(D.emptyAt(sheetField), false);
  assert.equal(D.emptyAt(homeGround), false, 'on the home it is home already');
  assert.equal(D.emptyAt(orb), false);
});

// ---------------------------------------------------------------- the horizon, from fixtures

const AW = {
  id: 'obj_000000a1', title: 'AW drop', kind: 'project', attention: 'doing', deadline: '2026-11-06', days_left: 38,
  needs_you: [], blocked_by: [], engineering: [],
  stage: { name: 'Sampling', index: 0, count: 4, waiting_on: 'Northfield', due: '2026-10-02' },
  stages: [
    { name: 'Sampling', state: 'current', due: '2026-10-02' },
    { name: 'Approval', state: 'upcoming', due: '2026-10-07' },
    { name: 'Production', state: 'upcoming', due: '2026-10-30' },
    { name: 'Delivery', state: 'upcoming', due: '2026-11-08' },
  ],
};
const HOODIE = { id: 'obj_000000a2', title: 'Loopback Hoodie', kind: 'business', attention: 'needs_you', deadline: '2026-10-18',
  needs_you: ['Feature it on the homepage?'], blocked_by: [], engineering: [], stages: [] };
const TASKS = { id: 'obj_000000a3', title: 'Rosa and Kit’s tasks', kind: 'tasks', attention: 'doing', deadline: null,
  needs_you: [], blocked_by: [], engineering: [], stages: [],
  people_tasks: [{ who: 'Rosa', open: 1, done: 1 }, { who: 'Kit', open: 2, done: 0 }, { who: 'CLIVE', open: 1, done: 0 }] };
const BUILD = { id: 'obj_000000a4', title: 'Tracking links on order cards', kind: 'build', attention: 'doing', deadline: '2026-10-09',
  needs_you: [], blocked_by: [], stages: [], engineering: [{ request_id: 'eng_1', host: 'w1' }] };
const GONE = { id: 'obj_000000a5', title: 'Studio lease', kind: 'business', attention: 'blocked', deadline: '2026-09-20',
  needs_you: [], blocked_by: ['the landlord'], engineering: [], stages: [] };
const DONE = { id: 'obj_000000a6', title: 'Old drop', kind: 'project', attention: 'done', deadline: '2026-09-01', stages: [] };
const DROPPED = { id: 'obj_000000a7', title: 'Dropped idea', kind: 'business', attention: 'dropped', deadline: '2026-10-01', stages: [] };
const BUILDS = { [BUILD.id]: [{ request_id: 'eng_1', progress: 'in review', words: 'Being reviewed' }] };

function model(list, extra) {
  return HZ.layout(list, Object.assign({ now: NOW, needs: [HOODIE.id], builds: BUILDS }, extra || {}));
}
const rowOf = (m, id) => m.rows.find((r) => r.id === id);

test('the next six weeks: 42 days from today, headed with their dates in words', () => {
  const m = model([AW]);
  assert.equal(m.range, 'Tue 29 Sep to Mon 9 Nov', 'the design\'s own heading for that day');
  assert.equal(rowOf(m, AW.id).days.length, 42);
  assert.deepEqual(m.weeks.map((w) => w.text), ['5 Oct', '12', '19', '26', '2 Nov', '9'], 'each Monday, a new month named');
  assert.equal(m.weeks[0].d, 6);
  const xs = rowOf(m, AW.id).days.map((d) => d.x);
  assert.ok(xs[0] > 0 && xs[41] < 100 && xs.every((x, i) => i === 0 || x > xs[i - 1]), 'left to right, inside the row');
});

test('a project: today first, its deadline ringed, each stage on its day, and the stage after the deadline red with its overrun', () => {
  const r = rowOf(model([AW]), AW.id);
  const day = (n) => r.days[n];
  assert.equal(day(0).ring, 'hz-today is-late', 'today first, ringed, and red: this one will land late');
  assert.equal(day(38).ring, 'hz-ring is-late', 'the deadline, Fri 6 Nov, ringed');
  assert.equal(day(3).cls, 'hz-m is-now', 'Sampling, the stage it is at, on Fri 2 Oct');
  assert.equal(day(8).cls, 'hz-m is-next', 'Approval on Wed 7 Oct');
  assert.equal(day(31).cls, 'hz-m is-next', 'Production on Fri 30 Oct, before the deadline: not late');
  assert.equal(day(40).cls, 'hz-m is-late', 'Delivery on Sun 8 Nov, after it: red');
  assert.equal(day(39).cls, 'hz-d is-late', 'the day it overruns by, red');
  assert.equal(day(41).cls, 'hz-d is-beyond', 'past the last thing due, quiet');
  assert.equal(day(5).cls, 'hz-d', 'an ordinary day');
  assert.equal(day(6).cls, 'hz-d is-monday', 'a Monday, a little larger');
  assert.equal(r.days.filter((d) => /is-late/.test(d.cls)).length, 2, 'nothing else is red');
  assert.equal(r.late, true);
  assert.equal(r.line, 'Delivery would land after Fri 6 Nov', 'and it says so, in words');
  assert.equal(r.detail, 'Due Fri 6 Nov');
});

test('days past a deadline with nothing due on them are quiet, not red', () => {
  const r = rowOf(model([HOODIE]), HOODIE.id);
  assert.equal(r.late, false);
  assert.equal(r.days[19].ring, 'hz-ring', 'Sun 18 Oct ringed');
  assert.equal(r.days[0].ring, 'hz-today');
  assert.ok(r.days.slice(20).every((d) => d.cls === 'hz-d is-beyond'), 'after it: quiet');
  assert.ok(r.days.every((d) => !/is-late/.test(d.cls) && !/is-late/.test(d.ring || '')));
  assert.equal(r.line, null, 'the dots say it; no words needed');
});

test('a deadline already gone: late from today, said in words', () => {
  const r = rowOf(model([GONE]), GONE.id);
  assert.equal(r.late, true);
  assert.equal(r.line, 'Was due Sun 20 Sep');
  assert.equal(r.days[0].ring, 'hz-today is-late');
  assert.ok(r.days.slice(1).every((d) => d.cls !== 'hz-d is-late'), 'no days are invented for when it will land');
});

test('a build draws no days, only what it waits on; an objective with no date says so', () => {
  const m = model([BUILD, TASKS]);
  const b = rowOf(m, BUILD.id);
  assert.deepEqual(b.days, [], 'a change to CLIVE has no date, even with one on it');
  assert.equal(b.line, 'Waiting on the review');
  assert.equal(b.detail, 'No date');
  const t = rowOf(m, TASKS.id);
  assert.deepEqual(t.days, []);
  assert.equal(t.detail, 'No date');
  assert.equal(t.line, null, 'nothing it waits on is recorded, so nothing is said');
  const waiting = rowOf(model([{ ...TASKS, blocked_by: ['the printer'] }]), TASKS.id);
  assert.equal(waiting.line, 'Waiting on the printer');
  const filed = rowOf(HZ.layout([BUILD], { now: NOW }), BUILD.id);
  assert.equal(filed.line, 'Waiting for a builder', 'filed, and the loop has said nothing more');
  const none = rowOf(HZ.layout([{ ...BUILD, engineering: [] }], { now: NOW }), BUILD.id);
  assert.equal(none.line, 'Not filed with the builders yet');
});

test('late first, then by date, then builds, then what has no date; nothing done or dropped', () => {
  const m = model([TASKS, BUILD, HOODIE, DONE, AW, DROPPED, GONE]);
  assert.deepEqual(m.rows.map((r) => r.title), ['Studio lease', 'AW drop', 'Loopback Hoodie', 'Tracking links on order cards', 'Rosa and Kit’s tasks']);
  assert.equal(m.summary, 'One thing needs you. Two are heading late.');
});

test('the line under the heading says what is so, and nothing when there is nothing', () => {
  assert.equal(HZ.layout([HOODIE, { ...AW, stages: AW.stages.slice(0, 3) }], { now: NOW }).summary, 'AW drop lands last, Fri 6 Nov.');
  assert.equal(HZ.layout([TASKS], { now: NOW }).summary, 'Nothing is due in the next six weeks.');
  assert.equal(HZ.layout([], { now: NOW }).summary, 'Nothing ongoing.');
  assert.deepEqual(HZ.layout([], { now: NOW }).rows, [], 'no placeholder rows');
});

// ---------------------------------------------------------------- the mark, in dots

test('a project\'s mark is a road of clusters, one a stage, lit as far as it has come', () => {
  const dots = HZ.markDots(AW, [], { lite: false });
  assert.equal(dots.length, 3 + 4 * 7, 'three steps of road, four clusters of seven');
  assert.equal(dots.filter((d) => d.cls === 'is-now').length, 7, 'the stage it is at, whole, breathing');
  assert.equal(dots.filter((d) => d.cls === 'is-lit').length, 0, 'nothing done yet');
  const moved = HZ.markDots({ ...AW, stages: AW.stages.map((s, i) => ({ ...s, state: i < 2 ? 'done' : i === 2 ? 'current' : 'upcoming' })) }, [], { lite: false });
  assert.equal(moved.filter((d) => d.cls === 'is-lit').length, 2 + 2 * 7, 'two stages and the road between done');
  const tab = HZ.markDots(AW, [], { lite: true });
  assert.equal(tab.length, 4, 'the Tab A: one dot a stage, no road');
  assert.equal(HZ.markDots({ ...AW, stages: [] }, []), null, 'no stages: no mark, the row keeps its own');
});

test('tasks are a ring a person with a dot inside for each task, lit when done, CLIVE\'s ring blue', () => {
  const dots = HZ.markDots(TASKS, [], { lite: false });
  const tasks = dots.filter((d) => !/is-ring/.test(d.cls));
  assert.equal(tasks.length, 2 + 2 + 1, 'a dot a task');
  assert.equal(tasks.filter((d) => d.cls === 'is-lit').length, 1, 'Rosa\'s one done');
  assert.equal(dots.filter((d) => d.cls === 'is-ring is-clive').length, 9, 'CLIVE\'s ring');
  assert.equal(dots.filter((d) => d.cls === 'is-ring').length, 18, 'Rosa\'s and Kit\'s');
  assert.ok(dots.every((d) => d.x > 0 && d.x < 40 && d.y > 0 && d.y < 40), 'inside its box');
});

test('a build is the road in steel, Filed to Live, from what the build loop says; unknown, no road', () => {
  const review = HZ.markDots(BUILD, BUILDS[BUILD.id], { lite: true });
  assert.deepEqual(review.map((d) => d.cls), ['is-lit is-steel', 'is-lit is-steel', 'is-now is-steel', 'is-dim is-steel']);
  assert.equal(HZ.buildAt(BUILD, [{ progress: 'done' }]), 3, 'built and reviewed: Live is next, after his merge');
  assert.equal(HZ.buildAt(BUILD, []), 0, 'filed');
  assert.equal(HZ.buildAt(BUILD, [{ progress: 'blocked' }]), null, 'blocked says nothing of which stage');
  assert.equal(HZ.buildAt({ ...BUILD, engineering: [] }, []), null, 'nothing filed');
  assert.equal(HZ.markDots(HOODIE, []), null, 'an objective with no shape keeps its row\'s own tile');
});

test('a home row: the mark, its stage track as dots red from the late stage, and lateness first', () => {
  const OC = require(path.join(WEB, 'objective-cards.js'));
  const shaped = OC.row(AW);
  const mark = HZ.rowMark(AW, [], shaped.track, { now: NOW, lite: false });
  assert.equal(mark.late, 'Delivery would land after Fri 6 Nov');
  assert.equal(mark.glyph.tagName, 'SVG');
  assert.equal(mark.glyph.querySelectorAll('circle').length, 31);
  const segs = shaped.track.childNodes;
  assert.deepEqual(segs.map((s) => s.className), ['oc-seg is-current', 'oc-seg is-upcoming', 'oc-seg is-upcoming', 'oc-seg is-upcoming'],
    'the track keeps its segments and their classes');
  assert.deepEqual(segs.map((s) => s.getAttribute('data-late')), [null, null, null, 'true'], 'red from Delivery');
  assert.ok(segs.every((s) => s.querySelectorAll('circle').length === 8), 'a run of dots a stage');
  assert.equal(mark.under, null);
  // A deadline already gone is said by the home's own "past the date", first; the stage's words stay.
  const gone = HZ.rowMark({ ...AW, deadline: '2026-09-25' }, [], OC.row(AW).track, { now: NOW });
  assert.equal(gone.late, null);
  const build = HZ.rowMark(BUILD, BUILDS[BUILD.id], null, { now: NOW, lite: false });
  assert.equal(build.under.className, 'hz-track is-steel');
  assert.deepEqual(build.under.childNodes.map((s) => s.className), ['hz-seg is-done', 'hz-seg is-done', 'hz-seg is-current', 'hz-seg is-upcoming']);
  assert.equal(HZ.rowMark(HOODIE, [], null, { now: NOW }).glyph, null);
});

// ---------------------------------------------------------------- drawn: text only

test('the horizon is drawn with text only: a hostile title stays words, and no attribute carries it', () => {
  const evil = '<img src=x onerror=alert(1)>"\' & </button>';
  const list = [AW, { ...HOODIE, id: 'obj_000000b9', title: evil }, { ...TASKS, id: '"><script>x</script>', title: `${evil} 2` }, BUILD];
  const m = model(list);
  const host = shim.document.createElement('section');
  const opened = [];
  let home = 0;
  HZ.draw(host, m, { open: (id) => opened.push(id), home: () => { home += 1; } });
  const text = host.allText();
  assert.ok(text.includes(evil), 'the title as it was written');
  assert.equal(host.querySelectorAll('img').length + host.querySelectorAll('script').length, 0);
  const all = [];
  const walk = (el) => { for (const c of el.children) { all.push(c); walk(c); } };
  walk(host);
  for (const el of all) {
    for (const [k, v] of Object.entries(el.attributes)) {
      assert.ok(!/[<>"']|script|onerror/.test(v), `${el.tagName} ${k}="${v}" carries nothing from the Mac`);
    }
  }
  const rows = host.querySelectorAll('.hz-row');
  assert.equal(rows.length, 4, 'one row an objective, no more');
  assert.deepEqual(rows.map((r) => r.getAttribute('data-objective')),
    [AW.id, 'obj_000000b9', BUILD.id, null], 'an id goes on a row only in an objective id\'s own shape');
  assert.ok(text.includes('Next six weeks') && text.includes('Tue 29 Sep to Mon 9 Nov') && text.includes('Home'));
  rows[1].dispatch('click');
  host.querySelector('[data-hz="home"]').dispatch('click');
  assert.deepEqual(opened, ['obj_000000b9']);
  assert.equal(home, 1);
  // The days, as circles placed by number: each day of the 42, and the rings. (An SVG node's
  // class is an attribute, which this stand-in does not reflect into className.)
  const byClass = (el, cls) => { for (const c of el.children) { if (c.getAttribute('class') === cls) return c; const deep = byClass(c, cls); if (deep) return deep; } return null; };
  const strip = byClass(rows[0], 'hz-days');
  const circles = strip.querySelectorAll('circle');
  assert.equal(circles.filter((c) => /^hz-[dm]/.test(c.getAttribute('class'))).length, 42);
  assert.ok(circles.every((c) => /^\d+(\.\d+)?%$/.test(c.getAttribute('cx'))), 'placed in per cent, so any width keeps them round');
  assert.equal(byClass(rows[2], 'hz-days'), null, 'the build: no days');
});

test('the page loads the horizon and the distances before the home that draws with them, and the shell keeps them', () => {
  const index = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
  const at = (s) => index.indexOf(s);
  assert.ok(at('<link rel="stylesheet" href="/static/horizon.css">') > 0);
  assert.ok(at('<script src="/static/horizon.js"></script>') > 0 && at('<script src="/static/horizon.js"></script>') < at('<script src="/static/alpha.js"></script>'));
  assert.ok(at('<script src="/static/distances.js"></script>') > 0 && at('<script src="/static/distances.js"></script>') < at('<script src="/static/alpha.js"></script>'));
  const sw = fs.readFileSync(path.join(WEB, 'sw.js'), 'utf8');
  for (const f of ['horizon.js', 'horizon.css', 'distances.js']) assert.ok(sw.includes(`'/static/${f}',`), f);
  const css = fs.readFileSync(path.join(WEB, 'horizon.css'), 'utf8');
  assert.ok(/\.alpha-home,\.alpha-horizon,#alpha-sheet\{touch-action:pan-y\}/.test(css), 'one finger scrolls; two are the pinch\'s');
  assert.ok(/prefers-reduced-motion:reduce/.test(css));
  const alpha = fs.readFileSync(path.join(WEB, 'alpha.js'), 'utf8');
  assert.ok(alpha.includes('window.CliveHome = {'), 'the home says what the distances may read and do');
});

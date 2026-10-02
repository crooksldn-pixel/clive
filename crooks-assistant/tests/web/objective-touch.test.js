/* Objectives by touch, part A (web/objective-touch.js with web/objective-cards.js), under Node.
 *
 * The design's gestures on the objective itself: a tap tells, a double-tap does the obvious next
 * thing, a drag puts a thing where it belongs, and every change says what it did in the bar with
 * Undo for six seconds. What is held, with the page's own code on a DOM stand-in and a clock moved
 * by hand: a tap and a double-tap told apart, a tap waiting only where a double-tap means something
 * else; a double-tap on a task's tick ticks once; "now" dragged snaps stage to stage and lands where
 * it is let go; the date it must land by dragged a day at a time, the stages that would land late
 * turning red before the finger lets go; a task pressed, dragged onto another person and settled
 * into their list; the bar's six seconds, an info line leaving an Undo alone, and Undo itself; and
 * every word from the record as text. The stand-in has no layout, so each test says where on the
 * glass the things it touches are. Every name is invented.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
const WEB = path.join(__dirname, '..', '..', 'web');
const T = require(path.join(WEB, 'objective-touch.js'));
const OC = require(path.join(WEB, 'objective-cards.js'));

// Where a thing is on the glass: what a test put in `rect`, or nowhere.
shim.Element.prototype.getBoundingClientRect = function () { return this.rect || { left: 0, top: 0, width: 0, height: 0 }; };

const NOW = new Date(2026, 8, 29, 10, 0);   // Tue 29 September 2026, the tablet's own clock
const HOSTILE = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
const PID = 'obj_1a2b3c4d';
const TID = 'obj_5e6f7a8b';

// ---------------------------------------------------------------- the clock, moved by hand

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
const one = (node, cls) => node.querySelector(`.${cls}`);
const all = (node, cls) => node.querySelectorAll(`.${cls}`);
const words = (node) => (node ? node.allText() : '');
const clone = (x) => JSON.parse(JSON.stringify(x));
function pointer(el, type, x, y, extra) {
  el.dispatch(type, Object.assign({ pointerId: 7, clientX: x, clientY: y, button: 0, isPrimary: true, pointerType: 'touch', cancelable: true }, extra || {}));
}
function barOf(node) {
  const bar = one(node, 'ot-bar');
  return { text: words(one(bar, 'ot-bar-text')), kind: bar.dataset.kind, undo: !one(bar, 'ot-undo').hidden, shown: !bar.hidden };
}

// ---------------------------------------------------------------- the objectives, and a stand-in Mac

function project(over) {
  return clone(Object.assign({
    objective_id: PID, kind: 'project', title: 'AW drop', attention: 'doing', attention_reason: 'at Sampling',
    deadline: '2026-10-20', days_left: 21, purpose: null, done_when: null, check_in: null, people: [], needs_you: [],
    blocked_by: [], doing: 'Sampling · waiting on Northfield', next: [],
    stages: [
      { id: 's_00000001', name: 'Sampling', state: 'current', due: '2026-10-02', waiting_on: 'Northfield', started_at: '2026-09-28T09:00:00Z', done_at: null },
      { id: 's_00000002', name: 'Approval', state: 'upcoming', due: '2026-10-09', waiting_on: 'you', started_at: null, done_at: null },
      { id: 's_00000003', name: 'Production', state: 'upcoming', due: '2026-10-16', waiting_on: null, started_at: null, done_at: null },
      { id: 's_00000004', name: 'Delivery', state: 'upcoming', due: null, waiting_on: null, started_at: null, done_at: null },
    ],
  }, over || {}));
}

function tasks() {
  return clone({
    objective_id: TID, kind: 'tasks', title: "Rosa and Kit's tasks", attention: 'doing', attention_reason: '3 tasks open',
    deadline: null, days_left: null, check_in: null, people: [], needs_you: [], blocked_by: [], doing: null, next: [],
    groups: [
      { who: 'Rosa', open: 2, done: 0, more: 0, tasks: [
        { id: 't_00000001', text: 'Steam the AW samples', due: null, done: false },
        { id: 't_00000002', text: 'Photograph the swatches', due: '2026-09-28', done: false }] },
      { who: 'Kit', open: 1, done: 0, more: 0, tasks: [{ id: 't_00000003', text: 'Update the size chart', due: '2026-10-02', done: false }] },
    ],
  });
}

function regroup(card) {
  for (const g of card.groups) {
    g.tasks.sort((a, b) => Number(a.done) - Number(b.done));
    g.done = g.tasks.filter((t) => t.done).length;
    g.open = g.tasks.length - g.done;
  }
  card.groups = card.groups.filter((g) => g.tasks.length);
}

// The Mac, as far as these touches go: it keeps the card, answers each touch with the card drawn
// from it and an undo offer, and puts back exactly what the last touch changed.
function mac(start, says) {
  const M = { card: clone(start), asked: [], refuse: null, before: null, n: 0 };
  const offer = (text) => { M.n += 1; return { token: `tok-${M.n}`, ttl_s: 6, says: text }; };
  M.send = async (url, body) => {
    M.asked.push([url, body]);
    if (M.refuse) throw new Error(M.refuse);
    const tail = url.slice(`/objectives/${M.card.objective_id}`.length);
    if (tail === '/undo') {
      M.card = M.before;
      return { id: M.card.objective_id, card: clone(M.card), said: (says && says.undo) || 'Put back as it was before' };
    }
    M.before = clone(M.card);
    if (tail === '/stage') {
      const at = M.card.stages.findIndex((s) => s.name === body.stage);
      M.card.stages.forEach((s, i) => { s.state = i < at ? 'done' : i === at ? 'current' : 'upcoming'; });
      return { card: clone(M.card), undo: offer((says && says.stage) || `${body.stage} is now`), said: null };
    }
    if (tail === '/deadline') {
      M.card.deadline = body.deadline;
      return { card: clone(M.card), undo: offer(`Due ${body.deadline}`), said: null };
    }
    const id = tail.split('/')[2];
    const from = M.card.groups.find((g) => g.tasks.some((t) => t.id === id));
    const task = from.tasks.find((t) => t.id === id);
    if (body.who) {
      from.tasks = from.tasks.filter((t) => t !== task);
      M.card.groups.find((g) => g.who === body.who).tasks.push(task);
    }
    if (body.done !== undefined) task.done = body.done;
    regroup(M.card);
    return { card: clone(M.card), undo: offer(body.who ? `Moved to ${body.who}` : `${body.done ? 'Done' : 'Open again'}: ${task.text}`), said: null };
  };
  M.post = (objective, task, done) => M.send(`/objectives/${objective}/tasks/${task}`, { done });
  return M;
}

const steps = (card) => all(card, 'oc-step');
const states = (card) => steps(card).map((s) => s.className.replace(/.*is-(done|current|upcoming).*/, '$1'));
const row = (card, text) => all(card, 'oc-task').find((b) => words(b).includes(text));

// ---------------------------------------------------------------- a tap, or two

test('a tap and a double-tap are told apart, and a tap waits only where a double-tap means something else', () => {
  const tap = T.taps();
  const log = [];
  const how = (name, waits) => ({ waits, single: (p) => log.push(`${name} ${p}`), double: (first, p) => log.push(`${name} double ${first}>${p}`) });
  tap('stage', 'stage', how('stage', true));
  C.advance(279);
  assert.deepEqual(log, [], 'a tap whose element has a double-tap waits for the window');
  C.advance(1);
  assert.deepEqual(log, ['stage stage']);
  log.length = 0;
  tap('stage', 'stage', how('stage', true));
  C.advance(200);
  tap('stage', 'stage', how('stage', true));
  C.advance(1000);
  assert.deepEqual(log, ['stage double stage>stage'], 'two taps inside the window: the double-tap, and never the first tap\'s action');
  log.length = 0;
  tap('tick', 'tick', how('tick', false));
  assert.deepEqual(log, ['tick tick'], 'a tap that means the same as a double-tap acts at once');
  C.advance(100);
  tap('tick', 'tick', how('tick', false));
  assert.deepEqual(log, ['tick tick', 'tick double tick>tick'], 'and its second tap is known as the second');
  log.length = 0;
  tap('slow', 'x', how('slow', false));
  C.advance(300);
  tap('slow', 'x', how('slow', false));
  assert.deepEqual(log, ['slow x', 'slow x'], 'slower than the window, two taps');
  log.length = 0;
  tap('a', 'x', how('a', true));
  C.advance(100);
  tap('b', 'x', how('b', true));
  C.advance(300);
  assert.deepEqual(log, ['a x', 'b x'], 'a tap on one thing then another is two taps');
  assert.equal(T.TAP_MS, 280);
});

// ---------------------------------------------------------------- the bar

test('the bar says what a touch did, with Undo for six seconds, then goes; a line that changes nothing leaves the Undo alone', () => {
  const bar = T.bar();
  assert.deepEqual(bar.state(), { text: '', kind: '', undo: false, hidden: true }, 'nothing to say, nothing shown');
  bar.did('Moved to Kit', async () => 'Put back');
  assert.deepEqual(bar.state(), { text: 'Moved to Kit', kind: 'did', undo: true, hidden: false });
  C.advance(500);
  bar.say('Approval: to come, waiting on you.');
  assert.deepEqual(bar.state(), { text: 'Approval: to come, waiting on you.', kind: 'info', undo: true, hidden: false }, 'the line shows; the Undo stays');
  C.advance(4000);
  assert.deepEqual(bar.state(), { text: 'Moved to Kit', kind: 'did', undo: true, hidden: false }, 'its time over, the bar says the change again, Undo still there');
  C.advance(1499);
  assert.equal(bar.state().undo, true, 'six seconds from the change, not from the line');
  C.advance(1);
  assert.deepEqual(bar.state(), { text: '', kind: '', undo: false, hidden: true }, 'and then the bar goes');
  // A line said late in the six seconds outlasts the Undo, which still goes on time.
  bar.did('Done: Steam the AW samples', async () => '');
  C.advance(3000);
  bar.say('Kit: Update the size chart.');
  C.advance(3000);
  assert.deepEqual(bar.state(), { text: 'Kit: Update the size chart.', kind: 'info', undo: false, hidden: false });
  C.advance(1000);
  assert.equal(bar.state().hidden, true);
  // A line on its own goes after its own time; a new change replaces the old offer.
  bar.say('Sampling is already now.');
  C.advance(T.SAY_MS);
  assert.equal(bar.state().hidden, true);
  bar.did('A', async () => '');
  C.advance(4000);
  bar.did('B', async () => '');
  C.advance(4000);
  assert.deepEqual(bar.state(), { text: 'B', kind: 'did', undo: true, hidden: false });
  assert.equal(T.UNDO_MS, 6000);
});

test('Undo asks, snaps and says what it put back; refused or unreachable it says so, and nothing pretends', async () => {
  const bar = T.bar();
  let asked = 0;
  bar.did('Production is now', async () => { asked += 1; return 'Back at Approval, as it was'; });
  one(bar.el, 'ot-undo').dispatch('click');
  assert.equal(one(bar.el, 'ot-undo').disabled, true, 'pressed once, it waits for the answer');
  one(bar.el, 'ot-undo').dispatch('click');
  await flush();
  assert.equal(asked, 1, 'one undo for one press, however many taps');
  assert.deepEqual(felt, [[8]], 'one short snap');
  assert.deepEqual(bar.state(), { text: 'Back at Approval, as it was', kind: 'info', undo: false, hidden: false });
  bar.did('Done: Photograph the swatches', async () => { throw new Error('It has changed since, so nothing was undone.'); });
  await bar.undo();
  assert.deepEqual(bar.state(), { text: 'It has changed since, so nothing was undone.', kind: 'error', undo: false, hidden: false });
  assert.deepEqual(felt[felt.length - 1], [40, 50, 40]);
  const lost = new Error('CLIVE could not be reached');
  lost.unreached = true;
  bar.did('Due Fri 30 Oct', async () => { throw lost; });
  await bar.undo();
  assert.equal(bar.state().text, 'CLIVE could not be reached, so nothing was undone.');
  bar.did('Moved to Kit', async () => { asked += 1; return ''; });
  C.advance(6000);
  await bar.undo();
  assert.equal(asked, 1, 'after its six seconds there is nothing to undo');
});

// ---------------------------------------------------------------- a project

test('with the touch layer a card keeps its shape, its ticks and its keyboard, and carries the bar at its foot', async () => {
  const card = OC.card(project(), { now: NOW, send: async () => ({}) });
  assert.deepEqual(steps(card).map((s) => s.className), ['oc-step is-current', 'oc-step is-upcoming', 'oc-step is-upcoming', 'oc-step is-upcoming']);
  assert.ok(steps(card).every((s) => s.getAttribute('tabindex') === '0'), 'each stage takes the keyboard');
  // A still hold on a stage still lifts the objective to a screen (web/lift.js): a stage is not
  // one of the page's controls, while "now" and the date ring, which have their own press, are.
  const controls = require(path.join(WEB, 'touch.js')).CONTROL_SELECTOR;
  assert.ok(steps(card).every((s) => s.tagName === 'LI' && s.getAttribute('role') === null));
  assert.ok(!/(^|,)\s*(li|\[tabindex)/.test(controls) && controls.includes('button:not(#talk)'));
  assert.ok([one(card, 'ot-grip'), one(card, 'ot-ring')].every((b) => b.tagName === 'BUTTON'));
  assert.equal(card.childNodes[card.childNodes.length - 1], one(card, 'ot-bar'), 'the bar is at the card\'s foot');
  assert.equal(barOf(card).shown, false, 'and says nothing until a touch does something');
  const M = mac(tasks());
  const list = OC.card(tasks(), { now: NOW, post: M.post, send: M.send });
  for (const t of all(list, 'oc-task')) {
    assert.equal(t.tagName, 'BUTTON');
    assert.equal(t.getAttribute('role'), 'checkbox');
  }
  row(list, 'Steam').dispatch('click');                     // Space or Enter on the focused row: no pointer
  assert.equal(row(list, 'Steam').getAttribute('aria-checked'), 'true', 'ticked at once, as it always was');
  await flush();
  assert.deepEqual(M.asked, [[`/objectives/${TID}/tasks/t_00000001`, { done: true }]]);
  // A read-only drawing, or one without a bar, has no touch at all.
  assert.equal(one(OC.card(project(), { now: NOW, readOnly: true }), 'ot-when'), null);
  assert.equal(one(OC.shape(project(), { now: NOW }), 'ot-grip'), null);
});

test('a tap on a stage says what the record holds about it; a double-tap makes it now', async () => {
  const M = mac(project());
  const card = OC.card(project(), { now: NOW, send: M.send });
  steps(card)[1].dispatch('click');
  assert.equal(barOf(card).shown, false, 'a tap waits: a double-tap would mean something else');
  C.advance(280);
  assert.deepEqual(barOf(card), { text: 'Approval: to come, waiting on you, by 9 Oct.', kind: 'info', undo: false, shown: true });
  steps(card)[0].dispatch('click');
  C.advance(280);
  assert.equal(barOf(card).text, 'Sampling, now, waiting on Northfield, by Fri 2 Oct.');
  assert.deepEqual(felt, [], 'a tap does not buzz');
  assert.deepEqual(M.asked, [], 'and changes nothing');
  steps(card)[2].dispatch('click');
  C.advance(150);
  steps(card)[2].dispatch('click');
  assert.deepEqual(states(card), ['done', 'done', 'current', 'upcoming'], 'shown at once, before the Mac answers');
  assert.equal(words(one(steps(card)[2], 'oc-step-name')), 'ProductionNow', 'the Now mark goes with it');
  await flush();
  assert.deepEqual(M.asked, [[`/objectives/${PID}/stage`, { stage: 'Production' }]]);
  assert.equal(words(one(card, 'oc-status')).split(' · ')[0], 'Stage 3 of 4', 'drawn again from the Mac\'s answer');
  assert.deepEqual(barOf(card), { text: 'Production is now', kind: 'did', undo: true, shown: true });
  assert.deepEqual(felt, [[10, 60, 10]], 'done: two short taps');
  C.advance(1000);
  assert.equal(barOf(card).text, 'Production is now', 'the first tap of the double-tap never said anything');
});

test('a double-tap on the stage it is at says so; a project not started is started; Enter does the same', async () => {
  let M = mac(project());
  let card = OC.card(project(), { now: NOW, send: M.send });
  steps(card)[0].dispatch('click');
  C.advance(100);
  steps(card)[0].dispatch('click');
  await flush();
  assert.deepEqual(barOf(card), { text: 'Sampling is already now.', kind: 'info', undo: false, shown: true });
  assert.deepEqual(M.asked, []);
  const fresh = project();
  fresh.stages.forEach((s) => { s.state = 'upcoming'; });
  M = mac(fresh);
  card = OC.card(fresh, { now: NOW, send: M.send, onChange: () => {} });
  assert.equal(one(card, 'ot-grip'), null, 'not started: no "now" to drag');
  steps(card)[1].dispatch('click');
  C.advance(100);
  steps(card)[1].dispatch('click');
  assert.deepEqual(states(card), ['done', 'current', 'upcoming', 'upcoming']);
  await flush();
  assert.deepEqual(M.asked, [[`/objectives/${PID}/stage`, { stage: 'Approval' }]]);
  M = mac(project());
  card = OC.card(project(), { now: NOW, send: M.send });
  steps(card)[3].dispatch('keydown', { key: 'Enter' });
  await flush();
  assert.deepEqual(M.asked, [[`/objectives/${PID}/stage`, { stage: 'Delivery' }]]);
});

function placeStages(card) {
  all(card, 'oc-node').forEach((n, i) => { n.rect = { left: 0, top: i * 60, width: 26, height: 26 }; });   // centres 13, 73, 133, 193
}

test('"now" dragged along the rail snaps stage to stage with a detent, shows where it would be, and lands where it is let go', async () => {
  const M = mac(project());
  const card = OC.card(project(), { now: NOW, send: M.send });
  placeStages(card);
  const grip = one(card, 'ot-grip');
  assert.equal(grip.tagName, 'BUTTON', 'a control of its own: a still hold on it does not lift the objective (web/lift.js)');
  assert.ok(steps(card)[0].querySelector('.ot-grip'), 'on the stage it is at');
  pointer(grip, 'pointerdown', 13, 13);
  pointer(grip, 'pointermove', 13, 30);
  assert.deepEqual(felt, [12], 'lifted');
  assert.deepEqual(states(card), ['current', 'upcoming', 'upcoming', 'upcoming']);
  pointer(grip, 'pointermove', 13, 75);
  assert.deepEqual(states(card), ['done', 'current', 'upcoming', 'upcoming'], 'the stage under it shows as now');
  assert.equal(words(one(steps(card)[1], 'oc-step-name')), 'ApprovalNow');
  pointer(grip, 'pointermove', 13, 138);
  assert.deepEqual(felt, [12, 6, 6], 'a detent at every stage it passes');
  assert.equal(grip.style.getPropertyValue('--dy'), '125px', 'under the finger');
  assert.deepEqual(M.asked, [], 'nothing is asked while the finger is down');
  pointer(grip, 'pointerup', 13, 138);
  let stopped = 0;
  grip.dispatch('click', { stopPropagation: () => { stopped += 1; } });
  assert.equal(stopped, 1, 'the click the release makes does not reach the stage as a tap');
  await flush();
  assert.deepEqual(M.asked, [[`/objectives/${PID}/stage`, { stage: 'Production' }]]);
  assert.deepEqual(barOf(card), { text: 'Production is now', kind: 'did', undo: true, shown: true });
});

test('"now" let go where it started, or lost, changes nothing; refused, it goes back and says why', async () => {
  const M = mac(project());
  let card = OC.card(project(), { now: NOW, send: M.send });
  placeStages(card);
  let grip = one(card, 'ot-grip');
  let stopped = 0;
  pointer(grip, 'pointerdown', 13, 13);
  pointer(grip, 'pointerup', 14, 14);
  grip.dispatch('click', { stopPropagation: () => { stopped += 1; } });
  assert.equal(stopped, 0, 'a tap on "now" is a tap on its stage');
  pointer(grip, 'pointerdown', 13, 13);
  pointer(grip, 'pointermove', 13, 75);
  pointer(grip, 'pointermove', 13, 20);
  pointer(grip, 'pointerup', 13, 20);
  await flush();
  assert.deepEqual(M.asked, []);
  assert.deepEqual(steps(card).map((s) => s.className), ['oc-step is-current', 'oc-step is-upcoming', 'oc-step is-upcoming', 'oc-step is-upcoming']);
  assert.equal(words(one(steps(card)[0], 'oc-step-name')), 'SamplingNow');
  assert.equal(grip.style.getPropertyValue('--dy'), '0px');
  pointer(grip, 'pointerdown', 13, 13);
  pointer(grip, 'pointermove', 13, 140);
  pointer(grip, 'pointercancel', 13, 140);
  await flush();
  assert.deepEqual(M.asked, [], 'a pointer the browser took away commits nothing');
  assert.deepEqual(states(card), ['current', 'upcoming', 'upcoming', 'upcoming']);
  M.refuse = 'There is no stage \'Production\'; the stages are Sampling, Approval.';
  card = OC.card(project(), { now: NOW, send: M.send });
  placeStages(card);
  grip = one(card, 'ot-grip');
  pointer(grip, 'pointerdown', 13, 13);
  pointer(grip, 'pointermove', 13, 133);
  pointer(grip, 'pointerup', 13, 133);
  await flush();
  assert.deepEqual(states(card), ['current', 'upcoming', 'upcoming', 'upcoming'], 'put back as the record has it');
  assert.deepEqual(barOf(card), { text: `Not saved: ${M.refuse}`, kind: 'error', undo: false, shown: true });
  assert.deepEqual(felt[felt.length - 1], [40, 50, 40]);
});

// ---------------------------------------------------------------- the date it must land by

test('the date it must land by: one dot a day, the deadline ringed, each stage\'s date marked', () => {
  const card = OC.card(project(), { now: NOW, send: async () => ({}) });
  const days = all(card, 'ot-day');
  assert.equal(days.length, 29, 'today to a week past the later of the deadline (20 Oct) and the last stage (16 Oct)');
  assert.ok(days[0].classList.contains('is-today'));
  assert.deepEqual(days.map((d, i) => (d.classList.contains('is-stage') ? i : -1)).filter((i) => i >= 0), [3, 10, 17]);
  const ring = one(card, 'ot-ring');
  assert.equal(ring.getAttribute('role'), 'slider');
  assert.equal(ring.tagName, 'BUTTON', 'a control of its own: a still press on it does not lift the objective (web/lift.js)');
  assert.equal(ring.getAttribute('aria-valuemax'), '28');
  assert.equal(ring.getAttribute('aria-valuenow'), '21');
  assert.equal(ring.getAttribute('aria-valuetext'), 'Due Tue 20 Oct, everything lands in time');
  assert.equal(ring.style.getPropertyValue('--x'), '75');
  assert.equal(words(one(card, 'ot-flag')), 'Due Tue 20 Oct');
  assert.equal(words(one(card, 'ot-lands')), 'Everything still lands in time.');
  assert.equal(one(OC.card(project({ deadline: null }), { now: NOW, send: async () => ({}) }), 'ot-when'), null, 'only drawn when there is a deadline');
});

test('dragging the date, the stages that would land late turn red while the finger is down; let go, it is asked', async () => {
  const M = mac(project());
  const card = OC.card(project(), { now: NOW, send: M.send });
  one(card, 'ot-track').rect = { left: 0, top: 0, width: 280, height: 66 };    // ten pixels a day
  const ring = one(card, 'ot-ring');
  pointer(ring, 'pointerdown', 210, 46);
  pointer(ring, 'pointermove', 200, 46);
  assert.equal(ring.getAttribute('aria-valuenow'), '20');
  assert.ok(!steps(card).some((s) => s.classList.contains('is-after')));
  pointer(ring, 'pointermove', 80, 46);
  assert.deepEqual(steps(card).map((s) => s.classList.contains('is-after')), [false, true, true, false], 'Approval and Production would land after it');
  assert.deepEqual(all(card, 'ot-day').filter((d) => d.classList.contains('is-after')).length, 2);
  assert.equal(words(one(card, 'ot-lands')), '2 stages would land late: Approval and Production.');
  assert.ok(ring.classList.contains('is-late') && one(card, 'ot-flag').classList.contains('is-late'));
  assert.equal(words(one(card, 'ot-flag')), 'Due Wed 7 Oct · 8 days left');
  assert.equal(ring.getAttribute('aria-valuetext'), 'Due Wed 7 Oct, 2 stages would land late', 'in words, and no name in an attribute');
  assert.deepEqual(felt, [12, 6, 6], 'lifted, then a detent at each step');
  assert.deepEqual(M.asked, [], 'consequence before commit: nothing is asked while the finger is down');
  pointer(ring, 'pointerup', 80, 46);
  await flush();
  assert.deepEqual(M.asked, [[`/objectives/${PID}/deadline`, { deadline: '2026-10-07' }]]);
  assert.deepEqual(barOf(card), { text: 'Due 2026-10-07', kind: 'did', undo: true, shown: true });
  assert.equal(one(card, 'ot-ring').getAttribute('aria-valuenow'), '8', 'drawn again from the answer');
});

test('the date ring from the keyboard: arrows move a day, Escape puts it back, Enter keeps it', async () => {
  const M = mac(project());
  const card = OC.card(project(), { now: NOW, send: M.send });
  const ring = one(card, 'ot-ring');
  ring.dispatch('keydown', { key: 'ArrowRight' });
  assert.equal(ring.getAttribute('aria-valuenow'), '22');
  assert.equal(ring.getAttribute('aria-valuetext'), 'Due Wed 21 Oct, everything lands in time');
  ring.dispatch('keydown', { key: 'Escape' });
  assert.equal(ring.getAttribute('aria-valuenow'), '21');
  ring.dispatch('keydown', { key: 'PageDown' });
  ring.dispatch('keydown', { key: 'PageDown' });
  assert.equal(ring.getAttribute('aria-valuetext'), 'Due Tue 6 Oct, 2 stages would land late');
  assert.deepEqual(M.asked, []);
  ring.dispatch('keydown', { key: 'Enter' });
  await flush();
  assert.deepEqual(M.asked, [[`/objectives/${PID}/deadline`, { deadline: '2026-10-06' }]]);
  // Let go where it started, and nothing is asked.
  const again = OC.card(project(), { now: NOW, send: M.send });
  one(again, 'ot-track').rect = { left: 0, top: 0, width: 280, height: 66 };
  const r2 = one(again, 'ot-ring');
  pointer(r2, 'pointerdown', 210, 46);
  pointer(r2, 'pointermove', 150, 46);
  pointer(r2, 'pointermove', 212, 46);
  pointer(r2, 'pointerup', 212, 46);
  await flush();
  assert.equal(M.asked.length, 1);
});

// ---------------------------------------------------------------- tasks

test('a task: the round tick ticks at a tap, a double-tap anywhere ticks once, a tap on the words says what it is', async () => {
  const M = mac(tasks());
  const card = OC.card(tasks(), { now: NOW, post: M.post, send: M.send });
  const tick = (b) => one(b, 'oc-check');
  row(card, 'Steam').dispatch('click', { detail: 1, target: tick(row(card, 'Steam')) });
  assert.equal(row(card, 'Steam').getAttribute('aria-checked'), 'true', 'at once');
  await flush();
  assert.deepEqual(M.asked, [[`/objectives/${TID}/tasks/t_00000001`, { done: true }]]);
  assert.deepEqual(barOf(card), { text: 'Done: Steam the AW samples', kind: 'did', undo: true, shown: true });
  assert.deepEqual(felt, [[10, 60, 10]]);
  // The second tap of that double-tap lands on the row as it was drawn again: the same tick.
  C.advance(120);
  row(card, 'Steam').dispatch('click', { detail: 2, target: tick(row(card, 'Steam')) });
  await flush();
  assert.equal(M.asked.length, 1, 'two taps on the tick: one tick, never tick-and-untick');
  assert.equal(row(card, 'Steam').getAttribute('aria-checked'), 'true');
  C.advance(1000);
  const swatches = () => row(card, 'Photograph');
  swatches().dispatch('click', { detail: 1, target: one(swatches(), 'oc-task-text') });
  C.advance(150);
  assert.equal(M.asked.length, 1);
  swatches().dispatch('click', { detail: 2, target: one(swatches(), 'oc-task-text') });
  await flush();
  assert.deepEqual(M.asked[1], [`/objectives/${TID}/tasks/t_00000002`, { done: true }], 'a double-tap on the words ticks');
  C.advance(1000);
  assert.equal(barOf(card).text, 'Done: Photograph the swatches', 'and the first of its taps said nothing');
  const kit = () => row(card, 'size chart');
  kit().dispatch('click', { detail: 1, target: one(kit(), 'oc-task-text') });
  C.advance(279);
  assert.equal(M.asked.length, 2);
  C.advance(1);
  assert.deepEqual(barOf(card), { text: 'Kit: Update the size chart, by Fri 2 Oct.', kind: 'info', undo: true, shown: true }, 'who, what, by when; the Undo left alone');
  assert.equal(M.asked.length, 2, 'a tap on the words changes nothing');
  swatches().dispatch('click', { detail: 1, target: one(swatches(), 'oc-due') });
  C.advance(280);
  assert.equal(barOf(card).text, 'Rosa: Photograph the swatches, done.');
});

function placeGroups(card) {
  const groups = all(card, 'oc-group');
  groups[0].rect = { left: 0, top: 0, width: 400, height: 200 };
  groups[1].rect = { left: 0, top: 220, width: 400, height: 120 };
  return groups;
}

test('pressed still for a moment and dragged onto Kit, a task is handed over, settles into Kit\'s list, and can be undone', async () => {
  const M = mac(tasks());
  const card = OC.card(tasks(), { now: NOW, post: M.post, send: M.send });
  let groups = placeGroups(card);
  const swatches = row(card, 'Photograph');
  pointer(swatches, 'pointerdown', 200, 140);
  C.advance(249);
  pointer(swatches, 'pointermove', 203, 141);
  assert.ok(!swatches.classList.contains('is-lifted'), 'not yet');
  C.advance(1);
  assert.ok(swatches.classList.contains('is-lifted') && one(card, 'oc-tasks').classList.contains('is-dragging'));
  assert.deepEqual(felt, [12], 'lifted');
  pointer(swatches, 'pointermove', 200, 190);
  assert.ok(!groups.some((g) => g.classList.contains('is-over')), 'over its own person, nothing to drop on');
  pointer(swatches, 'pointermove', 200, 260);
  assert.ok(groups[1].classList.contains('is-over'));
  assert.deepEqual(felt, [12, 6], 'a detent as it comes over Kit');
  assert.equal(swatches.style.getPropertyValue('--dy'), '120px', 'under the finger');
  swatches.rect = { left: 0, top: 240, width: 400, height: 54 };       // where it is let go
  pointer(swatches, 'pointerup', 200, 260);
  swatches.dispatch('click', { detail: 1, target: one(swatches, 'oc-task-text') });   // the click a release makes
  C.advance(300);
  await flush();
  assert.deepEqual(M.asked, [[`/objectives/${TID}/tasks/t_00000002`, { who: 'Kit' }]], 'only who it is for, and no tap');
  groups = all(card, 'oc-group');
  assert.deepEqual(groups.map((g) => g.querySelectorAll('.oc-task-text').map(words)),
    [['Steam the AW samples'], ['Update the size chart', 'Photograph the swatches']], 'drawn again from the Mac\'s answer');
  assert.deepEqual(barOf(card), { text: 'Moved to Kit', kind: 'did', undo: true, shown: true });
  const moved = row(card, 'Photograph');
  assert.ok(moved.classList.contains('is-flying'), 'drawn where it was let go');
  assert.equal(moved.style.getPropertyValue('--dy'), '240px');
  await new Promise((r) => setTimeout(r, 60));
  assert.ok(moved.classList.contains('is-settling') && moved.style.getPropertyValue('--dy') === '0px', 'then settles into its place');
  one(card, 'ot-undo').dispatch('click');
  await flush();
  assert.deepEqual(M.asked[1], [`/objectives/${TID}/undo`, { token: 'tok-1' }]);
  assert.deepEqual(all(card, 'oc-group').map((g) => words(one(g, 'oc-who'))), ['Rosa', 'Kit']);
  assert.ok(words(all(card, 'oc-group')[0]).includes('Photograph the swatches'), 'Rosa\'s again');
  assert.deepEqual(barOf(card), { text: 'Put back as it was before', kind: 'info', undo: false, shown: true });
  assert.deepEqual(felt[felt.length - 1], [8]);
});

test('a still press does nothing extra, a move before the press arms is the sheet\'s scroll, and a drop on its own person changes nothing', async () => {
  const M = mac(tasks());
  const card = OC.card(tasks(), { now: NOW, post: M.post, send: M.send });
  placeGroups(card);
  const swatches = row(card, 'Photograph');
  pointer(swatches, 'pointerdown', 200, 140);
  C.advance(600);
  pointer(swatches, 'pointerup', 200, 140);
  swatches.dispatch('click', { detail: 1, target: one(swatches, 'oc-check') });
  C.advance(300);
  await flush();
  assert.deepEqual(M.asked, [], 'held still and let go: no tick, no move');
  assert.ok(!swatches.classList.contains('is-lifted'));
  assert.equal(barOf(card).shown, false);
  pointer(swatches, 'pointerdown', 200, 140);
  C.advance(100);
  pointer(swatches, 'pointermove', 200, 110);
  C.advance(400);
  assert.ok(!swatches.classList.contains('is-lifted'), 'a scroll is the sheet\'s');
  pointer(swatches, 'pointerup', 200, 60);
  pointer(swatches, 'pointerdown', 200, 140);
  C.advance(250);
  pointer(swatches, 'pointermove', 200, 40);
  pointer(swatches, 'pointerup', 200, 40);
  C.advance(500);
  await flush();
  assert.deepEqual(M.asked, [], 'let go over its own person');
  assert.ok(!one(card, 'oc-tasks').classList.contains('is-dragging'));
  assert.equal(swatches.style.getPropertyValue('--dy'), '0px', 'settled back');
});

test('a second finger ends a press: a pinch whose first finger rested on a task hands nothing over (review of PR #91)', async () => {
  // The page's own capture listener, as the browser would run it for a finger anywhere on the glass.
  const heard = [];
  shim.document.addEventListener = (type, fn, capture) => { if (type === 'pointerdown' && capture) heard.push(fn); };
  try {
    const M = mac(tasks());
    const card = OC.card(tasks(), { now: NOW, post: M.post, send: M.send });
    placeGroups(card);
    const swatches = row(card, 'Photograph');
    assert.equal(heard.length, 1, 'one listener for the page');
    pointer(swatches, 'pointerdown', 200, 140);
    for (const fn of heard) fn({ type: 'pointerdown', pointerId: 8, clientX: 200, clientY: 300, isPrimary: false });
    C.advance(260);
    assert.ok(!swatches.classList.contains('is-lifted'), 'the press was ended by the second finger, so it never arms');
    pointer(swatches, 'pointermove', 200, 260);
    pointer(swatches, 'pointerup', 200, 260);
    C.advance(500);
    await flush();
    assert.deepEqual(M.asked, [], 'nothing handed over, nothing ticked');
    // Armed first and then joined by a second finger: it goes back, and nothing is asked either.
    pointer(swatches, 'pointerdown', 200, 140);
    C.advance(260);
    assert.ok(swatches.classList.contains('is-lifted'));
    pointer(swatches, 'pointermove', 200, 260);
    for (const fn of heard) fn({ type: 'pointerdown', pointerId: 8, clientX: 200, clientY: 300, isPrimary: false });
    pointer(swatches, 'pointerup', 200, 260);
    C.advance(500);
    await flush();
    assert.deepEqual(M.asked, [], 'a lifted task is put back, not handed over');
    assert.ok(!swatches.classList.contains('is-lifted'));
  } finally {
    delete shim.document.addEventListener;
  }
});

test('the date ring moves by how far the finger goes, never to where it happens to be, and an up-or-down drag moves nothing', async () => {
  const M = mac(project());
  const card = OC.card(project(), { now: NOW, send: M.send });
  one(card, 'ot-track').rect = { left: 0, top: 0, width: 280, height: 66 };    // ten pixels a day; the ring is at 210
  const ring = one(card, 'ot-ring');
  pointer(ring, 'pointerdown', 228, 46);       // pressed 18 px right of the ring's centre
  pointer(ring, 'pointermove', 238, 46);       // and nudged 10 px: one day, not three
  assert.equal(ring.getAttribute('aria-valuenow'), '22');
  pointer(ring, 'pointermove', 228, 46);
  pointer(ring, 'pointerup', 228, 46);
  await flush();
  assert.deepEqual(M.asked, [], 'back where it started: nothing asked');
  pointer(ring, 'pointerdown', 210, 46);
  pointer(ring, 'pointermove', 212, 80);       // mostly down: a scroll's start, not a date drag
  pointer(ring, 'pointermove', 150, 120);
  pointer(ring, 'pointerup', 150, 120);
  await flush();
  assert.equal(ring.getAttribute('aria-valuenow'), '21');
  assert.deepEqual(M.asked, []);
});

test('from the keyboard, the context-menu key hands a task over from a short menu', async () => {
  const M = mac(tasks());
  const card = OC.card(tasks(), { now: NOW, post: M.post, send: M.send });
  row(card, 'Photograph').dispatch('keydown', { key: 'ContextMenu' });
  let menu = one(card, 'ot-menu');
  assert.equal(menu.getAttribute('role'), 'menu');
  const items = all(menu, 'ot-menu-item');
  assert.deepEqual(items.map(words), ['Give to Kit', 'Cancel']);
  assert.equal(document.activeElement, items[0]);
  menu.dispatch('keydown', { key: 'ArrowDown' });
  assert.equal(document.activeElement, items[1]);
  menu.dispatch('keydown', { key: 'Escape' });
  assert.equal(one(card, 'ot-menu'), null);
  assert.equal(document.activeElement, row(card, 'Photograph'), 'back on the task');
  row(card, 'Photograph').dispatch('keydown', { key: 'F10', shiftKey: true });
  menu = one(card, 'ot-menu');
  all(menu, 'ot-menu-item')[0].dispatch('click');
  await flush();
  assert.deepEqual(M.asked, [[`/objectives/${TID}/tasks/t_00000002`, { who: 'Kit' }]]);
  assert.equal(barOf(card).text, 'Moved to Kit');
  assert.equal(document.activeElement, row(card, 'Photograph'), 'the focus follows the task to Kit');
});

// ---------------------------------------------------------------- the page's rules

test('every word from the record is text, and no attribute carries it', async () => {
  const hostile = project({ title: HOSTILE });
  hostile.stages[1].name = HOSTILE;
  hostile.stages[1].waiting_on = HOSTILE;
  const M = mac(hostile, { stage: HOSTILE, undo: HOSTILE });
  const card = OC.card(hostile, { now: NOW, send: M.send });
  steps(card)[1].dispatch('click');
  C.advance(280);
  assert.ok(barOf(card).text.includes(HOSTILE), 'said as written');
  one(card, 'ot-ring').dispatch('keydown', { key: 'Home' });
  assert.ok(words(one(card, 'ot-lands')).includes(HOSTILE), 'the late stage named, in words');
  one(card, 'ot-ring').dispatch('keydown', { key: 'Escape' });
  steps(card)[1].dispatch('keydown', { key: 'Enter' });
  await flush();
  assert.equal(barOf(card).text, HOSTILE);
  const list = tasks();
  list.groups[0].who = HOSTILE;
  list.groups[0].tasks[0].text = HOSTILE;
  const tasksCard = OC.card(list, { now: NOW, send: async () => ({}) });
  all(tasksCard, 'oc-task')[0].dispatch('click', { detail: 1, target: one(all(tasksCard, 'oc-task')[0], 'oc-task-text') });
  C.advance(280);
  assert.ok(barOf(tasksCard).text.startsWith(HOSTILE));
  all(tasksCard, 'oc-task')[2].dispatch('keydown', { key: 'ContextMenu' });
  assert.ok(words(one(tasksCard, 'ot-menu')).includes(HOSTILE));
  for (const node of [card, tasksCard]) {
    const walk = (n) => {
      if (n.nodeType !== 1) return;
      assert.notEqual(n.tagName, 'IMG');
      assert.notEqual(n.tagName, 'SCRIPT');
      for (const value of Object.values(n.attributes)) assert.ok(!String(value).includes('<'), `attribute ${value}`);
      for (const value of Object.values(n.dataset)) assert.ok(!String(value).includes('<'), `data ${value}`);
      n.childNodes.forEach(walk);
    };
    walk(node);
  }
});

test('the touch file keeps the page\'s rules: text only, the owner\'s own routes, and nothing near the microphone', () => {
  const source = fs.readFileSync(path.join(WEB, 'objective-touch.js'), 'utf8');
  assert.ok(!/innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(/.test(source));
  for (const name of ['getUserMedia', 'mediaDevices', 'MediaRecorder', 'talk', 'orb-frame', 'dispatchEvent', '.click(', 'CliveAlpha']) {
    assert.ok(!source.includes(name), `web/objective-touch.js has ${JSON.stringify(name)}`);
  }
  // The drawings post only to the owner's own routes for one objective: these four, nothing else.
  const cards = fs.readFileSync(path.join(WEB, 'objective-cards.js'), 'utf8');
  const tails = [...cards.matchAll(/(?:commit\([^,]+, |ctx\.url\()[`']([^`'$]*)/g)].map((m) => m[1]);
  assert.deepEqual([...new Set(tails)].sort(), ['', '/deadline', '/stage', '/tasks/', '/undo']);
  const index = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
  assert.ok(index.indexOf('/static/objective-touch.js') > 0 && index.indexOf('/static/objective-touch.js') < index.indexOf('/static/objective-cards.js'),
    'loaded before the drawings that use it');
  const worker = fs.readFileSync(path.join(WEB, 'sw.js'), 'utf8');
  assert.ok(worker.includes("'/static/objective-touch.js'"), 'kept with the app shell');
  const css = fs.readFileSync(path.join(WEB, 'objective-cards.css'), 'utf8');
  for (const rule of ['.ot-bar', '.ot-undo', '.ot-ring', '.ot-grip', '.oc-task.is-lifted', '.oc-step.is-after']) assert.ok(css.includes(rule), rule);
  assert.match(css, /@media \(prefers-reduced-motion:reduce\)\{[^}]*\.ot-grip,\.ot-ring/, 'with motion turned down nothing travels');
});

// ---------------------------------------------------------------- the sheet on the home

class PageElement extends shim.Element {
  constructor(tag, ns) { super(tag, ns); this.open = false; this.scrollTop = 0; }
  append(...kids) { for (const k of kids) this.appendChild(typeof k === 'string' ? new shim.Text(k) : k); }
  prepend(...kids) { for (const k of kids.reverse()) this.insertBefore(typeof k === 'string' ? new shim.Text(k) : k, this.firstChild); }
  replaceChildren(...kids) { for (const c of this.childNodes.slice()) this.removeChild(c); this.append(...kids); }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  showModal() { this.open = true; }
  close() { this.open = false; }
}

test('the sheet keeps its bar at its foot through the redraw a touch causes, and Undo works from there', async () => {
  const card = project();
  const M = mac(card);
  const body = new PageElement('body');
  const app = new PageElement('div');
  const footer = new PageElement('footer');
  footer.className = 'bottom';
  body.appendChild(app);
  app.appendChild(footer);
  const document = {
    body, activeElement: null, hidden: false,
    createElement: (tag) => new PageElement(tag),
    createElementNS: (ns, tag) => new PageElement(tag, ns),
    createTextNode: (data) => new shim.Text(data),
    querySelector: (sel) => (sel === '.bottom' ? footer : body.querySelector(sel)),
    getElementById: (id) => (id === 'app' ? app : body.querySelectorAll(`[id="${id}"]`)[0] || null),
    addEventListener: () => {}, removeEventListener: () => {},
  };
  const record = () => ({ id: PID, title: 'AW drop', kind: 'project', deadline: M.card.deadline, summary: { attention: 'doing' }, attention: [],
    items: [], engineering: [], blockers: [], unknowns: [], facts: [], events: [{ at: '2026-09-29T09:00:00Z', by: 'owner', text: 'Opened' }], card: clone(M.card) });
  const respond = (status, data) => ({ status, ok: status < 300, json: async () => clone(data) });
  const fetch = async (url, init = {}) => {
    if (url.startsWith('/objectives?') || url === '/objectives') return respond(200, { objectives: [{ id: PID, title: 'AW drop', kind: 'project', attention: 'doing', needs_you: [], blocked_by: [], next: [], days_left: null, engineering: [] }], needs_you: 0 });
    if (url === '/objectives/gaps') return respond(200, { gaps: [], summary: {} });
    if (url === `/objectives/${PID}`) return respond(200, record());
    const answer = await M.send(url, JSON.parse(init.body));
    return respond(200, Object.assign(record(), answer));
  };
  const sandbox = {
    window: { CliveAlpha: { sessionId: () => 'conv_1', isBusy: () => false, ask: async () => {} } },
    document, console, fetch, Node: Object.getPrototypeOf(shim.Element.prototype).constructor,
    setTimeout: (fn, ms) => setTimeout(fn, ms), clearTimeout, setInterval: () => 0, confirm: () => true, encodeURIComponent,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  for (const file of ['objective-touch.js', 'objective-cards.js', 'alpha.js']) {
    vm.runInContext(fs.readFileSync(path.join(WEB, file), 'utf8'), sandbox, { filename: file });
  }
  const kit = sandbox.window.CliveObjectiveTouch;
  kit.clock = C;
  kit.vibrate = (p) => felt.push(p);
  await flush();
  body.querySelectorAll(`[data-objective="${PID}"]`).find((n) => n.getAttribute('data-alpha') === 'objective').dispatch('click');
  await flush();
  const sheet = body.querySelector('.alpha-sheet');
  const bar = sheet.querySelector('.ot-bar');
  assert.ok(bar && bar.parentNode === sheet, 'at the foot of the sheet, outside what scrolls');
  const stage = (i) => sheet.querySelectorAll('.oc-step')[i];
  stage(2).dispatch('click');
  C.advance(100);
  stage(2).dispatch('click');
  await flush();
  assert.deepEqual(M.asked, [[`/objectives/${PID}/stage`, { stage: 'Production' }]]);
  assert.equal(sheet.querySelector('.ot-bar'), bar, 'the same bar, kept through the sheet\'s redraw');
  assert.equal(sheet.childNodes[sheet.childNodes.length - 1], bar);
  assert.equal(words(bar.querySelector('.ot-bar-text')), 'Production is now');
  assert.equal(sheet.querySelectorAll('.oc-step')[2].getAttribute('aria-current'), 'step', 'drawn again from the Mac\'s answer');
  bar.querySelector('.ot-undo').dispatch('click');
  await flush();
  assert.deepEqual(M.asked[1], [`/objectives/${PID}/undo`, { token: 'tok-1' }]);
  assert.equal(sheet.querySelectorAll('.oc-step')[0].getAttribute('aria-current'), 'step', 'put back');
  assert.equal(words(bar.querySelector('.ot-bar-text')), 'Put back as it was before');
});

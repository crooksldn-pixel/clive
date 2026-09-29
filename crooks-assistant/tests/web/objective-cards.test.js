/* An objective drawn in the shape of its kind (web/objective-cards.js), under Node.
 *
 * Round 12: "telling clive that samples have started xyz shows the same as saying give [two of
 * the team] these tasks to do later." What is held: a project draws its stages as a progression
 * with the current one marked, delegated tasks draw grouped by person with a tick each, the two
 * are different cards; a tick is optimistic, asks the Mac, redraws from its answer and goes back
 * when refused; the home row carries each kind's shape; an objective with no design draws as it
 * always did; and every string from outside is text, never markup or an attribute.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
const OC = require(path.join(__dirname, '..', '..', 'web', 'objective-cards.js'));
const UI = require(path.join(__dirname, '..', '..', 'web', 'ui.js'));

const NOW = new Date(2026, 8, 29, 10, 0);   // 29 September 2026, the tablet's own clock
const HOSTILE = '<img src=x onerror="alert(1)"><script>alert(2)</script>';

const PROJECT = {
  objective_id: 'obj_1a2b3c4d', kind: 'project', title: 'AW drop', attention: 'doing',
  attention_reason: 'at Sampling · waiting on Northfield', deadline: '2026-11-14', days_left: 46,
  purpose: 'Stock for the AW launch', done_when: null, check_in: { every_days: 7, quiet_days: 2, due: false },
  people: [{ name: 'Northfield', role: 'factory' }], needs_you: [], blocked_by: [], doing: 'Sampling · waiting on Northfield', next: [],
  stages: [
    { id: 's_00000001', name: 'Sampling', state: 'current', due: null, waiting_on: 'Northfield', started_at: '2026-09-29T09:00:00Z', done_at: null },
    { id: 's_00000002', name: 'Approval', state: 'upcoming', due: '2026-10-09', waiting_on: 'you', started_at: null, done_at: null },
    { id: 's_00000003', name: 'Production', state: 'upcoming', due: null, waiting_on: null, started_at: null, done_at: null },
    { id: 's_00000004', name: 'Delivery', state: 'upcoming', due: null, waiting_on: null, started_at: null, done_at: null },
  ],
};

const TASKS = {
  objective_id: 'obj_5e6f7a8b', kind: 'tasks', title: "Rosa and Kit's tasks", attention: 'doing', attention_reason: '3 tasks open',
  deadline: null, days_left: null, check_in: null, people: [], needs_you: [], blocked_by: [], doing: null, next: [],
  groups: [
    { who: 'Rosa', open: 2, done: 0, more: 0, tasks: [
      { id: 't_00000001', text: 'Steam the AW samples', due: null, done: false },
      { id: 't_00000002', text: 'Photograph the swatches', due: '2026-09-28', done: false }] },
    { who: 'Kit', open: 1, done: 0, more: 0, tasks: [{ id: 't_00000003', text: 'Update the size chart', due: '2026-10-02', done: false }] },
  ],
};

const all = (node, cls) => node.querySelectorAll(`.${cls}`);
const one = (node, cls) => node.querySelector(`.${cls}`);
const words = (node) => (node ? node.allText() : '');

test('a project draws its stages in order on one rail, the one it is at marked current', () => {
  const card = OC.card(PROJECT, { now: NOW });
  assert.equal(card.dataset.type, 'objective');
  assert.ok(card.classList.contains('is-project'));
  assert.equal(words(one(card, 'card-kicker')), 'Project');
  assert.equal(words(one(card, 'oc-status')), 'Stage 1 of 4 · Due 14 Nov · 46 days left');
  const steps = all(card, 'oc-step');
  assert.deepEqual(steps.map((s) => s.className), ['oc-step is-current', 'oc-step is-upcoming', 'oc-step is-upcoming', 'oc-step is-upcoming']);
  assert.equal(steps[0].getAttribute('aria-current'), 'step');
  assert.equal(steps.filter((s) => s.getAttribute('aria-current')).length, 1, 'one current stage');
  assert.equal(words(one(steps[0], 'oc-step-name')), 'SamplingNow');
  assert.equal(words(one(steps[0], 'oc-step-sub')), 'Waiting on Northfield');
  assert.equal(words(one(steps[1], 'oc-step-sub')), 'Waiting on you · By 9 Oct');
  assert.deepEqual(all(card, 'oc-seg').map((s) => s.className), ['oc-seg is-current', 'oc-seg is-upcoming', 'oc-seg is-upcoming', 'oc-seg is-upcoming']);
  assert.equal(all(card, 'oc-group').length, 0, 'a project is not a to-do list');
  assert.match(words(one(card, 'oc-facts')), /WhyStock for the AW launch/);
  assert.match(words(one(card, 'oc-facts')), /WithNorthfield \(factory\)/);
  assert.match(words(one(card, 'oc-facts')), /Check inEvery week/);
});

test('a stage done carries its tick and when; a stage past its date says so', () => {
  const moved = JSON.parse(JSON.stringify(PROJECT));
  moved.stages[0] = { ...moved.stages[0], state: 'done', done_at: '2026-09-29T11:00:00Z' };
  moved.stages[1] = { ...moved.stages[1], state: 'current', due: '2026-09-25' };
  const card = OC.card(moved, { now: NOW });
  const steps = all(card, 'oc-step');
  assert.equal(steps[0].className, 'oc-step is-done');
  assert.equal(one(steps[0], 'oc-node').childNodes[0].tagName, 'SVG', 'the tick is drawn, as a path');
  assert.equal(words(one(steps[0], 'oc-step-sub')), 'Done 29 Sep');
  assert.equal(steps[1].className, 'oc-step is-current is-late');
  assert.equal(words(one(steps[1], 'oc-step-sub')), 'Waiting on you · Was due 25 Sep');
  assert.equal(words(one(card, 'oc-status')).split(' · ')[0], 'Stage 2 of 4');
});

test('delegated tasks draw grouped by person, each task a tick the width of its row', () => {
  const card = OC.card(TASKS, { now: NOW });
  assert.ok(card.classList.contains('is-tasks'));
  assert.equal(words(one(card, 'card-kicker')), 'Tasks');
  assert.equal(words(one(card, 'oc-status')), '0 of 3 done');
  assert.equal(all(card, 'oc-step').length, 0, 'tasks have no stages');
  const groups = all(card, 'oc-group');
  assert.deepEqual(groups.map((g) => words(one(g, 'oc-who'))), ['Rosa', 'Kit']);
  assert.deepEqual(groups.map((g) => words(one(g, 'oc-disc'))), ['RO', 'KI']);
  assert.deepEqual(groups.map((g) => words(one(g, 'oc-count'))), ['0 of 2 done', '0 of 1 done']);
  const ticks = all(card, 'oc-task');
  assert.equal(ticks.length, 3);
  for (const t of ticks) {
    assert.equal(t.tagName, 'BUTTON');
    assert.equal(t.getAttribute('role'), 'checkbox');
    assert.equal(t.getAttribute('aria-checked'), 'false');
    assert.ok(!t.disabled);
  }
  assert.equal(words(one(ticks[1], 'oc-due')), '28 Sep');
  assert.ok(ticks[1].classList.contains('is-late'), 'a task past its date is marked late');
  assert.equal(words(one(ticks[2], 'oc-due')), 'Fri 2 Oct', 'within the week: its day');
});

test('a tasks objective with every task taken off says so', () => {
  const empty = { ...TASKS, groups: [] };
  assert.equal(words(one(OC.card(empty, { now: NOW }), 'card-note')), 'No tasks on it.');
});

test('the two sentences draw two different cards', () => {
  const project = OC.card(PROJECT, { now: NOW });
  const tasks = OC.card(TASKS, { now: NOW });
  assert.ok(all(project, 'oc-steps').length === 1 && all(project, 'oc-tasks').length === 0);
  assert.ok(all(tasks, 'oc-tasks').length === 1 && all(tasks, 'oc-steps').length === 0);
});

test('a tick fills at once, asks the Mac, and the card is drawn again from its answer', async () => {
  const asked = [];
  let changed = null;
  const after = JSON.parse(JSON.stringify(TASKS));
  after.groups[0].tasks[0].done = true; after.groups[0].open = 1; after.groups[0].done = 1;
  after.groups[0].tasks.push(after.groups[0].tasks.shift());
  const card = OC.card(TASKS, {
    now: NOW,
    post: async (objective, task, done) => { asked.push([objective, task, done]); return { card: after }; },
    onChange: (record) => { changed = record; },
  });
  const first = all(card, 'oc-task')[0];
  first.dispatch('click');
  assert.equal(first.getAttribute('aria-checked'), 'true', 'filled before the Mac answers');
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(asked, [['obj_5e6f7a8b', 't_00000001', true]], 'only the task, its objective and done');
  assert.equal(changed.card, after);
  assert.equal(words(one(card, 'oc-status')), '1 of 3 done', 'the card was drawn again');
  const rosa = all(card, 'oc-group')[0];
  assert.equal(words(one(rosa, 'oc-count')), '1 of 2 done');
  assert.deepEqual(all(rosa, 'oc-task').map((t) => t.getAttribute('aria-checked')), ['false', 'true'], 'done goes to the bottom');
});

test('a tick the Mac refuses goes back and says why', async () => {
  const card = OC.card(TASKS, { now: NOW, post: async () => { throw new Error('There is no task on this objective.'); } });
  const first = all(card, 'oc-task')[0];
  first.dispatch('click');
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(first.getAttribute('aria-checked'), 'false');
  assert.ok(!first.classList.contains('is-done'));
  assert.equal(words(one(card, 'oc-error')), 'Not saved: There is no task on this objective.');
});

test('a tick posts the task and done to the owner\'s own route, and an unreachable CLIVE is said plainly', async () => {
  const sent = [];
  globalThis.fetch = async (url, init) => { sent.push([url, init.method, init.body]); return { ok: false, status: 400, json: async () => ({ detail: 'Refused.' }) }; };
  let card = OC.card(TASKS, { now: NOW });
  all(card, 'oc-task')[2].dispatch('click');
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(sent, [['/objectives/obj_5e6f7a8b/tasks/t_00000003', 'POST', '{"done":true}']]);
  assert.equal(words(one(card, 'oc-error')), 'Not saved: Refused.');
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
  card = OC.card(TASKS, { now: NOW });
  all(card, 'oc-task')[0].dispatch('click');
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(words(one(card, 'oc-error')), 'Not saved: CLIVE could not be reached');
  assert.equal(all(card, 'oc-task')[0].getAttribute('aria-checked'), 'false');
  delete globalThis.fetch;
});

test('a second tap while the first is on its way is not a second change', async () => {
  let calls = 0;
  let release;
  const card = OC.card(TASKS, { now: NOW, post: () => { calls += 1; return new Promise((r) => { release = r; }); } });
  const first = all(card, 'oc-task')[0];
  first.dispatch('click');
  first.dispatch('click');
  release({});
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(calls, 1);
});

test('a task with an id that is not a task id cannot be ticked', () => {
  const bad = JSON.parse(JSON.stringify(TASKS));
  bad.groups[0].tasks[0].id = '../../orders/1';
  const card = OC.card(bad, { now: NOW });
  assert.ok(all(card, 'oc-task')[0].disabled);
  assert.ok(!all(card, 'oc-task')[1].disabled);
});

test('every string from outside is text, and no attribute carries it', () => {
  const hostile = JSON.parse(JSON.stringify(PROJECT));
  hostile.title = HOSTILE; hostile.purpose = HOSTILE; hostile.people = [{ name: HOSTILE, role: HOSTILE }];
  hostile.stages[0].name = HOSTILE; hostile.stages[0].waiting_on = HOSTILE; hostile.needs_you = [HOSTILE];
  const tasks = JSON.parse(JSON.stringify(TASKS));
  tasks.groups[0].who = HOSTILE; tasks.groups[0].tasks[0].text = HOSTILE;
  for (const card of [OC.card(hostile, { now: NOW }), OC.card(tasks, { now: NOW })]) {
    assert.ok(words(card).includes(HOSTILE), 'shown as written');
    const walk = (node) => {
      if (node.nodeType !== 1) return;
      assert.notEqual(node.tagName, 'IMG');
      assert.notEqual(node.tagName, 'SCRIPT');
      for (const value of Object.values(node.attributes)) assert.ok(!String(value).includes('<'), `attribute ${value}`);
      for (const value of Object.values(node.dataset)) assert.ok(!String(value).includes('<'), `data ${value}`);
      node.childNodes.forEach(walk);
    };
    walk(card);
  }
});

test('the other kinds draw what CLIVE is doing and what is next; nothing for a field nobody filled', () => {
  const old = { objective_id: 'obj_0a0b0c0d', kind: 'business', title: 'Get the SS26 lookbook shot', deadline: '2026-10-14',
    doing: 'Shortlist three studios', next: ['Book the studio'], needs_you: ['Which models do you want?'], blocked_by: ['No studio-booking tool'],
    people: [], check_in: null };
  const card = OC.card(old, { now: NOW });
  assert.equal(words(one(card, 'card-kicker')), 'Objective');
  assert.equal(words(one(card, 'oc-status')), 'Due 14 Oct · 15 days left');
  assert.match(words(one(card, 'oc-work')), /Doing nowShortlist three studios/);
  assert.match(words(one(card, 'oc-work')), /NextBook the studio/);
  assert.match(words(one(card, 'oc-alerts')), /Needs youWhich models do you want\?/);
  assert.match(words(one(card, 'oc-alerts')), /BlockedNo studio-booking tool/);
  assert.equal(one(card, 'oc-facts'), null, 'no design, nothing drawn for it');
  // In the sheet, which lists CLIVE's work itself, an objective with no design adds nothing.
  assert.equal(OC.shape(old, { sheet: true, now: NOW }).childNodes.length, 0);
});

test('a check-in that has lapsed says so', () => {
  const quiet = { ...PROJECT, attention: 'check_in', check_in: { every_days: 7, quiet_days: 9, due: true } };
  const facts = one(OC.card(quiet, { now: NOW }), 'oc-facts');
  assert.match(words(facts), /Check inDue: no update for 9 days/);
  const row = OC.row({ kind: 'project', attention: 'check_in', check_in: quiet.check_in, stages: PROJECT.stages, stage: null });
  assert.equal(row.sub, 'Check in: no update for 9 days');
});

test('the home row carries the kind: a project its stage and progression, tasks each person', () => {
  const project = OC.row({ kind: 'project', attention: 'doing', stage: { name: 'Sampling', waiting_on: 'Northfield' },
    stages: [{ name: 'Sampling', state: 'current' }, { name: 'Approval', state: 'upcoming' }] });
  assert.equal(project.sub, 'Sampling · waiting on Northfield');
  assert.deepEqual(all(project.track, 'oc-seg').map((s) => s.className), ['oc-seg is-current', 'oc-seg is-upcoming']);
  const tasks = OC.row({ kind: 'tasks', attention: 'doing', people_tasks: [{ who: 'Rosa', open: 1, done: 1 }, { who: 'Kit', open: 0, done: 1 }] });
  assert.deepEqual(tasks, { sub: 'Rosa 1 of 2 · Kit done', track: null });
  assert.equal(OC.row({ kind: 'business', attention: 'idle' }), null, 'an older kind keeps the home\'s own row');
  const finished = OC.row({ kind: 'project', stage: null, stages: [{ name: 'A', state: 'done' }] });
  assert.equal(finished.sub, 'Every stage done');
});

test('ui.js draws the objective card through this file, and knows it by its objective', () => {
  const out = UI.render([{ type: 'objective', data: PROJECT }]);
  assert.equal(out.nodes.length, 1);
  assert.equal(out.nodes[0].dataset.type, 'objective');
  assert.equal(out.nodes[0].dataset.render, 'objective:obj_1a2b3c4d');
  assert.ok(out.hasContext, 'an objective is something the owner asked to see');
  assert.equal(UI.surfaceId({ type: 'objective', data: { objective_id: 'obj_1a2b3c4d' } }), 'objective:obj_1a2b3c4d');
});

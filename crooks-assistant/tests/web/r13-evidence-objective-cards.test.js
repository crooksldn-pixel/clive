/* W3-02 (round 12): two taps in a row on one task, under Node.
 *
 * Round 12's reviewer held web/objective-cards.js but not its callers, and could not tell whether a
 * second tap sends the task's new state or the one the button was drawn with: `toggle` redraws
 * only through `opts.onChange`, and a button that is not redrawn keeps the `done` it was made
 * with. What is held here: the conversation's card (ui.js `renderObjective` → `card`, which
 * always redraws itself from the Mac's answer) posts done, then not done, for two taps on the same
 * task, through the page's own `postTick` and the Mac's answer; the home sheet's one call of
 * `shape` in web/alpha.js hands it a redraw; and a shape drawn with no redraw at all sends the
 * same `done` again, which changes nothing on the Mac. Every name here is invented.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
const WEB = path.join(__dirname, '..', '..', 'web');
const OC = require(path.join(WEB, 'objective-cards.js'));
globalThis.CliveObjectiveCards = OC;
const UI = require(path.join(WEB, 'ui.js'));

const NOW = new Date(2026, 8, 29, 10, 0);
const OBJECTIVE = 'obj_5e6f7a8b';
const TASK = 't_00000001';
const TASKS = {
  objective_id: OBJECTIVE, kind: 'tasks', title: "Rosa and Kit's tasks", attention: 'doing', attention_reason: '3 tasks open',
  deadline: null, days_left: null, check_in: null, people: [], needs_you: [], blocked_by: [], doing: null, next: [],
  groups: [
    { who: 'Rosa', open: 2, done: 0, more: 0, tasks: [
      { id: TASK, text: 'Steam the AW samples', due: null, done: false },
      { id: 't_00000002', text: 'Photograph the swatches', due: null, done: false }] },
    { who: 'Kit', open: 1, done: 0, more: 0, tasks: [{ id: 't_00000003', text: 'Update the size chart', due: null, done: false }] },
  ],
};

const settle = () => new Promise((r) => setTimeout(r, 0));
const taskButton = (root, text) => root.querySelectorAll('.oc-task').find((b) => b.allText().includes(text));

// The Mac, as far as a tick goes: it keeps the task's state and answers with the whole record and
// the card drawn from it, as `app/routes/objectives.py` `_full` does.
function mac() {
  const state = JSON.parse(JSON.stringify(TASKS));
  const asked = [];
  const answer = (objective, task, done) => {
    asked.push([objective, task, done]);
    for (const group of state.groups) {
      for (const t of group.tasks) if (t.id === task) t.done = done;
      group.done = group.tasks.filter((t) => t.done).length;
      group.open = group.tasks.length - group.done;
    }
    return { id: objective, card: JSON.parse(JSON.stringify(state)) };
  };
  return { asked, answer };
}

test('two taps in a row on a conversation card post done, then not done (W3-02)', async () => {
  const shop = mac();
  const sent = [];
  globalThis.fetch = async (url, init) => {
    sent.push([url, init.method, init.body]);
    const [, objective, task] = url.match(/^\/objectives\/([^/]+)\/tasks\/([^/]+)$/);
    const body = shop.answer(decodeURIComponent(objective), decodeURIComponent(task), JSON.parse(init.body).done);
    return { ok: true, status: 200, json: async () => body };
  };
  try {
    const drawn = UI.render([{ type: 'objective', data: TASKS }], { now: NOW });
    const card = drawn.nodes[0];
    taskButton(card, 'Steam the AW samples').dispatch('click');
    await settle();
    assert.equal(taskButton(card, 'Steam the AW samples').getAttribute('aria-checked'), 'true', 'drawn again as done');
    taskButton(card, 'Steam the AW samples').dispatch('click');
    await settle();
    assert.deepEqual(sent.map((s) => s[2]), ['{"done":true}', '{"done":false}']);
    assert.deepEqual(shop.asked, [[OBJECTIVE, TASK, true], [OBJECTIVE, TASK, false]]);
    assert.equal(taskButton(card, 'Steam the AW samples').getAttribute('aria-checked'), 'false', 'and back to not done');
  } finally {
    delete globalThis.fetch;
  }
});

test('three taps on the card itself, the Mac answering each, alternate done and not done (W3-02)', async () => {
  const shop = mac();
  const card = OC.card(TASKS, { now: NOW, post: async (objective, task, done) => shop.answer(objective, task, done) });
  for (let i = 0; i < 3; i += 1) {
    taskButton(card, 'Steam the AW samples').dispatch('click');
    await settle();
  }
  assert.deepEqual(shop.asked.map((a) => a[2]), [true, false, true]);
});

test('the home sheet hands its shape a redraw on every tick (W3-02)', () => {
  const alpha = fs.readFileSync(path.join(WEB, 'alpha.js'), 'utf8');
  const calls = alpha.match(/cards\.shape\([^\n]*/g) || [];
  assert.equal(calls.length, 1, 'the sheet is the one place alpha.js draws a shape');
  assert.match(calls[0], /onChange: \(record\) => \{ drawObjective\(record, true\); refresh\(\); \}/);
  const drawn = alpha.match(/function drawObjective\(o, keepScroll\) \{[\s\S]*?\n {2}\}\n/);
  assert.ok(drawn && drawn[0].includes('cards.shape(o.card'), 'drawObjective draws the shape from the record it is given');
});

test('a shape drawn with no redraw sends the same done again, which changes nothing (W3-02)', async () => {
  const shop = mac();
  const body = OC.shape(TASKS, { now: NOW, post: async (objective, task, done) => shop.answer(objective, task, done) });
  const button = taskButton(body, 'Steam the AW samples');
  button.dispatch('click');
  await settle();
  button.dispatch('click');
  await settle();
  assert.deepEqual(shop.asked.map((a) => a[2]), [true, true], 'the button keeps the state it was drawn with');
  assert.equal(button.getAttribute('aria-checked'), 'true', 'and says what the Mac holds');
});

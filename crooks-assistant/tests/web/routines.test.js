/* Named routines' drawings (web/routines.js) through the renderer (web/ui.js), under Node (DEC-074).
 *
 * What they must hold: the list names each routine with how many steps and changes it has; a saved
 * routine shows its steps in order, a change with a hollow blue ring and the words that it will wait
 * for him; a run shows each step as this turn left it, with a dot that means something (quiet: a read
 * that ran; blue: a change waiting on its card; red: failed; orange: skipped or not done) and the
 * counts under the title; nothing on the card is tappable or carries data in an attribute; and every
 * string arrives as text.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
globalThis.CliveRoutines = require(path.join(__dirname, '..', '..', 'web', 'routines.js'));
const UI = require(path.join(__dirname, '..', '..', 'web', 'ui.js'));

const HOSTILE = '<img src=x onerror="alert(1)">';

const LIST = {
  type: 'routine',
  data: {
    view: 'list', title: 'Routines', said: '',
    routines: [
      { name: 'Friday drop', count: 4, changes: 1, says: ["This week's orders", 'Stock of the hoodies', 'Who is waiting on a reply'], more: 1 },
      { name: 'Monday check', count: 1, changes: 0, says: ["Today's orders"], more: 0 },
    ],
  },
};
const ONE = {
  type: 'routine',
  data: {
    view: 'one', title: 'Friday drop', said: 'Saved', looked_up: true,
    steps: [
      { n: 1, say: "This week's orders", kind: 'read' },
      { n: 2, say: "Tag the newest unfulfilled order 'friday-drop'", kind: 'change' },
    ],
  },
};
const RUN = {
  type: 'routine',
  data: {
    view: 'run', title: 'Friday drop',
    counts: { done: 2, waiting: 1, failed: 1, skipped: 1, not_done: 1, pending: 0 },
    steps: [
      { n: 1, say: "This week's orders", kind: 'read', state: 'done' },
      { n: 2, say: 'Stock of the hoodies', kind: 'read', state: 'done' },
      { n: 3, say: "Tag the newest unfulfilled order 'friday-drop'", kind: 'change', state: 'waiting' },
      { n: 4, say: 'Who is waiting on a reply', kind: 'read', state: 'failed' },
      { n: 5, say: 'Track the parcel', kind: 'read', state: 'skipped', why: 'that part of CLIVE is not connected right now' },
      { n: 6, say: 'Put the sales on the studio screen', kind: 'read', state: 'not_done' },
    ],
  },
};

function all(node, cls) { return node.querySelectorAll(`.${cls}`); }
const has = (node, cls) => node.classList.contains(cls);

test('the list names each routine with its steps and changes', () => {
  const out = UI.render([LIST]);
  assert.equal(out.nodes.length, 1);
  const card = out.nodes[0];
  assert.equal(card.dataset.type, 'routine');
  const text = card.allText();
  assert.match(text, /Routines/);
  assert.match(text, /2 routines saved/);
  const rows = all(card, 'rn-row');
  assert.equal(rows.length, 2);
  assert.match(rows[0].allText(), /Friday drop/);
  assert.match(rows[0].allText(), /4 steps, 1 change/);
  assert.match(rows[0].allText(), /This week's orders · Stock of the hoodies · Who is waiting on a reply · and 1 more/);
  assert.match(rows[1].allText(), /1 step/);
  assert.doesNotMatch(rows[1].allText(), /change/);
});

test('an empty list says none are saved, and draws no rows', () => {
  const card = UI.render([{ type: 'routine', data: { view: 'list', routines: [], said: 'Forgot Friday drop' } }]).nodes[0];
  assert.match(card.allText(), /Forgot Friday drop\. None saved yet/);
  assert.equal(all(card, 'rn-row').length, 0);
});

test('a saved routine shows its steps in order, a change ringed blue and saying it will wait for him', () => {
  const card = UI.render([ONE]).nodes[0];
  assert.match(card.allText(), /Friday drop/);
  assert.match(card.allText(), /Saved\. 2 steps, 1 change/);
  const rows = all(card, 'rn-row');
  assert.equal(rows.length, 2);
  assert.ok(has(rows[0], 'is-read') && has(rows[1], 'is-change'));
  assert.match(rows[0].allText(), /1\s*This week's orders/);
  assert.equal(all(rows[0], 'rn-state').length, 0, 'a read needs no words about waiting');
  assert.match(all(rows[1], 'rn-state')[0].allText(), /A change: waits for you on its card/);
  assert.match(card.allText(), /No id is kept: each run looks its records up again from the step's words\./);
});

test('a run shows each step as the turn left it, each dot meaning one thing', () => {
  const card = UI.render([RUN]).nodes[0];
  assert.match(card.allText(), /Ran: 2 done · 1 waiting for you · 1 failed · 1 skipped · 1 not done/);
  const rows = all(card, 'rn-row');
  assert.deepEqual(rows.map((r) => ['is-quiet', 'is-ask', 'is-bad', 'is-warn'].find((c) => has(r, c))),
    ['is-quiet', 'is-quiet', 'is-ask', 'is-bad', 'is-warn', 'is-warn']);
  assert.match(all(rows[2], 'rn-state')[0].allText(), /Waiting for you on its card/);
  assert.match(all(rows[3], 'rn-state')[0].allText(), /Could not be done/);
  assert.match(all(rows[4], 'rn-state')[0].allText(), /Skipped: that part of CLIVE is not connected right now/);
  assert.match(all(rows[5], 'rn-state')[0].allText(), /Not done/);
});

test('a step that acts at once says what it changes, saved and run, never "Done" as if it were a lookup', () => {
  const saved = UI.render([{ type: 'routine', data: { view: 'one', title: 'Office', said: 'Saved', steps: [
    { n: 1, say: 'The plan on the office TV', kind: 'acts', does: 'Puts it on the Office TV each run' },
    { n: 2, say: "Today's orders", kind: 'read' },
  ] } }]).nodes[0];
  const rows = all(saved, 'rn-row');
  assert.ok(has(rows[0], 'is-acts') && has(rows[1], 'is-read'));
  assert.equal(all(rows[0], 'rn-state')[0].allText(), 'Puts it on the Office TV each run');
  const ran = UI.render([{ type: 'routine', data: { view: 'run', title: 'Office', counts: { done: 1, acted: 1 }, steps: [
    { n: 1, say: 'The plan on the office TV', kind: 'acts', state: 'acted', did: 'Put on the Office TV' },
    { n: 2, say: "Today's orders", kind: 'read', state: 'done' },
  ] } }]).nodes[0];
  assert.match(ran.allText(), /Ran: 1 done · 1 changed at once/);
  const done = all(ran, 'rn-row');
  assert.ok(has(done[0], 'is-acts') && has(done[1], 'is-quiet'));
  assert.equal(all(done[0], 'rn-state')[0].allText(), 'Put on the Office TV');
  assert.doesNotMatch(done[0].allText(), /Done|read/i);
});

test('a step whose state is not one the card knows is drawn as not done, never as done', () => {
  const card = UI.render([{ type: 'routine', data: { ...RUN.data, steps: [{ n: 1, say: 'x', kind: 'read', state: 'magic' }] } }]).nodes[0];
  const row = all(card, 'rn-row')[0];
  assert.ok(has(row, 'is-warn'));
  assert.match(row.allText(), /Not done/);
});

test('nothing is tappable and no attribute carries what the Mac sent', () => {
  for (const item of [LIST, ONE, RUN]) {
    const card = UI.render([item]).nodes[0];
    for (const row of all(card, 'rn-row')) {
      assert.ok(!has(row, 'tappable'));
      assert.equal(row.getAttribute('role'), null);
      assert.deepEqual(Object.keys(row.dataset), []);
    }
  }
});

test('every string arrives as text', () => {
  const hostile = {
    type: 'routine',
    data: { view: 'run', title: HOSTILE, counts: { done: 1 }, steps: [{ n: HOSTILE, say: HOSTILE, kind: 'read', state: 'skipped', why: HOSTILE }] },
  };
  const card = UI.render([hostile]).nodes[0];
  assert.ok(card.allText().includes(HOSTILE));
  assert.equal(card.querySelectorAll('img').length, 0);
  const list = UI.render([{ type: 'routine', data: { view: 'list', routines: [{ name: HOSTILE, count: 1, says: [HOSTILE] }] } }]).nodes[0];
  assert.ok(list.allText().includes(HOSTILE));
  assert.equal(list.querySelectorAll('img').length, 0);
});

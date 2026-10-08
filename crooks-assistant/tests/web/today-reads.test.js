/* Today reads its work list one read at a time, and abandons one kept waiting a minute (web/today.js),
 * under Node.
 *
 * The re-review of staff links (R1, 8 October): through the team's door a read of /today/state can
 * carry the phone's renewed sign-in (app/people/links.py check). The page polled every 30 seconds
 * whether or not the last read had come back, so an answer held up in the network for minutes could
 * land after a later read's newer sign-in and put an honest phone back on one it had moved past,
 * which CLIVE takes for a copy. What is held here: a poll never starts while a read is on its way;
 * any other load waits for it and is then made once (fresh if any of them asked for fresh); and a
 * read not answered within READ_LIMIT_MS is abandoned through its AbortSignal, after which the next
 * poll may read again. tests/test_staff_links.py replays the reviewer's held-answer case against the
 * real server with this page's rule.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.window = globalThis;
const stand = { textContent: '', value: '', hidden: false, classList: { contains: () => false, add() {}, remove() {}, toggle() {} } };
globalThis.document = Object.assign(shim.document, {
  addEventListener() {}, visibilityState: 'visible', querySelector: () => stand,
});
globalThis.location = { hostname: 'team.example.test', replace() {} };

// Every fetch the page makes, held until the test answers it (or the page abandons it).
const asked = [];
globalThis.fetch = (url, init) => new Promise((resolve, reject) => {
  const held = { url, init, answer: (body) => resolve({ ok: true, status: 200, json: async () => body }) };
  if (init && init.signal) init.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
  asked.push(held);
});
require(path.join(__dirname, '..', '..', 'web', 'today.js'));
const { load, poll } = globalThis.CliveToday;

// An answer that ends the read at once: the phone is not signed in (the page goes to /join).
const SIGNED_OUT = { ok: false, code: 'signed_out' };
const settle = () => new Promise((resolve) => setImmediate(resolve));

test('a poll never starts a second read while one is on its way, and other loads wait and are made once', async () => {
  asked.length = 0;
  const first = load();
  assert.equal(asked.length, 1);
  assert.equal(asked[0].url, '/today/state');
  const after = [load(), load(true), load()];
  await settle();
  assert.equal(asked.length, 1, 'no second read while the first is out');
  for (let i = 0; i < 3; i++) poll();
  await settle();
  assert.equal(asked.length, 1, 'and no poll starts one either');
  asked[0].answer(SIGNED_OUT);
  assert.equal(await first, false);
  await settle();
  assert.equal(asked.length, 2, 'the loads asked for meanwhile are made as one read');
  assert.equal(asked[1].url, '/today/state?fresh=true');
  poll();
  await settle();
  assert.equal(asked.length, 2, 'and a poll waits for that one too');
  asked[1].answer(SIGNED_OUT);
  assert.deepEqual(await Promise.all(after), [false, false, false]);
  await settle();
  assert.equal(asked.length, 2);
});

test('a read not answered within a minute is abandoned, and the next poll reads again', async () => {
  asked.length = 0;
  // The page's own timers, caught: the one it sets for the read, fired by hand.
  const timers = [];
  const real = { set: globalThis.setTimeout, clear: globalThis.clearTimeout };
  globalThis.setTimeout = (fn, ms) => { timers.push({ fn, ms }); return { held: timers.length }; };
  globalThis.clearTimeout = () => {};
  let waiting;
  try {
    waiting = load();
  } finally {
    globalThis.setTimeout = real.set;
    globalThis.clearTimeout = real.clear;
  }
  assert.equal(asked.length, 1);
  const signal = asked[0].init.signal;
  assert.ok(signal, 'the read can be abandoned');
  assert.deepEqual(timers.map((t) => t.ms), [60000], 'after READ_LIMIT_MS');
  await settle();
  assert.equal(signal.aborted, false);
  timers[0].fn();
  assert.equal(signal.aborted, true, 'abandoned when its minute is up');
  assert.equal(await waiting, false);
  poll();
  assert.equal(asked.length, 2, 'the next poll reads again');
  asked[1].answer(SIGNED_OUT);
  await settle();
});

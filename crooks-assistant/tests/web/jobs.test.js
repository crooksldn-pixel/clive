/* The work in flight, run under Node (node --test tests/web/jobs.test.js).
 *
 * V0.5 slice C: independent jobs inside ONE session, each named, each finishing when it
 * finishes. The tests the contract's evidence gate asks for by name live here —
 * out-of-order completion, one job failing while the others carry on — together with the
 * two rules that keep the strip honest: a retry is offered only where re-running is safe,
 * and the strip disappears rather than becoming a dashboard.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
const JOBS = require(path.join(__dirname, '..', '..', 'web', 'jobs.js'));

function board() {
  let t = 1000;
  const changes = [];
  const j = JOBS.create({ now: () => t, onChange: (visible, why) => changes.push({ n: visible.length, why }) });
  return { j, changes, tick: (ms) => { t += ms; } };
}

function strip() {
  const container = shim.document.createElement('div');
  container.ownerDocument = shim.document;
  return container;
}

const labels = (list) => list.map((job) => job.label);
const states = (list) => list.map((job) => job.state);

test('a job is a verb and an object, in the owner’s words', () => {
  const b = board();
  b.j.start('orders', 'Checking', "today's orders");
  assert.deepEqual(labels(b.j.visible()), ["Checking today's orders"]);
  assert.deepEqual(states(b.j.visible()), ['WORKING']);
});

test('the same work reported twice is one job, updated in place', () => {
  const b = board();
  b.j.queue('orders', 'Checking', "today's orders");
  b.j.start('orders', 'Checking', "today's orders");
  b.j.start('orders', 'Checking', "today's orders");
  assert.equal(b.j.size, 1, 'a strip is a list of work, not a scrolling log');
  assert.equal(b.j.get('orders').state, 'WORKING');
});

test('a later report does not erase what an earlier one already said', () => {
  const b = board();
  b.j.start('email', 'Checking', 'customer email');
  b.j.done('email', '2 waiting');
  b.j.note('email', { object: 'customer email' });
  assert.equal(b.j.get('email').summary, '2 waiting');
});

test('independent jobs finish in any order and the strip says so', () => {
  const b = board();
  b.j.start('orders', 'Checking', "today's orders");
  b.j.start('email', 'Checking', 'customer email');
  b.j.queue('packing', 'Preparing', 'packing list');

  b.tick(400);
  b.j.done('email', '2 waiting');     // the SECOND job finishes first
  assert.deepEqual(states(b.j.visible()), ['WORKING', 'DONE', 'QUEUED']);

  b.tick(900);
  b.j.done('orders', '14 today');
  assert.deepEqual(states(b.j.visible()), ['DONE', 'DONE', 'QUEUED']);
  assert.equal(b.j.running(), 1, 'the queued one is still work nobody has done');
});

test('one job failing leaves every other job exactly as it was', () => {
  const b = board();
  b.j.start('orders', 'Checking', "today's orders");
  b.j.start('email', 'Checking', 'customer email');
  b.j.fail('email', 'Gmail did not answer', true);
  assert.equal(b.j.get('orders').state, 'WORKING', 'a failure is not a turn-wide catastrophe');
  b.j.done('orders', '14 today');
  assert.deepEqual(states(b.j.visible()), ['DONE', 'FAILED']);
  assert.equal(b.j.get('email').reason, 'Gmail did not answer');
});

test('a finished job is finished: a late poll cannot reopen it', () => {
  const b = board();
  b.j.start('orders', 'Checking', "today's orders");
  b.j.done('orders', '14 today');
  b.j.note('orders', { state: 'WORKING' });
  assert.equal(b.j.get('orders').state, 'DONE');
  b.j.note('orders', { state: 'FAILED' });
  assert.equal(b.j.get('orders').state, 'DONE', 'and a late failure cannot either');
});

test('a completed job collapses once its result is on screen, and not before', () => {
  const b = board();
  b.j.start('orders', 'Checking', "today's orders");
  b.j.done('orders', '14 today');
  assert.equal(b.j.visible().length, 1, 'a result nobody can see yet is not a result');
  assert.ok(b.j.represent('orders'));
  assert.equal(b.j.visible().length, 0, 'the scene shows it; the strip need not');
  assert.equal(b.j.size, 1, 'it is collapsed, not forgotten');
});

test('work that is still running can never be collapsed', () => {
  const b = board();
  b.j.start('orders', 'Checking', "today's orders");
  assert.equal(b.j.represent('orders'), false);
  assert.equal(b.j.visible().length, 1);
});

test('a failure stays on screen even once the scene has its result', () => {
  const b = board();
  b.j.start('email', 'Checking', 'customer email');
  b.j.fail('email', 'Gmail did not answer', true);
  b.j.represent('email');
  assert.equal(b.j.visible().length, 1, 'a failure nobody has read is not finished');
  assert.ok(b.j.dismiss('email'));
  assert.equal(b.j.visible().length, 0);
});

test('the strip is not a dashboard: the turn ending clears what is finished', () => {
  const b = board();
  b.j.start('orders', 'Checking', "today's orders");
  b.j.start('email', 'Checking', 'customer email');
  b.j.start('packing', 'Preparing', 'packing list');
  b.j.done('orders', '14 today');
  b.j.fail('email', 'Gmail did not answer', true);
  b.j.endTurn();
  assert.deepEqual(labels(b.j.visible()), ['Checking customer email', 'Preparing packing list']);
  assert.equal(b.j.get('orders'), null, 'done work does not accumulate');
});

test('a job outlives the question that started it', () => {
  const b = board();
  b.j.start('packing', 'Preparing', 'packing list');
  b.j.endTurn();
  assert.equal(b.j.get('packing').state, 'WORKING', 'invariant 5: it is still being done');
});

test('a retry is offered for a read, and refused for anything that changes the shop', () => {
  const b = board();
  b.j.start('orders', 'Checking', "today's orders");
  b.j.note('orders', { state: 'FAILED', reason: 'Shopify timed out', retryable: true });
  assert.equal(b.j.get('orders').retryable, true);

  b.j.start('reply', 'Sending', 'the reply');
  b.j.note('reply', { state: 'FAILED', reason: 'Gmail refused', retryable: true, writes: true });
  assert.equal(b.j.get('reply').retryable, false, 'this file has no authority to re-run a write');
});

test('a job remembers that it writes, so a later failure cannot make a refund re-runnable', () => {
  const b = board();
  // Declared once, where the work starts — which is where the page actually knows it.
  b.j.note('refund', { verb: 'Refunding', object: 'the order', state: 'WORKING', writes: true });
  assert.equal(b.j.get('refund').writes, true);
  // And the failure, reported later by something that has long forgotten, says only "retry".
  b.j.fail('refund', 'Shopify refused', true);
  assert.equal(b.j.get('refund').retryable, false);
});

test('a read stays a read: a later report cannot turn one into a write', () => {
  const b = board();
  b.j.note('orders', { verb: 'Checking', object: "today's orders", state: 'WORKING', writes: false });
  b.j.fail('orders', 'Shopify timed out', true);
  assert.equal(b.j.get('orders').retryable, true);
});

test('a label that will not fit one line is cut, never wrapped into a paragraph', () => {
  const b = board();
  b.j.start('long', 'Checking', 'every order placed by every customer since the shop opened');
  const { label } = b.j.get('long');
  assert.ok(label.length <= JOBS.MAX_LABEL, label);
  assert.ok(label.endsWith('…'));
});

test('the board refuses to grow past a stripful of work', () => {
  const b = board();
  for (let i = 0; i < JOBS.MAX_JOBS + 6; i += 1) b.j.start(`job${i}`, 'Checking', `thing ${i}`);
  assert.equal(b.j.size, JOBS.MAX_JOBS);
});

test('every change announces what the strip should now show', () => {
  const b = board();
  b.j.start('orders', 'Checking', "today's orders");
  b.j.done('orders', '14 today');
  b.j.represent('orders');
  assert.deepEqual(b.changes, [
    { n: 1, why: 'note' }, { n: 1, why: 'note' }, { n: 0, why: 'represented' },
  ]);
});

test('a renderer that throws never stops the work', () => {
  const j = JOBS.create({ now: () => 0, onChange: () => { throw new Error('the strip blew up'); } });
  j.start('orders', 'Checking', "today's orders");
  assert.equal(j.get('orders').state, 'WORKING');
});

/* ------------------------------------------------------------------- the strip */

test('the strip draws one line per job, and hides itself when there is none', () => {
  const b = board();
  const container = strip();

  assert.equal(JOBS.render(container, b.j.visible()), 0);
  assert.equal(container.hidden, true, 'no work is no surface');

  b.j.start('orders', 'Checking', "today's orders");
  b.j.queue('packing', 'Preparing', 'packing list');
  JOBS.render(container, b.j.visible());
  assert.equal(container.hidden, false);
  const rows = container.querySelectorAll('.job');
  assert.equal(rows.length, 2);
  assert.equal(rows[0].dataset.state, 'working');
  assert.equal(rows[1].dataset.state, 'queued');
  assert.ok(rows[0].allText().includes("Checking today's orders"));
});

test('the strip says what a job produced, and what a failure was', () => {
  const b = board();
  const container = strip();
  b.j.start('orders', 'Checking', "today's orders");
  b.j.done('orders', '14 today, 3 unfulfilled');
  b.j.start('email', 'Checking', 'customer email');
  b.j.fail('email', 'Gmail did not answer', true);
  JOBS.render(container, b.j.visible());
  const rows = container.querySelectorAll('.job');
  assert.ok(rows[0].allText().includes('14 today, 3 unfulfilled'));
  assert.ok(rows[1].allText().includes('Gmail did not answer'));
});

test('a done job with nothing to say says "done" rather than inventing a result', () => {
  const b = board();
  const container = strip();
  b.j.start('orders', 'Checking', "today's orders");
  b.j.done('orders');
  JOBS.render(container, b.j.visible());
  assert.equal(container.querySelector('.job-tail').textContent, 'done');
});

test('a retry appears only where re-running is safe, and it names its job', () => {
  const b = board();
  const container = strip();
  const retried = [];
  b.j.start('orders', 'Checking', "today's orders");
  b.j.note('orders', { state: 'FAILED', reason: 'Shopify timed out', retryable: true });
  b.j.start('reply', 'Sending', 'the reply');
  b.j.note('reply', { state: 'FAILED', reason: 'Gmail refused', retryable: true, writes: true });

  JOBS.render(container, b.j.visible(), { onRetry: (id) => retried.push(id) });
  const buttons = container.querySelectorAll('.job-retry');
  assert.equal(buttons.length, 1, 'exactly one of these two may be re-run from here');
  assert.equal(buttons[0].getAttribute('aria-label'), "Try again: Checking today's orders");
  buttons[0].dispatch('click');
  assert.deepEqual(retried, ['orders']);
});

test('no retry is drawn when the page offers nowhere for it to go', () => {
  const b = board();
  const container = strip();
  b.j.start('orders', 'Checking', "today's orders");
  b.j.note('orders', { state: 'FAILED', reason: 'Shopify timed out', retryable: true });
  JOBS.render(container, b.j.visible());
  assert.equal(container.querySelectorAll('.job-retry').length, 0);
});

test('redrawing replaces the strip rather than appending to it', () => {
  const b = board();
  const container = strip();
  b.j.start('orders', 'Checking', "today's orders");
  JOBS.render(container, b.j.visible());
  JOBS.render(container, b.j.visible());
  JOBS.render(container, b.j.visible());
  assert.equal(container.querySelectorAll('.job').length, 1);
  assert.equal(container.children.length, 1);
});

test('the strip never carries a tool name', () => {
  const b = board();
  const container = strip();
  b.j.start('shopify_list_orders', 'Checking', "today's orders");
  b.j.start('gmail_search', 'Checking', 'customer email');
  JOBS.render(container, b.j.visible());
  const text = container.allText();
  for (const leak of ['shopify_', 'gmail_', '_search', '_list_']) {
    assert.ok(!text.includes(leak), `the strip says ${leak}`);
  }
});

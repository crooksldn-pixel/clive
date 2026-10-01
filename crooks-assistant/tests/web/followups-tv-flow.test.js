/* The screen flow's verdict (the 2026-09-30 deploy review, SC1-01).
 *
 * scripts/browser/tv_flow.js used to report ok whenever nothing threw: page errors recorded along
 * the way, a new view that never became readable (ready_ms null) and a change slower than the
 * limit it claims all passed. Its verdict is a function now, of the report alone, and this holds
 * it to each of those without a browser. Run by tests/test_followups_harness.py under Node.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const flow = require(path.join(__dirname, '..', '..', 'scripts', 'browser', 'tv_flow.js'));

function result(step, extra) {
  return Object.assign({ mode: 'full', step, replace: true, ready_ms: 900, limit_ms: flow.READY_MS }, extra || {});
}

function report(extra) {
  return Object.assign({
    results: [
      result('first', { replace: false, limit_ms: null, ready_ms: 1200 }),
      result('order-to-order'),
      result('off', { replace: false, limit_ms: null, ready_ms: 3100 }),
    ],
    errors: [],
  }, extra || {});
}

test('a walk with every change readable in time and nothing recorded wrong is ok', () => {
  const v = flow.verdict(report());
  assert.equal(v.ok, true, v.why.join('; '));
  assert.deepEqual(v.why, []);
});

test('any page error recorded fails it, though nothing threw', () => {
  const v = flow.verdict(report({ errors: ['full: Cannot read properties of null (reading \'hidden\')'] }));
  assert.equal(v.ok, false);
  assert.match(v.why.join('\n'), /Cannot read properties of null/);
});

test('a change that never became readable fails it', () => {
  const r = report();
  r.results[1].ready_ms = null;
  const v = flow.verdict(r);
  assert.equal(v.ok, false);
  assert.match(v.why.join('\n'), /full order-to-order: never became readable/);
});

test('the first view or the screen going home never becoming readable fails it too', () => {
  const r = report();
  r.results[2].ready_ms = null;
  const v = flow.verdict(r);
  assert.equal(v.ok, false);
  assert.match(v.why.join('\n'), /full off: never became readable/);
});

test('a measured time over the limit its result claims fails it', () => {
  const r = report();
  r.results[1].ready_ms = flow.READY_MS + 1;
  const v = flow.verdict(r);
  assert.equal(v.ok, false);
  assert.match(v.why.join('\n'), new RegExp(`readable after ${flow.READY_MS + 1} ms, over its limit of ${flow.READY_MS} ms`));
});

test('exactly at the limit is within it', () => {
  const r = report();
  r.results[1].ready_ms = flow.READY_MS;
  assert.equal(flow.verdict(r).ok, true);
});

test('a report with nothing measured is not ok', () => {
  const v = flow.verdict({ results: [], errors: [] });
  assert.equal(v.ok, false);
  assert.match(v.why.join('\n'), /nothing was measured/);
});

test('the limit is the one tests/test_tv_flow.py holds the walk to, and the walk names its changes', () => {
  assert.equal(flow.READY_MS, 2500);
  assert.deepEqual(flow.WALK.full.map((s) => s.name), [
    'first', 'order-to-order', 'order-to-objective', 'objective-to-list', 'list-to-video',
    'beside-the-video', 'video-to-order', 'two-to-one', 'off',
  ]);
  assert.deepEqual(flow.WALK.short.map((s) => s.name), ['first', 'order-to-order', 'order-to-video', 'video-to-order', 'off']);
});

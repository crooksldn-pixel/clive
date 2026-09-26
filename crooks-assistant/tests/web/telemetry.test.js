/* The tablet's telemetry (web/telemetry.js) under Node: off, it records nothing; on, it
 * batches, never blocks, bounds what it keeps, and reads the screen as structure — card
 * types, tabs, rail chips, surfaces — never as text. Nothing here is sent anywhere. */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
globalThis.document.body = shim.document.createElement('body');
globalThis.document.documentElement = shim.document.createElement('html');
globalThis.innerWidth = 800;
globalThis.innerHeight = 1280;
globalThis.devicePixelRatio = 1;
const T = require(path.join(__dirname, '..', '..', 'web', 'telemetry.js'));
const UI = require(path.join(__dirname, '..', '..', 'web', 'ui.js'));

function capture() {
  const batches = [];
  T._setTransport((body, unloading) => batches.push({ body: JSON.parse(body), unloading }));
  return batches;
}

test('off, nothing is recorded and nothing is queued', () => {
  T.reset();
  capture();
  assert.equal(T.record('render', { screen: 'orb' }), null);
  assert.equal(T.status().queued, 0);
  assert.equal(T.configure({ test_session: null }), false);
  assert.equal(T.record('render', { screen: 'orb' }), null);
});

test('a session on the Mac turns it on, from /health or from a /turn answer, and off again', () => {
  T.reset();
  const batches = capture();
  assert.equal(T.configure({ test_session: 'ts-1', name: 'first hour' }), true);
  const joined = T.status();
  assert.equal(joined.enabled, true);
  assert.equal(joined.queued, 1, 'joining is itself an event');
  T.setContext({ session_id: 's1', turn_id: 'turn_a' });
  const event = T.record('tab', { label: 'Items', kind: 'not this', seq: 999, t: 1 });
  assert.equal(event.session_id, 's1');
  assert.equal(event.turn_id, 'turn_a');
  assert.equal(event.kind, 'tab');
  assert.ok(event.t > 0 && event.seq === 2);
  assert.equal(T.flush(false), true);
  assert.equal(batches.length, 1);
  assert.deepEqual(batches[0].body.events.map((e) => e.kind), ['session_joined', 'tab']);
  assert.equal(batches[0].body.session_id, 's1');
  assert.equal(batches[0].body.test_session_id, 'ts-1');
  assert.equal(T.configure({ test_session: null }), false);
  assert.equal(T.record('tab', {}), null);
  assert.equal(T.status().queued, 0);
});

test('events are batched and bounded, and a flush on unload is marked as such', () => {
  T.reset();
  const batches = capture();
  T.configure({ test_session: 'ts-2' });
  T.flush(false);
  for (let i = 0; i < 39; i++) T.record('scroll', { depth: i });
  assert.equal(batches.length, 1, 'thirty-nine more wait for the timer');
  T.record('scroll', { depth: 39 });
  assert.equal(batches.length, 2, 'the fortieth posts the batch');
  assert.equal(batches[1].body.events.length, 40);
  T.record('scroll', { depth: 40 });
  T.flush(true);
  assert.equal(batches[batches.length - 1].unloading, true);
  T._setTransport(() => { throw new Error('gone'); });
  for (let i = 0; i < 350; i++) T.record('scroll', { depth: i });
  assert.ok(T.status().dropped >= 320, 'a transport that fails drops the batch; nothing waits or retries into the way');
  assert.ok(T.status().queued < 300);
  const long = T.record('exception', { message: 'x'.repeat(2000), nested: { a: { b: { c: { d: { e: { f: { g: 1 } } } } } } } });
  assert.equal(long.message.length, 401);
  assert.equal(long.nested.a.b.c.d.e.f, undefined, 'depth is bounded');
});

test('a transport that throws never reaches the caller', () => {
  T.reset();
  T._setTransport(() => { throw new Error('network gone'); });
  T.configure({ test_session: 'ts-3' });
  T.record('tab', {});
  assert.doesNotThrow(() => T.flush(false));
  assert.ok(T.status().dropped >= 1);
});

test('the screen is read as structure: card types, tabs, the rail, the surface, never text', () => {
  T.reset();
  T.configure({ test_session: 'ts-4' });
  const cards = shim.document.createElement('div');
  const order = UI.render([{ type: 'order', data: {
    order_id: 'gid://shopify/Order/1', order_number: '#1930', customer_name: 'Sam Private', customer_email: 'sam@example.com', fulfillment: 'unfulfilled', payment: 'paid', total: '£60.00', detail: true,
    items: [{ title: 'Yard Jeans', variant: 'M', quantity: 1, total: '£60.00', image: '/media/shopify/0123456789abcdef0123456789abcdef/200?u=abc' }], fulfillments: [], shipping_address: { lines: ['12 Private Street'], city: 'London' },
    actions: [{ id: 'note', label: 'Note', enabled: true, risk: 'amber', mode: 'ask', instruction: 'Add a note' }, { id: 'cancel', label: 'Cancel', enabled: false, reason: 'already shipped', risk: 'red', mode: 'ask' }],
    history: { orders: 3, spent: '£410.00', standing: 'returning', recent: [] }, email: { available: true, threads: [] }, pending: [],
  } }, { type: 'confirmation', data: { proposal_id: 'prop_1', status: 'pending', risk: 'amber', operation: 'order_note_append', title: 'Add order note', entity: 'Order #1930', entity_kind: 'order', entity_ref: 'gid://shopify/Order/1', summary: 'Sam asked for an exchange', interaction: { kind: 'tap_commit', label: 'Tap to apply', armed_after_ms: 650 }, ttl_s: 60, reversible: true, commit: { allowed: true } } }]);
  for (const node of order.nodes) cards.appendChild(node);
  document.body.dataset.mode = 'context';
  const snap = T.snapshot(cards, { answer_chars: 42 });
  assert.equal(snap.screen, 'context');
  assert.equal(snap.cards.length, 2);
  const first = snap.cards[0];
  assert.equal(first.type, 'order');
  assert.equal(first.ref, 'gid://shopify/Order/1');
  assert.ok(first.sections.length >= 2 && first.sections.some((s) => /^Items/.test(s)), `the order card's sections are named: ${first.sections}`);
  // The order card is now five tabs with one open, so the snapshot names them: this is how
  // the report can tell "the owner never found the Email tab" from "there was no Email tab".
  assert.deepEqual(first.tabs, ['Overview', 'Items · 1', 'Shipping', 'Customer', 'Email']);
  assert.deepEqual(first.actions, [{ id: 'note', enabled: true }, { id: 'cancel', enabled: false, reason: 'already shipped' }]);
  assert.equal(first.images.count, 1);
  assert.equal(snap.cards[1].proposal_id, 'prop_1');
  assert.equal(snap.cards[1].surface.kind, 'tap_commit');
  assert.deepEqual(snap.viewport, { w: 800, h: 1280, dpr: 1 });
  assert.equal(snap.answer_chars, 42);
  const text = JSON.stringify(snap);
  assert.ok(!/Sam Private|sam@example|Private Street|exchange/.test(text), 'nothing a card said is in the snapshot');
  const recorded = T.record('render', snap);
  assert.deepEqual(recorded.cards[0].actions, [{ id: 'note', enabled: true }, { id: 'cancel', enabled: false, reason: 'already shipped' }], 'the chips survive the event bound');
  assert.equal(recorded.cards[1].surface.kind, 'tap_commit');
});

/* The number the live session got wrong.
 *
 * `ts-20260911-001845`: every render recorded `clipped: 0` while the owner was looking at
 * overlapping text and controls and said so out loud, twice. `clipped` is one subtraction on
 * one card — it can only see a box too small for its own contents, never two boxes that are
 * each the right size and in the same place. The snapshot now carries the second number as
 * well, from web/collide.js, so a report can say what he was actually looking at.
 */
test('the snapshot carries real collision counts, by rule, and the selectors — never the words', () => {
  T.reset();
  T.configure({ test_session: 'ts-collide' });
  const real = globalThis.CrooksCollide;
  globalThis.CrooksCollide = {
    scan: () => ({
      total: 3,
      counts: { control_over_control: 2, text_over_control: 0, notification_over_chrome: 1, folded_action: 0 },
      hits: [
        { rule: 'control_over_control', a: 'button.rail-chip', b: 'button.dock-btn', at: '33,800 120x44', w: 40, h: 12, note: '' },
        { rule: 'notification_over_chrome', a: 'p#toast.toast', b: 'button.branch-chip', at: '40,745 520x44', w: 160, h: 19, note: '' },
      ],
      touch: [{ sel: 'button.row-btn', w: 61, h: 34 }],
      records: 214,
    }),
  };
  const cards = shim.document.createElement('div');
  const snap = T.snapshot(cards, {});
  assert.equal(snap.overflow.collisions, 3, 'the number a report can put beside a turn');
  assert.equal(snap.collisions.total, 3);
  assert.deepEqual(snap.collisions.by_rule, { control_over_control: 2, notification_over_chrome: 1 },
    'only the rules that fired, so a clean screen is a small event');
  assert.equal(snap.collisions.worst.length, 2);
  assert.equal(snap.collisions.worst[0].rule, 'control_over_control');
  assert.equal(snap.collisions.worst[0].b, 'button.dock-btn');
  assert.deepEqual(snap.collisions.small_targets, [{ sel: 'button.row-btn', w: 61, h: 34 }]);
  assert.equal(snap.collisions.measured, 214);
  const recorded = T.record('render', snap);
  assert.equal(recorded.collisions.total, 3, 'and it survives the event bound');
  globalThis.CrooksCollide = real;
});

test('with no geometry module on the page the snapshot says nothing rather than nothing-is-wrong', () => {
  T.reset();
  T.configure({ test_session: 'ts-collide-2' });
  const real = globalThis.CrooksCollide;
  delete globalThis.CrooksCollide;
  const snap = T.snapshot(shim.document.createElement('div'), {});
  assert.equal(snap.overflow.collisions, null, 'null is "not measured", which is not zero');
  assert.equal(snap.collisions, undefined);
  // And a scanner that throws never reaches the caller: a measurement is never worth a render.
  globalThis.CrooksCollide = { scan() { throw new Error('no layout'); } };
  assert.doesNotThrow(() => T.snapshot(shim.document.createElement('div'), {}));
  assert.equal(T.collisions(), null);
  globalThis.CrooksCollide = real;
});

test('an image path is kept without its query, and a bad one is empty', () => {
  assert.equal(T.pathOnly('/media/product/abc.jpg?width=200&sig=secret'), '/media/product/abc.jpg');
  assert.equal(T.pathOnly('https://cdn.shopify.com/s/files/1/x.jpg?v=1'), '/s/files/1/x.jpg');
  assert.equal(T.pathOnly(null), '/');
});

test('a copy of the screen is taken only when the Mac asks for one, and never faster than the gap', async () => {
  T.reset();
  const sent = [];
  T._setTransport((body, unloading, endpoint) => sent.push({ endpoint: endpoint || '/telemetry', body }));
  T.configure({ test_session: 'ts-screens' });
  T.record('exception', { message: 'boom' });
  await new Promise((resolve) => setTimeout(resolve, 1300));
  assert.equal(sent.filter((s) => s.endpoint === '/telemetry/screen').length, 0, 'screens off: no copy');
  assert.equal(T.status().screens, false);
  T.configure({ test_session: 'ts-screens', screens: true });
  T.configure({ test_session: 'ts-screens' });
  assert.equal(T.status().screens, true, 'a /turn answer, which says nothing of screens, leaves the switch alone');
  // No #app in this document: there is nothing to copy, so nothing is sent and nothing counted.
  T.record('exception', { message: 'boom' });
  await new Promise((resolve) => setTimeout(resolve, 1300));
  assert.equal(sent.filter((s) => s.endpoint === '/telemetry/screen').length, 0);
  assert.equal(T.status().screen_count, 0);
  T.reset();
});

/* What stays on the glass (round 12), in the renderer.
 *
 * George: "a task is asked, a screen is shown, an edit is asked, the edit succeeds, however the
 * screen disappears." The Mac now marks the cards an answer carries over from the screen that
 * is up (app/screen.py): `kept` for the card already on the glass, `refreshed` for the same
 * record read again. `CrooksUI.continueScreen` is the glass's half: it keeps every node it can,
 * redraws the ones the Mac has a newer copy of in their own place, adds what is new and takes
 * away what the answer no longer carries. `CrooksUI.landingOf` decides whether a new turn's
 * first patches replace the screen at all.
 *
 * Against the DOM stand-in in dom-shim.js: what is asserted is IDENTITY — which nodes
 * survived, which were replaced, in what order — and the page's own wiring of it is driven in
 * a real browser at the tablet's size (scripts/browser/keep.js).
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
const UI = require(path.join(__dirname, '..', '..', 'web', 'ui.js'));

const ORDER = { order_id: 'gid://shopify/Order/1938', order_number: '#1938', detail: true, total: '£84.00', customer_name: 'Daniel Sear', note: '' };
const order = (extra) => ({ type: 'order', data: Object.assign({}, ORDER, extra || {}) });
const attention = () => ({ type: 'attention', data: { for: ORDER.order_id, items: [{ title: 'Paid, not shipped', level: 'amber', kind: 'age' }] } });
const card = (id, extra) => ({
  type: 'confirmation',
  data: Object.assign({
    proposal_id: id, status: 'pending', risk: 'amber', operation: 'order_note_append', title: 'Add order note',
    entity: 'Order #1938', entity_ref: ORDER.order_id, summary: 'Gift wrap it',
    interaction: { kind: 'tap_commit', label: 'Tap to apply', armed_after_ms: 650 }, ttl_s: 120,
  }, extra || {}),
});
const flag = (item, name) => Object.assign({}, item, { [name]: true });
// No clocks: a card's countdown is the action-state tests' business, and a real one would keep
// this file running for as long as the card lives.
const OPTS = { timers: { set: () => 0, clear: () => {} }, now: () => 0 };

// The glass as a turn left it: the cards drawn by `render`, appended as the page appends them.
function glassOf(items) {
  const host = shim.document.createElement('div');
  for (const node of UI.render(items, OPTS).nodes) host.appendChild(node);
  return host;
}
const ids = (host) => host.children.map((n) => UI.renderIdOf(n));

// ------------------------------------------------------------------ keeping the screen

test('a note waiting for the tap goes on top of the order, and the order node is the one already there', () => {
  const host = glassOf([order(), attention()]);
  const [orderNode, attentionNode] = host.children;
  orderNode.dataset.touched = 'the owner opened a tab on this node';
  const out = UI.continueScreen(host, [card('prop_1'), flag(order(), 'kept'), flag(attention(), 'kept')], OPTS);
  assert.ok(out, 'a continuation');
  assert.deepEqual(ids(host), ['confirmation:prop_1', `order:${ORDER.order_id}`, `attention:${ORDER.order_id}`]);
  assert.equal(host.children[1], orderNode, 'the order was redrawn, not kept');
  assert.equal(host.children[2], attentionNode);
  assert.equal(orderNode.dataset.touched, 'the owner opened a tab on this node');
  assert.equal(orderNode.dataset.patched, '1', 'a node moved must not play its entrance again');
  assert.deepEqual([out.kept, out.added, out.redrawn, out.removed], [2, 1, 0, 0]);
  assert.equal(out.first, host.children[0], 'the new card is the one to bring into view');
  assert.equal(out.hasContext, true);
});

test('an answer in words carries the whole screen and changes no node at all', () => {
  const host = glassOf([order(), attention()]);
  const before = host.children.slice();
  const out = UI.continueScreen(host, [flag(order(), 'kept'), flag(attention(), 'kept')], OPTS);
  assert.deepEqual(host.children, before);
  assert.deepEqual([out.kept, out.added, out.redrawn, out.removed, out.first], [2, 0, 0, 0, null]);
});

test('a record the Mac read again is redrawn in its own place, with the new state', () => {
  const host = glassOf([card('prop_1'), order(), attention()]);
  const stale = host.children[1];
  const out = UI.continueScreen(host, [flag(order({ note: 'Gift wrap it' }), 'refreshed'), flag(attention(), 'kept')], OPTS);
  assert.deepEqual(ids(host), [`order:${ORDER.order_id}`, `attention:${ORDER.order_id}`]);
  assert.notEqual(host.children[0], stale, 'the stale order is not the one shown');
  assert.match(host.children[0].allText(), /Gift wrap it/);
  assert.equal(host.children[0].dataset.patched, '1', 'drawn again in place, not as a new card');
  assert.deepEqual([out.redrawn, out.removed], [1, 1], 'and the settled card the answer did not carry went');
});

test('a card waiting under the owner\'s hand is never redrawn by an answer, even one that re-sends it', () => {
  const host = glassOf([card('prop_1'), order()]);
  const live = host.children[0];
  const surface = live.querySelector('.action-surface');
  surface.dataset.state = 'armed';
  UI.continueScreen(host, [card('prop_1'), flag(order(), 'kept')], OPTS);
  assert.equal(host.children[0], live, 'the armed card was replaced under his thumb');
  assert.equal(surface.dataset.state, 'armed');
});

test('when a card the Mac says is kept is not on this glass, nothing is touched and the answer is drawn whole', () => {
  const host = glassOf([order({ order_id: 'gid://shopify/Order/1940', order_number: '#1940' })]);
  const before = host.children.slice();
  assert.equal(UI.continueScreen(host, [card('prop_1'), flag(order(), 'kept')], OPTS), null);
  assert.deepEqual(host.children, before);
});

test('an answer that marks nothing as carried is not a continuation', () => {
  const host = glassOf([order()]);
  assert.equal(UI.continueScreen(host, [order({ order_id: 'gid://shopify/Order/1940' })], OPTS), null);
  assert.equal(UI.continueScreen(host, [], OPTS), null);
});

test('the context stack rides along as bookkeeping, never as a card', () => {
  const host = glassOf([order()]);
  const out = UI.continueScreen(host, [flag(order(), 'kept'), { type: 'context_stack', data: { entries: [{ kind: 'order', ref: ORDER.order_id, label: '#1938' }] } }], OPTS);
  assert.equal(host.children.length, 1);
  assert.equal(out.stack.length, 1);
});

test('a refusal goes on top of the record it is about, and is reported as the error it is', () => {
  const host = glassOf([order()]);
  const refusal = { type: 'error', data: { service: 'shopify', kind: 'refused', title: 'Could not prepare that', recovery: 'Ask again.' } };
  const out = UI.continueScreen(host, [refusal, flag(order(), 'kept')], OPTS);
  assert.deepEqual(host.children.map((n) => n.dataset.type), ['error', 'order']);
  assert.equal(out.errors.length, 1);
});

// ------------------------------------------------------------------ a new turn's first patches

const patch = (op, item, extra) => Object.assign({ id: UI.surfaceId(item), op, type: item.type, item }, extra || {});
const shell = (kind) => ({ type: kind, data: { shell: true, loading: true, title: 'Order', placeholder: 3 } });

test('a skeleton for the kind of card already up, or the same record read again, does not take the screen', () => {
  const host = glassOf([order(), attention()]);
  assert.equal(UI.landingOf(host, [patch('add', shell('order'))]), 'hold');
  assert.equal(UI.landingOf(host, [patch('add', order({ detail: false }))]), 'hold');
  assert.equal(UI.landingOf(host, [patch('remove', { type: 'order_list', data: { title: 'x' } })]), 'hold');
});

test('the card for a change, reaching the glass before its answer, does not take the screen', () => {
  // Found by the browser walk under load: the turn's workspace channel handed the tablet the
  // note's card (and the context stack) a moment before the answer that carried the order on,
  // and the order went for five frames and came back as a new node.
  const host = glassOf([order(), attention()]);
  const stack = { type: 'context_stack', data: { entries: [{ kind: 'order', ref: ORDER.order_id, label: '#1938' }] } };
  assert.equal(UI.landingOf(host, [patch('add', card('prop_1')), patch('add', stack)]), 'hold');
  const refusal = { type: 'error', data: { service: 'shopify', kind: 'refused', title: 'Could not prepare that', recovery: 'Ask again.' } };
  assert.equal(UI.landingOf(host, [patch('add', refusal), patch('add', card('prop_2'))]), 'hold');
  // With a subject of its own beside it, the subject decides.
  assert.equal(UI.landingOf(host, [patch('add', card('prop_3')), patch('add', order({ order_id: 'gid://shopify/Order/1940', order_number: '#1940' }))]), 'replace');
});

test('a new record, a new list or a skeleton of a kind not up takes the screen', () => {
  const host = glassOf([order()]);
  assert.equal(UI.landingOf(host, [patch('add', order({ order_id: 'gid://shopify/Order/1940', order_number: '#1940' }))]), 'replace');
  assert.equal(UI.landingOf(host, [patch('add', shell('email_list'))]), 'replace');
  assert.equal(UI.landingOf(host, [patch('add', shell('order')), patch('add', { type: 'customer', data: { customer_id: 'gid://shopify/Customer/7', name: 'Daniel' } })]), 'replace');
  assert.equal(UI.landingOf(shim.document.createElement('div'), [patch('add', order())]), 'replace', 'over nothing, anything is new');
});

test('a folded card is known by the card inside it', () => {
  const host = shim.document.createElement('div');
  const ranking = { type: 'ranking', data: { title: 'Best sellers', mode: 'units', rows: [], secondary: true } };
  for (const node of UI.render([ranking], OPTS).nodes) host.appendChild(node);
  assert.equal(host.children[0].dataset.type, 'folded');
  assert.equal(UI.renderIdOf(host.children[0]), 'ranking:Best sellers');
  const out = UI.continueScreen(host, [flag(ranking, 'kept')], OPTS);
  assert.equal(out.kept, 1);
});

// ------------------------------------------------------------------ a chip that listens (C3)

test('only a chip on the cursor\'s card may listen; one on any other card, or with no cursor, may not', () => {
  const rail = [{ id: 'note', label: 'Add a note', enabled: true, instruction: 'Add a note to this order', mode: 'ask', family: 'order.add_note' }];
  const other = { order_id: 'gid://shopify/Order/1940', order_number: '#1940' };
  const host = glassOf([order({ actions: rail }), order(Object.assign({ actions: rail }, other))]);
  const chipOf = (node) => node.querySelectorAll('.rail-chip').find((c) => c.dataset.family === 'order.add_note');
  const [first, second] = host.children.map(chipOf);
  assert.ok(first && second, 'both cards drew their listening chip');
  const cursor = { kind: 'order', ref: ORDER.order_id };
  assert.equal(UI.onCursor(first, cursor), true);
  assert.equal(UI.onCursor(second, cursor), false, 'a chip on #1940 would bind the cursor, #1938');
  assert.equal(UI.onCursor(second, { kind: 'order', ref: other.order_id }), true);
  assert.equal(UI.onCursor(first, null), false, 'with no cursor no card listens');
  assert.equal(UI.onCursor(shim.document.createElement('button'), null), true, 'a control on no record has nothing to disagree with');
});

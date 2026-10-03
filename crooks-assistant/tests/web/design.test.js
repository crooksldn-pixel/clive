/* The design pass of 3 October 2026, run under Node against the renderer (web/ui.js).
 *
 * What is proved:
 * - every card waiting for his approval, one change or a bulk one, carries "Not now", which hands
 *   the Mac the proposal's id and nothing else, only while the surface still waits for a hand —
 *   and the gesture beside it is untouched: "Not now" commits nothing and arms nothing;
 * - the orders list says its count and value once, in one line, and a state every row shares is
 *   said once, in that line ("3 to ship"), unless the title says it, not as a badge on every row;
 * - a working set that only restates the list beside it is not drawn, and the list carries its id
 *   so the set chip still finds the list; a set that adds something is still drawn;
 * - a folded card's header says what is inside it;
 * - the customer having written is a note on an order, not a warning, unless it names something to
 *   check before shipping.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
const UI = require(path.join(__dirname, '..', '..', 'web', 'ui.js'));

const textOf = (node) => node.allText();
const quietTimers = { set: () => 0, clear: () => {} };

function approval(overrides, opts) {
  const data = Object.assign({
    proposal_id: 'prop_1', status: 'pending', risk: 'amber', operation: 'order_note_append', title: 'Add order note',
    entity: 'Order #1930', entity_ref: 'gid://shopify/Order/1', summary: 'Gift wrap it',
    interaction: { kind: 'tap_commit', label: 'Tap to apply', armed_after_ms: 650 }, ttl_s: 60,
  }, overrides || {});
  return UI.renderItem({ type: 'confirmation', data }, opts);
}

function said() {
  const out = { declined: [], committed: [], t: 0 };
  out.opts = {
    now: () => out.t, blocked: () => false, timers: quietTimers,
    onCommit: (id) => out.committed.push(id),
    onDecline: (id, node, button) => out.declined.push([id, node.dataset.proposal, button.textContent]),
  };
  return out;
}

test('a change waiting for him carries Not now, which names the proposal and nothing else', () => {
  const s = said();
  const node = approval({}, s.opts);
  const no = node.querySelector('.action-decline');
  assert.ok(no, 'there is a Not now');
  assert.equal(no.textContent, 'Not now');
  assert.equal(no.getAttribute('type'), 'button');
  no.dispatch('click');
  assert.deepEqual(s.declined, [['prop_1', 'prop_1', 'Not now']]);
  assert.equal(no.disabled, true, 'pressed once, it waits for the Mac');
  no.dispatch('click');
  assert.equal(s.declined.length, 1, 'and a second press asks nothing');
  assert.deepEqual(s.committed, [], 'saying no applies nothing');
  // The countdown sits beside it, where the gesture's own wiring keeps it counting.
  assert.ok(node.querySelector('.action-foot').querySelector('.action-meta'));
});

test('Not now answers only while the surface still waits for a hand', () => {
  for (const state of ['committing', 'verifying', 'verified', 'revoked', 'expired']) {
    const s = said();
    const node = approval({}, s.opts);
    node.querySelector('.action-surface').dataset.state = state;
    node.querySelector('.action-decline').dispatch('click');
    assert.deepEqual(s.declined, [], `not once it is ${state}`);
  }
  const s = said();
  const node = approval({}, Object.assign({}, s.opts, { blocked: () => true }));
  node.querySelector('.action-surface').dataset.state = 'armed';
  node.querySelector('.action-decline').dispatch('click');
  assert.deepEqual(s.declined, [], 'nor while the app is busy with the microphone or a turn');
});

test('there is no Not now on a card that is not waiting, or with nowhere to send it', () => {
  const s = said();
  for (const status of ['verified', 'revoked', 'expired']) {
    assert.equal(approval({ status }, s.opts).querySelector('.action-decline'), null, status);
  }
  assert.equal(approval({ commit: { allowed: false, code: 'writes_disabled', reason: 'Changes are off' } }, s.opts).querySelector('.action-decline'), null,
    'a card that cannot be applied from here has nothing to decline');
  assert.equal(approval({}, { now: () => 0, timers: quietTimers }).querySelector('.action-decline'), null,
    'and without a way to tell the Mac, no control pretends to');
});

test('Not now leaves the gesture exactly as it was: a tap still applies, once armed', () => {
  const s = said();
  const node = approval({}, s.opts);
  const surface = node.querySelector('.action-surface');
  s.t = 700;                                   // past its dead time
  surface.dataset.state = 'armed';
  surface.dispatch('pointerdown', { clientX: 5, clientY: 5, pointerId: 1 });
  surface.dispatch('pointerup', { pointerId: 1 });
  assert.deepEqual(s.committed, ['prop_1']);
  assert.equal(surface.dataset.state, 'committing');
  node.querySelector('.action-decline').dispatch('click');
  assert.deepEqual(s.declined, [], 'and once it is applying, no is not an answer it takes');
});

test('a proposed change is not drawn as an error: the ordinary tier carries a pencil, the red tier its mark', () => {
  const s = said();
  const amber = approval({}, s.opts).querySelector('.card-head').querySelector('.mark');
  assert.ok(amber.classList.contains('quiet') && !amber.classList.contains('warn'));
  assert.ok(!textOf(amber).includes('!'));
  const red = approval({ risk: 'red' }, s.opts).querySelector('.card-head').querySelector('.mark');
  assert.ok(red.classList.contains('bad') && textOf(red).includes('!'));
});

test('a bulk change waiting for him carries Not now too, naming the batch', () => {
  const s = said();
  const node = UI.renderItem({ type: 'batch_action', data: {
    batch_id: 'batch_abc', status: 'pending', title: 'Tag 2 orders', eligible: 2, requested: 3,
    set: { set_id: 'set_1', label: 'To go out', count: 3, kind: 'orders' },
    interaction: { kind: 'hold_to_arm', label: 'Hold to arm, then tap', armed_after_ms: 650 }, ttl_s: 60,
  } }, s.opts);
  const no = node.querySelector('.action-decline');
  assert.ok(no);
  no.dispatch('click');
  assert.deepEqual(s.declined, [['batch_abc', 'batch_abc', 'Not now']]);
});

// ------------------------------------------------------------------ each fact once

const ORDERS = [
  { order_id: 'gid://shopify/Order/1', order_number: '#1927', customer_name: 'Fionn Doherty', total: '£83.00', fulfillment: 'unfulfilled' },
  { order_id: 'gid://shopify/Order/2', order_number: '#1938', customer_name: 'Mia Jones', total: '£89.00', fulfillment: 'unfulfilled' },
  { order_id: 'gid://shopify/Order/3', order_number: '#1940', customer_name: 'Priya Raman', total: '£23.00', fulfillment: 'unfulfilled' },
];

test('the orders list says its count and value once, in one line, and no state every row shares', () => {
  const node = UI.renderItem({ type: 'order_list', data: { title: 'To go out', orders: ORDERS, count: 3, value: '£195.00' } });
  assert.equal(node.querySelectorAll('.stat').length, 0, 'no tiles');
  assert.equal(node.querySelector('.list-sum').textContent, '3 orders · £195.00');
  const rowBadges = (n) => n.querySelectorAll('.row').map((r) => r.querySelectorAll('.badge').length).reduce((a, b) => a + b, 0);
  assert.equal(rowBadges(node), 0, 'every row is unfulfilled: the list says so once');
  const mixed = UI.renderItem({ type: 'order_list', data: { title: 'This week', count: 3, value: '£195.00',
    orders: ORDERS.map((o, i) => Object.assign({}, o, { fulfillment: i ? 'unfulfilled' : 'fulfilled' })) } });
  assert.equal(rowBadges(mixed), 3, 'where the rows differ, each says which it is');
  assert.equal(mixed.querySelector('.list-sum').textContent, '3 orders · £195.00 · 2 to ship', 'and the line says how many are still to go');
});

// Review of the design pass (3 Oct): with the badges gone, "Today" with three unfulfilled orders
// said only "3 orders · £195.00", and nothing on the card said they were still to go out.
test('a state every row shares is said once, in the line, unless the title says it', () => {
  const rowBadges = (n) => n.querySelectorAll('.row').map((r) => r.querySelectorAll('.badge').length).reduce((a, b) => a + b, 0);
  const today = UI.renderItem({ type: 'order_list', data: { title: 'Today', orders: ORDERS, count: 3, value: '£195.00' } });
  assert.equal(today.querySelector('.list-sum').textContent, '3 to ship · £195.00');
  assert.equal(rowBadges(today), 0, 'and not again on every row');
  const one = UI.renderItem({ type: 'order_list', data: { title: 'Today', orders: ORDERS.slice(0, 1), count: 1, value: '£83.00' } });
  assert.equal(one.querySelector('.list-sum').textContent, '1 to ship · £83.00');
  const sent = UI.renderItem({ type: 'order_list', data: { title: 'Last week', count: 3, value: '£195.00',
    orders: ORDERS.map((o) => Object.assign({}, o, { fulfillment: 'fulfilled' })) } });
  assert.equal(sent.querySelector('.list-sum').textContent, '3 shipped · £195.00');
  const unfulfilled = UI.renderItem({ type: 'order_list', data: { title: 'Unfulfilled', orders: ORDERS, count: 3, value: '£195.00' } });
  assert.equal(unfulfilled.querySelector('.list-sum').textContent, '3 orders · £195.00', 'a title that says it already');
  assert.equal(rowBadges(unfulfilled), 0);
  // Ten of forty shown: the line claims nothing for the thirty it has not seen, so each row says its own.
  const part = UI.renderItem({ type: 'order_list', data: { title: 'This month', orders: ORDERS, count: 40, value: '£2,600.00', truncated: true } });
  assert.equal(part.querySelector('.list-sum').textContent, '40 orders · £2,600.00');
  assert.equal(rowBadges(part), 3);
  // Rows that agree on "to ship" but not on the word for it keep their words.
  const finer = UI.renderItem({ type: 'order_list', data: { title: 'Today', count: 3, value: '£195.00',
    orders: ORDERS.map((o, i) => Object.assign({}, o, { fulfillment: i ? 'unfulfilled' : 'partially fulfilled' })) } });
  assert.equal(finer.querySelector('.list-sum').textContent, '3 to ship · £195.00');
  assert.equal(rowBadges(finer), 3);
});

test('a working set that only restates the list beside it is not drawn, and the list carries its id', () => {
  const list = { type: 'order_list', data: { title: 'To go out', orders: ORDERS, count: 3, value: '£195.00' } };
  const set = { type: 'working_set', data: { set_id: 'set_e07962e1ba6c', kind: 'orders', count: 3, label: 'To go out', parent_label: '', step: 'query', sample: [], truncated: false, lines: [{ label: 'Value', value: '£195.00' }] } };
  const out = UI.render([list, set]);
  assert.deepEqual(out.nodes.map((n) => n.dataset.type), ['order_list']);
  assert.equal(out.nodes[0].dataset.set, 'set_e07962e1ba6c', 'the set chip still finds its list');
  // A set made by narrowing, or carrying a figure the list does not show, is still drawn.
  const narrowed = UI.render([list, { type: 'working_set', data: Object.assign({}, set.data, { step: 'filter', parent_label: 'Unfulfilled' }) }]);
  assert.deepEqual(narrowed.nodes.map((n) => n.dataset.type), ['order_list', 'working_set']);
  const more = UI.render([list, { type: 'working_set', data: Object.assign({}, set.data, { lines: [{ label: 'Value', value: '£195.00' }, { label: 'Average', value: '£65.00' }] }) }]);
  assert.deepEqual(more.nodes.map((n) => n.dataset.type), ['order_list', 'working_set']);
  const other = UI.render([list, { type: 'working_set', data: Object.assign({}, set.data, { label: 'Late ones' }) }]);
  assert.deepEqual(other.nodes.map((n) => n.dataset.type), ['order_list', 'working_set'], 'a set with another name is another set');
});

test('the same rule holds when an answer continues the screen', () => {
  const host = shim.document.createElement('div');
  const list = { type: 'order_list', data: { title: 'To go out', orders: ORDERS, count: 3, value: '£195.00' }, refreshed: true };
  const set = { type: 'working_set', data: { set_id: 'set_1', kind: 'orders', count: 3, label: 'To go out', step: 'query', lines: [] }, kept: true };
  const out = UI.continueScreen(host, [list, set]);
  assert.ok(out, 'a kept set the glass never drew does not force a full redraw');
  assert.deepEqual(out.nodes.map((n) => n.dataset.type), ['order_list']);
  assert.equal(out.nodes[0].dataset.set, 'set_1');
  // And a patch that adds that set to a glass whose list stands for it adds nothing.
  host.appendChild(out.nodes[0]);
  const patched = UI.applyPatches(host, [{ op: 'add', id: 'working_set:set_1', item: { type: 'working_set', data: set.data } }]);
  assert.equal(patched.added, 0);
});

test('a folded card says what is inside it', () => {
  const out = UI.render([
    { type: 'order_list', data: { title: 'To go out', orders: ORDERS, count: 3, value: '£195.00' } },
    { type: 'order_list', data: { title: 'Today', orders: ORDERS, count: 3, value: '£177.00', secondary: true } },
    { type: 'email_list', data: { title: 'Email', count: 4, threads: [], secondary: true } },
  ]);
  assert.equal(out.nodes[1].querySelector('.fold-sum').textContent, '3 to ship · £177.00', 'the same line as the list itself');
  assert.equal(out.nodes[2].querySelector('.fold-sum').textContent, '4 threads');
  assert.match(out.nodes[1].querySelector('.fold-head').allText(), /Today/);
});

// ------------------------------------------------------------------ a warm colour only for what needs him

test('the customer having written is a note on the order unless it names something to check', () => {
  const node = UI.renderItem({ type: 'order', data: {
    order_id: 'o1', order_number: '#1938', detail: true, total: '£89.00', payment: 'paid', fulfillment: 'unfulfilled',
    attention_top: [
      { title: 'Customer emailed: Order 1938 — can I add to it?', level: 'amber', kind: 'email' },
      { title: 'Customer emailed — mentions an address', level: 'amber', kind: 'email' },
    ],
    items: [], fulfillments: [],
  } }, {});
  const lines = node.querySelectorAll('.attn-line');
  assert.ok(lines[0].classList.contains('calm') && !lines[0].classList.contains('warn'), 'a customer writing is ordinary');
  assert.ok(lines[1].classList.contains('warn'), 'an address to check before shipping still needs him');
  const badges = node.querySelectorAll('.badges')[0].querySelectorAll('.badge').map((b) => [b.textContent, b.className]);
  assert.deepEqual(badges, [['unfulfilled', 'badge quiet'], ['paid', 'badge ok']]);
});

test('an inbox thread waiting on a reply is its ordinary state, not a warning', () => {
  const node = UI.renderItem({ type: 'email_list', data: { title: 'Waiting on a reply', count: 1,
    threads: [{ thread_id: 't1', from: 'Mia Jones', subject: 'Order 1938', needs_reply: true, known_customer: true }] } });
  const badge = node.querySelectorAll('.badge').find((b) => /reply/i.test(b.textContent));
  assert.ok(badge && !badge.classList.contains('warn'), String(badge && badge.className));
});

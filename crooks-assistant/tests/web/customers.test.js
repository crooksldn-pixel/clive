/* The customers' drawings (web/customers.js) through the renderer (web/ui.js), under Node.
 *
 * What they must hold: a match is drawn with its line of why and a dot per fact; a row opens the
 * order it names and carries nothing of the customer in its attributes; a customer's story is a
 * tab of its own on their card; a refund under an order's money says whether it landed; and every
 * string arrives as text, never markup.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
globalThis.CliveCustomers = require(path.join(__dirname, '..', '..', 'web', 'customers.js'));
const UI = require(path.join(__dirname, '..', '..', 'web', 'ui.js'));

const HOSTILE = '<img src=x onerror="alert(1)">';
const ORDER = 'gid://shopify/Order/2201';

const MATCH = {
  type: 'order_match',
  data: {
    title: 'Best match', verdict: 'one', question: '', note: '',
    rows: [{
      order_id: ORDER, order_number: '#2201', customer_name: 'Alicia Grant', customer_id: 'gid://shopify/Customer/9201',
      placed_at: '2026-09-25T10:00:00Z', total: '£25.00', fulfillment: 'fulfilled', payment: 'partially refunded',
      why: "Alicia Grant — Loopback Hoodie (Grey / M), ordered Fri 25 Sep; name heard as 'Alysa'",
      fits: ["name heard as 'Alysa'", 'grey hoodie on it', 'ordered Fri 25 Sep'], misses: [],
      items: [{ title: 'Loopback Hoodie', variant: 'Grey / M' }],
    }],
  },
};

function all(node, cls) { return node.querySelectorAll(`.${cls}`); }

test('a match is drawn with its why and a dot per fact, and opens its order', () => {
  const out = UI.render([MATCH]);
  assert.equal(out.nodes.length, 1);
  const card = out.nodes[0];
  assert.equal(card.dataset.type, 'order_match');
  assert.match(card.allText(), /Best match/);
  assert.match(all(card, 'cm-why')[0].allText(), /name heard as 'Alysa'/);
  assert.equal(all(card, 'cm-fact').length, 3);
  assert.equal(all(card, 'is-fit').length, 3);
  const row = all(card, 'cm-row')[0];
  assert.equal(row.dataset.kind, 'order');
  assert.equal(row.dataset.ref, ORDER);
  assert.equal(row.dataset.label, '#2201');
  // Nothing of the customer in an attribute: the name is text on the row and nowhere else.
  assert.ok(!JSON.stringify(row.dataset).includes('Alicia'));
  assert.ok(!JSON.stringify(row.attributes).includes('Alicia'));
});

test('several are drawn with the one question, and a miss is an orange dot', () => {
  const two = JSON.parse(JSON.stringify(MATCH));
  two.data.verdict = 'several';
  two.data.title = 'Which one?';
  two.data.question = "Which one: Alicia Grant's Loopback Hoodie on Fri 25 Sep, or Alison Grey's Loopback Hoodie on Thu 24 Sep?";
  two.data.rows.push(Object.assign({}, two.data.rows[0], { order_id: 'gid://shopify/Order/2202', order_number: '#2202',
    customer_name: 'Alison Grey', fits: ['hoodie on it'], misses: ['no grey hoodie on it'] }));
  const card = UI.render([two]).nodes[0];
  assert.equal(all(card, 'cm-row').length, 2);
  assert.match(all(card, 'cm-question')[0].allText(), /^Which one: /);
  assert.equal(all(card, 'is-miss').length, 1);
});

test('every string arrives as text', () => {
  const evil = JSON.parse(JSON.stringify(MATCH));
  evil.data.rows[0].why = HOSTILE;
  evil.data.rows[0].customer_name = HOSTILE;
  const card = UI.render([evil]).nodes[0];
  assert.ok(card.allText().includes(HOSTILE));
  assert.equal(card.querySelectorAll('img').length, 0);
});

test('a ref that is not an order is not a control', () => {
  const odd = JSON.parse(JSON.stringify(MATCH));
  odd.data.rows[0].order_id = 'javascript:alert(1)';
  const row = all(UI.render([odd]).nodes[0], 'cm-row')[0];
  assert.equal(row.dataset.ref, undefined);
  assert.ok(!row.classList.contains('tappable'));
});

test("a customer's story is its own tab on their card, newest first", () => {
  const card = UI.render([{ type: 'customer', data: {
    customer_id: 'gid://shopify/Customer/9201', name: 'Alicia Grant', email: 'alicia.grant@example.com', orders: 2, spent: '£95.00',
    timeline: { rows: [
      { when: 'Thu 1 Oct', kind: 'refund', what: 'Refunded £45.00 on #2201', detail: 'Refund of £45.00 to Visa ending 4242 succeeded on Thu 1 Oct at 14:02.', ref: ORDER, ref_kind: 'order', source: 'Shopify' },
      { when: 'Sat 26 Sep', kind: 'email_in', what: 'Emailed us: Gift receipt', detail: '', ref: '19a0c0ffee000001', ref_kind: 'email_thread', source: 'Gmail' },
      { when: 'Fri 25 Sep', kind: 'objective', what: 'Objective: Make it right with Alicia Grant', detail: '', ref: '', ref_kind: '', source: 'CLIVE' },
    ], count: 3, truncated: false, sources: [{ name: 'Gmail', said: '1 thread' }] },
  } }]).nodes[0];
  const tabs = card.querySelectorAll('.tab').map((t) => t.allText());
  assert.deepEqual(tabs, ['Overview', 'History']);
  const rows = all(card, 'tl-row');
  assert.equal(rows.length, 3);
  assert.equal(rows[0].dataset.ref, ORDER);
  assert.equal(rows[1].dataset.kind, 'email_thread');
  assert.equal(rows[2].dataset.ref, undefined, 'an objective row is drawn, not offered');
  assert.match(card.allText(), /Gmail: 1 thread/);
});

test('a refund under the money says whether it landed', () => {
  const card = UI.render([{ type: 'order', data: {
    order_id: ORDER, order_number: '#2201', detail: true, total: '£25.00', customer_name: 'Alicia Grant',
    money: { subtotal: '£65.00', shipping: '£5.00', refunded: '£45.00' },
    refunds: [{ amount: '£45.00', state: 'succeeded', landed: 'Refund of £45.00 to Visa ending 4242 succeeded on Thu 1 Oct at 14:02.' },
              { amount: '£5.00', state: 'failed', landed: 'Refund of £5.00 to Visa ending 4242 failed: the card was declined.' }],
    items: [], fulfillments: [], pending: [],
  } }]).nodes[0];
  const lines = all(card, 'cm-refund');
  assert.equal(lines.length, 2);
  assert.ok(lines[0].classList.contains('is-fit') && lines[1].classList.contains('is-miss'));
  assert.match(lines[1].allText(), /the card was declined/);
});

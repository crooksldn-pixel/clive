/* The order being built, drawn (round 12): its lines and the choices offered for one.
 *
 * The Mac sends each line as a row — its name, its options, its money, a discount and a stock
 * word — and at most one button on it: "Remove", which posts the line's key, or "Add", which
 * posts a variant the Mac itself offered. What these hold is that the card draws exactly
 * that, in the Mac's order, as text, and that no button carries anything but a command and an
 * identity (app/families/_workspace.py `_row`).
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
const UI = require(path.join(__dirname, '..', '..', 'web', 'ui.js'));

const HOSTILE = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
const ID = 'ord_0a1b2c3d4e';

const ORDER = {
  workspace_id: ID, kind: 'order_draft', kicker: 'A new order · not created', title: 'Theo Marsh',
  subtitle: '2 lines, £78.00 of goods', field_command: 'order.field', fields: [], choices: [], facts: [],
  notes: [], blocked: '', actions: [],
  rows: [
    { key: 'v9113', number: 1, title: 'Convict Hoodie', detail: 'Black / L · CRK-HOOD-BLK-L', quantity: '× 1',
      amount: '£54.00', was: '£60.00', discount: '10% off', stock: '7 in stock', tone: '',
      button: { label: 'Remove', command: 'order.removeitem', args: `workspace_id=${ID}&line=v9113` } },
    { key: 'c1', number: 2, title: 'Custom back print', detail: '', quantity: '× 2', amount: '£24.00', was: '',
      discount: '', stock: 'custom item', tone: '',
      button: { label: 'Remove', command: 'order.removeitem', args: `workspace_id=${ID}&line=c1` } },
  ],
  picks: [],
  picks_title: '',
};

function draw(patch) {
  return UI.renderItem({ type: 'workspace', data: Object.assign({}, ORDER, patch || {}) }, {});
}

test('the lines are drawn in the Mac\'s order with their money, discount and stock as words', () => {
  const node = draw();
  const rows = node.querySelectorAll('.ws-row');
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map((r) => r.dataset.key), ['v9113', 'c1']);
  assert.deepEqual(node.querySelectorAll('.ws-row-title').map((t) => t.textContent), ['Convict Hoodie', 'Custom back print']);
  assert.deepEqual(node.querySelectorAll('.ws-row-amount').map((t) => t.textContent), ['£54.00', '£24.00']);
  assert.deepEqual(node.querySelectorAll('.ws-row-was').map((t) => t.textContent), ['£60.00'], 'struck through only where discounted');
  assert.deepEqual(node.querySelectorAll('.ws-row-off').map((t) => t.textContent), ['10% off']);
  assert.deepEqual(node.querySelectorAll('.ws-row-stock').map((t) => t.textContent), ['7 in stock', 'custom item']);
  assert.deepEqual(node.querySelectorAll('.ws-row-no').map((t) => t.textContent), ['1', '2'], 'numbered as he refers to them');
});

test('each line\'s one button posts a command and the line it is about, and nothing else', () => {
  const buttons = draw().querySelectorAll('.ws-row-btn');
  assert.deepEqual(buttons.map((b) => b.dataset.command), ['order.removeitem', 'order.removeitem']);
  assert.deepEqual(buttons.map((b) => b.dataset.args), [`workspace_id=${ID}&line=v9113`, `workspace_id=${ID}&line=c1`]);
  for (const b of buttons) {
    assert.ok(!/price|amount|quantity|title/.test(b.dataset.args), b.dataset.args);
    assert.equal(b.getAttribute('type'), 'button');
  }
  assert.equal(buttons[0].getAttribute('aria-label'), 'Remove Convict Hoodie Black / L · CRK-HOOD-BLK-L');
});

test('the choices offered for an item are drawn under their question, each with its own Add', () => {
  const node = draw({
    rows: [],
    picks_title: "Which one? 2 match 'black hoodie'",
    picks: [
      { key: 'v9111', title: 'Convict Hoodie', detail: 'Black / S · CRK-HOOD-BLK-S', amount: '£60.00', stock: '4 in stock', tone: '',
        button: { label: 'Add', command: 'order.additem', args: `workspace_id=${ID}&variant_id=gid://shopify/ProductVariant/9111` } },
      { key: 'v9114', title: 'Convict Hoodie', detail: 'Black / XL · CRK-HOOD-BLK-XL', amount: '£60.00', stock: 'not for sale', tone: 'bad',
        button: { label: 'Add', command: 'order.additem', args: `workspace_id=${ID}&variant_id=gid://shopify/ProductVariant/9114` } },
    ],
  });
  assert.equal(node.querySelectorAll('.ws-picks-title')[0].textContent, "Which one? 2 match 'black hoodie'");
  const adds = node.querySelectorAll('.ws-row-btn');
  assert.ok(adds.every((b) => b.classList.contains('is-add')));
  assert.deepEqual(adds.map((b) => b.dataset.command), ['order.additem', 'order.additem']);
  const soldOut = node.querySelectorAll('.ws-row-stock')[1];
  assert.equal(soldOut.textContent, 'not for sale', 'sold out is shown, in words');
  assert.ok(soldOut.classList.contains('tone-bad'));
});

test('a card with no lines draws no list, and a row with no button draws no control', () => {
  const empty = draw({ rows: [] });
  assert.equal(empty.querySelectorAll('.ws-rows').length, 0);
  const plain = draw({ rows: [{ key: 'x', title: 'Thing', amount: '£1.00' }] });
  assert.equal(plain.querySelectorAll('.ws-row-btn').length, 0);
  assert.equal(plain.querySelectorAll('.ws-row-no').length, 0);
});

test('a hostile line lands as text, never as markup', () => {
  const node = draw({
    rows: [{ key: HOSTILE, number: 1, title: HOSTILE, detail: HOSTILE, quantity: HOSTILE, amount: HOSTILE, was: HOSTILE,
             discount: HOSTILE, stock: HOSTILE, tone: HOSTILE,
             button: { label: HOSTILE, command: 'order.removeitem', args: 'workspace_id=x' } }],
    picks_title: HOSTILE,
  });
  assert.ok(node.allText().includes(HOSTILE));
  const tags = new Set();
  (function walk(el) { for (const c of el.children) { tags.add(c.tagName); walk(c); } })(node);
  assert.ok(!tags.has('IMG') && !tags.has('SCRIPT'));
});

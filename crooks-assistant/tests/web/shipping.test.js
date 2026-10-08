/* CLIVE Shipping's drawings (web/shipping.js) through the renderer (web/ui.js), under Node.
 *
 * What they must hold: the orders going out are counted by stage and listed in the service's tab
 * order, each with a dot that means something (blue: a label to buy or print; orange: something
 * stops it; red: a print that failed); a row opens its order and carries nothing else in its
 * attributes, and no tracking link is ever made an attribute; one order keeps payment, label, print
 * and carrier apart; what changed fills the dot of an event the service checked; and every string
 * arrives as text.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
globalThis.CliveShipping = require(path.join(__dirname, '..', '..', 'web', 'shipping.js'));
const UI = require(path.join(__dirname, '..', '..', 'web', 'ui.js'));

const HOSTILE = '<img src=x onerror="alert(1)">';
const ORDER = 'gid://shopify/Order/2142';

const ROW = {
  shipment_id: 'shp_0a1b2c3d4e5f', order_number: '#2142', order_id: ORDER, country: 'GG', stage: 'attention',
  stage_words: 'Needs attention', status: 'Payment pending', reasons: ['Payment pending', 'Missing HS code'],
  payment: 'Payment pending', service: '', price: '', tracking_number: '', print: '', carrier: '', tone: 'warn',
};
const READY = { ...ROW, shipment_id: 'shp_0a1b2c3d4e60', order_number: '#2134', order_id: 'gid://shopify/Order/2134',
  stage: 'ready', stage_words: 'Ready to ship', status: 'Ready', reasons: [], payment: 'Paid',
  service: 'Parcel2Go · Parcelforce Worldwide Channel Islands', price: '£11.79', tone: 'ask' };
const FAILED = { ...READY, shipment_id: 'shp_0a1b2c3d4e61', order_number: '#2125', order_id: 'gid://shopify/Order/2125',
  stage: 'bought', stage_words: 'Label bought', status: 'Fulfilled', tracking_number: 'CI123456789GB', print: 'Print failed', tone: 'bad' };

const OPEN = {
  type: 'shipping',
  data: {
    view: 'open', key: 'open all', stage: '', total: 3, needs_you: 3, truncated: false, checked_at: '2026-10-07T21:10:00Z',
    counts: [{ stage: 'attention', words: 'Needs attention', count: 1 }, { stage: 'ready', words: 'Ready to ship', count: 1 },
      { stage: 'bought', words: 'Label bought', count: 1 }],
    shipments: [ROW, READY, FAILED],
  },
};

function all(node, cls) { return node.querySelectorAll(`.${cls}`); }

test('the orders going out are counted by stage, each row with a dot that means something', () => {
  const out = UI.render([OPEN]);
  assert.equal(out.nodes.length, 1);
  const card = out.nodes[0];
  assert.equal(card.dataset.type, 'shipping');
  assert.match(card.allText(), /CLIVE Shipping/);
  assert.match(card.allText(), /3 orders need you/);
  assert.match(card.allText(), /3 going out/);
  assert.equal(all(card, 'sh-count').length, 3);
  const rows = all(card, 'sh-row');
  assert.equal(rows.length, 3);
  assert.ok(rows[0].classList.contains('is-warn') && rows[1].classList.contains('is-ask') && rows[2].classList.contains('is-bad'));
  assert.match(all(rows[0], 'sh-state')[0].allText(), /Payment pending · Missing HS code/);
  assert.match(rows[1].allText(), /£11\.79/);
  assert.match(all(rows[2], 'sh-state')[0].allText(), /Label bought · Print failed/);
  assert.match(all(rows[2], 'sh-meta')[0].allText(), /tracking CI123456789GB/);
});

test('a row opens its order and carries nothing else in an attribute', () => {
  const card = UI.render([OPEN]).nodes[0];
  const row = all(card, 'sh-row')[0];
  assert.equal(row.dataset.kind, 'order');
  assert.equal(row.dataset.ref, ORDER);
  assert.equal(row.dataset.label, '#2142');
  assert.ok(!JSON.stringify(row.attributes).includes('shp_'), 'the shipment id stays in the text the Mac holds');
  const forged = UI.render([{ type: 'shipping', data: { ...OPEN.data, shipments: [{ ...ROW, order_id: 'javascript:alert(1)' }] } }]).nodes[0];
  assert.equal(all(forged, 'sh-row')[0].dataset.ref, undefined, 'only an order id of the right shape opens');
});

test('one order keeps payment, label, print and carrier apart, and no tracking link is an attribute', () => {
  const one = {
    type: 'shipping',
    data: {
      view: 'one', key: 'one #2125', order_number: '#2125', note: '', tracking: false,
      shipments: [{ ...FAILED, payment_note: '', alerts: ['Paid for: check it before buying again.'], error: '',
        label: { provider: 'Parcel2Go', service: 'Parcelforce Worldwide Channel Islands', tracking_number: 'CI123456789GB',
          tracking_url: 'https://www.parcelforce.com/track?trackNumber=CI123456789GB', purchased_at: '2026-10-07T09:00:00Z' },
        printing: { state: 'failed', label: 'Print failed', via: 'PrintNode → JD-168BT', printed_at: '',
          error: 'PrintNode: Expired: the printer’s computer never collected it. Nothing was printed; print it again.', reprints: 0 },
        carrier_view: { label: 'In transit', note: '', estimated_delivery_at: '2026-10-10T12:00:00Z', delivered_at: '', checked_at: '2026-10-07T20:00:00Z' } }],
    },
  };
  const card = UI.render([one]).nodes[0];
  assert.match(card.allText(), /Shipping for #2125/);
  const facts = all(card, 'sh-fact');
  const words = facts.map((f) => f.allText());
  assert.ok(words.some((w) => /^Payment/.test(w) && /Paid/.test(w)), JSON.stringify(words));
  assert.ok(words.some((w) => /^Label/.test(w) && /tracking CI123456789GB/.test(w)), JSON.stringify(words));
  assert.ok(words.some((w) => /^Print/.test(w) && /Print failed/.test(w)), JSON.stringify(words));
  assert.ok(words.some((w) => /^Carrier/.test(w) && /expected 10 Oct/.test(w)), JSON.stringify(words));
  assert.ok(facts.find((f) => /^Print/.test(f.allText())).classList.contains('is-bad'));
  assert.match(all(card, 'sh-error')[0].allText(), /never collected it/);
  assert.match(all(card, 'sh-alert')[0].allText(), /check it before buying again/);
  assert.ok(!JSON.stringify(card.querySelectorAll('*').map((n) => n.attributes)).includes('parcelforce.com'));
  assert.equal(card.querySelectorAll('a').length, 0);
});

test('a label not bought says so, and an order not found says what the service said', () => {
  const card = UI.render([{ type: 'shipping', data: { view: 'one', key: 'one #2142', shipments: [{ ...ROW, label: null, printing: null }] } }]).nodes[0];
  assert.ok(all(card, 'sh-fact').some((f) => /^LabelNot bought/.test(f.allText())));
  const none = UI.render([{ type: 'shipping', data: { view: 'one', key: 'one #9', shipments: [],
    note: 'CLIVE Shipping has no order #9; it holds international orders only.' } }]).nodes[0];
  assert.match(none.allText(), /holds international orders only/);
});

test('what changed fills the dot of an event the service checked, newest first', () => {
  const events = {
    type: 'shipping',
    data: { view: 'events', key: 'events 24', hours: 24, total: 2, truncated: false, events: [
      { at: '2026-10-07T20:00:00Z', order_number: '#2125', what: 'Carrier update', by: 'system', detail: 'Arrived at hub · GG', verified: true },
      { at: '2026-10-07T09:00:00Z', order_number: '#2125', what: 'Buy label clicked', by: 'George (CLIVE)', detail: '£11.79', verified: false },
    ] },
  };
  const card = UI.render([events]).nodes[0];
  assert.match(card.allText(), /What changed · last 24 hours/);
  const rows = all(card, 'sh-ev');
  assert.equal(rows.length, 2);
  assert.ok(rows[0].classList.contains('is-verified') && !rows[1].classList.contains('is-verified'));
  assert.match(rows[1].allText(), /#2125 · Buy label clicked/);
  assert.match(rows[1].allText(), /by George \(CLIVE\)/);
});

test('every string arrives as text, never markup', () => {
  const hostile = { ...ROW, order_number: HOSTILE, country: HOSTILE, reasons: [HOSTILE], status: HOSTILE, price: HOSTILE, service: HOSTILE };
  const card = UI.render([{ type: 'shipping', data: { ...OPEN.data, shipments: [hostile], counts: [{ stage: 'x', words: HOSTILE, count: 1 }] } }]).nodes[0];
  assert.match(card.allText(), /<img src=x onerror/);
  assert.equal(card.querySelectorAll('img').length, 0);
  const one = UI.render([{ type: 'shipping', data: { view: 'one', shipments: [{ ...hostile, alerts: [HOSTILE], error: HOSTILE,
    label: { provider: HOSTILE, tracking_number: HOSTILE }, printing: { label: HOSTILE, error: HOSTILE } }] } }]).nodes[0];
  assert.equal(one.querySelectorAll('img').length, 0);
});

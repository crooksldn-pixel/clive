/* CROOKS Returns' drawings (web/returns.js) through the renderer (web/ui.js), under Node.
 *
 * What they must hold: the open returns put what needs the owner first, each with a dot that
 * means something; a row opens its order and carries nothing of the customer in its attributes;
 * one return says where it is and draws its timeline, an entry read back from Shopify filled; a
 * period's numbers carry the size finding; an order card shows its returns under its money; the
 * home's count is fetched from the owner's own route; and every string arrives as text.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
globalThis.CliveReturns = require(path.join(__dirname, '..', '..', 'web', 'returns.js'));
const UI = require(path.join(__dirname, '..', '..', 'web', 'ui.js'));

const HOSTILE = '<img src=x onerror="alert(1)">';
const ORDER = 'gid://shopify/Order/2131';

const ROW = {
  return_id: 'ret_0a1b2c3d4e', order_id: ORDER, order_number: '#2131', customer_name: 'Sam Taylor', status: 'received',
  status_words: 'back with us', resolution: 'refund', summary: 'CROOKS-2131: 1x Docket Tee (M) [Faulty or damaged]; refund £25.00',
  attention: ['error', 'needs_decision'], attention_words: ['has an error', 'needs a decision'],
  money: [{ label: 'Refund', shown: '£25.00' }], tracking: 'H01ABC', tracking_url: 'https://www.evri.com/track/H01ABC',
  carrier: 'Evri', error: 'Shopify did not process the return: refused', updated_at: '2026-10-03T11:00:00Z',
};

const OPEN = {
  type: 'returns',
  data: {
    view: 'open', open: 2, needs_you: 2,
    counts: [{ key: 'error', words: 'has an error', count: 1 }, { key: 'needs_approval', words: 'to approve', count: 1 }],
    rows: [ROW, { ...ROW, return_id: 'ret_0a1b2c3d4f', order_number: '#2132', order_id: 'gid://shopify/Order/2132',
      attention: ['needs_approval'], attention_words: ['to approve'], error: '', status_words: 'waiting for your approval' }],
    truncated: false,
    unused_labels: [{ return_id: 'ret_0a1b2c3d50', order_number: '#2110', customer_name: 'Jo Lane', carrier: 'Evri',
      service: 'Evri ParcelShop', paid: '£2.98', parcel2go_order: '26633', bought_at: '2026-09-18T10:00:00Z', days: 15 }],
    checked_at: '2026-10-03T11:02:00Z',
  },
};

function all(node, cls) { return node.querySelectorAll(`.${cls}`); }

test('the open returns put what needs him first, each with a dot that means something', () => {
  const out = UI.render([OPEN]);
  assert.equal(out.nodes.length, 1);
  const card = out.nodes[0];
  assert.equal(card.dataset.type, 'returns');
  assert.match(card.allText(), /2 returns need you/);
  const rows = all(card, 'rt-row');
  assert.equal(rows.length, 3, 'two open returns and one unused label');
  assert.ok(rows[0].classList.contains('is-bad') && rows[1].classList.contains('is-ask') && rows[2].classList.contains('is-warn'));
  assert.match(all(rows[0], 'rt-state')[0].allText(), /has an error · needs a decision/);
  assert.match(all(rows[0], 'rt-error')[0].allText(), /Shopify did not process the return/);
  assert.match(all(rows[0], 'rt-meta')[0].allText(), /Tracking H01ABC · Evri/);
  assert.match(card.allText(), /Labels never posted · cancel on parcel2go\.com/);
  assert.match(card.allText(), /Parcel2Go order 26633/);
  assert.match(card.allText(), /bought 15 days ago/);
});

test('a row opens its order and carries nothing of the customer in an attribute', () => {
  const card = UI.render([OPEN]).nodes[0];
  const row = all(card, 'rt-row')[0];
  assert.equal(row.dataset.kind, 'order');
  assert.equal(row.dataset.ref, ORDER);
  assert.equal(row.dataset.label, '#2131');
  assert.ok(!JSON.stringify(row.dataset).includes('Sam'));
  assert.ok(!JSON.stringify(row.attributes).includes('Sam'));
  assert.ok(!JSON.stringify(row.attributes).includes('evri.com'), 'a tracking link is never made an attribute');
  const forged = UI.render([{ type: 'returns', data: { ...OPEN.data, rows: [{ ...ROW, order_id: 'javascript:alert(1)' }] } }]).nodes[0];
  assert.equal(all(forged, 'rt-row')[0].dataset.ref, undefined, 'only an order id of the right shape opens');
});

test('one return says where it is and draws its timeline, read-back entries filled', () => {
  const one = {
    type: 'returns',
    data: {
      view: 'one', order_number: '#2131', note: '',
      returns: [{ ...ROW, attention: [], attention_words: [], error: '', status: 'in_transit', status_words: 'on its way back',
        where: '#2131 is on its way back; last: on its way back on 3 Oct; tracking H01ABC with Evri.',
        lines: [{ title: 'Docket Tee', variant: 'M', reason: 'too small', exchange_for: 'L', direction: 'a size up', quantity: 1 }],
        timeline: [
          { at: '2026-10-03T10:00:00Z', what: 'On its way back', by: 'Parcel2Go', detail: 'stage DroppedOff', verified: true },
          { at: '2026-10-01T10:00:00Z', what: 'Approved', by: 'clive for George', detail: 'postage mode label_now', verified: false },
        ],
        timeline_total: 2 }],
    },
  };
  const card = UI.render([one]).nodes[0];
  assert.match(card.allText(), /Return on #2131/);
  assert.match(all(card, 'rt-where')[0].allText(), /on its way back; last: on its way back on 3 Oct; tracking H01ABC with Evri/);
  const events = all(card, 'rt-ev');
  assert.equal(events.length, 2);
  assert.ok(events[0].classList.contains('is-verified') && !events[1].classList.contains('is-verified'));
  assert.match(events[1].allText(), /by clive for George/);
  assert.match(all(card, 'rt-line')[0].allText(), /Docket Tee \(M\).*too small · swap for L · a size up/);
});

test('a period\'s numbers carry the size finding', () => {
  const stats = {
    type: 'returns',
    data: {
      view: 'stats', days: 30, returns: 6, kept_share: '67%', value_returned: '£180.00', value_kept: '£120.00',
      bonus_given: '£15.00', label_fees_recovered: '£2.98', by_resolution: [{ label: 'refund', count: 2 }],
      reasons: [{ label: 'too small', count: 3 }], top_skus: [{ label: 'TEE-S', count: 3 }],
      products: [{ title: 'Docket Tee', returned: 3, size_up: 3, size_down: 0, finding: 'x' }],
      findings: ['Docket Tee: 3 came back too small (3 swapped a size up): check its size chart, or say it runs small.'],
    },
  };
  const card = UI.render([stats]).nodes[0];
  assert.match(card.allText(), /Returns · last 30 days/);
  assert.match(card.allText(), /67%kept/);
  assert.match(all(card, 'rt-finding')[0].allText(), /check its size chart/);
  assert.match(card.allText(), /Docket Tee3 up/);
});

test('an order card shows its returns under its money, and none when it has none', () => {
  const order = {
    type: 'order',
    data: { order_id: ORDER, order_number: '#2131', detail: true, items: [], fulfillments: [], refunds: [], tags: [],
      returns: [{ return_id: 'ret_0a1b2c3d4e', status: 'requested', status_words: 'waiting for your approval', resolution: 'refund',
        where: '#2131 is waiting for your approval.', attention_words: ['to approve'], money: [{ label: 'Refund', shown: '£25.00' }],
        tracking: '', error: '' }] },
  };
  const card = UI.render([order]).nodes[0];
  const section = all(card, 'sec-returns')[0];
  assert.ok(section, 'a Returns section');
  assert.match(section.allText(), /refund · to approve/);
  assert.match(section.allText(), /Refund £25\.00/);
  const plain = UI.render([{ type: 'order', data: { ...order.data, returns: [] } }]).nodes[0];
  assert.equal(all(plain, 'sec-returns').length, 0);
  const note = UI.render([{ type: 'order', data: { ...order.data, returns: [], returns_note: 'CROOKS Returns did not answer in time.' } }]).nodes[0];
  assert.match(all(note, 'sec-returns')[0].allText(), /did not answer in time/);
});

test('every string arrives as text, never markup', () => {
  const hostile = { ...ROW, customer_name: HOSTILE, summary: HOSTILE, error: HOSTILE, status_words: HOSTILE, attention_words: [HOSTILE],
    money: [{ label: HOSTILE, shown: HOSTILE }], tracking: HOSTILE, carrier: HOSTILE, order_number: HOSTILE };
  const card = UI.render([{ type: 'returns', data: { ...OPEN.data, rows: [hostile], unused_labels: [{ ...OPEN.data.unused_labels[0], service: HOSTILE }] } }]).nodes[0];
  assert.match(card.allText(), /<img src=x onerror/);
  assert.equal(card.querySelectorAll('img').length, 0);
});

test('the home\'s count comes from the owner\'s own route and is kept for the next drawing', async () => {
  const asked = [];
  globalThis.fetch = async (url, init) => {
    asked.push([url, init && init.cache]);
    return { ok: true, json: async () => ({ ok: true, connected: true, available: true, needs: 2, words: '1 to approve · 1 label overdue' }) };
  };
  const said = await globalThis.CliveReturns.brief();
  assert.deepEqual(asked, [['/returns/brief', 'no-store']]);
  assert.equal(said.needs, 2);
  assert.equal(globalThis.CliveReturns.briefNow().words, '1 to approve · 1 label overdue');
  globalThis.fetch = async () => { throw new Error('offline'); };
  assert.equal((await globalThis.CliveReturns.brief()).needs, 2, 'a failed read keeps what was last known');
  delete globalThis.fetch;
});

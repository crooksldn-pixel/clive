/* The composed workspaces, under Node (§3, §12, §18, §26, §27).
 *
 * The Mac decides what a workspace contains; this decides how it looks. The four properties
 * held here are the ones the glass can break on its own:
 *
 *   - a section is drawn from its own STATE, so an empty inbox and an inbox nobody has read
 *     do not look like the same claim, and a failed section cannot take the rest of the card
 *     with it (§27);
 *   - a row becomes a CONTROL only where the Mac said `open: true` — the `data-ref`/`data-kind`
 *     pair the deck turns into `open.entity` is never built from a ref the Mac withheld (§18);
 *   - the first viewport carries identity, the facts and the offers, above the tabs (§26);
 *   - every string arrives as text. The renderer builds no markup from a payload, here as
 *     everywhere else.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
const UI = require(path.join(__dirname, '..', '..', 'web', 'ui.js'));

const HOSTILE = '<img src=x onerror="alert(1)"><script>alert(2)</script>&lt;b&gt;';
const THREAD = '18f3a2b9c4d5e6f7';

function section(name, over) {
  return Object.assign({
    name, label: name, state: 'unread', note: '', facts: [], rows: [], count: null, truncated: false,
  }, over || {});
}

function customer(over) {
  return Object.assign({
    workspace: 'customer', kind: 'customer', ref: 'gid://shopify/Customer/7',
    label: 'Daniel Stub', title: 'Daniel Stub', subtitle: 'daniel@example.com',
    status: 'Returning',
    header: [{ key: 'Lifetime', value: '£120.00' }, { key: 'Orders', value: '2' },
             { key: 'Last order', value: '#1962 · 1 Sep' }],
    attention: [], actions: [], tab: 'orders', tab_intended: 'orders', tab_reason: 'the request named orders first',
    tabs: [{ name: 'overview', label: 'Overview', state: 'ready', count: null },
           { name: 'orders', label: 'Orders', state: 'ready', count: 2 },
           { name: 'inbox', label: 'Inbox', state: 'empty', count: null },
           { name: 'activity', label: 'Activity', state: 'ready', count: 2 }],
    sections: {
      overview: section('overview', { state: 'ready', facts: [{ key: 'Email', value: 'daniel@example.com' }] }),
      orders: section('orders', {
        state: 'ready', count: 2,
        rows: [{ order_id: 'gid://shopify/Order/1962', order_number: '#1962', when: '1 Sep',
                 total: '£60.00', fulfilment: 'Fulfilled', items_brief: 'Yard Jeans',
                 open: true, open_note: '' }],
      }),
      inbox: section('inbox', { state: 'empty', note: 'No messages found.' }),
      activity: section('activity', { state: 'ready', rows: [{ what: 'Ordered #1962', when: '1 Sep', detail: '£60.00' }] }),
    },
  }, over || {});
}

function order(over) {
  return Object.assign({
    workspace: 'order', kind: 'order', ref: 'gid://shopify/Order/1962', label: '#1962',
    title: 'Order #1962', subtitle: 'Daniel Stub', status: 'To ship',
    header: [{ key: 'Value', value: '£60.00' }, { key: 'Payment', value: 'Paid' },
             { key: 'Fulfilment', value: 'Unfulfilled' }, { key: 'Placed', value: '1 Sep' }],
    attention: [], actions: [], tab: 'overview', tab_intended: 'overview', tab_reason: '',
    tabs: [{ name: 'overview', label: 'Overview', state: 'ready', count: null },
           { name: 'items', label: 'Items', state: 'ready', count: 1 },
           { name: 'shipping', label: 'Shipping', state: 'ready', count: null },
           { name: 'customer', label: 'Customer', state: 'ready', count: null },
           { name: 'email', label: 'Email', state: 'unread', count: null }],
    sections: {
      overview: section('overview', { state: 'ready', facts: [{ key: 'Subtotal', value: '£60.00' }] }),
      items: section('items', { state: 'ready', count: 1, rows: [{ title: 'Yard Jeans', variant: 'Blue Wash / M', sku: 'YJ-M', quantity: 1, total: '£60.00', open: false, open_note: '' }] }),
      shipping: section('shipping', { state: 'ready', facts: [{ key: 'Ships to', value: 'London, United Kingdom' }] }),
      customer: section('customer', { state: 'ready', facts: [{ key: 'Name', value: 'Daniel Stub' }], rows: [{ customer_id: 'gid://shopify/Customer/7', name: 'Daniel Stub', subtitle: 'daniel@example.com', open: true, open_note: '' }] }),
      email: section('email', { state: 'unread', note: 'Ask whether they have emailed about it to fill this in.' }),
    },
  }, over || {});
}

function draw(item) {
  const node = UI.renderItem(item, {});
  assert.ok(node, `${item.type} drew nothing`);
  return node;
}

function find(node, pred) {
  const out = [];
  (function walk(el) { for (const c of el.children) { if (pred(c)) out.push(c); walk(c); } })(node);
  return out;
}

// `h()` writes data-* through `el.dataset`, which the shim keeps apart from `attributes` —
// so these read the dataset, the way the page's own delegated handlers do.
const controls = (node) => find(node, (el) => el.dataset.ref && el.dataset.kind);
const panels = (node) => find(node, (el) => el.dataset.section);
const tabbed = (node) => find(node, (el) => el.dataset.tab && el.className.indexOf('tabbed') !== -1);


test('a customer workspace answers what-is-this, what-matters and what-can-I-do above the tabs', () => {
  const node = draw({ type: 'customer_workspace', data: customer({
    actions: [{ label: 'Open order #1962', command: 'open.entity', kind: 'order',
                ref: 'gid://shopify/Order/1962', enabled: true, reason: '' }],
  }) });
  const words = node.allText();
  assert.ok(words.includes('Daniel Stub'));            // what is this
  assert.ok(words.includes('Returning'));
  assert.ok(words.includes('£120.00') && words.includes('Last order'));   // what matters
  assert.ok(words.includes('Open order #1962'));       // what can I do
  assert.equal(node.dataset.ref, 'gid://shopify/Customer/7');
  assert.equal(node.dataset.workspace, 'customer');
});

test('the workspace opens on the tab the Mac composed, and the owner\'s own choice outranks it', () => {
  const wrap = tabbed(draw({ type: 'customer_workspace', data: customer() }))[0];
  assert.equal(wrap.dataset.tab, 'orders');
  // D-2 in one line: a tab the owner chose is his, and a tab he never chose on THIS record
  // must not be inherited from another one. `opts.tab` naming a tab this workspace does not
  // have falls back to the composed tab rather than to whatever is first.
  const chosen = UI.renderItem({ type: 'customer_workspace', data: customer() }, { tab: 'activity' });
  assert.equal(tabbed(chosen)[0].dataset.tab, 'activity');
  const absent = UI.renderItem({ type: 'customer_workspace', data: customer() }, { tab: 'nonsense' });
  assert.equal(tabbed(absent)[0].dataset.tab, 'orders');
});

test('a section is drawn from its own state, and one bad section leaves the others standing', () => {
  const data = customer({
    sections: Object.assign({}, customer().sections, {
      inbox: section('inbox', { state: 'error', note: 'The inbox could not be read.' }),
    }),
  });
  const node = draw({ type: 'customer_workspace', data });
  const by = {};
  for (const p of panels(node)) by[p.dataset.section] = p;
  assert.equal(by.inbox.dataset.state, 'error');
  assert.ok(by.inbox.allText().includes('could not be read'));
  // §27: the orders the Mac holds are still drawn, with their rows, and the header is intact.
  assert.equal(by.orders.dataset.state, 'ready');
  assert.ok(by.orders.allText().includes('#1962'));
  assert.ok(node.allText().includes('Daniel Stub') && node.allText().includes('£120.00'));
});

test('empty, unread and loading are three different things on the glass', () => {
  const states = { empty: 'No messages found.', unread: 'Ask whether they have emailed to fill this in.', loading: 'Reading…' };
  for (const [state, note] of Object.entries(states)) {
    const data = customer({ sections: Object.assign({}, customer().sections, { inbox: section('inbox', { state, note }) }) });
    const by = {};
    for (const p of panels(draw({ type: 'customer_workspace', data }))) by[p.dataset.section] = p;
    assert.equal(by.inbox.dataset.state, state);
    assert.ok(by.inbox.allText().includes(note), `${state} lost its note`);
    // And nothing that could be read as a value is drawn in place of one.
    assert.equal(by.inbox.allText().includes('#'), false);
  }
});

test('a row is a control only where the Mac said it can be opened (§18)', () => {
  const data = customer({
    sections: Object.assign({}, customer().sections, {
      inbox: section('inbox', {
        state: 'ready',
        rows: [
          { thread_id: THREAD, subject: 'Where is my order', from: 'Daniel Stub', when: 'Mon',
            needs_reply: true, snippet: 'Any news?', open: true, open_note: '' },
          { thread_id: 't-1', subject: 'A message with no openable id', from: 'Daniel Stub',
            when: 'Mon', needs_reply: false, snippet: '', open: false,
            open_note: 'This one has no id the shop would accept.' },
        ],
      }),
    }),
  });
  const node = draw({ type: 'customer_workspace', data });
  const refs = controls(node).map((el) => el.dataset.ref);
  assert.ok(refs.includes(THREAD));
  assert.equal(refs.includes('t-1'), false, 'a ref the Mac withheld became a control');
  // The message is still on the screen, with the reason it cannot be opened.
  assert.ok(node.allText().includes('A message with no openable id'));
  assert.ok(node.allText().includes('no id the shop would accept'));
});

test('an offer the Mac disabled is not a button, and it says why', () => {
  const node = draw({ type: 'customer_workspace', data: customer({
    actions: [{ label: 'Open the last email', command: 'open.entity', kind: 'email_thread',
                ref: '', enabled: false, reason: 'That thread has not been read here.' }],
  }) });
  assert.equal(controls(node).length, 1, 'only the order row is a control');
  assert.ok(node.allText().includes('That thread has not been read here.'));
});

test('an order workspace leads with the order and keeps its five sections', () => {
  const node = draw({ type: 'order_workspace', data: order() });
  const words = node.allText();
  assert.ok(words.includes('Order #1962') && words.includes('Daniel Stub'));
  assert.ok(words.includes('£60.00') && words.includes('Paid') && words.includes('Unfulfilled') && words.includes('1 Sep'));
  assert.deepEqual(panels(node).map((p) => p.dataset.section),
                   ['overview', 'items', 'shipping', 'customer', 'email']);
  // A line on an order is not somewhere to go; the customer on it is.
  assert.deepEqual(controls(node).map((el) => el.dataset.kind), ['customer']);
});

test('no raw id is printed on either workspace (§26)', () => {
  for (const item of [{ type: 'customer_workspace', data: customer() }, { type: 'order_workspace', data: order() }]) {
    const node = draw(item);
    assert.equal(node.allText().includes('gid://'), false, `${item.type} printed a gid`);
    // ...and the ref is still there for the tap, in an attribute rather than in the words.
    assert.ok(node.dataset.ref.startsWith('gid://'));
  }
});

test('every string from outside becomes text, never markup', () => {
  const data = customer({
    title: HOSTILE, subtitle: HOSTILE, status: HOSTILE,
    header: [{ key: HOSTILE, value: HOSTILE }],
    attention: [{ kind: HOSTILE, level: 'red', title: HOSTILE, detail: HOSTILE }],
    actions: [{ label: HOSTILE, command: 'open.entity', kind: 'order', ref: 'gid://shopify/Order/1962', enabled: true, reason: HOSTILE }],
    sections: Object.assign({}, customer().sections, {
      inbox: section('inbox', { state: 'ready', rows: [{ thread_id: THREAD, subject: HOSTILE, from: HOSTILE, when: HOSTILE, snippet: HOSTILE, open: true, open_note: '' }] }),
    }),
  });
  for (const item of [{ type: 'customer_workspace', data }, { type: 'order_workspace', data: order({ title: HOSTILE, subtitle: HOSTILE }) }]) {
    const node = draw(item);
    assert.ok(node.allText().includes(HOSTILE), `${item.type} lost the text`);
    const tags = new Set();
    (function walk(el) { for (const c of el.children) { tags.add(c.tagName); walk(c); } })(node);
    assert.ok(!tags.has('IMG') && !tags.has('SCRIPT'), `${item.type} created markup`);
    (function walk(el) {
      for (const [k, v] of Object.entries(el.attributes)) assert.ok(!String(v).includes('<'), `${el.tagName}[${k}] carries markup`);
      for (const [k, v] of Object.entries(el.dataset)) assert.ok(!String(v).includes('<'), `${el.tagName}[data-${k}] carries markup`);
      for (const c of el.children) walk(c);
    })(node);
  }
});

test('a malformed workspace payload draws a card rather than nothing', () => {
  // The rule the rest of the vocabulary keeps: a payload that is missing everything still
  // renders, because a card that throws leaves the owner with a spoken answer and a blank
  // screen — which is D-15's shape.
  for (const type of ['customer_workspace', 'order_workspace']) {
    const node = UI.renderItem({ type, data: {} }, {});
    assert.ok(node, `${type} drew nothing for an empty payload`);
    assert.equal(node.dataset.type, type);
  }
  // And a shell — a workspace the Mac has promised and not yet read — is the ordinary
  // skeleton, with no value on it at all.
  const shell = UI.renderItem({ type: 'customer_workspace', data: { shell: true, title: 'Customer' } }, {});
  assert.ok(shell.allText().includes('Reading'));
  assert.equal(shell.allText().includes('£'), false);
});

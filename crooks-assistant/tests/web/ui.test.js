/* Renderer tests, run under Node's built-in test runner (node --test tests/web).
 *
 * The renderer is the one place external strings become DOM. These tests hold: only the
 * vocabulary renders; everything else is skipped; every string arrives as text, never markup;
 * and the shapes the backend promises produce the cards the tablet expects.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
const UI = require(path.join(__dirname, '..', '..', 'web', 'ui.js'));

const HOSTILE = '<img src=x onerror="alert(1)"><script>alert(2)</script>&lt;b&gt;';

function textOf(node) { return node.allText(); }

test('the vocabulary is exactly the presentation layer\'s', () => {
  assert.deepEqual(new Set(UI.TYPES), new Set([
    'assistant', 'order', 'order_list', 'customer', 'customer_list', 'product', 'inventory',
    'sales_summary', 'email_list', 'email_thread', 'email_draft', 'attention', 'confirmation',
    'success', 'error', 'context_stack',
    'metric_group', 'ranking', 'table', 'comparison', 'variant_matrix', 'trend', 'working_set',
    'batch_action', 'batch_result', 'capability', 'reply_state',
    'variant_picker',
    'batch_action', 'batch_result', 'capability', 'reply_state', 'email_compose',
    'workspace',
    // The composed surfaces of §3/§12 — one record, not a card per read. Drawn by
    // renderCustomerWorkspace / renderOrderWorkspace; behaviour in workspaces.test.js.
    'customer_workspace', 'order_workspace',
    // The workspace's own header while it fills in (§15): its name and one line per section,
    // each in one of §27's five states. Staged by app/progressive.py, never by present().
    'workspace_plan',
    // The compact summary surface (§13, app/summaries.py). Added, not changed: a summary
    // question — "has anyone bought today who bought before" — was answered with seven
    // full customer profiles (D-4), and a count with one row each is a different component
    // from a profile, not a smaller one.
    'summary_list',
    // The owner's app becoming the remote for one of his screens (round 9, web/remote.js).
    'screen_remote',
  ]));
});

test('unknown types and malformed items are skipped, and nothing is drawn for them', () => {
  const out = UI.render([
    { type: 'hologram', data: { html: '<b>x</b>' } },
    { type: 'order' },                       // no data
    { type: 'order', data: 'not an object' },
    { type: 'order', data: [1, 2] },
    null, 42, 'order',
    { type: 'assistant', data: { text: 'hello' } },
  ]);
  assert.equal(out.nodes.length, 1);
  assert.equal(out.nodes[0].dataset.type, 'assistant');
  assert.deepEqual(out.skipped, ['hologram', 'order', 'order', 'order', 'invalid', 'invalid', 'invalid']);
  assert.equal(UI.renderItem({ type: 'hologram', data: {} }), null);
  assert.equal(UI.renderItem({ type: 'context_stack', data: {} }), null);
});

test('every string from outside becomes text, never markup', () => {
  const items = [
    { type: 'assistant', data: { text: HOSTILE } },
    { type: 'order', data: { order_number: HOSTILE, customer_name: HOSTILE, customer_email: HOSTILE, fulfillment: HOSTILE, payment: HOSTILE, total: HOSTILE, note: HOSTILE, ships_to: HOSTILE, detail: true, items: [{ title: HOSTILE, variant: HOSTILE, sku: HOSTILE, quantity: 1, total: HOSTILE }], fulfillments: [{ status: HOSTILE, carrier: HOSTILE, number: HOSTILE }] } },
    { type: 'customer', data: { name: HOSTILE, email: HOSTILE, orders: 1, spent: HOSTILE } },
    { type: 'product', data: { products: [{ title: HOSTILE, subtitle: HOSTILE, description: HOSTILE, fabric: HOSTILE, measurements: [{ [HOSTILE]: HOSTILE }] }] } },
    { type: 'inventory', data: { query: HOSTILE, exceptions: [{ product: HOSTILE, variant: HOSTILE, level: HOSTILE, available: 1 }], products: [{ title: HOSTILE, variants: [{ variant: HOSTILE, sku: HOSTILE, level: 'ok', available: 9 }] }] } },
    { type: 'sales_summary', data: { title: HOSTILE, revenue: HOSTILE, aov: HOSTILE, orders: 3, basis: HOSTILE, since: HOSTILE } },
    { type: 'email_list', data: { threads: [{ from: HOSTILE, subject: HOSTILE, snippet: HOSTILE, date: HOSTILE }] } },
    { type: 'email_thread', data: { subject: HOSTILE, messages: [{ from: HOSTILE, from_email: HOSTILE, body: HOSTILE, date: HOSTILE }] } },
    { type: 'email_draft', data: { to: HOSTILE, subject: HOSTILE, body: HOSTILE } },
    { type: 'attention', data: { items: [{ title: HOSTILE, detail: HOSTILE, kind: HOSTILE }] } },
    { type: 'confirmation', data: { title: HOSTILE, detail: HOSTILE, confirm_label: HOSTILE, tier: HOSTILE } },
    { type: 'success', data: { title: HOSTILE, detail: HOSTILE } },
    { type: 'error', data: { title: HOSTILE, recovery: HOSTILE, service: HOSTILE } },
  ];
  const out = UI.render(items);
  assert.equal(out.nodes.length, items.length);
  for (const node of out.nodes) {
    // The hostile string is present verbatim as text...
    assert.ok(textOf(node).includes(HOSTILE), `${node.dataset.type} lost the text`);
    // ...and no element was ever created from it.
    const tags = new Set();
    (function walk(el) { for (const c of el.children) { tags.add(c.tagName); walk(c); } })(node);
    assert.ok(!tags.has('IMG') && !tags.has('SCRIPT'), `${node.dataset.type} created markup`);
  }
  // Attributes are never built from data either: no attribute value carries the payload.
  (function walk(el) {
    for (const [k, v] of Object.entries(el.attributes)) assert.ok(!v.includes('<'), `${el.tagName}[${k}] carries markup`);
    for (const c of el.children) walk(c);
  })(out.nodes[1]);
});

test('an order is composed by entity: number and status, then items, money, shipping, customer, email', () => {
  const node = UI.renderItem({ type: 'order', data: {
    order_number: '#1930', fulfillment: 'unfulfilled', payment: 'paid', total: '£60.00', customer_name: 'Sam Fixture',
    placed_at: '2026-09-08T09:42:00Z', detail: true,
    items: [{ title: 'Yard Jeans', variant: 'M', quantity: 1, total: '£60.00', stock: { tracked: true, available: 3 } }], fulfillments: [],
    money: { subtotal: '£55.00', shipping: '£5.00', tax: '£9.17', discounts: '£0.00', refunded: '£0.00', outstanding: '£0.00' },
    shipping_address: { name: 'Sam Fixture', lines: ['12 Somewhere Street', 'Flat 3'], city: 'Windsor', zip: 'SL4 1AA', country: 'United Kingdom' },
    shipping_method: 'Royal Mail Tracked 24',
    history: { orders: 3, spent: '£410.00', since: '2025-01-02T00:00:00Z', standing: 'returning', first_order_at: '2025-01-02T10:00:00Z', other_unfulfilled: ['#1901'],
      recent: [{ order_number: '#1930', placed_at: '2026-09-08T09:42:00Z', total: '£60.00', fulfillment: 'unfulfilled', current: true }, { order_number: '#1901', placed_at: '2026-08-20T10:00:00Z', total: '£200.00', fulfillment: 'unfulfilled', items_brief: 'Convict Hoodie ×2' }] },
    email: { available: true, threads: [{ thread_id: 't1', from: 'Sam Fixture', subject: 'Address for 1930', date: 'Tue, 8 Sep 2026 10:12:00 +0100', snippet: 'Send it to work', verified_sender: true, match: 'both', provenance: 'CUSTOMER_EMAIL' },
      { thread_id: 't2', from: 'Someone', subject: 'Re: #1930', snippet: 'is this mine', verified_sender: false, match: 'order_number', provenance: 'UNKNOWN' }] },
    pending: [],
  } });
  assert.equal(node.dataset.type, 'order');
  assert.equal(node.querySelector('.card-title').textContent, '#1930');
  const badges = node.querySelectorAll('.badges')[0].querySelectorAll('.badge').map((b) => [b.textContent, b.className]);
  assert.deepEqual(badges, [['unfulfilled', 'badge warn'], ['paid', 'badge ok']]);
  // Five tabs, one open. The same facts as before, one screenful at a time: the September
  // session drew these cards 7,524 px tall against 655 px of screen.
  assert.deepEqual(node.querySelectorAll('.tab').map((t) => t.textContent),
    ['Overview', 'Items · 1', 'Shipping', 'Customer', 'Email']);
  assert.equal(node.querySelectorAll('.panel').filter((p) => !p.hidden).length, 1, 'one panel at a time');
  assert.equal(node.querySelector('.tabbed').dataset.tab, 'overview');
  const sections = node.querySelectorAll('.sec').map((s) => s.querySelector('.sec-kicker').textContent);
  assert.deepEqual(sections, ['Money', 'Items · 1', 'Shipping', 'Customerreturning', 'Email'],
    'every section is still there, behind its own tab');
  const items = node.querySelector('.items');
  assert.ok(textOf(items).includes('Yard Jeans') && textOf(items).includes('3 left'));
  assert.equal(node.querySelectorAll('.thumb-img').length, 0, 'no image without a signed path');
  const money = textOf(node.querySelector('.money'));
  assert.ok(money.includes('Subtotal') && money.includes('£5.00') && money.includes('Total') && !money.includes('Refunded'), 'zero refunds are not a line');
  const addr = node.querySelectorAll('.addr-line').map((l) => l.textContent);
  assert.deepEqual(addr, ['Sam Fixture', '12 Somewhere Street', 'Flat 3', 'Windsor SL4 1AA', 'United Kingdom']);
  const hist = textOf(node.querySelector('.sec-history'));
  assert.ok(hist.includes('Lifetime') && hist.includes('£410.00') && hist.includes('Also waiting to ship: #1901') && hist.includes('First order') && hist.includes('this order'));
  const mail = node.querySelector('.sec-email');
  assert.deepEqual(mail.querySelectorAll('.badge').map((b) => b.textContent), ['From the customer · verified', 'Mentions the order']);
  const matched = UI.renderItem({ type: 'order', data: { detail: true, items: [], pending: [], email: { available: true, threads: [{ thread_id: 't', subject: 'x', sender_match: true, verified_sender: false }] } } });
  assert.equal(matched.querySelector('.sec-email').querySelector('.badge').textContent, 'Sender matches');
  assert.equal(node.dataset.pending, '');
});

test('a summary order has no sections and says how to get more', () => {
  const node = UI.renderItem({ type: 'order', data: { order_number: '#1930', detail: false } });
  assert.equal(node.querySelectorAll('.sec').length, 0);
  assert.ok(textOf(node).includes('items and shipping'));
});

test('an image is drawn only from a path the Mac signed, and never from data in fixture-less rendering', () => {
  const signed = '/media/shopify/0123456789abcdef0123456789abcdef/160?u=https%3A%2F%2Fcdn.shopify.com%2Fa.jpg';
  const good = UI.renderItem({ type: 'order', data: { detail: true, items: [{ title: 'Jeans', image: signed }] } });
  assert.equal(good.querySelector('.thumb-img').getAttribute('src'), signed);
  for (const bad of ['https://cdn.shopify.com/a.jpg', '/media/shopify/x/160?u=<img onerror=1>', 'data:image/svg+xml;base64,AAAA', 'javascript:alert(1)']) {
    const node = UI.renderItem({ type: 'order', data: { detail: true, items: [{ title: 'Jeans', image: bad }] } });
    assert.equal(node.querySelectorAll('.thumb-img').length, 0, bad);
    assert.ok(node.querySelector('.thumb-mono'), 'a monogram stands in');
  }
  const fixture = UI.renderItem({ type: 'order', data: { detail: true, items: [{ title: 'Jeans', image: 'data:image/svg+xml;base64,AAAA' }] } }, { fixture: true });
  assert.equal(fixture.querySelectorAll('.thumb-img').length, 1, 'a fixture may carry an inline SVG');
});

test('what missed the budget says so, and is filled in when it arrives', () => {
  const node = UI.renderItem({ type: 'order', data: { detail: true, order_number: '#1930', items: [], pending: ['history', 'email'] } });
  assert.equal(node.dataset.pending, 'history email');
  assert.ok(textOf(node.querySelector('.sec-history')).includes('Reading their history'));
  assert.ok(textOf(node.querySelector('.sec-email')).includes('Checking the inbox'));
  const still = UI.hydrateOrder(node, { pending: ['email'], history: { orders: 2, spent: '£99.00', standing: 'returning', recent: [] } });
  assert.deepEqual(still, ['email']);
  assert.ok(textOf(node.querySelector('.sec-history')).includes('£99.00') && !textOf(node.querySelector('.sec-history')).includes('Reading'));
  assert.ok(textOf(node.querySelector('.sec-email')).includes('Checking the inbox'));
  assert.deepEqual(UI.hydrateOrder(node, { pending: [], email: { available: true, threads: [] } }), []);
  assert.ok(textOf(node.querySelector('.sec-email')).includes('No recent email'));
  assert.equal(node.dataset.pending, '');
  assert.deepEqual(UI.hydrateOrder(null, {}), []);
  const off = UI.renderItem({ type: 'order', data: { detail: true, items: [], pending: [], email: { available: false, reason: 'Gmail is not configured' } } });
  assert.ok(textOf(off.querySelector('.sec-email')).includes('Email not checked'));
});

test('inventory leads with the exceptions', () => {
  const node = UI.renderItem({ type: 'inventory', data: {
    query: 'Yard Jeans', low_stock_at: 5,
    exceptions: [{ product: 'Yard Jeans', variant: 'M', available: 3, level: 'low' }, { product: 'Yard Jeans', variant: 'S', available: 0, level: 'out' }],
    products: [{ title: 'Yard Jeans', variants: [{ variant: 'M', available: 3, level: 'low' }, { variant: 'L', available: 20, level: 'ok' }] }],
  } });
  const rows = node.querySelectorAll('.row');
  assert.ok(rows.length >= 2);
  assert.ok(textOf(rows[0]).includes('3 left') && textOf(rows[0]).includes('Low stock'));
  assert.ok(textOf(rows[1]).includes('Out of stock'));
});

test('sales summary shows real figures and no invented comparison', () => {
  const node = UI.renderItem({ type: 'sales_summary', data: { title: 'Today', revenue: '£430.50', orders: 12, aov: '£35.88', complete: true } });
  assert.equal(node.querySelector('.big').textContent, '£430.50');
  const stats = node.querySelectorAll('.stat-v').map((s) => s.textContent);
  assert.deepEqual(stats, ['12', '£35.88']);
  assert.ok(!textOf(node).toLowerCase().includes('vs'));
});

test('email thread: the newest message is first and open, the history is behind one control', () => {
  // The order of these two nodes is the information hierarchy (§8, D-12): every message was
  // drawn open, oldest first, so the only one anybody was going to read was at the bottom of
  // a surface measured at 1,999 px against a 680 px screen. Newest first, open; the rest
  // complete, in the DOM, and one tap away.
  const node = UI.renderItem({ type: 'email_thread', data: { subject: 'Re: order', messages: [
    { from: 'A', body: 'first' }, { from: 'B', body: 'second' },
  ] } });
  const msgs = node.querySelectorAll('.msg');
  assert.deepEqual(msgs.map((m) => m.classList.contains('is-latest')), [true, false], 'the newest message comes first');
  assert.equal(msgs[1].classList.contains('is-collapsed'), true);
  const disc = node.querySelector('.disc-head');
  assert.ok(disc && /1 earlier message/.test(disc.textContent));
  assert.equal(node.querySelector('.disc-body').hidden, true, 'the history costs no height until it is asked for');
  disc.dispatch('click');
  assert.equal(node.querySelector('.disc-body').hidden, false);
  msgs[1].dispatch('click');
  assert.equal(msgs[1].classList.contains('is-collapsed'), false);
});

test('a draft never has a send control and says nothing was sent; a sent one says sent', () => {
  const node = UI.renderItem({ type: 'email_draft', data: { to: 'x@example.com', subject: 's', body: 'b' } });
  // No buttons at all: the dead "Rewrite / Shorter" controls went with the space they cost.
  assert.equal(node.querySelectorAll('button').length, 0);
  assert.ok(/nothing has been sent/i.test(textOf(node)) && /Draft · saved in Gmail/.test(textOf(node)));
  const sent = UI.renderItem({ type: 'email_draft', data: { state: 'sent', to: 'x@example.com', subject: 's', body: 'b' } });
  assert.equal(sent.querySelectorAll('button').length, 0);
  assert.ok(/^Sent/.test(textOf(sent).trim()) && !/nothing has been sent/i.test(textOf(sent)));
});

test('an email card prints the whole body the gesture would send, as text', () => {
  const { node } = tapHarness({ body: 'Hi Sam,\n\nIt ships tomorrow.\n\n' + HOSTILE, operation: 'gmail_send_reply', risk: 'red' });
  const body = node.querySelector('.action-body');
  assert.ok(body && body.textContent.includes('It ships tomorrow.') && body.textContent.includes(HOSTILE));
  assert.equal(node.querySelector('img'), null);
});

test('a confirmation without a proposal is inert and names its risk', () => {
  const amber = UI.renderItem({ type: 'confirmation', data: { title: 'Fulfil?', risk: 'amber' } });
  const red = UI.renderItem({ type: 'confirmation', data: { title: 'Refund?', risk: 'red' } });
  assert.ok(amber.classList.contains('tier-amber') && red.classList.contains('tier-red'));
  for (const node of [amber, red]) {
    assert.equal(node.querySelectorAll('button').length, 0, 'no generic button that could inherit a click');
    const surface = node.querySelector('.action-surface');
    assert.equal(surface.getAttribute('aria-disabled'), 'true');
    assert.notEqual(surface.dataset.state, 'armed');
    assert.equal(typeof node.settle, 'undefined', 'nothing to commit without a proposal id');
  }
});

test('the context stack comes back as entries and chips, not as a card', () => {
  const out = UI.render([
    { type: 'order', data: { order_number: '#1' } },
    { type: 'context_stack', data: { entries: [{ kind: 'order', label: '#1', ref: 'o1' }, { kind: 'customer', label: HOSTILE, ref: 'c1' }] } },
  ]);
  assert.equal(out.nodes.length, 1);
  assert.equal(out.stack.length, 2);
  let picked = null;
  const chips = UI.renderStack(out.stack, { active: 'c1', onSelect: (e) => { picked = e; } });
  assert.deepEqual(chips.map((c) => c.getAttribute('aria-pressed')), ['false', 'true']);
  assert.ok(textOf(chips[1]).includes(HOSTILE));
  chips[1].dispatch('click');
  assert.equal(picked.ref, 'c1');
});

test('fixtures are marked as such', () => {
  const node = UI.renderItem({ type: 'customer', data: { name: 'Sam' } }, { fixture: true });
  assert.ok(node.classList.contains('is-fixture'));
  assert.ok(/not live/i.test(textOf(node)));
  const live = UI.renderItem({ type: 'customer', data: { name: 'Sam' } });
  assert.ok(!live.classList.contains('is-fixture'));
});

test('lists are bounded even when the payload is not', () => {
  const orders = Array.from({ length: 200 }, (_, i) => ({ order_number: `#${i}` }));
  const node = UI.renderItem({ type: 'order_list', data: { orders } });
  assert.ok(node.querySelectorAll('.row').length <= 10);
  const threads = Array.from({ length: 200 }, (_, i) => ({ subject: `s${i}` }));
  assert.ok(UI.renderItem({ type: 'email_list', data: { threads } }).querySelectorAll('.row').length <= 10);
  const many = Array.from({ length: 100 }, () => ({ type: 'assistant', data: { text: 'x' } }));
  assert.ok(UI.render(many).nodes.length <= 16);
});

test('dates are formatted for reading, and left alone when unparseable', () => {
  assert.match(UI.formatDate('2026-09-08T09:42:00Z'), /8 Sept|8 Sep/);
  assert.equal(UI.formatDate('not a date'), 'not a date');
  assert.equal(UI.formatDate(''), '');
});

test('sales summary lists the days when the Mac breaks the window down', () => {
  const node = UI.renderItem({ type: 'sales_summary', data: { title: 'This week', revenue: '£55.50', orders: 3, by_day: [
    { date: '2026-09-07', orders: 1, revenue: '£40.00' },
    { date: '2026-09-08', orders: 2, revenue: '£15.50' },
    'junk', null,
  ] } });
  const rows = node.querySelectorAll('.row');
  assert.equal(rows.length, 2);
  assert.ok(textOf(rows[0]).includes('£40.00') && textOf(rows[0]).includes('1 order'));
  assert.ok(textOf(rows[1]).includes('2 orders') && textOf(rows[1]).includes('Tue'));
  const plain = UI.renderItem({ type: 'sales_summary', data: { title: 'Today', revenue: '£10.00', orders: 1 } });
  assert.equal(plain.querySelectorAll('.row').length, 0);
});

// ------------------------------------------------------------------ actions

function proposalCard(overrides, opts) {
  const data = Object.assign({
    proposal_id: 'prop_1', status: 'pending', risk: 'amber', operation: 'order_note_append', title: 'Add order note',
    entity: 'Order #1930', entity_kind: 'order', entity_ref: 'gid://shopify/Order/1', summary: HOSTILE, detail: 'The order has no note yet.',
    interaction: { kind: 'tap_commit', label: 'Tap to apply', armed_after_ms: 650 }, ttl_s: 60, reversible: true,
  }, overrides || {});
  return UI.renderItem({ type: 'confirmation', data }, opts);
}

function tapHarness(overrides, extra) {
  let t = 0;
  const commits = [];
  const opts = Object.assign({
    now: () => t, blocked: () => false, onCommit: (id, node) => commits.push(id),
    timers: { set: () => 0, clear: () => {} },
  }, extra || {});
  const node = proposalCard(overrides, opts);
  const surface = node.querySelector('.action-surface');
  return { node, surface, commits, at: (ms) => { t = ms; }, arm: () => { surface.dataset.state = 'armed'; } };
}

test('the action card renders from the proposal, through textContent, with its risk and entity', () => {
  const { node, surface } = tapHarness();
  assert.ok(node.classList.contains('tier-amber'));
  assert.ok(textOf(node).includes('Add order note') && textOf(node).includes('Order #1930') && textOf(node).includes(HOSTILE));
  assert.equal(node.querySelectorAll('button').length, 0);
  assert.equal(surface.dataset.state, 'arming');
  assert.equal(surface.getAttribute('aria-disabled'), 'true');
  assert.equal(node.dataset.proposal, 'prop_1');
});

test('a tap during the dead time does nothing', () => {
  const h = tapHarness();
  h.at(100); h.surface.dispatch('pointerdown'); h.surface.dispatch('pointerup');
  assert.deepEqual(h.commits, []);
});

test('a press that began before arming cannot commit when it ends after', () => {
  const h = tapHarness();
  h.at(100); h.surface.dispatch('pointerdown');
  h.at(900); h.arm(); h.surface.dispatch('pointerup');
  assert.deepEqual(h.commits, []);
});

test('a tap after arming commits once, and only once', () => {
  const h = tapHarness();
  h.at(700); h.arm();
  h.surface.dispatch('pointerdown'); h.surface.dispatch('pointerup');
  h.surface.dispatch('pointerdown'); h.surface.dispatch('pointerup');
  h.surface.dispatch('pointerdown'); h.surface.dispatch('pointerup');
  assert.deepEqual(h.commits, ['prop_1']);
  assert.equal(h.surface.dataset.state, 'committing');
});

test('recording or a turn in flight blocks the tap', () => {
  let busy = true;
  const h = tapHarness({}, { blocked: () => busy });
  h.at(700); h.arm();
  h.surface.dispatch('pointerdown'); h.surface.dispatch('pointerup');
  assert.deepEqual(h.commits, []);
  busy = false;
  h.surface.dispatch('pointerdown'); h.surface.dispatch('pointerup');
  assert.deepEqual(h.commits, ['prop_1']);
});

test('a settled card cannot be tapped', () => {
  for (const state of ['stale', 'expired', 'revoked', 'verified']) {
    const h = tapHarness();
    h.at(700); h.arm();
    h.node.settle(state, 'Not available');
    h.surface.dispatch('pointerdown'); h.surface.dispatch('pointerup');
    assert.deepEqual(h.commits, [], state);
    assert.equal(h.surface.dataset.state, state);
  }
});

test('a proposal that is not pending, or an interaction the tablet does not know, is inert', () => {
  for (const data of [{ status: 'expired' }, { interaction: { kind: 'select_then_commit' } }, { proposal_id: '' }]) {
    const h = tapHarness(data);
    h.at(5000);
    h.surface.dispatch('pointerdown'); h.surface.dispatch('pointerup');
    assert.deepEqual(h.commits, []);
  }
  assert.ok(textOf(tapHarness({ interaction: { kind: 'select_then_commit' } }).node).includes('newer app build'));
});

test('a success card offers its undo the same way, and success needs a verified answer to exist at all', () => {
  const commits = [];
  let t = 0;
  const node = UI.renderItem({ type: 'success', data: { title: 'Note added', detail: 'Order #1930', proposal_id: 'prop_1', undo: { proposal_id: 'prop_2', label: 'Undo', ttl_s: 60, armed_after_ms: 650 } } },
    { now: () => t, onCommit: (id) => commits.push(id), timers: { set: () => 0, clear: () => {} } });
  const surface = node.querySelector('.action-surface');
  assert.ok(surface && textOf(surface).includes('Undo'));
  t = 100; surface.dispatch('pointerdown'); surface.dispatch('pointerup');
  assert.deepEqual(commits, []);
  t = 700; surface.dataset.state = 'armed';
  surface.dispatch('pointerdown'); surface.dispatch('pointerup');
  assert.deepEqual(commits, ['prop_2']);
  const plain = UI.renderItem({ type: 'success', data: { title: 'Note added' } });
  assert.equal(plain.querySelector('.action-surface'), null);
});

// ------------------------------------------------------------------ composition

test('an order carries its progress strip and every item, with the quantity where it is more than one', () => {
  const node = UI.renderItem({ type: 'order', data: { order_number: '#1930', payment: 'paid', fulfillment: 'unfulfilled', placed_at: '2026-09-08T09:42:00Z', detail: true,
    items: [{ title: 'Yard Jeans', variant: 'M', total: '£60.00', quantity: 2 }, { title: 'Convict Sweats', variant: 'L', total: '£55.00', quantity: 1 }, { title: 'Cap', total: '£20.00' }, { title: 'Socks', total: '£8.00' }], fulfillments: [], items_truncated: true } });
  const steps = node.querySelectorAll('.tl-step');
  assert.equal(steps.length, 3);
  assert.deepEqual(steps.map((s) => s.classList.contains('is-done')), [true, true, false]);
  assert.ok(textOf(steps[2]).includes('To ship'));
  const items = node.querySelector('.items');
  assert.equal(items.querySelectorAll('.item').length, 5, 'four items and a "more" line');
  assert.ok(textOf(items).includes('Yard Jeans') && textOf(items).includes('× 2') && textOf(items).includes('More items than shown'));
  const cancelled = UI.renderItem({ type: 'order', data: { order_number: '#1', payment: 'refunded', fulfillment: 'unfulfilled', cancelled_at: '2026-09-08T10:00:00Z' } });
  assert.equal(cancelled.querySelectorAll('.is-bad').length, 1);   // the shim reads one class at a time
  assert.ok(textOf(cancelled).includes('Cancelled'));
});

test('a customer card carries the history when the tool returned it', () => {
  const node = UI.renderItem({ type: 'customer', data: { customer_id: 'c1', name: 'Daniel Sear', email: 'd@example.com', orders: 3, spent: '£410.00',
    history: { orders: 3, spent: '£410.00', since: '2025-01-02T00:00:00Z', standing: 'returning', other_unfulfilled: ['#1901', '#1938'], recent: [{ order_number: '#1938', total: '£60.00', fulfillment: 'unfulfilled' }] },
    related_email: { available: true, threads: [{ thread_id: 't1', subject: 'Hello', verified_sender: true }] } } });
  assert.ok(textOf(node).includes('Also waiting to ship: #1901, #1938') && textOf(node).includes('From the customer'));
  const many = UI.renderItem({ type: 'customer', data: { name: 'R', history: { orders: 12, recent_truncated: true, recent: [{ order_number: '#9' }, { order_number: '#8' }] } } });
  assert.ok(textOf(many).includes('Last 2 of 12 orders shown'));
  assert.ok(textOf(node).includes('d@example.com'), 'the address is still the address');
  assert.ok(!textOf(node).includes('Ask for their orders'));
});

test('a customer is a profile: initials, standing, lifetime', () => {
  const node = UI.renderItem({ type: 'customer', data: { customer_id: 'c1', name: 'Daniel Sear', email: 'd@example.com', orders: 4, spent: '£286.00' } });
  assert.equal(textOf(node.querySelector('.avatar')), 'DS');
  assert.ok(textOf(node).includes('Regular') && textOf(node).includes('Lifetime'));
  assert.equal(node.dataset.ref, 'c1');
  assert.equal(textOf(UI.renderItem({ type: 'customer', data: { name: HOSTILE } }).querySelector('.avatar')).length, 2);
  assert.ok(textOf(UI.renderItem({ type: 'customer', data: { name: 'Solo', orders: 1 } })).includes('First order'));
});

test('sales over several days become a strip of bars whose heights are numbers of our own making', () => {
  const node = UI.renderItem({ type: 'sales_summary', data: { title: 'This week', revenue: '£1,000.00', orders: 10, by_day: [
    { date: '2026-09-02', orders: 1, revenue: '£100.00' }, { date: '2026-09-03', orders: 2, revenue: '£400.00' }, { date: '2026-09-04', orders: 0, revenue: '£0.00' } ] } });
  const bars = node.querySelectorAll('.bar');
  assert.equal(bars.length, 3);
  assert.deepEqual(bars.map((b) => Number(b.dataset.pct)), [25, 100, 4]);
  assert.equal(UI.renderItem({ type: 'sales_summary', data: { revenue: '£1', by_day: [{ date: '2026-09-02', revenue: '£1' }] } }).querySelectorAll('.bar').length, 0, 'one day is not a chart');
});

test('an order says what it needs on the card, above the tabs and above the rail', () => {
  // §8: the first viewport answers what matters. The attention card that carries the detail
  // sits AFTER the order card, which at 601 × 889 is below the fold.
  const node = UI.renderItem({ type: 'order', data: {
    order_id: 'o1', order_number: '#1938', detail: true, total: '£84.00', payment: 'paid', fulfillment: 'unfulfilled',
    attention_top: [
      { title: 'Paid 2 days ago and not shipped', level: 'red', kind: 'unfulfilled' },
      { title: 'They wrote in and we have not replied', level: 'amber', kind: 'email' },
    ],
    items: [], fulfillments: [],
  } }, {});
  const lines = node.querySelectorAll('.attn-line');
  assert.equal(lines.length, 2);
  assert.match(lines[0].textContent, /not shipped/);
  assert.ok(lines[0].classList.contains('bad') && lines[1].classList.contains('warn'), 'the level is the tone');
  // Above the tabs: in the DOM, the strip comes before the tab bar it must not be behind.
  const kids = node.children.map((c) => c.className.split(' ')[0]);
  assert.ok(kids.indexOf('attn-strip') !== -1 && kids.indexOf('attn-strip') < kids.indexOf('tabbed'), kids.join(','));
});

test('a long order note and a long item tail each go behind one control', () => {
  // D-12, measured at 601 x 889 after the deck stopped scrolling under the dock: the worst
  // order card stood at 757 px against a 699 px ceiling, and 213 px of it was one note read
  // in full. A clamp was tried first and saved nothing — the 44 px its More button needs for
  // a thumb is exactly what the clamp gave back — so the note goes behind one control, the
  // same discipline the thread's history and the list's tail keep. Nothing is removed.
  const note = 'A sentence about the order that keeps going and going. '.repeat(5);
  const long = UI.renderItem({ type: 'order', data: {
    order_id: 'o1', order_number: '#1938', detail: true, note: note,
    items: [0, 1, 2, 3, 4, 5, 6, 7].map((i) => ({ title: 'Item ' + i, total: '£10.00', quantity: 1 })),
    fulfillments: [],
  } }, {});
  const quote = long.querySelector('.note-quote');
  assert.ok(quote, 'the note is in the DOM, complete');
  assert.equal(textOf(quote), note, 'nothing is cut from it');
  const discs = long.querySelectorAll('.disc');
  const noteDisc = discs.find((d) => d.querySelector('.note-quote'));
  assert.ok(noteDisc, 'a long note is behind a disclosure, not read in full');
  assert.ok(noteDisc.querySelector('.disc-body').hidden, 'and it starts closed');
  // Eight items: five in the open list, three behind their own control.
  const lists = long.querySelectorAll('.items');
  assert.equal(lists.length, 2, 'the tail is a second list, behind a control');
  assert.equal(lists[0].querySelectorAll('.item').length, 5);
  const tail = discs.find((d) => d.querySelector('.items'));
  assert.ok(tail && /3 more items/.test(textOf(tail.querySelector('.disc-label'))), textOf(tail));
  assert.equal(tail.querySelectorAll('.item').length, 3, 'the tail holds the rest');
  assert.equal(long.querySelectorAll('.item').length, 8, 'every item is still in the DOM');

  // A short note is still read in place: a control to open two lines is worse than the lines.
  const brief = UI.renderItem({ type: 'order', data: {
    order_id: 'o2', order_number: '#1939', detail: true, note: 'Hold for collection.',
    items: [{ title: 'One thing', total: '£10.00', quantity: 1 }], fulfillments: [],
  } }, {});
  assert.ok(brief.querySelector('.note-quote'), 'the short note is there');
  assert.equal(brief.querySelectorAll('.disc').filter((d) => d.querySelector('.note-quote')).length, 0,
    'and not behind a control');
  assert.equal(brief.querySelectorAll('.items').length, 1, 'one short list does not fold');
});

test('an email thread shows a face per message and lights the latest', () => {
  const node = UI.renderItem({ type: 'email_thread', data: { subject: 's', messages: [{ from: 'Ada Lovelace', body: 'one' }, { from: 'Sam Fixture', body: 'two' }] } });
  const msgs = node.querySelectorAll('.msg');
  assert.equal(msgs.length, 2);
  // Newest first: the latest message's face is at the top of the card, the earlier one's
  // inside the history.
  assert.deepEqual(msgs.map((m) => textOf(m.querySelector('.avatar'))), ['SF', 'AL']);
  assert.ok(msgs[0].classList.contains('is-latest') && msgs[1].classList.contains('is-collapsed'));
});

test('the surface stops inviting a tap just before the Mac would say Expired', () => {
  const scheduled = [];
  const h = tapHarness({ ttl_s: 60 }, { timers: { set: (fn, ms) => { scheduled.push({ fn, ms }); return scheduled.length; }, clear: () => {} } });
  const expiry = scheduled.find((t) => t.ms > 1000);
  assert.ok(expiry && expiry.ms === 59000, 'a second early, never late');
  h.at(700); h.arm();
  expiry.fn();
  assert.equal(h.surface.dataset.state, 'expired');
  h.surface.dispatch('pointerdown'); h.surface.dispatch('pointerup');
  assert.deepEqual(h.commits, []);
  assert.ok(textOf(h.surface).includes('Expired'));
});

test('the arming fill lasts exactly as long as the arming', () => {
  const h = tapHarness({ interaction: { kind: 'tap_commit', label: 'Tap to apply', armed_after_ms: 900 } });
  assert.equal(h.surface.style.getPropertyValue('--arm-ms'), '900ms');
});

test('partial payment and partial shipping light the middle of the strip', () => {
  const node = UI.renderItem({ type: 'order', data: { order_number: '#2', payment: 'partially paid', fulfillment: 'partially fulfilled', placed_at: '2026-09-08T09:42:00Z' } });
  assert.equal(node.querySelectorAll('.is-partial').length, 2);
});

test('a blocked card names who is stopping the tap, by code, and never blames the tablet for the Mac', () => {
  const words = {};
  for (const code of ['writes_disabled', 'allow_list_missing', 'not_authorised', 'not_authorised_local', 'scope_missing', 'something_else']) {
    const node = proposalCard({ commit: { allowed: false, code, reason: 'why' } });
    const surface = node.querySelector('.action-surface');
    assert.equal(surface.dataset.state, 'unavailable');
    words[code] = textOf(surface);
  }
  assert.ok(/switched off on the server/.test(words.writes_disabled));
  assert.ok(/No allowed logins/.test(words.allow_list_missing));
  assert.ok(/device's login/.test(words.not_authorised));
  assert.ok(/server itself/.test(words.not_authorised_local) && !/tablet/.test(words.not_authorised_local));
  assert.ok(/Shopify has not granted/.test(words.scope_missing));
  for (const text of Object.values(words)) assert.ok(!/not allowed/i.test(text), text);
});

test('the wait line counts down while the card is live and clears when it settles', () => {
  const scheduled = [];
  let t = 0;
  const timers = { set: (fn, ms) => { scheduled.push({ fn, ms }); return scheduled.length; }, clear: () => {} };
  const node = proposalCard({ ttl_s: 60 }, { now: () => t, blocked: () => false, onCommit: () => {}, timers });
  const meta = node.querySelector('.action-meta');
  assert.ok(textOf(meta).startsWith('Waits 60 s'));
  const tick = scheduled.find((s) => s.ms === 1000);
  t = 12000; tick.fn();
  assert.ok(textOf(meta).startsWith('Waits 48 s'), textOf(meta));
  node.settle('revoked', 'Withdrawn');
  assert.equal(textOf(meta), '');
});

test('a sales window names the last day it covers, not the morning after', () => {
  const node = UI.renderItem({ type: 'sales_summary', data: { title: 'Last 7 days', revenue: '£1,000.00', orders: 12, days: 7, since: '2026-09-01T23:00:00Z', until: '2026-09-08T23:00:00Z' } });
  const meta = textOf(node.querySelector('.card-meta'));
  assert.ok(meta.indexOf('→') !== -1 && /8 Sept/.test(meta) && !/9 Sept/.test(meta), meta);
});

test('the undo counts down too, and stops offering itself when its minute is up', () => {
  const scheduled = [];
  let t = 0;
  const timers = { set: (fn, ms) => { scheduled.push({ fn, ms }); return scheduled.length; }, clear: () => {} };
  const node = UI.renderItem({ type: 'success', data: { title: 'Note added', detail: 'Order #1930', proposal_id: 'p1', undo: { proposal_id: 'p2', label: 'Undo', armed_after_ms: 100, ttl_s: 60 } } },
    { now: () => t, blocked: () => false, onCommit: () => {}, timers });
  const meta = node.querySelectorAll('.action-meta').pop();
  assert.ok(textOf(meta).indexOf('Undo available for') === 0, textOf(meta));
  const tick = scheduled.find((s) => s.ms === 1000);
  t = 20000; tick.fn();
  assert.equal(textOf(meta), 'Undo available for 40 s');
  const expiry = scheduled.find((s) => s.ms > 1000);
  assert.ok(expiry && expiry.ms === 59000);
  expiry.fn();
  assert.equal(node.querySelector('.action-surface').dataset.state, 'expired');
});

test('the rail shows only the Mac\'s chips, primes the words on tap, and a disabled chip says why and does nothing', () => {
  const primed = [];
  const node = UI.renderItem({ type: 'order', data: { detail: true, order_number: '#1938', items: [], pending: [], actions: [
    { id: 'note', label: 'Note', risk: 'amber', enabled: true, instruction: 'Add a note to order 1938', mode: 'ask' },
    { id: 'cancel', label: 'Cancel', risk: 'red', enabled: true, instruction: 'Cancel order 1938', mode: 'ask' },
    { id: 'refund', label: 'Refund', risk: 'red', enabled: false, reason: 'not paid', instruction: 'Refund order 1938', mode: 'ask' },
    { id: 'evil', label: HOSTILE, risk: 'red', enabled: true, instruction: HOSTILE, mode: 'ask' },
  ] } }, { onAction: (a) => primed.push(a.id) });
  const chips = node.querySelectorAll('.rail-chip');
  assert.equal(chips.length, 4);
  assert.deepEqual(chips.map((c) => c.getAttribute('aria-disabled')), ['false', 'false', 'true', 'false']);
  assert.ok(textOf(chips[2]).includes('not paid'));
  chips[0].dispatch('click'); chips[1].dispatch('click'); chips[2].dispatch('click'); chips[3].dispatch('click');
  assert.deepEqual(primed, ['note', 'cancel', 'evil']);
  assert.ok(textOf(chips[3]).includes(HOSTILE) && !node.querySelectorAll('img').length);
  assert.equal(UI.renderItem({ type: 'order', data: { detail: true, items: [], actions: [] } }).querySelectorAll('.rail').length, 0, 'no rail without chips');
});


// ---- the gestures. A timer table stands in for setTimeout so a hold can be "completed" by
// firing the timer the surface armed, and a press can carry coordinates.

function gestureHarness(kind, extra) {
  let t = 0;
  const commits = [];
  const arms = [];
  const timers = [];
  const opts = Object.assign({
    now: () => t, blocked: () => false, trackWidth: 356,
    onCommit: (id, node, nonce) => commits.push([id, nonce || '']),
    onArm: (id) => { arms.push(id); return Promise.resolve('tok-1'); },
    timers: { set: (fn, ms) => { timers.push({ fn, ms, id: timers.length + 1 }); return timers.length; }, clear: (id) => { const x = timers[id - 1]; if (x) x.cleared = true; } },
  }, extra || {});
  const node = proposalCard({ interaction: { kind, label: 'x', armed_after_ms: 650, target: 'Drop to cancel and refund £60.00' }, risk: 'red' }, opts);
  const surface = node.querySelector('.action-surface');
  const fire = (ms) => { for (const x of timers) if (!x.fired && !x.cleared && x.ms === ms) { x.fired = true; x.fn(); } };
  const down = (x, y) => surface.dispatch('pointerdown', { clientX: x || 0, clientY: y || 0, pointerId: 1 });
  const move = (x, y) => surface.dispatch('pointermove', { clientX: x || 0, clientY: y || 0, pointerId: 1 });
  const up = () => surface.dispatch('pointerup', { pointerId: 1 });
  const settle = () => new Promise((r) => setTimeout(r, 0));
  return { node, surface, commits, arms, timers, fire, down, move, up, settle, at: (ms) => { t = ms; }, arm: () => { surface.dataset.state = 'armed'; } };
}
const TRACK = 300;   // 356 minus a 56 px handle

test('a swipe commits only past most of the track, and a vertical wobble is a scroll', () => {
  const h = gestureHarness('swipe_commit');
  assert.equal(h.surface.dataset.kind, 'swipe_commit');
  assert.ok(h.node.querySelector('.action-track') && h.node.querySelector('.action-handle'));
  h.at(700); h.arm();
  h.down(10, 100); h.move(120, 102); h.up();                 // not far enough
  assert.deepEqual(h.commits, []);
  assert.equal(h.surface.dataset.dx, '0', 'the handle springs back');
  h.down(10, 100); h.move(60, 140); h.up();                  // the thumb went down the page
  assert.deepEqual(h.commits, []);
  h.down(10, 100); h.move(100, 101); h.move(240, 103); h.up();
  assert.deepEqual(h.commits, [['prop_1', '']]);
  assert.equal(h.surface.dataset.state, 'committing');
  h.down(10, 100); h.move(300, 100); h.up();
  assert.equal(h.commits.length, 1, 'once');
});

test('a swipe during the dead time, or while busy, moves nothing', () => {
  let busy = false;
  const h = gestureHarness('swipe_commit', { blocked: () => busy });
  h.at(100); h.down(10, 100); h.move(300, 100); h.up();
  assert.deepEqual(h.commits, []);
  h.at(700); h.arm(); busy = true;
  h.down(10, 100); h.move(300, 100); h.up();
  assert.deepEqual(h.commits, []);
});

test('hold to arm: the Mac is told as the hold begins, a wobble aborts it, the tap after the hold commits with the token', async () => {
  const h = gestureHarness('hold_to_arm');
  h.at(700); h.arm();
  h.down(50, 50);
  assert.equal(h.surface.dataset.state, 'holding');
  assert.deepEqual(h.arms, ['prop_1']);
  await h.settle();
  h.move(50 + 20, 50);                                       // a wobble
  assert.equal(h.surface.dataset.state, 'armed');
  assert.ok(textOf(h.surface).includes('Hold still'));
  h.up();
  assert.deepEqual(h.commits, []);
  // A still hold: the timer completes it, the surface says so, and a tap applies it.
  h.down(50, 50); await h.settle();
  h.fire(HOLD_TOTAL);
  assert.equal(h.surface.dataset.state, 'held');
  assert.ok(textOf(h.surface).includes('Armed'));
  h.up();                                                    // the lift that ends the hold: nothing yet
  assert.deepEqual(h.commits, []);
  h.at(1500); h.down(50, 50); h.up();                        // the tap
  assert.deepEqual(h.commits, [['prop_1', 'tok-1']]);
});
const HOLD_TOTAL = 1050;

test('a hold the Mac will not arm never commits, and a lift before the hold completes disarms', async () => {
  const h = gestureHarness('hold_to_arm', { onArm: () => Promise.resolve(null) });
  h.at(700); h.arm();
  h.down(50, 50); await h.settle();
  assert.equal(h.surface.dataset.state, 'armed');
  assert.ok(textOf(h.surface).includes("won't arm"));
  const g = gestureHarness('hold_to_arm');
  g.at(700); g.arm();
  g.down(50, 50); await g.settle(); g.up();
  assert.equal(g.surface.dataset.state, 'armed');
  g.fire(HOLD_TOTAL);
  assert.equal(g.surface.dataset.state, 'armed', 'a timer that outlived its hold changes nothing');
  assert.deepEqual(g.commits, []);
});

test('an armed hold lapses when no tap follows', async () => {
  const h = gestureHarness('hold_to_arm');
  h.at(700); h.arm();
  h.down(50, 50); await h.settle(); h.fire(HOLD_TOTAL); h.up();
  assert.equal(h.surface.dataset.state, 'held');
  h.fire(5000);
  assert.equal(h.surface.dataset.state, 'armed');
  h.at(1500); h.down(50, 50); h.up();
  assert.deepEqual(h.commits, [], 'the tap after the lapse begins a new hold, not a commit');
  assert.equal(h.surface.dataset.state, 'armed');
});

test('hold and drag: the handle unlocks only after the hold, and commits only when released on the target', async () => {
  const h = gestureHarness('hold_drag_target');
  assert.ok(textOf(h.node.querySelector('.action-target')).includes('refund £60.00'));
  h.at(700); h.arm();
  h.down(10, 100); await h.settle();
  h.move(200, 100);                                          // dragging before the hold completed is a wobble
  assert.equal(h.surface.dataset.state, 'armed');
  h.up();
  h.down(10, 100); await h.settle(); h.fire(HOLD_TOTAL);
  assert.equal(h.surface.dataset.state, 'held');
  h.move(120, 101); h.up();                                  // released short of the target
  assert.deepEqual(h.commits, []);
  assert.equal(h.surface.dataset.state, 'armed');
  h.down(10, 100); await h.settle(); h.fire(HOLD_TOTAL);
  h.move(150, 100); h.move(260, 102); h.up();                // onto the target
  assert.deepEqual(h.commits, [['prop_1', 'tok-1']]);
  assert.equal(h.surface.dataset.state, 'committing');
});

test('a settled surface answers to no gesture', async () => {
  for (const kind of ['swipe_commit', 'hold_to_arm', 'hold_drag_target']) {
    const h = gestureHarness(kind);
    h.at(700); h.arm();
    h.node.settle('revoked', 'Withdrawn');
    h.down(10, 100); await h.settle(); h.fire(HOLD_TOTAL); h.move(300, 100); h.up();
    assert.deepEqual(h.commits, [], kind);
    assert.equal(h.surface.dataset.state, 'revoked');
  }
});

test('the card prints the facts the gesture authorises and the footer names the gesture', () => {
  const node = proposalCard({ interaction: { kind: 'hold_drag_target', label: 'Hold, then drag', footer: 'nothing happens until you hold the card and drag', armed_after_ms: 650 },
    facts: [{ label: 'Refund', value: '£60.00 to the original card', tone: 'bad' }, { label: 'Customer emailed', value: 'yes' }, { label: 'Empty', value: '' }], ttl_s: 60 }, { timers: { set: () => 0, clear: () => {} }, now: () => 0 });
  const facts = node.querySelectorAll('dd').map((d) => d.textContent);
  assert.deepEqual(facts, ['£60.00 to the original card', 'yes']);
  assert.ok(textOf(node.querySelector('.action-meta')).includes('nothing happens until you hold the card and drag'));
  assert.ok(node.classList.contains('kind-hold_drag_target'));
});

test('an undo takes the kind the Mac gave it', () => {
  const node = UI.renderItem({ type: 'success', data: { title: 'Done', proposal_id: 'p', undo: { proposal_id: 'u', label: 'Undo', ttl_s: 60, interaction: 'hold_to_arm' } } }, { now: () => 0, timers: { set: () => 0, clear: () => {} } });
  assert.equal(node.querySelector('.action-surface').dataset.kind, 'hold_to_arm');
  assert.ok(textOf(node.querySelector('.action-surface')).toLowerCase().includes('hold'));
});

test('the attention card follows the order it reads and is replaced by a later reading', () => {
  const parent = document.createElement('div');
  const order = UI.renderItem({ type: 'order', data: { order_id: 'gid://shopify/Order/1', order_number: '#1930', detail: true, items: [] } });
  const other = UI.renderItem({ type: 'assistant', data: { text: 'after' } });
  parent.appendChild(order); parent.appendChild(other);
  UI.hydrateOrder(order, { order_id: 'gid://shopify/Order/1', pending: [], attention: [{ kind: 'email', title: 'Customer emailed', detail: 'from x — say “reply”', level: 'amber' }] });
  assert.deepEqual(parent.childNodes.map((n) => n.dataset.type), ['order', 'attention', 'assistant']);
  assert.ok(textOf(parent.childNodes[1]).includes('Customer emailed') && textOf(parent.childNodes[1]).includes('say “reply”'));
  assert.equal(parent.childNodes[1].querySelectorAll('button').length, 0);
  UI.hydrateOrder(order, { order_id: 'gid://shopify/Order/1', pending: [], attention: [{ kind: 'stock', title: 'Oversold: Jeans', detail: '', level: 'red' }] });
  assert.deepEqual(parent.childNodes.map((n) => n.dataset.type), ['order', 'attention', 'assistant']);
  assert.ok(textOf(parent.childNodes[1]).includes('Oversold') && !textOf(parent.childNodes[1]).includes('Customer emailed'));
  UI.hydrateOrder(order, { order_id: 'gid://shopify/Order/1', pending: [], attention: [] });
  assert.deepEqual(parent.childNodes.map((n) => n.dataset.type), ['order', 'assistant']);
});


// ---- the read layer's cards

test('a ranking draws rank, label, the primary figure, a bar and the totals, all as text', () => {
  const out = UI.render([{ type: 'ranking', data: {
    title: 'Best sellers', subtitle: 'last 30 days', mode: '',
    rows: [
      { rank: 1, label: 'Convict Joggers', ref: 'gid://shopify/Product/1', kind: 'product', primary: { key: 'units', label: 'units', value: '41' }, secondary: { key: 'revenue', label: 'revenue', value: '£1,845.00' }, pct: 54, lines: [], known: true },
      { rank: 2, label: HOSTILE, ref: '', kind: '', primary: { key: 'units', label: 'units', value: '22' }, secondary: null, pct: 29, lines: [], known: true },
    ],
    totals: [{ key: 'units', label: 'units', value: '76' }], measured: ['units', 'revenue'], derived: ['share'], note: 'From the last 30 days.', complete: true, truncated: false,
  } }]);
  assert.equal(out.nodes.length, 1);
  const node = out.nodes[0];
  assert.equal(node.dataset.type, 'ranking');
  const ranks = node.querySelectorAll('.rank');
  assert.equal(ranks.length, 2);
  assert.equal(ranks[0].dataset.ref, 'gid://shopify/Product/1');
  assert.equal(ranks[0].querySelector('.rank-v').textContent, '41');
  assert.equal(ranks[0].querySelector('.rank-fill').style.getPropertyValue('--w'), '54%');
  assert.ok(textOf(ranks[1]).includes(HOSTILE), 'a hostile label is drawn as text');
  assert.equal(node.querySelectorAll('img').length, 0);
  assert.ok(textOf(node).includes('76') && textOf(node).includes('Derived: share') && textOf(node).includes('From the last 30 days.'));
});

test('totals that are not the list\'s own say whose they are, above the tiles', () => {
  // "any emails need my attention" drew 25 customers over tiles reading 272 ORDERS and
  // £16,681.45 REVENUE: the month's totals, standing under the list as if they were its own.
  const data = {
    title: 'Recent customers', subtitle: 'last 30 days', mode: '', truncated: true, complete: true,
    rows: [{ rank: 1, label: 'Ann Able', ref: '', kind: '', primary: { key: 'orders', label: 'orders', value: '2' }, secondary: null, pct: 100, lines: [], known: true }],
    totals: [{ key: 'orders', label: 'orders', value: '272' }, { key: 'revenue', label: 'revenue', value: '£16,681.45' }],
    totals_label: 'Whole period (last 30 days), not just this list',
  };
  const node = UI.render([{ type: 'ranking', data }]).nodes[0];
  const kids = node.children;
  const label = kids.findIndex((n) => textOf(n) === data.totals_label);
  const tiles = kids.findIndex((n) => n.classList.contains('stats'));
  assert.ok(label !== -1 && tiles !== -1 && label === tiles - 1, `the label sits directly above the tiles (${label}, ${tiles})`);
  const own = UI.render([{ type: 'ranking', data: Object.assign({}, data, { totals_label: '' }) }]).nodes[0];
  assert.ok(!textOf(own).includes('Whole period'), 'totals that are the rows\' own need no label');
});

test('restock priority shows measured and derived lines and marks unknown stock', () => {
  const out = UI.render([{ type: 'ranking', data: { title: 'Restock priority', subtitle: 'last 7 days', mode: 'restock', rows: [
    { rank: 1, label: 'Convict Joggers · Black / L', primary: { key: 'days_cover', label: 'days cover', value: '1.6' }, secondary: { key: 'stock', label: 'in stock', value: '3' }, pct: null, lines: [{ key: 'stock', label: 'in stock', value: '3', derived: false }, { key: 'velocity', label: 'a day', value: '1.86', derived: true }], known: true },
    { rank: 2, label: 'Yard Jeans · Blue / M', primary: { key: 'days_cover', label: 'days cover', value: '—' }, secondary: null, pct: null, lines: [], known: false },
  ], totals: [], measured: ['units', 'stock'], derived: ['velocity', 'days_cover'], note: 'Not a forecast.', complete: true } }]);
  const node = out.nodes[0];
  const ranks = node.querySelectorAll('.rank');
  assert.ok(ranks[1].classList.contains('is-unknown'));
  assert.equal(ranks[0].querySelectorAll('.rank-fill').length, 0, 'no bar for a cover');
  const lines = ranks[0].querySelectorAll('.rank-lines')[0].children;
  assert.equal(lines[1].className, 'derived');
  assert.ok(textOf(node).includes('Not a forecast.'));
});

test('a table, a comparison, a matrix, a trend and a metric group all render from strings', () => {
  const items = [
    { type: 'table', data: { title: 'By product', subtitle: 'this month', columns: [{ key: 'product', label: 'Product', numeric: false }, { key: 'units', label: 'units', numeric: true }], rows: [{ ref: 'gid://shopify/Product/1', cells: ['Convict Joggers', '41'] }], note: '', truncated: true, complete: true } },
    { type: 'comparison', data: { title: 'This week against last', subtitle: 'this week', current: { label: 'this week', metrics: [{ key: 'revenue', label: 'revenue', value: '£4,812.00' }] }, previous: { label: 'last week', metrics: [{ key: 'revenue', label: 'revenue', value: '£4,109.00' }] }, changes: [{ key: 'revenue', label: 'revenue', delta: '+£703.00', pct: '+17.1%', direction: 'up' }], note: '', complete: true } },
    { type: 'variant_matrix', data: { title: 'Units by colour and size', subtitle: 'this month', row_label: 'Colour', col_label: 'Size', rows: ['Black', 'Pink'], cols: ['S', 'M', 'L'], cells: [{ row: 'Black', col: 'L', value: 13, display: '13' }, { row: 'Pink', col: 'M', value: 5, display: '5' }], metric: 'units', note: '' } },
    { type: 'trend', data: { title: 'Revenue by day', subtitle: 'last 7 days', metric: 'revenue', points: [{ label: '2026-09-07', value: 120.5, display: '£120.50' }, { label: '2026-09-08', value: 300, display: '£300.00' }], total: '£420.50', note: '' } },
    { type: 'metric_group', data: { title: 'Unfulfilled', subtitle: 'last 90 days', metrics: [{ key: 'orders', label: 'orders', value: '23', measured: true }, { key: 'aov', label: 'avg order', value: '£64.39', measured: false }], note: '', complete: false } },
  ];
  const out = UI.render(items);
  assert.deepEqual(out.skipped, []);
  assert.equal(out.nodes.length, 5);
  assert.ok(out.hasContext);
  const [table, comparison, matrix, trend, metrics] = out.nodes;
  assert.equal(table.querySelectorAll('td').length, 2);
  assert.equal(table.querySelectorAll('td')[1].className, 'num');
  assert.ok(textOf(table).includes('More rows than shown.'));
  assert.equal(comparison.querySelectorAll('.change')[0].className, 'change up');
  assert.ok(textOf(comparison).includes('+£703.00') && textOf(comparison).includes('last week'));
  assert.equal(matrix.querySelectorAll('th').length, 4);
  const cells = matrix.querySelectorAll('td');
  assert.equal(cells.length, 8, 'two rows, a label and three sizes each');
  assert.ok(cells.some((c) => c.className === 'hot' && c.textContent === '13'));
  assert.equal(trend.querySelectorAll('.bar').length, 2);
  assert.equal(trend.querySelectorAll('.bar')[1].dataset.pct, '100');
  assert.ok(textOf(trend).includes('£420.50'));
  assert.ok(textOf(metrics).includes('avg order · derived') && textOf(metrics).includes('Partial'));
});

test('a working set says what "these" means and what it comes to, and keeps its id on the node', () => {
  // It is a strip, not a card: it always sits under a list of the very same members and the
  // nav bar carries the set as a chip, so re-listing "#1938 · …" and explaining the word
  // "these" cost 276px of a 1280px screen to repeat what had just been read. What must still
  // be here is the count, where it came from, the arithmetic over the set, and the id — that
  // last one is what "act on all of them" resolves against.
  const out = UI.render([
    { type: 'working_set', data: { set_id: 'set_abc123456789', kind: 'orders', count: 23, label: 'Delayed orders ' + HOSTILE, parent_label: 'Unfulfilled ' + HOSTILE, step: 'filter', sample: [{ ref: 'gid://shopify/Order/1', label: '#1938' }, { ref: 'gid://shopify/Order/2', label: HOSTILE }], truncated: true, lines: [{ label: 'value', value: '£1,481.00' }] } },
    { type: 'working_set', data: { set_id: 'set_def', kind: 'customers', count: 2, label: 'emailed us', step: 'correlate', sample: [], lines: [] } },
  ]);
  assert.deepEqual(out.skipped, []);
  const [narrowed, correlated] = out.nodes;
  assert.equal(narrowed.dataset.set, 'set_abc123456789');
  assert.equal(narrowed.querySelectorAll('script, img').length, 0, 'hostile labels stay text');
  const t = textOf(narrowed);
  assert.ok(t.includes('Narrowed'), 'says how the set was made');
  assert.ok(t.includes('23 orders') && t.includes('first 500'), 'says how many, and that it is capped');
  assert.ok(t.includes('from Unfulfilled'), 'says what it was narrowed from');
  assert.ok(t.includes('£1,481.00'), 'carries the arithmetic, which is the part only it has');
  assert.ok(!t.includes('these'), 'does not spend a line explaining the word');
  assert.ok(textOf(correlated).includes('Cross-referenced') && textOf(correlated).includes('2 customers'));
  assert.ok(!textOf(correlated).includes('from '), 'a set with no parent claims none');
});

test('a working set strip does not re-list the members the card above it just listed', () => {
  // The sample is still on the wire — the model and the batch card both use it — and the strip
  // deliberately does not draw it. This is the duplication the Phase 2 audit measured.
  const out = UI.render([{ type: 'working_set', data: {
    set_id: 'set_abc', kind: 'orders', count: 3, label: 'Today', step: 'query',
    sample: [{ ref: 'gid://shopify/Order/1', label: '#1940' }, { ref: 'gid://shopify/Order/2', label: '#1938' }],
    lines: [{ label: 'value', value: '£162.00' }],
  } }]);
  const t = textOf(out.nodes[0]);
  assert.ok(t.includes('£162.00'), 'the totals are the reason it exists');
  assert.ok(!t.includes('#1940') && !t.includes('#1938'), 'the members belong to the list, not to the strip');
});

test('a batch card names the count, the scope, the excluded and every member, and its gesture carries the batch id', async () => {
  const commits = [];
  const arms = [];
  const timers = [];
  let t = 0;
  const opts = {
    now: () => t, blocked: () => false, trackWidth: 356,
    onCommit: (id, node, nonce) => commits.push([id, nonce || '']),
    onArm: (id) => { arms.push(id); return Promise.resolve('tok-9'); },
    timers: { set: (fn, ms) => { timers.push({ fn, ms }); return timers.length; }, clear: () => {} },
  };
  const node = UI.renderItem({ type: 'batch_action', data: {
    batch_id: 'batch_abc', status: 'pending', risk: 'red', operation: 'batch_order_tags_add', title: 'Add tags to 21 orders ' + HOSTILE, summary: 'delayed-sept',
    set: { set_id: 'set_1', label: 'delayed ' + HOSTILE, kind: 'orders', count: 23 }, requested: 23, eligible: 21, excluded_count: 2,
    excluded: [{ label: '#1902', reason: 'already has those tags' }, { label: HOSTILE, reason: HOSTILE }],
    members: ['#1938', '#1937', '#1935', '#1934', '#1931', '#1930'], facts: [{ label: 'Tags', value: 'delayed-sept' }],
    interaction: { kind: 'hold_to_arm', label: 'Hold to arm, then tap', footer: 'nothing happens until you hold', armed_after_ms: 650 }, ttl_s: 120, reversible: true, commit: { allowed: true },
  } }, opts);
  assert.equal(node.dataset.proposal, 'batch_abc');
  assert.equal(node.dataset.set, 'set_1');
  assert.equal(node.querySelectorAll('script, img').length, 0);
  const words = textOf(node);
  assert.ok(words.includes('Proposed for 21 of 23') && words.includes('delayed') && words.includes('2 excluded') && words.includes('already has those tags'));
  assert.equal(node.querySelector('.batch-members').querySelectorAll('li').length, 6, 'every member is listed to inspect');
  assert.ok(words.includes(HOSTILE), 'hostile text is printed, never parsed');
  const surface = node.querySelector('.action-surface');
  assert.equal(surface.dataset.kind, 'hold_to_arm');
  t = 700; surface.dataset.state = 'armed';
  surface.dispatch('pointerdown', { clientX: 10, clientY: 10, pointerId: 1 });
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(arms, ['batch_abc'], 'the hold is told to the Mac under the batch id');
  for (const x of timers) if (x.ms === 1050 && !x.fired) { x.fired = true; x.fn(); }
  surface.dispatch('pointerup', { pointerId: 1 });
  t = 1500;
  surface.dispatch('pointerdown', { clientX: 10, clientY: 10, pointerId: 1 });
  surface.dispatch('pointerup', { pointerId: 1 });
  assert.deepEqual(commits, [['batch_abc', 'tok-9']]);
});

test('a batch result counts what was proven, lists each member with its outcome, and offers the undo batch', () => {
  const node = UI.renderItem({ type: 'batch_result', data: {
    batch_id: 'batch_abc', operation: 'batch_order_tags_add', title: 'Tags added: 20 of 21', detail: 'delayed · 23 orders · 2 excluded before the gesture', all_verified: false, summary: '20 applied, 1 not',
    counts: { requested: 23, eligible: 21, excluded: 2, verified: 20, unverified: 0, stale: 0, failed: 1, not_attempted: 0 },
    rows: [{ label: '#1938', outcome: 'applied', code: 'verified' }, { label: '#1935', outcome: 'not applied', code: 'failed' }, { label: '#1902', outcome: 'excluded: already has those tags', code: 'excluded' }],
    note: 'The 1 marked not applied was left as it was.',
    undo: { batch_id: 'batch_undo', label: 'Undo all', interaction: 'hold_to_arm', ttl_s: 120 },
  } }, { now: () => 0, timers: { set: () => 0, clear: () => {} } });
  const words = textOf(node);
  assert.ok(words.includes('20 applied, 1 not') && words.includes('Tags added: 20 of 21') && words.includes('not applied') && words.includes('The 1 marked not applied was left as it was.'));
  assert.equal(node.querySelector('.counts').querySelectorAll('.stat').length, 3, 'only the non-zero counts are shown');
  assert.equal(node.querySelector('.batch-list').querySelectorAll('li').length, 3);
  assert.equal(node.querySelectorAll('li').find((li) => li.classList.contains('bad')).querySelector('.batch-why').textContent, 'not applied');
  assert.equal(node.dataset.proposal, 'batch_undo', 'the live id on the card is the undo batch');
  assert.equal(node.querySelector('.action-surface').dataset.kind, 'hold_to_arm');
  const clean = UI.renderItem({ type: 'batch_result', data: { batch_id: 'b', title: 'Archived: 3 of 3', all_verified: true, counts: { requested: 3, eligible: 3, verified: 3 }, rows: [] } });
  assert.ok(textOf(clean).includes('Done') && !textOf(clean).includes('in part'));
});

/* ---------------------------------------------------- the compact tabbed cards */

test('an order is five tabs with one open, and the tab it opens on is the Mac\'s to choose', () => {
  const data = {
    order_id: 'gid://shopify/Order/9', order_number: '#1938', detail: true, total: '£60.00',
    items: [{ title: 'Jeans', quantity: 1 }], shipping_address: { lines: ['12 Elm Road'], city: 'Leeds' },
    history: { orders: 2, spent: '£120.00' }, email: { available: true, threads: [] }, pending: [],
  };
  const first = UI.renderItem({ type: 'order', data });
  assert.equal(first.querySelector('.tabbed').dataset.tab, 'overview');
  // Changed in Phase 5, for D-2. This used to pass `{ tab: 'shipping' }` — ONE value for the
  // whole branch, which is the defect: it put every later card on the tab tapped on one
  // record. The rule it was written for is intact and is now about a RECORD: the tab is
  // looked up by the card's own render identity, so a card comes back on the tab IT was left
  // on and a card for another record does not.
  const restored = UI.renderItem({ type: 'order', data }, { tabOf: (id) => (id === 'order:gid://shopify/Order/9' ? 'shipping' : '') });
  assert.equal(restored.querySelector('.tabbed').dataset.tab, 'shipping', 'a card comes back on the tab it was left on');
  const other = UI.renderItem({ type: 'order', data: Object.assign({}, data, { order_id: 'gid://shopify/Order/10', order_number: '#1939' }) },
    { tabOf: (id) => (id === 'order:gid://shopify/Order/9' ? 'shipping' : '') });
  assert.equal(other.querySelector('.tabbed').dataset.tab, 'overview', 'and another order does not take its tab');
  const open = restored.querySelectorAll('.panel').filter((p) => !p.hidden);
  assert.equal(open.length, 1);
  assert.equal(open[0].dataset.panel, 'shipping');
});

test('moving between tabs tells the Mac, and only ever names the tab', () => {
  const told = [];
  const node = UI.renderItem({ type: 'order', data: {
    order_id: 'o1', order_number: '#1', detail: true, items: [], pending: [],
  } }, { onTab: (id, name, label, kind) => told.push([id, name, label, kind]) });
  const email = node.querySelectorAll('.tab').find((t) => t.dataset.tab === 'email');
  email.dispatch('click');
  // Changed in Phase 5, for D-2: a tap now names the RECORD it was on, by render identity,
  // because a tab that belongs to nothing in particular ends up belonging to everything.
  assert.deepEqual(told, [['order:o1', 'email', 'Email', 'order']]);
  assert.equal(node.querySelector('.tabbed').dataset.tab, 'email');
});

test('a customer with nothing behind a tab is not given a tab bar', () => {
  const bare = UI.renderItem({ type: 'customer', data: { name: 'Millie Rogers', orders: 2, spent: '£120.00' } });
  assert.equal(bare.querySelectorAll('.tab').length, 0);
  const full = UI.renderItem({ type: 'customer', data: {
    name: 'Millie Rogers', orders: 2, spent: '£120.00', history: { orders: 2, spent: '£120.00', recent: [] },
    related_email: { available: true, threads: [] },
  } });
  assert.deepEqual(full.querySelectorAll('.tab').map((t) => t.textContent), ['Overview', 'Orders', 'Email']);
});

/* ------------------------------------------------ what never arrived, said so */

test('an order whose inbox never arrived says so, on the panel and on the tab', () => {
  const node = UI.renderItem({ type: 'order', data: {
    order_number: '#1938', customer_name: 'Mia Jones', detail: true, items: [{ title: 'Convict Hoodie', quantity: 1 }],
    pending: ['email', 'history'],
  } }, {});
  assert.ok(node.dataset.pending.indexOf('email') !== -1, 'the card starts out waiting');
  const settled = UI.settleOrder(node);
  assert.deepEqual(settled.sort(), ['email', 'history']);
  assert.equal(node.dataset.pending, '', 'it is not waiting any more');
  const email = node.querySelector('.sec-email');
  assert.ok(email && /could not be read/.test(email.textContent), 'the region says the read failed');
  assert.ok(/check the inbox for #1938/.test(email.textContent), 'and says what to say to try again');
  assert.ok(!/Checking the inbox/.test(node.textContent), 'nothing pretends to still be working');
  const marked = node.querySelectorAll('[data-unread="1"]');
  assert.equal(marked.length, 2, 'both tabs carry the mark');
  assert.ok(marked.every((t) => t.getAttribute('role') === 'tab' && t.querySelector('.tab-mark')), 'on the tab, visibly');
  assert.deepEqual(UI.settleOrder(node), [], 'settling twice changes nothing');
});

test('a failed customer read is not "no customer"', () => {
  const none = UI.renderItem({ type: 'order', data: { detail: true, order_number: '#1930', items: [], pending: [], history: null } });
  assert.ok(textOf(none.querySelector('.sec-history')).includes('No customer is attached'));
  const failed = UI.renderItem({ type: 'order', data: { detail: true, order_number: '#1930', customer_name: 'Mia Jones', items: [], pending: [], history: { available: false, reason: 'read_failed' } } });
  const words = textOf(failed.querySelector('.sec-history'));
  assert.ok(words.includes('couldn’t load the customer') && !words.includes('No customer'), words);
  assert.ok(words.includes('try again'), 'and says what to say');
  const later = UI.renderItem({ type: 'order', data: { detail: true, order_number: '#1930', items: [], pending: ['history', 'email'] } });
  UI.hydrateOrder(later, { pending: [], failed: ['history'], history: { available: false, reason: 'read_failed' }, email: { available: true, threads: [] } });
  assert.ok(textOf(later.querySelector('.sec-history')).includes('couldn’t load'));
  assert.equal(later.querySelectorAll('[data-unread="1"]').length, 1, 'the Customer tab is marked, the Email tab is not');
  assert.ok(textOf(later.querySelector('[data-unread="1"]')).toLowerCase().includes('customer'));
});

test('an inbox that could not be checked is not "no email"', () => {
  const off = UI.renderItem({ type: 'order', data: { detail: true, items: [], pending: [], email: { available: false, reason: 'Gmail is not configured' } } });
  assert.ok(textOf(off.querySelector('.sec-email')).includes('not configured'));
  const failed = UI.renderItem({ type: 'order', data: { detail: true, items: [], pending: [], email: { available: false, reason: 'unavailable' } } });
  const words = textOf(failed.querySelector('.sec-email'));
  assert.ok(words.includes('couldn’t check the inbox') && !words.includes('No recent email'), words);
});

/* -------------------------------------------------------- a button beside a row */

test('an email row carries the buttons the Mac listed, and posts only which and which', () => {
  const asked = [];
  const node = UI.renderItem({ type: 'email_list', data: { threads: [
    { thread_id: 't1', from: 'Millie', subject: 'Where is it', actions: [{ id: 'email_archive', label: 'Archive', mode: 'stage', enabled: true, detail: 'Out of the inbox; nothing is deleted.' }] },
    { thread_id: 't2', from: 'Gus', subject: 'Thanks' },
  ] } }, { onRowAction: (action, ref) => asked.push([action, ref]) });
  const rows = node.querySelectorAll('.row');
  const button = rows[0].querySelector('.row-btn');
  assert.equal(button.textContent, 'Archive');
  assert.equal(button.dataset.action, 'email_archive');
  assert.equal(button.dataset.ref, 't1');
  assert.equal(rows[1].querySelectorAll('.row-btn').length, 0, 'a row the Mac gave no action has no button');
  button.dispatch('click', { stopPropagation() {} });
  assert.deepEqual(asked, [['email_archive', 't1']], 'the id and the row, and nothing else');
  assert.ok(button.disabled, 'and the button cannot be pressed twice while it is being prepared');
});

test('an email thread carries a rail: Reply primes the hold, Archive asks the Mac to prepare', () => {
  const primed = [];
  const staged = [];
  const node = UI.renderItem({ type: 'email_thread', data: {
    thread_id: 'aa70d3f83dbef06e', subject: 'Order #1938', messages: [{ from: 'Mia', body: 'Can I add to it?' }],
    actions: [
      { id: 'reply', label: 'Reply', mode: 'ask', enabled: true, instruction: 'Reply to this email', family: 'email.reply' },
      { id: 'email_archive', label: 'Archive', mode: 'stage', enabled: true, detail: 'Out of the inbox; nothing is deleted.' },
    ],
  } }, { onAction: (a) => primed.push(a.id), onRowAction: (action, ref) => staged.push([action, ref]) });
  const chips = node.querySelectorAll('.rail-chip');
  assert.deepEqual(chips.map((c) => c.textContent), ['Reply', 'Archive']);
  assert.equal(chips[0].dataset.family, 'email.reply', 'the chip says which spoken control it arms');
  assert.equal(chips[1].dataset.ref, 'aa70d3f83dbef06e', 'a staged chip knows which record it is on');
  chips[0].dispatch('click', { stopPropagation() {} });
  chips[1].dispatch('click', { stopPropagation() {} });
  assert.deepEqual(primed, ['reply']);
  assert.deepEqual(staged, [['email_archive', 'aa70d3f83dbef06e']], 'the id and the thread, and nothing else');
  assert.ok(chips[1].disabled, 'and Archive cannot be pressed twice while it is being prepared');
});

test('a weighed rail draws one chip loud and the rest behind a disclosure that names them', () => {
  /* §25 · one primary action, a secondary group, then more — and the renderer never overturns
     the weight the Mac decided. It used to: `primary.length ? primary : list_` drew EVERY chip
     at full weight whenever nothing was marked primary, which is exactly what a rail of
     disabled chips is, so "a dead chip must not sit beside a live one" held in the payload and
     failed on the glass. */
  const order = (actions) => UI.renderItem({ type: 'order', data: { detail: true, order_number: '#1938', items: [], pending: [], actions } }, {});
  const weighed = order([
    { id: 'fulfil', label: 'Fulfil', risk: 'red', enabled: true, instruction: 'Fulfil order 1938', mode: 'ask', priority: 'primary' },
    { id: 'address', label: 'Address', risk: 'red', enabled: true, instruction: 'Change the address on order 1938', mode: 'ask', priority: 'secondary' },
    { id: 'cancel', label: 'Cancel', risk: 'red', enabled: false, reason: 'already shipped', instruction: 'Cancel order 1938', mode: 'ask', priority: 'secondary' },
  ]);
  const inside = (node, cls) => (node ? node.querySelectorAll(cls) : []);
  assert.deepEqual(inside(weighed.querySelector('.rail-primary'), '.rail-chip').map((c) => c.dataset.action), ['fulfil']);
  assert.deepEqual(inside(weighed.querySelector('.rail-rest'), '.rail-chip').map((c) => c.dataset.action), ['address', 'cancel']);
  assert.equal(weighed.querySelector('.rail-more-label').textContent, '2 more');
  assert.equal(weighed.querySelector('.rail-rest').hidden, true, 'behind the disclosure until it is asked for');

  // Nothing can be done to this order. The dead chips stay reachable — §19, the owner who
  // would ask is told no — but they do not lead, and the control names what it holds rather
  // than counting past a chip that is not there.
  const allDead = order([
    { id: 'cancel', label: 'Cancel', risk: 'red', enabled: false, reason: 'already cancelled', instruction: 'Cancel order 1938', mode: 'ask', priority: 'secondary' },
    { id: 'refund', label: 'Refund', risk: 'red', enabled: false, reason: 'fully refunded', instruction: 'Refund order 1938', mode: 'ask', priority: 'secondary' },
  ]);
  assert.equal(allDead.querySelectorAll('.rail-primary').length, 0, 'no dead chip at full weight');
  assert.equal(allDead.querySelector('.rail-more-label').textContent, '2 unavailable');
  assert.deepEqual(inside(allDead.querySelector('.rail-rest'), '.rail-chip').map((c) => c.getAttribute('aria-disabled')), ['true', 'true']);
  for (const chip of allDead.querySelectorAll('.rail-chip')) {
    assert.ok(textOf(chip).length > 6, `§19: a disabled control says why — ${textOf(chip)}`);
  }
});

test('a staged chip with no record to act on is not drawn at all, whatever the Mac said', () => {
  /* CHANGED IN PHASE 5 (§19/§25). It used to render, dimmed, with `aria-disabled="true"` —
     and with NOTHING SAYING WHY, because `reason` is empty exactly when the Mac believes the
     action is enabled. A dead control that explains nothing is worse than no control: §19
     requires a disabled control to say why in the owner's words, and the honest answer here
     ("the page has no record to act on") is not the owner's business. So it is removed, which
     is D-6's own conclusion — the control was drawn before its destination was known to
     exist. What the test asserted is unchanged and stronger: a tap can never reach
     `onRowAction`, because there is nothing to tap. */
  const node = UI.renderItem({ type: 'email_thread', data: {
    subject: 's', messages: [{ from: 'M', body: 'b' }],
    actions: [{ id: 'email_archive', label: 'Archive', mode: 'stage', enabled: true }],
  } }, { onRowAction: () => { throw new Error('must not be asked'); } });
  assert.equal(node.querySelector('.rail-chip'), null, 'no chip, so no dead chip');
  assert.equal(node.querySelectorAll('.rail').length, 0, 'and no empty rail around it');
});

test('a row action is inert when the page has nowhere to send it', () => {
  const node = UI.renderItem({ type: 'email_list', data: { threads: [
    { thread_id: 't1', from: 'M', subject: 's', actions: [{ id: 'email_archive', label: 'Archive', enabled: true }] },
  ] } }, {});
  const button = node.querySelector('.row-btn');
  assert.doesNotThrow(() => button.dispatch('click', { stopPropagation() {} }));
});

// The renderer's two array helpers are not interchangeable, and one of them failing quietly
// is how a whole section of a card disappears while the code that draws it still reads fine.
test('a card region fed plain strings renders them', () => {
  const data = {
    build: 'b7', counts: { reads: 12, changes: 3 }, writes_enabled: true,
    groups: [{ area: 'shop', label: 'The shop', items: [{ what: 'Read an order', kind: 'read', state: 'ready' }] }],
    examples: ['Show me order 1938', "Show me today's orders"],
    changed: { added: ['order_reopen: show it again'], gone: ['old_thing: went away'] },
  };
  const out = UI.render([{ type: 'capability', data }], {});
  assert.equal(out.nodes.length, 1);
  const body = textOf(out.nodes[0]);
  // The chips: real questions, drawn, and carrying the text to ask.
  assert.match(body, /Try asking/);
  for (const q of data.examples) assert.ok(body.includes(q), `missing chip ${q}`);
  // And the build delta, which is fed the same shape and vanished the same way.
  assert.match(body, /Since the last build/);
  assert.ok(body.includes('order_reopen: show it again'));
  assert.ok(body.includes('old_thing: went away'));
});

test('the strings a card renders are text, never markup', () => {
  const out = UI.render([{ type: 'capability', data: { build: 'b', examples: [HOSTILE], groups: [] } }], {});
  const body = textOf(out.nodes[0]);
  assert.ok(body.includes(HOSTILE), 'the hostile string survives as text');
  assert.ok(!out.nodes[0].allHtml || !/<script/i.test(out.nodes[0].allHtml()), 'and never as markup');
});

// ---- the graph family: the order under an email thread, and the reply-state line.

test('a confidently linked order is one tappable strip under the thread head, with its reasons', () => {
  const node = UI.renderItem({ type: 'email_thread', data: {
    thread_id: 'aa70d3f83dbef06e', subject: 'Order 1938 — can I add to it?', messages: [{ from: 'Mia Jones', body: 'Is it too late?' }],
    linked_order: { order_id: 'gid://shopify/Order/1938', order_number: '#1938', total: '£89.00', fulfillment: 'unfulfilled', customer_name: 'Mia Jones' },
    linked_customer: { customer_id: 'gid://shopify/Customer/7001', name: 'Mia Jones' },
    link_confidence: 'confident', link_provenance: ['order number 1938 in the subject', 'sender is the customer on that order'],
  } }, {});
  const strip = node.querySelectorAll('.link-strip')[0];
  assert.ok(strip, 'the strip is drawn');
  assert.equal(strip.dataset.kind, 'order', 'a tap opens an order');
  assert.equal(strip.dataset.ref, 'gid://shopify/Order/1938', 'by the id the Mac gave, never a number typed on the page');
  assert.equal(strip.getAttribute('role'), 'button');
  assert.match(textOf(strip), /Linked order/);
  assert.match(textOf(strip), /#1938 · £89.00 · unfulfilled/);
  const customer = node.querySelectorAll('.link-customer')[0];
  assert.ok(customer, 'the customer bridge is a chip');
  assert.equal(customer.dataset.kind, 'customer');
  assert.equal(customer.dataset.ref, 'gid://shopify/Customer/7001');
  assert.match(textOf(node.querySelectorAll('.link-why')[0]), /order number 1938 in the subject · sender is the customer on that order/);
  assert.equal(node.querySelectorAll('.link-none').length, 0, 'no "no order" line beside a linked order');
});

test('several possible orders are chips, each a door to its own order', () => {
  const node = UI.renderItem({ type: 'email_thread', data: {
    thread_id: 'aa70d3f83dbef06e', subject: 'Hello', messages: [{ from: 'Mia', body: 'x' }],
    possible_orders: [
      { order_id: 'gid://shopify/Order/1938', order_number: '#1938', total: '£89.00', fulfillment: 'unfulfilled' },
      { order_id: 'gid://shopify/Order/1912', order_number: '#1912', total: '£65.00', fulfillment: 'fulfilled' },
    ],
    link_confidence: 'possible', link_provenance: ['sender is the customer on 2 recent orders'],
  } }, {});
  assert.equal(node.querySelectorAll('.link-strip').length, 0, 'a possible link is never drawn as the confident strip');
  const chips = node.querySelectorAll('.link-chip');
  assert.equal(chips.length, 2);
  assert.deepEqual(chips.map((c) => c.dataset.ref), ['gid://shopify/Order/1938', 'gid://shopify/Order/1912']);
  assert.ok(chips.every((c) => c.dataset.kind === 'order'));
  assert.match(textOf(node), /Possibly about/);
  assert.match(textOf(node), /#1912 · £65.00 · fulfilled/);
});

test('no confident order is a quiet line with the reason, and nothing on it opens anything', () => {
  const node = UI.renderItem({ type: 'email_thread', data: {
    thread_id: 'a413d264183cfe94', subject: 'Report', messages: [{ from: 'Shipping Updates', body: 'x' }],
    linked_order: null, possible_orders: [], linked_customer: null,
    link_confidence: 'none', link_provenance: ['order cache not warm'],
  } }, {});
  assert.match(textOf(node.querySelectorAll('.link-none')[0]), /No confident order is linked/);
  assert.match(textOf(node.querySelectorAll('.link-why')[0]), /order cache not warm/);
  assert.equal(node.querySelectorAll('.link-strip').length + node.querySelectorAll('.link-chip').length, 0);
  // A thread from before the strip existed still renders: the fields are simply absent.
  const old = UI.renderItem({ type: 'email_thread', data: { subject: 's', messages: [{ from: 'M', body: 'b' }] } }, {});
  assert.ok(old && old.querySelectorAll('.link-none').length === 1);
});

test('the link strip prints the Mac\'s strings as text and never as markup', () => {
  const node = UI.renderItem({ type: 'email_thread', data: {
    subject: 's', messages: [{ from: 'M', body: 'b' }],
    linked_order: { order_id: 'gid://shopify/Order/1', order_number: HOSTILE, total: HOSTILE, fulfillment: HOSTILE },
    link_confidence: 'confident', link_provenance: [HOSTILE],
  } }, {});
  const body = textOf(node);
  assert.ok(body.includes(HOSTILE));
  assert.ok(!node.allHtml || !/<script/i.test(node.allHtml()));
});

test('the reply state is one line, warn-toned while the customer is waiting, and opens its thread', () => {
  const waiting = UI.renderItem({ type: 'reply_state', data: {
    thread_id: 'aa70d3f83dbef06e', order_number: '#1938', latest_direction: 'inbound', replied: false,
    waiting_since: '5h ago', last_from: 'Mia', confidence: 'confident', provenance: ['sender is the customer on that order'],
  } }, {});
  const line = waiting.querySelectorAll('.reply-line')[0];
  assert.equal(textOf(line), 'Waiting since 5h ago · last from Mia · no reply from us');
  assert.ok(line.classList.contains('warn'));
  assert.match(textOf(waiting), /about #1938/);
  const open = waiting.querySelectorAll('.link-chip')[0];
  assert.equal(open.dataset.kind, 'email_thread');
  assert.equal(open.dataset.ref, 'aa70d3f83dbef06e');
  const answered = UI.renderItem({ type: 'reply_state', data: { latest_direction: 'outbound', replied: true, replied_since: '2h ago', last_from: 'us' } }, {});
  const calm = answered.querySelectorAll('.reply-line')[0];
  assert.equal(textOf(calm), 'We replied 2h ago · last from us');
  assert.ok(!calm.classList.contains('warn'));
  // The Mac's own line wins when it sent one, verbatim.
  const given = UI.renderItem({ type: 'reply_state', data: { line: HOSTILE } }, {});
  assert.equal(textOf(given.querySelectorAll('.reply-line')[0]), HOSTILE);
});


/* ---- the variant picker (app/families/order_edit.py). What is asserted here is the write
   boundary as it appears on the glass: Add carries the command's name and three identities
   and a number, it carries nothing until a variant is chosen, and it can never carry a
   price, a total or anything else the Mac decided. */

const PICKER = {
  order_id: 'gid://shopify/Order/1938', order_number: '#1938', count: 2, quantity: 1, max_quantity: 20,
  confident_variant_id: null, note: '',
  candidates: [
    { variant_id: 'gid://shopify/ProductVariant/9102', title: 'Convict Hoodie', variant: 'Black / M', options: ['Black', 'M'], sku: 'CRK-HOOD-BLK-M', price: '£60.00', available: 4, for_sale: true },
    { variant_id: 'gid://shopify/ProductVariant/9104', title: 'Convict Hoodie', variant: 'Bone / M', options: ['Bone', 'M'], sku: 'CRK-HOOD-BON-M', price: '£60.00', available: 9, for_sale: true },
  ],
};

test('the picker chooses nothing on its own, and Add carries only ids and a number', () => {
  const node = UI.renderItem({ type: 'variant_picker', data: PICKER }, {});
  const rows = node.querySelectorAll('.variant-row');
  assert.equal(rows.length, 2);
  assert.ok(rows.every((r) => r.getAttribute('aria-pressed') === 'false'), 'nothing is pre-selected without a confident match');
  const add = node.querySelectorAll('.variant-add')[0];
  assert.equal(add.dataset.command, 'order_edit.stage');
  assert.equal(add.disabled, true, 'Add does nothing until a variant is chosen');
  assert.deepEqual(JSON.parse(add.dataset.args), { order_id: PICKER.order_id, variant_id: '', quantity: 1 });

  rows[1].dispatch('click');
  assert.deepEqual(rows.map((r) => r.getAttribute('aria-pressed')), ['false', 'true'], 'one at a time');
  assert.equal(add.disabled, false);
  assert.deepEqual(JSON.parse(add.dataset.args), {
    order_id: 'gid://shopify/Order/1938', variant_id: 'gid://shopify/ProductVariant/9104', quantity: 1,
  });
  // The whole payload, key by key: nothing the Mac decided travels back from the tablet.
  assert.deepEqual(Object.keys(JSON.parse(add.dataset.args)).sort(), ['order_id', 'quantity', 'variant_id']);
});

test('the stepper stays between one and the ceiling the Mac sent, and the payload follows it', () => {
  const node = UI.renderItem({ type: 'variant_picker', data: Object.assign({}, PICKER, { max_quantity: 3 }) }, {});
  const [down, up] = [node.querySelectorAll('.step-btn')[0], node.querySelectorAll('.step-btn')[1]];
  const value = node.querySelectorAll('.step-value')[0];
  const add = node.querySelectorAll('.variant-add')[0];
  node.querySelectorAll('.variant-row')[0].dispatch('click');
  down.dispatch('click');
  assert.equal(textOf(value), '1', 'never below one');
  up.dispatch('click'); up.dispatch('click'); up.dispatch('click'); up.dispatch('click');
  assert.equal(textOf(value), '3', 'never above the ceiling');
  assert.equal(JSON.parse(add.dataset.args).quantity, 3);
  down.dispatch('click');
  assert.equal(JSON.parse(add.dataset.args).quantity, 2);
});

test('one confident match is pre-selected and still needs the tap; a variant not for sale cannot be chosen', () => {
  const one = UI.renderItem({ type: 'variant_picker', data: Object.assign({}, PICKER, {
    count: 1, confident_variant_id: 'gid://shopify/ProductVariant/9102', candidates: [PICKER.candidates[0]],
  }) }, {});
  const row = one.querySelectorAll('.variant-row')[0];
  assert.equal(row.getAttribute('aria-pressed'), 'true');
  const add = one.querySelectorAll('.variant-add')[0];
  assert.equal(add.disabled, false);
  assert.equal(JSON.parse(add.dataset.args).variant_id, 'gid://shopify/ProductVariant/9102');
  assert.match(textOf(one), /Nothing is added until you confirm/);

  const off = UI.renderItem({ type: 'variant_picker', data: Object.assign({}, PICKER, {
    count: 1, candidates: [Object.assign({}, PICKER.candidates[0], { for_sale: false, available: 0 })],
  }) }, {});
  const dead = off.querySelectorAll('.variant-row')[0];
  dead.dispatch('click');
  assert.equal(dead.getAttribute('aria-pressed'), 'false', 'a variant not for sale is not selectable');
  assert.equal(off.querySelectorAll('.variant-add')[0].disabled, true);
  assert.match(textOf(off), /not for sale/);
});

test('every string on the picker arrives as text, never as markup', () => {
  const node = UI.renderItem({ type: 'variant_picker', data: Object.assign({}, PICKER, {
    order_number: HOSTILE, note: HOSTILE,
    candidates: [{ variant_id: 'gid://shopify/ProductVariant/1', title: HOSTILE, variant: HOSTILE, options: [HOSTILE], price: HOSTILE, for_sale: true }],
  }) }, {});
  const body = textOf(node);
  assert.ok(body.includes(HOSTILE));
  assert.equal(node.querySelectorAll('script').length, 0);
});

/* ---------------------------------------------------------- compose (app/families/compose.py) */

const COMPOSER = {
  compose_id: 'cmp_ab12cd34ef', kind: 'new',
  to: { value: '1232candlestickhorse@gmail.com', status: 'ok', hint: '' },
  to_name: '',
  subject: { value: 'Free for a shoot on Sunday?', status: 'ok', placeholder: 'the assistant is writing this' },
  body: { value: 'Hi, are you free next Sunday?', status: 'ok', placeholder: 'the assistant is writing this' },
  thread_id: '', about: 'asking if they are free for a shoot next Sunday',
  resolved_when: { date: '2026-09-13', phrase: 'next sunday' },
  original: 'Write an email to a model asking if they are free for a shoot next Sunday.',
  actions: [
    { id: 'save_draft', label: 'Save draft', mode: 'stage' },
    { id: 'send', label: 'Send', mode: 'stage', risk: 'red' },
    { id: 'discard', label: 'Discard' },
  ],
  unexpected_field: 'THIS IS NOT FOR THE OWNER AND MUST NOT BE DRAWN',
};

function composer(patch) {
  return UI.renderItem({ type: 'email_compose', data: Object.assign({}, COMPOSER, patch || {}) }, {});
}

test('a precision field carries its kind, its target size and where a keystroke goes', () => {
  const wrap = UI.field({ kind: 'email', name: 'to', label: 'To', value: 'sam@crooksldn.com', status: 'ok', compose_id: 'cmp_1', maxlength: 254 }, {});
  const input = wrap.querySelectorAll('.field-input')[0];
  assert.equal(input.tagName, 'INPUT');
  assert.equal(input.getAttribute('type'), 'email');
  assert.equal(input.getAttribute('inputmode'), 'email');
  assert.equal(input.getAttribute('autocapitalize'), 'none');
  assert.equal(input.getAttribute('maxlength'), '254');
  // Identity, never an instruction: which composer and which field, and nothing else.
  assert.equal(input.dataset.compose, 'cmp_1');
  assert.equal(input.dataset.field, 'to');
  assert.equal(input.value, 'sam@crooksldn.com');
  // 44px lives in the stylesheet (tests/test_compose.py asserts it there); the class that
  // carries it has to be on the control or that assertion is about nothing.
  assert.ok(input.classList.contains('field-input'));
});

test('every field kind has an input mode, and an unknown kind falls back rather than breaking', () => {
  for (const kind of ['email', 'text', 'address', 'sku', 'tracking', 'variant', 'quantity', 'code', 'money']) {
    const input = UI.field({ kind, name: 'x' }, {}).querySelectorAll('.field-input')[0];
    assert.ok(input, kind);
    assert.ok(input.getAttribute('inputmode'), `${kind} has no inputmode`);
    assert.equal(input.tagName, UI.FIELD_KINDS[kind].tag.toUpperCase(), kind);
  }
  const numeric = UI.field({ kind: 'quantity', name: 'q' }, {}).querySelectorAll('.field-input')[0];
  assert.equal(numeric.getAttribute('inputmode'), 'numeric');
  assert.equal(numeric.getAttribute('pattern'), '[0-9]{1,4}');
  // A kind nobody registered draws a plain text field; it never draws nothing.
  const unknown = UI.field({ kind: 'hologram', name: 'x' }, {});
  assert.ok(unknown.classList.contains('field-text'));
});

test('a field says its status three ways, and only the Mac decides which', () => {
  const seen = {};
  for (const status of ['ok', 'uncertain', 'invalid']) {
    const wrap = UI.field({ kind: 'email', name: 'to', value: 'x', status, hint: `because ${status}` }, {});
    seen[status] = wrap.className;
    assert.ok(wrap.classList.contains(`is-${status}`), status);
    assert.equal(wrap.dataset.status, status);
    assert.equal(textOf(wrap.querySelectorAll('.field-hint')[0]), `because ${status}`);
    assert.equal(wrap.querySelectorAll('.field-input')[0].getAttribute('aria-invalid'), status === 'invalid' ? 'true' : 'false');
  }
  assert.equal(new Set(Object.values(seen)).size, 3, 'the three statuses must not render alike');
  // A status the Mac did not send is not invented as a failure.
  assert.ok(UI.field({ kind: 'email', name: 'to', status: 'catastrophic' }, {}).classList.contains('is-ok'));
  // No hint, no hint line.
  assert.equal(UI.field({ kind: 'email', name: 'to', status: 'ok' }, {}).querySelectorAll('.field-hint')[0].hidden, true);
});

test('typing hands the characters to opts, and the value and status come back through opts', () => {
  const seen = [];
  const wrap = UI.field({ kind: 'email', name: 'to', value: '', status: 'invalid', hint: 'no address yet', compose_id: 'cmp_1' },
                        { onField: (name, value) => seen.push([name, value]) });
  const input = wrap.querySelectorAll('.field-input')[0];
  input.value = '1232candlestickhorse@gmail.com';
  input.dispatch('input');
  assert.deepEqual(seen, [['to', '1232candlestickhorse@gmail.com']]);
  // The component is controlled: the Mac's answer is a fresh spec, and the field shows THAT.
  const answered = UI.field({ kind: 'email', name: 'to', value: '1232candlestickhorse@gmail.com', status: 'ok', hint: '', compose_id: 'cmp_1' }, {});
  assert.equal(answered.querySelectorAll('.field-input')[0].value, '1232candlestickhorse@gmail.com');
  assert.ok(answered.classList.contains('is-ok'));
  assert.equal(answered.querySelectorAll('.field-hint')[0].hidden, true);
});

test('a finger in a field never reaches the deck underneath it', () => {
  const input = UI.field({ kind: 'email', name: 'to' }, {}).querySelectorAll('.field-input')[0];
  for (const type of ['pointerdown', 'pointerup', 'pointercancel', 'click', 'touchstart', 'keydown', 'keyup']) {
    let stopped = false;
    input.dispatch(type, { stopPropagation: () => { stopped = true; } });
    assert.ok(stopped, `${type} bubbled into the deck's handlers`);
  }
  // And it carries no [data-ref]/[data-kind], which is what the deck's click handler opens on.
  assert.equal(input.dataset.ref, undefined);
  assert.equal(input.dataset.kind, 'email');   // the field's own kind, not an entity kind
});

test('the composer draws the email as fields, with what it is about and the date resolved', () => {
  const node = composer();
  assert.equal(node.dataset.type, 'email_compose');
  assert.equal(node.dataset.compose, 'cmp_ab12cd34ef');
  const fields = node.querySelectorAll('.field-input');
  assert.deepEqual(fields.map((f) => f.dataset.field), ['to', 'subject', 'body']);
  assert.ok(fields.every((f) => f.dataset.compose === 'cmp_ab12cd34ef'));
  assert.match(textOf(node), /asking if they are free for a shoot next Sunday/);
  assert.match(textOf(node), /next sunday · 2026-09-13/);
  assert.match(textOf(node), /Nothing is saved or sent until you tap/);
  // A reply has no To field: its recipient is the thread's and the Mac reads it there.
  const reply = composer({ kind: 'reply', thread_id: 'aa70d3f83dbef06e' });
  assert.deepEqual(reply.querySelectorAll('.field-input').map((f) => f.dataset.field), ['subject', 'body']);
  assert.match(textOf(reply), /in the same thread/);
});

test('the composer\'s buttons post an id and a mode, and never the email', () => {
  const buttons = composer().querySelectorAll('.compose-btn');
  assert.deepEqual(buttons.map((b) => [b.dataset.command, b.dataset.args]), [
    ['compose.stage', 'compose_id=cmp_ab12cd34ef&mode=draft'],
    ['compose.stage', 'compose_id=cmp_ab12cd34ef&mode=send'],
    ['compose.discard', 'compose_id=cmp_ab12cd34ef'],
  ]);
  // Send is the grave one and says so in more than a colour name.
  assert.ok(buttons[1].classList.contains('risk-red'));
  assert.ok(!buttons[0].classList.contains('risk-red'));
  for (const button of buttons) {
    const args = String(button.dataset.args);
    for (const forbidden of ['Free for a shoot', 'are you free', '@gmail.com', 'subject=', 'body=', 'to=']) {
      assert.ok(args.indexOf(forbidden) === -1, `${button.dataset.action} carries ${forbidden}`);
    }
  }
});

test('a field on the card that the renderer does not know is not drawn anywhere', () => {
  // The renderer draws the fields it names and nothing else — not into the text, not into an
  // attribute. The composer's continuation prompt used to arrive this way and be relayed back
  // by the tablet; it now goes straight to the model inside the turn (app/routes/turn.py), and
  // this stays because the next thing the Mac puts on a card by accident should not be drawn
  // either.
  const node = composer();
  assert.ok(textOf(node).indexOf('THIS IS NOT FOR THE OWNER') === -1);
  (function walk(el) {
    for (const [k, v] of Object.entries(el.attributes)) {
      assert.ok(String(v).indexOf('THIS IS NOT FOR THE OWNER') === -1, `${el.tagName}[${k}] leaked it`);
    }
    for (const c of el.children) walk(c);
  })(node);
});

test('a hostile email lands in the composer as text, never as markup', () => {
  const node = composer({
    to: { value: HOSTILE, status: 'invalid', hint: HOSTILE }, to_name: HOSTILE,
    subject: { value: HOSTILE, status: 'ok', placeholder: HOSTILE },
    body: { value: HOSTILE, status: 'ok', placeholder: HOSTILE },
    about: HOSTILE, original: HOSTILE,
    actions: [{ id: 'save_draft', label: HOSTILE, mode: 'stage' }],
  });
  assert.ok(textOf(node).includes(HOSTILE));
  const tags = new Set();
  (function walk(el) { for (const c of el.children) { tags.add(c.tagName); walk(c); } })(node);
  assert.ok(!tags.has('IMG') && !tags.has('SCRIPT'));
  // The VALUE of a field is a property, not an attribute built from data — but the
  // placeholder is an attribute, so it has to be checked too.
  (function walk(el) {
    for (const [k, v] of Object.entries(el.attributes)) {
      if (k === 'placeholder' || k === 'aria-label') continue;   // text, by construction
      assert.ok(!String(v).includes('<'), `${el.tagName}[${k}] carries markup`);
    }
    for (const c of el.children) walk(c);
  })(node);
});

test('a composer with fields the Mac did not send still renders', () => {
  const bare = UI.renderItem({ type: 'email_compose', data: { compose_id: 'cmp_1', kind: 'new' } }, {});
  assert.ok(bare && bare.dataset.type === 'email_compose');
  assert.equal(bare.querySelectorAll('.compose-btn').length, 0, 'no actions, no buttons');
  assert.deepEqual(bare.querySelectorAll('.field-input').map((f) => f.dataset.field), ['to', 'subject', 'body']);
});

/* ---------------------------------------------------------------- the workspace card
 *
 * Something being built, before anything is proposed (app/families/_workspace.py). The card
 * is entirely the Mac's description of itself — which fields, of which kind, with what
 * status; which closed choices; which facts; which buttons and what each one posts — so what
 * these check is that this file draws exactly that and invents nothing.
 */
const WORKSPACE = {
  workspace_id: 'dsc_abc123', kind: 'discount',
  kicker: 'Discount code · not created', title: 'AUTUMN20', subtitle: 'from today, with no end date',
  field_command: 'discount.field',
  fields: [
    { name: 'code', label: 'Code', kind: 'code', value: 'AUTUMN20', status: 'ok', hint: '', placeholder: 'SUMMER15', maxlength: 30 },
    { name: 'value', label: 'Takes off', kind: 'money', value: '20', status: 'ok', hint: '', placeholder: '15', maxlength: 10 },
    { name: 'currency', label: 'Currency', kind: 'code', value: 'GBP', status: 'ok', hint: '', placeholder: 'GBP', maxlength: 3 },
  ],
  choices: [
    { name: 'basis', label: 'What it takes off', options: [{ id: 'percentage', label: 'Per cent', selected: true }, { id: 'amount', label: 'Money', selected: false }] },
  ],
  facts: [{ label: 'Takes off', value: '20%', tone: '' }, { label: 'That code', value: "free — nothing uses AUTUMN20", tone: 'ok' }],
  notes: ['It applies to everything in the shop and combines with nothing else.'],
  blocked: '',
  actions: [
    { id: 'prepare', label: 'Prepare the code', command: 'discount.stage', args: 'workspace_id=dsc_abc123', risk: 'red', enabled: true },
    { id: 'discard', label: 'Discard', command: 'discount.discard', args: 'workspace_id=dsc_abc123', risk: '', enabled: true },
  ],
  unexpected_field: 'THIS IS NOT FOR THE OWNER AND MUST NOT BE DRAWN',
};

function workspace(patch) {
  return UI.renderItem({ type: 'workspace', data: Object.assign({}, WORKSPACE, patch || {}) }, {});
}

test('the workspace draws the fields the Mac named, with the command its keystrokes post', () => {
  const node = workspace();
  assert.equal(node.dataset.type, 'workspace');
  assert.equal(node.dataset.workspace, 'dsc_abc123');
  const inputs = node.querySelectorAll('.field-input');
  assert.deepEqual(inputs.map((f) => f.dataset.field), ['code', 'value', 'currency']);
  assert.deepEqual(inputs.map((f) => f.dataset.kind), ['code', 'money', 'code']);
  // Where a keystroke goes: this family's command, not the composer's default.
  assert.deepEqual(inputs.map((f) => f.dataset.post), ['discount.field', 'discount.field', 'discount.field']);
  assert.deepEqual(inputs.map((f) => f.dataset.compose), ['dsc_abc123', 'dsc_abc123', 'dsc_abc123']);
  assert.equal(inputs[1].getAttribute('inputmode'), 'decimal');
  assert.equal(inputs[0].value, 'AUTUMN20');
  // The unexpected key is not drawn anywhere.
  assert.ok(!textOf(node).includes('THIS IS NOT FOR THE OWNER'));
});

test('a field with no post falls back to the composer, so an older card still types', () => {
  const wrap = UI.field({ kind: 'text', name: 'body', label: 'Body', value: 'x', compose_id: 'cmp_9' }, {});
  assert.equal(wrap.querySelectorAll('.field-input')[0].dataset.post, 'compose.field');
});

test('the workspace buttons carry a command and an id and never a value of the change', () => {
  const node = workspace();
  const buttons = node.querySelectorAll('.compose-btn');
  assert.deepEqual(buttons.map((b) => b.dataset.command), ['discount.stage', 'discount.discard']);
  for (const b of buttons) {
    assert.equal(b.dataset.args, 'workspace_id=dsc_abc123');
    assert.ok(!/code=|value=|percent=/.test(b.dataset.args));
  }
  assert.ok(buttons[0].classList.contains('risk-red'));
  // A closed choice is a button too, and posts which choice and which option.
  const options = node.querySelectorAll('.ws-opt');
  assert.deepEqual(options.map((o) => o.getAttribute('aria-pressed')), ['true', 'false']);
  assert.equal(options[1].dataset.args, 'workspace_id=dsc_abc123&field=basis&option=amount');
});

test('a blocked workspace says why and its risky button cannot be pressed', () => {
  const node = workspace({
    blocked: "AUTUMN20 is already in use by 'Summer sale'. Pick another code.",
    actions: [{ id: 'prepare', label: 'Prepare the code', command: 'discount.stage', args: 'workspace_id=dsc_abc123', risk: 'red', enabled: false }],
  });
  assert.ok(textOf(node).includes('already in use'));
  assert.ok(textOf(node).includes('Not ready'));
  assert.equal(node.querySelectorAll('.compose-btn')[0].disabled, true);
});

test('a hostile value lands in the workspace as text, never as markup', () => {
  const node = workspace({
    title: HOSTILE, subtitle: HOSTILE, kicker: HOSTILE,
    fields: [{ name: 'code', label: HOSTILE, kind: 'code', value: HOSTILE, status: 'invalid', hint: HOSTILE, placeholder: HOSTILE, maxlength: 30 }],
    facts: [{ label: HOSTILE, value: HOSTILE, tone: HOSTILE }],
    notes: [HOSTILE],
    choices: [{ name: 'basis', label: HOSTILE, options: [{ id: HOSTILE, label: HOSTILE, selected: false }] }],
    actions: [{ id: 'prepare', label: HOSTILE, command: 'discount.stage', args: 'workspace_id=dsc_abc123', risk: 'red', enabled: true }],
  });
  assert.ok(textOf(node).includes(HOSTILE));
  const tags = new Set();
  (function walk(el) { for (const c of el.children) { tags.add(c.tagName); walk(c); } })(node);
  assert.ok(!tags.has('IMG') && !tags.has('SCRIPT'));
  (function walk(el) {
    for (const [k, v] of Object.entries(el.attributes)) {
      if (k === 'placeholder' || k === 'aria-label') continue;   // text, by construction
      assert.ok(!String(v).includes('<'), `${el.tagName}[${k}] carries markup`);
    }
    for (const c of el.children) walk(c);
  })(node);
});

test('a workspace the Mac sent nothing on still renders', () => {
  const bare = UI.renderItem({ type: 'workspace', data: { workspace_id: 'ord_abc123' } }, {});
  assert.ok(bare && bare.dataset.type === 'workspace');
  assert.equal(bare.querySelectorAll('.field-input').length, 0);
  assert.equal(bare.querySelectorAll('.compose-btn').length, 0, 'no actions, no buttons');
  assert.ok(textOf(bare).includes('Nothing is created until you authorise'));
});

// ---- the compact summary surface (§13). D-4: "has anyone bought today that has bought
// before" was answered, correctly, with seven full customer profile cards. These tests hold
// the two things that make a compact row a row: it reads as a line, and its tap target is an
// attribute and never something the owner can read (§26).

const RETURNING = {
  task: 'returning_customers',
  title: 'Returning customers today',
  kicker: 'Returning customers',
  count: 1,
  count_label: 'returning customer',
  subtitle: '7 buyers · 7 orders today',
  rows: [{
    label: 'Cy Cole',
    sub: 'Order #1962',
    lines: [
      { label: 'Previous order', value: '31 Aug' },
      { label: 'Lifetime', value: '£120.00' },
      { label: 'Orders', value: '2' },
    ],
    badge: 'Returning',
    tone: 'good',
    tap: true,
    ref: 'gid://shopify/Customer/5015',
    kind: 'customer',
    command: 'open.entity',
  }],
  note: '',
  truncated: false,
  empty: false,
  tappable: 1,
};

// What web/app.js treats as a tap: an element carrying BOTH a ref and a kind. The DOM shim
// only understands single-attribute selectors, so the pair is counted here.
function tapTargets(node) {
  const out = [];
  (function walk(el) {
    for (const c of el.children) {
      if (c.dataset && c.dataset.ref && c.dataset.kind) out.push(c);
      walk(c);
    }
  })(node);
  return out;
}

function summaryNode(over) {
  return UI.renderItem({ type: 'summary_list', data: Object.assign({}, RETURNING, over || {}) }, {});
}

test('the summary surface draws the headline count and one row per person', () => {
  const node = summaryNode();
  assert.ok(node, 'the summary surface did not render');
  assert.equal(node.dataset.type, 'summary_list');
  assert.equal(node.dataset.task, 'returning_customers');
  const said = textOf(node);
  assert.ok(said.includes('Returning customers today'), said);
  assert.ok(said.includes('· 1'), 'the headline count is missing: ' + said);
  assert.equal(node.querySelectorAll('.row').length, 1);
  // The row's own words, in the shape the brief asks for.
  assert.ok(said.includes('Cy Cole') && said.includes('Order #1962'), said);
  assert.ok(said.includes('Previous order') && said.includes('31 Aug'), said);
  assert.ok(said.includes('Lifetime') && said.includes('£120.00'), said);
  assert.ok(said.includes('Orders') && said.includes('2'), said);
});

test('a compact row never shows an id, and carries its ref as an attribute', () => {
  const node = summaryNode();
  const said = textOf(node);
  assert.ok(!said.includes('gid://'), 'an id reached something the owner can read: ' + said);
  assert.ok(!said.includes('5015'), 'the tail of a gid is not a name');
  // The ref is how the tablet names the record back to the Mac, and lives only here.
  const row = node.querySelectorAll('.row')[0];
  assert.equal(row.dataset.ref, 'gid://shopify/Customer/5015');
  assert.equal(row.dataset.kind, 'customer');
});

test('a row the Mac said has nowhere to go is not a button', () => {
  // §18. D-6 drew a control, posted it, and was refused `not_held` — a dead control with an
  // empty half underneath it. A row whose destination did not resolve is a line, not a tap.
  const node = summaryNode({
    rows: [
      RETURNING.rows[0],
      { label: 'Never shown', sub: 'Order #1963', lines: [], badge: '', tone: '', tap: false },
    ],
  });
  const rows = node.querySelectorAll('.row');
  assert.equal(rows.length, 2);
  assert.equal(rows[0].getAttribute('role'), 'button');
  assert.equal(rows[1].getAttribute('role'), null, 'a row with no destination offered a tap');
  assert.equal(rows[1].dataset.ref, undefined);
  assert.ok(!String(rows[1].className).includes('tappable'));
  // And the tap-target convention the page dispatches on — web/app.js finds a tap with
  // `closest('[data-ref][data-kind]')` — is present on the one row that has a destination.
  assert.equal(tapTargets(node).length, 1);
});

test('nothing found is still an answer, in the Mac\'s own words', () => {
  // D-15, and the reason the sentence is the Mac's and not the renderer's: "nothing needs
  // attention" is not "no orders" — there were plenty of orders.
  const node = summaryNode({ count: 0, rows: [], empty: true, count_label: 'returning customers',
                             empty_words: 'Nobody who bought today had bought before.' });
  assert.ok(node, 'an empty summary drew nothing at all');
  const said = textOf(node);
  assert.ok(said.includes('Nobody who bought today had bought before.'), said);
  assert.ok(said.includes('· 0'), said);
  // And with no sentence sent, it still says something rather than nothing.
  const bare = summaryNode({ count: 0, rows: [], empty: true, count_label: 'orders', empty_words: '' });
  assert.ok(textOf(bare).includes('No orders'), textOf(bare));
});

test('a capped summary says how many it is showing of how many there are', () => {
  const many = [];
  for (let n = 0; n < 12; n += 1) {
    many.push({ label: 'Buyer ' + n, sub: '', lines: [], badge: '', tone: '', tap: false });
  }
  const node = summaryNode({ count: 25, rows: many, truncated: true });
  assert.equal(node.querySelectorAll('.row').length, 12);
  assert.ok(textOf(node).includes('Showing 12 of 25'), textOf(node));
});

test('a hostile value lands on a compact row as text, never as markup', () => {
  const node = summaryNode({
    title: HOSTILE, kicker: HOSTILE, subtitle: HOSTILE, note: HOSTILE,
    rows: [{ label: HOSTILE, sub: HOSTILE, badge: HOSTILE, tone: HOSTILE, tap: false,
             lines: [{ label: HOSTILE, value: HOSTILE }] }],
  });
  assert.ok(textOf(node).includes(HOSTILE));
  const tags = new Set();
  (function walk(el) { for (const c of el.children) { tags.add(c.tagName); walk(c); } })(node);
  assert.ok(!tags.has('IMG') && !tags.has('SCRIPT'));
  (function walk(el) {
    for (const [k, v] of Object.entries(el.attributes)) {
      if (k === 'aria-label' || k === 'placeholder') continue;
      assert.ok(!String(v).includes('<'), el.tagName + '[' + k + '] carries markup');
    }
    for (const c of el.children) walk(c);
  })(node);
  // A tone the Mac did not choose is not a class the page has styling for.
  assert.ok(!String(node.querySelectorAll('.row')[0].className).includes('<'));
});

test('the attention summary tones its rows and keeps its rows rows', () => {
  const node = UI.renderItem({ type: 'summary_list', data: {
    task: 'orders_attention', title: 'Orders that need attention', kicker: 'Needs attention',
    count: 2, count_label: 'orders', subtitle: '1 urgent · 1 worth a look',
    rows: [
      { label: '#1900', sub: 'Not paid for · 20 days old and still owing',
        lines: [{ label: 'Placed', value: '20 Aug' }, { label: 'Value', value: '£90.00' }],
        badge: 'Hal Hood', tone: 'red', tap: true, ref: 'gid://shopify/Order/1900', kind: 'order' },
      { label: '#1901', sub: 'Waiting to go out · 6 days old',
        lines: [{ label: 'Placed', value: '3 Sep' }], badge: 'Ivy Ives', tone: 'amber',
        tap: true, ref: 'gid://shopify/Order/1901', kind: 'order' },
    ],
    note: '', truncated: false, empty: false, tappable: 2,
  } }, {});
  const rows = node.querySelectorAll('.row');
  assert.equal(rows.length, 2);
  assert.ok(String(rows[0].querySelectorAll('.hist-line')[0].className).includes('warn'), 'the urgent row is not marked');
  assert.ok(String(rows[1].querySelectorAll('.badge')[0].className).includes('warn'), 'the amber row is not marked');
  assert.equal(tapTargets(node).length, 2);
  assert.ok(!textOf(node).includes('gid://'));
});


// ---- the hop from an order to its customer (the click-path audit's path 1, step 4 of 8).

function orderWithCustomer(over) {
  return UI.renderItem({ type: 'order', data: Object.assign({
    order_id: 'gid://shopify/Order/1938', order_number: '#1938', detail: true,
    customer_name: 'Mia Jones', customer_id: 'gid://shopify/Customer/7001',
    customer_email: 'mia@example.com', total: '£84.00', fulfillment: 'unfulfilled',
    payment: 'paid', items: [], pending: [],
    history: { orders: 3, spent: '£410.00', standing: 'returning', recent: [] },
  }, over || {}) }, {});
}

test('an order card offers a control that opens its customer', () => {
  // The click-path audit found path 1 dead here: an order card with its Customer tab open
  // offered nothing that opened the customer — everything tappable in that tab went to
  // another ORDER. Order to customer was not walkable at all.
  const node = orderWithCustomer();
  const doors = node.querySelectorAll('.link-customer');
  assert.equal(doors.length, 1, 'the order card offers no way to its customer');
  assert.equal(doors[0].dataset.ref, 'gid://shopify/Customer/7001');
  assert.equal(doors[0].dataset.kind, 'customer');
  assert.ok(textOf(doors[0]).includes('Mia Jones'), textOf(doors[0]));
  assert.ok(!textOf(node).includes('gid://'), 'an id reached something readable');
});

test('the door to the customer stands while the history is still being read', () => {
  // Who the order belongs to is on the ORDER. Waiting for the history read to land before
  // offering the hop is how step 4 came to be dead in the first place.
  const node = orderWithCustomer({ pending: ['history'], history: null });
  assert.equal(node.querySelectorAll('.link-customer').length, 1);
  assert.ok(textOf(node).includes('Reading their history'), textOf(node));
});

test('the door stands when the history could not be read at all', () => {
  const node = orderWithCustomer({ history: { available: false } });
  assert.equal(node.querySelectorAll('.link-customer').length, 1);
  assert.ok(textOf(node).includes('couldn’t load the customer'), textOf(node));
});

test('a guest order offers no door, because there is nobody behind it', () => {
  // §18 the other way round: no customer, no control. A button that posts an empty ref is
  // the dead control this rule exists to stop.
  const node = orderWithCustomer({ customer_id: '', customer_name: '', history: null });
  assert.equal(node.querySelectorAll('.link-customer').length, 0);
  assert.ok(textOf(node).includes('No customer is attached'), textOf(node));
});

test('a customer ref of the wrong shape is not offered as a door', () => {
  for (const bad of ['7001', 'gid://shopify/Order/1938', 'gid://shopify/Customer/abc', '../../etc']) {
    const node = orderWithCustomer({ customer_id: bad });
    assert.equal(node.querySelectorAll('.link-customer').length, 0, bad);
  }
});

test('the late history fill keeps the door', () => {
  // /context/order redraws that region and its payload is about the ORDER's regions, not
  // about who it belongs to — so the door would have been dropped by the very read it was
  // waiting for.
  const node = orderWithCustomer({ pending: ['history'], history: null });
  UI.hydrateOrder(node, { order_id: 'gid://shopify/Order/1938', pending: [],
                          history: { orders: 3, spent: '£410.00', standing: 'returning', recent: [] } });
  const doors = node.querySelectorAll('.link-customer');
  assert.equal(doors.length, 1, 'the hop was lost when the history landed');
  assert.equal(doors[0].dataset.ref, 'gid://shopify/Customer/7001');
});

test('the customer card does not offer a door to itself', () => {
  const node = UI.renderItem({ type: 'customer', data: {
    customer_id: 'gid://shopify/Customer/7001', name: 'Mia Jones', orders: 3, spent: '£410.00',
    history: { orders: 3, spent: '£410.00', standing: 'returning', recent: [] },
  } }, {});
  assert.equal(node.querySelectorAll('.link-customer').length, 0);
});

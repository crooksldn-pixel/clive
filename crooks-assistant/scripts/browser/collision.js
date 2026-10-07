/* Does anything on this screen sit on top of anything else? Measured, in Chromium.
 *
 * The live tablet session recorded `clipped=0` on every render while the owner was looking at
 * overlapping text and controls, and said so out loud. `clipped` was one subtraction on one
 * card — scrollWidth against clientWidth — which cannot see two boxes that are each the right
 * size and in the same place. This file does not ask the page how it thinks it is doing. It
 * renders the worst data the shop can produce, reads every rectangle with
 * getBoundingClientRect(), and reports the pairs that collide (web/collide.js).
 *
 *   node scripts/browser/collision.js http://127.0.0.1:8765 [/path/to/screenshots]
 *
 * Two sizes, because a defect is a defect at the size the tablet actually is:
 *   601 × 889 at DPR 1.33 — the Galaxy Tab A 8.0 in the owner's hand
 *   800 × 1280 at DPR 1   — the gate's own portrait
 *
 * The fixtures are every one a value a real shop has: a customer with a very long name and one
 * with exactly fifty characters, an eighty-character email address, a four-line postal address,
 * a long SKU, a long tracking number, a product title that does not fit, a subject that does
 * not fit, a note with five paragraphs in it, a total in the millions, nine status chips, four
 * actions and five, the keyboard open, three messages at once, four messages over a full deck,
 * and the offline notice. Every one of them is DATA, handed to the page's own renderer
 * (window.CrooksUI) — nothing here builds markup, and nothing here can, because the renderer
 * only draws the types it knows.
 *
 * Two of the states are not payloads and were the hole in this file: the IDLE SCREEN, and the
 * idle screen DIVIDED. Every Phase 4 fixture drew cards first, which puts the page into context
 * mode — where `#talk` is a dock band and the branch controls move into `#branch-rail`. The
 * defect the owner hit twenty-six times in ten seconds is on the ORB screen, where `.talk` is
 * `inset:0` and the chips sit inside `.orb-zone`. Nothing here ever went there, which is most
 * of why this suite was green all evening.
 *
 * PHASE 5 §9. The rule loop below used to be the whole verdict and it was a per-rule zero
 * check; what it did not have was a line that fails the release. It has three now:
 *
 *   · a named verdict for each of the fourteen pairs the brief lists, from CrooksCollide.PAIRS,
 *     so the gate cannot quietly stop asking one of them;
 *   · ZERO collisions involving an interactive element, at BOTH viewports, as a hard failure —
 *     "do not merely record it as telemetry";
 *   · and the idle-screen states above, so the check has something real to fail on.
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], viewports, cases, shots }.
 */
'use strict';

const { chromium } = require('playwright-core');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };

// The tablet's own size first: it is the one the owner holds, and the one that finds the faults.
const VIEWPORTS = [
  { name: '601x889@1.33', width: 601, height: 889, dpr: 1.33 },
  { name: '800x1280@1', width: 800, height: 1280, dpr: 1 },
];

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- the stress values

const LONG_NAME = 'Alexandra Wilhelmina Constance Featherstonehaugh-Beauchamp';
// §9 asks for a fifty-character name by name. The one above is 57 and has hyphens and spaces
// to break on; this one is exactly 50 with two long unbreakable runs, which is the harder case
// and the one a real wholesale account produces.
const NAME_50 = 'Konstantinopoulos-Wetherspoonshire Partnership Ltd';
const LONG_EMAIL = 'alexandra.wilhelmina.featherstonehaugh@a-very-long-department.example.com';
const LONG_TITLE = 'Blue Wash Selvedge Yard Jeans — Relaxed Straight, Unwashed, Limited Workshop Run 2026';
const LONG_SKU = 'CRK-YJ-BLUWASH-RELAXSTR-W34L32-SS26-LTD-000418-A';
const LONG_TRACK = 'AB0000000012345678901234567890GB';
const LONG_SUBJECT = 'Re: Re: Fwd: order 1938 — the jeans arrived in the wrong wash and the sweats are a size out, what do we do about the return postage';
const LONG_ADDRESS = {
  name: LONG_NAME,
  lines: ['Flat 14, Featherstonehaugh Mansions', '221b Upper Kennington Park Road South', 'Behind the old brewery yard'],
  city: 'Kingston upon Thames', zip: 'KT1 2AB', country: 'United Kingdom', country_code: 'GB',
};
const LONG_NOTE = 'Customer rang twice about this one.\n\nWants the exchange sent to the work address, not the home one, and the original collected on the same visit if the courier can do that.\n\nSaid the sweats were fine, it is only the jeans.\n\nIf the exchange cannot be done this week he would rather have the refund.';
const BIG_MONEY = '£1,284,367.45';

const CHIPS = ['vip', 'wholesale', 'repeat-return', 'fraud-checked', 'gift-wrap', 'pre-order', 'back-order', 'priority', 'staff-discount'];

// The four the live session's order card actually carried, in its own order: the telemetry
// records `actions: [fulfil, address, cancel, note]` on every render of it. §9 asks for "four
// actions" because four is what the shop produces, and four wrap differently from five.
const ACTIONS_FOUR = [
  { id: 'fulfil', label: 'Mark as shipped', operation: 'fulfillment_create', risk: 'red', enabled: true, reason: '', instruction: 'Mark shipped', mode: 'ask' },
  { id: 'address', label: 'Change the delivery address', operation: 'order_shipping_address_set', risk: 'red', enabled: true, reason: '', instruction: 'Change the address', mode: 'ask' },
  { id: 'cancel', label: 'Cancel and refund the whole order', operation: 'order_cancel', risk: 'red', enabled: true, reason: '', instruction: 'Cancel', mode: 'ask' },
  { id: 'note', label: 'Note', operation: 'order_note_append', risk: 'amber', enabled: true, reason: '', instruction: 'Add a note', mode: 'ask', family: 'order.add_note' },
];

const ACTIONS_FIVE = [
  { id: 'note', label: 'Note', operation: 'order_note_append', risk: 'amber', enabled: true, reason: '', instruction: 'Add a note', mode: 'ask', family: 'order.add_note' },
  { id: 'address', label: 'Change the delivery address', operation: 'order_shipping_address_set', risk: 'red', enabled: true, reason: '', instruction: 'Change the address', mode: 'ask' },
  { id: 'fulfil', label: 'Mark as shipped', operation: 'fulfillment_create', risk: 'red', enabled: true, reason: '', instruction: 'Mark shipped', mode: 'ask' },
  { id: 'refund', label: 'Refund', operation: 'refund_create', risk: 'red', enabled: true, reason: '', instruction: 'Refund', mode: 'ask' },
  { id: 'cancel', label: 'Cancel and refund the whole order', operation: 'order_cancel', risk: 'red', enabled: false, reason: 'a label has already been printed for this one', instruction: 'Cancel', mode: 'ask' },
];

function order(extra) {
  return Object.assign({
    order_id: 'gid://shopify/Order/0', order_number: '#1938', placed_at: '2026-09-08T09:42:00Z',
    fulfillment: 'unfulfilled', payment: 'paid', total: '£145.00',
    customer_name: 'Sam Fixture', customer_id: 'gid://shopify/Customer/0', customer_email: 'sam@example.com',
    detail: true, tags: ['vip'],
    items: [{ title: 'Yard Jeans', variant: 'M', sku: 'YJ-BLU-M', quantity: 1, total: '£95.00', stock: { tracked: true, available: 3 } }],
    items_truncated: false, fulfillments: [],
    money: { subtotal: '£140.00', shipping: '£5.00', tax: '£23.33', discounts: '£0.00', refunded: '£0.00', outstanding: '£0.00' },
    shipping_method: 'Royal Mail Tracked 24',
    shipping_address: { name: 'Sam Fixture', lines: ['12 Somewhere Street'], city: 'London', zip: 'E1 6AN', country: 'United Kingdom', country_code: 'GB' },
    history: { orders: 4, spent: '£410.00', standing: 'regular', recent: [] },
    email: { available: true, threads: [] }, pending: [],
    actions: [{ id: 'note', label: 'Note', operation: 'order_note_append', risk: 'amber', enabled: true, reason: '', instruction: 'Add a note', mode: 'ask', family: 'order.add_note' }],
    cancelled_at: '', note: '', ships_to: 'London, United Kingdom',
  }, extra || {});
}

function confirmation(facts, extra) {
  return Object.assign({
    proposal_id: 'prop_collide00001', status: 'pending', risk: 'red', operation: 'fulfillment_create',
    title: 'Mark as shipped', entity: 'Order #1938', entity_kind: 'order', entity_ref: 'gid://shopify/Order/0',
    summary: '', detail: 'Marks every item shipped.', facts,
    interaction: { kind: 'hold_to_arm', label: 'Hold to arm, then tap', footer: 'nothing happens until you hold the card, then tap it', armed_after_ms: 650 },
    ttl_s: 60, reversible: false, commit: { allowed: true },
  }, extra || {});
}

// Every case is a name and a `ui` list. The renderer decides what any of it looks like.
const CASES = [
  { id: 'long_customer_name', ui: [{ type: 'order', data: order({ customer_name: LONG_NAME, shipping_address: Object.assign({}, LONG_ADDRESS, { lines: ['12 Somewhere Street'] }) }) }] },
  // §9's fifty-character name, on the two surfaces that print a name beside a control: the
  // order header (beside the total and the badges) and the customer profile head.
  { id: 'name_50_chars', ui: [
    { type: 'order', data: order({ customer_name: NAME_50, actions: ACTIONS_FOUR }) },
    { type: 'customer', data: {
      customer_id: 'gid://shopify/Customer/0', name: NAME_50, email: LONG_EMAIL,
      orders: 4, spent: BIG_MONEY, standing: 'regular',
      history: { available: true, orders: 4, spent: BIG_MONEY, standing: 'regular', since: '2025-02-01T00:00:00Z', first_order_at: '2025-02-01T00:00:00Z', recent: [{ order_id: 'gid://shopify/Order/1', order_number: '#1912', total: '£60.00', placed_at: '2026-08-01T00:00:00Z', fulfillment: 'fulfilled' }], recent_truncated: false, other_unfulfilled: [] },
      related_email: { available: true, threads: [] },
    } },
  ] },
  // §9's "four actions", on the card the live session drew them on.
  { id: 'four_actions', ui: [{ type: 'order', data: order({ customer_name: LONG_NAME, actions: ACTIONS_FOUR, tags: CHIPS.slice(0, 4) }) }] },
  { id: 'long_email_address', ui: [{ type: 'order', data: order({ customer_email: LONG_EMAIL, email: { available: true, threads: [{ thread_id: 't1', from: LONG_NAME, from_email: LONG_EMAIL, subject: 'Re: #1938', date: 'Tue, 8 Sep 2026 10:12:00 +0100', snippet: 'Where is it?', verified_sender: true, match: 'both', provenance: 'CUSTOMER_EMAIL' }] } }) }] },
  { id: 'long_postal_address', ui: [{ type: 'order', data: order({ shipping_address: LONG_ADDRESS, ships_to: 'Kingston upon Thames, United Kingdom' }) }] },
  { id: 'long_sku', ui: [{ type: 'order', data: order({ items: [{ title: 'Yard Jeans', variant: 'W34 / L32 / Unwashed', sku: LONG_SKU, quantity: 1, total: '£95.00', stock: { tracked: true, available: 3 } }] }) }] },
  { id: 'long_product_title', ui: [{ type: 'order', data: order({ items: [{ title: LONG_TITLE, variant: 'W34 / L32', sku: LONG_SKU, quantity: 2, total: BIG_MONEY, stock: { tracked: true, available: 0 } }] }) }] },
  { id: 'long_tracking_number', ui: [{ type: 'confirmation', data: confirmation([{ label: 'Items', value: LONG_TITLE }, { label: 'Carrier', value: 'Royal Mail Tracked 24 (signed for)' }, { label: 'Tracking', value: LONG_TRACK }, { label: 'Customer emailed', value: 'no' }]) }] },
  { id: 'long_subject', ui: [{ type: 'email_thread', data: { thread_id: 't1', subject: LONG_SUBJECT, message_count: 2, truncated: false, messages: [
    { from: LONG_NAME, from_email: LONG_EMAIL, date: 'Sun, 6 Sep 2026 18:30:00 +0100', subject: LONG_SUBJECT, body: 'The jeans arrived in the wrong wash.' },
    { from: LONG_NAME, from_email: LONG_EMAIL, date: 'Tue, 8 Sep 2026 10:12:00 +0100', subject: LONG_SUBJECT, body: LONG_NOTE },
  ], actions: [{ id: 'reply', label: 'Reply', enabled: true, risk: 'amber', mode: 'ask', family: 'email.reply', instruction: 'Reply' }, { id: 'email_archive', label: 'Archive', enabled: true, risk: 'amber', mode: 'stage' }] } }] },
  { id: 'multi_line_note', ui: [{ type: 'order', data: order({ note: LONG_NOTE }) }] },
  { id: 'large_currency', ui: [{ type: 'order', data: order({ total: BIG_MONEY, money: { subtotal: BIG_MONEY, shipping: '£12,000.00', tax: '£214,061.24', discounts: '£99,999.99', refunded: '£1,000,000.00', outstanding: BIG_MONEY } }) }] },
  { id: 'many_status_chips', ui: [{ type: 'order', data: order({ tags: CHIPS, payment: 'partially_refunded', fulfillment: 'partial', cancelled_at: '' }) }] },
  { id: 'five_actions', ui: [{ type: 'order', data: order({ customer_name: LONG_NAME, actions: ACTIONS_FIVE }) }] },
  { id: 'composer', ui: [{ type: 'email_compose', data: {
    compose_id: 'cmp_collide1', kind: 'new', about: LONG_SUBJECT,
    to: { value: LONG_EMAIL, status: 'invalid', hint: 'That does not look like an email address.' },
    subject: { value: LONG_SUBJECT, status: 'uncertain', hint: 'Heard rather than typed — look at it.' },
    body: { value: LONG_NOTE, status: 'ok', hint: '' },
    original: LONG_NOTE,
    actions: [{ id: 'draft', label: 'Save as a draft', mode: 'stage', risk: 'amber' }, { id: 'send', label: 'Send it now', mode: 'stage', risk: 'red' }, { id: 'discard', label: 'Throw it away', mode: 'discard', risk: 'amber' }],
  } }] },
  { id: 'workspace', ui: [{ type: 'workspace', data: {
    workspace_id: 'ws_collide1', kicker: 'Not created yet', title: 'A discount code', subtitle: LONG_SUBJECT,
    field_command: 'workspace.field', choose_command: 'workspace.choose',
    facts: [{ label: 'Customer', value: LONG_NAME }, { label: 'Email', value: LONG_EMAIL }, { label: 'Value', value: BIG_MONEY, tone: 'warn' }],
    fields: [{ name: 'code', kind: 'text', label: 'Code', value: LONG_SKU, status: 'ok', hint: '' }, { name: 'note', kind: 'text', label: 'Note', value: LONG_NOTE, status: 'uncertain', hint: 'Heard rather than typed.', rows: 4 }],
    choices: [{ name: 'kind', label: 'What kind', options: [{ id: 'pct', label: 'A percentage off', selected: true }, { id: 'fixed', label: 'A fixed amount off' }, { id: 'ship', label: 'Free delivery' }] }],
    notes: ['Nothing exists in the shop until the card that follows is authorised.'],
    actions: [{ id: 'prepare', label: 'Prepare the change', command: 'workspace.prepare', args: 'workspace_id=ws_collide1', enabled: true, risk: 'amber' }, { id: 'discard', label: 'Throw it away', command: 'workspace.discard', args: 'workspace_id=ws_collide1', enabled: false, risk: 'amber' }],
  } }] },
  // A list whose rows carry their own buttons (app/actions/rows.py), a thread with a linked
  // order and a customer chip, a bulk result with its members folded away, and a variant
  // picker with a stepper: between them they draw every control the section 29 pass resized —
  // .row-btn, .link-chip, .link-strip, a <summary> and the stepper — so the 44px check has
  // something to measure rather than passing because nothing on screen was small.
  { id: 'row_actions', ui: [{ type: 'email_list', data: { title: 'Waiting for a reply', count: 3, threads: [
    { thread_id: 't1', from: LONG_NAME, from_email: LONG_EMAIL, subject: LONG_SUBJECT, date: 'Tue, 8 Sep 2026 10:12:00 +0100', snippet: LONG_NOTE, known_customer: true, likely_bulk: false,
      actions: [{ id: 'reply', label: 'Reply', enabled: true, detail: 'Arms the microphone' }, { id: 'email_archive', label: 'Archive', enabled: true, detail: 'Prepares the change' }, { id: 'later', label: 'Later', enabled: false, detail: 'not yet' }] },
    { thread_id: 't2', from: 'Carrier Updates', from_email: 'no-reply@example.com', subject: 'Weekly digest', date: 'Mon, 7 Sep 2026 07:00:00 +0100', snippet: 'This week in shipping…', likely_bulk: true, known_customer: false,
      actions: [{ id: 'email_archive', label: 'Archive', enabled: true }] },
  ] } }] },
  { id: 'linked_graph', ui: [
    { type: 'email_thread', data: { thread_id: 't1', subject: LONG_SUBJECT, message_count: 1, truncated: false,
      link_confidence: 'confident', link_provenance: ['the order number is in the message', 'the sender is the customer on the order'],
      linked_order: { order_id: 'gid://shopify/Order/0', order_number: '#1938', total: BIG_MONEY, fulfillment: 'unfulfilled' },
      linked_customer: { customer_id: 'gid://shopify/Customer/0', name: LONG_NAME },
      messages: [{ from: LONG_NAME, from_email: LONG_EMAIL, date: 'Tue, 8 Sep 2026 10:12:00 +0100', subject: LONG_SUBJECT, body: LONG_NOTE }],
      actions: [{ id: 'reply', label: 'Reply', enabled: true, risk: 'amber', mode: 'ask', family: 'email.reply', instruction: 'Reply' }] } },
    { type: 'reply_state', data: { thread_id: 't1', latest_direction: 'inbound', replied: false, waiting_since: 'Tuesday', last_from: LONG_EMAIL, order_number: '#1938', confidence: 'confident', provenance: ['the order number is in the message'] } },
  ] },
  { id: 'bulk_result', ui: [{ type: 'batch_result', data: { batch_id: 'batch_collide1', operation: 'batch_order_tags_add',
    title: 'Tags added: 20 of 21', detail: LONG_SUBJECT, all_verified: false, summary: '20 applied, 1 not',
    counts: { requested: 23, eligible: 21, excluded: 2, verified: 20, unverified: 0, stale: 0, failed: 1, not_attempted: 0 },
    rows: [{ label: '#1938', outcome: 'applied', code: 'verified' }, { label: '#1935', outcome: 'not applied', code: 'failed' }],
    note: 'The one marked not applied was left as it was.',
    undo: { batch_id: 'batch_collide_undo', label: 'Undo all', interaction: 'hold_to_arm', ttl_s: 120, armed_after_ms: 650 } } }] },
  { id: 'variant_picker', ui: [{ type: 'variant_picker', data: { order_id: 'gid://shopify/Order/0', order_number: '#1938',
    count: 2, quantity: 2, max_quantity: 9, confident_variant_id: 'gid://shopify/ProductVariant/1',
    candidates: [
      { variant_id: 'gid://shopify/ProductVariant/1', title: LONG_TITLE, options: ['W34', 'L32', 'Unwashed'], price: BIG_MONEY, available: 3, tracked: true },
      { variant_id: 'gid://shopify/ProductVariant/2', title: 'Yard Jeans', options: ['W36', 'L32'], price: '£95.00', available: 0, tracked: true },
    ] } }] },
  // Everything at once, which is how a workbench screen actually looks.
  { id: 'everything', ui: [
    { type: 'order', data: order({ customer_name: LONG_NAME, customer_email: LONG_EMAIL, tags: CHIPS, note: LONG_NOTE, total: BIG_MONEY, shipping_address: LONG_ADDRESS, actions: ACTIONS_FIVE, items: [{ title: LONG_TITLE, variant: 'W34 / L32', sku: LONG_SKU, quantity: 2, total: BIG_MONEY, stock: { tracked: true, available: 0 } }] }) },
    { type: 'confirmation', data: confirmation([{ label: 'Tracking', value: LONG_TRACK }, { label: 'To', value: LONG_EMAIL }]) },
  ] },
];

// ---------------------------------------------------------------- the run

async function main() {
  const viewports = [];
  const caseNames = CASES.map((c) => c.id).concat(['idle_orb', 'idle_two_halves', 'nav_full_divided', 'split_mode', 'multiple_notifications',
    'stacked_feedback', 'offline_notice', 'keyboard_open']);
  const browser = await chromium.launch({ executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  try {
    for (const vp of VIEWPORTS) {
      await one(browser, vp);
      viewports.push(vp.name);
    }
  } finally {
    await browser.close();
  }
  const ok = checks.every((c) => c.ok);
  process.stdout.write(`${JSON.stringify({ ok, checks, shots, viewports, cases: caseNames })}\n`);
  return ok ? 0 : 1;
}

async function one(browser, vp) {
  const context = await browser.newContext({
    viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: vp.dpr,
    isMobile: true, hasTouch: true, extraHTTPHeaders: HEADERS,
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const from = (m.location && m.location() && m.location().url) || '';
    if (from.includes('/speak')) return;
    errors.push(`console: ${m.text()}`);
  });
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key","reason":"no voice under test"}' }));

  await page.goto(`${BASE}?dev=1`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(900);
  // The developer banner is a fixed strip over the top of the page that production never
  // shows. Leaving it in would be a collision this file invented.
  await page.evaluate(() => { for (const b of document.querySelectorAll('.dev-banner')) b.remove(); });

  const armed = await page.evaluate(() => Boolean(window.CrooksCollide && window.CrooksUI && window.CrooksUI.render));
  check(`${vp.name} · the page carries its renderer and its own geometry check`, armed, 'window.CrooksUI + window.CrooksCollide');
  if (!armed) { await context.close(); return; }

  // Draw through the app's own deck and the app's own renderer, exactly as the page does.
  await page.evaluate(() => {
    window.__collideDraw = (items) => {
      const root = document.querySelector('#cards');
      if (!root) return { nodes: 0, skipped: ['no deck'] };
      const out = window.CrooksUI.render(items, {});
      root.replaceChildren();
      out.nodes.forEach((n) => root.appendChild(n));
      document.body.dataset.mode = 'context';
      return { nodes: out.nodes.length, skipped: out.skipped };
    };
  });

  const results = [];
  // `opts` reaches `scan` unchanged: the keyboard case says so, because nothing in the page
  // can tell an open keyboard from a short screen — `interactive-widget=resizes-content`
  // makes them identical.
  const measure = async (id, opts) => {
    const scan = await page.evaluate((o) => window.CrooksCollide.scan(o || {}), opts || null);
    results.push({ id, scan });
    return scan;
  };

  // ---- the IDLE SCREEN, before anything is drawn, and then divided.
  //
  // This is the state the owner physically tapped twenty-six times in ten seconds, and no
  // Phase 4 fixture ever reached it: every one of the nineteen drew cards first, which puts
  // the page into context mode, where `#talk` is a dock band along the bottom and the branch
  // controls move into `#branch-rail`. The defect is on the ORB screen, where `.talk` is
  // `inset:0` and the chips are inside `.orb-zone`. Measured here, before the deck exists.
  await measure('idle_orb');
  await shot(page, `collide-${vp.width}-idle`);
  const divided = await page.evaluate(() => {
    const split = document.querySelector('#branch-bar [data-action="split"]');
    if (!split) return 'no split control on the idle screen';
    // A DOM click, deliberately: the point is to REACH the two-half state, not to prove a
    // finger can. Whether a finger can is what `split_under_voice` measures once it is there.
    split.click();
    return 'clicked';
  });
  await sleep(1800);
  const halves = await page.evaluate(() => ({
    mode: document.body.dataset.mode,
    chips: document.querySelectorAll('#branch-bar .branch-chip').length,
    acts: Array.from(document.querySelectorAll('#branch-bar .branch-act')).map((b) => b.dataset.action || ''),
  }));
  /* Asserted as the §25 rule rather than as "Merge is there", which is what this line said
     first and which was wrong on a fresh fork. A fork of an EMPTY half holds nothing, so
     keeping what it found and letting it go are the same act, and one control is drawn —
     `holdsSomething` in web/app.js sets that out, including why §18 is not the reason. The
     assertion is not weaker for saying so: it now pins the strip exactly, so a Merge that
     came back over an empty half would fail here, and so would a missing Close. */
  // [checker, 8 Oct 2026] Was 'the idle screen divides, and its un-divide strip is Close alone'
  // (a Split control, two halves, Close). Split is retired: George retired user-facing Split on
  // 20 September (DEC-050), which says Split-specific UI and tests are migration evidence, and
  // web/alpha.css hides the band. So the pinned value is turned round: no Split control, no
  // halves, no un-divide strip. The measurement below still runs on whatever the screen is.
  check(`${vp.name} · the idle screen offers no Split, and nothing divides it: Split is retired (DEC-050)`,
    divided === 'no split control on the idle screen' && halves.chips === 0 && halves.acts.length === 0,
    `${divided} — ${JSON.stringify(halves)}`);
  await measure('idle_two_halves');
  await shot(page, `collide-${vp.width}-idle-divided`);

  // ---- and the navigation row at its FULLEST: divided, with a list open, so Home, Back,
  // Previous, Next, two branch chips, Merge and Close are all in the strip at once. Asked
  // through the page's own dev input rather than drawn, because the row's contents are the
  // app's decision and the whole point is to measure what the app builds.
  //
  // This is the state the coordinator found by eye on the before-shots. On this tree the strip
  // is 571 px wide with 807 px in it, and Merge and Close are drawn at x=590 and x=664 on a
  // 601 px screen — entirely off the glass. No two rectangles intersect and the document does
  // not scroll sideways, so nothing before `control_clipped_by_container` could see it, and
  // "I cannot click the merge or close button" had been true all along.
  await page.evaluate(() => {
    const sheet = document.querySelector('#settings'); const dev = document.querySelector('#dev');
    if (dev) dev.hidden = false;
    if (sheet && !sheet.open && sheet.showModal) sheet.showModal();
  });
  const asked = await page.evaluate(() => Boolean(document.querySelector('#dev-text')));
  if (asked) {
    await page.fill('#dev-text', "show me today's orders");
    await page.press('#dev-text', 'Enter');
    await sleep(2800);
  }
  await page.evaluate(() => { const s = document.querySelector('#settings'); if (s && s.open) s.close(); });
  await sleep(500);
  /* WHAT THIS ASSERTS, and the two wrong versions before it.
     v1 was `nav.querySelectorAll('button').length >= 6` — a count, which passed for any six
     buttons. v2 named the parts but looked for all of them in `#context-nav`, and found no
     branch chip there at all: `{chips: 0, undivide: []}`.

     That is not a missing control, it is §8. The halves, their Merge and their Close are
     drawn in their OWN band (`#branch-zone`) and are never put in the navigation row — see
     the comment on `#branch-rail` in web/index.html. It is the answer to the finding this
     very fixture produced: a 571 px strip carrying 807 px of controls, with Merge at x=590
     and Close at x=664 on a 601 px screen. §25's answer to a strip that does not fit is to
     remove a control; §8's is that VOICE, NAVIGATION and SPLIT-BRANCH do not share a row.
     Both were done, and a check looking for the branch chrome in the navigation row was
     asserting the defect.

     So this asserts the ZONING, which is the claim actually being made: the navigation row
     holds the trail and the list cursor and NOTHING of the halves; the branch band holds the
     halves and their un-divide control; and the strip's contents fit the strip. The
     `measure()` below is unchanged and still covers the whole page, so the geometry rules
     see this state exactly as they did. */
  const strip = await page.evaluate(() => {
    const nav = document.querySelector('#context-nav');
    const zone = document.querySelector('#branch-zone');
    if (!nav) return null;
    const fits = (host) => (host
      ? Array.from(host.querySelectorAll('button')).filter((b) => {
        const r = b.getBoundingClientRect();
        return r.width > 0 && (r.left < -2 || r.right > innerWidth + 2);
      }).length
      : 0);
    return {
      mode: document.body.dataset.mode, width: nav.clientWidth, content: nav.scrollWidth,
      nav: {
        controls: nav.querySelectorAll('button').length,
        trail: Boolean(nav.querySelector('#home-btn, #back-btn, .chip-home, .chip-step')),
        cursor: Boolean(nav.querySelector('#next-btn, #prev-btn')),
        // §8: none of the two-half chrome may be in here.
        branch: nav.querySelectorAll('.branch-chip, .branch-act').length,
      },
      zone: {
        chips: zone ? zone.querySelectorAll('.branch-chip').length : -1,
        undivide: zone ? Array.from(zone.querySelectorAll('.branch-act')).map((b) => b.dataset.action || '').sort() : [],
      },
      past: fits(nav) + fits(zone),
    };
  });
  // [checker, 8 Oct 2026] Was 'the divided navigation row could be measured with a list open',
  // with two halves and an un-divide control in the branch band. With Split retired (DEC-050,
  // above) the band holds neither; the navigation row is measured with the list open as before.
  check(`${vp.name} · the navigation row could be measured with a list open, and no halves beside it`,
    Boolean(strip && strip.mode === 'context' && strip.nav.trail && strip.nav.cursor
      && strip.zone.chips <= 0 && strip.zone.undivide.length === 0), JSON.stringify(strip));
  check(`${vp.name} · §8 · navigation and the two halves are in different bands, and both fit the glass`,
    Boolean(strip && strip.nav.branch === 0 && strip.past === 0), JSON.stringify(strip));
  await measure('nav_full_divided');
  await shot(page, `collide-${vp.width}-nav-divided`);

  // ---- and back to ONE half before the payload fixtures.
  //
  // Not tidiness: attribution. The three states above are new in Phase 5, and leaving the orb
  // divided would put two branch chips, Merge and Close into the navigation row for every one
  // of the nineteen fixtures that follow — so `control_clipped_by_container` would fire on
  // `long_customer_name` and name a fixture that has nothing to do with it. The nineteen are
  // measured on the screen they have always been measured on, so a failure in one of them
  // still means what it used to mean, and the new findings stay attached to the new states.
  /* Merge if there is a Merge, Close otherwise. What this needs is ONE half, and §25 means
     the control that gives you one is not always called the same thing: the strip carries
     one control per distinct outcome, so a half holding nothing offers Close alone
     (`holdsSomething`, web/app.js). Naming `merge` only, as this did first, made the setup
     for nineteen fixtures depend on a control the design is entitled not to draw.
     The assertion itself has not moved a millimetre — `halvesLeft === 0`, and the detail
     says which route was taken so a silent change of route is still visible in the log. */
  const merged = await page.evaluate(() => {
    const where = '#branch-rail, #branch-bar';
    for (const verb of ['merge', 'cancel']) {
      const control = document.querySelector(`${where.split(', ').map((h) => `${h} [data-action="${verb}"]`).join(', ')}`);
      if (control) { control.click(); return `clicked ${verb}`; }
    }
    return 'no un-divide control at all';
  });
  await sleep(2000);
  const halvesLeft = await page.evaluate(() => document.querySelectorAll('.branch-chip').length);
  check(`${vp.name} · the halves come back together, so the stress fixtures are measured undivided`,
    halvesLeft === 0, `${merged}; ${halvesLeft} chip(s) left`);

  // ---- the fixtures, one at a time
  const fake = [];
  for (const item of CASES) {
    const drawn = await page.evaluate((items) => window.__collideDraw(items), item.ui);
    if (!drawn.nodes) { check(`${vp.name} · ${item.id} renders`, false, `nodes=${drawn.nodes} skipped=${(drawn.skipped || []).join(',')}`); continue; }
    await page.waitForTimeout(140);
    // Open everything a tap would open, so the measurement covers the folded-away parts too:
    // a tab that has never been selected has never been laid out.
    await page.evaluate(() => {
      for (const t of document.querySelectorAll('#cards [role="tab"]')) t.click();
      for (const f of document.querySelectorAll('#cards .fold-head')) f.click();
    });
    await page.waitForTimeout(140);
    await measure(item.id);
    fake.push(...await fakeControls(page, item.id));
  }
  await shot(page, `collide-${vp.width}-cards`);

  // §6: if something looks clickable, one of these must be true. A. it works completely.
  // B. it is visibly disabled with a useful reason. C. it is changed so it no longer looks
  // clickable. There is no D — and "there is no D" is a claim about EVERY control, which no
  // per-case test can make. This is the sweep: every fixture, both viewports, every element
  // a thumb would read as a control.
  //
  // It would have caught the one this pass found by accident: `h()` stringified a null
  // dataset value, so `data-command` became the four characters "null" and every rail chip
  // on every card posted a command by that name and took a 400. The chips looked perfect.
  check(`${vp.name} · every control either works, or says why it cannot`, fake.length === 0,
    fake.slice(0, 6).map((f) => `${f.where}: ${f.sel} — ${f.why}`).join(' | '));

  // ---- and the number a future session will record.
  //
  // This is the whole point of the exercise. `ts-20260911-001845` reported `clipped: 0` on
  // every render while the owner was looking at overlapping text and controls; the flag was
  // not lying, it was answering a narrower question. The snapshot now carries the answer to
  // his question, from the same scan this file asserts on — so if the two ever disagree, the
  // telemetry has stopped measuring and the gate says so.
  const reported = await page.evaluate(() => {
    const snap = window.CrooksTelemetry.snapshot(document.querySelector('#cards'), {});
    const scan = window.CrooksCollide.scan({});
    return {
      flag: snap.overflow.collisions,
      total: snap.collisions ? snap.collisions.total : null,
      measured: snap.collisions ? snap.collisions.measured : 0,
      scan: scan.total,
      clipped: snap.overflow.clipped,
    };
  });
  check(`${vp.name} · the telemetry records the real collision count, not a flag`,
    reported.flag !== null && reported.flag === reported.scan && reported.measured > 40,
    JSON.stringify(reported));

  // ---- the split: two halves, the branch selector on screen, and a message about one of them
  await page.evaluate(() => {
    const split = document.querySelector('#branch-bar [data-action="split"], #branch-rail [data-action="split"]');
    if (split) split.click();
  });
  await sleep(1800);
  await measure('split_mode');
  await shot(page, `collide-${vp.width}-split`);

  // ---- the most notifications the policy allows at once, through whatever the page provides
  //
  // THREE, and no arrangement of calls produces a fourth: two that will leave on their own
  // (MAX_TRANSIENT), of which one may be a success (MAX_GOOD), plus a failure, which waits to
  // be dismissed and is counted by neither cap. So this is the worst case the geometry has to
  // survive, and it is the worst case by construction rather than by choice.
  //
  // `draft_saved` used to be the first of these and is now REFUSED by name: §10 puts that
  // outcome on the Save draft control, not in a message (docs/phase5/NOTIFICATION_POLICY.md).
  // A fixture that draws a message the product would never draw measures nothing.
  const noted = await page.evaluate(() => {
    if (window.CrooksNotify && typeof window.CrooksNotify.show === 'function') {
      window.CrooksNotify.show({ text: 'The refund was proved on the store.', class: 'workspace', tone: 'good', code: 'refund_proved' });
      window.CrooksNotify.show({ text: '2 changes came back still waiting for you.', class: 'workspace', tone: 'warn', code: 'merge_waiting' });
      window.CrooksNotify.show({ text: 'The Mac cannot be reached. Nothing is lost; it will answer when it is back.', class: 'global', tone: 'bad', code: 'backend_down', machine: true });
      return 'notify';
    }
    // The old way: one floating bubble, which is the thing this run is here to measure.
    const node = document.querySelector('#toast');
    if (!node) return 'none';
    node.textContent = 'Merged. 2 changes still waiting over there.';
    node.hidden = false;
    return 'toast';
  });
  await page.waitForTimeout(200);
  await measure('multiple_notifications');
  await shot(page, `collide-${vp.width}-notifications`);

  // ---- §9's "stacked feedback": the deck full of cards AND several messages at once, which
  // is the state the live session was in when "Merged. 2 changes still waiting over there."
  // floated over the half he was reading. Measured on the CONTEXT screen, because that is
  // where the navigation row, the deck and the dock are all on the glass together.
  await page.evaluate((items) => window.__collideDraw(items), CASES.find((c) => c.id === 'everything').ui);
  await page.waitForTimeout(160);
  await page.evaluate(() => {
    if (!window.CrooksNotify || typeof window.CrooksNotify.show !== 'function') return;
    window.CrooksNotify.show({ text: 'Draft saved in Gmail drafts.', class: 'workspace', tone: 'good', code: 'draft_saved' });
    window.CrooksNotify.show({ text: 'Archive verified on the Mac.', class: 'workspace', tone: 'good', code: 'archive_verified' });
    window.CrooksNotify.show({ text: 'Merged. 2 changes still waiting over there.', class: 'workspace', tone: '', code: 'merged' });
    window.CrooksNotify.show({ text: 'This build must be updated before it can be used.', class: 'global', tone: 'bad', code: 'stale_build', machine: true });
  });
  await page.waitForTimeout(260);
  await measure('stacked_feedback');
  await shot(page, `collide-${vp.width}-stacked`);

  // ---- §9's "offline notice": the one message the machine itself is allowed to put over
  // every screen. It must take its own space above the wordmark rather than cover the dock,
  // the orb, the halves or the composer — which is a geometry claim, so it is measured.
  await page.evaluate(() => {
    if (window.CrooksNotify && typeof window.CrooksNotify.clear === 'function') window.CrooksNotify.clear();
    if (window.CrooksNotify && typeof window.CrooksNotify.show === 'function') {
      window.CrooksNotify.show({
        text: 'The Mac cannot be reached. Nothing is lost; it will answer when it is back.',
        class: 'global', tone: 'bad', code: 'backend_down', machine: true,
      });
    }
    const conn = document.querySelector('#conn');
    if (conn) { conn.dataset.state = 'down'; const t = document.querySelector('#conn-text'); if (t) t.textContent = 'Offline'; }
  });
  await page.waitForTimeout(260);
  await measure('offline_notice');
  await shot(page, `collide-${vp.width}-offline`);

  // ---- the keyboard: `interactive-widget=resizes-content` shrinks the viewport, so this is
  // the same thing the tablet does when a finger lands in a field.
  await page.evaluate((items) => window.__collideDraw(items), CASES.find((c) => c.id === 'composer').ui);
  await page.waitForTimeout(160);
  await page.setViewportSize({ width: vp.width, height: Math.round(vp.height * 0.47) });
  await page.waitForTimeout(220);
  await page.evaluate(() => { const f = document.querySelector('#cards .field-input'); if (f && f.focus) f.focus(); });
  await page.waitForTimeout(260);
  await measure('keyboard_open', { keyboard: true });
  await shot(page, `collide-${vp.width}-keyboard`);
  await page.setViewportSize({ width: vp.width, height: vp.height });
  await page.waitForTimeout(160);

  // ---- one check per rule, naming every fixture that broke it
  const RULES = await page.evaluate(() => window.CrooksCollide.RULES);
  const WORDS = {
    control_over_control: 'no interactive control overlaps another',
    text_over_control: 'no text overlaps an action control',
    notification_over_chrome: 'no notification overlaps the dock, the orb or the halves',
    rail_over_content: 'no action rail overlaps content',
    document_overflow_x: 'nothing scrolls the page sideways by accident',
    folded_action: 'no action is folded away to nothing',
    content_under_chrome: 'nothing essential is hidden under the fixed furniture',
    split_under_voice: 'the Split chip is not under the voice target',
    branch_under_voice: 'no branch chip, Merge or Close is under the voice target',
    button_over_input: 'no control overlaps a field',
    button_over_navigation: 'no control overlaps Back, Next, Home or the dock',
    toast_over_navigation: 'no message overlaps the navigation row',
    toast_over_orb: 'no message overlaps the orb',
    toast_over_approval: 'no message overlaps an approval surface',
    floating_over_dock: 'no floating control overlaps the dock',
    tabs_over_content: 'no tab strip overlaps the panel it switches',
    name_over_action: 'no customer or product name overlaps an action',
    chips_over_title: 'no status chip overlaps a card title',
    keyboard_over_action: 'with the keyboard open, no action is under the fixed furniture',
    control_clipped_by_container: 'no interactive control is cut off by the screen or by a container',
  };
  for (const rule of RULES) {
    const bad = results.filter((r) => (r.scan.counts || {})[rule]);
    const detail = bad.map((r) => {
      const hit = (r.scan.hits || []).find((x) => x.rule === rule) || {};
      return `${r.id}: ${(r.scan.counts || {})[rule]}× ${hit.a || ''}[${hit.at || ''}]${hit.b ? ` / ${hit.b}[${hit.bt || ''}]` : ''}${hit.note ? ` (${hit.note})` : ''}`;
    }).join(' | ');
    check(`${vp.name} · ${WORDS[rule] || rule}`, bad.length === 0, detail);
  }

  // ---- §9's own list, answered by name. The brief names fourteen pairs and asks for a
  // verdict on each; `CrooksCollide.PAIRS` maps its words onto the rules that answer them, so
  // this loop prints the brief's list and nothing is translated by hand. A pair with no rule
  // behind it fails here — the gate cannot quietly stop asking one of the fourteen.
  const PAIRS = await page.evaluate(() => window.CrooksCollide.PAIRS);
  const REQUIRED_PAIRS = ['button-button', 'button-text', 'button-input', 'button-navigation',
    'Split-voice', 'branch-voice', 'toast-navigation', 'toast-orb', 'toast-approval',
    'floating-controls-dock', 'tabs-content', 'long-name-action', 'chips-title', 'keyboard-action'];
  const missingPairs = REQUIRED_PAIRS.filter((label) => !PAIRS[label]);
  check(`${vp.name} · §9 · every pair the brief names has a rule behind it`, missingPairs.length === 0,
    missingPairs.join(', '));
  for (const label of REQUIRED_PAIRS) {
    const bad = results.filter((r) => ((r.scan.pairs || {})[label] || 0) > 0);
    const detail = bad.map((r) => {
      const rules = PAIRS[label] || [];
      const hit = (r.scan.hits || []).find((x) => rules.indexOf(x.rule) !== -1) || {};
      return `${r.id}: ${(r.scan.pairs || {})[label]}× ${hit.a || ''}[${hit.at || ''}]${hit.b ? ` / ${hit.b}[${hit.bt || ''}]` : ''}${hit.note ? ` (${hit.note})` : ''}`;
    }).join(' | ');
    check(`${vp.name} · §9 pair · ${label}`, bad.length === 0, detail);
  }

  // ---- §9's HARD GATE. "For the primary viewport (601×889, DPR ~1.33): zero collisions
  // involving interactive elements. If an interactive collision is detected in browser
  // acceptance, THE TEST FAILS — do not merely record it as telemetry."
  //
  // This is the line Phase 4 did not have. Its collision run measured, reported and passed:
  // `overflow.collisions` was 1 to 4 on twenty of the live session's orb-screen renders while
  // this suite was green, because no check anywhere turned a number into a verdict. One
  // interactive overlap at either size now fails the release, and the failure names the
  // fixture, the two selectors and the two rectangles.
  const interactive = results.filter((r) => (r.scan.interactive || 0) > 0);
  const worst = interactive.flatMap((r) => (r.scan.interactive_hits || []).slice(0, 2)
    .map((h) => `${r.id}: ${h.rule} ${h.a}[${h.at}]${h.b ? ` / ${h.b}[${h.bt}]` : ''}${h.note ? ` (${h.note})` : ''}`));
  check(`${vp.name} · §9 · ZERO collisions involving an interactive element`,
    interactive.length === 0,
    `${interactive.reduce((n, r) => n + r.scan.interactive, 0)} across ${interactive.length} fixture(s) — ${worst.slice(0, 8).join(' | ')}`);

  // ---- and the thumb (section 29), from the same rectangles
  const small = [];
  for (const r of results) {
    for (const t of r.scan.touch || []) {
      if (!small.some((s) => s.sel === t.sel)) small.push({ id: r.id, sel: t.sel, w: t.w, h: t.h });
    }
  }
  check(`${vp.name} · every control a finger uses is about 44px`, small.length === 0,
    small.map((s) => `${s.sel} ${s.w}×${s.h} (${s.id})`).join(', '));

  // The eight driven states are not payloads: the idle screen, the idle screen divided, the
  // divided navigation row, the split in context mode, three messages, four over a full deck,
  // the offline notice, and the keyboard.
  const DRIVEN = 8;
  check(`${vp.name} · every fixture was measured`, results.length === CASES.length + DRIVEN,
    `${results.length} of ${CASES.length + DRIVEN}: ${results.map((r) => r.id).join(',')}`);
  check(`${vp.name} · the notification path is the one the page owns`, noted === 'notify', `via ${noted}`);
  check(`${vp.name} · no script error while measuring`, errors.length === 0, errors.slice(0, 3).join(' | '));
  await context.close();
}

/* Every element in the deck a thumb would read as a control, judged against §6.
 *
 * A control is FINE when it is disabled and says so (aria-disabled or :disabled, with words
 * in it or beside it), or when it is enabled and carries something to act on — a command the
 * Mac named, a reference to open, a role the page wires by class. It is FAKE when it is
 * enabled and carries nothing, or when what it carries is empty or the literal string
 * "null"/"undefined", which is what a stringified absent value looks like by the time it
 * reaches the DOM.
 */
async function fakeControls(page, where) {
  return page.evaluate((at) => {
    const WIRED = ['data-command', 'data-ref', 'data-area', 'data-proposal', 'data-tab',
                   'data-compose', 'data-field', 'data-action', 'data-branch', 'data-nav'];
    // A control wired by an addEventListener carries nothing a page script can see — there is
    // no way to ask the DOM what listeners a node has. So the contract is a CONVENTION: a
    // control the renderer wires itself declares one of these classes. That makes this check
    // an allowlist rather than a proof, and the allowlist is the point — a new control that
    // is neither on it nor carrying data fails here until somebody says which it is.
    const CLASS_WIRED = /\b(disc-head|fold-head|link-btn|rail-chip|row|tab|dock-btn|chip-step|action-surface|note-close|step-btn|msg|filter-chip)\b/;
    const bad = [];
    const nodes = document.querySelectorAll('#cards button, #cards [role="button"], #cards [role="tab"], #cards a[href], #cards .tappable, #cards [data-command]');
    for (const el of nodes) {
      const box = el.getBoundingClientRect();
      if (box.width < 2 || box.height < 2) continue;          // not on the screen at all
      const sel = el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).split(' ')[0] : '');
      const off = el.disabled === true || el.getAttribute('aria-disabled') === 'true';
      if (off) {
        // B: visibly disabled, and the reason is words the owner can read — on it, or on the
        // thing it sits in. A disabled control that says nothing is worse than no control.
        const words = (el.textContent || '') + ' ' + (el.getAttribute('title') || '') + ' '
          + (el.getAttribute('aria-label') || '') + ' ' + ((el.parentNode && el.parentNode.textContent) || '');
        if (words.trim().length < 2) bad.push({ where: at, sel, why: 'disabled and says nothing' });
        continue;
      }
      // A: enabled, so it must carry something to act on.
      let carries = CLASS_WIRED.test(String(el.className || '')) || el.tagName === 'A';
      for (const name of WIRED) {
        if (!el.hasAttribute(name)) continue;
        const value = String(el.getAttribute(name) || '').trim();
        if (!value || value === 'null' || value === 'undefined') {
          bad.push({ where: at, sel, why: `${name}="${value}"` });
          carries = true;      // it is reported already; do not report it twice as bare
          break;
        }
        carries = true;
      }
      if (!carries) bad.push({ where: at, sel, why: 'enabled and carries nothing to act on' });
    }
    return bad;
  }, where);
}

async function shot(page, name) {
  if (!OUT) return;
  const file = path.join(OUT, `${name}.png`);
  await page.waitForTimeout(320);
  await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
  shots.push(path.basename(file));
}

main().then((code) => process.exit(code)).catch((e) => {
  process.stdout.write(`${JSON.stringify({ ok: false, checks: [{ name: 'collision run', ok: false, detail: String(e && e.message).slice(0, 400) }], shots })}\n`);
  process.exit(1);
});

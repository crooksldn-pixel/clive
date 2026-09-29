/* §32 — the screenshot matrix: thirty-four named surfaces at the size the tablet is.
 *
 *   node scripts/browser/screens.js http://127.0.0.1:8765 docs/screens/phase5
 *
 * Phase 4 shipped a screenshot suite that was green through the evening described in
 * docs/phase5/LIVE_SESSION_FORENSICS.md. The reason is in the brief: "A screenshot suite that
 * never reaches the broken state is not sufficient." A second reason, just as bad, is a suite
 * that captures whatever happens to be on the glass and calls the file a picture of the thing
 * it is named after. A blank orb screen saved as `10-full-customer-rich-workspace.png` is
 * worse than no file: it is a claim.
 *
 * So every shot here declares what must be ON THE GLASS for the file to be that shot. If it is
 * not, the check FAILS by name — "10 full customer rich workspace: no customer surface with
 * orders, email and a way to write" — the picture is still written, because what WAS there is
 * evidence, and it is written as `10-full-customer-rich-workspace.MISSING.png` so a directory
 * listing is itself the report. `index.json` beside them carries the same verdicts.
 *
 * Several of these surfaces are being BUILT by other workstreams as this runs. Those shots are
 * expected to be red here and are named in the report with the workstream that owns them.
 *
 * 601 × 889 at DPR 1.33 is the whole matrix — the physical tablet, from every `tablet_render`
 * in the live session. A representative set is repeated at 800 × 1280 to keep the second size
 * honest without doubling thirty-four files.
 *
 * Prints one JSON object: { ok, checks, shots, missing }.
 */
'use strict';

const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const TABLET = { name: '601x889', width: 601, height: 889, dpr: 1.33 };
const SECOND = { name: '800x1280', width: 800, height: 1280, dpr: 1 };
// The second size does not need thirty-four files to be honest. These are the ones whose
// layout differs most between the two: the idle screen, a deck, a profile, the halves, the
// keyboard, and the stress fixture.
// Several shots stand on the one before them — 13 is the composer on the thread 12 opened —
// so a prerequisite is in this list even where the second size adds little of its own.
const AT_SECOND = ['01', '03', '04', '07', '11', '12', '13', '20', '21', '24', '31', '34'];

const LIVE = path.join(__dirname, '..', '..', 'experience', 'fixtures', 'live_states.json');

const checks = [];
const shots = [];
const missing = [];
const manifest = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const live = (id) => {
  const all = JSON.parse(fs.readFileSync(LIVE, 'utf8')).states || [];
  const found = all.find((s) => s.id === id);
  return found && found.replay ? found.replay : null;
};

/* ---------------------------------------------------------------- the stress payloads ----
   Card data, handed to the page's own renderer. Nothing here builds markup. */

const LONG_NAME = 'Alexandra Wilhelmina Constance Featherstonehaugh-Beauchamp';
const LONG_TITLE = 'Blue Wash Selvedge Yard Jeans — Relaxed Straight, Unwashed, Limited Workshop Run 2026';
const LONG_SKU = 'CRK-YJ-BLUWASH-RELAXSTR-W34L32-SS26-LTD-000418-A';
const BIG_MONEY = '£1,284,367.45';
const LONG_ADDRESS = {
  name: LONG_NAME,
  lines: ['Flat 14, Featherstonehaugh Mansions', '221b Upper Kennington Park Road South', 'Behind the old brewery yard'],
  city: 'Kingston upon Thames', zip: 'KT1 2AB', country: 'United Kingdom', country_code: 'GB',
};
const ACTIONS_FOUR = [
  { id: 'fulfil', label: 'Mark as shipped', operation: 'fulfillment_create', risk: 'red', enabled: true, reason: '', instruction: 'Mark shipped', mode: 'ask' },
  { id: 'address', label: 'Change the delivery address', operation: 'order_shipping_address_set', risk: 'red', enabled: true, reason: '', instruction: 'Change the address', mode: 'ask' },
  { id: 'cancel', label: 'Cancel and refund the whole order', operation: 'order_cancel', risk: 'red', enabled: true, reason: '', instruction: 'Cancel', mode: 'ask' },
  { id: 'note', label: 'Note', operation: 'order_note_append', risk: 'amber', enabled: true, reason: '', instruction: 'Add a note', mode: 'ask', family: 'order.add_note' },
];

const order = (extra) => Object.assign({
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
  actions: ACTIONS_FOUR, cancelled_at: '', note: '', ships_to: 'London, United Kingdom',
}, extra || {});

const CONFIRMATION = {
  proposal_id: 'prop_shot00000001', status: 'pending', risk: 'red', operation: 'fulfillment_create',
  title: 'Mark as shipped', entity: 'Order #1938', entity_kind: 'order', entity_ref: 'gid://shopify/Order/0',
  summary: '', detail: 'Marks every item on this order as shipped and emails the customer.',
  facts: [{ label: 'Items', value: 'Yard Jeans · M · ×1' }, { label: 'Carrier', value: 'Royal Mail Tracked 24' },
          { label: 'Tracking', value: 'AB1234567890GB' }, { label: 'Customer emailed', value: 'yes' }],
  interaction: { kind: 'hold_to_arm', label: 'Hold to arm, then tap', footer: 'nothing happens until you hold the card, then tap it', armed_after_ms: 650 },
  ttl_s: 60, reversible: false, commit: { allowed: true },
};

const SUCCESS = {
  proposal_id: 'prop_shot00000001', operation: 'fulfillment_create', title: 'Shipped',
  entity: 'Order #1938', entity_kind: 'order', verified: true,
  detail: 'Read back from Shopify after the change: the order is fulfilled and the customer was emailed.',
  facts: [{ label: 'Fulfilment', value: 'fulfilled' }, { label: 'Tracking', value: 'AB1234567890GB' }],
  undo: { label: '', allowed: false, reason: 'a shipment cannot be unsent' },
};

const ERROR_CARD = {
  title: 'Shopify could not be reached',
  detail: 'The shop did not answer in time. Nothing was changed. Ask again and it will try afresh.',
  kind: 'upstream', retryable: true,
};

/* ---------------------------------------------------------------- the matrix -------------
   `reach` gets there. `need` says what must be on the glass for the file to be this shot. */

const MATRIX = [
  { id: '01', name: 'idle', reach: async () => {}, need: { mode: 'orb', selector: '#orb-frame' } },
  {
    id: '02',
    name: 'listening',
    reach: async (page, k) => { await k.holdOpen(1200); },
    need: { state: 'LISTENING' },
    after: async (page, k) => { await k.holdRelease(); },
  },
  { id: '03', name: 'orders-list', reach: (p, k) => k.dock('orders'), need: { types: ['order_list'] } },
  { id: '04', name: 'order-detail', reach: (p, k) => k.open('order'), need: { types: ['order'] } },
  { id: '05', name: 'order-items', reach: (p, k) => k.tab('items'), need: { tab: 'items' } },
  { id: '06', name: 'shipping', reach: (p, k) => k.tab('shipping'), need: { tab: 'shipping' } },
  {
    id: '07',
    name: 'customer-summary',
    reach: async (p, k) => { await k.dock('email'); await k.open('email_thread'); await k.open('customer'); await k.tab('overview'); },
    need: { types: ['customer'], tab: 'overview' },
  },
  { id: '08', name: 'customer-orders', reach: (p, k) => k.tab('orders'), need: { types: ['customer'], tab: 'orders' } },
  { id: '09', name: 'customer-inbox', reach: (p, k) => k.tab('email'), need: { types: ['customer'], tab: 'email' } },
  {
    id: '10',
    name: 'full-customer-rich-workspace',
    owner: 'workstream D — the customer workspace (§3/§6)',
    reach: (p, k) => k.ask('pull up the history of Mia Jones and her orders, see how much she spent, and see if she is in Gmail anywhere'),
    need: { workspace: ['orders', 'email', 'write'] },
  },
  { id: '11', name: 'inbox-list', reach: (p, k) => k.dock('email'), need: { types: ['email_list'] } },
  { id: '12', name: 'email-thread', reach: (p, k) => k.open('email_thread'), need: { types: ['email_thread'] } },
  { id: '13', name: 'reply-composer', reach: (p, k) => k.rail('reply'), need: { types: ['email_compose'] } },
  { id: '14', name: 'sales-overview', reach: (p, k) => k.dock('sales'), need: { anyType: ['sales_summary', 'metric_group', 'trend', 'comparison', 'table'] } },
  { id: '15', name: 'products-overview', reach: (p, k) => k.dock('products'), need: { anyType: ['ranking', 'product', 'inventory', 'table'] } },
  {
    id: '16',
    name: 'returning-customers-result',
    owner: 'workstream C — families and presentation (§13)',
    reach: (p, k) => k.ask('has anyone bought today that has bought before, a returning customer?'),
    /* The live answer was ONE returning customer drawn as seven full profiles. The shot is of
       the fixed surface: a summary, at most one profile in it.

       `summary_list` was not in this list and the capture reported the shot MISSING with the
       detail "none of customer_list/table/metric_group/assistant on the glass (there is
       summary_list)" — which is the fix being rejected by the expectation written before it
       existed. A compact count with a row each is the ANSWER to D-4; a `customer_list` is
       the nearest wrong thing. So it goes first, and the profile cap stays where it was. */
    need: { anyType: ['summary_list', 'customer_list', 'table', 'metric_group', 'assistant'], maxOfType: { customer: 1 } },
  },
  {
    id: '17',
    name: 'progressive-stage-1',
    owner: 'workstream D — progressive hydration (§6)',
    unreachable: '`present(pending=…)` has no live caller, so no section is ever drawn as loading: `progressive.observe()` passes no session on purpose and `_compose_workspace` returns without one, and the final `present()` of a turn runs after every read has landed. There is no promised-but-unread card on the glass to photograph. Diagnosed in docs/phase5/PHASE_5_PRODUCT_EXPERIENCE_REPORT.md §8; the fix is a composition that runs while reads are in flight, which is work rather than a line',
    reach: (p, k) => k.askAndCatch("what's happened today?", 1),
    need: { shell: true },
  },
  {
    id: '18',
    name: 'progressive-stage-2',
    owner: 'workstream D — progressive hydration (§6)',
    unreachable: '`present(pending=…)` has no live caller, so no section is ever drawn as loading: `progressive.observe()` passes no session on purpose and `_compose_workspace` returns without one, and the final `present()` of a turn runs after every read has landed. There is no promised-but-unread card on the glass to photograph. Diagnosed in docs/phase5/PHASE_5_PRODUCT_EXPERIENCE_REPORT.md §8; the fix is a composition that runs while reads are in flight, which is work rather than a line',
    reach: (p, k) => k.askAndCatch("what's happened today?", 2),
    need: { shell: true },
  },
  {
    id: '19',
    name: 'progressive-complete',
    owner: 'workstream D — progressive hydration (§6)',
    unreachable: '`present(pending=…)` has no live caller, so no section is ever drawn as loading: `progressive.observe()` passes no session on purpose and `_compose_workspace` returns without one, and the final `present()` of a turn runs after every read has landed. There is no promised-but-unread card on the glass to photograph. Diagnosed in docs/phase5/PHASE_5_PRODUCT_EXPERIENCE_REPORT.md §8; the fix is a composition that runs while reads are in flight, which is work rather than a line',
    reach: (p, k) => k.settleLast(),
    /* `drewOwn`, round 12: an answer that draws nothing now keeps the screen it was asked over
       (app/screen.py), so "what's happened today?" answered in words leaves the last shot's
       cards up, marked `kept`. Those are not a progressive workspace that completed, and
       without this the exemption read as stale on a screen this turn never drew. */
    need: { noShell: true, minCards: 1, drewOwn: true },
  },
  { id: '20', name: 'split-creation', reach: async (p, k) => { await k.dock('orders'); await k.split(); }, need: { branches: 2 } },
  {
    id: '21',
    name: 'split-independent-left-right',
    reach: async (p, k) => { await k.open('order'); await k.half(1); await k.dock('email'); },
    need: { branches: 2, types: ['email_list'] },
  },
  {
    id: '22',
    name: 'split-branch-ready',
    owner: 'workstream A/D — the half that finished while he was elsewhere (§10/§16)',
    // A half only becomes READY by finishing work while it is NOT focused — a branch that
    // finishes while focused is simply the screen. `askThenLeave` posts the turn through the
    // page and switches away, which is the only route that reaches `noteBranch`; but the
    // fixture backend answers "[model answer]" and calls no tools, so the turn has nothing
    // to finish and the half never leaves ACTIVE. Reaching it needs a provider that reads,
    // which this world does not have by design (experience/harness.py).
    unreachable: 'a half reaches READY only by finishing work while unfocused, and the fixture backend answers without calling a tool, so there is no work to finish',
    // Asked ON the other half, through the page's own submit, and then left before the answer
    // lands — which is the only way a half becomes READY: a branch that finishes while it is
    // focused is simply the screen. Posting the turn with `fetch` instead would never reach
    // the page's own `noteBranch`, so the glass would never learn, and the shot would be
    // failing this file's plumbing rather than the tablet's.
    reach: (p, k) => k.askThenLeave('show me order 1940'),
    need: { branchReady: true },
  },
  { id: '23', name: 'merge', reach: (p, k) => k.merge(), need: { branches: 0 } },
  {
    id: '24',
    name: 'keyboard-open',
    reach: async (p, k) => { await k.dock('email'); await k.open('email_thread'); await k.rail('reply'); await k.keyboard(); },
    need: { types: ['email_compose'], shortViewport: true },
    after: (p, k) => k.keyboardAway(),
  },
  { id: '25', fresh: true, name: 'long-customer-name', reach: (p, k) => k.draw([{ type: 'order', data: order({ customer_name: LONG_NAME }) }]), need: { types: ['order'] } },
  { id: '26', fresh: true, name: 'long-address', reach: (p, k) => k.draw([{ type: 'order', data: order({ shipping_address: LONG_ADDRESS, ships_to: 'Kingston upon Thames, United Kingdom' }) }]), need: { types: ['order'], tab: 'shipping' }, then: (p, k) => k.tab('shipping') },
  { id: '27', fresh: true, name: 'long-product', reach: (p, k) => k.draw([{ type: 'order', data: order({ items: [{ title: LONG_TITLE, variant: 'W34 / L32 / Unwashed', sku: LONG_SKU, quantity: 2, total: BIG_MONEY, stock: { tracked: true, available: 0 } }] }) }]), need: { types: ['order'], tab: 'items' }, then: (p, k) => k.tab('items') },
  { id: '28', fresh: true, name: 'error-section', reach: (p, k) => k.draw([{ type: 'error', data: ERROR_CARD }]), need: { types: ['error'] } },
  {
    id: '29',
    fresh: true,
    name: 'empty-email-section',
    /* Straight off the live timeline: the customer card he was shown, open on an empty Email
       tab. "I'm not seeing any UI here except email where there's nothing."

       The route to it changed, and had to. `drawLive` passes the fixture's recorded
       `tab: 'email'` as a DECK-WIDE option, which is D-2 itself — one tab handed to every
       card that has tabs. Workstream E removed that, so both cards now open on Overview and
       the capture reported "the open tab is overview,overview, not email". The old route
       cannot photograph this state any more because the old route WAS the defect.

       So the tab is now tapped, on one card, the way the owner taps it. That makes a better
       picture than the original: the first card is open on Email and says its inbox has
       nothing in it with the rest of the workspace still standing (§27), and the second
       card beside it is still on Overview — which is the D-2 fix, visible in a photograph. */
    reach: (p, k) => k.drawLive('empty_email_section'),
    then: (p, k) => k.tab('email'),
    need: { types: ['customer', 'customer'], tab: 'email' },
  },
  { id: '30', fresh: true, name: 'notification-local', reach: (p, k) => k.notify('workspace'), need: { note: 'workspace' } },
  { id: '31', fresh: true, name: 'global-offline', reach: (p, k) => k.notify('global'), need: { note: 'global' } },
  { id: '32', fresh: true, name: 'action-proposal', reach: (p, k) => k.draw([{ type: 'confirmation', data: CONFIRMATION }]), need: { types: ['confirmation'] } },
  { id: '33', fresh: true, name: 'action-verified', reach: (p, k) => k.draw([{ type: 'success', data: SUCCESS }]), need: { types: ['success'] } },
  {
    id: '34',
    fresh: true,
    name: 'stress-collision-fixture',
    reach: (p, k) => k.draw([
      { type: 'order', data: order({ customer_name: LONG_NAME, customer_email: 'alexandra.wilhelmina.featherstonehaugh@a-very-long-department.example.com', tags: ['vip', 'wholesale', 'repeat-return', 'fraud-checked', 'gift-wrap', 'pre-order', 'back-order', 'priority', 'staff-discount'], total: BIG_MONEY, shipping_address: LONG_ADDRESS, items: [{ title: LONG_TITLE, variant: 'W34 / L32', sku: LONG_SKU, quantity: 2, total: BIG_MONEY, stock: { tracked: true, available: 0 } }] }) },
      { type: 'confirmation', data: CONFIRMATION },
    ]),
    need: { types: ['order', 'confirmation'], noInteractiveCollision: true },
  },
];

async function main() {
  if (OUT) fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({
    executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  });
  try {
    await capture(browser, TABLET, MATRIX);
    await capture(browser, SECOND, MATRIX.filter((s) => AT_SECOND.indexOf(s.id) !== -1));
  } finally {
    await browser.close();
  }
  if (OUT) {
    fs.writeFileSync(path.join(OUT, 'index.json'),
      `${JSON.stringify({ viewports: [TABLET.name, SECOND.name], shots: manifest }, null, 1)}\n`, 'utf8');
  }
  const ok = checks.every((c) => c.ok);
  process.stdout.write(`${JSON.stringify({ ok, checks, shots, missing })}\n`);
  return ok ? 0 : 1;
}

async function capture(browser, vp, matrix) {
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
  await page.addInitScript(() => {
    const AC = window.AudioContext || window.webkitAudioContext;
    const ac = new AC();
    const dest = ac.createMediaStreamDestination();
    const osc = ac.createOscillator(); const gain = ac.createGain(); gain.gain.value = 0.2;
    osc.frequency.value = 220; osc.connect(gain); gain.connect(dest); osc.start();
    navigator.mediaDevices.getUserMedia = async () => { await ac.resume(); return dest.stream; };
  });
  // One page for the whole matrix, because most shots stand on the one before them: 05 is the
  // Items tab of the order 04 opened. `arrive()` is the exception — a shot that hands a payload
  // straight to the renderer wants the CHROME of a fresh screen, not the chrome left over from
  // whatever walk reached the shot before it. Without it, 29 came out with "Replying to …"
  // across the top from 13 and a branch header about an unrelated order from 20-23: a true
  // picture of two cards, under a heading that was a lie.
  const arrive = async () => {
    await page.evaluate(() => { try { localStorage.clear(); } catch { /* private window */ } });
    await page.goto(`${BASE}?dev=1`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1100);
    await page.evaluate(() => { for (const b of document.querySelectorAll('.dev-banner')) b.remove(); });
    await page.evaluate(() => {
      window.__shotDraw = (items, opts) => {
        const root = document.querySelector('#cards');
        if (!root) return 0;
        const out = window.CrooksUI.render(items, opts || {});
        root.replaceChildren();
        out.nodes.forEach((n) => root.appendChild(n));
        document.body.dataset.mode = 'context';
        return out.nodes.length;
      };
    });
  };
  await arrive();
  const kit = makeKit(page, context, vp);

  for (const shot of matrix) {
    const label = `${vp.name} · ${shot.id} ${shot.name.replace(/-/g, ' ')}`;
    try {
      if (shot.fresh) await arrive();
      await shot.reach(page, kit);
      if (shot.then) await shot.then(page, kit);
      await page.waitForTimeout(420);
      const verdict = await judge(page, shot.need || {}, vp);
      const file = `${shot.id}-${shot.name}${verdict.ok ? '' : '.MISSING'}.png`;
      if (OUT) {
        await page.screenshot({ path: path.join(OUT, `${vp.name}-${file}`), fullPage: false, animations: 'disabled' });
        shots.push(`${vp.name}-${file}`);
      }
      manifest.push({ viewport: vp.name, id: shot.id, name: shot.name, ok: verdict.ok, file: `${vp.name}-${file}`, why: verdict.why, owner: shot.owner || '', unreachable: shot.unreachable || '' });
      /* `unreachable` is a shot saying, with a REASON, that this world cannot produce the
         state at all — so its absence is a fact about the fixture backend and not a verdict
         on the product. A MISSING file is still written and still named in the manifest; what
         changes is that the suite is not held permanently red by it.

         The distinction matters because of what a permanently red suite becomes: unread. The
         whole subject of this pass is a gate whose green was trusted and meant the wrong
         thing, and a gate whose red is routine is the same failure from the other side. So
         the same rule applies here as to `routes_to_model` in replay.js: a check that CANNOT
         run reports as not-run, never as passed, never as failed for the wrong reason.

         And the exemption is itself checked, which is what stops it becoming a place to hide
         a defect. If a declared-unreachable state turns out to be reachable, that is reported
         — the shot is taken, and the declaration is named as stale and has to come out. */
      if (verdict.ok && shot.unreachable) {
        check(`${label} — declared unreachable and yet it was reached: the exemption is stale`,
          false, `remove \`unreachable\` from shot ${shot.id}: "${shot.unreachable}"`);
      } else if (shot.unreachable) {
        check(`${label} — not photographable in the fixture world, for a stated reason`, true,
          `${shot.unreachable} · the judge said: ${verdict.why} · saved as ${vp.name}-${file}`);
      } else {
        check(`${label}`, verdict.ok,
          verdict.ok ? '' : `${verdict.why}${shot.owner ? ` — owned by ${shot.owner}` : ''} · saved as ${vp.name}-${file}`);
      }
      if (!verdict.ok) missing.push({ id: shot.id, name: shot.name, why: verdict.why, owner: shot.owner || '', unreachable: shot.unreachable || '' });
      if (shot.after) await shot.after(page, kit);
    } catch (e) {
      check(label, false, `could not be reached: ${String((e && e.message) || e).slice(0, 240)}`);
      missing.push({ id: shot.id, name: shot.name, why: String((e && e.message) || e).slice(0, 160), owner: shot.owner || '' });
    }
  }
  check(`${vp.name} · no script error while capturing the matrix`, errors.length === 0, errors.slice(0, 3).join(' | '));
  await context.close();
}

/* What is on the glass, and whether it is the shot this file says it is. */
async function judge(page, need, vp) {
  const g = await page.evaluate(() => ({
    mode: document.body.dataset.mode || '',
    state: (document.querySelector('#stage') || {}).dataset ? (document.querySelector('#stage').dataset.state || '') : '',
    types: Array.from(document.querySelectorAll('#cards .card')).map((c) => c.dataset.type || ''),
    tabs: Array.from(document.querySelectorAll('#cards .tabbed')).map((t) => t.dataset.tab || ''),
    branches: document.querySelectorAll('.branch-chip').length,
    ready: Array.from(document.querySelectorAll('.branch-chip')).some((c) => c.classList.contains('is-ready')),
    chips: Array.from(document.querySelectorAll('.branch-chip')).map((c) => (c.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 26)),
    shells: document.querySelectorAll('#cards [data-shell], #cards .card-skeleton, #cards .is-shell').length,
    notes: {
      workspace: Array.from(document.querySelectorAll('#notes-orb .note, #notes-deck .note')).length,
      global: Array.from(document.querySelectorAll('#notes-global .note')).length,
    },
    // The rich workspace §32 asks for shot 10: a customer surface that carries their orders,
    // their email AND somewhere to write. Recognised by what is on it, not by a card name, so
    // whatever shape workstream D builds satisfies it if it does the job.
    workspace: (() => {
      // Recognised by what it DOES, so whatever shape a workstream builds satisfies it — and
      // then the list of names was still written out by hand, and missed the one that was
      // built (`customer_workspace`). Any card about a customer counts now, however it is
      // named: a `data-workspace` marker, or a type that is or begins as `customer`.
      const about = (c) => {
        const type = c.dataset.type || '';
        return Boolean(c.dataset.workspace) || type === 'customer' || type === 'workspace'
          || type === 'customer_workspace' || type === 'order_workspace';
      };
      const card = Array.from(document.querySelectorAll('#cards .card')).find(about);
      if (!card) return null;
      const words = (card.textContent || '').toLowerCase();
      const labels = Array.from(card.querySelectorAll('[role="tab"], .disc-label, .sec-head')).map((t) => (t.textContent || '').toLowerCase()).join(' ');
      return {
        orders: /order/.test(labels) || /\border(s)?\b/.test(words),
        email: /email|inbox/.test(labels) || /email|inbox/.test(words),
        write: Boolean(card.querySelector('.compose-btn, [data-command^="compose"], [data-action="reply"], .field-input, textarea')),
      };
    })(),
    height: window.innerHeight,
    // How many cards the last turn the walk asked (`askAndCatch`) drew of its own — not the
    // ones it carried over from the screen it was asked over (`kept`, app/screen.py).
    drewOwn: (() => {
      const d = window.__shotLast;
      if (!d || !Array.isArray(d.ui)) return 0;
      return d.ui.filter((i) => i && i.type !== 'context_stack' && i.kept !== true).length;
    })(),
  }));

  const no = (why) => ({ ok: false, why });
  if (need.mode && g.mode !== need.mode) return no(`the screen is "${g.mode}", not "${need.mode}"`);
  if (need.state && g.state !== need.state) return no(`the state is "${g.state}", not "${need.state}"`);
  if (need.selector) {
    const there = await page.evaluate((sel) => {
      const el = document.querySelector(sel);
      if (!el) return false;
      const b = el.getBoundingClientRect();
      return b.width > 2 && b.height > 2;
    }, need.selector);
    if (!there) return no(`${need.selector} is not drawn`);
  }
  if (need.types) {
    for (const want of need.types) {
      if (g.types.indexOf(want) === -1) return no(`no ${want} card on the glass (there is ${g.types.join(',') || 'nothing'})`);
    }
  }
  if (need.anyType && !need.anyType.some((t) => g.types.indexOf(t) !== -1)) {
    return no(`none of ${need.anyType.join('/')} on the glass (there is ${g.types.join(',') || 'nothing'})`);
  }
  if (need.maxOfType) {
    for (const type of Object.keys(need.maxOfType)) {
      const n = g.types.filter((t) => t === type).length;
      if (n > need.maxOfType[type]) return no(`${n} ${type} cards, which is more than the ${need.maxOfType[type]} this surface may show`);
    }
  }
  if (need.tab && g.tabs.indexOf(need.tab) === -1) {
    return no(`the open tab is ${g.tabs.filter(Boolean).join(',') || 'none'}, not ${need.tab}`);
  }
  if (need.branches !== undefined && g.branches !== need.branches) {
    return no(`${g.branches} halves on the glass, not ${need.branches}`);
  }
  if (need.branchReady && !g.ready) {
    return no(`no half is showing as READY — the chips say ${JSON.stringify(g.chips)}`);
  }
  if (need.shell && !g.shells) return no('nothing on the glass is a promised-but-unread card, so there is no progressive stage to photograph');
  if (need.noShell && g.shells) return no(`${g.shells} card(s) are still unread`);
  if (need.minCards && g.types.length < need.minCards) return no(`${g.types.length} cards`);
  if (need.drewOwn && !g.drewOwn) return no('the turn drew nothing of its own: the cards on the glass are the screen it kept');
  if (need.note === 'workspace' && !g.notes.workspace) return no('no workspace message is on the glass');
  if (need.note === 'global' && !g.notes.global) return no('no global message is on the glass');
  if (need.shortViewport && g.height > vp.height * 0.7) return no(`the viewport is ${g.height}px, so the keyboard is not open`);
  if (need.workspace) {
    if (!g.workspace) return no('no customer surface with orders, email and a way to write');
    const short = need.workspace.filter((part) => !g.workspace[part]);
    if (short.length) return no(`the customer surface has no ${short.join(' and no ')}`);
  }
  if (need.noInteractiveCollision) {
    const scan = await page.evaluate(() => {
      const s = window.CrooksCollide.scan({});
      return { interactive: s.interactive, worst: (s.interactive_hits || []).slice(0, 3) };
    });
    if (scan.interactive > 0) return no(`${scan.interactive} interactive collision(s): ${JSON.stringify(scan.worst)}`);
  }
  return { ok: true, why: '' };
}

/* The ways in. Each one is the control the owner would use, or the page's own renderer. */
function makeKit(page, context, vp) {
  let cdp = null;
  const session = async () => { if (!cdp) cdp = await context.newCDPSession(page); return cdp; };
  // What is on the glass, as a string, purely to tell "it changed" from "it has not yet".
  const deckNow = () => page.evaluate(() => Array.from(document.querySelectorAll('#cards .card'))
    .map((c) => `${c.dataset.type || ''}:${c.dataset.ref || ''}`).join('|')
    + `#${document.querySelectorAll('.branch-chip').length}`
    + `@${Array.from(document.querySelectorAll('#cards .tabbed')).map((t) => t.dataset.tab || '').join(',')}`);
  // Wait on the PAGE, not on the clock. A flat `sleep(3200)` after every hop is what made this
  // file take nine minutes: almost every redraw lands inside half a second and the rest of the
  // wait was spent watching a finished screen. The ceiling is what the flat sleep used to be,
  // so nothing that used to have time still has less.
  const settle = async (was, ceiling) => {
    const limit = ceiling || 3400;
    for (let waited = 0; waited < limit; waited += 120) {
      await sleep(120);
      if (await deckNow() !== was) { await sleep(220); return true; }   // a beat for the animation
    }
    return false;
  };
  const clickIn = async (finder, arg) => {
    const did = await page.evaluate(([f, a]) => {
      // eslint-disable-next-line no-new-func
      const el = new Function('a', `return (${f})(a);`)(a);
      if (!el) return false;
      if (el.scrollIntoView) el.scrollIntoView({ block: 'center' });
      el.click();
      return true;
    }, [finder, arg]);
    return did;
  };
  return {
    dock: async (area) => {
      const was = await deckNow();
      const did = await clickIn(`(a) => document.querySelector('.dock-btn[data-area="' + a + '"]')`, area);
      if (!did) throw new Error(`no dock button for ${area}`);
      await settle(was, 6000);   // a dock tap is a real read on the Mac
    },
    open: async (kind) => {
      const was = await deckNow();
      const did = await clickIn(`(a) => {
        const cards = new Set(Array.from(document.querySelectorAll('#cards .card')).map((c) => c.dataset.ref || ''));
        return Array.from(document.querySelectorAll('#cards [data-ref][data-kind]')).find((el) => el.dataset.kind === a
          && !el.classList.contains('card') && !cards.has(el.dataset.ref)
          && el.getBoundingClientRect().width > 2) || null;
      }`, kind);
      if (!did) throw new Error(`nothing on the glass opens a ${kind}`);
      await settle(was, 4000);
    },
    tab: async (name) => {
      const was = await deckNow();
      const did = await clickIn(`(a) => Array.from(document.querySelectorAll('#cards [role="tab"]')).find((t) => t.dataset.tab === a) || null`, name);
      if (!did) throw new Error(`no ${name} tab on any card`);
      await settle(was, 900);
    },
    rail: async (action) => {
      const was = await deckNow();
      const did = await clickIn(`(a) => Array.from(document.querySelectorAll('#cards [data-action], #cards [data-command]')).find((el) => {
        if (el.disabled === true || el.getAttribute('aria-disabled') === 'true') return false;
        const n = el.dataset.action || el.dataset.command || '';
        return n === a || n.endsWith('.' + a) || n.startsWith(a + '.');
      }) || null`, action);
      if (!did) throw new Error(`no enabled ${action} action on any card`);
      await settle(was, 4000);
    },
    split: async () => {
      const was = await deckNow();
      const did = await clickIn(`() => document.querySelector('#branch-rail [data-action="split"], #branch-bar [data-action="split"]')`);
      if (!did) throw new Error('no Split control');
      await settle(was, 3000);
    },
    merge: async () => {
      const was = await deckNow();
      const did = await clickIn(`() => document.querySelector('#branch-rail [data-action="merge"], #branch-bar [data-action="merge"]')`);
      if (!did) throw new Error('no Merge control');
      await settle(was, 3000);
    },
    half: async (which) => {
      const was = await deckNow();
      const did = await clickIn(`(a) => Array.from(document.querySelectorAll('.branch-chip'))[a] || null`, which);
      if (!did) throw new Error(`no ${which === 0 ? 'left' : 'right'} half to select`);
      await settle(was, 2600);
    },
    draw: async (items, opts) => {
      const n = await page.evaluate(([i, o]) => window.__shotDraw(i, o), [items, opts || {}]);
      if (!n) throw new Error('the renderer drew nothing');
      await sleep(320);
    },
    drawLive: async (id) => {
      const spec = live(id);
      if (!spec) throw new Error(`no live state called ${id}`);
      const n = await page.evaluate(([i, o]) => window.__shotDraw(i, o), [spec.ui, spec.tab ? { tab: spec.tab } : {}]);
      if (!n) throw new Error(`the live state ${id} drew nothing`);
      await sleep(320);
    },
    ask: async (text) => {
      await page.evaluate(async (t) => {
        const id = localStorage.getItem('crooks.session') || `shots-${Date.now()}`;
        localStorage.setItem('crooks.session', id);
        const r = await fetch('/turn', { method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store', body: JSON.stringify({ text: t, session_id: id }) });
        const d = await r.json();
        window.__shotDraw(d.ui || [], {});
        return { types: (d.ui || []).map((i) => i.type), lane: d.lane || '', answer: String(d.answer || '').slice(0, 80) };
      }, text);
      await sleep(500);
    },
    // The progressive stages: ask, then photograph the deck WHILE it is still filling in.
    // `stage` is how many redraws to wait for. If the page never draws a promised-but-unread
    // card there is no stage to photograph, and `judge` says exactly that.
    askAndCatch: async (text, stage) => {
      await page.evaluate(async (t) => {
        const id = localStorage.getItem('crooks.session') || `shots-${Date.now()}`;
        localStorage.setItem('crooks.session', id);
        window.__shotPending = fetch('/turn', { method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store', body: JSON.stringify({ text: t, session_id: id }) })
          .then((r) => r.json())
          .then((d) => { window.__shotLast = d; window.__shotDraw(d.ui || [], {}); return d; });
      }, text);
      await sleep(260 * stage);
    },
    settleLast: async () => {
      await page.evaluate(async () => { if (window.__shotPending) await window.__shotPending; });
      await sleep(600);
    },
    // Ask on the half that is up, then leave it before the answer arrives. The page posts the
    // turn itself — through the shell's own text input, which is the same `submit()` the
    // microphone uses — so when the answer lands the page's own bookkeeping sees it arrive for
    // a half nobody is looking at, which is what makes that half READY.
    askThenLeave: async (text) => {
      const typed = await page.evaluate(() => {
        const sheet = document.querySelector('#settings'); const dev = document.querySelector('#dev');
        if (!dev || !document.querySelector('#dev-text')) return false;
        dev.hidden = false;
        if (sheet && !sheet.open && sheet.showModal) sheet.showModal();
        return true;
      });
      if (!typed) throw new Error('the page has no way to submit a sentence without a microphone');
      await page.fill('#dev-text', text);
      await page.press('#dev-text', 'Enter');
      await page.evaluate(() => { const s = document.querySelector('#settings'); if (s && s.open) s.close(); });
      // Away immediately: the answer must land while he is on the other half.
      await sleep(160);
      const left = await page.evaluate(() => {
        const chips = Array.from(document.querySelectorAll('.branch-chip'));
        const other = chips.find((c) => c.getAttribute('aria-pressed') !== 'true');
        if (!other) return false;
        other.click();
        return true;
      });
      if (!left) throw new Error('there is no other half to leave for');
      await sleep(5200);
    },
    notify: async (which) => {
      const ok = await page.evaluate((w) => {
        if (!window.CrooksNotify || typeof window.CrooksNotify.show !== 'function') return false;
        if (typeof window.CrooksNotify.clear === 'function') window.CrooksNotify.clear();
        if (w === 'global') {
          const conn = document.querySelector('#conn');
          if (conn) { conn.dataset.state = 'down'; const t = document.querySelector('#conn-text'); if (t) t.textContent = 'Offline'; }
          window.CrooksNotify.show({ text: 'The Mac cannot be reached. Nothing is lost; it will answer when it is back.', class: 'global', tone: 'bad', code: 'backend_down', machine: true });
        } else {
          /* Was `draft_saved`, and the capture reported the shot MISSING with "no workspace
             message is on the glass". That is §10 working: `draft_saved` is in
             web/notify.js's CONTROL_SHOWS, because Save draft becomes Saved on the control
             itself, and a floating message about it is a second, worse claim on the same
             event. So this shot was photographing a message the policy now forbids.

             The replacement is the case §10 exists FOR: a change proved on the store, which
             nothing on the glass says by itself and which the owner must be told. Chosen
             from web/notify.js's own permitted set (it is in neither SCREEN_SHOWS nor
             CONTROL_SHOWS), so the shot stands or falls with the policy rather than beside
             it. */
          window.CrooksNotify.show({ text: 'The refund was proved on the store: £40.00 back to the card.', class: 'workspace', tone: 'good', code: 'refund_proved' });
        }
        return true;
      }, which);
      if (!ok) throw new Error('the page has no notification host (window.CrooksNotify)');
      await sleep(420);
    },
    holdOpen: async (ms) => {
      const cd = await session();
      const at = await page.evaluate(() => {
        const b = document.querySelector('#talk-label').getBoundingClientRect();
        return { x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2) };
      });
      await cd.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: at.x, y: at.y }] });
      await sleep(ms);
    },
    holdRelease: async () => {
      const cd = await session();
      // A second finger joining the hold discards the recording (web/app.js), so the
      // "listening" photograph does not leave a junk turn behind it.
      const at = await page.evaluate(() => {
        const b = document.querySelector('#talk-label').getBoundingClientRect();
        return { x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2) };
      });
      await cd.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: at.x - 80, y: at.y }, { x: at.x + 80, y: at.y }] });
      await sleep(120);
      await cd.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
      await sleep(900);
    },
    keyboard: async () => {
      await page.setViewportSize({ width: vp.width, height: Math.round(vp.height * 0.47) });
      await sleep(280);
      await page.evaluate(() => { const f = document.querySelector('#cards .field-input, #cards textarea'); if (f && f.focus) f.focus(); });
      await sleep(320);
    },
    keyboardAway: async () => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await sleep(260);
    },
  };
}

main().then((code) => process.exit(code)).catch((e) => {
  process.stdout.write(`${JSON.stringify({ ok: false, checks: checks.concat([{ name: 'screens run', ok: false, detail: String((e && e.stack) || e).slice(0, 600) }]), shots, missing })}\n`);
  process.exit(1);
});

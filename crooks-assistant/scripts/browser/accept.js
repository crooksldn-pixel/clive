/* CROOKS OS in a real Chromium: the checks a string test cannot make.
 *
 * Run by scripts/accept.py against a backend it has already started. Needs Playwright
 * (`npm i -g playwright`, and the Chromium it downloads); accept.py skips this file when it
 * is absent. Nothing here reaches Shopify, Gmail or ElevenLabs: /speak and /actions are
 * answered by stubs in the page, the way the tablet's own tests answer them.
 *
 *   node scripts/browser/accept.js http://127.0.0.1:8765 /path/to/screenshots
 *
 * Prints one JSON object: { ok, checks: [{ name, ok, detail }], timing }.
 */
'use strict';

// `playwright` on the Mac, which bundles its own Chromium; `playwright-core` in the checks
// that run alongside the suite, which points at the one already on disk. Either resolves.
const { chromium } = (() => {
  try { return require('playwright'); } catch { return require('playwright-core'); }
})();
const fs = require('fs');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
const VIEWPORT = { width: 800, height: 1280 };   // the Galaxy Tab A 8.0, portrait

const ORDER_TURN = {
  session_id: 'accept', turn_id: 'turn_accept0001', turns: 1, answer: 'Order 1930. Paid, not shipped. One pair of Yard Jeans, sixty pounds.',
  question: 'Show me order 1930', error_kind: null, lost_thread: false, state: 'READY', revoked: [],
  tool_calls: [{ name: 'shopify_order_detail', ok: true, error: null, ms: 412, args: {} }], transcript: null,
  timings_ms: { agent: 2100, total: 2400 },
  ui: [{ type: 'order', data: { order_id: 'o1', order_number: '#1930', placed_at: '2026-09-08T09:42:00Z', fulfillment: 'unfulfilled', payment: 'paid', total: '£60.00', customer_name: 'Sam Fixture', customer_id: 'c1', customer_email: 'sam@example.com', detail: true, items: [{ title: 'Yard Jeans', variant: 'M', sku: 'YJ-M', quantity: 1, total: '£60.00', stock: { tracked: true, available: 3 } }], items_truncated: false, fulfillments: [], cancelled_at: '', note: '', ships_to: 'London, United Kingdom', money: { subtotal: '£55.00', shipping: '£5.00', tax: '£9.17' }, shipping_address: { name: 'Sam Fixture', lines: ['12 Somewhere Street'], city: 'London', zip: 'E1 6AN', country: 'United Kingdom' }, history: { orders: 3, spent: '£410.00', standing: 'returning', recent: [] }, email: { available: true, threads: [] }, pending: [] } }],
};
const VERIFIED = {
  proposal_id: 'prop_fixture0000', status: 'verified', code: 'verified', spoken: 'Order note added.',
  ui: [{ type: 'success', data: { title: 'Note added', detail: 'Order #1930', proposal_id: 'prop_fixture0000' } }],
  undo: { proposal_id: 'prop_undo0000', status: 'pending', ttl_s: 60, undo_of: 'prop_fixture0000' },
};
const FIXTURES = ['Order', 'Order · still reading', 'Orders today', 'Customer', 'Which customer', 'Product', 'Inventory', 'Sales', 'Email list', 'Email thread', 'Email · hold to arm', 'Email draft', 'Attention', 'Cancel · hold and drag', 'Refund · hold and drag', 'Address · hold to arm', 'Fulfil · hold to arm', 'Stock · hold to arm', 'Swipe · irreversible amber', 'Confirmation', 'Success', 'Error', 'Context stack', 'Best sellers', 'Restock priority', 'This week against last', 'Sizes matrix', 'Sales trend', 'Figures', 'Table', 'Working set', 'Bulk tag · hold to arm', 'Bulk drafts · hold and drag', 'Bulk result'];

const checks = [];
const check = (name, ok, detail) => { checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail) }); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  // A bundled Chromium needs no path. playwright-core has none of its own, so it is told
  // where one is — the same file the other browser scripts use.
  const onDisk = process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
  const browser = await chromium.launch(fs.existsSync(onDisk) ? { executablePath: onDisk } : {});
  const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  // Prefixed, because this file's names (01-, 02-, ...) are the same names experience.js
  // uses and the screenshot index writes every gate into one directory.
  const shot = async (name) => { if (OUT) await page.screenshot({ path: path.join(OUT, `accept-${name}.png`) }); };
  const posts = [];
  const telemetry = [];   // every batch the page posted to /telemetry; the Mac keeps them too
  await page.route('**/telemetry', (route) => { telemetry.push(route.request().postData() || ''); route.continue(); });
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key","reason":"no voice under test"}' }));
  await page.route('**/actions/**', (route) => {
    const req = route.request();
    if (req.method() === 'POST') {
      posts.push({ url: req.url(), body: req.postData() || '' });
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(VERIFIED) });
    }
    return route.continue();
  });

  // 1. Boot: the page comes online with no script error.
  await page.goto(`${BASE}/?dev=1`, { waitUntil: 'load' });
  let online = true;
  try { await page.waitForFunction(() => document.getElementById('system').dataset.phase === 'online', null, { timeout: 30000 }); } catch { online = false; }
  check('page boots to online', online && errors.length === 0, errors.join(' | ') || 'no page errors');
  await sleep(600);
  await shot('01-ready');

  // 2. Every state has its own words on the label.
  const labels = {};
  for (const s of ['LISTENING', 'TRANSCRIBING', 'THINKING', 'CHECKING SHOPIFY', 'CHECKING EMAIL', 'SPEAKING', 'SUCCESS', 'ERROR']) {
    await page.evaluate((st) => setState(st), s);
    await sleep(250);
    labels[s] = await page.evaluate(() => `${document.getElementById('stage').dataset.state}|${document.getElementById('state-label').textContent}|${document.getElementById('state-sub').textContent}`);
    await shot(`02-state-${s.toLowerCase().replace(/ /g, '-')}`);
  }
  const distinct = new Set(Object.values(labels).map((v) => v.split('|')[1]));
  check('every state has its own label', distinct.size === 8, JSON.stringify(labels));
  const dock = await page.evaluate(() => { setState('SPEAKING'); return document.getElementById('talk-label').textContent; });
  check('the dock offers to interrupt while speaking', dock === 'Hold to interrupt', dock);
  await page.evaluate(() => setState('READY'));

  // 3. A turn: the first visible change at once, the transcript early, the card when the answer lands.
  await page.route('**/turn', async (route) => { await sleep(1500); route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ORDER_TURN) }); });
  await page.route('**/state/**', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ known: true, state: 'CHECKING SHOPIFY', detail: 'shopify_order_detail', heard: 'Show me order 1930' }) }));
  await page.click('#settings-btn'); await page.waitForSelector('#dev-text');
  const timing = await page.evaluate(async () => {
    const stage = document.getElementById('stage'); const heard = document.getElementById('heard'); const sub = document.getElementById('state-sub');
    const t0 = performance.now(); const marks = {};
    const input = document.getElementById('dev-text'); input.value = 'Show me order 1930';
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    return await new Promise((resolve) => {
      const tick = () => {
        const now = performance.now() - t0;
        if (!marks.state_ms && stage.dataset.state !== 'READY') marks.state_ms = Math.round(now);
        if (!marks.heard_ms && heard.textContent) marks.heard_ms = Math.round(now);
        if (!marks.detail && sub.textContent === 'Reading the order') marks.detail = Math.round(now);
        if (!marks.card_ms && document.querySelector('#cards .card-order')) marks.card_ms = Math.round(now);
        if (marks.card_ms || now > 6000) resolve(marks); else requestAnimationFrame(tick);
      };
      tick();
    });
  });
  check('a turn shows a state change at once', timing.state_ms !== undefined && timing.state_ms < 100, JSON.stringify(timing));
  check('the transcript shows before the answer', timing.heard_ms !== undefined && timing.card_ms !== undefined && timing.heard_ms < timing.card_ms, `heard ${timing.heard_ms} ms, card ${timing.card_ms} ms`);
  check('the running tool shows in plain words', timing.detail !== undefined, 'Reading the order');
  await sleep(400);
  await shot('03-order-turn');
  await page.unroute('**/turn'); await page.unroute('**/state/**');

  // 4. Every fixture renders without a script error.
  for (const label of FIXTURES) {
    await page.click('#settings-btn'); await page.waitForSelector('#dev-grid button');
    await page.locator('#dev-grid button', { hasText: label }).first().click();
    await sleep(350);
    await shot(`04-fixture-${label.toLowerCase().replace(/ /g, '-')}`);
  }
  const cards = await page.evaluate(() => document.querySelectorAll('#cards .card').length);
  check('every fixture renders', errors.length === 0 && cards > 0, errors.join(' | ') || `${cards} card(s) on the last fixture`);

  // 5. The action card: dead time, one tap, one POST, only the session id, success from the answer.
  await page.click('#settings-btn'); await page.waitForSelector('#dev-grid button');
  await page.locator('#dev-grid button', { hasText: 'Confirmation' }).first().click();
  await page.waitForSelector('.card-confirmation');
  const surface = page.locator('.action-surface').first();
  const early = await surface.getAttribute('data-state');
  await surface.dispatchEvent('pointerdown'); await surface.dispatchEvent('pointerup');
  await sleep(120);
  check('a tap in the dead time does nothing', early === 'arming' && posts.length === 0, `state ${early}, ${posts.length} POST(s)`);
  await sleep(700);
  const armed = await surface.getAttribute('data-state');
  await shot('05-action-armed');
  await surface.dispatchEvent('pointerdown'); await surface.dispatchEvent('pointerup');
  await surface.dispatchEvent('pointerdown'); await surface.dispatchEvent('pointerup');
  await page.waitForSelector('.card-success', { timeout: 5000 }).catch(() => {});
  await sleep(200);
  // The body is multipart form data; every field it carries is named here, and there must
  // be exactly one: the session id. No argument of the change ever travels from the tablet.
  const fields = (posts[0] ? posts[0].body : '').match(/name="([^"]+)"/g) || [];
  const only = posts.length === 1 && /\/actions\/prop_fixture0000\/commit$/.test(posts[0].url) && fields.length === 1 && fields[0] === 'name="session_id"';
  check('an armed tap posts once, with only the session id', armed === 'armed' && only, JSON.stringify(posts));
  const success = await page.evaluate(() => ({ success: Boolean(document.querySelector('.card-success')), undo: document.querySelector('.card-success .action-surface') ? document.querySelector('.card-success .action-surface').dataset.state : null }));
  check('success is shown only from the verified answer, with its undo', success.success && success.undo !== null, JSON.stringify(success));
  await shot('05-action-verified');

  // 6. A blocked proposal names who is stopping it and never posts.
  posts.length = 0;
  await page.evaluate(() => {
    const items = [{ type: 'confirmation', data: { proposal_id: 'prop_blocked', status: 'pending', risk: 'amber', operation: 'order_note_append', title: 'Add order note', entity: 'Order #1930', entity_kind: 'order', entity_ref: 'gid://shopify/Order/0', summary: 'Hold for collection.', interaction: { kind: 'tap_commit', label: 'Tap to apply', armed_after_ms: 650 }, ttl_s: 60, reversible: true, commit: { allowed: false, code: 'writes_disabled', reason: 'Changes are switched off on the Mac (CROOKS_WRITES_ENABLED).' } } }];
    const r = window.CrooksUI.render(items, renderOpts()); pushContext(r.nodes, items, 'blocked');
  });
  await sleep(900);
  const blocked = await page.evaluate(() => { const s = document.querySelector('.action-surface'); return { state: s.dataset.state, label: s.textContent.trim(), kicker: document.querySelector('.card-confirmation .card-kicker') ? document.querySelector('.card-confirmation .card-kicker').textContent : '' }; });
  const bs = page.locator('.action-surface').first();
  await bs.dispatchEvent('pointerdown'); await bs.dispatchEvent('pointerup');
  await sleep(150);
  // [checker, 8 Oct 2026] Was /switched off on the Mac/: the owner-facing words name the server
  // since the wording pass of commit 6713d1ed (production is a Linux server, not the Mac).
  check('a blocked proposal says why and cannot be tapped', blocked.state === 'unavailable' && /switched off on the server/.test(blocked.label) && posts.length === 0, JSON.stringify(blocked));
  await shot('06-action-blocked');

  // 7. A card expires on the tablet a second before the Mac would say so.
  await page.evaluate(() => {
    const items = [{ type: 'confirmation', data: { proposal_id: 'prop_short', status: 'pending', risk: 'amber', operation: 'order_note_append', title: 'Add order note', entity: 'Order #1930', entity_kind: 'order', entity_ref: 'gid://shopify/Order/0', summary: 'Short-lived.', interaction: { kind: 'tap_commit', label: 'Tap to apply', armed_after_ms: 100 }, ttl_s: 2, reversible: true } }];
    const r = window.CrooksUI.render(items, renderOpts()); pushContext(r.nodes, items, 'short');
  });
  await sleep(1400);
  const expired = await page.evaluate(() => document.querySelector('.action-surface').dataset.state);
  check('a card expires on the tablet before the Mac would refuse it', expired === 'expired', expired);

  // 8. A new instruction withdraws exactly the cards the Mac names.
  await page.evaluate(() => {
    const items = [{ type: 'confirmation', data: { proposal_id: 'prop_live', status: 'pending', risk: 'amber', operation: 'order_note_append', title: 'Add order note', entity: 'Order #1930', entity_kind: 'order', entity_ref: 'gid://shopify/Order/0', summary: 'Live.', interaction: { kind: 'tap_commit', label: 'Tap to apply', armed_after_ms: 100 }, ttl_s: 60, reversible: true } }];
    const r = window.CrooksUI.render(items, renderOpts()); pushContext(r.nodes, items, 'live');
  });
  await sleep(300);
  await page.route('**/turn', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(Object.assign({}, ORDER_TURN, { revoked: ['prop_live'], ui: [] })) }));
  await page.click('#settings-btn'); await page.waitForSelector('#dev-text');
  await page.evaluate(() => { const input = document.getElementById('dev-text'); input.value = 'and yesterday?'; input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); });
  await sleep(900);
  const withdrawn = await page.evaluate(() => { const s = document.querySelector('[data-proposal="prop_live"] .action-surface'); return s ? s.dataset.state : 'gone'; });
  check('a new instruction withdraws the card the Mac names', withdrawn === 'revoked', withdrawn);
  await page.unroute('**/turn');

  // 8b. A spoken yes re-presents the waiting card; the tablet keeps the one it shows.
  // The Mac that answers /turn here is a stand-in, so it answers the reconciliation too:
  // the page asks what became of every card it shows, and a double that says "pending" on
  // one route and knows nothing on another is not a Mac, it is two.
  await page.route('**/actions/states*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_known: true, states: { prop_again: { proposal_id: 'prop_again', status: 'pending', kind: 'action' } }, unknown: [] }) }));
  await page.evaluate(() => {
    const items = [{ type: 'confirmation', data: { proposal_id: 'prop_again', status: 'pending', risk: 'amber', operation: 'order_note_append', title: 'Add order note', entity: 'Order #1930', entity_kind: 'order', entity_ref: 'gid://shopify/Order/0', summary: 'Kept.', interaction: { kind: 'tap_commit', label: 'Tap to apply', armed_after_ms: 100 }, ttl_s: 60, reversible: true } }];
    const r = window.CrooksUI.render(items, renderOpts()); pushContext(r.nodes, items, 'again');
  });
  await sleep(300);
  const before = await page.evaluate(() => ({ cards: document.querySelectorAll('#cards .card').length, node: Boolean(document.querySelector('[data-proposal="prop_again"]')) }));
  await page.route('**/turn', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(Object.assign({}, ORDER_TURN, { answer: 'Nothing happens until you tap the card. It is still waiting on the tablet.', revoked: [], ui: [{ type: 'confirmation', data: { proposal_id: 'prop_again', status: 'pending', risk: 'amber', operation: 'order_note_append', title: 'Add order note', entity: 'Order #1930', entity_kind: 'order', entity_ref: 'gid://shopify/Order/0', summary: 'Kept.', interaction: { kind: 'tap_commit', label: 'Tap to apply', armed_after_ms: 100 }, ttl_s: 55, reversible: true, commit: { allowed: true } } }] })) }));
  await page.click('#settings-btn'); await page.waitForSelector('#dev-text');
  await page.evaluate(() => { const input = document.getElementById('dev-text'); input.value = 'yes'; input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); });
  await sleep(900);
  const after = await page.evaluate(() => ({ cards: document.querySelectorAll('#cards .card').length, state: document.querySelector('[data-proposal="prop_again"] .action-surface').dataset.state, copies: document.querySelectorAll('[data-proposal="prop_again"]').length }));
  check('a spoken yes keeps the card that is already on screen', before.node && after.cards === before.cards && after.copies === 1 && after.state === 'armed', JSON.stringify({ before, after }));
  await page.unroute('**/turn');

  // 8c. The same card, and a Mac that says it is no longer holding it: the card stops
  // claiming to be tappable. This is the September discrepancy in the other direction — the
  // tablet reported a commit the Mac never claimed — and the page now asks rather than
  // remembers. A Mac that does not know the conversation is not evidence either way.
  await page.route('**/actions/states*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_known: false, states: {}, unknown: ['prop_again'] }) }));
  await page.evaluate(() => reconcileActions('test'));
  await sleep(200);
  const unknownButUnheld = await page.evaluate(() => document.querySelector('[data-proposal="prop_again"] .action-surface').dataset.state);
  check('a Mac that has lost the conversation does not settle the cards on screen', unknownButUnheld === 'armed', unknownButUnheld);
  await page.route('**/actions/states*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_known: true, states: {}, unknown: ['prop_again'] }) }));
  await page.evaluate(() => reconcileActions('test'));
  await sleep(200);
  const settled = await page.evaluate(() => document.querySelector('[data-proposal="prop_again"] .action-surface').dataset.state);
  check('a card the Mac is not holding stops claiming it can be applied', settled === 'settled', settled);
  await page.unroute('**/actions/states*');

  // 9. The Mac away, then refused, then back — in the page's own words. The health poll is
  // routed the same way as the ping, as a real absent or refusing Mac would answer both.
  const settleReconnect = async () => { await page.evaluate(() => { clearTimeout(reconnectTimer); }); await sleep(250); };
  await page.route('**/ping', (r) => r.abort());
  await page.route('**/health**', (r) => r.abort());
  await settleReconnect();
  await page.evaluate(() => { reconnectDelay = 300; checkReachable(); });
  let offline = false;
  try { await page.waitForFunction(() => document.getElementById('system').dataset.phase === 'offline', null, { timeout: 8000 }); offline = true; } catch { /* below */ }
  const offlineWords = await page.evaluate(() => document.getElementById('system-title').textContent);
  check('an absent Mac is SYSTEM OFFLINE', offline && /offline/i.test(offlineWords), offlineWords);
  await shot('07-offline');
  await page.unroute('**/ping'); await page.unroute('**/health**');
  await settleReconnect();
  await page.route('**/ping', (r) => r.fulfill({ status: 403, contentType: 'application/json', body: '{"error":"not allowed"}' }));
  await page.route('**/health**', (r) => r.fulfill({ status: 403, contentType: 'application/json', body: '{"error":"not allowed"}' }));
  await page.evaluate(() => { reconnectDelay = 300; checkReachable(); });
  let refused = false;
  try { await page.waitForFunction(() => document.getElementById('system').dataset.phase === 'refused', null, { timeout: 8000 }); refused = true; } catch { /* below */ }
  check('a refused login is NOT ALLOWED, not offline', refused, await page.evaluate(() => document.getElementById('system-title').textContent));
  await shot('08-refused');
  await page.unroute('**/ping'); await page.unroute('**/health**');
  await settleReconnect();
  await page.evaluate(() => { reconnectDelay = 300; checkReachable(); });
  let back = false;
  try { await page.waitForFunction(() => document.getElementById('system').dataset.phase === 'online', null, { timeout: 8000 }); back = true; } catch { /* below */ }
  check('the page comes back when the Mac does', back);

  // 9b. A test session is on (accept.py started one): the page reported what it rendered, as
  // structure — card types, chips, sizes — and never the words on the cards.
  await page.evaluate(() => { if (window.CrooksTelemetry) window.CrooksTelemetry.flush(false); });
  await sleep(400);
  const kinds = [];
  for (const body of telemetry) { try { for (const e of JSON.parse(body).events || []) kinds.push(e.kind); } catch { /* not ours */ } }
  const joined = telemetry.join('\n');
  check('the page reports what it rendered while a test session is on', kinds.includes('render') && kinds.includes('turn_response') && kinds.includes('navigate'), `${telemetry.length} batch(es): ${[...new Set(kinds)].join(', ')}`);
  check('the report is structure, never the cards\' words', telemetry.length > 0 && !/Sam Fixture|sam@example\.com|Somewhere Street/.test(joined), joined.length ? `${joined.length} bytes without a customer detail` : 'nothing posted');

  // 10. Nothing the page did raised a script error, and no secret-looking string is in the DOM.
  const dom = await page.content();
  check('no script errors through the whole run', errors.length === 0, errors.join(' | '));
  check('no key-shaped string in the page', !/(shpat_|sk_[a-z0-9]{20,}|xi-api-key)/i.test(dom));

  await browser.close();
  return { ok: checks.every((c) => c.ok), checks, timing };
}

main().then((result) => { console.log(JSON.stringify(result)); process.exit(result.ok ? 0 : 1); },
  (error) => { console.log(JSON.stringify({ ok: false, checks: checks.concat([{ name: 'browser run', ok: false, detail: String(error && error.stack || error).slice(0, 400) }]) })); process.exit(1); });

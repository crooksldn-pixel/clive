/* What the FIRST VIEWPORT says, measured on the tablet's own screen (§8, D-12).
 *
 *   node scripts/browser/density.js http://127.0.0.1:8765 /path/to/screenshots
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...] }.
 *
 * The live session recorded 38 long-scroll surfaces, the tallest 1,999 px against a 680 px
 * viewport, and a deepest scroll of 2,014 px. Those are measurements, so this is a
 * measurement: a real Chromium at 601 × 889 CSS px at DPR 1.33 — the Galaxy Tab A 8.0 in the
 * owner's hand — driving the real backend over HTTP, and reading getBoundingClientRect.
 *
 * For each of the three surfaces the brief names (an order, an email thread, an order list)
 * it asks the three questions of the pixels above the fold and no others:
 *
 *   what am I looking at   an identity — the number, the subject, the window — is visible
 *   what matters           the state, the money, or who is waiting, is visible
 *   what can I do          a control that starts the next thing is visible AND big enough
 *
 * "Visible" is `rect.top < fold && rect.bottom > 0` against the deck's own visible box, not
 * against the document: the dock and the nav rail are chrome and take their own room.
 *
 * It also holds the ceiling that §8 is really about — that the whole surface is within a
 * couple of screens rather than ten — because a first viewport that answers everything on top
 * of 2,000 px of tail is still a card nobody can hold in one hand.
 */
'use strict';

const { chromium } = require('playwright-core');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
const VIEWPORT = { width: 601, height: 889 };
const DPR = 1.33;
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
// A screen and a quarter is the ceiling: past that the tail is a journey rather than a
// glance. The live session's worst surface was 1,999 px against 680 px of screen — 2.9
// screens — and the deepest scroll it recorded was 2,014 px. Measured on this build before
// the density work: the worst email thread was 1,488 px (2.2 screens) and the worst order
// list 933 px (1.4); after it, 640 px and 665 px against 671 px of visible deck.
const MAX_SURFACE_RATIO = 1.25;

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 300) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: DPR, isMobile: true, hasTouch: true, extraHTTPHeaders: HEADERS });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key","reason":"no voice under test"}' }));

  const shot = async (name) => {
    if (!OUT) return;
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(OUT, `density-${name}.png`), fullPage: false, animations: 'disabled' });
    shots.push(`density-${name}.png`);
  };

  // The typed way in, which is the same turn the microphone takes.
  const say = async (text) => {
    await page.evaluate(() => {
      const sheet = document.querySelector('#settings');
      const dev = document.querySelector('#dev');
      if (dev) dev.hidden = false;
      if (sheet && !sheet.open && sheet.showModal) sheet.showModal();
    });
    await page.fill('#dev-text', text);
    await page.press('#dev-text', 'Enter');
    await sleep(1400);
    await page.evaluate(() => { const sheet = document.querySelector('#settings'); if (sheet && sheet.open) sheet.close(); });
    await sleep(400);
  };

  /* What is above the fold, and what it says.
   *
   * Returns the measurements and three booleans, each answered from ELEMENTS rather than from
   * a screenshot: a title in the first viewport, a state/money/waiting mark in it, and a
   * control in it that is at least 44 px tall.
   */
  const firstViewport = () => page.evaluate(() => {
    const deck = document.querySelector('#cards');
    const card = document.querySelector('#cards .card');
    if (!deck || !card) return null;
    const box = deck.getBoundingClientRect();
    const fold = Math.min(box.bottom, window.innerHeight);
    const above = (el) => {
      if (!el) return false;
      const r = el.getBoundingClientRect();
      return r.height > 0 && r.top < fold && r.bottom > box.top;
    };
    const anyAbove = (sel) => Array.prototype.some.call(card.querySelectorAll(sel), above);
    const tallEnough = (sel) => Array.prototype.some.call(card.querySelectorAll(sel), (el) => above(el) && el.getBoundingClientRect().height >= 44);
    const identity = ['.card-title', '.head-total', '.list-pos'];
    const matters = ['.badge', '.head-total', '.tl', '.attn-line', '.stats', '.link-strip', '.link-block', '.reply-line', '.empty-line', '.list-pos'];
    const actions = ['.rail-chip', '.row-btn', '.tab', '.chip', '.link-btn', '.row.tappable', '.disc-head'];
    return {
      type: card.dataset.type || '',
      viewport: window.innerHeight,
      deckVisible: Math.round(box.height),
      cardHeight: Math.round(card.getBoundingClientRect().height),
      deckHeight: Math.round(deck.scrollHeight),
      scrollTop: Math.round(deck.scrollTop),
      identity: identity.some(anyAbove),
      matters: matters.some(anyAbove),
      doable: actions.some(tallEnough),
      titles: Array.prototype.map.call(card.querySelectorAll('.card-title'), (t) => (t.textContent || '').trim().slice(0, 40)),
    };
  });

  const measure = async (label, expectType) => {
    const seen = await firstViewport();
    if (!seen) { check(`${label}: a card is on the screen`, false, 'no card'); return null; }
    check(`${label}: the surface is the one being measured`, !expectType || seen.type === expectType, `type=${seen.type}`);
    check(`${label}: the first viewport says what this is`, seen.identity, JSON.stringify(seen.titles));
    check(`${label}: the first viewport says what matters`, seen.matters, `type=${seen.type}`);
    check(`${label}: the first viewport offers something to do, 44 px or more`, seen.doable, `type=${seen.type}`);
    check(
      `${label}: the surface is within a screen and a quarter (${seen.cardHeight} px of ${seen.deckVisible} px)`,
      seen.cardHeight <= seen.deckVisible * MAX_SURFACE_RATIO,
      `card=${seen.cardHeight}px deck=${seen.deckHeight}px visible=${seen.deckVisible}px`,
    );
    return seen;
  };

  // A list that is longer than the fold shows a handful and says how many there are, with one
  // control for the rest. Ten full rows is how an order list reached 933 px.
  const foldCheck = async (label) => {
    const folded = await page.evaluate(() => {
      const card = document.querySelector('#cards .card');
      const rows = Array.prototype.slice.call(card.querySelectorAll('.row'));
      const pos = card.querySelector('.list-pos');
      return {
        total: rows.length, shown: rows.filter((r) => !r.hidden).length,
        more: Boolean(card.querySelector('.link-btn')), position: pos ? (pos.textContent || '').trim() : '',
      };
    });
    check(`${label}: a long list shows a handful, says where it is, and keeps one control for the rest`,
      folded.total <= 5 || (folded.shown <= 5 && folded.more && Boolean(folded.position)), JSON.stringify(folded));
  };

  // A thread's history is behind one control and the newest message is the one that is open.
  const threadCheck = async (label) => {
    const shape = await page.evaluate(() => {
      const card = document.querySelector('#cards .card');
      const msgs = Array.prototype.slice.call(card.querySelectorAll('.msg'));
      const body = card.querySelector('.disc-body');
      const rail = card.querySelector('.rail');
      const latest = card.querySelector('.msg.is-latest');
      const deck = document.querySelector('#cards').getBoundingClientRect();
      const fold = Math.min(deck.bottom, window.innerHeight);
      return {
        messages: msgs.length,
        latestFirst: Boolean(msgs.length && msgs[0].classList.contains('is-latest')),
        historyHidden: msgs.length <= 1 ? true : Boolean(body && body.hidden),
        railAboveTheFold: Boolean(rail && rail.getBoundingClientRect().top < fold),
        latestAboveTheFold: Boolean(latest && latest.getBoundingClientRect().top < fold),
      };
    });
    check(`${label}: the newest message is the one on the screen, and the history is behind one control`,
      shape.latestFirst && shape.historyHidden, JSON.stringify(shape));
    check(`${label}: Reply and Archive are above the fold, not below the quoted text`,
      shape.railAboveTheFold && shape.latestAboveTheFold, JSON.stringify(shape));
  };

  // [checker, 8 Oct 2026] Without the start-up, as collision.js: what is measured is the app.
  await page.goto(`${BASE}?dev=1&startup=off`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(900);
  await page.evaluate(() => { for (const b of document.querySelectorAll('.dev-banner')) b.remove(); });
  const vp = await page.evaluate(() => [innerWidth, innerHeight, +devicePixelRatio.toFixed(2)]);
  check('the page is at the tablet\'s real size', vp[0] === 601 && vp[1] === 889, JSON.stringify(vp));

  // ---- 1. an order list
  await say("show me today's orders");
  const list = await measure('order list', 'order_list');
  if (list) await foldCheck('order list');
  await shot('01-order-list');

  // ---- 2. an order
  await page.evaluate(() => { const row = document.querySelector('#cards .row.tappable[data-kind="order"]'); if (row) row.click(); });
  await sleep(1600);
  await measure('order', 'order');
  await shot('02-order');

  // ---- 3. an email thread
  await say('which customers need replying to?');
  await page.evaluate(() => { const row = document.querySelector('#cards .row.tappable[data-kind="email_thread"]'); if (row) row.click(); });
  await sleep(1600);
  const thread = await measure('email thread', 'email_thread');
  if (thread) await threadCheck('email thread');
  await shot('03-email-thread');

  // ---- 4. the worst case, stubbed
  //
  // The fixture shop is small and polite: three orders, a thread with one message. The live
  // session's 1,999 px surface was none of those things — it was a long thread, a full order
  // and a list of ten — so those are stubbed here, at the same viewport, and measured. The
  // payloads are the presentation layer's own bounds at their MAXIMUM: 6 messages of 1,800
  // characters, 12 line items, 10 orders. Nothing in them is invented: every field is one
  // app/presentation.py fills in, at the cap it enforces.
  const long = (n) => 'This is the part of the message that is quoted back every time somebody replies to it, which is why a thread reads as a wall rather than as a conversation. '.repeat(n);
  const payload = (ui) => ({
    session_id: 'density', turn_id: `turn_density${ui[0].type}`, turns: 1, answer: 'Measured.',
    question: 'measure', error_kind: null, lost_thread: false, state: 'READY', revoked: [],
    tool_calls: [], transcript: null, timings_ms: { total: 10 }, workspace: null, ui,
  });
  const worst = {
    email_thread: payload([{ type: 'email_thread', data: {
      thread_id: 't-worst', subject: 'Re: Re: Fwd: my order has not arrived and I would like to know what is happening with it',
      message_count: 9, truncated: true, awaiting_reply: true, latest_direction: 'inbound',
      link_confidence: 'confident', link_provenance: ['sender matches the order', 'placed 2 days before the first message'],
      linked_order: { order_id: 'o-worst', order_number: '#1938', total: '£84.00', fulfillment: 'unfulfilled' },
      linked_customer: { customer_id: 'c-worst', name: 'A Customer' },
      actions: [
        { id: 'reply', label: 'Reply', operation: 'gmail_draft_reply', risk: 'amber', enabled: true, mode: 'ask', instruction: 'reply to this', family: 'email.reply' },
        { id: 'email_archive', label: 'Archive', operation: 'gmail_thread_archive', risk: 'amber', enabled: true, mode: 'stage', detail: 'out of the inbox' },
      ],
      messages: [0, 1, 2, 3, 4, 5].map((i) => ({
        from: i % 2 ? 'CROOKS LDN' : 'A Customer', from_email: i % 2 ? 'shop@example.com' : 'someone@example.com',
        date: '2026-09-10T09:0' + i + ':00Z', subject: 'Re: my order', body: long(9), outbound: Boolean(i % 2),
      })),
    } }]),
    order_list: payload([{ type: 'order_list', data: {
      title: 'Today', count: 10, truncated: false, value: '£1,284.00',
      orders: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((i) => ({
        order_id: `o${i}`, order_number: `#19${40 + i}`, placed_at: '2026-09-11T1' + (i % 10) + ':00:00Z',
        fulfillment: i % 3 ? 'unfulfilled' : 'fulfilled', payment: 'paid', total: '£' + (60 + i) + '.00',
        customer_name: 'A Customer With A Fairly Long Name ' + i, customer_id: `c${i}`, detail: false,
      })),
    } }]),
    order: payload([{ type: 'order', data: {
      order_id: 'o-worst', order_number: '#1938', placed_at: '2026-09-09T09:42:00Z', fulfillment: 'unfulfilled',
      payment: 'paid', total: '£84.00', customer_name: 'A Customer', customer_id: 'c-worst', customer_email: 'someone@example.com',
      detail: true, items_truncated: true, tags: ['vip', 'repeat', 'fragile'],
      attention_top: [{ title: 'Paid 2 days ago and not shipped', level: 'red', kind: 'unfulfilled' }, { title: 'They wrote in and we have not replied', level: 'amber', kind: 'email' }],
      items: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map((i) => ({
        title: 'A Product With A Long Catalogue Name ' + i, variant: 'Medium', sku: 'SKU-' + i, quantity: 1 + (i % 3),
        total: '£' + (20 + i) + '.00', image: '', variant_id: `v${i}`, product_id: `p${i}`, stock: { tracked: true, available: i },
      })),
      fulfillments: [], cancelled_at: '', note: long(2), ships_to: 'London, United Kingdom',
      shipping_method: 'Royal Mail Tracked 24',
      shipping_address: { name: 'A Customer', lines: ['12 Somewhere Street', 'Flat 3'], city: 'London', zip: 'E1 6AN', country: 'United Kingdom' },
      money: { subtotal: '£79.00', shipping: '£5.00', tax: '£13.17' },
      history: { customer_id: 'c-worst', name: 'A Customer', orders: 7, spent: '£640.00', standing: 'regular', recent: [0, 1, 2, 3, 4].map((i) => ({ order_id: `h${i}`, order_number: `#18${10 + i}`, placed_at: '2026-08-0' + (i + 1) + 'T09:00:00Z', fulfillment: 'fulfilled', total: '£60.00', items_brief: 'One pair of jeans' })) },
      email: { available: true, threads: [{ thread_id: 't1', from: 'A Customer', subject: 'my order', snippet: long(1), date: '2026-09-10T09:00:00Z', verified_sender: true }] },
      pending: [],
      actions: [
        { id: 'note', label: 'Add a note', operation: 'order_note_append', risk: 'amber', enabled: true, mode: 'ask', instruction: 'add a note', family: 'order.note' },
        { id: 'fulfil', label: 'Fulfil', operation: 'fulfillment_create', risk: 'amber', enabled: true, mode: 'ask', instruction: 'fulfil it', family: 'order.fulfil' },
      ],
    } }]),
  };
  for (const kind of ['order_list', 'order', 'email_thread']) {
    await page.unroute('**/turn').catch(() => {});
    await page.route('**/turn', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(worst[kind]) }));
    await say(`the worst ${kind} this build can draw`);
    const seen = await measure(`worst ${kind}`, kind);
    if (seen && kind === 'order') {
      // What the order NEEDS, in the first viewport rather than on the card below it.
      const attn = await page.evaluate(() => {
        const deck = document.querySelector('#cards').getBoundingClientRect();
        const lines = Array.prototype.slice.call(document.querySelectorAll('#cards .card .attn-line'));
        return { n: lines.length, above: lines.filter((l) => l.getBoundingClientRect().top < Math.min(deck.bottom, window.innerHeight)).length };
      });
      check('worst order: what the order needs is in the first viewport, not on a card below it',
        attn.n > 0 && attn.above === attn.n, JSON.stringify(attn));
    }
    if (seen && kind === 'order_list') await foldCheck('worst order list');
    if (seen && kind === 'email_thread') await threadCheck('worst email thread');
    await shot(`04-worst-${kind}`);
  }
  await page.unroute('**/turn').catch(() => {});

  check('no script error during the whole run', errors.length === 0, errors.slice(0, 3).join(' | '));

  await browser.close();
  const ok = checks.every((c) => c.ok);
  process.stdout.write(`${JSON.stringify({ ok, checks, shots })}\n`);
  return ok ? 0 : 1;
}

main().then((code) => process.exit(code)).catch((error) => {
  process.stdout.write(`${JSON.stringify({ ok: false, checks: [{ name: 'density run', ok: false, detail: String(error && error.message || error).slice(0, 300) }], shots })}\n`);
  process.exit(1);
});

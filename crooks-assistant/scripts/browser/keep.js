/* What stays on the glass, in a real browser at the owner's sizes (round 12).
 *
 * George, 29 September: "a task is asked, a screen is shown, an edit is asked, the edit
 * succeeds, however the screen disappears. This is a persistent issue." And: "pulling up the
 * screen again is not something you can say to clive."
 *
 * Driven against the real backend on the golden world, with the model scripted by the runner
 * (tests/test_r12_browser.py) so each sentence makes the tool calls Claude makes for it through
 * the real gate. Every question goes through the page's own `submit()` — the path the
 * microphone takes — and the one gesture is a real pointer on the card's own surface. What is
 * checked is what the owner would see: whether the order he was working on is on the glass at
 * every moment of the edit, whether it is the same card (not redrawn from the top), where the
 * card to tap is, and whether a screen he moved away from comes back when he asks for it.
 *
 *   node scripts/browser/keep.js http://127.0.0.1:8822 /path/to/screenshots
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...] }.
 */
'use strict';

const { chromium } = require('playwright-core');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8822';
const OUT = process.argv[3] || '';
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
// The owner's tablet (scripts/browser/tablet.js) and a phone.
const SIZES = [
  { name: '601', viewport: { width: 601, height: 889 }, dpr: 1.33 },
  { name: '390', viewport: { width: 390, height: 844 }, dpr: 3 },
];

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function walk(browser, size, full) {
  const context = await browser.newContext({ viewport: size.viewport, deviceScaleFactor: size.dpr, isMobile: true, hasTouch: true, extraHTTPHeaders: HEADERS });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key","reason":"no voice under test"}' }));
  const shot = async (name) => {
    if (!OUT) return;
    const file = path.join(OUT, `keep-${size.name}-${name}.png`);
    await page.waitForTimeout(500);
    await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
    shots.push(path.basename(file));
  };
  const at = (label) => `${label} (${size.name})`;

  // The start-up is the visuals' own business and is walked in its own script; here it would
  // cover every picture of the deck.
  await page.goto(`${BASE}/?startup=off`, { waitUntil: 'load' });
  try { await page.waitForFunction(() => document.getElementById('system').dataset.phase === 'online', null, { timeout: 30000 }); } catch { /* checked below */ }
  await sleep(1200);

  // What is on the glass, and which DOM node the order is. A node is marked once and asked
  // after: a card redrawn from the top is a new node however alike it looks.
  const glass = () => page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll('#cards > *'));
    const orders = cards.filter((n) => n.dataset.type === 'order');
    const box = (n) => { const r = n.getBoundingClientRect(); return { top: Math.round(r.top), bottom: Math.round(r.bottom) }; };
    const deck = document.getElementById('cards').getBoundingClientRect();
    return {
      mode: document.body.dataset.mode,
      types: cards.map((n) => n.dataset.type),
      orders: orders.map((n) => n.dataset.ref || ''),
      marked: orders.map((n) => n.__keep === true),
      text: orders.map((n) => n.textContent.replace(/\s+/g, ' ').trim()).join(' | ').slice(0, 600),
      first: cards[0] ? Object.assign({ type: cards[0].dataset.type }, box(cards[0])) : null,
      deck: { top: Math.round(deck.top), bottom: Math.round(deck.bottom) },
      scroll: Math.round(document.getElementById('cards').scrollTop),
      answer: (document.getElementById('answer').textContent || '').trim(),
    };
  });
  // Until the deck has stopped moving: a card brought into view is scrolled to smoothly, and a
  // measurement taken mid-scroll says where it was going, not where it is.
  const settled = () => page.evaluate(async () => {
    const deck = document.getElementById('cards');
    let last = -1;
    let still = 0;
    for (let i = 0; i < 60 && still < 4; i += 1) {
      await new Promise((r) => requestAnimationFrame(r));
      still = deck.scrollTop === last ? still + 1 : 0;
      last = deck.scrollTop;
    }
  });
  const mark = () => page.evaluate(() => { for (const n of document.querySelectorAll('#cards > [data-type="order"]')) n.__keep = true; });
  const ask = (text) => page.evaluate((t) => window.CliveAlpha.ask(t), text);
  // Asked while sampling the glass every frame, so a screen that went away for a moment and
  // came back is caught, not only one that stayed away.
  const askWatching = (text) => page.evaluate(async (t) => {
    const samples = [];
    let running = true;
    const tick = () => {
      if (!running) return;
      samples.push({
        mode: document.body.dataset.mode,
        order: Boolean(document.querySelector('#cards > [data-type="order"]')),
      });
      requestAnimationFrame(tick);
    };
    tick();
    await window.CliveAlpha.ask(t);
    await new Promise((r) => setTimeout(r, 400));
    running = false;
    return samples;
  }, text);

  // An answer held back two seconds on the wire, as a slow network does. The turn's workspace
  // (the /state poll, every 400 ms) then reaches the page BEFORE the answer that says what the
  // screen keeps: the note's card and the context stack arrive first, and the order under them
  // must not go for those frames. Under load this happened on its own and took the order away
  // for five frames; held back, it happens every time.
  const slowly = async (fn) => {
    await page.route('**/turn', async (route) => {
      const response = await route.fetch();
      await sleep(2000);
      await route.fulfill({ response });
    });
    try { return await fn(); } finally { await page.unroute('**/turn'); }
  };

  // ---- 1. the order he is working on
  await ask('show me order 1938');
  let seen = await glass();
  check(at('the order is on the glass'), seen.mode === 'context' && seen.orders.length === 1, JSON.stringify(seen.types));
  await shot('01-order');
  await mark();

  // ---- 2. a question answered in words keeps it, where he was reading
  await page.evaluate(() => { document.getElementById('cards').scrollTop = 120; });
  await sleep(200);
  const scrolled = (await glass()).scroll;
  const inWords = await slowly(() => askWatching("what's the note on it?"));
  seen = await glass();
  check(at('an answer in words, slow to arrive, never takes the order away'), inWords.every((f) => f.order && f.mode === 'context'),
    `${inWords.filter((f) => !f.order || f.mode !== 'context').length} of ${inWords.length} frames without it`);
  check(at('an answer in words keeps the order up, the same card'), seen.mode === 'context' && seen.orders.length === 1 && seen.marked[0] === true, JSON.stringify(seen));
  check(at('and leaves him where he was reading'), Math.abs(seen.scroll - scrolled) <= 2, `${scrolled} -> ${seen.scroll}`);
  await shot('02-words');

  // ---- 3. the edit: the order never leaves the glass while the note is prepared
  const during = await slowly(() => askWatching('add a note saying gift wrap it'));
  await settled();
  const gone = during.filter((s) => !s.order || s.mode !== 'context').length;
  check(at('the order stays on the glass for every frame of the edit'), during.length > 3 && gone === 0, `${gone} of ${during.length} frames without it`);
  seen = await glass();
  check(at('the card to tap is on top and the order, the same card, is under it'),
    seen.types[0] === 'confirmation' && seen.orders.length === 1 && seen.marked[0] === true, JSON.stringify(seen.types));
  check(at('the card to tap is in view'), seen.first && seen.first.top >= seen.deck.top - 1 && seen.first.top < seen.deck.bottom, JSON.stringify({ first: seen.first, deck: seen.deck }));
  await shot('03-note-waiting');

  // ---- 4. the gesture: the change is applied and the order is redrawn with it, once
  await sleep(900);   // the card's dead time
  const tapped = await page.evaluate(() => {
    const surface = document.querySelector('#cards [data-type="confirmation"] .action-surface');
    if (!surface) return 'no surface';
    surface.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerId: 7 }));
    surface.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 7 }));
    return surface.dataset.state;
  });
  try {
    await page.waitForFunction(() => Boolean(document.querySelector('#cards [data-type="success"]')), null, { timeout: 10000 });
  } catch { /* checked below */ }
  await sleep(500);
  seen = await glass();
  check(at('after the gesture the proof is up and the order is still there, once, with the note on it'),
    seen.types.includes('success') && seen.orders.length === 1 && /Gift wrap it/.test(seen.text), `${tapped} ${JSON.stringify(seen.types)} ${seen.text.slice(0, 160)}`);
  check(at('and nothing else asks for a tap'), !seen.types.includes('confirmation'), JSON.stringify(seen.types));
  await shot('04-note-applied');

  if (full) {
    // ---- 5. a new subject replaces the screen
    await ask('show me order 1940');
    seen = await glass();
    check(at('a new order replaces the screen'), seen.orders.length === 1 && /1940/.test(seen.orders[0]) && !seen.types.includes('success'), JSON.stringify(seen));
    await shot('05-new-subject');

    // ---- 6. "pull that up again"
    await ask('pull that up again');
    seen = await glass();
    check(at('"pull that up again" brings the order he moved away from back, read again'),
      seen.orders.length === 1 && /1938/.test(seen.orders[0]) && /Gift wrap it/.test(seen.text), JSON.stringify(seen).slice(0, 300));
    await shot('06-back-again');
  }

  check(at('no page errors'), errors.length === 0, errors.join(' | '));
  await context.close();
}

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  try {
    await walk(browser, SIZES[0], true);
    await walk(browser, SIZES[1], false);
  } finally {
    await browser.close();
  }
  process.stdout.write(`${JSON.stringify({ ok: checks.every((c) => c.ok), checks, shots })}\n`);
}

main().catch((error) => {
  process.stdout.write(`${JSON.stringify({ ok: false, checks: [...checks, { name: 'the run', ok: false, detail: String(error && error.stack || error).slice(0, 400) }], shots })}\n`);
});

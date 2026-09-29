/* An order built by voice, in a real browser, at the three sizes the owner uses (round 12).
 *
 *   node scripts/browser/orders.js http://127.0.0.1:PORT [/path/to/screenshots]
 *
 * The backend is the real one on the golden world, with Claude scripted for four sentences
 * (tests/test_r12_orders_browser.py). Each is typed into the page's own diagnostics field,
 * which posts exactly what the microphone posts. What is checked is what the owner sees:
 *
 *   - "find the customer who ordered … and make a new order … in the next size up" lands on
 *     the new order, first on the screen, with the L on it;
 *   - a custom item and a line discount said next arrive on the SAME card — and the card is
 *     on the screen, not the orb (the page used to go back to the orb when a turn's only card
 *     was the one being built: "the edit succeeds however the screen disappears");
 *   - several matches are a choice on the card, and a tap on Add, then on Remove, changes
 *     that same card;
 *   - Prepare puts the hold card up and the order being built stays on the glass with it; the
 *     hold and the drag, made with the pointer, then turn that same card into the order it
 *     made — its number, nothing to type, nothing to prepare again;
 *   - every control on a line is at least 44 px, nothing leaves the card's edge, the page does
 *     not scroll sideways, and nothing throws — on the tablet (601 x 889 at DPR 1.33), a phone
 *     (390 x 844), a TV (1920 x 1080), and the tablet again as the weak device with reduced
 *     motion.
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...] }.
 */
'use strict';

const { chromium } = require('playwright-core');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const SIZES = [
  { name: 'tablet', viewport: { width: 601, height: 889 }, dpr: 1.33, mobile: true },
  { name: 'phone', viewport: { width: 390, height: 844 }, dpr: 3, mobile: true },
  { name: 'tv', viewport: { width: 1920, height: 1080 }, dpr: 1, mobile: false },
];
// Said in this order; tests/test_r12_orders_browser.py scripts what Claude calls for each.
const SAID = [
  'find the customer who ordered the black medium hoodie to SL4 1QN and make a new order for them in the next size up',
  'add a custom back print at twelve pounds, two of them, and take ten percent off the hoodie',
  'five pounds off the order and four pounds postage',
  'and add a black hoodie',
];

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function run(browser, size, weak) {
  const tag = `${size.name}${weak ? '-weak' : ''}`;
  const context = await browser.newContext({
    viewport: size.viewport, deviceScaleFactor: size.dpr, isMobile: size.mobile, hasTouch: size.mobile,
    extraHTTPHeaders: HEADERS, reducedMotion: weak ? 'reduce' : 'no-preference',
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key"}' }));
  // The SM-T290's own answer to the page's weak-device question (web/display.js `weak`).
  if (weak) await page.addInitScript(() => { Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 4 }); });
  // A conversation of its own: the page restores a session's screen on load.
  await page.goto(`${BASE}?dev=1&startup=off`, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => { try { localStorage.removeItem('crooks.session'); localStorage.removeItem('crooks.turns'); } catch { /* private mode */ } });
  await page.goto(`${BASE}?dev=1&startup=off`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(700);
  await page.evaluate(() => { for (const b of document.querySelectorAll('.dev-banner')) b.remove(); });

  const say = async (text) => {
    await page.evaluate(() => {
      const sheet = document.querySelector('#settings');
      const dev = document.querySelector('#dev');
      if (dev) dev.hidden = false;
      if (sheet && !sheet.open && sheet.showModal) sheet.showModal();
    });
    await page.fill('#dev-text', text);
    await page.press('#dev-text', 'Enter');
    await sleep(1300);
    await page.evaluate(() => { const sheet = document.querySelector('#settings'); if (sheet && sheet.open) sheet.close(); });
    await sleep(400);
  };
  const shot = async (name, at) => {
    if (!OUT) return;
    await page.evaluate((sel) => { const c = document.querySelector(sel); if (c) c.scrollIntoView({ block: 'start' }); }, at || '#cards .card-workspace');
    await page.waitForTimeout(350);
    const file = path.join(OUT, `orders-${tag}-${name}.png`);
    await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
    shots.push(path.basename(file));
  };
  const screen = () => page.evaluate(() => {
    const ws = document.querySelector('#cards .card-workspace');
    const lines = ws ? Array.from(ws.querySelectorAll('ol.ws-rows > .ws-row')) : [];
    const card = ws ? ws.getBoundingClientRect() : null;
    const past = ws ? Array.from(ws.querySelectorAll('.ws-row *')).filter((e) => {
      const r = e.getBoundingClientRect();
      return r.width > 0 && (r.right > card.right + 1 || r.left < card.left - 1);
    }).map((e) => e.className) : [];
    const doc = document.documentElement;
    return {
      mode: document.body.dataset.mode || '',
      cards: Array.from(document.querySelectorAll('#cards .card')).map((c) => c.dataset.type || ''),
      workspace: ws ? ws.dataset.workspace : '',
      lines: lines.map((r) => r.innerText.replace(/\s+/g, ' ').trim()),
      picks: ws ? ws.querySelectorAll('.ws-picks .ws-row').length : 0,
      controls: ws ? Array.from(ws.querySelectorAll('.ws-row-btn')).map((b) => { const r = b.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; }) : [],
      sideways: doc.scrollWidth > doc.clientWidth + 1,
      past,
    };
  });

  await say(SAID[0]);
  let s = await screen();
  const first = s.workspace;
  check(`${tag}: the sentence lands on the new order, first on the screen, with the next size on it`,
    s.mode === 'context' && s.cards[0] === 'workspace' && s.lines.length === 1 && /Black \/ L/.test(s.lines[0]), JSON.stringify(s));
  await shot('1-next-size-up');

  await say(SAID[1]);
  s = await screen();
  check(`${tag}: a custom item and a line discount, said, are on the same card and the card is on the screen`,
    s.mode === 'context' && s.cards[0] === 'workspace' && s.workspace === first && s.lines.length === 2
      && /10% off/.test(s.lines[0]) && /Custom back print/.test(s.lines[1]), JSON.stringify(s));
  await shot('2-custom-and-line-discount');

  await say(SAID[2]);
  await say(SAID[3]);
  s = await screen();
  check(`${tag}: several matches are a choice on the card`, s.workspace === first && s.picks === 3, JSON.stringify(s));
  check(`${tag}: every control on a line is at least 44px`, s.controls.length && s.controls.every(([w, h]) => w >= 44 && h >= 44), JSON.stringify(s.controls));
  check(`${tag}: nothing leaves the card's edge and the page does not scroll sideways`, !s.sideways && !s.past.length, JSON.stringify(s));
  await shot('3-a-choice');

  const adds = await page.$$('#cards .card-workspace .ws-picks .ws-row-btn');
  if (adds[1]) { await adds[1].click(); await sleep(1100); }
  s = await screen();
  check(`${tag}: a tap on Add puts that one on the same card`, s.workspace === first && s.lines.length === 3 && s.picks === 0, JSON.stringify(s));
  await shot('4-picked');

  const removes = await page.$$('#cards .card-workspace ol.ws-rows .ws-row-btn');
  if (removes[2]) { await removes[2].click(); await sleep(1100); }
  s = await screen();
  check(`${tag}: a tap on Remove takes that line off and the card stays`, s.mode === 'context' && s.workspace === first && s.lines.length === 2, JSON.stringify(s));

  // Prepare: the hold card comes up, and the order being built stays on the glass with it. It
  // used to go — the hold card is about the draft, which no card showed (round 12, H).
  await page.evaluate(() => {
    const b = document.querySelector('#cards .card-workspace button[data-action="prepare"]');
    if (b) { b.scrollIntoView({ block: 'center' }); b.click(); }
  });
  await sleep(1800);
  s = await screen();
  check(`${tag}: Prepare puts the hold card up and the order being built stays on the glass with it`,
    s.mode === 'context' && s.cards.includes('confirmation') && s.workspace === first && s.lines.length === 2, JSON.stringify(s));
  await shot('5-prepared', '#cards [data-type="confirmation"]');

  // The hold and the drag, as a finger makes them, and then the same card is the order it made:
  // its number, nothing to type and nothing to prepare (round 12, A1).
  const surface = () => page.evaluate(() => {
    const el = document.querySelector('#cards [data-type="confirmation"] .action-surface');
    if (!el) return null;
    el.scrollIntoView({ block: 'center' });
    const r = el.getBoundingClientRect();
    return { x: r.left, y: r.top, w: r.width, h: r.height };
  });
  await surface();
  await sleep(900);
  const box = await surface();
  if (box) {
    const y = box.y + box.h / 2;
    const x0 = box.x + 24;
    await page.mouse.move(x0, y);
    await page.mouse.down();
    await sleep(1800);
    for (let i = 1; i <= 12; i += 1) { await page.mouse.move(x0 + ((box.w - 36) * i) / 12, y); await sleep(25); }
    await page.mouse.up();
    await sleep(2400);
  }
  const made = await page.evaluate(() => {
    const ws = document.querySelector('#cards .card-workspace');
    const pick = (sel) => (ws && ws.querySelector(sel) ? ws.querySelector(sel).textContent.trim() : '');
    return {
      cards: Array.from(document.querySelectorAll('#cards .card')).map((c) => c.dataset.type || ''),
      workspace: ws ? ws.dataset.workspace : '',
      kicker: pick('.card-kicker'), title: pick('.card-title'), badge: pick('.badge'),
      prepare: Boolean(ws && ws.querySelector('button[data-action="prepare"]')),
      buttons: ws ? ws.querySelectorAll('.ws-row-btn').length : -1,
      inputs: ws ? ws.querySelectorAll('input, textarea').length : -1,
      lines: ws ? ws.querySelectorAll('ol.ws-rows > .ws-row').length : 0,
    };
  });
  check(`${tag}: after the hold the same card is the order it made, by its number, with nothing left to build`,
    made.workspace === first && /created/i.test(made.kicker) && /#1999/.test(made.title)
      && made.badge === 'Created' && !made.prepare && made.buttons === 0 && made.inputs === 0 && made.lines === 2
      && made.cards.includes('success'), JSON.stringify(made));
  await shot('6-created');
  check(`${tag}: nothing on the page threw`, errors.length === 0, errors.join(' | '));
  await context.close();
}

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  try {
    for (const size of SIZES) await run(browser, size, false);
    await run(browser, SIZES[0], true);
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ ok: checks.length > 0 && checks.every((c) => c.ok), checks, shots }));
})().catch((error) => {
  console.log(JSON.stringify({ ok: false, checks, error: String((error && error.stack) || error) }));
  process.exit(1);
});

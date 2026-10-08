/* CLIVE Shipping, in a real browser: the international orders, one order, a hold that buys its label,
 * and the Connections row for the service's two keys.
 *
 *   node scripts/browser/shipping.js http://127.0.0.1:PORT [/path/to/screenshots]
 *
 * The backend is the real one, with the shipping service's own code behind CLIVE's client and Claude
 * scripted for each sentence (tests/test_shipping_browser.py). Each sentence is typed into the page's
 * own diagnostics field, which posts exactly what the microphone posts. What is checked is what the
 * owner sees, at the tablet's size and a phone's:
 *
 *   - "Which international orders need me?" draws the orders going out, counted by stage, what stops
 *     each first, with dots that mean something;
 *   - "show me the shipping for 2145" keeps payment, label, print and carrier apart;
 *   - "buy the label for 2145" draws the hold card that IS the service's preview, price and all, and
 *     nothing is bought until the hold; on the phone the hold and the tap buy it, and the card says so;
 *   - "print the label for 2140" draws a print card (his swipe) that moves no money and goes through
 *     the service's PrintNode; on the phone the swipe sends it, and with the service's PrintNode
 *     switched off (as in this world) the card says the service refused it, never that it printed;
 *   - the Connections screen has the CLIVE Shipping row, and Connect asks for its two keys by the
 *     names of the server settings they are copied from;
 *   - nothing leaves the card's edge, the page does not scroll sideways, and nothing throws.
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
  { name: 'tablet', viewport: { width: 601, height: 889 }, dpr: 1.33, mobile: true, commit: false },
  { name: 'phone', viewport: { width: 390, height: 844 }, dpr: 3, mobile: true, commit: true },
];
const SAID = {
  open: 'Which international orders need me?',
  one: 'show me the shipping for 2145',
  buy: 'buy the label for 2145',
  print: 'print the label for 2140',
};
const SHIPPING = '#cards .card[data-type="shipping"]';
const HOLD = '#cards .card[data-type="confirmation"]';

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function run(browser, size) {
  const tag = size.name;
  const context = await browser.newContext({
    viewport: size.viewport, deviceScaleFactor: size.dpr, isMobile: size.mobile, hasTouch: size.mobile, extraHTTPHeaders: HEADERS,
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key"}' }));
  await page.goto(`${BASE}?dev=1&startup=off`, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => { try { localStorage.clear(); } catch { /* private mode */ } });
  await page.goto(`${BASE}?dev=1&startup=off`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(700);
  await page.evaluate(() => { for (const b of document.querySelectorAll('.dev-banner')) b.remove(); });

  const say = async (text, wait) => {
    await page.evaluate(() => {
      const sheet = document.querySelector('#settings');
      const dev = document.querySelector('#dev');
      if (dev) dev.hidden = false;
      if (sheet && !sheet.open && sheet.showModal) sheet.showModal();
    });
    await page.fill('#dev-text', text);
    await page.press('#dev-text', 'Enter');
    await sleep(500);
    await page.evaluate(() => { const sheet = document.querySelector('#settings'); if (sheet && sheet.open) sheet.close(); });
    try { await page.waitForSelector(wait, { timeout: 8000 }); } catch { /* checked below */ }
    await sleep(700);
  };
  const shot = async (name, at) => {
    if (!OUT) return;
    await page.evaluate((sel) => { const c = Array.from(document.querySelectorAll(sel)).pop(); if (c) c.scrollIntoView({ block: 'start' }); }, at);
    await page.waitForTimeout(350);
    const file = path.join(OUT, `shipping-${tag}-${name}.png`);
    await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
    shots.push(path.basename(file));
  };
  const seen = (sel) => page.evaluate((s) => {
    const card = Array.from(document.querySelectorAll(s)).pop();
    if (!card) return { found: false };
    const box = card.getBoundingClientRect();
    const past = Array.from(card.querySelectorAll('*')).filter((e) => {
      const r = e.getBoundingClientRect();
      return r.width > 0 && !e.closest('.tabs') && (r.right > box.right + 1 || r.left < box.left - 1);
    }).map((e) => e.className).slice(0, 5);
    const doc = document.documentElement;
    const dots = Array.from(card.querySelectorAll('.sh-row')).map((r) => ['is-ask', 'is-warn', 'is-bad', 'is-quiet'].find((c) => r.classList.contains(c)) || '');
    return { found: true, past, dots, sideways: doc.scrollWidth > doc.clientWidth + 1, text: card.innerText.replace(/\s+/g, ' ').trim() };
  }, sel);

  // 1. The orders going out: counted by stage, what stops them first.
  await say(SAID.open, SHIPPING);
  let card = await seen(SHIPPING);
  check(`${tag}: the orders going out, counted by stage, what stops each first`, card.found && /4 orders need you/.test(card.text)
    && /2 Needs attention/.test(card.text) && /1 Ready to ship/.test(card.text) && /1 Label bought/.test(card.text)
    && /#2148/.test(card.text) && /Missing weight · Missing HS code · Missing country of origin/.test(card.text)
    && /Payment pending/.test(card.text) && /£10\.69/.test(card.text) && /Label bought · Not printed/.test(card.text)
    && !/Max Muster|Torstrasse|Sam Lee|Broadway/.test(card.text), JSON.stringify(card));
  check(`${tag}: the dots: orange for what stops an order, blue for a label to buy or print`,
    JSON.stringify(card.dots) === JSON.stringify(['is-warn', 'is-warn', 'is-ask', 'is-ask']), JSON.stringify(card.dots));
  check(`${tag}: the shipping card fits`, card.found && !card.past.length && !card.sideways, JSON.stringify(card.past));
  await shot('1-orders', SHIPPING);

  // 2. One order: payment, label, print and carrier apart.
  await say(SAID.one, `${SHIPPING} .sh-facts`);
  card = await seen(SHIPPING);
  check(`${tag}: one order keeps its payment, label and service apart`, card.found && /Shipping for #2145/.test(card.text)
    && /Payment\s*Paid/.test(card.text) && /Label\s*Not bought/.test(card.text) && /£10\.69/.test(card.text), JSON.stringify(card));
  check(`${tag}: the order card fits`, card.found && !card.past.length && !card.sideways, JSON.stringify(card.past));
  await shot('2-order', SHIPPING);

  // 3. The hold card is the service's own preview; nothing is bought until the hold.
  await say(SAID.buy, HOLD);
  card = await seen(HOLD);
  check(`${tag}: the card is the service's preview, price and all, and asks for the hold`, card.found
    && /Buy the label for #2145/.test(card.text) && /for £10\.69 from/.test(card.text) && /Mark CROOKS-2145 fulfilled in Shopify/.test(card.text)
    && /Hold to arm, then tap/i.test(card.text) && /Moves money/i.test(card.text), JSON.stringify(card));
  check(`${tag}: the hold card fits`, card.found && !card.past.length && !card.sideways, JSON.stringify(card.past));
  await shot('3-buy-hold-card', HOLD);
  if (size.commit) {
    await page.waitForTimeout(900);
    const surface = await page.$(`${HOLD} .action-surface`);
    if (surface) await surface.evaluate((e) => e.scrollIntoView({ block: 'center' }));
    await page.waitForTimeout(400);
    const box = surface ? await surface.boundingBox() : null;
    if (box) {
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.waitForTimeout(2200);
      await page.mouse.up();
      await page.waitForTimeout(250);
      await page.mouse.down();
      await page.mouse.up();
    }
    try { await page.waitForSelector('#cards .card[data-type="success"]', { timeout: 15000 }); } catch { /* checked below */ }
    await sleep(800);
    const done = await page.evaluate(() => Array.from(document.querySelectorAll('#cards .card[data-type="success"]')).map((c) => c.innerText.replace(/\s+/g, ' ').trim()).pop() || '');
    check(`${tag}: his hold and tap buy it, and the card says what is true now`, /Label bought/.test(done) && /Tracking/.test(done), done);
    await shot('4-bought', '#cards .card[data-type="success"]');
  } else {
    const waiting = await page.evaluate((sel) => {
      const c = Array.from(document.querySelectorAll(sel)).pop();
      return c ? c.querySelector('.action-surface').dataset.state : '';
    }, HOLD);
    check(`${tag}: nothing is bought while the card waits for the hold`, ['arming', 'armed'].includes(waiting), waiting);
  }

  // 4. A print is its own card and his swipe: through the service's PrintNode, never a purchase.
  await say(SAID.print, HOLD);
  card = await seen(HOLD);
  check(`${tag}: the print card goes through the service's PrintNode, moves no money, and asks for the swipe`, card.found
    && /Print the label for #2140/.test(card.text) && /through PrintNode, once/.test(card.text)
    && /Moves money\s*no: printing never buys postage/i.test(card.text) && /Swipe to apply/i.test(card.text), JSON.stringify(card));
  check(`${tag}: the print card fits`, card.found && !card.past.length && !card.sideways, JSON.stringify(card.past));
  await shot('5-print-card', HOLD);
  if (size.commit) {
    await page.waitForTimeout(900);
    const box = await page.evaluate((sel) => {
      const c = Array.from(document.querySelectorAll(sel)).pop();
      const el = c ? c.querySelector('.action-surface') : null;
      if (!el) return null;
      el.scrollIntoView({ block: 'center' });
      const r = el.getBoundingClientRect();
      return { x: r.left, y: r.top, w: r.width, h: r.height };
    }, HOLD);
    if (box) {
      const y = box.y + box.h / 2;
      const x0 = box.x + 24;
      await page.mouse.move(x0, y);
      await page.mouse.down();
      for (let i = 1; i <= 12; i += 1) { await page.mouse.move(x0 + ((box.w - 36) * i) / 12, y); await sleep(25); }
      await page.mouse.up();
    }
    try { await page.waitForSelector('#cards .card[data-type="error"]', { timeout: 15000 }); } catch { /* checked below */ }
    await sleep(800);
    const said = await page.evaluate(() => Array.from(document.querySelectorAll('#cards .card')).map((c) => `${c.dataset.type}: ${c.innerText.replace(/\s+/g, ' ').trim()}`).join(' | '));
    check(`${tag}: with the service's PrintNode off, his swipe is refused in its words and nothing claims a print`,
      /error: /.test(said) && /PrintNode\) is not switched on\. Set PRINTNODE_\* in clive-shipping\/\.env/.test(said) && !/Sent to the printer/.test(said), said);
    await shot('6-print-refused', '#cards .card[data-type="error"]');
  } else {
    const waiting = await page.evaluate((sel) => {
      const c = Array.from(document.querySelectorAll(sel)).pop();
      return c ? c.querySelector('.action-surface').dataset.state : '';
    }, HOLD);
    check(`${tag}: nothing is sent to the printer while the card waits for the swipe`, ['arming', 'armed'].includes(waiting), waiting);
  }

  // 5. The Connections screen: the row for CLIVE Shipping's two keys.
  await page.goto(`${BASE}/connections`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  const row = await page.evaluate(() => {
    const r = document.querySelector('.conn[data-name="shipping"]');
    if (!r) return { found: false };
    r.scrollIntoView({ block: 'center' });
    const doc = document.documentElement;
    return { found: true, text: r.innerText.replace(/\s+/g, ' ').trim(), sideways: doc.scrollWidth > doc.clientWidth + 1 };
  });
  check(`${tag}: Connections has the CLIVE Shipping row, and it fits`, row.found && /CLIVE Shipping/.test(row.text) && !row.sideways,
    JSON.stringify(row));
  // Connect asks for the service's two keys, each named by the server setting it is copied from.
  const act = await page.$('.conn[data-name="shipping"] .conn-act');
  if (act) await act.click();
  await page.waitForTimeout(400);
  const boxes = await page.evaluate(() => {
    const r = document.querySelector('.conn[data-name="shipping"]');
    if (!r) return { keys: 0, text: '' };
    r.scrollIntoView({ block: 'center' });
    return { keys: r.querySelectorAll('input.key-input').length, text: r.innerText.replace(/\s+/g, ' ').trim() };
  });
  check(`${tag}: Connect asks for the read key and the write key, by their server settings`, boxes.keys === 2
    && /SHIPPING_CLIVE_READ_KEYS/.test(boxes.text) && /SHIPPING_CLIVE_WRITE_KEYS/.test(boxes.text)
    && /\/opt\/clive\/clive-shipping\/\.env/.test(boxes.text), JSON.stringify(boxes));
  if (OUT) {
    await page.waitForTimeout(300);
    const file = path.join(OUT, `shipping-${tag}-7-connections.png`);
    await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
    shots.push(path.basename(file));
  }

  check(`${tag}: nothing threw`, errors.length === 0, errors.join(' | '));
  await context.close();
}

(async () => {
  const onDisk = process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
  const browser = await chromium.launch({ executablePath: onDisk });
  try {
    for (const size of SIZES) await run(browser, size);
  } catch (error) {
    checks.push({ name: 'the run finished', ok: false, detail: String(error && error.stack || error).slice(0, 600) });
  } finally {
    await browser.close();
  }
  process.stdout.write(JSON.stringify({ ok: checks.every((c) => c.ok), checks, shots }) + '\n');
})();

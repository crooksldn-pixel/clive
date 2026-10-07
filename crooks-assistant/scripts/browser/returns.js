/* CROOKS Returns, in a real browser: what needs him, a hold that approves, where a return is, the
 * month's numbers, an order's returns and a customer's story.
 *
 *   node scripts/browser/returns.js http://127.0.0.1:PORT [/path/to/screenshots]
 *
 * The backend is the real one on the customers' fixture shop, with the returns service's own code
 * behind CLIVE's client and Claude scripted for each sentence (tests/test_returns_browser.py). Each
 * sentence is typed into the page's own diagnostics field, which posts exactly what the microphone
 * posts. What is checked is what the owner sees, at the tablet's size and a phone's:
 *
 *   - the home's Needs you row says how many returns need him and why, and never who;
 *   - "Which returns need me?" draws the open returns, the broken first, with the label to cancel;
 *   - "approve Mia's swap" draws the hold card that IS the service's preview, and nothing happens
 *     until the hold; on the phone the hold and the tap approve it, and the card says so;
 *   - "where is Alicia's return" says where it is and draws its timeline;
 *   - "how did returns do this month" carries the size-chart finding;
 *   - an order's card shows its return, and a customer's story has her returns in it;
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
  open: 'Which returns need me?',
  approve: "approve Mia's swap and send her a label",
  where: "where is Alicia's return",
  stats: 'how did returns do this month',
  order: 'show me order 2202',
  story: "show me Alicia Grant's history",
};
const RETURNS = '#cards .card[data-type="returns"]';

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
    const file = path.join(OUT, `returns-${tag}-${name}.png`);
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
    return { found: true, past, sideways: doc.scrollWidth > doc.clientWidth + 1, text: card.innerText.replace(/\s+/g, ' ').trim() };
  }, sel);

  // 1. The home: one row in Needs you for the returns, its words, and no customer's name.
  try { await page.waitForSelector('[data-alpha="returns"]', { timeout: 8000 }); } catch { /* checked below */ }
  const home = await page.evaluate(() => {
    const row = document.querySelector('[data-alpha="returns"]');
    const summary = document.querySelector('.alpha-summary');
    return { row: row ? row.innerText.replace(/\s+/g, ' ').trim() : '', summary: summary ? summary.innerText : '' };
  });
  check(`${tag}: the home says how many returns need him and why, never who`,
    /3 returns need you/.test(home.row) && /1 needs a decision/.test(home.row) && /1 delivered, not checked/.test(home.row) && /1 to approve/.test(home.row)
      && /1 unused label to cancel/.test(home.row) && !/Mia|Alicia|Alison|Elise/.test(home.row), JSON.stringify(home));
  await shot('1-home', '[data-alpha="returns"]');

  // 2. What needs him: the broken first, then his decisions, and the label to cancel.
  await say(SAID.open, RETURNS);
  let card = await seen(RETURNS);
  check(`${tag}: the open returns, what each needs, and the label never posted`, card.found && /3 returns need you/.test(card.text)
    && /#2202 Alison Grey/.test(card.text) && /has an error|needs a decision/.test(card.text) && /delivered, not checked/.test(card.text)
    && /to approve/.test(card.text) && /Labels never posted · cancel on parcel2go\.com/i.test(card.text) && /#2190 Elise Hart/.test(card.text),
  JSON.stringify(card));
  check(`${tag}: the returns card fits`, card.found && !card.past.length && !card.sideways, JSON.stringify(card.past));
  await shot('2-what-needs-you', RETURNS);

  // 3. The hold card is the service's own preview; nothing happens until the hold.
  const HOLD = '#cards .card[data-type="confirmation"]';
  await say(SAID.approve, HOLD);
  card = await seen(HOLD);
  check(`${tag}: the card is the service's preview, money and all, and asks for the hold`, card.found
    && /Approve the return · label bought now/.test(card.text) && /Create Shopify return on CROOKS-2205/.test(card.text)
    && /Book Evri \(Evri Parcelshop\) for £2\.39 from Parcel2Go PrePay/.test(card.text) && /Hold to arm, then tap/i.test(card.text)
    && /Moves money/i.test(card.text), JSON.stringify(card));
  await shot('3-approve-hold-card', HOLD);
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
    check(`${tag}: his hold and tap approve it, and the card says what is true now`,
      /Return approved/.test(done) && /waiting for the customer to post it/.test(done), done);
    await shot('4-approved', '#cards .card[data-type="success"]');
  } else {
    const waiting = await page.evaluate((sel) => {
      const c = Array.from(document.querySelectorAll(sel)).pop();
      return c ? c.querySelector('.action-surface').dataset.state : '';
    }, HOLD);
    check(`${tag}: nothing is sent while the card waits for the hold`, ['arming', 'armed'].includes(waiting), waiting);
  }

  // 4. Where a return is.
  await say(SAID.where, RETURNS);
  card = await seen(RETURNS);
  check(`${tag}: where Alicia's return is, from its status, tracking and timeline`, card.found && /Return on #2201/.test(card.text)
    && /#2201 is on its way back/.test(card.text) && /delivered to us/i.test(card.text) && /Label bought/.test(card.text), JSON.stringify(card));
  await shot('5-where-is-it', RETURNS);

  // 5. The month's numbers, with the size finding.
  await say(SAID.stats, `${RETURNS} .rt-figs`);
  card = await seen(RETURNS);
  check(`${tag}: the month's numbers carry the size-chart finding`, card.found && /Returns · last 30 days/.test(card.text)
    && /Convict T-Shirt: 2 came back too small/.test(card.text) && /check its size chart/.test(card.text), JSON.stringify(card));
  await shot('6-month', RETURNS);

  // 6. An order's card shows its return under its money.
  const ORDER = '#cards .card[data-type="order"]';
  await say(SAID.order, `${ORDER} .sec-returns`);
  const onOrder = await page.evaluate((s) => {
    const sec = Array.from(document.querySelectorAll(s)).pop();
    return sec ? sec.innerText.replace(/\s+/g, ' ').trim() : '';
  }, `${ORDER} .sec-returns`);
  check(`${tag}: order 2202's card shows its return and what it needs`, /Returns/i.test(onOrder) && /needs a decision/.test(onOrder)
    && /#2202 is back with us/.test(onOrder), onOrder);
  await shot('7-order-card', `${ORDER} .sec-returns`);

  // 7. A customer's story has her returns in it.
  const CUSTOMER = '#cards .card[data-type="customer"]';
  await say(SAID.story, `${CUSTOMER} .tab[data-tab="activity"]`);
  const tab = await page.$(`${CUSTOMER} .tab[data-tab="activity"]`);
  if (tab) await tab.click();
  await sleep(400);
  const story = await page.evaluate((s) => {
    const c = Array.from(document.querySelectorAll(s)).pop();
    return c ? Array.from(c.querySelectorAll('.cst-row.is-returns')).filter((r) => r.offsetParent !== null).map((r) => r.innerText.replace(/\s+/g, ' ').trim()) : [];
  }, CUSTOMER);
  check(`${tag}: her story has her returns`, story.some((r) => /Return on #2201: on its way back/.test(r))
    && story.some((r) => /Asked to return #2150/.test(r)), JSON.stringify(story));
  await shot('8-her-story', CUSTOMER);

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

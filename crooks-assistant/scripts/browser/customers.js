/* Customers, in a real browser: the order he meant, a customer's story, a checkout link, a refund.
 *
 *   node scripts/browser/customers.js http://127.0.0.1:PORT [/path/to/screenshots]
 *
 * The backend is the real one on the customers' fixture shop (tests/customers_world.py), with
 * Claude scripted for each sentence (tests/test_customers_browser.py). Each sentence is typed into
 * the page's own diagnostics field, which posts exactly what the microphone posts. What is checked
 * is what the owner sees, at the tablet's own size (601 x 889 at DPR 1.33) and a phone's:
 *
 *   - "look up Alysa who ordered the grey hoodie last week" puts up the one order it found, with
 *     the line that says why — "name heard as 'Alysa'" — and a tap on it opens that order;
 *   - "Alysa who ordered a hoodie last week" puts up the two that fit and one question;
 *   - "show me Alicia Grant's history" puts up her card, and its History tab is her story;
 *   - "send Mia a checkout link for the black tee, size M" puts up the hold card that IS the email:
 *     to, items, Shopify's price, the link, the words — and nothing has been sent;
 *   - "has the refund on 2201 landed" puts up the order with its refund's answer under the money;
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
  { name: 'tablet', viewport: { width: 601, height: 889 }, dpr: 1.33, mobile: true },
  { name: 'phone', viewport: { width: 390, height: 844 }, dpr: 3, mobile: true },
];
// Said in this order; tests/test_customers_browser.py scripts what Claude calls for each.
const SAID = {
  lookup: 'look up Alysa who ordered the grey hoodie last week',
  several: 'Alysa who ordered a hoodie last week',
  history: "show me Alicia Grant's history",
  checkout: 'send Mia a checkout link for the black tee, size M',
  refund: 'has the refund on 2201 landed',
};

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
    await page.evaluate((sel) => { const c = document.querySelector(sel); if (c) c.scrollIntoView({ block: 'start' }); }, at);
    await page.waitForTimeout(350);
    const file = path.join(OUT, `customers-${tag}-${name}.png`);
    await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
    shots.push(path.basename(file));
  };
  const fits = (sel) => page.evaluate((s) => {
    const card = document.querySelector(s);
    if (!card) return { found: false };
    const box = card.getBoundingClientRect();
    // A tab bar scrolls sideways by design (web/style.css .tabs, faded at its edge by
    // web/edges.js), so a tab past the card's edge on a phone is reached by a swipe, not lost.
    const past = Array.from(card.querySelectorAll('*')).filter((e) => {
      const r = e.getBoundingClientRect();
      return r.width > 0 && !e.closest('.tabs') && (r.right > box.right + 1 || r.left < box.left - 1);
    }).map((e) => e.className).slice(0, 5);
    const doc = document.documentElement;
    return { found: true, past, sideways: doc.scrollWidth > doc.clientWidth + 1, text: card.innerText.replace(/\s+/g, ' ').trim() };
  }, sel);

  // 1. The order he meant, found from a misheard name.
  const MATCH = '#cards .card[data-type="order_match"]';
  await say(SAID.lookup, MATCH);
  let seen = await fits(MATCH);
  check(`${tag}: one order found from 'Alysa', with why`, seen.found && /Best match/.test(seen.text) && /name heard as 'Alysa'/.test(seen.text)
    && /#2201/.test(seen.text) && /Alicia Grant/.test(seen.text), JSON.stringify(seen));
  check(`${tag}: the match fits its card`, seen.found && !seen.past.length && !seen.sideways, JSON.stringify(seen.past));
  await shot('1-lookup', MATCH);
  await page.click(`${MATCH} .cm-row`);
  try { await page.waitForSelector('#cards .card[data-type="order"]', { timeout: 8000 }); } catch { /* checked below */ }
  await sleep(600);
  const opened = await page.evaluate(() => Array.from(document.querySelectorAll('#cards .card[data-type="order"] .card-title')).map((t) => t.innerText));
  check(`${tag}: a tap on the match opens that order`, opened.some((t) => /2201/.test(t)), JSON.stringify(opened));

  // 2. Two that fit about as well, and one question.
  await say(SAID.several, `${MATCH} .cm-question`);
  seen = await fits(MATCH);
  check(`${tag}: two that fit are shown with one question`, seen.found && /Which one\?/.test(seen.text) && /#2202/.test(seen.text)
    && /Which one: Alicia Grant/.test(seen.text), JSON.stringify(seen));
  await shot('2-which-one', MATCH);

  // 3. A customer's story, in her card's History tab.
  const CUSTOMER = '#cards .card[data-type="customer"]';
  await say(SAID.history, `${CUSTOMER} .tab[data-tab="activity"]`);
  const tab = await page.$(`${CUSTOMER} .tab[data-tab="activity"]`);
  if (tab) await tab.click();
  await sleep(400);
  const story = await page.evaluate((s) => {
    const card = Array.from(document.querySelectorAll(s)).pop();
    return card ? Array.from(card.querySelectorAll('.cst-row')).filter((r) => r.offsetParent !== null).map((r) => r.innerText.replace(/\s+/g, ' ').trim()) : [];
  }, CUSTOMER);
  check(`${tag}: her story, newest first, from the shop, the inbox and CLIVE`, story.length >= 6 && /Refunded £45.00 on #2201/.test(story[0])
    && story.some((r) => /Emailed us/.test(r)) && story.some((r) => /We emailed them/.test(r)) && story.some((r) => /Ordered #2150/.test(r)),
  JSON.stringify(story));
  seen = await fits(CUSTOMER);
  check(`${tag}: the story fits its card`, seen.found && !seen.past.length && !seen.sideways, JSON.stringify(seen.past));
  await shot('3-history', CUSTOMER);

  // 4. A checkout link: the hold card is the email, and nothing has gone.
  const HOLD = '#cards .card[data-type="confirmation"]';
  await say(SAID.checkout, HOLD);
  seen = await fits(HOLD);
  check(`${tag}: the checkout link's card shows to, items, Shopify's price, the link and the words`, seen.found
    && /Send a checkout link/.test(seen.text) && /Mia Jones <mia\.jones@example\.com>/.test(seen.text)
    && /Convict T-Shirt Black \/ M · £30\.00/.test(seen.text) && /https:\/\/crooksldn\.com\//.test(seen.text)
    && /Pay here:/.test(seen.text) && /hold/i.test(seen.text), JSON.stringify(seen));
  check(`${tag}: the checkout card fits`, seen.found && !seen.past.length && !seen.sideways, JSON.stringify(seen.past));
  await shot('4-checkout-link', HOLD);

  // 5. Has the refund landed: the order, its money, and the provider's answer under it.
  await say(SAID.refund, '#cards .card[data-type="order"] .cm-refund');
  const refund = await page.evaluate(() => Array.from(document.querySelectorAll('#cards .card[data-type="order"] .cm-refund')).map((r) => r.innerText.trim()));
  check(`${tag}: the refund says it landed, to which card and when`, refund.some((r) => /Refund of £45\.00 to Visa ending 4242 succeeded on /.test(r)),
    JSON.stringify(refund));
  await shot('5-refund-landed', '#cards .card[data-type="order"] .sec-money');

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

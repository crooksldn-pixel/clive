/* [returns-events] CROOKS Returns rings CLIVE's door, in a real browser: what the owner sees when a
 * return comes in to approve and another one's refund fails, with nobody touching anything.
 *
 *   node scripts/browser/returns_events.js http://127.0.0.1:PORT [/path/to/screenshots]
 *
 * Driven by tests/test_returns_events_browser.py over stdin and stdout: at each `phase:<size>:<name>`
 * line this prints, the test changes the returns service (tests/returns_stub.py) and posts its signed
 * events to /hooks/returns exactly as the service does, then answers with a line. What is checked is
 * what is on the glass, at the tablet's size and a phone's:
 *
 *   - before: nothing about returns needs him, so the home has no returns row and no notice;
 *   - after the doorbell, by the home's own next look (no tap, no reload): the Needs you row says two
 *     returns need him and why, and two notices say what happened by order number, the failure
 *     marked Failed and the approval a Note, never a customer's name; both fit the screen;
 *   - Dismiss takes a notice away, and neither the next look nor a reload says either again.
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...] }.
 */
'use strict';

const { chromium } = require('playwright-core');
const path = require('path');
const readline = require('readline');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const SIZES = [
  { name: 'tablet', viewport: { width: 601, height: 889 }, dpr: 1.33 },
  { name: 'phone', viewport: { width: 390, height: 844 }, dpr: 3 },
];
const POLL_WAIT_MS = 30000;   // the home looks again every 20 seconds (web/alpha.js)
const CUSTOMERS = /Ana Fixture|Ben Fixture|example\.com/;

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 500) });

const lines = readline.createInterface({ input: process.stdin });
const waiting = [];
lines.on('line', () => { const next = waiting.shift(); if (next) next(); });
function phase(tag, name) {
  process.stdout.write(`phase:${tag}:${name}\n`);
  return new Promise((resolve) => waiting.push(resolve));
}

async function glass(page) {
  return page.evaluate(() => {
    const row = document.querySelector('[data-alpha="returns"]');
    const notes = Array.from(document.querySelectorAll('.note')).filter((n) => /Return on/.test(n.innerText))
      .map((n) => {
        const box = n.getBoundingClientRect();
        const shown = !n.hidden && !n.closest('[hidden]') && box.width > 0 && box.height > 0;
        return { text: n.innerText.replace(/\s+/g, ' ').trim(), tone: n.dataset.tone, shown, left: box.left, right: box.right };
      });
    const doc = document.documentElement;
    return { row: row ? row.innerText.replace(/\s+/g, ' ').trim() : '', notes, width: doc.clientWidth, sideways: doc.scrollWidth > doc.clientWidth + 1 };
  });
}

async function run(browser, size) {
  const tag = size.name;
  await phase(tag, 'fresh');
  const context = await browser.newContext({
    viewport: size.viewport, deviceScaleFactor: size.dpr, isMobile: true, hasTouch: true, extraHTTPHeaders: HEADERS,
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key"}' }));
  const open = async () => {
    await page.goto(`${BASE}?dev=1&startup=off`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1500);
    await page.evaluate(() => { for (const b of document.querySelectorAll('.dev-banner')) b.remove(); });
  };
  const shot = async (name) => {
    if (!OUT) return;
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(300);
    const file = path.join(OUT, `returns-events-${tag}-${name}.png`);
    await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
    shots.push(path.basename(file));
  };

  // 1. Before: nothing about returns needs him.
  await open();
  const before = await glass(page);
  check(`${tag}: before the doorbell the home has no returns row and no notice`, !before.row && !before.notes.length, JSON.stringify(before));
  await shot('1-before');

  // 2. The service records two events and rings; the home's own next look shows them.
  await phase(tag, 'loaded');
  const started = Date.now();
  try {
    await page.waitForFunction(() => {
      const row = document.querySelector('[data-alpha="returns"]');
      return row && /2 returns need you/.test(row.innerText)
        && Array.from(document.querySelectorAll('.note')).filter((n) => /Return on/.test(n.innerText)).length >= 2;
    }, null, { timeout: POLL_WAIT_MS });
  } catch { /* checked below */ }
  const rang = await glass(page);
  const note = rang.notes.find((n) => /#2131/.test(n.text));
  const failed = rang.notes.find((n) => /#2132/.test(n.text));
  check(`${tag}: the home's next look says two returns need him and why, with no tap`,
    /2 returns need you/.test(rang.row) && /1 has an error/.test(rang.row) && /1 to approve/.test(rang.row),
    `${JSON.stringify(rang.row)} after ${Date.now() - started} ms`);
  check(`${tag}: a notice says the return to approve, by its order`,
    note && note.shown && note.tone === 'info' && /^Note Return on #2131: waiting for your approval\. Dismiss$/i.test(note.text), JSON.stringify(note));
  check(`${tag}: a notice says the refund that failed, marked Failed`,
    failed && failed.shown && failed.tone === 'bad' && /^Failed Return on #2132: Shopify didn't move the money\. Dismiss$/i.test(failed.text),
    JSON.stringify(failed));
  check(`${tag}: no customer's name or address anywhere it says so`,
    !CUSTOMERS.test(rang.row) && !rang.notes.some((n) => CUSTOMERS.test(n.text)), JSON.stringify(rang));
  check(`${tag}: the notices fit the screen and nothing scrolls sideways`,
    rang.notes.length >= 2 && rang.notes.every((n) => n.left >= -1 && n.right <= rang.width + 1) && !rang.sideways, JSON.stringify(rang));
  await shot('2-rang');

  // 3. Dismiss: gone, and never said again, at the next look or after a reload.
  const dismiss = page.locator('.note', { hasText: 'Return on #2131' }).locator('.note-dismiss');
  if (await dismiss.count()) await dismiss.first().tap();
  await page.waitForTimeout(300);
  const after = await glass(page);
  check(`${tag}: Dismiss takes the notice away and leaves the other`,
    !after.notes.some((n) => /#2131/.test(n.text)) && after.notes.some((n) => /#2132/.test(n.text)), JSON.stringify(after.notes));
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));   // he comes back to the app
  await page.waitForTimeout(2000);
  const again = await glass(page);
  check(`${tag}: the next look does not say it again`, !again.notes.some((n) => /#2131/.test(n.text)) && /2 returns need you/.test(again.row),
    JSON.stringify(again));
  await open();
  const reloaded = await glass(page);
  check(`${tag}: after a reload the row is still there and neither notice is said again`,
    /2 returns need you/.test(reloaded.row) && !reloaded.notes.length, JSON.stringify(reloaded));
  await shot('3-reloaded');

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
    lines.close();
  }
  process.stdout.write(JSON.stringify({ ok: checks.every((c) => c.ok), checks, shots }) + '\n');
})();

/* Named routines, in a real browser: saved, listed, run, edited and forgotten by name (DEC-074).
 *
 *   node scripts/browser/routines.js http://127.0.0.1:PORT [/path/to/screenshots]
 *
 * The backend is the real one on the golden world, with Claude scripted for each sentence
 * (tests/test_routines_browser.py). Each sentence is typed into the page's own diagnostics field,
 * which posts exactly what the microphone posts. What is checked is what the owner sees, at the
 * tablet's size and a phone's:
 *
 *   - "save this as my friday drop routine" draws the routine as it was saved: its steps in order,
 *     the change ringed blue and saying it will wait for him, and that no order is kept;
 *   - "show my routines" lists it with its steps and changes;
 *   - "run my friday drop routine" puts the change's own hold card on top, then the routine as it
 *     ran (two reads done, the change waiting for him), then what the reads found; and the card
 *     still waits: nothing is applied;
 *   - "take step 2 out of my friday drop routine" and "forget my friday drop routine" say what
 *     they did, read back from the store, each a screen of its own (nothing of the run left under it);
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
const SAID = {
  save: 'save this as my friday drop routine',
  list: 'show my routines',
  run: 'run my friday drop routine',
  drop: 'take step 2 out of my friday drop routine',
  forget: 'forget my friday drop routine',
};
const ROUTINE = '#cards .card[data-type="routine"]';
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

  // What the last answer drew: so a wait is for THIS answer's card, not the one before it.
  const answered = () => page.evaluate(() => Array.from(document.querySelectorAll('#cards .card')).map((c) => c.dataset.render || '').join('|'));
  const say = async (text, wait) => {
    const before = await answered();
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
    try {
      await page.waitForFunction(([sel, was]) => document.querySelector(sel)
        && Array.from(document.querySelectorAll('#cards .card')).map((c) => c.dataset.render || '').join('|') !== was, [wait, before], { timeout: 10000 });
    } catch { /* checked below */ }
    await sleep(800);
  };
  const shot = async (name, at) => {
    if (!OUT) return;
    await page.evaluate((sel) => { const c = document.querySelector(sel); if (c) c.scrollIntoView({ block: 'start' }); }, at);
    await page.waitForTimeout(350);
    const file = path.join(OUT, `routines-${tag}-${name}.png`);
    await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
    shots.push(path.basename(file));
  };
  const seen = (sel) => page.evaluate((s) => {
    const card = Array.from(document.querySelectorAll(s)).pop();
    if (!card) return { found: false };
    const box = card.getBoundingClientRect();
    const past = Array.from(card.querySelectorAll('*')).filter((e) => {
      const r = e.getBoundingClientRect();
      return r.width > 0 && (r.right > box.right + 1 || r.left < box.left - 1);
    }).map((e) => e.className).slice(0, 5);
    const doc = document.documentElement;
    const dots = Array.from(card.querySelectorAll('.rn-row')).map((r) => ['is-ask', 'is-warn', 'is-bad', 'is-quiet', 'is-change', 'is-read', 'is-pending'].find((c) => r.classList.contains(c)) || '');
    return { found: true, past, dots, sideways: doc.scrollWidth > doc.clientWidth + 1, text: card.innerText.replace(/\s+/g, ' ').trim() };
  }, sel);
  const fits = (card) => card.found && !card.past.length && !card.sideways;

  // 1. Saved: its steps in order, the change ringed and saying it waits for him, no order kept.
  await say(SAID.save, ROUTINE);
  let card = await seen(ROUTINE);
  check(`${tag}: saved, the routine as the store read it back`, card.found && /Friday drop/.test(card.text)
    && /Saved\. 3 steps, 1 change/.test(card.text) && /1\s*Today's orders/.test(card.text) && /2\s*Who wrote today/.test(card.text)
    && /3\s*Note on 1940: pack it first/.test(card.text) && /A change: waits for you on its card/.test(card.text)
    && /No order or thread is kept: each run looks them up again\./.test(card.text), JSON.stringify(card));
  check(`${tag}: the reads are quiet and the change is ringed blue`,
    JSON.stringify(card.dots) === JSON.stringify(['is-read', 'is-read', 'is-change']), JSON.stringify(card.dots));
  check(`${tag}: the saved routine fits`, fits(card), JSON.stringify(card.past));
  await shot('1-saved', ROUTINE);

  // 2. Listed.
  await say(SAID.list, ROUTINE);
  card = await seen(ROUTINE);
  check(`${tag}: listed with its steps and its change`, card.found && /Routines/.test(card.text) && /1 routine saved/.test(card.text)
    && /Friday drop/.test(card.text) && /3 steps, 1 change/.test(card.text)
    && /Today's orders · Who wrote today · Note on 1940: pack it first/.test(card.text), JSON.stringify(card));
  await shot('2-listed', ROUTINE);

  // 3. Run: the hold card on top, then the routine as it ran, then what the reads found.
  await say(SAID.run, HOLD);
  card = await seen(ROUTINE);
  const order = await page.evaluate(() => Array.from(document.querySelectorAll('#cards .card')).map((c) => c.dataset.type));
  const hold = await seen(HOLD);
  check(`${tag}: the change's own card is on top, then the routine, then what the steps read`,
    order[0] === 'confirmation' && order[1] === 'routine' && order.includes('order_list') && order.includes('email_list'), JSON.stringify(order));
  check(`${tag}: the routine as it ran: two reads done, the change waiting for him`, card.found
    && /Ran: 2 done · 1 waiting for you/.test(card.text) && /Waiting for you on its card/.test(card.text)
    && JSON.stringify(card.dots) === JSON.stringify(['is-quiet', 'is-quiet', 'is-ask']), JSON.stringify(card));
  const waiting = await page.evaluate((sel) => {
    const c = document.querySelector(sel);
    const surface = c ? c.querySelector('.action-surface') : null;
    return surface ? surface.dataset.state : '';
  }, HOLD);
  check(`${tag}: the note on 1940 is a card waiting for his gesture, and nothing is applied`, hold.found
    && /#1940/.test(hold.text) && ['arming', 'armed'].includes(waiting), `${waiting} :: ${hold.text}`);
  check(`${tag}: the run fits`, fits(card) && fits(hold), JSON.stringify([card.past, hold.past]));
  await shot('3-run-hold-on-top', HOLD);
  await shot('4-run-routine', ROUTINE);

  // 4. Edited, then forgotten: each said from what the store now holds.
  await say(SAID.drop, ROUTINE);
  card = await seen(ROUTINE);
  check(`${tag}: a step taken out, read back`, card.found && /Took out step 2\. 2 steps, 1 change/.test(card.text)
    && !/Who wrote today/.test(card.text), JSON.stringify(card));
  await say(SAID.forget, ROUTINE);
  card = await seen(ROUTINE);
  check(`${tag}: forgotten, and none saved`, card.found && /Forgot Friday drop\. None saved yet/.test(card.text), JSON.stringify(card));
  const left = await page.evaluate(() => Array.from(document.querySelectorAll('#cards .card')).map((c) => c.dataset.type));
  check(`${tag}: the list is the screen, with nothing of the run left under it`, JSON.stringify(left) === '["routine"]', JSON.stringify(left));
  await shot('5-forgotten', ROUTINE);

  check(`${tag}: no page errors`, errors.length === 0, errors.join(' | '));
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

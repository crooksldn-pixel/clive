/* The test bench's screen in a real browser, on a scripted bench run of the fake shop.
 *
 *   node scripts/browser/bench.js http://127.0.0.1:8765 [/path/to/screenshots]
 *
 * Driven by tests/test_bench_browser.py (and `python -m tests.bench_world <shots>`), which makes a run
 * with every model scripted (tests/bench_world.py) and serves the real backend and its door on the
 * fake shop. Judged on what is on the glass, at a phone's size (390 x 844) and the tablet's (601 x 889):
 *
 *   - the settings sheet carries a Test bench row, and /bench lists the run, saying it was scripted;
 *   - a run says it was scripted before anything else, shows four measured safety counts, all nought,
 *     the results to rate, scores by person, the worst, what CLIVE could not do (each beside CLIVE's
 *     own record of real use), tools never used;
 *   - a result shows the conversation, the tools, the refund waiting for the hold, the cards drawn in
 *     their frame by CLIVE's own renderer, and the judge's six scores with reasons;
 *   - a rating of 4 with a note is saved, said, and counted on the run and in the agreement;
 *   - nothing is wider than the screen, every button is a finger's size, and the console stays clean.
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...] }.
 */
'use strict';

const { chromium } = require('playwright-core');
const path = require('path');

const BASE = (process.argv[2] || 'http://127.0.0.1:8765').replace(/\/$/, '');
const OUT = process.argv[3] || '';
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const SIZES = {
  phone: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true },
  tablet: { viewport: { width: 601, height: 889 }, deviceScaleFactor: 1.33, isMobile: true, hasTouch: true },
};

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });

async function open(browser, size) {
  const context = await browser.newContext(Object.assign({ extraHTTPHeaders: HEADERS }, SIZES[size]));
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/\/speak|Failed to load resource/.test(m.text())) errors.push(m.text()); });
  return { context, page, errors };
}

async function shot(page, name, full) {
  if (!OUT) return;
  const file = path.join(OUT, `${name}.png`);
  await page.waitForTimeout(400);
  await page.screenshot({ path: file, animations: 'disabled', fullPage: Boolean(full) });
  shots.push(path.basename(file));
}

async function ready(page) {
  await page.waitForSelector('#bench-page[data-ready="true"] #view[aria-busy="false"]', { timeout: 20000 });
  await page.waitForTimeout(350);
}

// A tap that changes the view: the address moves, then the new view has drawn.
async function moved(page, mark) {
  await page.waitForFunction((m) => location.hash.includes(m) && document.getElementById('bench-page').dataset.view === location.hash,
    mark, { timeout: 20000 });
  await page.waitForTimeout(350);
}

async function fits(page, size, where) {
  const wide = await page.evaluate(() => {
    const w = document.documentElement.clientWidth;
    return [...document.querySelectorAll('#bench-page *')].filter((n) => {
      const r = n.getBoundingClientRect();
      return r.width > 0 && r.right > w + 1 && !n.closest('details:not([open])') && !n.closest('.table-wrap');
    }).map((n) => n.className || n.tagName).slice(0, 5);
  });
  check(`${size}, ${where}: nothing is wider than the screen`, wide.length === 0, wide.join(', '));
  const small = await page.evaluate(() => [...document.querySelectorAll('#bench-page button, #bench-page a.back, #bench-page summary')]
    .filter((n) => { const r = n.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.height < 35.5; })
    .map((n) => `${n.className || n.tagName}:${Math.round(n.getBoundingClientRect().height)}`).slice(0, 5));
  check(`${size}, ${where}: every button is a finger's size`, small.length === 0, small.join(', '));
}

async function phone(browser) {
  const { context, page, errors } = await open(browser, 'phone');
  // The way in: the settings sheet's row.
  await page.goto(`${BASE}/?startup=off`, { waitUntil: 'domcontentloaded' });
  const row = await page.locator('#open-bench').getAttribute('href').catch(() => null);
  check('the settings sheet carries a Test bench row that opens /bench', row === '/bench', row);

  await page.goto(`${BASE}/bench`, { waitUntil: 'domcontentloaded' });
  await ready(page);
  const title = await page.locator('#title').textContent();
  check('the screen is called Test bench', title === 'Test bench', title);
  const runs = await page.locator('#view .row').allTextContents();
  check('the run is listed, saying no model was asked', runs.length === 1 && /scripted, no model asked/.test(runs[0]), runs.join(' | '));
  check('the run row counts its questions and people', /10 questions · 6 people/.test(runs[0] || ''), runs[0]);
  await shot(page, 'phone-01-runs');
  await fits(page, 'phone', 'runs');

  await page.locator('#view button.row').first().click();
  await moved(page, '#run=');
  const banner = await page.locator('#view .banner').first().textContent();
  check('a scripted run says so before anything else', /^Scripted run: no model was asked/.test(banner), banner);
  const safe = await page.locator('.safe').allTextContents();
  check('four safety counts, all nought', safe.join('|') === 'Nothing executed|Nothing sent to the shop|No card taken past its hold|The seal held', safe.join('|'));
  check('every safety dot is green', (await page.locator('.safe .dot.is-good').count()) === 4, '');
  const groups = await page.locator('.group-title').allTextContents();
  for (const name of ['Rate these', 'By person', 'Worst ten', 'CLIVE couldn’t do', 'Tools never used', 'Every question']) {
    check(`the run shows ${name}`, groups.some((g) => g.startsWith(name)), groups.join(' | '));
  }
  const gaps = await page.locator('.group', { hasText: 'CLIVE couldn’t do' }).locator('.row-name').allTextContents();
  check('what CLIVE could not do names the capabilities', ['film recommendations', 'CRM pipeline', 'supplier payments'].every((g) => gaps.includes(g)), gaps.join(' | '));
  const inUse = await page.locator('.group', { hasText: 'CLIVE couldn’t do' }).locator('.row-line').allTextContents();
  check('each gap says whether CLIVE has hit it in real use', inUse.filter((l) => l === 'Not hit in real use yet').length === 3, inUse.join(' | '));
  if (OUT) {
    const gapGroup = page.locator('.group', { hasText: 'CLIVE couldn’t do' });
    await gapGroup.scrollIntoViewIfNeeded();
    await gapGroup.screenshot({ path: path.join(OUT, 'phone-03b-gaps.png'), animations: 'disabled' });
    shots.push('phone-03b-gaps.png');
  }
  const summary = await page.locator('#summary').textContent();
  check('the run says how many were scored and its overall', /10 questions · 10 scored · 3\.3 overall · 0 rated by you/.test(summary), summary);
  await shot(page, 'phone-02-run-top');
  await shot(page, 'phone-03-run-full', true);
  await fits(page, 'phone', 'a run');

  // Filter every question by person.
  await page.locator('.filter', { hasText: 'Emily' }).click();
  const emily = await page.locator('.group', { hasText: 'Every question' }).locator('.row').count();
  check('every question filters by person', emily === 2, emily);

  // A result with cards: George's "show me order 1938".
  const runId = (await page.evaluate(() => location.hash)).replace('#run=', '');
  await page.goto(`${BASE}/bench#run=${runId}&q=q006`, { waitUntil: 'domcontentloaded' });
  await ready(page);
  const bubbles = await page.locator('.bubble').allTextContents();
  check('the conversation is shown: what was said and what CLIVE answered', bubbles.length === 2 && /show me order 1938/.test(bubbles[0]) && /Order 1938/.test(bubbles[1]), bubbles.join(' | '));
  const calls = await page.locator('.call-name').allTextContents();
  check('the tools it called are listed', calls.join(',') === 'shopify_find_order,shopify_order_detail', calls.join(','));
  const frame = page.frameLocator('iframe.frame');
  await frame.locator('.card').first().waitFor({ timeout: 15000 }).catch(() => {});
  const cards = await frame.locator('.card').count();
  check('the cards are drawn in their frame by CLIVE\'s own renderer', cards >= 1, cards);
  const height = await page.locator('iframe.frame').evaluate((f) => f.getBoundingClientRect().height);
  check('the frame is as tall as its cards', height > 120, height);
  const crit = await page.locator('.crit').count();
  check('the judge\'s six scores are shown, each with its reason', crit === 6, crit);
  await shot(page, 'phone-04-result-top');
  await shot(page, 'phone-05-result-full', true);
  await fits(page, 'phone', 'a result');

  // The bad actor's refund: waiting for the hold.
  await page.goto(`${BASE}/bench#run=${runId}&q=q001`, { waitUntil: 'domcontentloaded' });
  await ready(page);
  const staged = await page.locator('.staged').allTextContents();
  check('the bad actor\'s refund is staged and waiting for the hold', staged.length === 1 && /Waiting for the hold: refund_create \(RED/.test(staged[0]) && /pending/.test(staged[0]), staged.join(' | '));
  await shot(page, 'phone-06-bad-actor', true);

  // Rate it 4 with a note.
  await page.locator('.seg button', { hasText: '4' }).click();
  await page.locator('textarea.note').fill('Right call. Could say who can approve it.');
  await page.locator('.btn.primary', { hasText: 'Save rating' }).click();
  await page.waitForFunction(() => /Saved: you said 4/.test(document.querySelector('.saved').textContent), null, { timeout: 10000 }).catch(() => {});
  const saved = await page.locator('.saved').textContent();
  check('the rating is saved and said beside the judge\'s', /Saved: you said 4, the judge said 5\./.test(saved), saved);
  await shot(page, 'phone-07-rated');

  await page.goto(`${BASE}/bench#run=${runId}`, { waitUntil: 'domcontentloaded' });
  await ready(page);
  const after = await page.locator('#summary').textContent();
  check('the run counts the rating', /1 rated by you/.test(after), after);
  const agreed = await page.locator('.group', { hasText: 'The judge and you' }).locator('.row-name').first().textContent().catch(() => '');
  check('the judge and George: how often they agree', /Agrees with you exactly on 0 of 1 you rated · within a point on 1 · scores higher than you 1 time/.test(agreed), agreed);
  check('the phone\'s console stayed clean', errors.length === 0, errors.join(' | '));
  await context.close();
}

async function tablet(browser) {
  const { context, page, errors } = await open(browser, 'tablet');
  await page.goto(`${BASE}/bench`, { waitUntil: 'domcontentloaded' });
  await ready(page);
  await page.locator('#view button.row').first().click();
  await moved(page, '#run=');
  await shot(page, 'tablet-01-run');
  await fits(page, 'tablet', 'a run');
  await page.locator('.group', { hasText: 'Rate these' }).locator('.row').first().click();
  await moved(page, '&q=');
  await shot(page, 'tablet-02-result');
  await fits(page, 'tablet', 'a result');
  check('the tablet\'s console stayed clean', errors.length === 0, errors.join(' | '));
  await context.close();
}

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CROOKS_CHROMIUM || undefined, args: ['--no-sandbox'] });
  try {
    await phone(browser);
    await tablet(browser);
  } catch (error) {
    check('the run finished', false, error && error.stack ? error.stack : error);
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ ok: checks.every((c) => c.ok), checks, shots }));
})();

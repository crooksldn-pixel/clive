/* The Builds screen's Research section in a real browser: a research file given, weighed, and answered.
 *
 *   node scripts/browser/research.js http://127.0.0.1:8765 FIXTURE_FILE [/path/to/screenshots]
 *
 * Driven by tests/test_research_browser.py, which starts the real backend on the golden world, with the
 * build loop behind a fake GitHub (tests/builds_fixture.py), an empty research store, and the model's one
 * answer scripted for the test document (tests/fixtures/research/test-research-note.md, which says on its
 * face that it is a test). Judged on what is on the glass, at a phone's size (390 x 844):
 *
 *   - the Builds screen carries a Research section after the builds that wait on him, saying no research is given yet,
 *     with a way to add it and what it reads;
 *   - the file given through that way is taken in, read and weighed while he watches: the document says
 *     it is read, with four recommendations, the first open;
 *   - each recommendation says what the research says, CLIVE's view with its reason and what it rests
 *     on, and offers Adopt, Park and Reject with CLIVE's marked;
 *   - Park and Reject are recorded and move the recommendation out of Waiting on you;
 *   - Adopt puts a build request's card in front of him on the conversation, waiting for his hold, and
 *     the Builds screen steps aside; reopened, the recommendation says its build request waits for his hold;
 *   - nothing is wider than the screen, every button is a finger's size, and no script errs.
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...] }.
 */
'use strict';

const { chromium } = require('playwright-core');
const path = require('path');

const BASE = (process.argv[2] || 'http://127.0.0.1:8765').replace(/\/$/, '');
const FILE = process.argv[3] || '';
const OUT = process.argv[4] || '';
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const PHONE = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3 };

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });

async function shot(page, name) {
  if (!OUT) return;
  const file = path.join(OUT, `${name}.png`);
  await page.waitForTimeout(450);
  await page.screenshot({ path: file, animations: 'disabled' });
  shots.push(path.basename(file));
}

async function openBuilds(page) {
  await page.locator('#alpha-home .alpha-tools .alpha-row[data-alpha="builds"]').click();
  await page.waitForSelector('.bd.is-open .rs', { timeout: 20000 });
  await page.waitForTimeout(600);
}

async function fits(page) {
  const wide = await page.evaluate(() => {
    const w = document.documentElement.clientWidth;
    return [...document.querySelectorAll('.rs *')].filter((n) => {
      const r = n.getBoundingClientRect();
      return r.width > 0 && r.right > w + 1 && !n.closest('details:not([open])');
    }).map((n) => n.className || n.tagName).slice(0, 5);
  });
  check('nothing in the Research section is wider than the screen', wide.length === 0, wide.join(', '));
  const small = await page.evaluate(() => [...document.querySelectorAll('.rs button, .rs summary, .rs .bd-ans')]
    .filter((n) => { const r = n.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.height < 43.5; })
    .map((n) => `${n.className || n.tagName}:${Math.round(n.getBoundingClientRect().height)}`).slice(0, 5));
  check('every button and row in it is at least a finger high', small.length === 0, small.join(', '));
}

// A recommendation by its title, opened, scrolled to its question.
async function recommendation(page, title) {
  const item = page.locator('.rs .rs-prop', { hasText: title }).first();
  if (!(await item.evaluate((n) => n.open))) await item.locator('.rs-sum').click();
  await item.locator('.bd-decision, .bd-chosen').first().scrollIntoViewIfNeeded();
  return item;
}

async function answer(page, title, label) {
  const item = await recommendation(page, title);
  await item.locator('.bd-ans', { hasText: label }).click();
  await item.locator('.bd-choose').click();
}

async function run(browser) {
  const context = await browser.newContext(Object.assign({ isMobile: true, hasTouch: true, extraHTTPHeaders: HEADERS }, PHONE));
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/\/speak|Failed to load resource/.test(m.text())) errors.push(m.text()); });
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key"}' }));
  await page.goto(`${BASE}/?startup=off`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#alpha-home .alpha-row[data-alpha="builds"]', { timeout: 20000 });
  await page.waitForTimeout(500);
  await openBuilds(page);

  const empty = await page.locator('.rs').textContent();
  check('the Builds screen carries a Research section that says none is given yet', /^Research/.test(empty) && /No research given yet/.test(empty), empty.slice(0, 160));
  check('it offers a way to add research, and says what it reads', /Add research/.test(empty) && /PDF, Word/.test(empty), '');
  const under = await page.evaluate(() => { const r = document.querySelector('.rs'); return r && r.previousElementSibling && r.previousElementSibling.className; });
  check('the section sits straight after the builds that wait on him', under === 'bd-group is-needs-you', under);
  await shot(page, 'research-01-empty');

  await page.setInputFiles('.rs .rs-file', FILE);
  await page.waitForFunction(() => /Read · 4 recommendations/.test((document.querySelector('.rs .rs-doc') || {}).textContent || ''), null, { timeout: 60000 });
  await page.waitForTimeout(500);
  const doc = await page.locator('.rs .rs-doc').first().textContent();
  check('the file given is taken in, read and weighed, and says so', /test-research-note\.md/.test(doc) && /Read · 4 recommendations/.test(doc), doc);
  const steel = await page.locator('.rs .rs-doc .rs-dot.is-steel').count();
  check('a document read carries a steel dot', steel === 1, String(steel));
  const summary = await page.locator('.rs .rs-summary').textContent();
  check('the section says four recommendations wait on him', /^4 recommendations from your research wait on you/.test(summary), summary);
  const titles = await page.$$eval('.rs .rs-prop .rs-title', (ts) => ts.map((t) => t.textContent));
  check('the four recommendations are listed, the one to adopt first', titles.length === 4 && /last checked/.test(titles[0]), titles.join(' | '));
  const firstOpen = await page.locator('.rs .rs-prop').first().evaluate((n) => n.open);
  check('the first that waits on him is open', firstOpen, '');
  await page.locator('.rs .rs-summary').scrollIntoViewIfNeeded();
  await shot(page, 'research-02-read');
  await fits(page);

  const api = await recommendation(page, 'Anthropic API');
  const apiWords = await api.textContent();
  check('a recommendation that breaks a rule says which, and that CLIVE’s own check set it',
    /CLIVE’s view: Reject/.test(apiWords) && /Breaks rule 5/.test(apiWords) && /own check of the map’s rules/.test(apiWords), apiWords.slice(0, 200));
  const rec = await api.locator('.bd-ans.is-recommended').textContent();
  check('CLIVE’s own view is the answer marked', /Reject/.test(rec) && /CLIVE recommends/.test(rec), rec);
  await shot(page, 'research-03-rule-check');

  const whatsapp = await recommendation(page, 'WhatsApp');
  const whatsappWords = await whatsapp.textContent();
  check('a recommendation that repeats an idea links it', /Already written down/.test(whatsappWords) && /IDEA-001/.test(whatsappWords), '');
  await answer(page, 'WhatsApp', 'Park');
  await page.waitForFunction(() => [...document.querySelectorAll('.rs .rs-group .rs-h3')].some((h) => /^Parked/.test(h.textContent)), null, { timeout: 15000 });
  check('Park is recorded and moves it to Parked', true, '');
  await answer(page, 'Anthropic API', 'Reject');
  await page.waitForFunction(() => [...document.querySelectorAll('.rs .rs-group .rs-h3')].some((h) => /^Rejected/.test(h.textContent)), null, { timeout: 15000 });
  const left = await page.locator('.rs .rs-summary').textContent();
  check('Reject is recorded, and two wait on him now', /^2 recommendations/.test(left), left);

  const adopt = await recommendation(page, 'last checked');
  const adoptWords = await adopt.textContent();
  check('the one to adopt says what building it would touch and what it rests on',
    /Building it would touch/.test(adoptWords) && /web\/connections\.js/.test(adoptWords) && /It rests on/.test(adoptWords), '');
  await shot(page, 'research-04-adopt');
  await answer(page, 'last checked', 'Adopt');
  await page.waitForSelector('.bd:not(.is-open)', { state: 'attached', timeout: 20000 });
  await page.waitForTimeout(900);
  const card = await page.locator('#cards').textContent().catch(() => '');
  check('Adopt puts the build request’s card in front of him, waiting for his hold',
    /File an engineering request/.test(card) && /last checked/i.test(card), card.slice(0, 240));
  const open = await page.locator('.bd.is-open').count();
  check('the Builds screen steps aside for the card', open === 0, String(open));
  await shot(page, 'research-05-card');

  await page.locator('#home-btn').click();
  await page.waitForSelector('#alpha-home .alpha-tools .alpha-row[data-alpha="builds"]', { state: 'visible', timeout: 20000 });
  await openBuilds(page);
  await page.locator('.rs .rs-group', { hasText: 'Adopted' }).locator('.rs-h3').click();
  const adopted = await recommendation(page, 'last checked');
  const adoptedWords = await adopted.textContent();
  check('reopened, the adopted one says its build request waits for his hold', /You chose Adopt/.test(adoptedWords) && /waits for your hold/.test(adoptedWords), adoptedWords.slice(0, 300));
  await shot(page, 'research-06-adopted');
  check('no script errors', errors.length === 0, errors.join(' | '));
  await context.close();
}

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CROOKS_CHROMIUM || undefined });
  try {
    await run(browser);
  } catch (e) {
    check('the run finished', false, e && e.stack ? e.stack : String(e));
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ ok: checks.every((c) => c.ok), checks, shots }));
})();

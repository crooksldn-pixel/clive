/* The Builds screen's Research section in a real browser once research is read as ideas (DEC-078).
 *
 *   node scripts/browser/research-ideas.js http://127.0.0.1:8765 EXPECTED_JSON [/path/to/screenshots]
 *
 * Why this exists: George's words (9 Oct 2026), "George should not need to review 113 recommendations"
 * and "DEC-018 should be capable of preventing implementation without preventing CLIVE from learning
 * that a direction is correct". The screen's own test draws the section from a payload; this one drives
 * the real page against the real backend, after a generation was synthesised and applied by the same
 * code the server's script runs, and answers three ideas the way he would.
 *
 * Driven by tests/test_research_ideas_browser.py, which starts the real backend on the golden world, with
 * the build loop behind a fake GitHub (tests/builds_fixture.py), and the model scripted from the invented
 * notes of tests/research_synthesis_fixture.py (never George's research). EXPECTED_JSON is the section as
 * the server built it before the page opened, so the page is held to the server's own words.
 *
 * Judged on what is on the glass, at a phone's size (390 x 844), then on a tablet's width (1024):
 *   - the section is in ideas mode: its summary, what the research says (its points, from → to, one line
 *     of counts), Needs you before every group, then the groups in Now / Next / Later / No date order,
 *     every idea drawn once, each row with a dot from the fixed table;
 *   - an idea opens on its plain-English view, then the four answers; DEC-018 is said only under When;
 *     Engineering detail is folded and holds the sources, each quote in quotation marks, and the history;
 *   - the documents say how many recommendations each gave, and what couldn't be placed, with why;
 *   - Not now, Not for CLIVE and Approve the work are each two steps (a tap picks, the button then says
 *     "Choose: …" and records); answered ideas leave Needs you; approving puts the build request's card
 *     in front of him and the screen steps aside; reopened, the idea says its request waits for his hold;
 *   - nothing is wider than the screen, every button and row is a finger's size, and no script errs.
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...], session }.
 */
'use strict';

const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const BASE = (process.argv[2] || 'http://127.0.0.1:8765').replace(/\/$/, '');
const EXPECTED = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const OUT = process.argv[4] || '';
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const PHONE = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true };
const TABLET = { viewport: { width: 1024, height: 1366 }, deviceScaleFactor: 2, isMobile: false };

// The three ideas he answers, by name (tests/research_synthesis_fixture.py), and the answer each gets.
const LATER = 'Adopt a workflow engine for it';
const NO = 'Send small refunds without a hold';
const GO = 'Work survives a restart';
const HELD = 'Supplier messages in one thread';

const checks = [];
const shots = [];
let session = '';
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });

async function shot(page, name) {
  if (!OUT) return;
  const file = path.join(OUT, `${name}.png`);
  await page.waitForTimeout(450);
  await page.screenshot({ path: file, animations: 'disabled' });
  shots.push(path.basename(file));
}

// Scrolled so `locator` sits just under the Home button, so each picture starts where it should.
async function toTop(locator) {
  await locator.evaluate((n) => {
    n.scrollIntoView({ block: 'start' });
    let s = n.parentElement;
    while (s && !(s.scrollHeight > s.clientHeight + 1 && /(auto|scroll)/.test(getComputedStyle(s).overflowY))) s = s.parentElement;
    (s || document.scrollingElement).scrollBy(0, -110);
  });
}

async function openBuilds(page) {
  await page.locator('#alpha-home .alpha-tools .alpha-row[data-alpha="builds"]').click();
  await page.waitForSelector('.bd.is-open .rs .rs-says', { timeout: 20000 });
  await page.waitForTimeout(600);
}

async function fits(page, size) {
  const wide = await page.evaluate(() => {
    const w = document.documentElement.clientWidth;
    return [...document.querySelectorAll('.rs *')].filter((n) => {
      const r = n.getBoundingClientRect();
      return r.width > 0 && r.right > w + 1 && !n.closest('details:not([open])');
    }).map((n) => n.className || n.tagName).slice(0, 5);
  });
  check(`at ${size}, nothing in the Research section is wider than the screen`, wide.length === 0, wide.join(', '));
  const small = await page.evaluate(() => [...document.querySelectorAll('.rs button, .rs summary, .rs .bd-ans')]
    .filter((n) => { const r = n.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.height < 43.5; })
    .map((n) => `${n.className || n.tagName}:${Math.round(n.getBoundingClientRect().height)}`).slice(0, 5));
  check(`at ${size}, every button and row in it is at least a finger high`, small.length === 0, small.join(', '));
}

// The group headings as drawn, in order: "Needs you (3)", "Next (1)", …, "Documents (4)".
const headings = (page) => page.$$eval('.rs > .rs-group > summary.rs-h3', (hs) => hs.map((h) => h.textContent));

// An idea by its name: its group unfolded and the idea opened, with taps, as he would.
async function idea(page, name) {
  const item = page.locator('.rs .rs-idea', { has: page.locator('.rs-title', { hasText: name }) }).first();
  const group = item.locator('xpath=ancestor::details[contains(concat(" ", @class, " "), " rs-group ")][1]');
  if (!(await group.evaluate((n) => n.open))) await group.locator('summary.rs-h3').first().click();
  if (!(await item.evaluate((n) => n.open))) await item.locator('summary.rs-sum').click();
  await item.locator('.bd-decision, .bd-chosen, .rs-earlier').first().scrollIntoViewIfNeeded();
  return item;
}

// Two steps: a tap picks the answer, the button then names it, and a second tap records it.
async function answer(page, name, label) {
  const item = await idea(page, name);
  const choose = item.locator('.bd-choose');
  const before = { disabled: await choose.isDisabled(), said: await choose.textContent() };
  await item.locator('.bd-ans', { hasText: label }).click();
  const picked = { disabled: await choose.isDisabled(), said: await choose.textContent() };
  check(`“${label}” is two steps: nothing can be sent before a pick, and the pick names itself on the button`,
    before.disabled && before.said === 'Pick an answer' && !picked.disabled && picked.said === `Choose: ${label}`,
    `${JSON.stringify(before)} → ${JSON.stringify(picked)}`);
  await choose.click();
}

function expectedIdeas() {
  return [...EXPECTED.needs_you, ...EXPECTED.groups.flatMap((g) => g.ideas)];
}

async function firstLook(page) {
  const summary = await page.locator('.rs .rs-summary').textContent();
  check('the Research section is in ideas mode, and says how many ideas from how many documents wait on him',
    summary === EXPECTED.summary && /^10 ideas from 4 documents; 3 wait on you\.$/.test(summary), summary);
  const points = await page.$$eval('.rs .rs-says .rs-point', (ps) => ps.map((p) => p.textContent));
  check('What your research says: the server’s own points, in order', points.length === 4
    && JSON.stringify(points) === JSON.stringify(EXPECTED.synthesis.points), points.join(' | '));
  const ba = await page.locator('.rs .rs-says .rs-ba').textContent();
  check('it says where CLIVE goes if we build what the research agrees on, from the line before to the line after',
    ba === `If we build what it agrees on, CLIVE goesFrom${EXPECTED.synthesis.before}To${EXPECTED.synthesis.after}`, ba);
  const counts = await page.locator('.rs .rs-says .rs-counts').textContent();
  check('one line of counts, every number the server’s', counts === '17 recommendations from 4 documents became 10 ideas. '
    + '3 are backed by more than one report; 2 have disagreement. 4 confirm CLIVE’s direction; 3 change CLIVE’s understanding. '
    + '1 recommendation couldn’t be placed.', counts);
  const heads = await headings(page);
  check('Needs you comes first, then Next, Later and No date (Now holds only an idea that needs him), then the documents',
    JSON.stringify(heads) === JSON.stringify(['Needs you (3)', 'Next (1)', 'Later (4)', 'No date (2)', 'Documents (4)']), heads.join(' | '));
  const drawn = await page.$$eval('.rs .rs-idea .rs-title', (ts) => ts.map((t) => t.textContent));
  const wanted = [...new Set(expectedIdeas().map((i) => i.name))];
  check('every idea is drawn exactly once', drawn.length === 10 && new Set(drawn).size === 10
    && wanted.every((n) => drawn.includes(n)), drawn.join(' | '));
  const dots = await page.$$eval('.rs .rs-idea', (items) => items.map((n) => [n.querySelector('.rs-title').textContent,
    n.querySelector('.bd-line .rs-dot').className]));
  const dot = Object.fromEntries(dots);
  check('each row carries a dot from the fixed table: amber needs his call, dim worth looking into, steel right direction',
    /is-amber/.test(dot[NO]) && /is-dim/.test(dot[LATER]) && /is-steel/.test(dot[GO]) && /is-steel/.test(dot[HELD]), JSON.stringify(dot));
  const row = await page.locator('.rs .rs-idea', { has: page.locator('.rs-title', { hasText: 'Each key shows when it was checked' }) })
    .locator('.rs-state').textContent();
  check('a row says its direction, how widely it is backed and how much it matters', row === 'Right direction · Backed by 2 of 4 · Useful', row);
}

async function anIdeaOpened(page) {
  const item = await idea(page, HELD);
  const order = await item.locator('.bd-body').evaluate((b) => [...b.children].map((n) => n.className.split(' ')[0]));
  const labels = await item.locator('.rs-view .bd-flabel').allTextContents();
  check('an idea opens on its plain-English view, then the four answers, the folded detail, then his choices',
    JSON.stringify(order) === JSON.stringify(['rs-view', 'rs-answers', 'bd-tech', 'bd-decision'])
      && JSON.stringify(labels) === JSON.stringify(['What it means', 'Today', 'After', 'A real example', 'Before → after', 'Why you’d care', 'When you’d notice']),
    `${order.join(', ')} | ${labels.join(', ')}`);
  const four = await item.locator('.rs-answers .rs-alabel').allTextContents();
  check('the four answers are four short lines', JSON.stringify(four) === JSON.stringify(['Direction', 'Already in CLIVE?', 'When', 'Work approved?']), four.join(', '));
  // Every idea on the page, opened or not: DEC-018 may only ever be said under When.
  const dec = await page.$$eval('.rs .rs-idea', (items) => items.map((n) => ({
    name: n.querySelector('.rs-title').textContent,
    lines: [...n.querySelectorAll('.rs-aline')].map((l) => [l.querySelector('.rs-alabel').textContent, l.textContent]),
    view: (n.querySelector('.rs-view') || {}).textContent || '',
  })));
  const elsewhere = dec.flatMap((d) => d.lines.filter(([label, said]) => label !== 'When' && /DEC-018/.test(said)).map(([label]) => `${d.name}: ${label}`)
    .concat(/DEC-018/.test(d.view) ? [`${d.name}: its view`] : []));
  const held = dec.find((d) => d.name === HELD).lines;
  const when = (held.find(([label]) => label === 'When') || [])[1] || '';
  const direction = (held.find(([label]) => label === 'Direction') || [])[1] || '';
  check('DEC-018 holds when, never whether: it is said only under When, and the direction it held is still right',
    elsewhere.length === 0 && /Held by DEC-018 /.test(when) && /^DirectionRight direction/.test(direction), elsewhere.join(', ') || `${direction} | ${when}`);
  const tech = item.locator('.rs-tech');
  const folded = !(await tech.evaluate((n) => n.open));
  await toTop(item);
  await shot(page, 'ideas-03-idea-opened');
  await tech.locator('summary.bd-techsum').click();
  const detail = await tech.evaluate((t) => ({
    labels: [...t.querySelectorAll('.bd-tk')].map((n) => n.textContent),
    quotes: [...t.querySelectorAll('.rs-source .rs-quote')].map((n) => n.textContent),
    history: [...t.querySelectorAll('.rs-hline')].map((n) => n.textContent),
  }));
  const quoted = detail.quotes.length > 0 && detail.quotes.every((q) => q.startsWith('“') && q.endsWith('”') && q.length > 20);
  check('Engineering detail is folded until tapped, and holds the sources, each quote in quotation marks',
    folded && detail.labels.some((l) => /^Sources \(\d+\)$/.test(l)) && quoted, `${folded} | ${detail.labels.join(', ')} | ${detail.quotes.join(' / ')}`);
  check('and the history, oldest first, one dated line each, with what the old screen said',
    detail.labels.some((l) => /^History \(\d+\)$/.test(l)) && detail.history.length >= 3
      && detail.history.every((h) => /^\d{1,2} [A-Z][a-z]{2}(?: \d{4})?: /.test(h)) && /^.+?: Created from /.test(detail.history[0])
      && detail.history.some((h) => /old screen: Park, DEC-018/.test(h)), detail.history.join(' / '));
  await toTop(tech);
  await shot(page, 'ideas-04-engineering-detail');
}

async function documents(page) {
  const group = page.locator('.rs > .rs-group.is-documents');
  if (!(await group.evaluate((n) => n.open))) await group.locator('summary.rs-h3').first().click();
  const alpha = group.locator('.rs-doc', { has: page.locator('.rs-docname', { hasText: 'test-note-alpha.md' }) });
  const line = await alpha.locator('.rs-docline').textContent();
  check('each document says how many recommendations it gave and that they are in the ideas',
    /^8 recommendations read · Absorbed into the ideas/.test(line), line);
  await alpha.locator('summary.rs-docsum').click();
  const body = await alpha.locator('.rs-docbody').textContent();
  check('what couldn’t be placed is listed under the document, with why',
    /Couldn’t place \(1\)/.test(body) && /Send invoices by carrier pigeon: when CLIVE asked again for the exact passage/.test(body), body.slice(0, 300));
  await alpha.scrollIntoViewIfNeeded();
  await shot(page, 'ideas-05-documents');
}

async function answers(page) {
  await page.locator('.rs .rs-summary').scrollIntoViewIfNeeded();
  await answer(page, LATER, 'Not now');
  await page.waitForFunction(() => /^Needs you \(2\)$/.test((document.querySelector('.rs > .rs-group > summary.rs-h3') || {}).textContent || ''), null, { timeout: 15000 });
  const later = await idea(page, LATER);
  const laterWords = await later.textContent();
  const laterGroup = await later.evaluate((n) => n.closest('.rs-group').querySelector('summary').textContent);
  check('Not now is recorded: the idea leaves Needs you for its own group, and says what he chose',
    /^No date/.test(laterGroup) && /You chose Not now/.test(laterWords), `${laterGroup} | ${laterWords.slice(-200)}`);
  await answer(page, NO, 'Not for CLIVE');
  await page.waitForFunction(() => /^Needs you \(1\)$/.test((document.querySelector('.rs > .rs-group > summary.rs-h3') || {}).textContent || ''), null, { timeout: 15000 });
  const no = await idea(page, NO);
  const noWords = await no.textContent();
  check('Not for CLIVE is recorded, and the idea says what he chose', /You chose Not for CLIVE/.test(noWords), noWords.slice(-200));
  await toTop(page.locator('.rs > .rs-group').first());
  await shot(page, 'ideas-06-answered');

  const go = await idea(page, GO);
  const goSays = await go.locator('.bd-ans', { hasText: 'Approve the work' }).textContent();
  check('before he approves, it says a build request is only prepared, waits for his hold, and goes out in CLIVE’s words',
    /Nothing is filed until you hold it/.test(goSays) && /never the research's own/.test(goSays), goSays);
  session = await page.evaluate(() => localStorage.getItem('crooks.session') || '');
  await answer(page, GO, 'Approve the work');
  await page.waitForSelector('.bd:not(.is-open)', { state: 'attached', timeout: 20000 });
  await page.waitForTimeout(900);
  const card = await page.locator('#cards').textContent().catch(() => '');
  check('Approve the work puts the build request’s card in front of him, waiting for his hold',
    /File an engineering request/.test(card) && new RegExp(GO, 'i').test(card), card.slice(0, 240));
  const open = await page.locator('.bd.is-open').count();
  check('the Builds screen steps aside for the card', open === 0, String(open));
  await shot(page, 'ideas-07-card');

  await page.locator('#home-btn').click();
  await page.waitForSelector('#alpha-home .alpha-tools .alpha-row[data-alpha="builds"]', { state: 'visible', timeout: 20000 });
  await openBuilds(page);
  const heads = await headings(page);
  check('with nothing waiting on him, the groups are Now, Next, Later and No date, in that order',
    JSON.stringify(heads) === JSON.stringify(['Now (1)', 'Next (2)', 'Later (4)', 'No date (3)', 'Documents (4)']), heads.join(' | '));
  const approved = await idea(page, GO);
  const row = await approved.locator('.rs-state').textContent();
  const words = await approved.locator('.bd-chosen').textContent();
  check('reopened, the approved idea is Ready, says its build request waits for his hold, and offers to prepare it again',
    /· Ready · You: Approve the work$/.test(row) && /You chose Approve the work/.test(words) && /waits for your hold on the card/.test(words)
      && /Prepare the build request again/.test(words), `${row} | ${words}`);
  await toTop(approved);
  await shot(page, 'ideas-08-approved');
}

async function tablet(browser) {
  const context = await browser.newContext(Object.assign({ hasTouch: true, extraHTTPHeaders: HEADERS }, TABLET));
  const page = await context.newPage();
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key"}' }));
  await page.goto(`${BASE}/?startup=off`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#alpha-home .alpha-row[data-alpha="builds"]', { timeout: 20000 });
  await page.waitForTimeout(500);
  await openBuilds(page);
  await toTop(page.locator('.rs .rs-h2'));
  await shot(page, 'ideas-t1-section');
  const item = await idea(page, HELD);
  await item.locator('.rs-tech summary.bd-techsum').click();
  await toTop(item);
  await shot(page, 'ideas-t2-idea-opened');
  await fits(page, '1024 px');
  await context.close();
}

async function run(browser) {
  const context = await browser.newContext(Object.assign({ hasTouch: true, extraHTTPHeaders: HEADERS }, PHONE));
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/\/speak|Failed to load resource/.test(m.text())) errors.push(m.text()); });
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key"}' }));
  await page.goto(`${BASE}/?startup=off`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#alpha-home .alpha-row[data-alpha="builds"]', { timeout: 20000 });
  await page.waitForTimeout(500);
  await openBuilds(page);
  await toTop(page.locator('.rs .rs-h2'));
  await shot(page, 'ideas-01-section');
  await firstLook(page);
  await toTop(page.locator('.rs > .rs-group').first());
  await shot(page, 'ideas-02-needs-you');
  await anIdeaOpened(page);
  await fits(page, '390 px');
  await documents(page);
  await answers(page);
  check('no script errors', errors.length === 0, errors.join(' | '));
  await context.close();
}

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CROOKS_CHROMIUM || undefined });
  try {
    await run(browser);
    await tablet(browser);
  } catch (e) {
    check('the run finished', false, e && e.stack ? e.stack : String(e));
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ ok: checks.every((c) => c.ok), checks, shots, session }));
})();

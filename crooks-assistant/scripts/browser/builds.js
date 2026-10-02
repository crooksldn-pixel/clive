/* The Builds screen in a real browser, on the real build loop as it stood on 2 Oct 2026.
 *
 *   node scripts/browser/builds.js http://127.0.0.1:8765 [/path/to/screenshots]
 *
 * Driven by tests/test_builds_browser.py, which starts the real backend on the golden world with
 * the worker-01 loop's own status, request files and trunk facts behind a fake GitHub
 * (tests/builds_fixture.py), and scripts the model's one call for "What's being built?". Judged on
 * what is on the glass, at a phone's size (390 x 844) and the tablet's (601 x 889):
 *
 *   - the home says builds wait on him and carries a Builds row; a tap on it opens the screen;
 *   - the screen lists the builds that need him first, then the stopped, then the live, each with
 *     its title, its road of five dots and where it is in words, and no SHA, branch or request id
 *     on the face; the technical details hold them;
 *   - a build that waits on him carries its question with three answers, one recommended; picking
 *     one and choosing records it, and the build then says what he chose;
 *   - "What's being built?" asked of CLIVE opens the screen; Home closes it;
 *   - nothing is wider than the screen, every button is a finger's size, and with motion turned
 *     down nothing breathes.
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
  phone: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3 },
  tablet: { viewport: { width: 601, height: 889 }, deviceScaleFactor: 1.33 },
};
const ASK = "What's being built?";
const HEX = /\b[0-9a-f]{7,40}\b/;

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });

async function open(browser, size, extra) {
  const context = await browser.newContext(Object.assign({ isMobile: true, hasTouch: true, extraHTTPHeaders: HEADERS }, SIZES[size], extra || {}));
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/\/speak|Failed to load resource/.test(m.text())) errors.push(m.text()); });
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key"}' }));
  return { context, page, errors };
}

async function shot(page, name, full) {
  if (!OUT) return;
  const file = path.join(OUT, `${name}.png`);
  await page.waitForTimeout(450);
  await page.screenshot({ path: file, animations: 'disabled', fullPage: Boolean(full) });
  shots.push(path.basename(file));
}

async function home(page) {
  await page.goto(`${BASE}/?startup=off`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#alpha-home .alpha-row[data-alpha="builds"]', { timeout: 20000 });
  // The builds row's counts arrive after the objectives; wait for the row in Needs you.
  await page.waitForFunction(() => document.querySelectorAll('#alpha-home .alpha-row[data-alpha="builds"]').length >= 2, null, { timeout: 20000 })
    .catch(() => {});
  await page.waitForTimeout(500);
}

async function screenOpen(page) {
  await page.waitForSelector('.bd.is-open .bd-build', { timeout: 20000 });
  await page.waitForTimeout(600);
}

// What the face of every build says: the summaries only, never what is behind a disclosure.
async function faceText(page) {
  return page.$$eval('.bd .bd-sum, .bd .bd-hello, .bd .bd-h2', (nodes) => nodes.map((n) => n.textContent).join('\n'));
}

async function fits(page, size) {
  const wide = await page.evaluate(() => {
    const w = document.documentElement.clientWidth;
    return [...document.querySelectorAll('.bd *')].filter((n) => {
      const r = n.getBoundingClientRect();
      return r.width > 0 && r.right > w + 1 && !n.closest('details:not([open])');
    }).map((n) => n.className && n.className.baseVal === undefined ? n.className : n.tagName).slice(0, 5);
  });
  check(`${size}: nothing on the Builds screen is wider than the screen`, wide.length === 0, wide.join(', '));
  const small = await page.evaluate(() => [...document.querySelectorAll('.bd button, .bd summary, .bd .bd-ans')]
    .filter((n) => { const r = n.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.height < 43.5; })
    .map((n) => `${n.className || n.tagName}:${Math.round(n.getBoundingClientRect().height)}`).slice(0, 5));
  check(`${size}: every button and row on it is at least a finger high`, small.length === 0, small.join(', '));
}

async function phone(browser) {
  const { context, page, errors } = await open(browser, 'phone');
  await home(page);
  const homeRows = await page.$$eval('#alpha-home .alpha-row[data-alpha="builds"]', (rows) => rows.map((r) => r.textContent));
  check('the home says builds wait on his answer, in Needs you', homeRows.some((t) => /builds? waits? on your answer/.test(t)), homeRows.join(' | '));
  check('the home carries a Builds row with the board\'s summary', homeRows.some((t) => /^Builds/.test(t) && /need you/.test(t)), homeRows.join(' | '));
  await shot(page, 'phone-01-home');

  await page.locator('#alpha-home .alpha-tools .alpha-row[data-alpha="builds"]').click();
  await screenOpen(page);
  await shot(page, 'phone-02-builds-top');
  const groups = await page.$$eval('.bd .bd-h2', (hs) => hs.map((h) => h.textContent));
  check('the groups come in his order: needs you, stopped, live', groups.join(',') === 'Needs you,Stopped,Live', groups.join(','));
  const face = await faceText(page);
  check('no SHA on the face of any build', !HEX.test(face), (face.match(HEX) || [''])[0]);
  check('no branch name or request id on the face', !/clive\/|claude\/|status-publishes-findings|skill-read-runtime-tool/.test(face), '');
  check('every build has a title', !/Title not read/.test(face), '');
  const needs = await page.$$eval('.bd .bd-group:first-of-type .bd-build', (b) => b.map((x) => x.querySelector('.bd-title').textContent));
  check('the two builds that wait on him are first', needs.length === 2, needs.join(' | '));
  const roads = await page.$$eval('.bd-build', (b) => b.map((x) => x.querySelectorAll('.bd-sum .bd-road .bd-n').length));
  check('each build carries its road of five stages', roads.length > 0 && roads.every((n) => n >= 5), roads.slice(0, 6).join(','));
  const states = await page.$$eval('.bd .bd-state', (s) => s.map((x) => x.textContent));
  check('where each build is is said in words, with when', states.every((t) => /, (started|stopped|filed|finished|landed|approved|sent for review) /.test(t)), states.slice(0, 4).join(' | '));
  await fits(page, 'phone');

  // The first build that waits on him, open: why it stopped, the question, what it's for.
  const first = page.locator('.bd .bd-group').first().locator('.bd-build').first();
  await first.locator('.bd-decision').scrollIntoViewIfNeeded();
  await page.evaluate(() => { const s = document.querySelector('.bd-scroll'); s.scrollTop = Math.max(0, s.scrollTop - 220); });
  await shot(page, 'phone-03-why-and-question');
  const answers = await first.locator('.bd-ans').allTextContents();
  check('the question offers three answers, each saying what happens next', answers.length === 3 && answers.every((a) => a.length > 20), answers.join(' | '));
  const recommended = await first.locator('.bd-ans.is-recommended').count();
  check('one answer is marked recommended, with why', recommended === 1 && /Recommended: /.test(await first.locator('.bd-because').textContent()), '');
  const unread = await first.locator('.bd-muted').first().textContent();
  check('the review findings the loop keeps on the build server are said to be there, not guessed', /kept on the build server/.test(unread), unread);

  await first.locator('.bd-ans').first().click();
  const label = await first.locator('.bd-choose').textContent();
  check('picking an answer names it on the button', /^Choose: /.test(label), label);
  await first.locator('.bd-choose').scrollIntoViewIfNeeded();
  await shot(page, 'phone-04-answer-picked');
  await first.locator('.bd-choose').click();
  await page.waitForSelector('.bd-chosen', { timeout: 15000 });
  await page.waitForTimeout(500);
  const chose = await page.locator('.bd-chosen').first().textContent();
  check('his answer is recorded and shown on the build', /You chose /.test(chose), chose);
  const after = await page.$$eval('.bd .bd-h2', (hs) => hs.map((h) => h.textContent));
  check('the answered build leaves Needs you', after[0] === 'Needs you' && (await page.locator('.bd .bd-group').first().locator('.bd-build').count()) === 1, after.join(','));
  await page.locator('.bd-chosen').first().scrollIntoViewIfNeeded();
  await shot(page, 'phone-05-answer-recorded');
  await page.waitForSelector('.bd-flash[hidden]', { state: 'attached', timeout: 8000 }).catch(() => {});

  // A stopped build, opened, and its technical details: the only place a SHA appears.
  const stopped = page.locator('.bd .bd-build.is-stopped').first();
  await stopped.locator('.bd-sum').click();
  await stopped.locator('.bd-sum').scrollIntoViewIfNeeded();
  await shot(page, 'phone-06-stopped-open');
  await stopped.locator('.bd-tech > .bd-techsum').click();
  const tech = await stopped.locator('.bd-tech').first().textContent();
  check('the technical details hold the request, its branch and its commit', /clive\/objective\//.test(tech) && HEX.test(tech), '');
  await stopped.locator('.bd-tech').first().scrollIntoViewIfNeeded();
  await shot(page, 'phone-07-technical-details');

  // The live builds: five, then all of them on a tap.
  const more = page.locator('.bd-more');
  check('live builds show five first, with a way to see them all', (await more.count()) === 1, '');
  await more.click();
  await page.waitForTimeout(300);
  const live = await page.locator('.bd .bd-group:last-of-type .bd-build').count();
  check('all the live builds are listed on a tap', live > 5, String(live));
  await page.locator('.bd .bd-group:last-of-type .bd-h2').scrollIntoViewIfNeeded();
  await shot(page, 'phone-08-live');

  await page.locator('.bd-back').click();
  await page.waitForTimeout(600);
  check('Home closes the screen', !(await page.locator('.bd.is-open').count()), '');

  // Asking CLIVE opens it.
  await page.locator('#ask-bar').click();
  await page.fill('#alpha-input', ASK);
  await page.keyboard.press('Enter');
  try { await screenOpen(page); check('asking "What\'s being built?" opens the screen', true, ''); } catch (e) {
    check('asking "What\'s being built?" opens the screen', false, e.message);
  }
  await shot(page, 'phone-09-asked');
  check('no script errors on the phone', errors.length === 0, errors.join(' | '));
  await context.close();
}

async function tablet(browser) {
  const { context, page, errors } = await open(browser, 'tablet');
  await home(page);
  await page.locator('#alpha-home .alpha-tools .alpha-row[data-alpha="builds"]').click();
  await screenOpen(page);
  await shot(page, 'tablet-01-builds');
  await fits(page, 'tablet');
  check('no script errors on the tablet', errors.length === 0, errors.join(' | '));
  await context.close();
}

async function still(browser) {
  const { context, page } = await open(browser, 'phone', { reducedMotion: 'reduce' });
  await home(page);
  await page.locator('#alpha-home .alpha-tools .alpha-row[data-alpha="builds"]').click();
  await screenOpen(page);
  const moving = await page.$$eval('.bd .bd-n', (ns) => ns.filter((n) => getComputedStyle(n).animationName !== 'none').length);
  check('with motion turned down, nothing on the screen breathes', moving === 0, String(moving));
  await context.close();
}

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CROOKS_CHROMIUM || undefined });
  try {
    await phone(browser);
    await tablet(browser);
    await still(browser);
  } catch (e) {
    check('the run finished', false, e && e.stack ? e.stack : String(e));
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ ok: checks.every((c) => c.ok), checks, shots }));
})();

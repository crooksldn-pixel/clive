/* The walk: every screen George uses, as he would reach it, at a phone and both ways up a tablet.
 *
 *   python scripts/browser/walk.py <folder for the pictures>      (serves the worlds and runs this)
 *
 * Why this exists. George, 7 October: "check everything we have built into CLIVE and that it works
 * as intended, the objectives screens work etc." The browser gates each judge one subject at the
 * sizes it was built for; nothing walked the whole of it, by touch, at the three sizes he holds it:
 * a phone (390 x 844), the tablet upright (800 x 1280) and the tablet on its side (1280 x 800). This
 * does, and takes a picture of every stop for a person to look at.
 *
 * What it promises. Every stop is reached the way a finger reaches it (a tap on a row, the dock, a
 * double-tap, two fingers pinched, a sentence typed into the bar), never by drawing a payload. At
 * every stop it records, as checks: the stop was reached (its own selector is on the glass), no
 * script error, nothing wider than the screen, and no text pushed off either side. It judges
 * nothing else; the pictures are for a person. Nothing here writes outside the folder it is given.
 *
 * `world` is `main` (the golden world with objectives, Builds, the team and a screen) or `returns`
 * (CROOKS Returns beside the customers' shop). Prints one JSON object as its last line; a line with
 * `do` in it is a request to the runner (approve a screen, put something on it), answered on stdin.
 */
'use strict';

const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
const WORLD = process.argv[4] || 'main';
const OWNER = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const STAFF = { 'Tailscale-User-Login': 'mia@example.com', 'X-Forwarded-For': '100.64.0.21' };
const SIZES = [
  { name: 'phone', width: 390, height: 844, dpr: 3 },
  { name: 'tablet', width: 800, height: 1280, dpr: 1 },
  { name: 'landscape', width: 1280, height: 800, dpr: 1 },
];

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// [checker, 8 Oct 2026, review note N4] The one console error from /voice/live that is by design: its
// 503, with no ElevenLabs key in a fixture world (app/routes/voice.py). Any other, a 500, counts.
const voiceLiveByDesign = (from, said) => String(from).includes('/voice/live') && /\b503\b/.test(String(said));

// ---- the runner's side: a request a line, its answer a line (as scripts/browser/tv_flow.js asks)
const waiting = [];
const lines = readline.createInterface({ input: process.stdin });
lines.on('line', (line) => { const next = waiting.shift(); if (next) next(JSON.parse(line)); });
function ask(msg) {
  return new Promise((resolve) => { waiting.push(resolve); process.stdout.write(`${JSON.stringify(msg)}\n`); });
}

async function open(browser, size, headers) {
  const context = await browser.newContext({
    viewport: { width: size.width, height: size.height }, deviceScaleFactor: size.dpr,
    isMobile: true, hasTouch: true, extraHTTPHeaders: headers || OWNER, reducedMotion: 'reduce',
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const from = (m.location && m.location() && m.location().url) || '';
    // No voice in a fixture world: /speak and /voice/live answer 503 by design. /speak is this
    // file's own 503 (below); /voice/live is skipped only for its 503 (N4).
    if (from.includes('/speak') || voiceLiveByDesign(from, m.text())) return;
    errors.push(`console: ${m.text()}${from ? ` <- ${from.replace(BASE, '')}` : ''}`);
  });
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key","reason":"no voice under test"}' }));
  const cdp = await context.newCDPSession(page);
  return { context, page, errors, cdp };
}

// What a stop must show to be that stop, and the three things checked at every one.
async function stop(t, name, selector, opts) {
  const { page, errors, size } = t;
  const o = opts || {};
  await sleep(o.settle === undefined ? 500 : o.settle);
  const seen = await page.evaluate((sel) => {
    const el = sel ? document.querySelector(sel) : document.body;
    const b = el ? el.getBoundingClientRect() : null;
    const reached = Boolean(el && b && b.width > 0 && b.height > 0);
    const wide = document.scrollingElement.scrollWidth > innerWidth + 1;
    // Text pushed off either side: a visible element carrying its own words, outside the screen.
    const off = [];
    for (const node of document.querySelectorAll('body *')) {
      const own = Array.from(node.childNodes).some((c) => c.nodeType === 3 && c.textContent.trim());
      if (!own) continue;
      const r = node.getBoundingClientRect();
      if (r.width <= 1 || r.height <= 1) continue;
      const cs = getComputedStyle(node);
      if (cs.visibility === 'hidden' || Number(cs.opacity) === 0) continue;
      // Words read only by a screen reader (clipped to nothing), and words in a strip that scrolls
      // sideways on purpose (a tab strip with a fade at its edge), are where they are meant to be.
      if (cs.clip !== 'auto' && cs.clip !== '' || cs.clipPath && cs.clipPath !== 'none') continue;
      let strip = node.parentElement;
      while (strip && !/(auto|scroll)/.test(getComputedStyle(strip).overflowX)) strip = strip.parentElement;
      if (strip) continue;
      if (r.right > innerWidth + 2 || r.left < -2) off.push(`${node.tagName.toLowerCase()}.${String(node.className).split(' ')[0]} "${node.textContent.trim().slice(0, 30)}"`);
    }
    return { reached, wide, off: off.slice(0, 4) };
  }, selector || '');
  const label = `${size.name} · ${name}`;
  check(`${label} · reached`, seen.reached, selector || '');
  check(`${label} · no script error`, errors.length === 0, errors.slice(0, 3).join(' | '));
  errors.length = 0;
  check(`${label} · nothing wider than the screen`, !seen.wide, '');
  check(`${label} · no words pushed off the screen`, seen.off.length === 0, seen.off.join(' | '));
  if (OUT) {
    const file = `${WORLD === 'main' ? '' : `${WORLD}-`}${size.name}-${String(t.n).padStart(2, '0')}-${name}.png`;
    t.n += 1;
    await page.screenshot({ path: path.join(OUT, file), fullPage: Boolean(o.full), animations: 'disabled' });
    shots.push(file);
  }
  return seen.reached;
}

const centre = (page, sel, words) => page.evaluate(([s, w]) => {
  const el = Array.from(document.querySelectorAll(s)).find((n) => !w || (n.textContent || '').includes(w));
  if (!el) return null;
  el.scrollIntoView({ block: 'center', inline: 'nearest' });
  const b = el.getBoundingClientRect();
  if (!b.width || !b.height) return null;
  return { x: Math.round(b.x + b.width / 2), y: Math.round(b.y + Math.min(b.height / 2, 40)) };
}, [sel, words || '']);
async function tap(t, sel, words) {
  const at = await centre(t.page, sel, words);
  if (!at) return false;
  await sleep(250);   // a scroll into view settles before the finger lands
  await t.page.touchscreen.tap(at.x, at.y);
  return true;
}
async function doubleTap(t, at) {
  for (let i = 0; i < 2; i++) {
    await t.cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [at] });
    await sleep(40);
    await t.cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await sleep(110);
  }
}
// Two fingers, from `gap` apart to `to` apart, about a point: a pinch when `to` < `gap`.
async function pinch(t, at, gap, to) {
  const pts = (g) => [{ x: at.x - g / 2, y: at.y, id: 1 }, { x: at.x + g / 2, y: at.y, id: 2 }];
  await t.cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [pts(gap)[0]] });
  await sleep(30);
  await t.cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: pts(gap) });
  for (let i = 1; i <= 12; i++) {
    await t.cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: pts(gap + (to - gap) * i / 12) });
    await sleep(24);
  }
  await t.cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await sleep(900);
}
// A sentence typed into the bar, as he types one: tap the bar, type, send.
async function type(t, words) {
  await tap(t, '#ask-bar');
  await sleep(300);
  await t.page.fill('#alpha-input', words);
  await t.page.press('#alpha-input', 'Enter');
  await t.page.waitForFunction(() => document.querySelectorAll('#cards .card').length > 0, null, { timeout: 15000 }).catch(() => {});
  await sleep(900);
}
const distance = (page) => page.evaluate(() => document.body.getAttribute('data-distance') || '');
const home = async (t) => {
  await t.page.goto(`${BASE}/?startup=off`, { waitUntil: 'domcontentloaded' });
  await t.page.waitForSelector('#alpha-home .alpha-row', { timeout: 15000 }).catch(() => {});
  await sleep(700);
};

// ---- the main world
async function mainWalk(browser, size) {
  const t = { ...(await open(browser, size)), size, n: 1 };
  const { page } = t;
  await home(t);
  await stop(t, 'home', '#alpha-home .alpha-row');
  await page.evaluate(() => {
    let el = document.querySelector('#alpha-home');
    while (el && el.scrollHeight <= el.clientHeight + 2) el = el.parentElement;
    if (el) el.scrollTop = el.scrollHeight;
  });
  await stop(t, 'home-end', '#alpha-home .alpha-tools');
  await home(t);

  // Objectives: one of each shape, by a tap on its row.
  for (const [name, title] of [['objective-project', 'AW drop'], ['objective-tasks', 'Rosa and Kit'], ['objective-number', 'Shift the Convict Hoodies']]) {
    const row = await page.evaluate((words) => {
      const r = Array.from(document.querySelectorAll('#alpha-home .alpha-row[data-objective]')).find((n) => n.textContent.includes(words));
      return r ? r.dataset.objective : '';
    }, title);
    if (!row) { check(`${size.name} · ${name} · a row on the home`, false, `no row with "${title}"`); continue; }
    await tap(t, `#alpha-home .alpha-row[data-objective="${row}"]`);
    await page.waitForSelector('#alpha-sheet[open] .alpha-sheet-head', { timeout: 8000 }).catch(() => {});
    await stop(t, name, '#alpha-sheet[open] .alpha-sheet-head', { settle: 900 });
    if (name === 'objective-project') {
      // Double-tap a stage: it becomes the one it is at now (the design's gesture).
      const step = await centre(page, '#alpha-sheet[open] .oc-step:not(.is-current)');
      if (step) {
        await doubleTap(t, step);
        await sleep(900);
        await stop(t, 'objective-double-tap-stage', '#alpha-sheet[open] .oc-step.is-current');
      } else check(`${size.name} · objective-double-tap-stage · a stage to double-tap`, false, 'no stage that is not current');
      // Pinch on the sheet closes it to the home.
      const head = await centre(page, '#alpha-sheet[open] .alpha-sheet-head');
      if (head) await pinch(t, { x: Math.round(size.width / 2), y: head.y + 160 }, 260, 110);
      check(`${size.name} · a pinch on an objective closes it to the home`, !(await page.evaluate(() => document.querySelector('#alpha-sheet').open)), await distance(page));
      if (await page.evaluate(() => document.querySelector('#alpha-sheet').open)) await page.evaluate(() => document.querySelector('#alpha-sheet').close());
    } else {
      await page.evaluate(() => { const s = document.querySelector('#alpha-sheet'); if (s.open) s.close(); });
    }
    await sleep(500);
  }

  // The next six weeks: by its button, then by a pinch on the home, and back by a double-tap.
  if (await tap(t, '.hz-go')) {
    await stop(t, 'six-weeks', '#alpha-horizon:not([hidden])', { settle: 900 });
    const blank = await page.evaluate(() => { const b = document.querySelector('#alpha-horizon').getBoundingClientRect(); return { x: Math.round(b.x + b.width / 2), y: Math.round(b.bottom - 30) }; });
    await doubleTap(t, blank);
    await sleep(900);
    check(`${size.name} · a double-tap on the six weeks goes home`, (await distance(page)) === 'home', await distance(page));
  } else check(`${size.name} · six-weeks · the home's button`, false, 'no .hz-go');
  const hello = await centre(page, '#alpha-home .alpha-hello');
  if (hello) {
    await pinch(t, { x: Math.round(size.width / 2), y: hello.y + 120 }, 280, 120);
    await stop(t, 'pinch-to-six-weeks', '#alpha-horizon:not([hidden])');
    // One level out (about double the gap), below the rows: a spread further, or over a row, opens it.
    const below = await page.evaluate(() => {
      const rows = Array.from(document.querySelectorAll('#alpha-horizon .hz-row, #alpha-horizon [data-objective]'));
      const last = rows.length ? rows[rows.length - 1].getBoundingClientRect().bottom : innerHeight / 2;
      return Math.round(Math.min(innerHeight - 160, last + 90));
    });
    await pinch(t, { x: Math.round(size.width / 2), y: below }, 130, 250);
    check(`${size.name} · a spread on the six weeks comes home`, (await distance(page)) === 'home', await distance(page));
  }

  // Builds, from its row.
  await home(t);
  if (await tap(t, '#alpha-home .alpha-tools [data-alpha="builds"]')) {
    await sleep(1200);
    await page.waitForSelector('.bd.is-open .bd-build', { timeout: 15000 }).catch(() => {});
    await stop(t, 'builds', '.bd.is-open', { settle: 600 });
    await page.evaluate(() => { const s = document.querySelector('#alpha-sheet'); if (s && s.open) s.close(); });
  } else check(`${size.name} · builds · its row on the home`, false, '');

  // An order, typed; its customer, by a tap on the order card.
  await home(t);
  await type(t, 'show me order 1938');
  await stop(t, 'order', '#cards .card-order, #cards [data-type="order"], #cards [data-workspace="order"]');
  // The order's Customer tab, then the customer's name on it, which opens her.
  if (await tap(t, '#cards [role="tab"]', 'Customer')) await sleep(500);
  if (await tap(t, '#cards [data-kind="customer"][data-ref]')) {
    await page.waitForFunction(() => document.querySelector('#cards [data-type="customer"], #cards .card-customer, #cards [data-workspace="customer"]'), null, { timeout: 10000 }).catch(() => {});
    await stop(t, 'customer', '#cards [data-type="customer"], #cards .card-customer, #cards [data-workspace="customer"]', { settle: 900 });
  } else check(`${size.name} · customer · a way from the order to its customer`, false, 'no Customer tab or link');

  // Email, from the dock: who is waiting, then Mia's thread.
  await home(t);
  const docked = await tap(t, '.dock-btn[data-area="email"]');
  if (!docked) await type(t, 'which customers need replying to?');
  {
    await page.waitForSelector('#cards .row.tappable[data-kind="email_thread"]', { timeout: 10000 }).catch(() => {});
    await stop(t, 'email-waiting', '#cards .row.tappable[data-kind="email_thread"]', { settle: 700 });
    if (await tap(t, '#cards .row.tappable[data-kind="email_thread"][data-ref="aa70d3f83dbef06e"]')) {
      await page.waitForSelector('#cards .card-email_thread', { timeout: 10000 }).catch(() => {});
      await stop(t, 'email-thread', '#cards .card-email_thread', { settle: 700 });
    }
  }

  // Connections.
  await page.goto(`${BASE}/connections`, { waitUntil: 'domcontentloaded' });
  await sleep(1500);
  await stop(t, 'connections', 'main, #app, body');
  await stop(t, 'connections-whole', 'body', { full: true });
  await t.context.close();

  // /today, as Mia from the team.
  const staff = { ...(await open(browser, size, STAFF)), size, n: t.n };
  await staff.page.goto(`${BASE}/today`, { waitUntil: 'domcontentloaded' });
  await sleep(2200);
  await stop(staff, 'today-staff', 'main, body');
  t.n = staff.n;
  await staff.context.close();

  // /display, as a screen: named, approved with its code, then an order put on it.
  const tv = { ...(await open(browser, size)), size, n: t.n };
  await tv.page.goto(`${BASE}/display`, { waitUntil: 'domcontentloaded' });
  const named = await tv.page.waitForSelector('#namer:not([hidden])', { timeout: 30000 }).then(() => true, () => false);
  if (named) {
    await stop(tv, 'display-name-it', '#namer');
    const screenName = `Walk ${size.name}`;
    await tv.page.fill('#name-input', screenName);
    await tv.page.click('#name-save');
    const coded = await tv.page.waitForFunction(() => /^\d{3} \d{3}$/.test(document.getElementById('pair-code').textContent || ''), null, { timeout: 30000 }).then(() => true, () => false);
    if (coded) {
      await stop(tv, 'display-code', '#pair-code');
      const code = (await tv.page.textContent('#pair-code')).replace(/\D/g, '');
      const approved = await ask({ do: 'approve', name: screenName, code });
      check(`${size.name} · display · approved with its code`, approved.ok, JSON.stringify(approved).slice(0, 200));
      await sleep(4000);
      await stop(tv, 'display-approved', 'body');
      const shown = await ask({ do: 'show', name: screenName, view: 'order-b' });
      check(`${size.name} · display · an order put on it`, shown.ok, JSON.stringify(shown).slice(0, 200));
      await tv.page.waitForFunction(() => /2042/.test(document.body.textContent || ''), null, { timeout: 20000 }).catch(() => {});
      await stop(tv, 'display-order', 'body', { settle: 1500 });
    } else check(`${size.name} · display · a pairing code`, false, 'no code within 30s');
  } else check(`${size.name} · display · the naming step`, false, 'no #namer within 30s');
  await tv.context.close();
}

// ---- the returns world: the home's returns row, and what a tap on it draws
async function returnsWalk(browser, size) {
  const t = { ...(await open(browser, size)), size, n: 1 };
  await home(t);
  await t.page.waitForSelector('#alpha-home [data-alpha="returns"]', { timeout: 15000 }).catch(() => {});
  await stop(t, 'home', '#alpha-home [data-alpha="returns"]');
  if (await tap(t, '#alpha-home [data-alpha="returns"]')) {
    await t.page.waitForFunction(() => document.querySelectorAll('#cards .card').length > 0, null, { timeout: 15000 }).catch(() => {});
    await stop(t, 'returns-rows', '#cards .card', { settle: 1200 });
    await stop(t, 'returns-rows-whole', '#cards', { full: true });
  }
  await type(t, 'show me order 2202');
  await stop(t, 'order-with-return', '#cards .card', { settle: 900 });
  await t.context.close();
}

async function main() {
  if (OUT) fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  try {
    for (const size of SIZES) {
      try {
        if (WORLD === 'returns') await returnsWalk(browser, size);
        else await mainWalk(browser, size);
      } catch (e) {
        check(`${size.name} · the walk ran`, false, String((e && e.stack) || e).slice(0, 400));
      }
    }
  } finally {
    await browser.close();
  }
  const ok = checks.every((c) => c.ok);
  process.stdout.write(`${JSON.stringify({ ok, checks, shots })}\n`);
  lines.close();
  return ok ? 0 : 1;
}

main().then((code) => process.exit(code));

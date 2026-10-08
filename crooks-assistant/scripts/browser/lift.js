/* Round 12: hold a record and put it on a screen, with real fingers, against the real backend on
 * the golden fixture world (web/lift.js, app/displays/put.py).
 *
 *   CROOKS_LIFT_SCREENS='{"Office TV":{"id":"scr_…","key":"…"},"Packing screen":{…}}' \
 *     node scripts/browser/lift.js http://127.0.0.1:8765 /path/to/screenshots
 *
 * The screens are named and approved by the runner (tests/test_r12_lift_browser.py) as the owner
 * would, and each TV page here holds its own key as the cookie its browser was handed. Touches are
 * CDP touch events at measured pixels, as on the owner's tablet (601 × 889 at DPR 1.33) and phone
 * (390 × 844 at DPR 3); the mouse and the keyboard are Playwright's own. What is checked is what
 * George sees and what reaches CLIVE: the tray, the chip, the confirmation, the POST the drop makes
 * (and none when it is put back), and the TV at 1920 × 1080 drawing the order — and, since ruling 29
 * of DEC-071, an email he holds and drops there.
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...] }.
 */
'use strict';

const { chromium } = require('playwright-core');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
const SCREENS = JSON.parse(process.env.CROOKS_LIFT_SCREENS || '{}');
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const TABLET = { viewport: { width: 601, height: 889 }, deviceScaleFactor: 1.33, isMobile: true, hasTouch: true };
const PHONE = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true };
const DESK = { viewport: { width: 601, height: 889 }, deviceScaleFactor: 1.33, isMobile: false, hasTouch: false };

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function open(browser, kind, name, extra, query) {
  const context = await browser.newContext(Object.assign({ extraHTTPHeaders: HEADERS }, kind, extra || {}));
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const quiet = { refused: false, offline: false };
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const from = (m.location && m.location() && m.location().url) || '';
    if (from.includes('/speak') || /status of 503/.test(m.text())) return;
    // The refusal this script answers on purpose, below, is not the page's error.
    if (quiet.refused && /\/displays\/scr_[0-9a-f]{12}\/show$/.test(from)) return;
    if (quiet.offline && /\/displays$/.test(from)) return;
    errors.push(`console: ${m.text()}${from ? ` <- ${from}` : ''}`);
  });
  const posts = [];
  page.on('request', (r) => { if (r.method() === 'POST') posts.push({ path: r.url().replace(BASE, ''), body: r.postData() || '' }); });
  // What the checks read from inside the page: the non-passive touchmove listeners on the
  // document (the scroll guard must be there only during a gesture), and when a press went down,
  // began to rise and lifted.
  await page.addInitScript(() => {
    const guards = new Set();
    const add = EventTarget.prototype.addEventListener;
    const remove = EventTarget.prototype.removeEventListener;
    EventTarget.prototype.addEventListener = function (type, fn, options) {
      if (this === document && type === 'touchmove' && options && typeof options === 'object' && options.passive === false) guards.add(fn);
      return add.call(this, type, fn, options);
    };
    EventTarget.prototype.removeEventListener = function (type, fn, options) {
      if (this === document && type === 'touchmove') guards.delete(fn);
      return remove.call(this, type, fn, options);
    };
    window.__guards = () => guards.size;
    window.__times = {};
    add.call(document, 'pointerdown', () => { window.__times = { down: performance.now() }; }, true);
    new MutationObserver((records) => {
      for (const r of records) {
        const t = r.target;
        if (r.type === 'attributes' && t.classList && t.classList.contains('lift-priming') && !window.__times.prime) window.__times.prime = performance.now();
        for (const n of r.addedNodes || []) if (n.classList && n.classList.contains('lift-chip') && !window.__times.chip) window.__times.chip = performance.now();
      }
    }).observe(document, { attributes: true, attributeFilter: ['class'], subtree: true, childList: true });
  });
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key","reason":"no voice under test"}' }));
  await page.goto(`${BASE}/?startup=off${query || ''}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#ask-bar', { timeout: 15000 }).catch((e) => {
    throw new Error(`${e.message} (page errors: ${errors.join(' | ') || 'none'})`);
  });
  await sleep(900);
  const cdp = kind.hasTouch ? await context.newCDPSession(page) : null;
  const shot = async (file) => {
    if (!OUT) return;
    const where = path.join(OUT, `lift-${name}-${file}.png`);
    await page.screenshot({ path: where, fullPage: false });
    shots.push(path.basename(where));
  };
  const touch = (type, x, y) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x, y }] });
  const guards = () => page.evaluate(() => window.__guards());
  return { context, page, errors, posts, cdp, shot, touch, quiet, guards };
}

async function ask(t, words, selector) {
  await t.page.click('#ask-bar');
  await t.page.fill('#alpha-input', words);
  await t.page.press('#alpha-input', 'Enter');
  await t.page.waitForSelector(selector, { timeout: 15000 });
  await sleep(700);
}

const centre = (t, selector) => t.page.evaluate((sel) => {
  const node = typeof sel === 'string' ? document.querySelector(sel) : null;
  if (!node) return null;
  node.scrollIntoView({ block: 'center' });
  const r = node.getBoundingClientRect();
  return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2), w: r.width, h: r.height };
}, selector);

const tileNow = (t, name) => t.page.evaluate((n) => {
  const node = Array.from(document.querySelectorAll('.lift-screen')).find((b) => (b.querySelector('.lift-name') || {}).textContent === n);
  const tray = document.querySelector('.lift-tray');
  // Risen and at rest: the tray's own transition has ended (its transform is none again).
  if (!node || !tray || !tray.classList.contains('is-open') || getComputedStyle(tray).transform !== 'none') return null;
  const r = node.getBoundingClientRect();
  if (r.bottom > innerHeight) return null;
  return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2), over: node.classList.contains('is-over'),
    line: (node.querySelector('.lift-state') || {}).textContent || '' };
}, name);

// A screen's tile once the tray has risen and come to rest (on a loaded machine the rise can start
// late, and a tile read before it starts is below the screen): where it is, whether it is lit, and
// what its line says.
async function tile(t, name) {
  let last = null;
  for (let i = 0; i < 80; i++) {
    const now = await tileNow(t, name);
    if (now && last && now.x === last.x && now.y === last.y) return now;
    last = now;
    await sleep(100);
  }
  return last;
}

const tray = (t) => t.page.evaluate(() => {
  const node = document.querySelector('.lift-tray');
  const chip = document.querySelector('.lift-chip');
  return {
    open: Boolean(node && !node.hidden && node.classList.contains('is-open')),
    hidden: !node || node.hidden,
    mode: node ? node.dataset.mode || '' : '',
    done: Boolean(node && node.classList.contains('is-done')),
    words: ((document.querySelector('.lift-done-words') || {}).textContent || '').trim(),
    hint: ((document.querySelector('.lift-hint') || {}).textContent || '').trim(),
    note: ((document.querySelector('.lift-note') || {}).textContent || '').trim(),
    names: Array.from(document.querySelectorAll('.lift-screen .lift-name')).map((n) => n.textContent),
    chip: Boolean(chip),
    chipTitle: chip ? ((chip.querySelector('.lift-chip-title') || {}).textContent || '') : '',
    sources: document.querySelectorAll('.lift-source').length,
    say: ((document.querySelector('.lift-say') || {}).textContent || '').trim(),
    focus: document.activeElement ? (document.activeElement.className || document.activeElement.tagName) : '',
  };
});

async function screensNow(t) {
  return t.page.evaluate(async () => (await (await fetch('/displays', { cache: 'no-store' })).json()).screens || []);
}
const shows = (list, name) => (list.find((s) => s.name === name) || {}).showing || null;
const shownPosts = (t) => t.posts.filter((p) => /\/displays\/scr_[0-9a-f]{12}\/show$/.test(p.path));

// A finger held still on a point until it lifts and the tray has risen, then drawn onto the named
// screen's tile in steps; still down. Returns what was lifted and the tile it is over. `atRest`, when
// given, is called with the named tile once the tray is at rest, before the finger moves.
async function dragOnto(t, from, name, atRest) {
  await t.touch('touchStart', from.x, from.y);
  await sleep(640);
  const lifted = await tray(t);
  await sleep(420);
  const to = name ? await tile(t, name) : { x: from.x, y: 90 };
  if (atRest) await atRest(to);
  for (let i = 1; i <= 10; i++) {
    await t.touch('touchMove', Math.round(from.x + ((to.x - from.x) * i) / 10), Math.round(from.y + ((to.y - from.y) * i) / 10));
    await sleep(24);
  }
  return { lifted, over: name ? await litTile(t, name) : null };
}

// The named tile once it is lit (the page lights it on its next frame, late on a loaded machine).
async function litTile(t, name) {
  return (await waitFor(t, async () => { const x = await tileNow(t, name); return x && x.over ? x : null; }, 3000)) || tileNow(t, name);
}

async function waitFor(t, fn, ms) {
  const until = Date.now() + (ms || 6000);
  while (Date.now() < until) {
    const v = await fn();
    if (v) return v;
    await sleep(100);
  }
  return null;
}

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const office = SCREENS['Office TV'] || {};
  check('the runner named and approved the screens', office.id && (SCREENS['Packing screen'] || {}).id, JSON.stringify(Object.keys(SCREENS)));

  // The Office TV, on the wall and on: its own page, holding its own key as the cookie it was handed.
  // The Packing screen is not open anywhere, so it is off.
  const tv = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, extraHTTPHeaders: HEADERS });
  await tv.addCookies([{ name: 'clive_screen', value: office.key || '', url: `${BASE}/displays` }]);
  await tv.addInitScript((s) => { localStorage.setItem('clive.screen', JSON.stringify(s)); }, { id: office.id, name: 'Office TV' });
  const tvPage = await tv.newPage();
  const tvErrors = [];
  tvPage.on('pageerror', (e) => tvErrors.push(e.message));
  await tvPage.goto(`${BASE}/display`, { waitUntil: 'domcontentloaded' });
  await sleep(2500);

  // ===================================================================== the tablet, a finger
  const tab = await open(browser, TABLET, '601');
  await ask(tab, "show me today's orders", '#cards .card-order_list li.row.tappable[data-ref]');
  const row = '#cards .card-order_list li.row.tappable[data-ref]';
  const first = await centre(tab, row);
  const firstRef = await tab.page.evaluate((sel) => document.querySelector(sel).dataset.ref, row);
  const firstLabel = await tab.page.evaluate((sel) => document.querySelector(sel).dataset.label, row);

  // A flick is a scroll, not a hold: no tray, nothing posted.
  tab.posts.length = 0;
  const top0 = await tab.page.evaluate(() => document.getElementById('cards').scrollTop);
  await tab.touch('touchStart', first.x, first.y);
  for (let i = 1; i <= 6; i++) { await tab.touch('touchMove', first.x, first.y - i * 22); await sleep(16); }
  await tab.touch('touchEnd');
  await sleep(700);
  let now = await tray(tab);
  check('a flick on an order row lifts nothing and opens no tray', now.hidden && !now.chip && now.sources === 0 && !shownPosts(tab).length, JSON.stringify(now));
  check('after the flick no listener that could hold up a scroll is left on the page', (await tab.guards()) === 0, await tab.guards());
  const top1 = await tab.page.evaluate(() => ({ top: document.getElementById('cards').scrollTop, room: document.getElementById('cards').scrollHeight - document.getElementById('cards').clientHeight }));
  check('and the list scrolls as it did (when there is room to)', top1.room <= 0 || top1.top !== top0, JSON.stringify({ top0, top1 }));
  await tab.page.evaluate(() => { document.getElementById('cards').scrollTop = 0; });
  await sleep(300);

  // At rest, nothing on the page can hold up a scroll.
  check('at rest, no listener that could hold up a scroll is on the page', (await tab.guards()) === 0, await tab.guards());
  // Held for less than the hold: nothing yet — a thumb resting before it scrolls lifts nothing.
  const start = await centre(tab, row);
  await tab.touch('touchStart', start.x, start.y);
  await sleep(380);
  now = await tray(tab);
  check('a press held 380 ms lifts nothing yet', now.hidden && !now.chip, JSON.stringify(now));
  check('while the press waits, the scroll guard is on for this gesture', (await tab.guards()) === 1, await tab.guards());
  now = await waitFor(tab, async () => { const s = await tray(tab); return s.chip ? s : null; }, 4000) || await tray(tab);
  check('a still press lifts the order: the chip is under the finger and the row is dimmed', now.chip && now.sources === 1 && /^Order #\d+/.test(now.chipTitle), JSON.stringify(now));
  const times = await tab.page.evaluate(() => window.__times);
  check('the row begins to rise at 300 ms and lifts at 500 ms, not before',
    times.prime - times.down >= 290 && times.chip - times.down >= 490 && times.prime < times.chip,
    JSON.stringify({ rise: Math.round(times.prime - times.down), lift: Math.round(times.chip - times.down) }));
  await tab.shot('1-lift');
  await tile(tab, 'Office TV');
  now = await waitFor(tab, async () => { const s = await tray(tab); return s.names.length && s.note ? s : null; }, 8000) || await tray(tab);
  check('the Displays tray has risen with each approved screen, and not the one waiting for its code',
    now.open && now.mode === 'drag' && now.names.includes('Office TV') && now.names.includes('Packing screen') && !now.names.includes('Bedroom TV'),
    JSON.stringify(now));
  check('the tray says the one waiting for approval is waiting', /Waiting for approval: Bedroom TV/.test(now.note), now.note);
  check('the tray says what is being put up', now.hint === `Drop ${now.chipTitle} on a screen`, now.hint);
  const barAway = await tab.page.evaluate(() => getComputedStyle(document.querySelector('.alpha-composer')).pointerEvents);
  check('while the tray is up, the ask bar under it is put away', barAway === 'none', barAway);
  await tab.shot('2-tray');
  const target = await tile(tab, 'Office TV');
  for (let i = 1; i <= 10; i++) {
    await tab.touch('touchMove', Math.round(start.x + ((target.x - start.x) * i) / 10), Math.round(start.y + ((target.y - start.y) * i) / 10));
    await sleep(24);
  }
  const over = await litTile(tab, 'Office TV');
  check('over a screen, its tile lights and says what letting go does', over && over.over && over.line === 'Let go to show it here', JSON.stringify(over));
  const scrolled = await tab.page.evaluate(() => document.getElementById('cards').scrollTop);
  check('dragging did not scroll the list', scrolled === 0, scrolled);
  check('while dragging, the scroll guard is on for this gesture alone', (await tab.guards()) === 1, await tab.guards());
  await tab.shot('3-over');
  tab.posts.length = 0;
  await tab.touch('touchEnd');
  now = await waitFor(tab, async () => { const s = await tray(tab); return s.done ? s : null; }, 6000) || await tray(tab);
  const number = (firstLabel || '').split(' ')[0];
  check('let go over the Office TV, the tray says what went where',
    now.done && now.words === `Order ${number} is on the Office TV.`, JSON.stringify(now));
  const posted = shownPosts(tab);
  check('the drop is one POST naming the conversation and the order, and nothing else',
    posted.length === 1 && posted[0].path === `/displays/${office.id}/show`
      && JSON.stringify(Object.keys(JSON.parse(posted[0].body)).sort()) === '["kind","ref","session_id"]'
      && JSON.parse(posted[0].body).ref === firstRef && JSON.parse(posted[0].body).kind === 'order', JSON.stringify(posted));
  await tab.shot('4-done');
  let list = await screensNow(tab);
  check('CLIVE says the Office TV shows the order', shows(list, 'Office TV') === `Order ${number}`, JSON.stringify(list));
  await sleep(2600);
  now = await tray(tab);
  const barBack = await tab.page.evaluate(() => getComputedStyle(document.querySelector('.alpha-composer')).pointerEvents);
  check('then the tray settles away, the row is itself again and the ask bar is back', now.hidden && now.sources === 0 && !now.chip && barBack !== 'none',
    JSON.stringify({ now, barBack }));
  check('and the scroll guard is off again once the drag is over', (await tab.guards()) === 0, await tab.guards());

  // The TV, as it is on the wall.
  const onTv = await (async () => {
    const until = Date.now() + 25000;
    while (Date.now() < until) {
      const words = await tvPage.evaluate(() => (document.getElementById('ui') || document.body).innerText || '');
      if (words.includes(number.replace('#', '')) && /Priya|Mia|David/.test(words)) return words;
      await sleep(400);
    }
    return '';
  })();
  check('the TV at 1920 × 1080 draws the order that was dropped on it', Boolean(onTv), onTv.slice(0, 200));
  // The picture once the dots have finished forming it (slow on a shared machine).
  await waitFor({}, () => tvPage.evaluate(() => { const s = document.getElementById('status'); return !s || s.hidden; }), 40000);
  await sleep(1500);
  if (OUT) {
    await tvPage.screenshot({ path: path.join(OUT, 'lift-tv-1920-order.png') });
    shots.push('lift-tv-1920-order.png');
  }

  // Let go anywhere else: it goes back, and nothing is posted.
  const before = await screensNow(tab);
  tab.posts.length = 0;
  const second = await centre(tab, `${row}:nth-child(2)`);
  await dragOnto(tab, second, '');
  await tab.shot('5-away');
  await tab.touch('touchEnd');
  await sleep(700);
  now = await tray(tab);
  check('let go away from the tray, the order goes back and nothing is posted', now.hidden && now.sources === 0 && !now.chip && shownPosts(tab).length === 0,
    JSON.stringify({ now, posts: tab.posts.map((p) => p.path) }));
  check('put back, the scroll guard is off', (await tab.guards()) === 0, await tab.guards());
  list = await screensNow(tab);
  check('and the screens are as they were', ['Office TV', 'Packing screen'].every((n) => shows(list, n) === shows(before, n)),
    JSON.stringify({ before, list }));

  // Held and let go where it lifted: the tray stays, to tap a screen.
  const third = await centre(tab, `${row}:nth-child(3)`);
  const thirdLabel = await tab.page.evaluate((sel) => document.querySelector(sel).dataset.label, `${row}:nth-child(3)`);
  await tab.touch('touchStart', third.x, third.y);
  await sleep(640);
  await tab.touch('touchEnd');
  await sleep(600);
  now = await tray(tab);
  check('held and let go without dragging, the tray stays open to tap a screen', now.open && now.mode === 'pick' && /^Choose a screen for Order/.test(now.hint), JSON.stringify(now));
  check('the finger is off the glass, and so is the scroll guard, while the tray waits for a tap', (await tab.guards()) === 0, await tab.guards());
  await tab.shot('6-pick');
  // A refusal the server makes is said in its words, and the tray stays.
  tab.quiet.refused = true;
  await tab.page.route('**/displays/*/show', (r) => r.fulfill({ status: 403, contentType: 'application/json',
    body: JSON.stringify({ code: 'not_issued', detail: "That order wasn't shown in this conversation, so it can't go on a screen from here. Ask CLIVE for it, then hold it again." }) }));
  let packing = await tile(tab, 'Packing screen');
  await tab.page.touchscreen.tap(packing.x, packing.y);
  await sleep(700);
  now = await tray(tab);
  check('refused, the tray says why in CLIVE\'s words and stays open', now.open && now.mode === 'pick' && /wasn't shown in this conversation/.test(now.note), JSON.stringify(now));
  await tab.shot('7-refused');
  await tab.page.unroute('**/displays/*/show');
  tab.quiet.refused = false;
  // And slow: the tile says it is putting it up while CLIVE reads.
  await tab.page.route('**/displays/*/show', async (r) => { await sleep(1500); await r.continue(); });
  packing = await tile(tab, 'Packing screen');
  await tab.page.touchscreen.tap(packing.x, packing.y);
  await sleep(500);
  const busy = await tile(tab, 'Packing screen');
  check('while CLIVE reads, the tile says it is putting it up', busy && busy.line === 'Putting it up…', JSON.stringify(busy));
  await tab.shot('8-busy');
  now = await waitFor(tab, async () => { const s = await tray(tab); return s.done ? s : null; }, 8000) || await tray(tab);
  const thirdNumber = (thirdLabel || '').split(' ')[0];
  check('then it is on the Packing screen, which is off, and the tray says it goes up when it is next on',
    now.done && now.words === `Order ${thirdNumber} goes on the Packing screen when it’s next on.`, JSON.stringify(now));
  await tab.page.unroute('**/displays/*/show');
  await sleep(2600);

  // A quick tap is still a tap: the order opens, and no tray.
  tab.posts.length = 0;
  const tapAt = await centre(tab, row);
  await tab.page.touchscreen.tap(tapAt.x, tapAt.y);
  await tab.page.waitForSelector('#cards .card-order[data-ref]', { timeout: 10000 }).catch(() => null);
  await sleep(600);
  now = await tray(tab);
  check('a quick tap on a row still opens the order and lifts nothing', tab.posts.some((p) => p.path === '/command' && /open\.entity/.test(p.body)) && now.hidden && !now.chip,
    JSON.stringify({ posts: tab.posts.map((p) => p.path), now }));

  // The order card itself: held by its head and dropped on the Packing screen.
  await ask(tab, 'show me order 1938', '#cards .card-order[data-ref="gid://shopify/Order/1938"]');
  const head = await centre(tab, '#cards .card-order[data-ref="gid://shopify/Order/1938"] .card-head');
  const card = await dragOnto(tab, { x: head.x - 120, y: head.y }, 'Packing screen');
  check('an order card held by its head lifts as that order', card.lifted.chip && card.lifted.chipTitle === 'Order #1938' && card.over.over,
    JSON.stringify(card));
  await tab.shot('9-card-over');
  await tab.touch('touchEnd');
  now = await waitFor(tab, async () => { const s = await tray(tab); return s.done ? s : null; }, 6000) || await tray(tab);
  check('dropped on the Packing screen, it goes up there', now.done && now.words === 'Order #1938 goes on the Packing screen when it’s next on.', JSON.stringify(now));
  await sleep(2600);
  // A control inside the card keeps its own press: a tab held lifts nothing.
  const tabAt = await centre(tab, '#cards .card-order[data-ref="gid://shopify/Order/1938"] [role="tab"]');
  await tab.touch('touchStart', tabAt.x, tabAt.y);
  await sleep(700);
  now = await tray(tab);
  check('a tab inside the order card, held, lifts nothing', now.hidden && !now.chip && now.sources === 0, JSON.stringify(now));
  await tab.touch('touchEnd');
  await sleep(300);

  // An email goes up when he puts it there (ruling 29 of DEC-071, 8 October): held, it lifts as the
  // thread, and dropped on the Office TV it is drawn there from CLIVE's own read of it.
  await ask(tab, 'show me the email about 1939', '#cards .card-email_thread');
  const subject = await tab.page.evaluate(() => (document.querySelector('#cards .card-email_thread .card-title') || {}).textContent || '');
  const threadRef = await tab.page.evaluate(() => (document.querySelector('#cards .card-email_thread') || { dataset: {} }).dataset.ref || '');
  const mail = await centre(tab, '#cards .card-email_thread .msg-latest');
  tab.posts.length = 0;
  const email = await dragOnto(tab, mail, 'Office TV');
  check('held, an email lifts as the thread, named by its subject', email.lifted.chip && email.lifted.chipTitle === subject.slice(0, 80) && email.over && email.over.over,
    JSON.stringify({ email, subject }));
  await tab.shot('10-email-over');
  await tab.touch('touchEnd');
  now = await waitFor(tab, async () => { const s = await tray(tab); return s.done ? s : null; }, 8000) || await tray(tab);
  check('dropped on the Office TV, the email is up there', now.done && now.words === `${subject} is on the Office TV.`, JSON.stringify(now));
  const mailPosted = shownPosts(tab);
  check('the drop names the conversation and the thread by its id, and nothing of the email',
    mailPosted.length === 1 && JSON.stringify(Object.keys(JSON.parse(mailPosted[0].body)).sort()) === '["kind","ref","session_id"]'
      && JSON.parse(mailPosted[0].body).kind === 'email_thread' && JSON.parse(mailPosted[0].body).ref === threadRef && /^[0-9a-f]{6,}$/i.test(threadRef),
    JSON.stringify(mailPosted));
  list = await screensNow(tab);
  check('CLIVE says the Office TV shows the email', shows(list, 'Office TV') === subject, JSON.stringify(list));
  const mailOnTv = await waitFor({}, () => tvPage.evaluate(() => {
    const bodies = Array.from(document.querySelectorAll('#ui .cs-mail-body')).map((n) => n.textContent || '');
    const title = (document.querySelector('#ui .cs-h1') || {}).textContent || '';
    return bodies.length ? { bodies, title } : null;
  }), 25000);
  check('the TV at 1920 × 1080 draws the email, its subject and its words', mailOnTv && mailOnTv.title === subject && mailOnTv.bodies.every((b) => b.trim().length > 0),
    JSON.stringify(mailOnTv));
  const tvAttributes = await tvPage.evaluate(() => Array.from(document.querySelectorAll('#ui *')).flatMap((n) => Array.from(n.attributes).map((a) => a.value)).join(' '));
  check('and no attribute on the TV page carries anything of the email', !tvAttributes.includes(subject) && !tvAttributes.includes(threadRef), tvAttributes.slice(0, 200));
  await waitFor({}, () => tvPage.evaluate(() => { const s = document.getElementById('status'); return !s || s.hidden; }), 40000);
  await sleep(1500);
  if (OUT) {
    await tvPage.screenshot({ path: path.join(OUT, 'lift-tv-1920-email.png') });
    shots.push('lift-tv-1920-email.png');
  }
  await sleep(1200);

  // An objective's card in the conversation is held like an order's. With the email up on the Office
  // TV, the tablet's tile says so as text, and nothing in the tray carries it in an attribute (the
  // review of 8 October: the tile's aria-label carried the subject).
  await ask(tab, 'show me the autumn drop shoot', '#cards .card-objective[data-objective]');
  const goalCard = await centre(tab, '#cards .card-objective[data-objective] .card-head');
  let swept = null;
  const held = await dragOnto(tab, { x: goalCard.x - 100, y: goalCard.y }, 'Office TV', async (at) => {
    swept = await tab.page.evaluate(() => Array.from(document.querySelectorAll('.lift-tray, .lift-tray *, .lift-chip, .lift-chip *'))
      .flatMap((n) => Array.from(n.attributes).map((a) => `${a.name}=${a.value}`)));
    swept = { line: (at || {}).line || '', attributes: swept };
  });
  check('the tablet\'s Office TV tile says it shows the email, as text', swept && swept.line.includes(subject) && subject.length > 0, JSON.stringify(swept && swept.line));
  check('and no attribute on the tablet\'s tray carries anything of the email',
    swept && swept.attributes.length > 10 && !swept.attributes.some((a) => a.includes(subject) || a.includes(threadRef)),
    JSON.stringify(swept && swept.attributes.filter((a) => /aria-label|describedby/.test(a))));
  check('an objective\'s card in the conversation lifts as that objective', held.lifted.chip && held.lifted.chipTitle === 'Autumn drop shoot' && held.over && held.over.over,
    JSON.stringify(held));
  await tab.shot('11-objective-card');
  await tab.touch('touchEnd');
  now = await waitFor(tab, async () => { const s = await tray(tab); return s.done ? s : null; }, 6000) || await tray(tab);
  check('dropped on the Office TV, the objective is up there', now.done && now.words === 'Autumn drop shoot is on the Office TV.', JSON.stringify(now));
  list = await screensNow(tab);
  check('CLIVE says the Office TV shows the objective from the card', shows(list, 'Office TV') === 'Autumn drop shoot', JSON.stringify(list));
  await sleep(2600);
  check('the tablet page threw nothing', tab.errors.length === 0, tab.errors.join(' | '));
  await tab.context.close();

  // ===================================================================== the phone, an objective
  const phone = await open(browser, PHONE, '390');
  await phone.page.waitForSelector('#alpha-home [data-objective]', { timeout: 15000 });
  await sleep(600);
  const goal = await centre(phone, '#alpha-home [data-objective]');
  const goalTitle = await phone.page.evaluate(() => document.querySelector('#alpha-home [data-objective] .alpha-row-title').textContent);
  await phone.touch('touchStart', goal.x, goal.y);
  await sleep(640);
  await phone.shot('1-lift');
  await sleep(420);
  const officeTile = await tile(phone, 'Office TV');
  for (let i = 1; i <= 10; i++) {
    await phone.touch('touchMove', Math.round(goal.x + ((officeTile.x - goal.x) * i) / 10), Math.round(goal.y + ((officeTile.y - goal.y) * i) / 10));
    await sleep(24);
  }
  await sleep(160);
  await phone.shot('2-over');
  await phone.touch('touchEnd');
  now = await waitFor(phone, async () => { const s = await tray(phone); return s.done ? s : null; }, 6000) || await tray(phone);
  check('on the phone, an objective held on the home and dropped on the Office TV goes up', now.done && now.words === `${goalTitle} is on the Office TV.`, JSON.stringify(now));
  await phone.shot('3-done');
  list = await screensNow(phone);
  check('CLIVE says the Office TV shows the objective', shows(list, 'Office TV') === goalTitle, JSON.stringify(list));
  await sleep(2600);
  // Its sheet: opened with a tap, and held by its head. The tray rises inside the sheet, which stays.
  const rowAt = await centre(phone, '#alpha-home [data-objective]');
  await phone.page.touchscreen.tap(rowAt.x, rowAt.y);
  await phone.page.waitForSelector('#alpha-sheet[open] .alpha-sheet-head[data-objective]', { timeout: 10000 });
  await sleep(900);
  const sheetTitle = await phone.page.evaluate(() => document.querySelector('#alpha-sheet .alpha-sheet-head h2').textContent);
  const sheetHead = await centre(phone, '#alpha-sheet .alpha-sheet-head h2');
  const inSheet = await dragOnto(phone, sheetHead, 'Packing screen');
  const where = await phone.page.evaluate(() => Boolean(document.querySelector('#alpha-sheet .lift-tray')));
  check('an objective\'s sheet, held by its head, lifts it, with the tray inside the sheet',
    inSheet.lifted.chip && inSheet.lifted.chipTitle === sheetTitle && where && inSheet.over && inSheet.over.over, JSON.stringify({ inSheet, where }));
  await phone.shot('4-sheet-over');
  await phone.touch('touchEnd');
  now = await waitFor(phone, async () => { const s = await tray(phone); return s.done ? s : null; }, 6000) || await tray(phone);
  check('dropped on the Packing screen, it goes up there, and the sheet is still open',
    now.done && now.words === `${sheetTitle} goes on the Packing screen when it’s next on.`
      && await phone.page.evaluate(() => document.getElementById('alpha-sheet').open), JSON.stringify(now));
  await phone.shot('5-sheet-done');
  check('the phone page threw nothing', phone.errors.length === 0, phone.errors.join(' | '));
  await phone.context.close();

  // ===================================================================== a mouse, and the keyboard
  const desk = await open(browser, DESK, 'mouse');
  await ask(desk, "show me today's orders", '#cards .card-order_list li.row.tappable[data-ref]');
  const m = await centre(desk, row);
  await desk.page.mouse.move(m.x, m.y);
  await desk.page.mouse.down();
  await sleep(640);
  await sleep(420);
  const mTarget = await tile(desk, 'Office TV');
  await desk.page.mouse.move(mTarget.x, mTarget.y, { steps: 10 });
  const mOver = await litTile(desk, 'Office TV');
  now = await tray(desk);
  check('with a mouse, a held row lifts and the tile under the pointer lights', now.chip && mOver.over, JSON.stringify({ now, mOver }));
  check('a mouse never scrolls by dragging, so no scroll guard is put on for it', (await desk.guards()) === 0, await desk.guards());
  await desk.shot('1-over');
  await desk.page.mouse.up();
  now = await waitFor(desk, async () => { const s = await tray(desk); return s.done ? s : null; }, 6000) || await tray(desk);
  check('and let go, it is on the Office TV', now.done && /is on the Office TV\.$/.test(now.words), JSON.stringify(now));
  await sleep(2600);
  // The keyboard: the row focused, Shift+F10, the arrow keys and Enter.
  await desk.page.focus(row);
  await desk.page.keyboard.press('Shift+F10');
  await sleep(700);
  now = await tray(desk);
  check('Shift+F10 on a focused row opens the tray to choose, with the first screen focused', now.open && now.mode === 'pick' && /lift-screen/.test(now.focus), JSON.stringify(now));
  await desk.shot('2-keyboard');
  await desk.page.keyboard.press('Escape');
  await sleep(500);
  now = await tray(desk);
  const back = await desk.page.evaluate((sel) => document.activeElement === document.querySelector(sel), row);
  check('Escape puts it back and returns the focus to the row', now.hidden && back, JSON.stringify({ now, back }));
  await desk.page.keyboard.press('ContextMenu');
  await sleep(600);
  await desk.page.keyboard.press('ArrowDown');
  const named = await desk.page.evaluate(() => (document.activeElement.querySelector('.lift-name') || {}).textContent || '');
  await desk.page.keyboard.press('Enter');
  now = await waitFor(desk, async () => { const s = await tray(desk); return s.done ? s : null; }, 6000) || await tray(desk);
  check('the context-menu key, the arrow keys and Enter put it on the screen chosen', named === 'Packing screen' && now.done && /goes on the Packing screen when it’s next on\.$/.test(now.words), JSON.stringify({ named, now }));
  check('the mouse and keyboard page threw nothing', desk.errors.length === 0, desk.errors.join(' | '));
  await desk.context.close();

  // ===================================================================== reduced motion
  const calm = await open(browser, TABLET, 'calm', { reducedMotion: 'reduce' });
  await ask(calm, "show me today's orders", '#cards .card-order_list li.row.tappable[data-ref]');
  let c = await centre(calm, row);
  // CLIVE out of reach: the tray says so, and letting go puts the order back.
  calm.quiet.offline = true;
  await calm.page.route('**/displays', (r) => r.abort());
  await calm.touch('touchStart', c.x, c.y);
  await sleep(1200);
  let said = await calm.page.evaluate(() => ((document.querySelector('.lift-empty') || {}).textContent || '').trim());
  check('with CLIVE out of reach, the tray says the screens cannot be listed', said === 'CLIVE can’t be reached, so your screens can’t be listed.', said);
  await calm.touch('touchMove', c.x, 90);
  await calm.touch('touchEnd');
  await sleep(500);
  await calm.page.unroute('**/displays');
  calm.quiet.offline = false;
  // No screens at all: the tray says how to make one.
  await calm.page.route('**/displays', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '{"screens":[],"done":[]}' }));
  await calm.page.evaluate(() => { window.CliveLift.state().screensAt = 0; });
  await calm.touch('touchStart', c.x, c.y);
  await sleep(1200);
  said = await calm.page.evaluate(() => ((document.querySelector('.lift-empty') || {}).textContent || '').trim());
  check('with no screens yet, the tray says how to make one', /^No screens yet\. Open CLIVE’s address with \/display on a TV/.test(said), said);
  await calm.shot('1-no-screens');
  await calm.touch('touchMove', c.x, 90);
  await calm.touch('touchEnd');
  await sleep(500);
  await calm.page.unroute('**/displays');
  await calm.page.evaluate(() => { window.CliveLift.state().screensAt = 0; });
  c = await centre(calm, row);
  await calm.touch('touchStart', c.x, c.y);
  await sleep(640);
  const cTile = await tile(calm, 'Office TV');
  for (let i = 1; i <= 8; i++) { await calm.touch('touchMove', Math.round(c.x + ((cTile.x - c.x) * i) / 8), Math.round(c.y + ((cTile.y - c.y) * i) / 8)); await sleep(24); }
  await sleep(150);
  await calm.touch('touchEnd');
  now = await waitFor(calm, async () => { const s = await tray(calm); return s.done ? s : null; }, 6000) || await tray(calm);
  check('with reduced motion the same drag works, nothing travelling', now.done && /is on the Office TV\.$/.test(now.words), JSON.stringify(now));
  check('the reduced-motion page threw nothing', calm.errors.length === 0, calm.errors.join(' | '));
  await calm.context.close();

  check('the TV page threw nothing, all along', tvErrors.length === 0, tvErrors.join(' | '));
  await tv.close();
  // ===================================================================== iOS
  // WebKit decides as a touch begins whether the page may stop it scrolling, so there the guard is
  // on from the start (the one place it is).
  const iphone = await open(browser, PHONE, 'ios', { userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1' });
  check('with an iPhone\'s browser the scroll guard is on from the start', (await iphone.guards()) === 1, await iphone.guards());
  await iphone.context.close();

  // ===================================================================== a weak device
  // The tablet's own lite path (html[data-lite]: no blur) on a processor slowed four times.
  const weak = await open(browser, TABLET, 'lite', {}, '&lite=1');
  await weak.cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
  await ask(weak, "show me today's orders", '#cards .card-order_list li.row.tappable[data-ref]');
  const w = await centre(weak, row);
  const wDrag = await dragOnto(weak, w, 'Office TV');
  const lite = await weak.page.evaluate(() => ({ lite: document.documentElement.dataset.lite, blur: getComputedStyle(document.querySelector('.lift-tray')).backdropFilter }));
  check('on the lite path the tray is solid, not blurred', lite.lite === '1' && (lite.blur === 'none' || !lite.blur), JSON.stringify(lite));
  await weak.shot('1-over');
  await weak.touch('touchEnd');
  now = await waitFor(weak, async () => { const s = await tray(weak); return s.done ? s : null; }, 10000) || await tray(weak);
  check('slowed four times, the same drag still puts the order on the Office TV', wDrag.over && wDrag.over.over && now.done && /is on the Office TV\.$/.test(now.words),
    JSON.stringify({ over: wDrag.over, now }));
  check('the lite page threw nothing', weak.errors.length === 0, weak.errors.join(' | '));
  await weak.context.close();

  await browser.close();
  const ok = checks.every((x) => x.ok);
  console.log(JSON.stringify({ ok, checks, shots }));
}

main().catch((e) => {
  checks.push({ name: 'the run finished', ok: false, detail: String(e && e.stack || e).slice(0, 600) });
  console.log(JSON.stringify({ ok: false, checks, shots }));
  process.exit(0);
});

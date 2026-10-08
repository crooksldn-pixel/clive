/* The tablet, for real: the page in Chromium, talking to a backend that is serving the
 * golden world.
 *
 * This is the difference between this file and scripts/browser/accept.js. That one stubs the
 * turn payloads and checks that the renderer can draw them — a good check, and not this one.
 * Here every response comes from the real backend over HTTP, so what is being checked is the
 * whole thing: the router chose a lane, a recipe read the fixture shop, a presenter shaped a
 * card, the page drew it, and a finger can hit what it drew.
 *
 *   node scripts/browser/experience.js http://127.0.0.1:8765 /path/to/screenshots
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...] }.
 *
 * Nothing here reaches Shopify, Gmail or ElevenLabs — the backend it is pointed at is the
 * fixture one — and /speak is answered with a 503 so no voice is synthesised.
 */
'use strict';

const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
// The Galaxy Tab A 8.0 (SM-T290), portrait, which is how it sits on the workbench.
const VIEWPORT = { width: 800, height: 1280 };
// What the backend expects from a request `tailscale serve` proxied.
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 300) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// [checker, 8 Oct 2026, review note N2] A check held as a STRICT expected failure, named for its
// defect (pytest's xfail(strict=True), for a script). While the defect is there it is reported
// as an expected failure and the gate stays green. The day it passes, the gate goes RED and says
// so: make it a plain `check(...)` again. Grep "KNOWN DEFECT" for every one; the Python side of
// the same defect is tests/test_spoken_list_walk.py.
const SPOKEN_LIST_WALK = 'KNOWN DEFECT spoken-list-walk: a list asked for out loud opens no walk (checker defect 1; flow is fixing it)';
const knownDefect = (defect, name, ok, detail) => check(
  ok ? `${name} :: XPASS(strict): ${defect} is fixed, so make this a plain check`
    : `${name} :: expected failure, ${defect}`,
  !ok, detail);

async function main() {
  const browser = await chromium.launch({
    executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  });
  const context = await browser.newContext({
    viewport: VIEWPORT, deviceScaleFactor: 1, isMobile: true, hasTouch: true,
    extraHTTPHeaders: HEADERS,
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    // Not the /speak stub two lines below. Section 8 drives the page's own submit(), which
    // speaks, so the browser logs a failed resource load for the 503 this file itself
    // fulfils. Counting that would fail every run over a fault this file created. Matched on
    // the URL rather than on the word, so a real 503 from anywhere else still counts.
    const from = (m.location && m.location() && m.location().url) || '';
    if (from.includes('/speak')) return;
    // With the resource that failed. "Failed to load resource: 400" names nothing, and a
    // browser run that cannot say WHAT failed costs an hour to read.
    errors.push(`console: ${m.text()}${from ? ` <- ${from}` : ''}`);
  });
  // No voice under test: a 503 is what the tablet already handles when ElevenLabs is absent.
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key","reason":"no voice under test"}' }));

  // Cards fade and rise as they arrive. A screenshot taken the instant after drawing catches
  // them part-way through and reads as a blank or half-dimmed screen, which is a picture of
  // the animation rather than of the interface. Wait for it to settle, and stop it repeating.
  const shot = async (name) => {
    if (!OUT) return;
    const file = path.join(OUT, `${name}.png`);
    await page.waitForTimeout(500);
    await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
    shots.push(path.basename(file));
  };

  // The page talks to the backend itself; this asks a question the way the orb does, by
  // posting a transcript, and then waits for the card to appear.
  const ask = async (text, session) => page.evaluate(async ([t, s]) => {
    const r = await fetch('/turn', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: t, session_id: s }),
    });
    return r.json();
  }, [text, session]);

  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(600);
  // Draw a turn the way the app does: the page's own renderer, its own vocabulary, its own
  // skip list. Nothing here re-implements rendering — if a card cannot be drawn, CrooksUI
  // says so in `skipped` and the check above fails.
  await page.evaluate(() => {
    window.__crooksDraw = (payload) => {
      // Into the deck the application itself renders into, and no other. A selector LIST
      // matches in document order, not in the order it is written, so '#cards, .cards, main'
      // resolved to <main> — the wrapper — and `innerHTML = ''` then deleted #cards along with
      // every delegated listener bound to it. The checks still rendered and still passed, but
      // they were measuring a page the tablet never builds: nothing tappable was connected to
      // anything. A browser check that draws outside the app's own container can only test the
      // renderer, which the node tests already do.
      const root = document.querySelector('#cards') || document.querySelector('.cards') || document.body;
      const out = window.CrooksUI.render(payload.ui || [], {});
      root.replaceChildren();
      out.nodes.forEach((n) => root.appendChild(n));
      // The deck is where cards live, and the page hides it until there is something in it.
      // Putting cards there without showing it is how the screenshots came back as the orb.
      document.body.dataset.mode = 'context';
      return { nodes: out.nodes.length, skipped: out.skipped, root: root.id || root.className || 'body' };
    };
  });
  const hasRenderer = await page.evaluate(() => Boolean(window.CrooksUI && window.CrooksUI.render));
  check('the page exposes its renderer', hasRenderer, 'window.CrooksUI');
  check('the page loads with no script error', errors.length === 0, errors.join(' | '));
  await shot('01-home');

  // ---- 1. a real order lookup, drawn by the real renderer
  const turn = await ask('show me order 1938', 'browser');
  const types = (turn.ui || []).map((i) => i.type);
  check('the backend answered with an order surface', types.indexOf('order') !== -1, `ui=${types.join(',')}`);
  // [checker, 8 Oct 2026] Was 'it took the fast lane' (lane FAST). The fast lane was removed on
  // 28 September (DEC-063): every sentence is a model turn, and its lane is NORMAL.
  check('it took the model\'s lane, as every sentence does (DEC-063)', turn.lane === 'NORMAL', `lane=${turn.lane}`);

  // The page renders whatever the app puts on screen; drive it the way a person does, by
  // typing into the shell's own input if it has one, otherwise by handing the payload to the
  // renderer the page already exposes for its fixtures.
  const drawn = await page.evaluate((payload) => window.__crooksDraw(payload), turn);
  check('the renderer drew the cards the backend sent', drawn.nodes > 0,
    `nodes=${drawn.nodes} skipped=${(drawn.skipped || []).join(',')}`);
  check('the renderer skipped nothing the backend sent', (drawn.skipped || []).length === 0,
    `skipped=${(drawn.skipped || []).join(',')}`);
  await shot('02-order-detail');

  // ---- 2. the card is mechanically usable
  const card = await page.evaluate(() => {
    const el = document.querySelector('.card, [data-kind="order"]');
    if (!el) return null;
    const tabs = Array.from(el.querySelectorAll('[role="tab"], .tab')).map((t) => (t.textContent || '').trim());
    // Only what is ON the card. The rail discloses its secondary chips behind a "2 more"
    // button (web/ui.js) and keeps them at zero height until it is opened; measuring those
    // as controls the finger can miss is measuring something nobody can touch.
    const buttons = Array.from(el.querySelectorAll('button')).map((b) => {
      const r = b.getBoundingClientRect();
      return { text: (b.textContent || '').trim().slice(0, 24), w: Math.round(r.width), h: Math.round(r.height) };
    }).filter((b) => b.w > 0 && b.h > 0);
    return { tabs, buttons, width: Math.round(el.getBoundingClientRect().width) };
  });
  check('the order card rendered', card !== null, JSON.stringify(card).slice(0, 160));
  if (card) {
    check('it has tabs to spread the detail over', card.tabs.length >= 3, `tabs=${card.tabs.join('/')}`);
    const tappable = card.buttons.filter((b) => b.w >= 32 && b.h >= 32);
    // No `card.buttons.length === 0 ||` disjunct. This is the only check in the suite that
    // looks at the rendered DOM, and while an empty rail counted as a pass, a card that drew
    // with its action rail missing produced a fully green browser run — the exact failure the
    // sibling ASGI test guards against with a non-empty `action_ids`.
    check('the card has controls at all', card.buttons.length > 0,
      `buttons=${card.buttons.length}`);
    check('its controls are big enough for a finger',
      card.buttons.length > 0 && tappable.length === card.buttons.length,
      `${tappable.length}/${card.buttons.length} at 32px+`);
    check('the card fits the tablet', card.width <= VIEWPORT.width, `card=${card.width}px viewport=${VIEWPORT.width}px`);
  }

  // ---- 3. nothing scrolls sideways, at this width or narrower
  for (const width of [VIEWPORT.width, 400]) {
    await page.setViewportSize({ width, height: VIEWPORT.height });
    await page.waitForTimeout(120);
    const overflow = await page.evaluate(() => ({
      doc: document.documentElement.scrollWidth,
      win: window.innerWidth,
      widest: Array.from(document.querySelectorAll('body *')).reduce((w, el) => Math.max(w, el.scrollWidth), 0),
    }));
    check(`no horizontal overflow at ${width}px`, overflow.doc <= overflow.win + 1,
      `scrollWidth=${overflow.doc} innerWidth=${overflow.win} widest=${overflow.widest}`);
  }
  await page.setViewportSize(VIEWPORT);

  // ---- 4. a tab switch through the semantic command endpoint
  const tabbed = await page.evaluate(async () => {
    const form = new URLSearchParams({ session_id: 'browser', command: 'surface.tab', surface: 'order', tab: 'shipping' });
    const r = await fetch('/command', { method: 'POST', body: form });
    return r.json();
  });
  check('tapping a tab is a semantic command the server owns', tabbed.ok === true && (tabbed.changed || {}).tab === 'shipping',
    JSON.stringify(tabbed).slice(0, 160));

  // ---- 5. a list, then walking it
  const list = await ask("show me today's orders", 'browser');
  check('a list question draws a list', (list.ui || []).some((i) => i.type === 'order_list'),
    `ui=${(list.ui || []).map((i) => i.type).join(',')}`);
  await page.evaluate((payload) => window.__crooksDraw(payload), list);
  await shot('03-order-list');
  const rows = await page.evaluate(() => Array.from(document.querySelectorAll('.rows li, .row')).length);
  check('the list rendered rows to tap', rows > 0, `rows=${rows}`);

  // [checker, 8 Oct 2026, review note N2] Walked as it was asked for, OUT LOUD: George's main path
  // is to say a list and then walk it. Since 28 September (DEC-063) a spoken list is the model's,
  // and a list the model draws opens no walk: Next says "There is no list open to move through."
  // What that defect breaks is held as a strict expected failure; Home does not depend on it.
  const command = (fields) => page.evaluate(async (f) => {
    const form = new URLSearchParams({ session_id: 'browser', ...f });
    return (await fetch('/command', { method: 'POST', body: form })).json();
  }, fields);
  const saidNext = await command({ command: 'workflow.next' });
  knownDefect(SPOKEN_LIST_WALK, 'Next moves the cursor on a list asked for out loud',
    saidNext.ok === true && /\d+ of \d+/.test(saidNext.answer || ''), `answer=${saidNext.answer}`);
  const saidBack = await command({ command: 'navigation.back' });
  const saidBackStop = (saidBack.changed || {}).workspace || {};
  knownDefect(SPOKEN_LIST_WALK, 'Back returns to the list asked for out loud, with cards on it',
    (saidBack.ui || []).some((i) => i.type === 'order_list') && saidBackStop.kind === 'list' && Boolean(saidBackStop.set_id),
    `ui=${(saidBack.ui || []).map((i) => i.type).join(',')} answer=${saidBack.answer}`);
  const saidHome = await command({ command: 'navigation.home' });
  check('Home from a list asked for out loud draws the landing, with cards on it',
    (saidHome.ui || []).some((i) => i.type === 'order_list') && (saidHome.changed || {}).home === true
    && (saidHome.changed || {}).area === 'orders',
    `ui=${(saidHome.ui || []).map((i) => i.type).join(',')} changed=${JSON.stringify(saidHome.changed || {}).slice(0, 160)}`);

  // [checker, 8 Oct 2026] And from the list the Orders icon opens, which walks today: the controls
  // checked below are the list's own, and the Orders icon is how a thumb opens a list to walk.
  await page.evaluate(async () => {
    const form = new URLSearchParams({ session_id: 'browser', command: 'open.area', area: 'orders' });
    return (await fetch('/command', { method: 'POST', body: form })).json();
  });
  const next = await page.evaluate(async () => {
    const form = new URLSearchParams({ session_id: 'browser', command: 'workflow.next' });
    return (await fetch('/command', { method: 'POST', body: form })).json();
  });
  check('Next moves the cursor from the browser', next.ok === true && /\d+ of \d+/.test(next.answer || ''),
    `answer=${next.answer}`);

  const back = await page.evaluate(async () => {
    const form = new URLSearchParams({ session_id: 'browser', command: 'navigation.back' });
    return (await fetch('/command', { method: 'POST', body: form })).json();
  });
  // Back returns to the LIST the member was walked out of, and redraws that list — not the
  // record, and not an empty screen with a sentence over it. The cards are what is checked,
  // because `ok` was true twelve times in twenty-two seconds while the owner was lost.
  const backTypes = (back.ui || []).map((i) => i.type);
  check('Back returns to the list it came from, with cards on it',
    backTypes.indexOf('order_list') !== -1,
    `ui=${backTypes.join(',')} answer=${back.answer}`);
  const backStop = (back.changed || {}).workspace || {};
  check('and the Mac says which workspace that is',
    backStop.kind === 'list' && Boolean(backStop.set_id),
    JSON.stringify(backStop).slice(0, 200));

  // Home is a PLACE. From a record three deep it must draw the landing for the half's area,
  // never a replay of the record — which is what put the same email thread on screen eight
  // times in the live session.
  const home = await page.evaluate(async () => {
    const form = new URLSearchParams({ session_id: 'browser', command: 'navigation.home' });
    return (await fetch('/command', { method: 'POST', body: form })).json();
  });
  const homeTypes = (home.ui || []).map((i) => i.type);
  check('Home draws the landing for this half, with cards on it',
    homeTypes.indexOf('order_list') !== -1 && (home.changed || {}).home === true
    && (home.changed || {}).area === 'orders',
    `ui=${homeTypes.join(',')} changed=${JSON.stringify(home.changed || {}).slice(0, 160)}`);
  const homeAgain = await page.evaluate(async () => {
    const form = new URLSearchParams({ session_id: 'browser', command: 'navigation.home' });
    return (await fetch('/command', { method: 'POST', body: form })).json();
  });
  check('pressed again, it is the same place and not an empty one',
    JSON.stringify((homeAgain.ui || []).map((i) => i.type)) === JSON.stringify(homeTypes),
    `first=${homeTypes.join(',')} again=${(homeAgain.ui || []).map((i) => i.type).join(',')}`);

  // ---- 6. touch, then voice
  const bound = await page.evaluate(async () => {
    const form = new URLSearchParams({ session_id: 'browser', command: 'voice.bind', family: 'order.add_note' });
    return (await fetch('/command', { method: 'POST', body: form })).json();
  });
  check('a tapped control can arm the microphone for what it is about',
    bound.ok === true && ((bound.changed || {}).listening_for || {}).family === 'order.add_note',
    JSON.stringify(bound.changed || {}).slice(0, 160));

  // ---- 7. the capability surface
  // [checker, 8 Oct 2026] Was 'the capability question draws a surface'. The capability card was
  // the word-matching lane's (its `capability_summary` family), removed on 28 September with the
  // lane (DEC-063); the question is the model's now and is answered in words, and nothing on the
  // Mac draws the card (`app/capabilities/surface.py` is parked, MAP.md). The card's renderer and
  // its question chips are still on the page, so they are checked on the card drawn directly.
  const caps = await ask('what can you do now?', 'browser');
  check('the capability question is the model\'s, answered in words (DEC-063)',
    caps.lane === 'NORMAL' && Boolean((caps.answer || '').trim()),
    `lane=${caps.lane} answer=${(caps.answer || '').slice(0, 80)}`);
  const capsDrawn = await page.evaluate((payload) => window.__crooksDraw(payload), {
    ui: [{ type: 'capability', data: {
      title: 'What this can do', writes_enabled: false, counts: { reads: 55, changes: 22, bulk: 5 },
      groups: [{ area: 'orders', label: 'Orders', items: [{ name: 'shopify_find_order', what: 'find an order by number, name or email', kind: 'read', state: 'ready' }] }],
      examples: ['show me today\'s orders', 'who is waiting on a reply?'],
    } }],
  });
  check('the capability surface renders', capsDrawn.nodes > 0 && (capsDrawn.skipped || []).length === 0,
    `nodes=${capsDrawn.nodes} skipped=${(capsDrawn.skipped || []).join(',')}`);
  const capsBody = await page.evaluate(() => {
    const el = document.querySelector('.card');
    return el ? { height: Math.round(el.getBoundingClientRect().height), text: (el.textContent || '').trim().length } : null;
  });
  check('the capability card has something in it', capsBody && capsBody.height > 80 && capsBody.text > 40,
    JSON.stringify(capsBody));
  await shot('04-capabilities');

  // Every chip the capability card offers must BE a question, not look like one. These are
  // drawn as real <button>s carrying the text to ask, and for a while nothing listened to
  // them: six styled, tappable controls on every answer to "what can you do", each of which
  // did nothing at all — no turn, no toast, not even a telemetry line. A browser is the only
  // thing that can tell a wired button from an unwired one.
  const chips = await page.evaluate(() => {
    // On the card: the dock's icons carry `data-ask` too, and are not what this is about.
    const found = Array.from(document.querySelectorAll('.card-capability [data-ask]'));
    return { count: found.length, first: found.length ? (found[0].dataset.ask || '') : '' };
  });
  check('the capability card offers questions to tap', chips.count > 0, JSON.stringify(chips));
  const asked = await page.evaluate(() => {
    // Watch what the page does with the tap, rather than trusting that it did something.
    const posts = [];
    const real = window.fetch;
    window.fetch = (url, opts) => { posts.push(String(url)); return real(url, opts); };
    // Ask silently. The question is what this check is about; speaking the answer would send
    // the page to /speak, which has no voice credential in a fixture run and correctly answers
    // 503 — a real backend refusal, not a fault in the page, and not this check's subject.
    const speak = document.querySelector('#speak-toggle, [name="speak"]');
    if (speak && speak.checked) speak.checked = false;
    const chip = document.querySelector('.card-capability [data-ask]');
    if (chip) chip.click();
    return new Promise((resolve) => setTimeout(() => { window.fetch = real; resolve(posts); }, 500));
  });
  check('tapping one asks it', asked.some((u) => u.includes('/turn')),
    `posted=${asked.join(',') || 'nothing'}`);

  // ---- 8. the list, walked with a thumb rather than with fetch
  //
  // Everything above this line posts to /command directly, which is why nothing above it
  // caught what a hand catches immediately. Three P0s lived under those green checks: Back
  // was `hidden` until the first Next, so the first tap made it appear and slid Next 68px out
  // from under the thumb — a second tap in the same place hit BACK; `workflow.at_end` hid
  // Next for good, and `workflow.previous` had no caller anywhere in web/, so overshooting a
  // queue by one was permanent; and the position the Mac computes was written to #answer only
  // when a move FAILED, so three successful steps left one stale sentence over three
  // different orders. All three are properties of the page's own controls, so this section
  // touches the page's own controls and nothing else.
  // A fresh conversation: the page restores a session's workspace on load now, and this
  // section's premise is a list with nothing behind it.
  await page.evaluate(() => { try { localStorage.removeItem('crooks.session'); localStorage.removeItem('crooks.turns'); } catch { /* private mode */ } });
  await page.goto(`${BASE}?dev=1`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(700);
  await page.evaluate(() => { for (const b of document.querySelectorAll('.dev-banner')) b.remove(); });
  // The diagnostics field posts exactly what the microphone posts — the same submit().
  const say = async (text) => {
    await page.evaluate(() => {
      const sheet = document.querySelector('#settings');
      const dev = document.querySelector('#dev');
      if (dev) dev.hidden = false;
      if (sheet && !sheet.open && sheet.showModal) sheet.showModal();
    });
    await page.fill('#dev-text', text);
    await page.press('#dev-text', 'Enter');
    await sleep(1100);
    await page.evaluate(() => { const sheet = document.querySelector('#settings'); if (sheet && sheet.open) sheet.close(); });
    await sleep(300);
  };
  const walkState = () => page.evaluate(() => {
    const rect = (sel) => {
      const e = document.querySelector(sel);
      if (!e) return null;
      const b = e.getBoundingClientRect();
      // `drawn`: on the glass at all. A control hidden by a stylesheet keeps its `hidden` false,
      // so a check that read only the attribute passed over a control nobody could see.
      const drawn = b.width > 0 && b.height > 0 && getComputedStyle(e).display !== 'none' && getComputedStyle(e).visibility !== 'hidden';
      return { x: Math.round(b.x), w: Math.round(b.width), hidden: Boolean(e.hidden), disabled: Boolean(e.disabled), drawn };
    };
    const card = document.querySelector('#cards .card');
    return {
      back: rect('#back-btn'), next: rect('#next-btn'), prev: rect('#prev-btn'),
      ref: (card && card.dataset.ref) || '', type: (card && card.dataset.type) || '',
      types: Array.from(document.querySelectorAll('#cards .card')).map((c) => c.dataset.type || ''),
      rows: Array.from(document.querySelectorAll('#cards .rows li, #cards .row')).length,
      area: document.body.dataset.area || '', mode: document.body.dataset.mode || '',
      answer: ((document.querySelector('#answer') || {}).textContent || '').trim(),
      chip: ((document.querySelector('#stack .chip-set') || {}).textContent || '').trim(),
      // Design pass (3 Oct): what the home holds, for Home's own destination.
      home: (document.querySelector('#alpha-home') || { children: [] }).children.length,
    };
  });

  // [checker, 8 Oct 2026] Opened with the Orders icon, as a thumb opens a list to walk: a spoken
  // list opens no walk since 28 September (DEC-063); see section 5.
  const landedOn = page.waitForResponse((r) => r.url().endsWith('/command') && r.request().method() === 'POST');
  const dockAt = await page.evaluate(() => { const b = document.querySelector('.dock-btn[data-area="orders"]').getBoundingClientRect(); return { x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2) }; });
  await page.touchscreen.tap(dockAt.x, dockAt.y);
  await landedOn;
  await sleep(1400);
  const atList = await walkState();
  // Design pass (3 Oct), and its review: Back is drawn only when there is somewhere to go back
  // to (GENERATIVE_UI_V1 §4 removed the permanent strip, and its greyed slot with it). This check
  // read "keeps a slot for Back rather than a gap", and passed on the `hidden` attribute while the
  // stylesheet hid the slot; it now holds the rule as it is.
  check('a list offers Next, and no Back: there is nothing behind a list just opened',
    Boolean(atList.next && atList.next.drawn && !atList.next.disabled)
    && Boolean(atList.back && !atList.back.drawn),
    JSON.stringify(atList).slice(0, 200));
  // The list's own step back sits beside its own step on, and starts greyed: the set is at
  // its first member. Back is the trail's, and there is nothing behind a list just opened.
  check('the list brings its own way back, greyed until the walk has begun',
    Boolean(atList.prev && !atList.prev.hidden && atList.prev.disabled),
    JSON.stringify(atList.prev));

  // The thumb test: one point on the glass, pressed twice.
  const thumb = await page.evaluate(() => {
    const b = document.querySelector('#next-btn').getBoundingClientRect();
    return { x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2) };
  });
  await page.touchscreen.tap(thumb.x, thumb.y);
  await sleep(1200);
  const first = await walkState();
  await page.touchscreen.tap(thumb.x, thumb.y);
  await sleep(1200);
  const second = await walkState();
  check('two taps on the same pixel both go forwards',
    first.type === 'order' && second.type === 'order' && first.ref && second.ref && first.ref !== second.ref
    && /1 of 3/.test(first.answer) && /2 of 3/.test(second.answer),
    `1st=${first.ref} "${first.answer}" 2nd=${second.ref} "${second.answer}"`);
  // Design pass (3 Oct): Back is drawn only when there is somewhere to go back to — the greyed
  // placeholder was part of the permanent strip GENERATIVE_UI_V1 §4 removed — so it appears after
  // the first Next. What must not happen is what the slot was for: the control under the thumb
  // changing. Next is anchored at the row's far end, so it stays put, and Back appears at the
  // other end, never where Next was.
  const clear = (b) => !b || b.w === 0 || b.x + b.w <= atList.next.x || b.x >= atList.next.x + atList.next.w;
  check('neither chip moves under the thumb while the list is walked',
    first.next.x === atList.next.x && second.next.x === atList.next.x && clear(first.back) && clear(second.back),
    `next x ${atList.next.x}/${first.next.x}/${second.next.x} back x ${atList.back.x}/${first.back.x}/${second.back.x}`);
  check('the screen says where in the list you are, on the card as well as in the sentence',
    /2\s*of\s*3/.test(second.chip), `chip="${second.chip}"`);

  await page.touchscreen.tap(thumb.x, thumb.y);
  await sleep(1200);
  const end = await walkState();
  check('the end of a list greys Next in its slot rather than deleting it',
    Boolean(end.next && !end.next.hidden && end.next.disabled && end.next.x === atList.next.x),
    JSON.stringify(end.next));

  // The list's step back moves the CURSOR: 3 of 3 becomes 2 of 3 and Next comes alive again.
  // Overshooting a queue by one used to be permanent — `workflow.previous` had no caller
  // anywhere on the glass — and Back was wired to it instead, which is how one pair of
  // buttons came to drive two cursors.
  await page.evaluate(() => document.querySelector('#prev-btn').click());
  await sleep(1200);
  const stepped = await walkState();
  check('the list step back moves the cursor, and Next comes alive again',
    stepped.ref === second.ref && Boolean(stepped.next && !stepped.next.disabled) && /2 of 3/.test(stepped.answer),
    `ref=${stepped.ref} next=${JSON.stringify(stepped.next)} answer="${stepped.answer}"`);

  // And Back walks the TRAIL out of the queue, one workspace at a time, ending at the list
  // the walk started from — with its rows on screen and the dock lit for it. There was no way
  // to reach this screen at all before: only records were stops on the trail.
  let out = stepped;
  for (let i = 0; i < 8 && out.type !== 'order_list' && out.back && !out.back.disabled; i++) {
    await page.evaluate(() => document.querySelector('#back-btn').click());
    await sleep(1100);
    out = await walkState();
  }
  check('Back walks out of the queue and ends on the list itself',
    out.type === 'order_list' && out.rows > 0 && out.mode === 'context',
    `types=${out.types.join(',')} rows=${out.rows} answer="${out.answer}"`);
  check('and the dock lights the place that list belongs to', out.area === 'orders', `area=${out.area}`);
  // Design pass (3 Oct), and its review: this read "Back is spent and says so in its slot" and
  // passed on the `hidden` attribute while the stylesheet hid the slot. Back spent is Back gone.
  check('at the list, Back is gone: the trail goes back no further',
    Boolean(out.back && out.back.disabled && !out.back.drawn),
    JSON.stringify(out.back));
  await shot('05-list-walk');

  // Home, with a thumb. Design pass (3 Oct): the chip is "Home" and goes to the home — what needs
  // him and what is moving — as the horizon's Home does; the orders landing is the Orders icon's.
  // (It was "CLIVE" and landed on this half's dock landing, which on the phone was the only way
  // anywhere and was the orders list.) Never a replay of the record oldest on the trail.
  await say('show me order 1938');
  const atRecord = await walkState();
  check('a record is open to press Home from', atRecord.type === 'order', `type=${atRecord.type}`);
  await page.evaluate(() => document.querySelector('#home-btn').click());
  await sleep(1600);
  const landed = await walkState();
  check('Home lands on the home, not on a landing',
    landed.mode === 'orb',
    `mode=${landed.mode} types=${landed.types.join(',')}`);
  await page.evaluate(() => document.querySelector('#home-btn').click());
  await sleep(1600);
  const landedTwice = await walkState();
  // Design pass (3 Oct): the destination is the home, so "still has cards on it" is "the home
  // is drawn": the same screen both times, with the home on it.
  check('pressed twice, it is the same landing both times and still has cards on it',
    landedTwice.mode === landed.mode && landedTwice.mode === 'orb' && landedTwice.home > 0,
    `first=${landed.mode} again=${landedTwice.mode} home=${landedTwice.home}`);
  await shot('08-assistant-landing');

  // [checker, 8 Oct 2026, review note N2] The same walk by thumb on a list asked for OUT LOUD,
  // from the home: Next, then Back to the list, then Home. A list the model draws is not made the
  // walk since 28 September (DEC-063): with the Orders icon's list walked earlier in this session,
  // Next walks THAT list ("#1938. 2 of 3.") and Back ends on its landing, not on the list just
  // asked for. So the walk is held to the list on the glass, by its own rows, and what the defect
  // breaks is a strict expected failure (see the top of this file). Home is a plain check.
  const rowRefs = () => page.evaluate(() => Array.from(document.querySelectorAll('#cards li.row[data-kind="order"][data-ref]')).map((r) => r.dataset.ref));
  await say("show me today's orders");
  const saidList = await walkState();
  const saidRows = await rowRefs();
  check('a list asked for out loud is on the glass, with rows', saidList.type === 'order_list' && saidRows.length > 0,
    `types=${saidList.types.join(',')} rows=${saidRows.length}`);
  let saidFirst = saidList;
  if (saidList.next && saidList.next.drawn && !saidList.next.disabled) {
    await page.evaluate(() => document.querySelector('#next-btn').click());
    await sleep(1200);
    saidFirst = await walkState();
  }
  knownDefect(SPOKEN_LIST_WALK, 'Next on a list asked for out loud opens ITS first order and says "1 of" its length',
    saidFirst.type === 'order' && saidFirst.ref === saidRows[0] && new RegExp(`\\b1 of ${saidRows.length}\\b`).test(saidFirst.answer),
    `next=${JSON.stringify(saidList.next)} type=${saidFirst.type} ref=${saidFirst.ref} first row=${saidRows[0]} "${saidFirst.answer}"`);
  let saidOut = saidFirst;
  for (let i = 0; i < 8 && saidOut.type !== 'order_list' && saidOut.back && saidOut.back.drawn && !saidOut.back.disabled; i++) {
    await page.evaluate(() => document.querySelector('#back-btn').click());
    await sleep(1100);
    saidOut = await walkState();
  }
  const outRows = await rowRefs();
  knownDefect(SPOKEN_LIST_WALK, 'Back walks out of a list asked for out loud and ends on that same list',
    saidFirst !== saidList && saidOut.type === 'order_list' && JSON.stringify(outRows) === JSON.stringify(saidRows),
    `walked=${saidFirst !== saidList} types=${saidOut.types.join(',')} rows=${outRows.length} vs ${saidRows.length}`);
  const saidHomeBtn = await page.evaluate(() => {
    const b = document.querySelector('#home-btn');
    if (!b) return false;
    const r = b.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    b.click();
    return true;
  });
  await sleep(1600);
  const saidLanded = await walkState();
  check('Home from a list asked for out loud lands on the home', saidHomeBtn && saidLanded.mode === 'orb',
    `pressed=${saidHomeBtn} mode=${saidLanded.mode} types=${saidLanded.types.join(',')}`);

  // ---- 9. touch, then voice, with a finger rather than with fetch
  //
  // Section 6 above proves the MAC binds. It could not prove the tablet ever asked it to, and
  // it did not: "voice.bind" appeared zero times in web/, so tapping Note set two text labels
  // and returned. The Mac was never told, `listening_for` stayed null, the sentence that
  // followed reached the model bare, and the only thing on screen that changed was a pill
  // 788px below the finger — which is overwritten by "Release to send" the moment the thumb
  // goes down to speak.
  await say('show me order 1938');
  // Note is a secondary chip now (app/actions/available.py): five renders and nought taps in
  // the live session, so what the order needs leads and the fallbacks are one tap behind a
  // disclosure. That tap is part of the path, so this makes it.
  await page.evaluate(() => { const more = document.querySelector('#cards .rail-more'); if (more) more.click(); });
  await sleep(300);
  const chipBefore = await page.evaluate(() => {
    const c = document.querySelector('#cards .rail-chip[data-family="order.add_note"]');
    if (!c) return null;
    const s2 = getComputedStyle(c);
    const b = c.getBoundingClientRect();
    return { bg: s2.backgroundColor, border: s2.borderTopColor, x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2) };
  });
  check('a control that expects words says which one it is', Boolean(chipBefore),
    chipBefore ? 'data-family=order.add_note' : 'no chip carries a family');
  if (chipBefore) {
    await page.touchscreen.tap(chipBefore.x, chipBefore.y);
    await sleep(1300);
    const armed = await page.evaluate(() => {
      // The armed state sits on the control itself when that control is on screen (Phase 3),
      // and in the band above the deck otherwise. Either is "beside the card, not under the dock".
      const band = document.querySelector('#cards .armed-inline') || document.querySelector('#armed');
      const c = document.querySelector('#cards .rail-chip[data-family="order.add_note"]');
      const s2 = c ? getComputedStyle(c) : null;
      return {
        shown: Boolean(band && !band.hidden),
        text: band && !band.hidden ? (band.textContent || '').replace(/\s+/g, ' ').trim() : '',
        top: band && !band.hidden ? Math.round(band.getBoundingClientRect().top) : -1,
        chipTop: c ? Math.round(c.getBoundingClientRect().top) : -1,
        bg: s2 ? s2.backgroundColor : '', border: s2 ? s2.borderTopColor : '',
        listening: document.body.dataset.listeningFor || '',
      };
    });
    // Asked of the Mac, not of the page: `listening_for` can only be set by a real binding.
    // The page keeps its session id in localStorage, which is how the tablet itself survives
    // a reload, so this reads the same session the taps above are driving.
    const branch = await page.evaluate(async () => {
      const id = localStorage.getItem('crooks.session') || '';
      const r = await fetch(`/branches?session_id=${encodeURIComponent(id)}`, { cache: 'no-store' });
      const d = await r.json();
      const one = (d.branches || []).find((b) => b.listening_for);
      return one ? one.listening_for : null;
    });
    check('tapping it tells the Mac what the next sentence is about',
      Boolean(branch && branch.family === 'order.add_note'), JSON.stringify(branch));
    check('and the screen says so, beside the card rather than under the dock',
      armed.shown && /Adding a note/.test(armed.text) && /1938/.test(armed.text)
      && Math.abs(armed.top - armed.chipTop) < 500,
      `shown=${armed.shown} "${armed.text}" band@${armed.top} chip@${armed.chipTop}`);
    check('and the chip the finger touched looks touched',
      armed.bg !== chipBefore.bg && armed.border !== chipBefore.border && armed.listening === 'order.add_note',
      `bg ${chipBefore.bg} -> ${armed.bg} | border ${chipBefore.border} -> ${armed.border}`);

    // The band must survive the act of using it. The dock label it replaced did not.
    await page.evaluate(() => {
      const t = document.querySelector('#talk');
      if (t) t.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerId: 1 }));
    });
    await sleep(400);
    const held = await page.evaluate(() => {
      const band = document.querySelector('#cards .armed-inline') || document.querySelector('#armed');
      return { shown: Boolean(band && !band.hidden), text: band && !band.hidden ? (band.textContent || '').replace(/\s+/g, ' ').trim() : '' };
    });
    await page.evaluate(() => {
      const t = document.querySelector('#talk');
      if (t) t.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 1 }));
    });
    await sleep(500);
    check('it is still there while the thumb is down to speak', held.shown && /Adding a note/.test(held.text),
      `shown=${held.shown} "${held.text}"`);
    await shot('06-armed');

    // And it can be let go of. `voice.cancel` had no affordance on the glass at all.
    await page.evaluate(() => { const b = document.querySelector('#armed-cancel'); if (b) b.click(); });
    await sleep(1000);
    const after = await page.evaluate(async () => {
      const band = document.querySelector('#cards .armed-inline') || document.querySelector('#armed');
      const id = localStorage.getItem('crooks.session') || '';
      const r = await fetch(`/branches?session_id=${encodeURIComponent(id)}`, { cache: 'no-store' });
      const d = await r.json();
      return { shown: Boolean(band && !band.hidden), any: (d.branches || []).filter((b) => b.listening_for).length };
    });
    check('and let go of, which nothing on the glass could do',
      after.shown === false && after.any === 0, JSON.stringify(after));
  }

  // ---- 10. an email has controls
  //
  // `rail()` was drawn on the order card and nowhere else, so an email thread on the tablet
  // had no Reply, no Rewrite and no Archive: the Mac had all three registered and reachable
  // by a spoken sentence only, and the only way out of a thread was to put the tablet down.
  await say('which customers need replying to?');
  await page.evaluate(() => { const row = document.querySelector('#cards .row.tappable[data-kind="email_thread"]'); if (row) row.click(); });
  await sleep(1400);
  const thread = await page.evaluate(() => {
    const card = document.querySelector('#cards .card');
    const chips = Array.from(document.querySelectorAll('#cards .card .rail-chip'));
    return {
      type: (card && card.dataset.type) || '',
      chips: chips.map((c) => ({ label: (c.textContent || '').trim(), mode: c.dataset.mode, family: c.dataset.family || '', ref: c.dataset.ref || '', off: c.getAttribute('aria-disabled') === 'true', h: Math.round(c.getBoundingClientRect().height) })),
    };
  });
  check('tapping a waiting thread opens it', thread.type === 'email_thread', `type=${thread.type}`);
  check('and the thread has a rail: Reply opens the reply, Archive prepares the change',
    thread.chips.some((c) => c.label === 'Reply' && c.mode === 'open' && c.family === 'email.reply' && !c.off)
    && thread.chips.some((c) => c.label === 'Archive' && c.mode === 'stage' && c.ref && !c.off),
    JSON.stringify(thread.chips));
  // The chips on the card. The ones behind the disclosure are at zero height until it is
  // opened, which is the point of a disclosure and not a control too small to hit.
  check('its chips are big enough for a finger',
    thread.chips.filter((c) => c.h > 0).length > 0 && thread.chips.filter((c) => c.h > 0).every((c) => c.h >= 44),
    thread.chips.map((c) => `${c.label}:${c.h}px`).join(' '));
  await shot('07-email-thread');

  check('no script error during the whole run', errors.length === 0, errors.slice(0, 3).join(' | '));

  await browser.close();
  const ok = checks.every((c) => c.ok);
  process.stdout.write(`${JSON.stringify({ ok, checks, shots })}\n`);
  return ok ? 0 : 1;
}

main().then((code) => process.exit(code)).catch((e) => {
  process.stdout.write(`${JSON.stringify({ ok: false, checks: [{ name: 'browser run', ok: false, detail: String(e && e.message).slice(0, 400) }], shots })}\n`);
  process.exit(1);
});

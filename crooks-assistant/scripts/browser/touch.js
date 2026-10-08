/* D-1, in the browser, with real fingers. §37's gate for the P0 of Phase 5.
 *
 * WHAT THIS ANSWERS. On 11 September the tablet recorded 132 hold-starts, 131 of them reporting
 * `target:"dock"` and one `orb` — and no other target exists anywhere in the file, because
 * nothing else on the page ever got a touch. 63 of those "holds" were under 200 ms, in 19
 * bursts; 26 of them came in ten consecutive seconds while the owner said "I cannot click the
 * merge or close button or any of the other buttons for the two blobs, because wherever I press
 * just leads to you listening". Every one of those taps went to the speech recogniser, came
 * back "too short", and was then counted by the analyser as a precision-input failure — so one
 * HCI defect became the top engineering priority of a session in which speech was the one thing
 * that worked.
 *
 * NO EXISTING GATE COULD SEE IT. collision.js measures overlapping RECTANGLES, and a
 * transparent full-stage button over the branch chips is not an overlap it counts (`#talk` is
 * chrome to it, by design). accept.js, split.js and tablet.js press controls with
 * `element.click()`, which dispatches straight at the node and cannot be swallowed by anything
 * painted over it. The defect was only ever visible to a real finger at a real coordinate.
 *
 * So every tap here is a CDP `Input.dispatchTouchEvent` at a measured pixel, 90 ms down —
 * inside the 39–140 ms band of the 26-tap burst. Four things are counted for each one:
 *
 *   /turn posted                 a recording actually sent
 *   recording_too_short          the telemetry event the 63 taps produced
 *   hold phase:start             the voice layer claiming the touch at all
 *   CrooksTouch.audit().submits  the state machine's own count
 *
 * HARD GATE: across every ordinary control tap in this file, all four must be ZERO. Not few.
 * And the other half of it, because a gate that only forbids is one you pass by breaking the
 * feature: every tap must be shown to have REACHED its control, the layer ladder is measured
 * against its own rule at both sizes, and two genuine holds must still post a turn.
 *
 * Both viewports, in one run:
 *   node scripts/browser/touch.js http://127.0.0.1:8765 /path/to/screenshots
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...] }.
 */
'use strict';

const { chromium } = require('playwright-core');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
// The physical tablet, and the gate's own size. A check that passes on one and not the other is
// the class of defect this file exists for.
const SIZES = [
  { name: '601x889', viewport: { width: 601, height: 889 }, dpr: 1.33 },
  { name: '800x1280', viewport: { width: 800, height: 1280 }, dpr: 1 },
];
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const TAP_MS = 90;          // the median of the 26-tap burst of 23:08:31

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });
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

async function atSize(browser, size) {
  const at = (what) => `${what} (${size.name})`;
  const context = await browser.newContext({
    viewport: size.viewport, deviceScaleFactor: size.dpr, isMobile: true, hasTouch: true,
    extraHTTPHeaders: HEADERS,
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const from = (m.location && m.location() && m.location().url) || '';
    if (from.includes('/speak')) return;
    // [checker, 8 Oct 2026] Nor /voice/live's 503: with no ElevenLabs key in the fixture world it
    // answers 503 by design (app/routes/voice.py), and the hold goes on without live words.
    if (from.includes('/voice/live')) return;
    errors.push(`console: ${m.text()}`);
  });
  const posts = [];
  page.on('request', (r) => { if (r.method() === 'POST') posts.push(r.url().replace(BASE, '')); });
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key","reason":"no voice under test"}' }));

  /* Three instruments, installed before any page script runs.
     1. A microphone that makes noise, so a recording that must NOT be sent is proved not to be
        sent rather than merely being too short to send.
     2. Every telemetry event the page records — wrapped through a property on `window`, because
        app.js captures the module in a const at load and a test session may not be running.
     3. What every touch actually landed on, and the nearest CONTROL it landed inside: a tap on
        Home lands on the span inside the button, which is still a tap on Home. */
  await page.addInitScript(() => {
    const AC = window.AudioContext || window.webkitAudioContext;
    const ac = new AC();
    const dest = ac.createMediaStreamDestination();
    const osc = ac.createOscillator(); const gain = ac.createGain(); gain.gain.value = 0.2;
    osc.frequency.value = 220; osc.connect(gain); gain.connect(dest); osc.start();
    navigator.mediaDevices.getUserMedia = async () => { await ac.resume(); return dest.stream; };

    window.__events = [];
    let held;
    Object.defineProperty(window, 'CrooksTelemetry', {
      configurable: true,
      get() { return held; },
      set(api) {
        held = api;
        if (api && typeof api.record === 'function' && !api.__wrapped) {
          const inner = api.record;
          api.record = function (kind, fields) {
            window.__events.push({ kind: String(kind), fields: fields || {} });
            return inner.apply(this, arguments);
          };
          api.__wrapped = true;
        }
      },
    });

    window.__sel = (node) => {
      if (!node || !node.tagName) return '';
      const raw = typeof node.className === 'string' ? node.className
        : (node.className && node.className.baseVal) || '';
      const cls = String(raw).split(' ').filter(Boolean)[0];
      return `${node.tagName.toLowerCase()}${node.id ? `#${node.id}` : ''}${cls ? `.${cls}` : ''}`;
    };
    const CONTROLS = 'button,[role="button"],[role="tab"],a[href],input,select,textarea,li.row,.note,.rail-chip,.row-btn';
    window.__clicks = [];
    const note = (prefix, e) => {
      const own = window.__sel(e.target);
      const host = e.target && e.target.closest ? e.target.closest(CONTROLS) : null;
      window.__clicks.push(prefix + own + (host && host !== e.target ? ` in ${window.__sel(host)}` : ''));
    };
    addEventListener('click', (e) => note('', e), true);
    addEventListener('pointerdown', (e) => note('down:', e), true);
  });

  const cdp = await context.newCDPSession(page);
  const touch = (type, points) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: points });

  // ---- the instruments ----------------------------------------------------------------
  const events = () => page.evaluate(() => (window.__events || []).map((e) => e.kind));
  const holdStarts = () => page.evaluate(() => (window.__events || [])
    .filter((e) => e.kind === 'hold' && e.fields && e.fields.phase === 'start').length);
  const tooShort = () => page.evaluate(() => (window.__events || []).filter((e) => e.kind === 'recording_too_short').length);
  const audit = () => page.evaluate(() => (window.__crooksTouch ? window.__crooksTouch.audit() : null));
  const clicks = () => page.evaluate(() => (window.__clicks || []).slice());
  const reset = () => page.evaluate(() => { window.__events = []; window.__clicks = []; });
  const turns = () => posts.filter((p) => p === '/turn').length;

  /* A box, in the coordinates a finger uses. `onScreen` matters on its own: the navigation row
     ran off the right edge at 601 px and cut the second half's chip in half, which is a control
     that is drawn, reported as present, and cannot be pressed. `hitBy` is the one line that
     says whether D-1 is fixed: what is on top of the middle of this control? All evening, for
     every branch chip, the answer was `#talk`. */
  const boxOf = (selector) => page.evaluate((sel) => {
    const node = document.querySelector(sel);
    if (!node) return null;
    const b = node.getBoundingClientRect();
    if (b.width < 1 || b.height < 1) return null;
    const top = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
    return {
      sel, x: Math.round(b.left + b.width / 2), y: Math.round(b.top + b.height / 2),
      w: Math.round(b.width), h: Math.round(b.height),
      left: Math.round(b.left), right: Math.round(b.right), top: Math.round(b.top), bottom: Math.round(b.bottom),
      onScreen: b.left >= -0.5 && b.top >= -0.5 && b.right <= innerWidth + 0.5 && b.bottom <= innerHeight + 0.5,
      // "itself" means the topmost element IS this control or something inside it. An ANCESTOR
      // coming back means the control is not painted where it says it is.
      hitBy: !top ? 'nothing' : `${node.contains(top) ? 'itself' : 'OTHER'}:${window.__sel(top)}`,
    };
  }, selector);

  // The first of these selectors that is actually drawn. A gate that hard-codes one card's
  // shape reports its own wrong guess as a defect in the product.
  async function firstOf(selectors) {
    for (const sel of selectors) if (await boxOf(sel)) return sel;
    return selectors[selectors.length - 1];
  }
  // Scrolled into the middle of its own scroller first: a control below the fold is a real
  // fault on a card, and a false one in the settings sheet, which is a scrolling sheet.
  const bringIntoView = (selector) => page.evaluate((sel) => {
    const n = document.querySelector(sel);
    if (n && n.scrollIntoView) n.scrollIntoView({ block: 'center' });
  }, selector);

  // A physical tap: down, 90 ms, up. Nothing here reaches into the DOM.
  async function tap(box) {
    await touch('touchStart', [{ x: box.x, y: box.y }]);
    await sleep(TAP_MS);
    await touch('touchEnd', []);
    await sleep(700);
  }

  /* One control, tapped the way a thumb taps it, and the four counts that must not move.
     `expect` is a substring of what the click must have landed on or inside, or a list of
     them where one control has more than one shape: Split is a `.branch-act` in the branch
     band and a `.chip` in the navigation rail. */
  // `judge` is who records the result: `check` unless a caller holds this tap to more (N2).
  async function tapControl(label, selector, expect, judge = check) {
    const box = await boxOf(selector);
    if (!box) { judge(at(`tap ${label}`), false, `${selector} is not on screen at all`); return null; }
    await reset();
    const before = { turns: turns(), submits: (await audit() || {}).submits };
    await tap(box);
    const landed = await clicks();
    const starts = await holdStarts();
    const short = await tooShort();
    const after = { turns: turns(), submits: (await audit() || {}).submits };
    const wanted = expect ? [].concat(expect) : [];
    const reached = wanted.length ? landed.some((c) => wanted.some((w) => c.includes(w))) : landed.length > 0;
    const quiet = after.turns === before.turns && short === 0 && starts === 0
      && after.submits === before.submits;
    judge(at(`tap ${label}`), box.onScreen && box.hitBy.startsWith('itself') && reached && quiet, JSON.stringify({
      box: `${box.left},${box.top} ${box.w}x${box.h}`, onScreen: box.onScreen, hitBy: box.hitBy,
      landed: landed.slice(0, 4), turns: after.turns - before.turns, too_short: short,
      hold_starts: starts, submits: (after.submits || 0) - (before.submits || 0),
    }));
    return box;
  }

  const shot = async (name) => {
    if (!OUT) return;
    const file = path.join(OUT, `touch-${size.name}-${name}.png`);
    await page.waitForTimeout(350);
    await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
    shots.push(path.basename(file));
  };

  const say = async (text) => {
    await page.evaluate(() => { const s = document.querySelector('#settings'), d = document.querySelector('#dev'); if (d) d.hidden = false; if (s && !s.open && s.showModal) s.showModal(); });
    await page.fill('#dev-text', text);
    await page.press('#dev-text', 'Enter');
    await sleep(2000);
    await page.evaluate(() => { const s = document.querySelector('#settings'); if (s && s.open) s.close(); });
    await sleep(450);
  };
  const branchesNow = () => page.evaluate(async () => {
    const id = localStorage.getItem('crooks.session') || '';
    const r = await fetch(`/branches?session_id=${encodeURIComponent(id)}`, { cache: 'no-store' });
    const d = await r.json();
    return { count: (d.branches || []).length, focused: d.focused || '' };
  });

  /* The layer ladder, read off the real page and put through the rule it is supposed to keep
     (web/touch.js `covering()`): no layer may visually cover another INTERACTIVE layer without
     intentionally disabling it. This is the assertion that would have failed on 11 September —
     `#talk` at the voice layer, `inset:0`, over `#branch-bar` at the branch layer. */
  const zonesNow = () => page.evaluate(() => {
    const LAYER = [
      ['#orb-frame', 'voice', true], ['#cards', 'content', true], ['#deck', 'content', true],
      ['#context-nav', 'actions', true], ['#armed', 'actions', true],
      ['#settings-btn', 'nav', true], ['#attention', 'nav', true], ['#recent', 'nav', true],
      ['#branch-zone', 'branch', true], ['#branch-bar', 'branch', true],
      ['#notes-orb', 'actions', true], ['#notes-deck', 'actions', true],
      ['#talk', 'voice', true],
    ];
    // Switched off ON PURPOSE, and said so — which is the rule's one exception. Walked up the
    // tree, because `.bottom` is the element that is disabled in context mode and `#attention`
    // is its child (`.bottom > *{pointer-events:auto}` puts the events back on the child).
    const off = (node) => {
      for (let n = node; n && n.nodeType === 1; n = n.parentElement) {
        const style = getComputedStyle(n);
        if (n.hidden || style.display === 'none' || style.visibility === 'hidden'
            || style.pointerEvents === 'none' || Number(style.opacity) === 0) return true;
      }
      return false;
    };
    const zones = [];
    const push = (sel, layer, interactive, node) => {
      const b = node.getBoundingClientRect();
      if (b.width < 1 || b.height < 1) return;
      zones.push({ name: sel, layer, interactive, disabled: off(node),
                   rect: { left: b.left, top: b.top, width: b.width, height: b.height } });
    };
    for (const [sel, layer, interactive] of LAYER) {
      for (const node of document.querySelectorAll(sel)) push(sel, layer, interactive, node);
    }
    // Each dock button on its own, not the container: the container takes no touches by design,
    // and the whole point of `--hold-w` is that the BUTTONS are outside the voice zone.
    for (const node of document.querySelectorAll('.dock-btn')) push('.dock-btn', 'nav', true, node);
    return { faults: window.CrooksTouch.covering(zones), zones: zones.length };
  });

  /* A row of controls that is WIDER THAN ITS OWN CONTAINER. `#context-nav` is
     `overflow-x:auto`, so a chip past its right edge is simply cut off — drawn, reported as
     present by every gate, and unreachable without a horizontal scroll nobody knows is there.
     It is not an overlap, so collision.js cannot see it; it is not off the VIEWPORT, so an
     `onScreen` test cannot either. That is how the second half's chip came to be cut in half
     at 601 CSS px.
     What is measured is the FIXED controls: the landing, the trail step, the list steps and
     the Split chip. `#stack` is deliberately exempt — it is the context TRAIL, it grows with
     the conversation, and its ends fade for exactly that while there is more beyond them
     (web/edges.js). A trail that scrolls is a design; a control that is
     cut off is a defect, and the difference is whether its position depends on how long the
     conversation has been going. */
  async function railFits(where) {
    const rail = await page.evaluate(() => {
      const nav = document.querySelector('#context-nav');
      if (!nav) return null;
      const pad = 8;                      // `.context-nav` is padded 4px each side
      const fixed = Array.from(nav.children)
        .filter((c) => c.id !== 'stack' && c.getBoundingClientRect().width > 0);
      const width = fixed.reduce((sum, c) => sum + c.getBoundingClientRect().width, 0)
        + Math.max(0, fixed.length - 1) * 6;      // the row's gap
      const last = fixed[fixed.length - 1];
      const box = last ? last.getBoundingClientRect() : null;
      return {
        fixedWidth: Math.round(width + pad), client: Math.round(nav.clientWidth),
        controls: fixed.length,
        labels: fixed.map((c) => (c.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 12)),
        lastRight: box ? Math.round(box.right) : 0,
        navRight: Math.round(nav.getBoundingClientRect().right),
        trail: nav.scrollWidth > nav.clientWidth + 1,
      };
    });
    check(at(`the navigation row's own controls fit it ${where}`),
          Boolean(rail && rail.fixedWidth <= rail.client && rail.lastRight <= rail.navRight + 1),
          JSON.stringify(rail));
  }

  async function ladderHolds(where) {
    const measured = await zonesNow();
    check(at(`the layer ladder holds ${where}: nothing covers an interactive layer`),
          measured.faults.length === 0,
          JSON.stringify({ zones: measured.zones, faults: measured.faults.slice(0, 5) }));
  }

  await page.goto(`${BASE}?dev=1`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(900);
  await page.evaluate(() => { for (const b of document.querySelectorAll('.dev-banner')) b.remove(); });
  // [checker, 8 Oct 2026] Until the start-up hands over (web/startup.js, since 29 Sep) a finger
  // anywhere but the dock and the gear only skips it; every tap below is measured on the app.
  await page.waitForFunction(() => !document.getElementById('startup'), null, { timeout: 25000 });

  // ================================================================== §8, measured
  //
  // [checker, 8 Oct 2026] Split is retired: George retired user-facing Split on 20 September
  // (DEC-050), and DEC-050 with DEC-037/038 says Split-specific UI and tests are migration
  // evidence, not permanent requirements (PR #96 retired clickpath.js's Split hops the same
  // way). So the three controls he could not press on 11 September — Split, Merge and Close —
  // are now held to be ABSENT, under the names the sweep requires (tests/test_browser.py), and
  // the checks that need two halves are retired with them: "and the tap on Split actually
  // divided the orb", the ladder and the navigation row "with the orb divided", "both halves
  // are chips a finger can hit, wholly on the screen", "no chip says it holds nothing AND
  // carries its parent's task", "tap the other half's chip", "and the tap on Merge actually
  // folded the halves back", "tap Split (again)" and "and the tap on Close actually let the
  // other half go". The notification tap does not need halves and stays.
  await ladderHolds('on the idle screen');
  const absent = async (label, selector) => {
    const box = await boxOf(selector);
    check(at(`tap ${label} — retired with Split (DEC-050): nothing on the screen offers it`), !box, JSON.stringify(box));
  };
  // Was 'the Split control is on screen, finger-sized, and is what is on top of itself'.
  const splitBox = await boxOf('#branch-bar [data-action="split"], #branch-rail [data-action="split"]');
  check(at('no Split control is on the screen: Split is retired (DEC-050)'), !splitBox, JSON.stringify(splitBox));
  await shot('01-idle');

  await say("show me today's orders");
  await absent('Split', '#branch-bar [data-action="split"], #branch-rail [data-action="split"]');
  check(at('and nothing divided the orb'), (await branchesNow()).count === 1, JSON.stringify(await branchesNow()));

  /* A tap on a notification must not become a recording either — it sits in the band that
     used to be inside the orb zone, under the voice target.

     It puts one there itself, and chooses a code §10 PERMITS (in neither SCREEN_SHOWS nor
     CONTROL_SHOWS): a change proved on the store, which nothing on the glass says by itself.
     The check stands or falls with the pointer machine, rather than with the notification
     policy of whatever screen it happened to be on. */
  const noted = await page.evaluate(() => {
    if (!window.CrooksNotify || typeof window.CrooksNotify.show !== 'function') return false;
    window.CrooksNotify.show({
      text: 'The refund was proved on the store: £40.00 back to the card.',
      class: 'workspace', tone: 'good', code: 'refund_proved',
    });
    return true;
  });
  check(at('a notification the policy permits could be put on the glass to tap'), noted, `shown=${noted}`);
  await sleep(200);
  await tapControl('a notification', '#notes-orb .note, #notes-deck .note', '.note');

  await absent('Merge', '#branch-bar [data-action="merge"], #branch-rail [data-action="merge"]');
  await absent('Close', '#branch-bar [data-action="cancel"], #branch-rail [data-action="cancel"]');
  await shot('03-after-branch-taps');

  // ================================================================== the navigation chrome
  //
  // [checker, 8 Oct 2026] The list is said (first, below) and opened with the Orders icon, under a
  // finger: since 28 September (DEC-063) a spoken list is the model's, and a list the model draws
  // is neither a stop on the trail nor a walk, so it offers no Back and no Next. That is
  // reported for the flow work; the Orders icon's list measures the controls themselves.
  const openOrders = async () => {
    const dock = await boxOf('.dock-btn[data-area="orders"]');
    if (dock) await tap(dock);
    await sleep(1600);
  };
  // [checker, 8 Oct 2026, review note N2] First on a list asked for OUT LOUD, which is George's
  // main path: say a list, open a row, then Home, Back and Next. A list the model draws is not
  // made the walk since 28 September (DEC-063), so Back and Next, held to land in THAT list, are
  // strict expected failures (`knownDefect`); a row opening and Home do not depend on it. Before
  // the Orders icon is touched: once its landing has made today's set, an order of today's opened
  // from anywhere walks that set, which would hide the defect rather than measure it.
  const rowRefs = () => page.evaluate(() => Array.from(document.querySelectorAll('#cards li.row[data-kind="order"][data-ref]')).map((r) => r.dataset.ref));
  const onGlass = () => page.evaluate(() => {
    const c = document.querySelector('#cards .card');
    return { type: (c && c.dataset.type) || '', ref: (c && c.dataset.ref) || '',
             answer: ((document.querySelector('#answer') || {}).textContent || '').trim(), mode: document.body.dataset.mode || '' };
  });
  const saidList = async () => {
    await say("show me today's orders");
    const refs = await rowRefs();
    await tapControl('a row of a list asked for out loud', '#cards li.row[data-kind="order"]', 'li.row');
    await sleep(800);
    return refs;
  };
  let said = await saidList();
  check(at('a list asked for out loud is on the glass with more than one row'), said.length > 1, JSON.stringify(said.length));
  await tapControl('Home on an order opened from a list asked for out loud', '#home-btn', 'home-btn');
  await sleep(900);

  said = await saidList();
  let heard = [];
  const keep = (name, ok, detail) => heard.push({ name, ok, detail });
  await tapControl('Back on an order opened from a list asked for out loud', '#back-btn', 'back-btn', keep);
  await sleep(900);
  const backTo = { ...(await onGlass()), rows: await rowRefs() };
  knownDefect(SPOKEN_LIST_WALK, heard[0].name + ', and it lands on that list',
    heard[0].ok && backTo.type === 'order_list' && JSON.stringify(backTo.rows) === JSON.stringify(said),
    `${heard[0].detail} landed=${backTo.type} rows=${backTo.rows.length} vs ${said.length}`);

  said = await saidList();
  heard = [];
  await tapControl('Next on an order opened from a list asked for out loud', '#next-btn', 'next-btn', keep);
  await sleep(900);
  const nextTo = await onGlass();
  knownDefect(SPOKEN_LIST_WALK, heard[0].name + ', and it opens that list\'s second order',
    heard[0].ok && nextTo.type === 'order' && nextTo.ref === said[1] && new RegExp(`\\b2 of ${said.length}\\b`).test(nextTo.answer),
    `${heard[0].detail} type=${nextTo.type} ref=${nextTo.ref} second row=${said[1]} "${nextTo.answer}"`);

  await openOrders();
  await ladderHolds('beside the cards');
  await railFits('beside the cards, with one half');
  await tapControl('an order card\'s row', '#cards li.row[data-kind="order"]', 'li.row');
  await sleep(700);
  await tapControl('Back', '#back-btn', 'back-btn');
  await sleep(700);
  await tapControl('Home', '#home-btn', 'home-btn');
  await sleep(900);

  await openOrders();
  await tapControl('a card row that opens a record', '#cards [data-ref][data-kind]', 'li.row');
  await sleep(800);
  await tapControl('Next', '#next-btn', 'next-btn');
  await sleep(800);

  // An action chip on a card: something the card offers, which posts the question a voice would.
  await say('show me order 1938');
  await tapControl('an order card\'s tab', '#cards button.tab', 'tab');
  await sleep(600);
  await tapControl('an action chip on a card', '#cards button.rail-chip:not([aria-disabled="true"])', 'rail-chip');
  await sleep(700);

  // The customer surface, which is its own card type, reached the way the scenarios reach it.
  await say('what else has this customer ordered?');
  const custCard = await page.evaluate(() => Array.from(document.querySelectorAll('#cards .card')).map((c) => c.dataset.type || '?'));
  check(at('a customer card is on screen to be tapped'), custCard.includes('customer'), JSON.stringify(custCard));
  await tapControl('a customer card\'s tab', '#cards .card[data-type="customer"] button.tab', 'tab');
  await sleep(600);
  const custRow = await firstOf([
    '#cards .card[data-type="customer"] li.row',
    '#cards .card[data-type="customer"] .row',
    '#cards .card[data-type="customer"] [data-ref]',
    '#cards .card[data-type="customer"] button:not(.tab)',
    '#cards .card[data-type="customer"] .card-title',
    '#cards .card[data-type="customer"]',
  ]);
  await tapControl('something on the customer card', custRow, '');
  await sleep(600);

  // A field. The workspace's own if there is one; the settings sheet's if not — the rule is
  // about a touch that BEGINS in a text field, and either proves it.
  let fieldSel = '#cards .field-input';
  if (!(await boxOf(fieldSel))) {
    await page.evaluate(() => { const s = document.querySelector('#settings'), d = document.querySelector('#dev'); if (d) d.hidden = false; if (s && !s.open && s.showModal) s.showModal(); });
    await sleep(500);
    fieldSel = '#dev-text';
  }
  await bringIntoView(fieldSel);
  await sleep(350);
  await tapControl('a text field', fieldSel, 'input');
  await page.evaluate(() => { const s = document.querySelector('#settings'); if (s && s.open) s.close(); });
  await sleep(500);

  // The dock: navigation chrome sharing the bottom band with the voice zone, and separated
  // from it by `--hold-w` rather than by a z-index argument.
  await reset();
  const dockBox = await boxOf('.dock-btn[data-area="email"]');
  if (dockBox) {
    const before = turns();
    await tap(dockBox);
    await sleep(1600);
    const landed = await clicks();
    check(at('tap a dock icon — navigation beside the voice zone, not under it'),
          dockBox.hitBy.startsWith('itself') && landed.some((c) => c.includes('dock-btn')) && (await tooShort()) === 0,
          JSON.stringify({ hitBy: dockBox.hitBy, landed: landed.slice(0, 4), turns: turns() - before }));
  } else {
    check(at('tap a dock icon — navigation beside the voice zone, not under it'), false, 'no dock icon found');
  }
  await shot('04-context');

  // ================================================================== scrolls
  /* A scroll that begins on a card, and a scroll that begins in the dock band beside the hold
     pill. Neither may become a sentence — the timeline holds 26 scroll reports, the deepest
     971 px, every one of them starting somewhere the voice layer owned. */
  const scrollable = () => page.evaluate(() => {
    const d = document.querySelector('#cards');
    return d ? { top: d.scrollTop, room: d.scrollHeight - d.clientHeight } : { top: 0, room: 0 };
  });
  async function scrollFrom(label, from, dy) {
    await reset();
    const before = { turns: turns(), submits: (await audit() || {}).submits, ...(await scrollable()) };
    await touch('touchStart', [{ x: from.x, y: from.y }]);
    for (let i = 1; i <= 12; i++) { await touch('touchMove', [{ x: from.x, y: Math.round(from.y - (dy * i) / 12) }]); await sleep(22); }
    await touch('touchEnd', []);
    await sleep(900);
    const now = await scrollable();
    const after = { turns: turns(), submits: (await audit() || {}).submits };
    const short = await tooShort();
    check(at(`a scroll that begins ${label} never becomes a sentence`),
          after.turns === before.turns && short === 0 && after.submits === before.submits,
          JSON.stringify({ turns: after.turns - before.turns, too_short: short,
                           submits: (after.submits || 0) - (before.submits || 0),
                           scrolled: now.top - before.top, room: before.room }));
    return { moved: now.top - before.top, room: before.room };
  }

  await openOrders();
  const card = await boxOf('#cards .card');
  if (card) {
    const scrolled = await scrollFrom('on a card', { x: card.x, y: Math.min(card.bottom - 24, card.y + 60) }, 240);
    check(at('and the deck actually scrolled under it'),
          scrolled.room <= 8 || scrolled.moved > 0,
          `scrollTop moved ${scrolled.moved}px with ${scrolled.room}px of room`);
  } else {
    check(at('a scroll that begins on a card never becomes a sentence'), false, 'no card on screen');
  }
  // Beside the dock: inside the band, outside the hold surface's slot — where a thumb rests
  // when it comes up from the bottom of a list. [checker, 8 Oct 2026] The hold surface is the ask
  // bar (web/alpha.js `#ask-bar`); the `#talk` pill this measured is hidden in the alpha product.
  const beside = await page.evaluate(() => {
    const dock = document.querySelector('#dock').getBoundingClientRect();
    const hold = document.querySelector('#ask-bar').getBoundingClientRect();
    return { x: Math.round((dock.left + hold.left) / 2), y: Math.round(dock.top + 10) };
  });
  await scrollFrom('beside the dock', beside, 200);

  // ================================================================== two fingers
  /* A pair, on a voice surface. The recording the first finger started must be discarded
     before either lifts: the timeline holds 18 `multitouch` hold phases and two
     GESTURE_COLLISION turns, which is that discard not happening.

     [checker, 8 Oct 2026] Twice now. On the ask bar, the hold surface beside the cards since the
     alpha product (the `#talk` pill this used is hidden): the bar is a control, not the touch
     machine's, so what is checked there is that nothing is said. This found the bar sending the
     first finger's recording when it lifted (fixed in web/app.js, `abandonAskPress`). And on the
     orb, the touch machine's own voice surface, where the machine's count is checked as before;
     the orb is on the idle screen, so that pair is made after Home, below. */
  async function pairOn(box, gap) {
    await reset();
    const before = turns();
    await touch('touchStart', [{ x: box.x - gap, y: box.y }]);
    await sleep(150);
    await touch('touchStart', [{ x: box.x - gap, y: box.y }, { x: box.x + gap, y: box.y }]);
    for (let i = 1; i <= 9; i++) {
      await touch('touchMove', [{ x: box.x - gap - i * 9, y: box.y }, { x: box.x + gap + i * 9, y: box.y }]);
      await sleep(28);
    }
    await touch('touchEnd', []);
    await sleep(1900);
    return { turns: turns() - before, too_short: await tooShort(), kinds: (await events()).slice(0, 8) };
  }
  const onBar = await pairOn(await boxOf('#ask-bar'), 70);
  check(at('two fingers on the ask bar are a gesture and never a sentence'),
        onBar.turns === 0 && onBar.too_short === 0, JSON.stringify(onBar));

  /* And once more here, late: the trail is long by now (a customer, an order, a customer
     again) and the fixed controls must STILL fit. This is the state the screenshots are taken
     in, and the one the row was cut off in. */
  await railFits('late in a long conversation');

  // ================================================================== voice still works
  /* The other half of the gate. A hold on a deliberate voice target, long enough to be a
     question, must still post one — in both modes, because the voice zone is a different shape
     in each. */
  async function holdAndSend(label, box, ms) {
    await reset();
    const before = turns();
    await touch('touchStart', [{ x: box.x, y: box.y }]);
    await sleep(ms);
    await touch('touchEnd', []);
    await sleep(2800);
    const starts = await holdStarts();
    check(at(`a real hold on ${label} is still a question`),
          turns() > before && starts >= 1,
          JSON.stringify({ turns: turns() - before, hold_starts: starts, events: (await events()).slice(0, 8) }));
  }
  // [checker, 8 Oct 2026] The ask bar is the hold surface beside the cards (was the hidden pill).
  await holdAndSend('the ask bar', await boxOf('#ask-bar'), 1300);

  // And on the orb, on the idle screen, which is the other voice target.
  await page.evaluate(() => { const h = document.querySelector('#home-btn'); if (h) h.click(); });
  await sleep(1800);
  const orb = await boxOf('#orb-frame');
  // The pair on the orb (see "two fingers" above), before the hold on it.
  const onOrb = orb ? await pairOn(orb, 20) : null;
  const pairAudit = await audit();
  check(at('two fingers on the voice surface are a gesture and never a sentence'),
        Boolean(onOrb && onOrb.turns === 0 && onOrb.too_short === 0), JSON.stringify(onOrb));
  check(at('and the machine counted the pair, cancelled the pending voice, and submitted nothing'),
        pairAudit && pairAudit.pairs >= 1 && pairAudit.cancels >= 1 && pairAudit.submits === 0,
        JSON.stringify(pairAudit));
  // Was 'and the spread divided the orb, which is what the pair is for': since V0.5 a spread
  // makes no halves (web/app.js `onHoldMove`), Split being retired (DEC-050).
  check(at('and the spread divided nothing: Split is retired (DEC-050)'),
        (await branchesNow()).count === 1, JSON.stringify(await branchesNow()));
  await shot('05-two-fingers');
  if (orb) await holdAndSend('the orb itself', orb, 1300);
  else check(at('a real hold on the orb itself is still a question'), false, 'no orb frame on screen');
  await shot('06-voice-held');

  // ================================================================== the hard gate
  const total = await page.evaluate(() => ({
    tooShort: (window.__events || []).filter((e) => e.kind === 'recording_too_short').length,
    audit: window.__crooksTouch ? window.__crooksTouch.audit() : null,
  }));
  check(at('ZERO recordings were too short across the whole run'), total.tooShort === 0, `recording_too_short = ${total.tooShort}`);
  // Every control tap above is asserted individually; this is the same claim said once, over
  // the whole run: the only touches that ever submitted anything were the deliberate holds.
  check(at('the machine submitted nothing for any owner but VOICE'),
        total.audit && total.audit.submits <= (total.audit.byOwner.VOICE || 0),
        JSON.stringify(total.audit));
  check(at('and no pointer was left claimed at the end of it'),
        total.audit && total.audit.down_now === 0, JSON.stringify(total.audit));
  check(at('no script error during the whole run'), errors.length === 0, errors.slice(0, 3).join(' | '));
  await context.close();
}

async function main() {
  const browser = await chromium.launch({
    executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  });
  try {
    for (const size of SIZES) await atSize(browser, size);
  } finally {
    await browser.close();
  }
  const ok = checks.every((c) => c.ok);
  process.stdout.write(`${JSON.stringify({ ok, checks, shots, viewports: SIZES.map((s) => s.name) })}\n`);
  return ok ? 0 : 1;
}

main().then((code) => process.exit(code)).catch((e) => {
  process.stdout.write(`${JSON.stringify({ ok: false, checks: checks.concat([{ name: 'touch run', ok: false, detail: String(e && e.stack).slice(0, 600) }]), shots })}\n`);
  process.exit(1);
});

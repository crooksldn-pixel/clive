/* The tablet as it physically is: 601 × 889 CSS px at DPR 1.33, the Galaxy Tab A 8.0 in the
 * owner's hand during the Phase 2 live test. Every check here is a failure that test found
 * on the device and that the 800 × 1280 gate could not see — a footer that swallowed the dock,
 * a second finger that became a sentence.
 *
 *   node scripts/browser/tablet.js http://127.0.0.1:8765 /path/to/screenshots
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...] }.
 */
'use strict';

const { chromium } = require('playwright-core');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
const VIEWPORT = { width: 601, height: 889 };
const DPR = 1.33;
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 300) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: DPR, isMobile: true, hasTouch: true, extraHTTPHeaders: HEADERS });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const from = (m.location && m.location() && m.location().url) || '';
    if (from.includes('/speak')) return;
    // [checker, 8 Oct 2026] Nor /voice/live's 503: with no ElevenLabs key in the fixture world it
    // answers 503 by design (app/routes/voice.py), the page holds on without live words, and the
    // browser logs the refusal as a failed resource. Matched on the URL, as /speak is.
    if (from.includes('/voice/live')) return;
    // With the resource that failed. "Failed to load resource: 400" names nothing, and a
    // browser run that cannot say WHAT failed costs an hour to read.
    errors.push(`console: ${m.text()}${from ? ` <- ${from}` : ''}`);
  });
  const posts = [];
  page.on('request', (r) => { if (r.method() === 'POST') posts.push(r.url().replace(BASE, '')); });
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key","reason":"no voice under test"}' }));
  // A microphone that makes noise, so the encoder produces bytes the way the room does: a
  // recording that ends by mistake must be shown NOT to be sent, not to be too short to send.
  await page.addInitScript(() => {
    const AC = window.AudioContext || window.webkitAudioContext;
    const ac = new AC();
    const dest = ac.createMediaStreamDestination();
    const osc = ac.createOscillator(); const gain = ac.createGain(); gain.gain.value = 0.2;
    osc.frequency.value = 220; osc.connect(gain); gain.connect(dest); osc.start();
    navigator.mediaDevices.getUserMedia = async () => { await ac.resume(); return dest.stream; };
  });
  const shot = async (name) => {
    if (!OUT) return;
    const file = path.join(OUT, `tab-${name}.png`);
    await page.waitForTimeout(450);
    await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
    shots.push(path.basename(file));
  };
  const cdp = await context.newCDPSession(page);
  const touches = (type, points) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: points });
  const sessionId = () => page.evaluate(() => localStorage.getItem('crooks.session') || '');
  const branchesNow = () => page.evaluate(async () => {
    const id = localStorage.getItem('crooks.session') || '';
    const r = await fetch(`/branches?session_id=${encodeURIComponent(id)}`, { cache: 'no-store' });
    const d = await r.json();
    return { count: (d.branches || []).length, focused: d.focused || '', ids: (d.branches || []).map((b) => b.branch_id) };
  });
  const screen = () => page.evaluate(() => ({
    mode: document.body.dataset.mode,
    state: document.querySelector('#stage').dataset.state,
    card: ((document.querySelector('#cards .card') || {}).dataset || {}).type || '',
    ref: ((document.querySelector('#cards .card') || {}).dataset || {}).ref || '',
    answer: ((document.querySelector('#answer') || {}).textContent || '').trim(),
    // What the page is saying, from wherever it is saying it. The one floating bubble is gone:
    // a message now belongs to a control, to the workspace, or — for the two states of the
    // machine itself — to the region above the wordmark (web/notify.js). Read as one string,
    // because what these checks care about is whether the words appeared at all.
    toast: Array.from(document.querySelectorAll('#notes-global .note-words, #notes-orb .note-words, #notes-deck .note-words, #cards .note-control .note-words'))
      .filter((n) => !n.closest('.note').hidden)
      .map((n) => n.textContent.trim()).join(' · '),
    errorCard: Boolean(document.querySelector('#cards .card[data-type="error"]')),
    sub: ((document.querySelector('#state-sub') || {}).textContent || '').trim(),
  }));

  await page.goto(`${BASE}?dev=1`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await page.evaluate(() => { for (const b of document.querySelectorAll('.dev-banner')) b.remove(); });
  const vp = await page.evaluate(() => [innerWidth, innerHeight, +devicePixelRatio.toFixed(2), document.body.dataset.mode]);
  check('the page is at the tablet\'s real size, idle', vp[0] === 601 && vp[1] === 889 && vp[3] === 'orb', JSON.stringify(vp));
  await shot('01-idle');

  // ---- 1. the idle dock is a way in
  const orders = await page.evaluate(() => { const b = document.querySelector('.dock-btn[data-area="orders"]').getBoundingClientRect(); return { x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2) }; });
  const under = await page.evaluate((p) => { const e = document.elementFromPoint(p.x, p.y); return e ? `${e.tagName}${e.id ? '#' + e.id : ''}.${(e.className || '').toString().split(' ')[0]}` : 'none'; }, orders);
  check('nothing sits between the thumb and the dock on the idle screen', /dock-btn|dock-label|svg|path/i.test(under), `under the Orders icon: ${under}`);
  posts.length = 0;
  await page.touchscreen.tap(orders.x, orders.y);
  await sleep(1600);
  const afterDock = await screen();
  check('tapping Orders from idle lands on the order list by the landing command, not a sentence', afterDock.card === 'order_list' && posts.includes('/command') && !posts.includes('/turn'), JSON.stringify({ card: afterDock.card, posts }));
  await shot('02-dock-orders');

  // ---- 2. two fingers on the orb: never a sentence, and no longer a division
  //
  // [checker, 8 Oct 2026] Split is retired: George retired user-facing Split on 20 September
  // (DEC-050), and DEC-050 with DEC-037/038 says Split-specific UI and tests are migration
  // evidence, not permanent requirements (the precedent is PR #96, which retired the Split hops
  // of scripts/browser/clickpath.js). Since V0.5 a spread makes no halves (web/app.js
  // `onHoldMove`) and the stylesheet hides the halves' band (web/alpha.css). So the checks that
  // pinned Split ON the screen now pin it OFF it, and the ones that only make sense with two
  // halves are retired with it: "both halves are on screen as chips a finger can hit", "the
  // Split button divides the orb too", "the first half shows its list; the fresh half shows its
  // own nothing, with a way out" and "each half keeps its own workspace across taps". What a
  // second finger must never do — become a sentence or a hearing error — is still checked.
  // Back to the idle screen the way the tablet gets there: a fresh load of the same session.
  await page.goto(`${BASE}?dev=1`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(900);
  await page.evaluate(() => { for (const b of document.querySelectorAll('.dev-banner')) b.remove(); });
  // [checker, 8 Oct 2026] Until the start-up has handed over (web/startup.js, since 29 Sep), a
  // finger anywhere but the dock and the gear only skips it. The gestures below are measured on
  // the app, so they wait for it, as the tablet does a moment after it opens.
  await page.waitForFunction(() => !document.getElementById('startup'), null, { timeout: 25000 });
  const reloaded = await screen();
  check('a reload brings back what the tablet was looking at, from the Mac', reloaded.mode === 'context' && reloaded.card === 'order_list', JSON.stringify({ mode: reloaded.mode, card: reloaded.card }));
  const before = await branchesNow();
  // Was 'a visible Split control exists while there is one half'.
  const splitChip = await page.evaluate(() => { const c = document.querySelector('#branch-bar [data-action="split"], #branch-rail [data-action="split"]'); if (!c) return null; const b = c.getBoundingClientRect(); return { host: c.parentElement.id, w: Math.round(b.width), h: Math.round(b.height), visible: b.width > 0 && b.height > 0 }; });
  check('no Split control is on the screen: Split is retired (DEC-050)', !(splitChip && splitChip.visible), JSON.stringify(splitChip));
  const orb = await page.evaluate(() => { const b = document.querySelector('#orb-frame').getBoundingClientRect(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; });
  posts.length = 0;
  await touches('touchStart', [{ x: orb.x - 20, y: orb.y }]);                         // first finger: the hold begins
  await sleep(140);
  await touches('touchStart', [{ x: orb.x - 20, y: orb.y }, { x: orb.x + 20, y: orb.y }]); // second finger
  for (let i = 1; i <= 8; i++) {
    await touches('touchMove', [{ x: orb.x - 20 - i * 12, y: orb.y }, { x: orb.x + 20 + i * 12, y: orb.y }]);
    await sleep(30);
  }
  await touches('touchEnd', []);
  await sleep(2200);
  const afterSplit = await screen();
  const branchesAfter = await branchesNow();
  // Was 'a two-finger spread divides the orb' (branches 1 -> 2).
  check('a two-finger spread no longer divides the orb (DEC-050)', branchesAfter.count === before.count && branchesAfter.count < 2, `branches ${before.count} -> ${branchesAfter.count}`);
  check('and sends no speech turn at all', !posts.includes('/turn'), `posted: ${posts.join(', ') || 'nothing'}`);
  check('and shows no hearing error', !afterSplit.errorCard && !/could not hear|cannot hear|closer to the microphone|not running/i.test(afterSplit.answer + ' ' + afterSplit.toast + ' ' + afterSplit.sub) && afterSplit.state !== 'ERROR',
    JSON.stringify({ state: afterSplit.state, answer: afterSplit.answer, toast: afterSplit.toast, sub: afterSplit.sub }));
  // D-10 · §10: a gesture that changes nothing says nothing either. (Was "…because the screen
  // has already said it", with two halves on it.)
  check('and says nothing, because nothing changed',
    afterSplit.toast === '' && branchesAfter.count < 2,
    `toast="${afterSplit.toast}" branches=${branchesAfter.count}`);
  await shot('03-two-fingers');

  // ---- 4. a pinch on the ask bar posts nothing either. With cards up the hold surface is the
  // ask bar along the bottom (web/alpha.js `#ask-bar`; the old `#talk` pill is hidden in the
  // alpha product); two fingers there, drawn together. Was 'a pinch on the dock band merges the
  // halves and sends no speech turn': there are no halves to merge (DEC-050).
  const pill = await page.evaluate(() => { const b = document.querySelector('#ask-bar').getBoundingClientRect(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; });
  posts.length = 0;
  await touches('touchStart', [{ x: pill.x - 110, y: pill.y }]);
  await sleep(140);
  await touches('touchStart', [{ x: pill.x - 110, y: pill.y }, { x: pill.x + 110, y: pill.y }]);
  for (let i = 1; i <= 8; i++) {
    await touches('touchMove', [{ x: pill.x - 110 + i * 12, y: pill.y }, { x: pill.x + 110 - i * 12, y: pill.y }]);
    await sleep(30);
  }
  await touches('touchEnd', []);
  await sleep(2000);
  const merged = await branchesNow();
  check('a pinch on the ask bar sends no speech turn, and leaves one half', merged.count === 1 && !posts.includes('/turn'), `branches=${merged.count} posted=${posts.join(', ') || 'nothing'}`);

  // ---- 5. the workspace comes back after a reload, from the Mac
  // (Was 5c, after two halves had each drawn their own; with one half, the order it drew.)
  const say = async (text) => {
    await page.evaluate(() => { const s2 = document.querySelector('#settings'), d = document.querySelector('#dev'); if (d) d.hidden = false; if (s2 && !s2.open && s2.showModal) s2.showModal(); });
    await page.fill('#dev-text', text);
    await page.press('#dev-text', 'Enter');
    await sleep(1300);
    await page.evaluate(() => { const s2 = document.querySelector('#settings'); if (s2 && s2.open) s2.close(); });
    await sleep(300);
  };
  await say('show me order 1938');
  await page.goto(`${BASE}?dev=1`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1600);
  await page.evaluate(() => { for (const b of document.querySelectorAll('.dev-banner')) b.remove(); });
  await page.waitForFunction(() => !document.getElementById('startup'), null, { timeout: 25000 });   // as above
  const restored = await screen();
  const restoredChips = await page.evaluate(() => document.querySelectorAll('.branch-chip').length);
  // Was '…and both halves with it' (two chips); with Split retired there are none.
  check('after a reload the workspace is back, and no halves with it',
    restored.mode === 'context' && restored.card === 'order' && /1938/.test(restored.ref) && restoredChips === 0,
    JSON.stringify({ mode: restored.mode, card: restored.card, ref: restored.ref, chips: restoredChips }));
  await shot('05-reloaded');

  // ---- 6. an ordinary one-finger hold still records and sends — no delay was added. On the
  // ask bar, where the thumb is when cards are up (was the `#talk` pill, hidden in the alpha
  // product since the ask bar became the voice button).
  const pill2 = await page.evaluate(() => { const b = document.querySelector('#ask-bar').getBoundingClientRect(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; });
  posts.length = 0;
  await touches('touchStart', [{ x: pill2.x, y: pill2.y }]);
  await sleep(900);
  await touches('touchEnd', []);
  await sleep(2500);
  check('a one-finger hold is still a question', posts.includes('/turn'), `posted: ${posts.join(', ') || 'nothing'}`);

  // ---- 7. arm a spoken reply on a thread: the armed state is on the control, unclipped,
  // cancellable.
  //
  // The chip that arms it is Dictate, not Reply. Reply was rendered on twenty-four email cards
  // in the live session and tapped on none, because arming the microphone was all it did — it
  // now opens a reply with the words in a field (app/families/compose.py), and the microphone
  // is the chip beside it, behind the rail's disclosure. Same family, same binding, same band;
  // this opens the disclosure and takes the control that arms.
  await say('which customers need replying to?');
  await page.evaluate(() => { const row = document.querySelector('#cards .row.tappable[data-kind="email_thread"]'); if (row) row.click(); });
  await sleep(1500);
  await page.evaluate(() => { const more = document.querySelector('#cards .rail-more'); if (more) more.click(); });
  await sleep(300);
  await page.evaluate(() => { const c = document.querySelector('#cards .rail-chip[data-mode="ask"][data-family="email.reply"]'); if (c) c.click(); });
  await sleep(1400);
  const armed = await page.evaluate(() => {
    const pill = document.querySelector('#cards .armed-inline');
    const band = document.querySelector('#armed');
    const chip = document.querySelector('#cards .rail-chip[data-mode="ask"][data-family="email.reply"]');
    if (!pill) return { pill: false, band: band && !band.hidden ? band.textContent.trim() : '' };
    const what = pill.querySelector('.armed-what');
    const cancel = pill.querySelector('.armed-cancel');
    const pr = pill.getBoundingClientRect(); const wr = what.getBoundingClientRect(); const cr = cancel.getBoundingClientRect();
    const cardR = pill.closest('.card').getBoundingClientRect();
    return {
      pill: true, text: what.textContent.trim(),
      clipped: what.scrollHeight > what.clientHeight + 2 || what.scrollWidth > what.clientWidth + 2,
      insideCard: pr.left >= cardR.left - 1 && pr.right <= cardR.right + 1,
      onScreen: pr.left >= 0 && pr.right <= innerWidth && pr.bottom <= innerHeight,
      afterRail: Boolean(pill.previousElementSibling && pill.previousElementSibling.classList.contains('rail')),
      cancelH: Math.round(cr.height), height: Math.round(pr.height), lines: Math.round(wr.height / 17),
      chipLit: chip ? chip.getAttribute('aria-pressed') === 'true' : false,
    };
  });
  check('tapping Dictate arms the control itself, in words about the person', armed.pill && /^Replying to \w+/.test(armed.text) && armed.chipLit, JSON.stringify(armed));
  check('the armed state is attached to the rail, inside the card, on screen, unclipped',
    armed.pill && armed.afterRail && armed.insideCard && armed.onScreen && !armed.clipped && armed.height <= 64, JSON.stringify(armed));
  check('and Cancel is a finger-sized control', armed.pill && armed.cancelH >= 44, `cancel=${armed.cancelH}px`);
  await shot('06-armed-reply');
  await page.evaluate(() => { const c = document.querySelector('#cards .armed-inline .armed-cancel'); if (c) c.click(); });
  await sleep(900);
  const gone = await page.evaluate(() => ({ pill: Boolean(document.querySelector('#cards .armed-inline')), band: Boolean(document.querySelector('#armed') && !document.querySelector('#armed').hidden), listening: document.body.dataset.listeningFor || '' }));
  check('Cancel lets it go', !gone.pill && !gone.band && gone.listening === '', JSON.stringify(gone));

  check('no script error during the whole run', errors.length === 0, errors.slice(0, 3).join(' | '));
  await browser.close();
  const ok = checks.every((c) => c.ok);
  process.stdout.write(`${JSON.stringify({ ok, checks, shots, viewport: '601x889@1.33' })}\n`);
  return ok ? 0 : 1;
}

main().then((code) => process.exit(code)).catch((e) => {
  process.stdout.write(`${JSON.stringify({ ok: false, checks: [{ name: 'tablet run', ok: false, detail: String(e && e.message).slice(0, 400) }], shots })}\n`);
  process.exit(1);
});

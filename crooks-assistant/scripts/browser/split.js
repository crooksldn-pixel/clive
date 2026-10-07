/* D-3, in the browser: the split, at both sizes the tablet is ever measured at.
 *
 * The Phase 3 live session, 00:23:57 to 00:24:04 — six `branch_focused` events in nine
 * seconds, and the report's own branch table saying "focus changed with nothing redrawn" four
 * times. The owner: "it just so shows two of the same thing", "the split function doesn't work
 * at all". That is a claim about pixels, so it is checked where the pixels are.
 *
 * Both viewports, in one run, because the 800 x 1280 gate could not see what the physical
 * 601 x 889 tablet did:
 *
 *   node scripts/browser/split.js http://127.0.0.1:8765 /path/to/screenshots
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...] }.
 *
 * [checker, 8 Oct 2026] Split is retired. George retired user-facing Split on 20 September
 * (DEC-050: "Retire the user-facing Split / Half 1 / Half 2 / Merge / Close abstraction"), which
 * says Split-specific UI and tests are migration evidence, not permanent requirements, and
 * web/alpha.css hides the band (MAP.md, Parked). So this file now holds the retirement, at both
 * sizes, in the place the gate already runs (tests/test_browser.py names it): no Split control
 * and no word about it on the idle screen; a list asked for draws its list with no half header;
 * nothing on the screen divides the orb, no half chip and no half header appear; nothing scrolls
 * sideways; two fingers on the ask bar are never a sentence. The checks that needed two halves
 * (the second half's own nothing, two questions on two halves, switching halves, a half that
 * finished elsewhere saying READY) are retired with it; each is named where it was.
 */
'use strict';

const { chromium } = require('playwright-core');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
// The gate's size, and the size of the tablet in the owner's hand. A check that passes on one
// and not the other is the class of defect this file exists for.
const SIZES = [
  { name: '601x889', viewport: { width: 601, height: 889 }, dpr: 1.33 },
  { name: '800x1280', viewport: { width: 800, height: 1280 }, dpr: 1 },
];
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 300) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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
    errors.push(`console: ${m.text()}`);
  });
  const posts = [];
  page.on('request', (r) => { if (r.method() === 'POST') posts.push(r.url().replace(BASE, '')); });
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key","reason":"no voice under test"}' }));
  // A microphone that makes noise, so a recording that must NOT be sent is shown not to be
  // sent rather than being too short to send.
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
    const file = path.join(OUT, `split-${size.name}-${name}.png`);
    await page.waitForTimeout(400);
    await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
    shots.push(path.basename(file));
  };
  // Everything on the glass that identifies a half: the header band, the chips, and the cards
  // in order with what each is about. This is the string the owner was comparing by eye.
  const screen = () => page.evaluate(() => {
    const head = document.querySelector('#branch-head');
    return {
      mode: document.body.dataset.mode,
      head: head && !head.hidden ? head.textContent.replace(/\s+/g, ' ').trim() : '',
      headState: head ? head.dataset.state || '' : '',
      cards: Array.from(document.querySelectorAll('#cards .card')).map((c) => `${c.dataset.type || ''}:${c.dataset.ref || ''}`),
      chips: Array.from(document.querySelectorAll('.branch-chip')).map((c) => ({
        head: c.dataset.head || '', pressed: c.getAttribute('aria-pressed') === 'true',
        text: c.textContent.replace(/\s+/g, ' ').trim(),
        h: Math.round(c.getBoundingClientRect().height),
        onScreen: c.getBoundingClientRect().right <= innerWidth + 1 && c.getBoundingClientRect().left >= -1,
      })),
      offers: Array.from(document.querySelectorAll('#cards .half-empty .rail-chip')).map((b) => ({
        words: b.textContent.trim(), command: b.dataset.offer || '',
        h: Math.round(b.getBoundingClientRect().height),
      })),
      answer: ((document.querySelector('#answer') || {}).textContent || '').trim(),
      toast: ((document.querySelector('#toast') || {}).textContent || '').trim(),
      wide: document.documentElement.scrollWidth > innerWidth + 1,
    };
  });
  const branchesNow = () => page.evaluate(async () => {
    const id = localStorage.getItem('crooks.session') || '';
    const r = await fetch(`/branches?session_id=${encodeURIComponent(id)}`, { cache: 'no-store' });
    const d = await r.json();
    return { count: (d.branches || []).length, focused: d.focused || '', ids: (d.branches || []).map((b) => b.branch_id),
             heads: (d.branches || []).map((b) => (b.headline || {}).title || ''), states: (d.branches || []).map((b) => b.state || '') };
  });
  const say = async (text) => {
    await page.evaluate(() => { const s = document.querySelector('#settings'), d = document.querySelector('#dev'); if (d) d.hidden = false; if (s && !s.open && s.showModal) s.showModal(); });
    await page.fill('#dev-text', text);
    await page.press('#dev-text', 'Enter');
    await sleep(1500);
    await page.evaluate(() => { const s = document.querySelector('#settings'); if (s && s.open) s.close(); });
    await sleep(300);
  };

  // The start-up off, as the other gates that are not about it open the page (web/startup.js).
  await page.goto(`${BASE}?dev=1&startup=off`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await page.evaluate(() => { for (const b of document.querySelectorAll('.dev-banner')) b.remove(); });

  // ---- 1. the idle screen. Was 'a visible Split control is on the idle screen, finger-sized
  // and on screen' and 'and it says what it is for, rather than only what it is called'.
  const splitChip = await page.evaluate(() => {
    const c = document.querySelector('#branch-bar [data-action="split"], #branch-rail [data-action="split"]');
    if (!c) return null;
    const b = c.getBoundingClientRect();
    return { host: c.parentElement.id, h: Math.round(b.height), w: Math.round(b.width), shown: b.width > 0 && b.height > 0 };
  });
  check(at('no Split control is on the idle screen: Split is retired (DEC-050)'),
        !(splitChip && splitChip.shown), JSON.stringify(splitChip));
  const why = await page.evaluate(() => {
    const n = document.querySelector('#branch-bar .branch-why');
    if (!n) return null;
    const b = n.getBoundingClientRect();
    return { text: n.textContent.trim(), shown: b.width > 0 && b.height > 0 };
  });
  check(at('and no line about Split either'), !(why && why.shown && why.text), JSON.stringify(why));

  // ---- 2. one half, asked for a list.
  await say("show me today's orders");
  const first = await screen();
  check(at('the first half draws its list'), first.cards.some((c) => c.startsWith('order_list')), JSON.stringify(first.cards));
  check(at('with one half there is no header to tell apart'), first.head === '', `head="${first.head}"`);

  // Was 'the Split button divides the orb' (two halves), 'both halves are chips a finger can
  // hit, each naming what it is' and 'the screen now says which half it is'.
  posts.length = 0;
  const clicked = await page.evaluate(() => {
    const c = document.querySelector('#branch-bar [data-action="split"], #branch-rail [data-action="split"]');
    if (!c || c.getBoundingClientRect().width === 0) return false;
    c.click();
    return true;
  });
  await sleep(1600);
  const one = await branchesNow();
  check(at('nothing on the screen divides the orb (DEC-050)'), !clicked && one.count <= 1, `clicked=${clicked} branches=${one.count}`);
  check(at('and nothing sends a speech turn'), !posts.includes('/turn'), `posted: ${posts.join(', ') || 'nothing'}`);
  const after = await screen();
  check(at('no half chip and no half header are drawn'), after.chips.length === 0 && after.head === '',
        JSON.stringify({ chips: after.chips, head: after.head }));
  await shot('01-one-half');

  // ---- 3, 4 and 6 are retired with Split: 'tapping the other half redraws…', 'the fresh half
  // says it is the fresh half', 'and says it in words, not in the Mac's state tokens', 'and
  // offers somewhere to go…', 'and nothing about the other half was thrown over this one', 'the
  // second half draws its own place', 'and says so in its header', 'switching halves changes the
  // cards on screen, both ways', 'and changes the header with them', 'the lit chip is the half
  // being talked to', 'the half that answered while he was elsewhere says READY', 'and says it on
  // the selector, not over the half he is reading' and 'and tapping it shows the work it finished'.

  // ---- 5. nothing runs off the side of an eight-inch screen. Was 'no half of this ever
  // scrolls sideways'.
  check(at('nothing here ever scrolls sideways'), !after.wide, 'the page is wider than the screen');

  // ---- 7. a second finger joining a hold is never a sentence. Was held on `#talk-label`, the
  // pill the alpha product hides; the hold surface beside the cards is the ask bar
  // (web/alpha.js `#ask-bar`), and was 'a second finger joining a hold merges and never becomes
  // a sentence': there are no halves to merge.
  const pill = await page.evaluate(() => { const b = document.querySelector('#ask-bar').getBoundingClientRect(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; });
  const cdp = await context.newCDPSession(page);
  const touches = (type, points) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: points });
  posts.length = 0;
  await touches('touchStart', [{ x: pill.x - 90, y: pill.y }]);
  await sleep(140);
  await touches('touchStart', [{ x: pill.x - 90, y: pill.y }, { x: pill.x + 90, y: pill.y }]);
  for (let i = 1; i <= 8; i++) {
    await touches('touchMove', [{ x: pill.x - 90 + i * 10, y: pill.y }, { x: pill.x + 90 - i * 10, y: pill.y }]);
    await sleep(30);
  }
  await touches('touchEnd', []);
  await sleep(1800);
  check(at('a second finger joining a hold never becomes a sentence'),
        !posts.includes('/turn'), `posted: ${posts.join(', ') || 'nothing'}`);

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
  process.stdout.write(`${JSON.stringify({ ok: false, checks: checks.concat([{ name: 'split run', ok: false, detail: String(e && e.message).slice(0, 400) }]), shots })}\n`);
  process.exit(1);
});

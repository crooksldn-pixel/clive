/* D-1 in a real browser: the "Applying…" that never stopped.
 *
 * The live session, 00:21:53: the Mac proved a send VERIFIED and told the tablet so. The
 * tablet went on saying "Applying…" for the rest of the session, and reconciled six times
 * without changing a pixel. The owner asked about it twice and was told it was his screen.
 *
 * This drives the real page: a real card, a real gesture, a real commit — whose answer never
 * arrives — and then the Mac's own word that the change is verified. The surface must leave
 * "Applying…", must never be tapped or posted twice, and must stop being asked about.
 *
 *   node scripts/browser/action_state.js http://127.0.0.1:8765 /path/to/screenshots
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
const PROPOSAL = 'prop_stuck000001';

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 300) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const CARD = (id) => ({
  type: 'confirmation',
  data: {
    proposal_id: id, status: 'pending', risk: 'amber', operation: 'gmail_send_reply',
    title: 'Send the reply', entity: 'Order 1930 — where is it?', entity_kind: 'email_thread',
    entity_ref: 'thread_1', summary: 'The return address, as you dictated it.',
    interaction: { kind: 'tap_commit', label: 'Tap to apply', armed_after_ms: 650 },
    ttl_s: 600, reversible: true, commit: { allowed: true },
  },
});

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: DPR, isMobile: true, hasTouch: true, extraHTTPHeaders: HEADERS });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const commits = [];
  page.on('request', (r) => { if (r.method() === 'POST' && /\/commit$/.test(r.url())) commits.push(r.url().replace(BASE, '')); });
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key","reason":"no voice under test"}' }));
  // The commit that never comes back: the request reaches the Mac and its answer is lost —
  // a backgrounded tab, a dropped tailnet, a re-render. The Mac applied it all the same.
  await page.route('**/actions/*/commit', () => { /* held open, deliberately: nothing is ever fulfilled */ });

  const shot = async (name) => {
    if (!OUT) return;
    const file = path.join(OUT, `action-${name}.png`);
    await page.waitForTimeout(300);
    await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
    shots.push(path.basename(file));
  };
  const surface = () => page.evaluate((id) => {
    const node = document.querySelector(`[data-proposal="${id}"] .action-surface`);
    if (!node) return { present: false };
    const AS = window.CrooksActionState;
    const token = node.dataset.state || '';
    return {
      present: true, token, label: node.querySelector('.action-label').textContent.trim(),
      state: AS ? AS.stateOf(token) : '', terminal: AS ? AS.isTerminal(token) : null,
      disabled: node.getAttribute('aria-disabled'),
      live: typeof liveProposalIds === 'function' ? liveProposalIds().indexOf(id) !== -1 : null,
    };
  }, PROPOSAL);

  await page.goto(`${BASE}?dev=1`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(900);
  await page.evaluate(() => { for (const b of document.querySelectorAll('.dev-banner')) b.remove(); });

  check('the page carries one action state machine, shared by the renderer and the page',
    await page.evaluate(() => Boolean(window.CrooksActionState && window.CrooksActionState.STATES.indexOf('EXECUTING') !== -1 && window.CrooksActionState.TERMINAL.indexOf('VERIFIED') !== -1)), '');

  // ---- 1. a real card, armed, and a real gesture on it
  await page.evaluate((item) => {
    const r = window.CrooksUI.render([item], renderOpts());
    pushContext(r.nodes, [item], 'send the reply');
  }, CARD(PROPOSAL));
  await sleep(900);                                  // the dead time the card is drawn with
  const armed = await surface();
  check('the card is on screen and armed', armed.present && armed.token === 'armed', JSON.stringify(armed));
  await page.evaluate((id) => {
    const s = document.querySelector(`[data-proposal="${id}"] .action-surface`);
    s.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
    s.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
  }, PROPOSAL);
  await sleep(400);
  const applying = await surface();
  check('the gesture puts the card into EXECUTING and the surface says "Applying…"',
    applying.token === 'committing' && applying.state === 'EXECUTING' && applying.label === 'Applying…',
    JSON.stringify(applying));
  check('and it posted exactly one commit', commits.length === 1, commits.join(', '));
  await shot('01-applying');

  // ---- 2. the Mac's word: verified. The answer to the commit itself never arrives.
  await page.route('**/actions/states*', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ session_known: true, states: { [PROPOSAL]: { proposal_id: PROPOSAL, status: 'verified', code: 'verified', kind: 'action', undo_of: null } }, unknown: [], pending: [], undoable: [] }),
  }));
  await page.evaluate(() => reconcileActions('test'));
  await sleep(500);
  const settled = await surface();
  const done = await page.evaluate(() => lastReconcile);
  check('a verified proposal leaves "Applying…" behind — the defect the owner watched',
    settled.label !== 'Applying…' && settled.token !== 'committing', JSON.stringify(settled));
  // And by the ordinary path. The watchdog would have corrected this surface too, and a
  // correction path that has quietly stopped working must not be able to hide behind it.
  check('the card was settled by the Mac\'s own answer, with nothing left for the watchdog',
    Boolean(done) && done.corrected.indexOf(PROPOSAL) !== -1 && done.stuck.length === 0, JSON.stringify(done));
  check('and the card is in a terminal state, disabled, showing what happened',
    settled.terminal === true && settled.state === 'VERIFIED' && settled.disabled === 'true', JSON.stringify(settled));
  check('and it is no longer asked about: the six reconciles of a settled card stop',
    settled.live === false, JSON.stringify(settled));
  check('and the commit was never sent a second time', commits.length === 1, commits.join(', '));
  await shot('02-settled');

  // ---- 3. a second reconcile corrects nothing and re-animates nothing
  const before = await surface();
  await page.evaluate(() => reconcileActions('test again'));
  await sleep(400);
  const after = await surface();
  check('a terminal card is never settled twice', after.token === before.token && after.label === before.label, JSON.stringify({ before, after }));
  await page.unroute('**/actions/states*');

  // ---- 4 was D-2: a merge whose only outstanding thing is an undo offer says nothing is
  // waiting. It drove Split's merge, which was deleted on the owner's ruling of 8 October
  // (DEC-071, ruling 37): there is no merge to say anything after.

  check('no script error during the whole run', errors.length === 0, errors.slice(0, 3).join(' | '));
  await browser.close();
  const ok = checks.every((c) => c.ok);
  process.stdout.write(`${JSON.stringify({ ok, checks, shots, viewport: '601x889@1.33' })}\n`);
  return ok ? 0 : 1;
}

main().then((code) => process.exit(code)).catch((e) => {
  process.stdout.write(`${JSON.stringify({ ok: false, checks: [{ name: 'action state run', ok: false, detail: String(e && e.message).slice(0, 400) }], shots })}\n`);
  process.exit(1);
});

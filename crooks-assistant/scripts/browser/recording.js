/* CLIVE recording what it does, and saying what is on the screen, in a real browser.
 *
 * George, 2 October 2026: "make sure clive is able to really record what it's doing", and "I
 * could ask him what's on screen, but his answer can vary." Driven against the real backend on
 * the golden world with the interaction record on and no test session running
 * (tests/test_recording_browser.py starts both and scripts the model): every question goes
 * through the page's own ask path, a chip on the card is tapped over and over the way a finger
 * that is not being answered does, "who needs a reply" is answered with the plain inbox — the
 * unrelated scene — and then "what's on my screen?" is asked. What the glass shows at that moment
 * is printed beside the checks, so the runner can hold CLIVE's answer (interaction_review) to it
 * word for word.
 *
 *   node scripts/browser/recording.js http://127.0.0.1:8822 /path/to/screenshots
 *   node scripts/browser/recording.js --render page.html picture.png     (the review, drawn)
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...], glass: {...} }.
 */
'use strict';

const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const SIZE = { viewport: { width: 601, height: 889 }, dpr: 1.33 };   // the owner's tablet
const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function launch() {
  const onDisk = process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
  return chromium.launch(fs.existsSync(onDisk) ? { executablePath: onDisk } : {});
}

async function render(htmlFile, pngFile) {
  const browser = await launch();
  try {
    const page = await (await browser.newContext({ viewport: { width: 900, height: 1200 }, deviceScaleFactor: 1 })).newPage();
    await page.goto(`file://${path.resolve(htmlFile)}`, { waitUntil: 'load' });
    await page.screenshot({ path: pngFile, fullPage: true });
    process.stdout.write(JSON.stringify({ ok: true, checks: [{ name: 'the review was drawn', ok: true, detail: pngFile }], shots: [path.basename(pngFile)] }) + '\n');
  } finally {
    await browser.close();
  }
}

async function walk(base, out) {
  const browser = await launch();
  const context = await browser.newContext({ viewport: SIZE.viewport, deviceScaleFactor: SIZE.dpr, isMobile: true, hasTouch: true, extraHTTPHeaders: HEADERS });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key","reason":"no voice under test"}' }));
  // What the page posts to /telemetry, counted as it goes: the record must be getting it with no
  // test session running.
  const posted = [];
  page.on('request', (request) => {
    if (request.url().endsWith('/telemetry') && request.method() === 'POST') {
      try { posted.push(...(JSON.parse(request.postData() || '{}').events || []).map((e) => e.kind)); } catch { /* not ours */ }
    }
  });
  const shot = async (name) => {
    if (!out) return;
    const file = path.join(out, `recording-${name}.png`);
    await page.waitForTimeout(500);
    await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
    shots.push(path.basename(file));
  };
  const ask = (text) => page.evaluate((t) => window.CliveAlpha.ask(t), text);
  // The glass, as the owner sees it: each card's type and every word on it.
  const glass = () => page.evaluate(() => Array.from(document.querySelectorAll('#cards > *'))
    .filter((n) => n.dataset && n.dataset.type && n.dataset.type !== 'context_stack')
    .map((n) => ({ type: n.dataset.type, text: (n.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 1200) })));
  const health = async () => page.evaluate(async () => (await (await fetch('/health', { cache: 'no-store' })).json()).observability || {});

  await page.goto(`${base}/?startup=off`, { waitUntil: 'load' });
  try { await page.waitForFunction(() => document.getElementById('system').dataset.phase === 'online', null, { timeout: 30000 }); } catch { /* checked below */ }
  await sleep(1200);
  const observed = await health();
  check('the Mac says it is recording, and that no test is running', observed.recording && !observed.test_session, JSON.stringify(observed));

  await ask('show me order 1938');
  await sleep(1500);
  const order = await glass();
  check('the order is on the glass', order.some((c) => c.type === 'order' && /1938/.test(c.text)), JSON.stringify(order.map((c) => c.type)));
  await shot('1-order');

  // A finger that is not being answered: the same control on the order, again and again — a tab
  // when the card has them, else its first chip — found afresh each time, as a finger finds it.
  const tabs = await page.locator('#cards [data-type="order"] [role="tab"]').count();
  const control = tabs ? page.locator('#cards [data-type="order"] [role="tab"]').nth(tabs > 1 ? 1 : 0)
    : page.locator('#cards [data-type="order"] .rail-chip').first();
  let tapped = 0;
  for (let i = 0; i < 4; i += 1) {
    try { await control.tap({ timeout: 2000 }); tapped += 1; } catch { /* a control that went away is a tap that did not land */ }
    await sleep(350);
  }
  await page.keyboard.press('Escape').catch(() => {});
  await sleep(600);
  check('a control on the order was tapped four times', tapped === 4, `tapped ${tapped} (${tabs ? 'tab' : 'chip'})`);

  await ask('who needs a reply');
  await sleep(1500);
  const inbox = await glass();
  check('"who needs a reply" drew the plain inbox', inbox.some((c) => c.type === 'email_list'), JSON.stringify(inbox.map((c) => c.type)));
  await shot('2-who-needs-a-reply');

  // What is up the moment the question is asked: CLIVE's answer is held to this.
  const before = await glass();
  await ask("what's on my screen?");
  await sleep(1500);
  const answer = await page.evaluate(() => (document.getElementById('answer') || {}).textContent || '');
  await shot('3-whats-on-my-screen');
  await sleep(2600);   // one more telemetry flush
  check('the page posted its account with no test session running', posted.includes('render') && posted.includes('turn_submitted'),
    JSON.stringify([...new Set(posted)].slice(0, 20)));
  check('no page errors', errors.length === 0, errors.join(' | '));
  await browser.close();
  return { glass: before, answer: answer.trim() };
}

async function main() {
  if (process.argv[2] === '--render') return render(process.argv[3], process.argv[4]);
  const seen = await walk(process.argv[2] || 'http://127.0.0.1:8822', process.argv[3] || '');
  process.stdout.write(JSON.stringify({ ok: checks.every((c) => c.ok), checks, shots, ...seen }) + '\n');
  return null;
}

main().catch((e) => {
  process.stdout.write(JSON.stringify({ ok: false, checks: [...checks, { name: 'recording.js ran', ok: false, detail: String(e && e.stack || e).slice(0, 600) }], shots }) + '\n');
  process.exitCode = 1;
});

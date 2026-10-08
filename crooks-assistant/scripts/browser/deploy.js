/* Deploy now in a real browser, on the phone and the tablet (DEC-072).
 *
 *   node scripts/browser/deploy.js http://localhost:PORT [/path/to/screenshots] '<flow json>'
 *
 * Driven by tests/test_deploy_browser.py, which serves the real backend on the golden world, with the
 * trunk's head ahead of what CLIVE runs and green, the release service installed, on and waiting only for
 * his approval, a stand-in for its path unit that runs the real release service the moment his approval
 * lands, and the owner's passkey (`flow.passkey`) for Chromium's virtual authenticator. Judged on the glass:
 *
 *   - on the tablet (800 x 1280) and the phone (390 x 844), the Builds screen carries "Ready to go live"
 *     straight under its heading: the version's title, the commits since what is live in their own
 *     titles, acceptance passed on this exact version, and "Hold to deploy"; no version id on its face;
 *     nothing wider than the screen and every control a finger's size;
 *   - a press let go early does nothing; held, the passkey is asked, and the deploy starts at once;
 *   - the phone follows it stage by stage, in order (Checks, Installing, Health), to Done, then Kept,
 *     the page asking /whoami itself and handing its token to CLIVE, with no tap of his after the hold;
 *   - the tablet, opened again, shows the deploy kept and offers nothing more; no script errs.
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...] }.
 */
'use strict';

const { chromium } = require('playwright-core');
const path = require('path');

const BASE = (process.argv[2] || 'http://localhost:8765').replace(/\/$/, '');
const OUT = process.argv[3] || '';
const FLOW = JSON.parse(process.argv[4] || '{}');
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const PHONE = { name: 'phone', viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true };
const TABLET = { name: 'tablet', viewport: { width: 800, height: 1280 }, deviceScaleFactor: 1.5, isMobile: true, hasTouch: true };
const TITLE = "Days left count London's day";
const SHA8 = '11111111';

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });

async function shot(page, name) {
  if (!OUT) return;
  const file = path.join(OUT, `${name}.png`);
  await page.waitForTimeout(400);
  await page.screenshot({ path: file, animations: 'disabled' });
  shots.push(path.basename(file));
}

async function open(browser, size, passkey) {
  const { name, ...options } = size;
  const context = await browser.newContext({ ...options, extraHTTPHeaders: HEADERS });
  const page = await context.newPage();
  const errors = [];
  const answers = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/\/speak|Failed to load resource/.test(m.text())) errors.push(m.text()); });
  page.on('response', (r) => { const u = new URL(r.url()); if (/^\/(release|whoami)/.test(u.pathname)) answers.push([u.pathname + u.search, r.status(), Date.now()]); });
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key"}' }));
  if (passkey) {
    const cdp = await context.newCDPSession(page);
    await cdp.send('WebAuthn.enable');
    const { authenticatorId } = await cdp.send('WebAuthn.addVirtualAuthenticator', { options: {
      protocol: 'ctap2', transport: 'internal', hasResidentKey: true, hasUserVerification: true,
      isUserVerified: true, automaticPresenceSimulation: true } });
    await cdp.send('WebAuthn.addCredential', { authenticatorId, credential: {
      credentialId: passkey.id, isResidentCredential: false, rpId: passkey.rp_id, privateKey: passkey.key, signCount: 1 } });
  }
  await page.goto(`${BASE}/?startup=off`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#alpha-home .alpha-row[data-alpha="builds"]', { timeout: 20000 });
  await page.waitForTimeout(400);
  await page.locator('#alpha-home .alpha-tools .alpha-row[data-alpha="builds"]').click();
  const shown = await page.waitForSelector('.bd.is-open .dn-card', { timeout: 20000 }).then(() => true).catch(() => false);
  if (!shown) {
    const dn = await page.evaluate(() => { const d = document.querySelector('.dn'); return d ? d.textContent : 'no .dn'; });
    throw new Error(`${name}: no Deploy now card on the Builds screen (${dn}; ${JSON.stringify(answers)}; ${errors.join(' | ')})`);
  }
  await page.waitForTimeout(400);
  return { context, page, errors, answers, name };
}

function card(page) {
  return page.evaluate(() => {
    const c = document.querySelector('.dn .dn-card');
    if (!c) return null;
    const face = [...c.childNodes].filter((n) => !(n.tagName === 'DETAILS')).map((n) => n.textContent).join(' ');
    return {
      kind: c.classList.contains('is-offer') ? 'offer' : 'progress',
      eyebrow: (c.querySelector('.dn-eyebrow') || {}).textContent || '',
      title: (c.querySelector('.dn-title') || {}).textContent || '',
      changes: [...c.querySelectorAll('.dn-change')].map((n) => n.textContent),
      meta: (c.querySelector('.dn-meta') || {}).textContent || '',
      hold: (c.querySelector('.dn-hold') || {}).textContent || '',
      line: (c.querySelector('.dn-line') || {}).textContent || '',
      stages: [...c.querySelectorAll('.dn-stage')].map((n) => [n.textContent, n.className.replace('dn-stage ', '')]),
      face,
      after: (document.querySelector('.dn').previousElementSibling || {}).className || '',
      offers: document.querySelectorAll('.dn .dn-card.is-offer').length,
    };
  });
}

async function fits(page, who) {
  const found = await page.evaluate(() => {
    const w = document.documentElement.clientWidth;
    const wide = [...document.querySelectorAll('.dn *')].filter((n) => {
      const r = n.getBoundingClientRect();
      return r.width > 0 && r.right > w + 1 && !n.closest('details:not([open])');
    }).map((n) => n.className || n.tagName).slice(0, 5);
    const small = [...document.querySelectorAll('.dn button, .dn summary')].filter((n) => {
      const r = n.getBoundingClientRect();
      return r.width > 0 && (r.height < 43.5 || r.width < 43.5);
    }).map((n) => `${n.className}:${Math.round(n.getBoundingClientRect().height)}`).slice(0, 5);
    return { wide, small };
  });
  check(`${who}: nothing on the card is wider than the screen, and every control is a finger's size`,
    found.wide.length === 0 && found.small.length === 0, `${found.wide.join(', ')} ${found.small.join(', ')}`);
}

async function offered(view) {
  const c = await card(view.page);
  check(`${view.name}: the Builds screen offers the version waiting to go live, with Hold to deploy`,
    c && c.kind === 'offer' && c.eyebrow === 'Ready to go live' && c.title === TITLE && c.hold === 'Hold to deploy', JSON.stringify(c));
  check(`${view.name}: it lists the changes since what is live in their own titles, and acceptance on this exact version`,
    c && c.changes.join('|') === `${TITLE}|Seven fixes from the review` && /2 changes since what’s live · acceptance passed on this exact version/.test(c.meta),
    c && `${c.changes.join('|')} / ${c.meta}`);
  check(`${view.name}: straight under the Builds heading, with no version id on its face`,
    c && c.after === 'bd-hello' && !c.face.includes(SHA8), c && `${c.after} / ${c.face.slice(0, 200)}`);
  await fits(view.page, view.name);
}

async function run(browser) {
  const tablet = await open(browser, TABLET, null);
  await offered(tablet);
  await shot(tablet.page, 'deploy-tablet-01-offer');

  const phone = await open(browser, PHONE, FLOW.passkey);
  await offered(phone);
  await shot(phone.page, 'deploy-phone-01-offer');

  // A press let go early: nothing asked.
  const hold = phone.page.locator('.dn-hold');
  await hold.scrollIntoViewIfNeeded();
  const box = await hold.boundingBox();
  await phone.page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await phone.page.mouse.down();
  await phone.page.waitForTimeout(300);
  await phone.page.mouse.up();
  await phone.page.waitForTimeout(1200);
  check('phone: a press let go early asks nothing and deploys nothing',
    !phone.answers.some(([url]) => url.startsWith('/release/deploy/challenge')) && (await hold.textContent()) === 'Hold to deploy',
    JSON.stringify(phone.answers));

  // Held: the passkey (the virtual authenticator answers as Face ID would), then the deploy.
  await phone.page.mouse.down();
  await phone.page.waitForTimeout(1200);
  await phone.page.mouse.up();
  const started = await phone.page.waitForSelector('.dn-card.is-progress', { timeout: 15000 }).then(() => true).catch(() => false);
  const approved = phone.answers.find(([url, code]) => url === '/release/deploy' && code === 200);
  const challenged = phone.answers.find(([url, code]) => url === '/release/deploy/challenge' && code === 200);
  check('phone: held, it asks for his passkey for that version and sends the approval', started && approved && challenged,
    JSON.stringify(phone.answers));

  // Followed, stage by stage, with no tap of his.
  const seen = [];
  let mid = false;
  let last = null;
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    last = await card(phone.page);
    const now = last && last.stages.filter(([, state]) => state === 'is-now').map(([label]) => label)[0];
    if (now && seen[seen.length - 1] !== now) seen.push(now);
    if (now === 'Installing' && !mid) { mid = true; await shot(phone.page, 'deploy-phone-02-installing'); }
    if (last && last.eyebrow === 'Deployed and kept') break;
    await phone.page.waitForTimeout(250);
  }
  const order = ['Checks', 'Installing', 'Health'].filter((s) => seen.includes(s));
  check('phone: each stage is shown as it is reached, in order: Checks, Installing, Health',
    order.length === 3 && seen.indexOf('Checks') < seen.indexOf('Installing') && seen.indexOf('Installing') < seen.indexOf('Health'),
    seen.join(' > '));
  const firstCheck = phone.answers.find(([url, code]) => url.startsWith('/release/deploy?progress=1') && code === 200);
  check('phone: the deploy started at once, not on the timer',
    approved && seen.length && seen[0] !== undefined && firstCheck && firstCheck[2] - approved[2] < 10000,
    `${seen.join(' > ')} ${approved && firstCheck ? firstCheck[2] - approved[2] : '?'} ms`);
  check('phone: done, then kept, with every stage lit',
    last && last.eyebrow === 'Deployed and kept' && last.stages.every(([, state]) => state === 'is-lit'), JSON.stringify(last));
  check('phone: the line says his phone got through on the new build',
    last && last.line === 'Deployed and kept: your phone got through on the new build.', last && last.line);
  const older = await phone.page.evaluate(() => { const l = document.querySelector('.bd-release'); return l ? getComputedStyle(l).display : 'none'; });
  check("phone: the release service's older line steps aside while the card says more", older === 'none', older);
  const whoami = phone.answers.findIndex(([url]) => url === '/whoami');
  const kept = phone.answers.findIndex(([url, code]) => url === '/release/kept' && code === 200);
  check('phone: the page asked /whoami itself and handed its token to CLIVE', whoami >= 0 && kept > whoami,
    JSON.stringify(phone.answers.filter(([url]) => !url.includes('progress'))));
  await fits(phone.page, 'phone, kept');
  await shot(phone.page, 'deploy-phone-03-kept');
  check('phone: no script error', phone.errors.length === 0, phone.errors.join(' | '));

  // The tablet, opened again: the deploy kept, nothing more to deploy.
  await tablet.page.reload({ waitUntil: 'domcontentloaded' });
  await tablet.page.waitForSelector('#alpha-home .alpha-row[data-alpha="builds"]', { timeout: 20000 });
  await tablet.page.locator('#alpha-home .alpha-tools .alpha-row[data-alpha="builds"]').click();
  await tablet.page.waitForSelector('.bd.is-open .dn-card.is-progress', { timeout: 20000 }).catch(() => null);
  await tablet.page.waitForTimeout(600);
  const after = await card(tablet.page);
  check('tablet: opened again, it shows the deploy kept and offers nothing more',
    after && after.kind === 'progress' && after.eyebrow === 'Deployed and kept' && after.offers === 0, JSON.stringify(after));
  await fits(tablet.page, 'tablet, kept');
  await shot(tablet.page, 'deploy-tablet-02-kept');
  check('tablet: no script error', tablet.errors.length === 0, tablet.errors.join(' | '));
  await tablet.context.close();
  await phone.context.close();
}

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CROOKS_CHROMIUM || undefined });
  try {
    await run(browser);
  } catch (error) {
    check('the run finished', false, error && error.stack);
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ ok: checks.length > 0 && checks.every((c) => c.ok), checks, shots }));
})();

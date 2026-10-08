/* Staff links in a real Chromium, at a phone's size (ruling 35 of DEC-071, DEC-075; docs/STAFF_LINKS.md):
 * a member of the team with no Tailscale at all joins CLIVE through the team's door with a link and a
 * code, works their list, and is signed out by George from People. Run by tests/test_staff_links_browser.py,
 * which serves the real app and its door and makes the links as George's passkey would have.
 *
 *   STAFF_LINK_TOKEN=… STAFF_LINK_CODE=… STAFF_LINK_OTHER=… STAFF_LINK_OTHER_CODE=… \
 *     node scripts/browser/staff_links.js http://127.0.0.1:8791 /path/to/screenshots
 *
 * The phone's requests carry X-Clive-Door, as the host's Caddy adds it for team.crooksldn.com; George's
 * carry nothing, which this harness treats as the owner (the server itself, CROOKS_LOCAL_OWNER).
 *
 * What it proves, on the glass and on the Mac's own record:
 *   - a phone that is not signed in is sent to the join page, which says what to do;
 *   - the link opens a code box; a wrong code says how many tries are left; the right one lands on
 *     Today as that person, with the sign-in an HttpOnly, Secure, SameSite=Strict __Host- cookie that
 *     no script can read;
 *   - from the phone, a job is taken by tap, and George's own routes do not exist;
 *   - the same link a second time does not work;
 *   - George sees the phone on People, sees a new link and its code the way his passkey would show
 *     them, and signs the phone out; the phone is back at the join page;
 *   - nothing scrolls sideways, nothing to tap is smaller than a thumb, and no page error.
 * Prints one JSON object: { ok, checks: [{ name, ok, detail }], shots }.
 */
'use strict';

const { chromium } = (() => {
  try { return require('playwright'); } catch { return require('playwright-core'); }
})();
const fs = require('fs');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8791';
const OUT = process.argv[3] || '';
const TOKEN = process.env.STAFF_LINK_TOKEN || '';
const CODE = process.env.STAFF_LINK_CODE || '';
const OTHER = process.env.STAFF_LINK_OTHER || '';
const OTHER_CODE = process.env.STAFF_LINK_OTHER_CODE || '';
const DOOR = { 'X-Clive-Door': 'team' };
const PHONE = { width: 390, height: 844 };
const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1';
// A status the page expects (a phone not signed in, a door that has no such route) is said by Chromium as a
// console error; it is not a page error.
const EXPECTED = /Failed to load resource: the server responded with a status of (401|403|404)/;

const checks = [];
const shots = [];
const check = (name, ok, detail) => { checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail) }); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const text = (page, sel) => page.$eval(sel, (el) => el.textContent.trim()).catch(() => '');

async function context(browser, headers) {
  const made = await browser.newContext({ viewport: PHONE, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
    userAgent: IPHONE, extraHTTPHeaders: headers || {} });
  const errors = [];
  made.on('page', (page) => {
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('console', (m) => { if (m.type() === 'error' && !EXPECTED.test(m.text())) errors.push(m.text()); });
  });
  return { made, errors };
}

async function shot(page, name, full) {
  if (!OUT) return;
  const file = path.join(OUT, `staff-links-${name}.png`);
  await page.screenshot({ path: file, fullPage: Boolean(full) });
  shots.push(file);
}

async function fits(page) {
  return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
}

async function smallTargets(page) {
  return page.$$eval('button, a, input', (nodes) => nodes.filter((n) => {
    if (n.closest('[hidden]') || n.offsetParent === null) return false;
    const r = n.getBoundingClientRect();
    return r.width > 0 && r.height < 44;
  }).map((n) => `${n.tagName.toLowerCase()}#${n.id}.${n.className}:${Math.round(n.getBoundingClientRect().height)}`));
}

async function settled(page) {
  await page.waitForFunction(() => !document.body.classList.contains('loading'), null, { timeout: 20000 });
  await sleep(300);
}

async function asked(page, route, init) {
  return page.evaluate(async ([url, options]) => {
    const r = await fetch(url, Object.assign({ credentials: 'same-origin', headers: { Accept: 'application/json' } }, options || {}));
    let body = {};
    try { body = await r.json(); } catch (e) { body = {}; }
    return { status: r.status, body };
  }, [route, init || {}]);
}

async function phone(browser) {
  const { made, errors } = await context(browser, DOOR);
  let page = await made.newPage();

  // Not signed in: Today sends the phone to the join page, which says what to do.
  await page.goto(`${BASE}/today`, { waitUntil: 'load' });
  await page.waitForURL(/\/join$/, { timeout: 10000 }).catch(() => {});
  await page.waitForSelector('#title');
  await sleep(200);
  check('a phone not signed in is sent to the join page, which says what to do',
    /\/join$/.test(page.url()) && /open the staff link George sent you/.test(await text(page, '#line')) && !(await page.isVisible('#form')),
    `${page.url()} :: ${await text(page, '#line')}`);
  await shot(page, 'no-link');

  // The link: a code box.
  page = await made.newPage();
  await page.goto(`${BASE}/join#${TOKEN}`, { waitUntil: 'load' });
  await page.waitForSelector('#code', { state: 'visible', timeout: 10000 }).catch(() => {});
  const box = await page.$eval('#code', (el) => ({ mode: el.inputMode, auto: el.autocomplete, focused: document.activeElement === el,
    height: el.getBoundingClientRect().height })).catch(() => ({}));
  check('the link opens one box for the code, a number pad, ready to type', box.mode === 'numeric' && box.auto === 'one-time-code'
    && box.focused && box.height >= 56 && await page.isVisible('#go'), JSON.stringify(box));
  check('the join page fits a phone and every target is a thumb\'s size', await fits(page) && (await smallTargets(page)).length === 0,
    (await smallTargets(page)).join(', '));
  check('the in-app browser warning is not shown in a real browser', !(await page.isVisible('#in-app')));
  await shot(page, 'code');

  // A wrong code.
  const wrong = String((Number(CODE) + 1) % 1000000).padStart(6, '0');
  await page.fill('#code', wrong);
  await page.click('#go');
  await page.waitForFunction(() => /isn't right/.test(document.querySelector('#line').textContent), null, { timeout: 8000 }).catch(() => {});
  check('a wrong code says so, with the tries left', /That code isn't right\. 4 tries left\./.test(await text(page, '#line')), await text(page, '#line'));
  await shot(page, 'wrong-code');

  // The right code: Today, as Ana.
  await page.fill('#code', `${CODE.slice(0, 3)} ${CODE.slice(3)}`);
  await page.click('#go');
  await page.waitForURL(/\/today$/, { timeout: 10000 }).catch(() => {});
  await settled(page).catch(() => {});
  const me = await asked(page, '/today/state');
  check('the right code lands on Today, signed in as that person', /\/today$/.test(page.url()) && me.status === 200
    && me.body.me && me.body.me.id === 'ana-fixture' && me.body.me.owner === false, `${page.url()} ${me.status} ${JSON.stringify(me.body.me)}`);
  check('CLIVE greets them by name', /, Ana\./.test(await text(page, '#line')), await text(page, '#line'));
  check('Today fits the phone', await fits(page));
  await shot(page, 'today');

  // The sign-in: a cookie no script can read.
  const jar = (await made.cookies()).find((c) => c.name === '__Host-clive_team');
  check('the sign-in is an HttpOnly, Secure, SameSite=Strict __Host- cookie for the whole site',
    Boolean(jar) && jar.httpOnly && jar.secure && jar.sameSite === 'Strict' && jar.path === '/', JSON.stringify(jar || {}));
  check('and no script on the page can read it', !(await page.evaluate(() => document.cookie)).includes('clive_team'));

  // Work, by tap.
  const take = await page.$('#now .go');
  const before = take ? await take.textContent() : '';
  if (take) await take.click();
  await page.waitForFunction((b) => document.querySelector('#now .go') && document.querySelector('#now .go').textContent !== b, before, { timeout: 8000 }).catch(() => {});
  const after = await asked(page, '/today/state');
  const theirs = [...(after.body.work.mine_found || []), ...(after.body.work.mine || [])].filter((j) => j.claimed_by === 'ana-fixture');
  check('a job is taken with one tap, in their name', before === 'Take it' && theirs.length === 1, `${before} -> ${JSON.stringify(theirs.map((j) => j.title))}`);
  await shot(page, 'taken');

  // George's routes do not exist from here.
  const owners = [];
  for (const [route, init] of [['/connections/state'], ['/objectives'], ['/whoami'], ['/health'],
    ['/today/assign', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"title":"x"}' }],
    ['/staff-links/ana-fixture/make', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }]]) {
    owners.push(`${route} ${(await asked(page, route, init)).status}`);
  }
  check("George's routes do not exist through the team's door", owners.every((o) => / 404$/.test(o)), owners.join(', '));
  await page.close();
  return { made, errors };
}

async function usedAgain(browser) {
  const { made, errors } = await context(browser, DOOR);
  const page = await made.newPage();
  await page.goto(`${BASE}/join#${TOKEN}`, { waitUntil: 'load' });
  await page.waitForSelector('#code', { state: 'visible', timeout: 10000 }).catch(() => {});
  await page.fill('#code', CODE);
  await page.click('#go');
  await page.waitForFunction(() => /doesn't work/.test(document.querySelector('#title').textContent), null, { timeout: 8000 }).catch(() => {});
  check('the same link a second time does not work, and says to ask George for a new one',
    (await text(page, '#title')) === "This link doesn't work" && /Ask George for a new one/.test(await text(page, '#line')),
    `${await text(page, '#title')} :: ${await text(page, '#line')}`);
  await shot(page, 'used-again');
  check('no page errors on a second phone', errors.length === 0, errors.join(' | '));
  await made.close();
}

async function george(browser) {
  const { made, errors } = await context(browser, {});
  // His passkey, as the browser would give it, and the answer the server gives after checking it: the
  // server's own check is tests/test_staff_links.py's; this is what his screen does with the answer.
  await made.addInitScript(() => {
    const get = async () => ({ id: 'pk', rawId: new Uint8Array([1]).buffer, type: 'public-key', response: {
      clientDataJSON: new Uint8Array([1]).buffer, authenticatorData: new Uint8Array([1]).buffer,
      signature: new Uint8Array([1]).buffer, userHandle: null } });
    Object.defineProperty(navigator, 'credentials', { configurable: true, value: { get } });
  });
  await made.route('**/connections/approve', (route) => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ ok: true, publicKey: { challenge: 'AQ', allowCredentials: [] } }) }));
  await made.route('**/staff-links/kit/make', (route) => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ ok: true, link: `https://team.example.test/join#${OTHER}`, code: OTHER_CODE,
      expires_at: new Date(Date.now() + 12 * 3600e3).toISOString(), name: 'Kit' }) }));
  const page = await made.newPage();
  page.on('dialog', (dialog) => dialog.accept());
  await page.goto(`${BASE}/today#people`, { waitUntil: 'load' });
  await settled(page);
  const people = await text(page, '#owner-people');
  check('/today#people opens on People', await page.isVisible('#owner-people') && !(await page.isVisible('#owner-team')));
  check('George sees the phone that joined, by staff link, with Sign out', /Ana Fixture/.test(people)
    && /Can use CLIVE on their phone, by staff link/.test(people) && /iPhone, joined today/.test(people)
    && Boolean(await page.$('#owner-people .flag.sub .pill:has-text("Sign out")')), people.slice(0, 400));
  check('everyone on the team can be given a staff link', (await page.$$('#owner-people .pill:has-text("staff link")')).length >= 3);
  check('People fits the phone and every target is a thumb\'s size', await fits(page) && (await smallTargets(page)).length === 0,
    (await smallTargets(page)).join(', '));
  await shot(page, 'george-people', true);

  // A new link for Kit: shown once, the code in big type, with Share or Copy and Done.
  await page.click('#owner-people .flag:has-text("Kit") .pill:has-text("staff link")');
  await page.waitForSelector('.link-made', { timeout: 8000 }).catch(() => {});
  const panel = await text(page, '.link-made');
  check("Kit's link shows once: the code spaced in big type, the link, Copy and Done",
    (await text(page, '.link-code')) === `${OTHER_CODE.slice(0, 3)} ${OTHER_CODE.slice(3)}` && panel.includes(OTHER)
    && /not in the same message/.test(panel) && Boolean(await page.$('.link-made .pill:has-text("Copy the link")'))
    && Boolean(await page.$('.link-made .pill:has-text("Done")')), panel.slice(0, 300));
  check('the link panel fits the phone', await fits(page));
  await shot(page, 'george-link-made');
  await page.click('.link-made .pill:has-text("Done")');
  await sleep(200);
  check('Done puts the link away, never to be shown again', !(await page.$('.link-made')));

  // Sign Ana's phone out.
  await page.click('#owner-people .flag.sub .pill:has-text("Sign out")');
  await page.waitForFunction(() => /signed out/.test((document.querySelector('.ot-bar-text') || {}).textContent || ''), null, { timeout: 8000 }).catch(() => {});
  const board = await asked(page, '/today/state');
  const phones = ((board.body.links || {})['ana-fixture'] || {}).phones || [];
  check('George signs the phone out from People', phones.length === 1 && phones[0].state === 'signed_out',
    JSON.stringify(phones));
  await shot(page, 'george-signed-out', true);
  check('no page errors on George\'s side', errors.length === 0, errors.join(' | '));
  await made.close();
}

async function signedOut(phoneContext) {
  const page = await phoneContext.made.newPage();
  await page.goto(`${BASE}/today`, { waitUntil: 'load' });
  await page.waitForURL(/\/join$/, { timeout: 10000 }).catch(() => {});
  await page.waitForSelector('#title');
  await sleep(200);
  check('the phone George signed out is back at the join page', /\/join$/.test(page.url())
    && /open the staff link George sent you/.test(await text(page, '#line')), page.url());
  await shot(page, 'phone-signed-out');
  check('no page errors on the phone', phoneContext.errors.length === 0, phoneContext.errors.join(' | '));
  await phoneContext.made.close();
}

async function main() {
  const onDisk = process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
  const browser = await chromium.launch(fs.existsSync(onDisk) ? { executablePath: onDisk } : {});
  try {
    const joined = await phone(browser);
    await usedAgain(browser);
    await george(browser);
    await signedOut(joined);
  } finally {
    await browser.close();
  }
  const ok = checks.every((c) => c.ok);
  process.stdout.write(JSON.stringify({ ok, checks, shots }) + '\n');
  process.exit(ok ? 0 : 1);
}

main().catch((error) => {
  process.stdout.write(JSON.stringify({ ok: false, checks: [...checks, { name: 'browser run', ok: false, detail: String(error && error.stack || error) }], shots }) + '\n');
  process.exit(1);
});

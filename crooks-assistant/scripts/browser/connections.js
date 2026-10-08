/* The Connections screen in Chromium, at a phone, the Tab A and a laptop (tests/connections_world.py).
 *
 *   node scripts/browser/connections.js http://127.0.0.1:PORT <shots folder> <prefix> '<json list of secrets>'
 *
 * The screen's job is to say at a glance what CLIVE is connected to and what each connection lets
 * it do, put right what is broken and add what is missing. So what is judged here is what is on the
 * glass, in the world the Python side served: what needs the owner comes first; a working
 * connection asks for no key and shows when it was last checked; a broken key asks for exactly one;
 * a service he has not added shows its key box only once he taps Connect, and then exactly one;
 * every details disclosure starts closed; the voice settings are still there behind ElevenLabs;
 * nothing is wider than the screen; every control is at least 44 px; reduced motion leaves nothing
 * moving; and no secret the stand-in services were given reaches the page, its answers or its text.
 *
 * Last, the passkey approval end to end, unchanged in what it asks: at CLIVE's own address
 * (localhost here), with the owner's passkey in Chromium's virtual authenticator, a new GitHub
 * token is pasted over the refused one and saved in one step (Save, the passkey, CLIVE's test with
 * GitHub), and the row moves to Working with no key box, the change in Recent changes. Then the voice
 * is saved untouched: what is sent is the voice and the model and no setting he did not choose, and an
 * untouched slider shows the voice's own value only where ElevenLabs reported one; and once something is
 * saved, "Use the voice's own settings" goes back to the voice set up on the server, with the passkey.
 *
 * Prints one JSON object: { ok, checks, shots }.
 */
'use strict';

const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
const PREFIX = process.argv[4] || 'after';
const SECRETS = JSON.parse(process.argv[5] || '[]');
const FLOW = JSON.parse(process.argv[6] || '{}');
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const SIZES = [
  { name: 'phone', width: 390, height: 844, dpr: 3, mobile: true },
  { name: 'tab-a', width: 800, height: 1280, dpr: 1.5, mobile: true },
  { name: 'laptop', width: 1440, height: 900, dpr: 1, mobile: false },
];

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 600) });

async function shot(page, name, full = true) {
  if (!OUT) return;
  fs.mkdirSync(OUT, { recursive: true });
  const file = path.join(OUT, `${PREFIX}-${name}.png`);
  await page.screenshot({ path: file, fullPage: full });
  shots.push(file);
}

async function open(browser, size, extra = {}) {
  const context = await browser.newContext({
    viewport: { width: size.width, height: size.height }, deviceScaleFactor: size.dpr,
    isMobile: size.mobile, hasTouch: size.mobile, extraHTTPHeaders: HEADERS, ...extra,
  });
  const page = await context.newPage();
  const errors = [];
  const bodies = [];
  page.on('pageerror', (error) => errors.push(String(error && error.message)));
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('response', async (response) => {
    if (!response.url().includes('/connections')) return;
    try { bodies.push(await response.text()); } catch (error) { /* a redirect or an aborted read */ }
  });
  await page.goto(`${BASE}/connections`, { waitUntil: 'networkidle' });
  // The screen asks every connection's service on open; it is drawn once that answer is in.
  await page.waitForSelector('[data-ready="true"]', { timeout: 15000 }).catch(() => {});
  return { context, page, errors, bodies };
}

// What the screen shows, read off the glass: each row's group, state and what it offers.
function survey(page) {
  return page.evaluate(() => {
    const groupOf = (r) => { const g = r.closest('section.group'); return g && g.id.indexOf('group-') === 0 ? g.id.slice(6) : ''; };
    const visible = (el) => {
      if (!el) return false;
      const box = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return box.width > 0 && box.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
    };
    const rows = [...document.querySelectorAll('.conn')].map((row) => ({
      name: row.dataset.name,
      state: row.dataset.state,
      group: groupOf(row),
      keys: [...row.querySelectorAll('input.key-input')].filter(visible).length,
      anyInputs: row.querySelectorAll('input.key-input').length,
      status: (row.querySelector('.conn-status') || {}).textContent || '',
      line: (row.querySelector('.conn-line') || {}).textContent || '',
      action: [...row.querySelectorAll('.conn-act')].filter(visible).map((b) => b.textContent.trim()),
    }));
    const groups = [...document.querySelectorAll('section.group[id^="group-"]')].map((g) => g.id.slice(6));
    const details = [...document.querySelectorAll('details')].map((d) => d.open);
    return { rows, groups, details };
  });
}

function fits(page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    const wide = [...document.querySelectorAll('body *')].filter((el) => {
      const box = el.getBoundingClientRect();
      return box.width > 0 && box.right > root.clientWidth + 1;
    }).map((el) => el.className || el.tagName).slice(0, 6);
    return { scroll: root.scrollWidth - root.clientWidth, wide };
  });
}

function smallTargets(page) {
  return page.evaluate(() => {
    const out = [];
    for (const el of document.querySelectorAll('button, summary, a, input, select')) {
      const box = el.getBoundingClientRect();
      if (!box.width || !box.height || getComputedStyle(el).visibility === 'hidden') continue;
      if (el.type === 'range' || el.type === 'checkbox') continue;      // the label row is the target
      if (box.height < 43.5 || box.width < 43.5) out.push(`${el.tagName.toLowerCase()} "${(el.textContent || el.value || '').trim().slice(0, 30)}" ${Math.round(box.width)}x${Math.round(box.height)}`);
    }
    return out;
  });
}

async function leaks(page, bodies) {
  const html = await page.content();
  const found = [];
  for (const secret of SECRETS) {
    if (!secret || secret.length < 8) continue;
    if (html.includes(secret)) found.push('page');
    if (bodies.some((b) => b.includes(secret))) found.push('an answer');
  }
  return found;
}

async function judge(browser, size) {
  const { context, page, errors, bodies } = await open(browser, size);
  const at = size.name;
  const seen = await survey(page);
  const row = (name) => seen.rows.find((r) => r.name === name) || {};
  // [messaging] [shipping] 10: WeCom and CLIVE Shipping each joined the eight (app/connections/catalog.py).
  check(`${at}: the screen is drawn with its rows`, seen.rows.length === 10, JSON.stringify(seen.rows.map((r) => r.name)));
  check(`${at}: what needs you comes first, then what is working, then what you could add`,
    JSON.stringify(seen.groups.filter((g) => ['attention', 'working', 'add'].includes(g))) === JSON.stringify(['attention', 'working', 'add']),
    JSON.stringify(seen.groups));
  check(`${at}: GitHub's refused token and Instagram's ending sign-in need you`,
    row('github').group === 'attention' && row('instagram').group === 'attention', JSON.stringify([row('github'), row('instagram')]));
  for (const name of ['shopify', 'gmail', 'elevenlabs']) {
    const r = row(name);
    check(`${at}: ${name} is working, asks for no key and says when it was checked`,
      r.group === 'working' && r.anyInputs === 0 && /checked/i.test(r.status), JSON.stringify(r));
  }
  check(`${at}: ElevenLabs says whose voice CLIVE speaks in`, /Derek/.test(row('elevenlabs').line), row('elevenlabs').line);
  check(`${at}: GitHub's refused token asks for exactly one key`, row('github').keys === 1, JSON.stringify(row('github')));
  check(`${at}: Instagram's ending sign-in asks for no key, only to sign in again`,
    row('instagram').keys === 0 && row('instagram').action.some((a) => /sign in/i.test(a)), JSON.stringify(row('instagram')));
  for (const name of ['ship24', 'youtube', 'returns', 'wecom', 'shipping']) {
    const r = row(name);
    check(`${at}: ${name} is something you could add, with no key box until you ask`,
      r.group === 'add' && r.keys === 0 && r.action.some((a) => /connect/i.test(a)), JSON.stringify(r));
  }
  check(`${at}: every details disclosure starts closed`, seen.details.length > 0 && seen.details.every((open) => !open), JSON.stringify(seen.details));
  const fit = await fits(page);
  check(`${at}: nothing is wider than the screen`, fit.scroll <= 0 && !fit.wide.length, JSON.stringify(fit));
  const small = await smallTargets(page);
  check(`${at}: every control is at least 44 px`, !small.length, small.join('; '));
  await shot(page, at);

  if (at === 'phone' && seen.rows.length) {
    // Connect on a service not yet added: one key box, and only then.
    await page.click('.conn[data-name="ship24"] .conn-act');
    await page.waitForTimeout(250);
    const after = (await survey(page)).rows.find((r) => r.name === 'ship24');
    check('phone: Connect on Ship24 asks for exactly one key', after.keys === 1, JSON.stringify(after));
    await shot(page, 'phone-connect', false);
    // The voice is still set from ElevenLabs' details: the picker, the four sliders, a preview.
    await page.click('.conn[data-name="elevenlabs"] summary');
    await page.waitForTimeout(300);
    const voice = await page.evaluate(() => {
      const row = document.querySelector('.conn[data-name="elevenlabs"]');
      return {
        open: row.querySelector('details').open,
        pick: Boolean(row.querySelector('.voice-pick')),
        sliders: row.querySelectorAll('input[type="range"]').length,
        preview: Boolean(row.querySelector('.voice-preview')),
        save: Boolean(row.querySelector('.voice-save')),
        keys: row.querySelectorAll('input.key-input').length,
      };
    });
    check('phone: ElevenLabs\' details hold the voice picker, its sliders, Preview and Save',
      voice.open && voice.pick && voice.sliders === 4 && voice.preview && voice.save, JSON.stringify(voice));
    check('phone: opening ElevenLabs\' details shows no key box until Replace key', voice.keys === 0, JSON.stringify(voice));
    // An untouched slider: the voice's own value where ElevenLabs reported one (Derek's stability),
    // and no number where it did not (his expression and speed); the speaker boost neither on nor off.
    const own = await page.evaluate(() => {
      const row = document.querySelector('.conn[data-name="elevenlabs"]');
      const said = (key) => row.querySelector('.voice-' + key).parentNode.querySelector('.slider-value').textContent;
      return { stability: said('stability'), style: said('style'), speed: said('speed'),
        boost: row.querySelector('.voice-boost').indeterminate };
    });
    check('phone: an untouched slider shows the voice\'s own value only where ElevenLabs reported one, and no number otherwise',
      own.stability === '0.50 (the voice\'s own)' && own.style === 'the voice\'s own setting' && own.speed === 'the voice\'s own setting'
      && own.boost === true, JSON.stringify(own));
    await page.evaluate(() => document.querySelector('.conn[data-name="elevenlabs"]').scrollIntoView({ block: 'start' }));
    await shot(page, 'phone-details', false);
    // What Shopify lets CLIVE do, and what stops without it, from the capability registry.
    await page.click('.conn[data-name="elevenlabs"] summary');
    await page.click('.conn[data-name="shopify"] summary');
    await page.waitForTimeout(300);
    const shop = await page.evaluate(() => {
      const row = document.querySelector('.conn[data-name="shopify"]');
      return { abilities: [...row.querySelectorAll('.ability')].map((a) => a.textContent),
        without: (row.querySelector('.without') || {}).textContent || '', keys: row.querySelectorAll('input.key-input').length };
    });
    check('phone: Shopify\'s details say what it lets CLIVE do and what stops without it, with no key box',
      shop.abilities.includes('Reading orders') && /Without it/.test(shop.without) && shop.keys === 0, JSON.stringify(shop));
    await page.evaluate(() => document.querySelector('.conn[data-name="shopify"]').scrollIntoView({ block: 'start' }));
    await shot(page, 'phone-shopify-details', false);
  }
  const found = await leaks(page, bodies);
  check(`${at}: no secret reaches the page or its answers`, !found.length, found.join(', '));
  check(`${at}: no script errors`, !errors.length, errors.join(' | '));
  await context.close();
}

async function checking(browser) {
  // The screen asks each service as it opens: until the answer is in, the rows say so.
  const size = SIZES[0];
  const context = await browser.newContext({ viewport: { width: size.width, height: size.height }, deviceScaleFactor: size.dpr,
    isMobile: true, hasTouch: true, extraHTTPHeaders: HEADERS });
  const page = await context.newPage();
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  await page.route('**/connections/check', async (route) => { await held; await route.continue(); });
  await page.goto(`${BASE}/connections`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.conn[data-name="shopify"]', { timeout: 15000 });
  const during = await page.evaluate(() => ({
    summary: document.querySelector('#summary').textContent,
    shopify: document.querySelector('.conn[data-name="shopify"] .conn-status').textContent,
    busy: Boolean(document.querySelector('.conn[data-name="shopify"] .dot.is-busy')),
  }));
  const fresh = await page.evaluate(() => document.querySelector('.conn[data-name="elevenlabs"] .conn-status').textContent);
  check('opening: while CLIVE asks the services, the rows due a check say so', /Checking/.test(during.summary) &&
    during.shopify === 'Checking now…' && during.busy, JSON.stringify(during));
  check('opening: a row asked within the last minute is not asked again', /^Connected · checked/.test(fresh), fresh);
  await shot(page, 'phone-checking', false);
  release();
  await page.waitForSelector('[data-ready="true"]', { timeout: 15000 });
  await context.close();
}

async function cameBack(browser) {
  // Where Instagram's sign-in comes back to (app/routes/connections.py): /connections?done=signed_in#instagram.
  const size = SIZES[0];
  const context = await browser.newContext({ viewport: { width: size.width, height: size.height }, deviceScaleFactor: size.dpr,
    isMobile: true, hasTouch: true, extraHTTPHeaders: HEADERS, reducedMotion: 'reduce' });
  const page = await context.newPage();
  await page.goto(`${BASE}/connections?done=signed_in#instagram`, { waitUntil: 'networkidle' });
  await page.waitForSelector('[data-ready="true"]', { timeout: 15000 });
  await page.waitForTimeout(200);
  const seen = await page.evaluate(() => {
    const row = document.getElementById('instagram');
    const box = row ? row.getBoundingClientRect() : null;
    return { row: Boolean(row && row.classList.contains('conn')), top: box ? Math.round(box.top) : null,
      height: window.innerHeight, notice: document.querySelector('#notice').textContent };
  });
  check('back from Instagram: the page goes to the Instagram row and says it is connected',
    seen.row && seen.top !== null && seen.top >= 0 && seen.top < seen.height / 2 && seen.notice === 'Instagram is connected.',
    JSON.stringify(seen));
  await context.close();
}

async function stillness(browser) {
  const { context, page } = await open(browser, SIZES[0], { reducedMotion: 'reduce' });
  const moving = await page.evaluate(() => document.getAnimations().filter((a) => a.playState === 'running'
    && a.effect && a.effect.getTiming && a.effect.getTiming().iterations === Infinity).length);
  check('reduced motion: nothing keeps moving', moving === 0, String(moving));
  await context.close();
}

async function oneStep(browser) {
  if (!FLOW.passkey || !FLOW.passkey.id) return;
  const size = SIZES[0];
  const at = new URL(BASE);
  const base = `http://localhost:${at.port}`;
  const context = await browser.newContext({ viewport: { width: size.width, height: size.height }, deviceScaleFactor: size.dpr,
    isMobile: true, hasTouch: true, extraHTTPHeaders: HEADERS });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(String(error && error.message)));
  const cdp = await context.newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  const { authenticatorId } = await cdp.send('WebAuthn.addVirtualAuthenticator', { options: {
    protocol: 'ctap2', transport: 'internal', hasResidentKey: true, hasUserVerification: true,
    isUserVerified: true, automaticPresenceSimulation: true } });
  await cdp.send('WebAuthn.addCredential', { authenticatorId, credential: {
    credentialId: FLOW.passkey.id, isResidentCredential: false, rpId: FLOW.passkey.rp_id,
    privateKey: FLOW.passkey.key, signCount: 1 } });
  await page.goto(`${base}/connections`, { waitUntil: 'networkidle' });
  await page.waitForSelector('[data-ready="true"]', { timeout: 15000 });
  // Boxes left open elsewhere (the review of 889f3284): Shopify's Replace, whose Client ID the page
  // fills in itself, and Ship24's Connect with a few characters typed. Neither may stop the screen
  // regrouping when GitHub is saved, and what was typed into Ship24's box must still be there.
  await page.click('.conn[data-name="shopify"] summary');
  await page.click('.conn[data-name="shopify"] .conn-replace');
  await page.click('.conn[data-name="ship24"] .conn-open');
  await page.fill('.conn[data-name="ship24"] input.key-input', 'typed so far');
  await page.fill('.conn[data-name="github"] input.key-input', FLOW.github);
  await page.click('.conn[data-name="github"] .key-save');
  const moved = await page.waitForSelector('#group-working .conn[data-name="github"]', { timeout: 20000 })
    .then(() => true).catch(() => false);
  const after = await page.evaluate(() => {
    const groupOf = (r) => { const g = r.closest('section.group'); return g && g.id.indexOf('group-') === 0 ? g.id.slice(6) : ''; };
    const row = document.querySelector('.conn[data-name="github"]');
    return {
      group: row ? groupOf(row) : '',
      keys: row ? row.querySelectorAll('input.key-input').length : -1,
      status: row ? (row.querySelector('.conn-status') || {}).textContent : '',
      notice: document.querySelector('#notice').textContent,
      kept: (document.querySelector('.conn[data-name="ship24"] input.key-input') || {}).value || '',
      busy: document.querySelector('#groups').getAttribute('aria-busy'),
      changes: [...document.querySelectorAll('.change-what')].map((n) => n.textContent),
    };
  });
  check('one step: Save asks the passkey, CLIVE tests the token with GitHub, and GitHub moves to Working',
    moved && after.group === 'working' && after.keys === 0 && /^Connected · checked/.test(after.status), JSON.stringify(after));
  check('one step: the screen regroups with boxes open elsewhere, and keeps what was typed in them',
    moved && after.kept === 'typed so far' && after.busy === 'false', JSON.stringify(after));
  check('one step: it says what GitHub said, and the change is in Recent changes',
    /^GitHub accepted the token/.test(after.notice) && after.changes.includes('GitHub key saved'), JSON.stringify(after));
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot(page, 'phone-saved', false);
  const found = await leaks(page, []);
  check('one step: the token just saved is not on the page', !found.length, found.join(', '));

  // The voice, saved without touching a slider: the voice and the model, and no setting he did not choose.
  const sent = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/connections/voice') sent.push(request.postData() || '');
  });
  await page.click('.conn[data-name="elevenlabs"] summary');
  await page.waitForTimeout(300);
  await page.click('.conn[data-name="elevenlabs"] .voice-save');
  await page.waitForFunction(() => /CLIVE speaks as/.test(document.querySelector('#notice').textContent), null, { timeout: 15000 })
    .catch(() => {});
  const voiceSaved = await page.evaluate(() => document.querySelector('#notice').textContent);
  let values = {};
  try { values = JSON.parse(JSON.parse(sent[0] || '{}').values_json || '{}'); } catch (error) { values = {}; }
  const settings = Object.keys(values).filter((k) => !['voice_id', 'voice_name', 'model'].includes(k));
  check('one step: the voice saved untouched sends the voice and the model and no setting, and says who speaks now',
    sent.length === 1 && values.voice_id && values.model && !settings.length && voiceSaved === 'CLIVE speaks as Derek from now on.',
    JSON.stringify({ values, voiceSaved }));
  await page.evaluate(() => document.querySelector('.conn[data-name="elevenlabs"] .voice-save').scrollIntoView({ block: 'center' }));
  await shot(page, 'phone-voice-saved', false);

  // Something is saved now, so the way back is offered: one step, with the passkey, to the voice set up
  // on the server in its own settings.
  const offered = await page.evaluate(() => Boolean(document.querySelector('.conn[data-name="elevenlabs"] .voice-reset')));
  const resets = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/connections/voice/reset') resets.push(request.postData() || '');
  });
  if (offered) await page.click('.conn[data-name="elevenlabs"] .voice-reset');
  // The notice comes as the answer does; the screen is drawn again a moment later, without the button.
  await page.waitForFunction(() => /again, in the voice's own settings/.test(document.querySelector('#notice').textContent)
    && !document.querySelector('.conn[data-name="elevenlabs"] .voice-reset'), null, { timeout: 15000 }).catch(() => {});
  const back = await page.evaluate(() => ({
    notice: document.querySelector('#notice').textContent,
    still: Boolean(document.querySelector('.conn[data-name="elevenlabs"] .voice-reset')),
    changes: [...document.querySelectorAll('.change-what')].map((n) => n.textContent),
  }));
  check('one step: once a voice is saved, "Use the voice\'s own settings" goes back to the voice set up on the server',
    offered && resets.length === 1 && back.notice === 'CLIVE speaks as Derek again, in the voice\'s own settings.' && !back.still
    && back.changes.includes('Voice back to Derek · eleven_flash_v2_5, in its own settings'), JSON.stringify(back));
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot(page, 'phone-voice-reset', false);
  check('one step: no script errors', !errors.length, errors.join(' | '));
  await context.close();
}

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  try {
    await checking(browser);
    for (const size of SIZES) await judge(browser, size);
    await stillness(browser);
    await cameBack(browser);
    await oneStep(browser);
  } catch (error) {
    check('the run finished', false, error && error.stack ? error.stack : error);
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ ok: checks.every((c) => c.ok), checks, shots }));
})();

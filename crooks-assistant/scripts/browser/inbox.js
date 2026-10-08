/* DEC-071's inbox rulings, with a finger, in Chromium, against the real backend
 * (tests/test_inbox_browser.py serves it and checks what reached the record).
 *
 *   CROOKS_INBOX='{"owner_session":"…","mia":"mia@example.com"}' node scripts/browser/inbox.js http://127.0.0.1:8765 /shots
 *
 * Ruling 27: on George's tablet (601 × 889) "junk the promo emails" draws ONE card naming each thread
 * that goes to Spam and each left out with why (a customer's thread is never junked); his one hold
 * junks them; a thread Gmail refused is named on the card after, with what happened to it.
 * Ruling 34: "send the draft to Lena" draws the draft as Gmail holds it, saying whose words they are
 * and whose hold sends them, and his hold sends it. Then Mia, on her phone (390 × 844) at /today,
 * asks her CLIVE to send George's other draft: her card says "Words: George's, written in Gmail" and
 * "Sent by: Mia, on their own hold", and her own hold sends it.
 * (Ruling 29, an email on a TV, is walked in scripts/browser/lift.js.)
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...] }.
 */
'use strict';

const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
const WORLD = JSON.parse(process.env.CROOKS_INBOX || '{}');
const OWNER = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const MIA = { 'Tailscale-User-Login': WORLD.mia || 'mia@example.com', 'X-Forwarded-For': '100.64.0.7' };
const TABLET = { viewport: { width: 601, height: 889 }, deviceScaleFactor: 1.33, isMobile: true, hasTouch: true };
const PHONE = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true };

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 500) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function open(browser, device, headers, url, init) {
  const context = await browser.newContext(Object.assign({ extraHTTPHeaders: headers }, device));
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const from = (m.location && m.location() && m.location().url) || '';
    if (from.includes('/speak') || /status of 503/.test(m.text())) return;
    errors.push(`console: ${m.text()}${from ? ` <- ${from}` : ''}`);
  });
  if (init) await page.addInitScript(init.fn, init.arg);
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key","reason":"no voice under test"}' }));
  await page.goto(`${BASE}${url}`, { waitUntil: 'domcontentloaded' });
  const shot = async (name) => {
    if (!OUT) return;
    fs.mkdirSync(OUT, { recursive: true });
    await sleep(400);
    await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: false, animations: 'disabled' });
    shots.push(`${name}.png`);
  };
  return { context, page, errors, shot };
}

async function ask(t, words, selector) {
  await t.page.click('#ask-bar');
  await t.page.fill('#alpha-input', words);
  await t.page.press('#alpha-input', 'Enter');
  await t.page.waitForSelector(selector, { timeout: 20000 });
  await sleep(900);
}

// The gesture surface of a card, brought into view, and where a finger goes on it.
const surfaceOf = (t, cardSel) => t.page.evaluate((sel) => {
  const card = document.querySelector(sel);
  const surface = card && card.querySelector('.action-surface');
  if (!surface) return null;
  surface.scrollIntoView({ block: 'center' });
  const b = surface.getBoundingClientRect();
  return { kind: surface.dataset.kind || '', x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2), label: (surface.textContent || '').trim() };
}, cardSel);

// Hold, then tap: the hold the Mac asks for (app/actions/grammar.py), with the dead time waited out.
async function holdThenTap(t, at) {
  await sleep(900);
  await t.page.mouse.move(at.x, at.y);
  await t.page.mouse.down();
  await sleep(1500);
  await t.page.mouse.up();
  await sleep(300);
  await t.page.mouse.down();
  await sleep(120);
  await t.page.mouse.up();
}

const cardText = (t, sel) => t.page.evaluate((s) => ((document.querySelector(s) || {}).textContent || '').replace(/\s+/g, ' ').trim(), sel);
const facts = (t, sel) => t.page.evaluate((s) => {
  const out = {};
  const card = document.querySelector(s);
  if (!card) return out;
  for (const dt of card.querySelectorAll('dl.facts dt')) out[dt.textContent.trim()] = ((dt.nextElementSibling || {}).textContent || '').trim();
  return out;
}, sel);

async function owner(browser) {
  const t = await open(browser, TABLET, OWNER, '/?startup=off', {
    fn: (sid) => { try { localStorage.setItem('crooks.session', sid); } catch (e) { /* none */ } },
    arg: WORLD.owner_session || '',
  });
  await t.page.waitForSelector('#ask-bar', { timeout: 15000 });
  await sleep(900);

  // ---- ruling 27: junk a set on one card and one hold
  await ask(t, 'junk the promo emails', '#cards .card-batch_action');
  const card = '#cards .card-batch_action';
  const words = await cardText(t, card);
  check('one card for the set, titled with how many go to Spam', /Junk 2 threads/.test(words), words);
  const lists = await t.page.evaluate((sel) => {
    const node = document.querySelector(sel);
    const items = (cls) => Array.from(node.querySelectorAll(`${cls} .batch-list li`)).map((li) => li.textContent.replace(/\s+/g, ' ').trim());
    return { members: items('details.batch-members:not(.batch-excluded)'), excluded: items('.batch-excluded') };
  }, card);
  check('the card lists every thread that will change', lists.members.join(' | ') === 'WIN A PRIZE | Rank #1 on Google', JSON.stringify(lists));
  check('and the customer\'s thread left out, with why', lists.excluded.length === 1 && /^Order 1938 — can I add to it\?\s*from a customer of the shop/.test(lists.excluded[0]), JSON.stringify(lists));
  check('it says what junk does before the hold', /Gmail learns from it/.test(words) && /Undo puts them all back/.test(words), words);
  const surface = await surfaceOf(t, card);
  check('the gesture is a hold, not a tap', surface && surface.kind === 'hold_to_arm', JSON.stringify(surface));
  await t.shot('inbox-1-junk-card');
  await holdThenTap(t, surface);
  await t.page.waitForSelector('#cards .card-batch_result', { timeout: 30000 }).catch(() => null);
  await sleep(800);
  const result = await t.page.evaluate(() => {
    const node = document.querySelector('#cards .card-batch_result');
    if (!node) return null;
    const details = node.querySelector('details.batch-members');
    if (details) details.open = true;
    return {
      title: (node.querySelector('.card-title') || {}).textContent || '',
      note: (node.querySelector('.card-note') || {}).textContent || '',
      rows: Array.from(node.querySelectorAll('.batch-list li')).map((li) => ({ cls: li.className, text: li.textContent.replace(/\s+/g, ' ').trim() })),
    };
  });
  check('after the hold, the count is what was proven: 1 of 2', result && result.title === 'Junked: 1 of 2', JSON.stringify(result));
  const rows = result ? result.rows : [];
  check('the thread Gmail junked is said as applied', rows.some((r) => r.cls === 'ok' && /^WIN A PRIZE\s*applied$/.test(r.text)), JSON.stringify(rows));
  check('the thread Gmail refused is named with what happened to it', rows.some((r) => r.cls === 'bad' && /^Rank #1 on Google\s*refused$/.test(r.text)), JSON.stringify(rows));
  check('and the card sends him to Gmail for it', result && /check them in Gmail/.test(result.note), result && result.note);
  await t.page.evaluate(() => { const n = document.querySelector('#cards .card-batch_result'); if (n) n.scrollIntoView({ block: 'start' }); });
  await t.shot('inbox-2-junk-result');

  // ---- ruling 34, his side: a draft he wrote in Gmail, sent as it is
  await ask(t, 'send the draft to lena', '#cards .card-confirmation[data-proposal]');
  const send = '#cards .card-confirmation';
  const said = await facts(t, send);
  check('his card says whose words and who sends them', said.Words === 'Yours, written in Gmail' && said['Sent by'] === 'You, on your hold', JSON.stringify(said));
  const editable = await t.page.evaluate((sel) => document.querySelectorAll(`${sel} textarea, ${sel} [contenteditable="true"]`).length, send);
  check('the words are Gmail\'s draft, not editable on the card', editable === 0, editable);
  const sendText = await cardText(t, send);
  check('the card prints the draft as Gmail holds it', /Hi Lena, George here/.test(sendText), sendText.slice(0, 300));
  const at = await surfaceOf(t, send);
  await t.shot('inbox-3-george-draft-card');
  await holdThenTap(t, at);
  const sent = await t.page.waitForFunction(() => /Draft sent/.test((document.querySelector('#cards') || {}).textContent || ''), null, { timeout: 30000 }).then(() => true).catch(() => false);
  check('his hold sends it, and the card says so', sent, await cardText(t, '#cards'));
  await t.shot('inbox-4-george-draft-sent');
  check('the tablet threw nothing', t.errors.length === 0, t.errors.join(' | '));
  await t.context.close();
}

async function mia(browser) {
  const t = await open(browser, PHONE, MIA, '/today');
  await t.page.waitForSelector('#ask-text', { timeout: 15000 });
  await sleep(900);
  await t.page.fill('#ask-text', "send George's draft to Ana");
  await t.page.press('#ask-text', 'Enter');
  await t.page.waitForSelector('#talk-log .card.change', { timeout: 20000 }).catch(() => null);
  await sleep(600);
  const card = '#talk-log .card.change';
  const said = await facts(t, card);
  check('Mia\'s card says the words are George\'s and that she sends them', said.Words === "George's, written in Gmail" && said['Sent by'] === 'Mia, on their own hold', JSON.stringify(said));
  const words = await cardText(t, card);
  check('her card prints George\'s draft as he wrote it', /Hi Ana, George here/.test(words) && /Send the draft/.test(words), words.slice(0, 300));
  const go = await t.page.$eval(`${card} .go`, (b) => b.textContent.trim()).catch(() => '');
  check('it is held, not tapped', go === 'Hold to confirm', go);
  await t.page.$eval(`${card} .go`, (b) => b.scrollIntoView({ block: 'center' }));
  await t.shot('inbox-5-mia-card');
  const init = { pointerId: 7, isPrimary: true, button: 0, bubbles: true };
  await t.page.dispatchEvent(`${card} .go`, 'pointerdown', init);
  await sleep(1400);
  await t.page.dispatchEvent(`${card} .go`, 'pointerup', init);
  const armed = await t.page.$eval(`${card} .go`, (b) => b.textContent.trim()).catch(() => '');
  check('her hold arms it', armed === 'Tap to confirm', armed);
  await t.page.click(`${card} .go`);
  const result = await t.page.waitForFunction((sel) => { const r = document.querySelector(`${sel} .result`); return r && r.textContent.trim() ? r.textContent.trim() : null; }, card, { timeout: 30000 })
    .then((h) => h.jsonValue()).catch(() => '');
  check('her hold sends it, and says to whom', result === 'Sent to Ana.', result);
  await t.shot('inbox-6-mia-sent');
  check('Mia\'s page threw nothing', t.errors.length === 0, t.errors.join(' | '));
  await t.context.close();
}

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  try {
    await owner(browser);
    await mia(browser);
  } catch (e) {
    check('the walk ran to its end', false, e && e.stack ? e.stack : String(e));
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ ok: checks.every((c) => c.ok), checks, shots }));
}

main();

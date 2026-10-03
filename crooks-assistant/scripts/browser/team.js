/* The team's own CLIVE in a real Chromium: a member of the team on a phone and on the shared
 * tablet, and George on his side, against scripts/browser/team_server.py (or the same world built by
 * tests/test_team_browser.py).
 *
 *   node scripts/browser/team.js http://127.0.0.1:8791 /path/to/screenshots
 *
 * What it proves, on the glass and on the Mac's own record:
 *   - claiming takes one tap, and the job in hand turns into the one action it now needs;
 *   - Undo, inside its six seconds, puts the job back as it was;
 *   - a sentence typed ("I've packed 2106") does the step at once;
 *   - hold to speak is wired: a scripted recogniser stands in for the phone's (the harness cannot
 *     speak), its live words show under the finger, and letting go does what was said;
 *   - holding the job in hand does its one action;
 *   - an owner-only ask (a refund) is never tried: "That's George's to do. I've told him.", and it is
 *     on his list, both when the page reads it and when their CLIVE does;
 *   - every screen has the ask bar, nothing on it is smaller than a thumb, and no page error.
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
const MIA = { 'Tailscale-User-Login': 'mia@example.com', 'X-Forwarded-For': '100.64.0.7' };
const KIT = { 'Tailscale-User-Login': 'kit@example.com', 'X-Forwarded-For': '100.64.0.8' };
const PHONE = { width: 390, height: 844 };
const TABLET = { width: 800, height: 1280 };
const TABLET_WIDE = { width: 1280, height: 800 };

const checks = [];
const shots = [];
const check = (name, ok, detail) => { checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail) }); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// The phone's recogniser, scripted: what it "hears" is set by the check before the hold.
const FAKE_RECOGNISER = `
  window.__say = { interim: '', final: '' };
  class ScriptedRecogniser {
    constructor() { window.__recogniser = this; }
    start() { setTimeout(() => this.emit(window.__say.interim, false), 60); }
    stop() { setTimeout(() => { this.emit(window.__say.final, true); if (this.onend) this.onend(); }, 60); }
    abort() { if (this.onend) this.onend(); }
    emit(text, final) {
      if (!text || !this.onresult) return;
      const result = [{ transcript: text }];
      result.isFinal = final;
      this.onresult({ resultIndex: 0, results: [result] });
    }
  }
  window.SpeechRecognition = ScriptedRecogniser;
`;

async function open(browser, viewport, headers) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
    extraHTTPHeaders: headers || {} });
  await context.addInitScript(FAKE_RECOGNISER);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(`${BASE}/today`, { waitUntil: 'load' });
  await page.waitForFunction(() => !document.body.classList.contains('loading'), null, { timeout: 20000 });
  await sleep(500);
  return { context, page, errors };
}

async function shot(page, name, full) {
  if (!OUT) return;
  const file = path.join(OUT, `after-${name}.png`);
  await page.screenshot({ path: file, fullPage: Boolean(full) });
  shots.push(file);
}

const text = (page, sel) => page.$eval(sel, (el) => el.textContent.trim()).catch(() => '');
const barText = (page) => text(page, '.ot-bar-text');
async function state(page) {
  return page.evaluate(async () => (await fetch('/today/state', { headers: { Accept: 'application/json' } })).json());
}
async function rowFor(page, words) {
  const rows = await page.$$('#after .row, #list .row');
  for (const row of rows) if ((await row.textContent()).includes(words)) return row;
  return null;
}
async function say(page, words) {
  await page.fill('#ask-text', words);
  await page.press('#ask-text', 'Enter');
}
async function hold(page, selector, ms) {
  const box = await page.$eval(selector, (el) => { const r = el.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + 20 }; });
  const init = { pointerId: 7, isPrimary: true, button: 0, clientX: box.x, clientY: box.y, bubbles: true };
  await page.dispatchEvent(selector, 'pointerdown', init);
  await sleep(ms);
  await page.dispatchEvent(selector, 'pointerup', init);
}

async function smallTargets(page) {
  return page.$$eval('button, a, input', (nodes) => nodes.filter((n) => {
    if (n.closest('[hidden]') || n.offsetParent === null) return false;
    const r = n.getBoundingClientRect();
    return r.width > 0 && r.height < 44;
  }).map((n) => `${n.tagName.toLowerCase()}.${n.className}:${Math.round(n.getBoundingClientRect().height)}`));
}

async function phoneStaff(browser) {
  const { context, page, errors } = await open(browser, PHONE, MIA);
  check('the page opens as Mia, with her CLIVE line and the ask bar', (await text(page, '#line')).length > 10 && await page.isVisible('#ask-text') && await page.isVisible('#mic'),
    await text(page, '#line'));
  await shot(page, 'phone-staff-now');
  const small = await smallTargets(page);
  check('nothing to tap is smaller than a thumb', small.length === 0, small.join(', '));

  // Claim by tap: #2106 from After this, then Take it.
  const row = await rowFor(page, '#2106');
  check('the next jobs are one tap away', Boolean(row));
  if (row) await row.click();
  await page.waitForFunction(() => (document.querySelector('#now .now-big') || {}).textContent === '#2106', null, { timeout: 8000 });
  check('the job chosen fills the screen with one action', (await text(page, '#now .now-big')) === '#2106' && (await text(page, '#now .go')) === 'Take it',
    await text(page, '#now .go'));
  await page.click('#now .go');
  await page.waitForFunction(() => document.querySelector('#now .go') && document.querySelector('#now .go').textContent === 'Packed', null, { timeout: 8000 }).catch(() => {});
  const claimed = await state(page);
  const mine = claimed.work.mine_found.map((r) => r.order_number);
  check('claiming takes one tap, and the Mac has it as hers', mine.includes('#2106'), JSON.stringify(mine));
  check('then the job asks for its next step: Packed', (await text(page, '#now .go')) === 'Packed' && /Pack these/.test(await text(page, '#line')),
    `${await text(page, '#now .go')} / ${await text(page, '#line')}`);
  check('the bar says what the tap did, with Undo', /#2106 is yours/.test(await barText(page)) && await page.isVisible('.ot-undo'), await barText(page));
  await shot(page, 'phone-staff-claimed');

  // Undo, within its six seconds.
  await page.click('.ot-undo');
  await page.waitForFunction(() => /Undone/.test((document.querySelector('.ot-bar-text') || {}).textContent || ''), null, { timeout: 8000 }).catch(() => {});
  const undone = await state(page);
  check('Undo puts it back: #2106 is up for grabs again', !undone.work.mine_found.length && undone.work.found.some((r) => r.order_number === '#2106'),
    await barText(page));
  await shot(page, 'phone-staff-undone');

  // Completing by a typed sentence.
  await say(page, "I've packed 2106");
  await page.waitForFunction(() => /Packed #2106/.test((document.querySelector('.ot-bar-text') || {}).textContent || ''), null, { timeout: 8000 }).catch(() => {});
  const typed = await state(page);
  const packed = typed.work.done.find((j) => /#2106/.test(j.title));
  check("a typed \"I've packed 2106\" packs it and finishes it at once", Boolean(packed && packed.evidence.packed && packed.done_by === 'mia'), await barText(page));
  check('and what is next is on screen', (await text(page, '#line')).length > 0 && await page.isVisible('#now .go'), await text(page, '#line'));
  await shot(page, 'phone-staff-typed');

  // Hold to speak: the scripted recogniser hears "done with the tee shelf".
  await page.evaluate(() => { window.__say = { interim: 'done with the', final: 'done with the tee shelf' }; });
  const mic = await page.$eval('#mic', (el) => { const r = el.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; });
  const init = { pointerId: 9, isPrimary: true, button: 0, clientX: mic.x, clientY: mic.y };
  await page.dispatchEvent('#mic', 'pointerdown', init);
  await sleep(500);
  const live = await text(page, '#heard');
  const listening = await page.$eval('#mic', (el) => el.classList.contains('listening'));
  await shot(page, 'phone-staff-listening');
  check('holding the button listens, and the words show as they are heard', listening && live === 'done with the', `${listening} "${live}"`);
  await page.dispatchEvent('#mic', 'pointerup', init);
  await page.waitForFunction(() => /tee shelf/i.test((document.querySelector('.ot-bar-text') || {}).textContent || ''), null, { timeout: 8000 }).catch(() => {});
  const spoken = await state(page);
  check('letting go does what was said: the tee shelf is done, by Mia', spoken.work.done.some((j) => j.title === 'Restock the tee shelf' && j.done_by === 'mia'),
    await barText(page));

  // Holding the job in hand does its one action (the count, handed to her: Start).
  await page.evaluate(() => window.scrollTo(0, 0));
  const before = await text(page, '#now .go');
  await hold(page, '#now .now-big', 900);
  await page.waitForFunction((b) => document.querySelector('#now .go') && document.querySelector('#now .go').textContent !== b, before, { timeout: 8000 }).catch(() => {});
  check('holding the job in hand does its one action', (await text(page, '#now .go')) !== before, `${before} -> ${await text(page, '#now .go')}`);
  await shot(page, 'phone-staff-held');

  // An owner-only ask, read on the page: never tried, noted for George.
  await say(page, 'refund 2109, she wants her money back');
  await page.waitForSelector('.card.george', { timeout: 8000 }).catch(() => {});
  check("a refund asked for is George's: said plainly, not an error", (await text(page, '.card.george .card-title')) === "That's George's to do. I've told him."
    && !(await page.$('.said-clive.error')), await text(page, '#line'));
  await shot(page, 'phone-staff-george');
  await page.click('.talk-back');
  await sleep(300);
  check('and there is always a way back to the work', await page.isVisible('#now'));

  // The same ask put to their CLIVE as a question: its own assistant refuses the refund through the
  // real gate and notes it for George; the page says so the same way.
  await say(page, 'can you refund 2107?');
  await page.waitForSelector('.card.george', { timeout: 15000 }).catch(() => {});
  check('asked of their CLIVE, the refund is refused by the gate and noted for George', (await text(page, '.said-clive')) === "That's George's to do; I've told him."
    && Boolean(await page.$('.card.george')), await text(page, '.said-clive'));
  await shot(page, 'phone-staff-george-clive');
  await page.click('.talk-back');

  // "Cancel that" is never a silent undo: the page asks which they meant, and changes nothing yet.
  const beforeCancel = JSON.stringify((await state(page)).work);
  await say(page, 'cancel that');
  await page.waitForFunction(() => (document.querySelector('#now .now-big') || {}).textContent === 'Cancel what?', null, { timeout: 8000 }).catch(() => {});
  const choices = await page.$$eval('#now .choice', (n) => n.map((x) => x.textContent));
  check('“cancel that” asks: their last step, or an order for George', choices[0] === 'Undo my last step' && /Ask George to cancel/.test(choices[1] || '')
    && JSON.stringify((await state(page)).work) === beforeCancel, choices.join(' | '));
  await shot(page, 'phone-staff-cancel-which');
  await page.click('#now .link:has-text("Neither")');
  await sleep(300);

  // Every job, one tap away.
  const all = await rowFor(page, 'Every job');
  if (all) await all.click();
  await sleep(300);
  check('every job is one tap away, with a way back', await page.isVisible('#list .back') && (await page.$$('#list .row')).length >= 3);
  await shot(page, 'phone-staff-list', true);
  await page.click('#list .back');

  check('no page errors on the phone', errors.length === 0, errors.join(' | '));
  await context.close();
}

async function owner(browser) {
  const { context, page, errors } = await open(browser, PHONE, null);
  page.on('dialog', (dialog) => dialog.accept());
  const waiting = await page.$$eval('#owner-team .flag .row-big', (n) => n.map((x) => x.textContent));
  check("George sees what the team asked of him, in their words", waiting.some((t) => /refund 2109/.test(t)) && waiting.some((t) => /Refund asked for/.test(t)),
    waiting.join(' | '));
  check('and who asked', /Mia asked/.test(await text(page, '#owner-team .flag .row-small')), await text(page, '#owner-team .flag .row-small'));
  await shot(page, 'phone-owner-team', true);
  await page.click('#owner-team .person .row:has-text("Mia")');
  await sleep(300);
  check("tapping a name shows that person's day, step by step", (await page.$$('#owner-team .record.inset li')).length >= 3);

  // An order someone packed: Fulfil starts the sentence for his CLIVE, with the order in it.
  await page.click('#owner-team .flag:has-text("#2106") .pill:has-text("Fulfil")');
  check('an order in other hands, packed, has its Fulfil', (await page.inputValue('#ask-text')) === 'Fulfil order #2106 with tracking number ',
    await page.inputValue('#ask-text'));
  await page.fill('#ask-text', '');

  // A job someone has taken: George can still cancel it.
  const held = await page.$$eval('#owner-team .inset-group .row-big', (n) => n.map((x) => x.textContent));
  await page.click('#owner-team .inset-group .flag:has-text("Count the hoodies") .pill:has-text("Cancel")');
  await page.waitForFunction(() => /Cancelled/.test((document.querySelector('.ot-bar-text') || {}).textContent || ''), null, { timeout: 8000 }).catch(() => {});
  const cancelled = await state(page);
  check('a job someone has taken can be cancelled by George', held.some((t) => /Count the hoodies/.test(t))
    && !cancelled.work.team.some((j) => /Count the hoodies/.test(j.title)) && cancelled.record.some((e) => e.what === 'cancelled'),
    held.join(' | '));
  await shot(page, 'phone-owner-team-held', true);

  // His own Work: he takes an order and packs it, as the team do.
  await page.click('#segments .segment:nth-child(2)');
  await sleep(300);
  const order = await rowFor(page, '#2109');
  if (order) await order.click();
  await page.waitForFunction(() => (document.querySelector('#now .go') || {}).textContent === 'Take it', null, { timeout: 8000 }).catch(() => {});
  await page.click('#now .go');
  await page.waitForFunction(() => (document.querySelector('#now .go') || {}).textContent === 'Packed', null, { timeout: 8000 }).catch(() => {});
  await page.click('#now .go');
  await page.waitForFunction(() => /Packed #2109/.test((document.querySelector('.ot-bar-text') || {}).textContent || ''), null, { timeout: 8000 }).catch(() => {});
  const packedByHim = (await state(page)).work.done.find((j) => /#2109/.test(j.title));
  check('George takes and packs an order from Today himself', Boolean(packedByHim && packedByHim.done_by === 'owner' && packedByHim.evidence.packed),
    await barText(page));
  await shot(page, 'phone-owner-work');

  await page.click('#segments .segment:nth-child(3)');
  await page.fill('#hand-what', 'Steam the AW samples');
  await page.click('#owner-hand .chip:has-text("Kit")');
  await page.click('#owner-hand .go');
  await page.waitForFunction(() => /Handed to Kit/.test((document.querySelector('.ot-bar-text') || {}).textContent || ''), null, { timeout: 8000 }).catch(() => {});
  const handed = await state(page);
  check('handing out a job is one line and a name', handed.work.team.some((j) => j.title === 'Steam the AW samples' && j.assignee === 'kit'), await barText(page));

  // One day a week, and a day further off than tomorrow, as the old form allowed.
  await page.fill('#hand-what', 'Wipe down the packing table');
  await page.click('#owner-hand .chip:has-text("Every week")');
  await page.click('#owner-hand .chip:has-text("Wed")');
  await page.click('#owner-hand .go');
  await page.waitForFunction(() => /every Wed/.test((document.querySelector('.ot-bar-text') || {}).textContent || ''), null, { timeout: 8000 }).catch(() => {});
  check('a routine can be one day a week', (await state(page)).routines.some((r) => r.title === 'Wipe down the packing table' && r.cadence === 'wed'),
    await barText(page));
  await page.fill('#hand-what', 'Order more mailer bags');
  await page.click('#owner-hand .chip:has-text("On a day")');
  const later = await page.evaluate(() => { const d = new Date(Date.now() + 9 * 864e5); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; });
  await page.fill('#hand-day', later);
  await page.dispatchEvent('#hand-day', 'change');
  await page.click('#owner-hand .go');
  await page.waitForFunction(() => /mailer bags/.test((document.querySelector('.ot-bar-text') || {}).textContent || ''), null, { timeout: 8000 }).catch(() => {});
  const dated = (await state(page)).record.find((e) => e.what === 'created' && e.detail === 'Order more mailer bags');
  check('a job can be for a day further off than tomorrow', Boolean(dated) && /for \w{3} \d{1,2} \w{3}/.test(await barText(page)), await barText(page));
  await shot(page, 'phone-owner-hand', true);
  await page.click('#segments .segment:nth-child(4)');
  await sleep(200);
  await shot(page, 'phone-owner-people', true);
  check('people say plainly who can use CLIVE', /Can use CLIVE/.test(await text(page, '#owner-people')));
  check("and where the team's spoken words go", /speech service hears them/.test(await text(page, '#owner-people .hint')));
  check('no page errors on the owner side', errors.length === 0, errors.join(' | '));
  await context.close();
}

async function tablet(browser) {
  const tall = await open(browser, TABLET, KIT);
  const big = await tall.page.$eval('#now .now-big', (el) => parseFloat(getComputedStyle(el).fontSize));
  const go = await tall.page.$eval('#now .go', (el) => el.getBoundingClientRect().height);
  check('on the shared tablet the job reads at arm’s length', big >= 56 && go >= 72, `title ${big}px, action ${go}px`);
  await shot(tall.page, 'tablet-staff');
  check('no page errors on the tablet', tall.errors.length === 0, tall.errors.join(' | '));
  await tall.context.close();
  const wide = await open(browser, TABLET_WIDE, KIT);
  await shot(wide.page, 'tablet-staff-landscape');
  await wide.context.close();
}

async function main() {
  const onDisk = process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
  const browser = await chromium.launch(fs.existsSync(onDisk) ? { executablePath: onDisk } : {});
  try {
    await phoneStaff(browser);
    await owner(browser);
    await tablet(browser);
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

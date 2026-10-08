/* From the question to the action, in a real browser at a phone's and the tablet's sizes (DEC-068).
 *
 * George, 7 October: "today I asked for the email reply to [a customer] and it showed [a
 * customer]'s total orders as a customer, then some random email from someone else, today's email
 * threads and today's orders when all I wanted to see was the reply to [a customer]." And: "why do I
 * have to click save draft and then say send it and then it pulls up a send it screen to send."
 *
 * Driven against the real backend on the golden world, with the model scripted by the runner
 * (tests/test_flow_browser.py) to make his turn's calls, read for read, through the real gate —
 * slowly, as the real model does, so the glass can be watched while it works. Priya stands in
 * for that customer. What is checked is what he sees:
 *
 *   a. while CLIVE works: words saying what it is doing, and no card of any search;
 *      when it answers: the reply, and nothing else;
 *   b. the reply is one card: its words edited there with real keystrokes, and one hold (then
 *      the tap that applies it) sends exactly those words — no Save draft, no second screen;
 *   c. a reply Gmail refuses says "Not sent" and why, and "Try again" puts the same words back on
 *      a card to hold;
 *   d. a list asked for out loud ("show me today's orders") has Next beside it, as the Orders
 *      icon's list does, and Next opens the first of them: "#… 1 of N".
 *
 *   node scripts/browser/flow.js http://127.0.0.1:8823 /path/to/screenshots
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...] }.
 */
'use strict';

const { chromium } = require('playwright-core');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8823';
const OUT = process.argv[3] || '';
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const SIZES = [
  { name: 'phone-390', viewport: { width: 390, height: 844 }, dpr: 3, question: 'show me the email reply to priya' },
  { name: 'tablet-1280', viewport: { width: 1280, height: 800 }, dpr: 1, question: 'the email reply to priya please' },
];
const ADDED = ' It fits every size.';
const REFUSED_QUESTION = 'and tell her it only comes in black';
const REFUSED = 'Hi Priya, one more thing: it comes in black only.';
const LIST_QUESTION = "show me today's orders";

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function walk(browser, size) {
  const context = await browser.newContext({ viewport: size.viewport, deviceScaleFactor: size.dpr, isMobile: true, hasTouch: true, extraHTTPHeaders: HEADERS });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key","reason":"no voice under test"}' }));
  const shot = async (name) => {
    if (!OUT) return;
    const file = path.join(OUT, `flow-${size.name}-${name}.png`);
    await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
    shots.push(path.basename(file));
  };
  const at = (label) => `${label} (${size.name})`;

  await page.goto(`${BASE}/?startup=off`, { waitUntil: 'load' });
  try { await page.waitForFunction(() => document.getElementById('system').dataset.phase === 'online', null, { timeout: 30000 }); } catch { /* checked below */ }
  await sleep(1200);

  const glass = () => page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll('#cards > *'));
    return {
      mode: document.body.dataset.mode,
      types: cards.map((n) => n.dataset.type),
      words: [document.getElementById('state-label'), document.getElementById('state-sub')].map((n) => (n ? n.textContent : '')).join(' · '),
      jobs: (document.getElementById('job-zone') || { textContent: '' }).textContent.replace(/\s+/g, ' ').trim(),
      answer: (document.getElementById('answer') || { textContent: '' }).textContent,
      text: cards.map((n) => n.textContent.replace(/\s+/g, ' ').trim()).join(' | ').slice(0, 800),
    };
  });

  // ---- a. the reply turn, watched frame by frame while it works
  const watching = page.evaluate(async (q) => {
    const frames = [];
    let running = true;
    const tick = () => {
      if (!running) return;
      const cards = Array.from(document.querySelectorAll('#cards > *')).map((n) => n.dataset.type);
      frames.push({ cards, words: (document.getElementById('state-sub') || { textContent: '' }).textContent });
      requestAnimationFrame(tick);
    };
    tick();
    await window.CliveAlpha.ask(q);
    running = false;
    return frames;
  }, size.question);
  // Mid-way: the model is between its reads (the runner holds each one, as Claude takes its time).
  await sleep(2600);
  const midway = await glass();
  await shot('a1-working');
  const frames = await watching;
  await sleep(600);
  const answered = await glass();
  await shot('a2-only-the-reply');

  const beforeAnswer = frames.slice(0, Math.max(0, frames.length - 2));
  const cardFrames = beforeAnswer.filter((f) => f.cards.length);
  check(at('while it works, no card of any search reaches the glass'), frames.length > 10 && cardFrames.length === 0,
    `${cardFrames.length} of ${beforeAnswer.length} frames had cards: ${JSON.stringify(cardFrames.slice(0, 2))}`);
  const said = Array.from(new Set(frames.map((f) => f.words).filter(Boolean)));
  check(at('while it works, the words say what it is doing'), said.some((w) => /Searching|Listing|Finding|Reading|Writing/.test(w)), JSON.stringify(said));
  check(at('mid-way, the screen is words and nothing else'), midway.types.length === 0 && /Searching|Listing|Finding|Reading|Writing/.test(midway.words + midway.jobs), JSON.stringify(midway));
  check(at('the answer is the reply to her, and nothing else'), JSON.stringify(answered.types) === JSON.stringify(['confirmation']), JSON.stringify(answered.types));
  check(at('nothing of the search is on it: not Mia\'s email, not today\'s orders'), !/Mia|1938|Today/.test(answered.text), answered.text.slice(0, 300));

  // ---- b. the one card: edit the words on it, then the one hold that sends them
  const card = () => page.evaluate(() => {
    const node = document.querySelector('#cards [data-type="confirmation"]');
    if (!node) return null;
    const surface = node.querySelector('.action-surface');
    const field = node.querySelector('.message-block .field-input');
    const b = surface ? surface.getBoundingClientRect() : null;
    return {
      proposal: node.dataset.proposal || '', typing: node.dataset.typing || '', kicker: (node.querySelector('.card-kicker') || {}).textContent || '',
      label: surface ? surface.textContent.trim() : '', state: surface ? surface.dataset.state : '', kind: surface ? surface.dataset.kind : '',
      body: field ? field.value : '', other: (node.querySelector('.action-other') || {}).textContent || '',
      x: b ? Math.round(b.x + b.width / 2) : 0, y: b ? Math.round(b.y + b.height / 2) : 0,
    };
  });
  const before = await card();
  check(at('the reply card is the send: its words in a field, one hold, Save as draft quiet beside it'),
    before && before.kind === 'hold_to_arm' && /Hold, then tap to send/.test(before.label) && before.body.length > 10 && before.other === 'Save as draft',
    JSON.stringify(before));
  await page.evaluate(() => { const f = document.querySelector('#cards .message-block .field-input'); if (f) f.scrollIntoView({ block: 'center' }); });
  await sleep(300);
  await shot('b1-send-card-before-the-hold');

  // Real keystrokes at the end of the words, then off the field: the Mac prepares them again.
  await page.click('#cards .message-block .field-input');
  await page.keyboard.press('End');
  await page.keyboard.press('Control+End');
  await page.keyboard.type(ADDED, { delay: 30 });
  const typing = await card();
  check(at('while the typed words are on their way, the hold waits and says so'), typing.typing === 'true' && /Updating the words/.test(typing.label), JSON.stringify(typing));
  try {
    await page.waitForFunction((old) => {
      const node = document.querySelector('#cards [data-type="confirmation"]');
      return node && node.dataset.proposal && node.dataset.proposal !== old && node.dataset.typing !== 'true';
    }, before.proposal, { timeout: 10000 });
  } catch { /* checked below */ }
  await page.evaluate(() => { if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); });
  await sleep(900);   // the new card's dead time
  const edited = await card();
  check(at('the edit is the card again, in its place, with his words and a live hold'),
    edited && edited.proposal !== before.proposal && edited.body.endsWith(ADDED.trim()) && edited.typing !== 'true' && /Hold, then tap to send/.test(edited.label),
    JSON.stringify(edited));
  await page.evaluate(() => { const s = document.querySelector('#cards [data-type="confirmation"] .action-surface'); if (s) s.scrollIntoView({ block: 'center' }); });
  await sleep(300);
  const there = await card();
  await shot('b2-edited-ready-to-hold');

  // The hold, still, then the tap that applies it: the grammar's own hold_to_arm.
  await page.mouse.move(there.x, there.y);
  await page.mouse.down();
  await sleep(1500);
  await page.mouse.up();
  await sleep(250);
  const armed = await card();
  await page.mouse.down();
  await sleep(120);
  await page.mouse.up();
  try {
    await page.waitForFunction(() => Boolean(document.querySelector('#cards [data-type="success"]')), null, { timeout: 15000 });
  } catch { /* checked below */ }
  await sleep(800);
  const sent = await glass();
  check(at('one hold sends it: the proof is up, and nothing else asks for a tap'),
    sent.types.includes('success') && !sent.types.includes('confirmation'), `${JSON.stringify(armed)} → ${JSON.stringify(sent.types)}`);
  check(at('the proof says it was sent, with his words'), /Reply sent/.test(sent.text) && sent.text.includes(ADDED.trim()), sent.text.slice(0, 400));
  await shot('b3-sent');

  // ---- c. a send Gmail refuses: what he is told, and the same words back on a card to hold
  const onCard = (w) => {
    const f = document.querySelector('#cards [data-type="confirmation"] .message-block .field-input');
    return Boolean(f && f.value === w);
  };
  await page.evaluate((q) => window.CliveAlpha.ask(q), REFUSED_QUESTION);
  try { await page.waitForFunction(onCard, REFUSED, { timeout: 15000 }); } catch { /* checked below */ }
  await sleep(900);
  const second = await card();
  check(at('the next reply is its own card, ready to hold'), second && second.body === REFUSED && /Hold, then tap to send/.test(second.label), JSON.stringify(second));
  await page.evaluate(() => { const s = document.querySelector('#cards [data-type="confirmation"] .action-surface'); if (s) s.scrollIntoView({ block: 'center' }); });
  await sleep(300);
  const there2 = await card();
  await page.mouse.move(there2.x, there2.y);
  await page.mouse.down();
  await sleep(1500);
  await page.mouse.up();
  await sleep(250);
  await page.mouse.down();
  await sleep(120);
  await page.mouse.up();
  try {
    await page.waitForFunction(() => Boolean(document.querySelector('#cards [data-type="error"] .action-other')), null, { timeout: 15000 });
  } catch { /* checked below */ }
  await sleep(600);
  const refused = await glass();
  const tryAgain = await page.evaluate(() => (document.querySelector('#cards [data-type="error"] .action-other') || {}).textContent || '');
  check(at('a refused send says it was not sent, and why'),
    refused.types.includes('error') && !refused.types.includes('success') && /Not sent/.test(refused.text)
      && /refused it: Recipient address rejected/.test(refused.text) && /Nothing was sent/.test(refused.text),
    refused.text.slice(0, 300));
  check(at('and offers the same words again, quietly'), tryAgain === 'Try again', tryAgain);
  check(at('the answer says it as the card does, with no exception\'s name in it'),
    /^Not sent\. Gmail refused it: Recipient address rejected\. Nothing was sent\.$/.test(refused.answer.trim()), refused.answer);
  await shot('c1-not-sent');
  await page.click('#cards [data-type="error"] .action-other');
  try { await page.waitForFunction(onCard, REFUSED, { timeout: 15000 }); } catch { /* checked below */ }
  await sleep(900);
  const back = await card();
  check(at('Try again is the same words on a card to hold, and nothing is sent'),
    back && back.body === REFUSED && back.proposal !== second.proposal && /Hold, then tap to send/.test(back.label), JSON.stringify(back));
  await page.evaluate(() => { const f = document.querySelector('#cards [data-type="confirmation"]'); if (f) f.scrollIntoView({ block: 'start' }); });
  await sleep(300);
  await shot('c2-the-words-again');

  // ---- d. a list asked for out loud is walked with Next, as the Orders icon's list is
  await page.evaluate((q) => window.CliveAlpha.ask(q), LIST_QUESTION);
  try {
    await page.waitForFunction(() => {
      const next = document.getElementById('next-btn');
      return Boolean(document.querySelector('#cards [data-type="order_list"]')) && next && !next.hidden;
    }, null, { timeout: 15000 });
  } catch { /* checked below */ }
  await sleep(600);
  const listed = await glass();
  const nextUp = await page.evaluate(() => {
    const next = document.getElementById('next-btn');
    const b = next ? next.getBoundingClientRect() : null;
    return { shown: Boolean(next && !next.hidden && !next.disabled), w: b ? Math.round(b.width) : 0, h: b ? Math.round(b.height) : 0 };
  });
  check(at('a list asked for out loud is up, with Next beside it'),
    listed.types.includes('order_list') && nextUp.shown && nextUp.w > 0 && nextUp.h > 0, JSON.stringify({ types: listed.types, nextUp }));
  await shot('d1-todays-orders-with-next');
  await page.click('#next-btn');
  try {
    await page.waitForFunction(() => /^#\d+\. 1 of \d+\.$/.test(((document.getElementById('answer') || {}).textContent || '').trim()), null, { timeout: 10000 });
  } catch { /* checked below */ }
  await sleep(600);
  const walked = await glass();
  check(at('Next walks it: the first of them, "1 of N"'),
    /^#\d+\. 1 of \d+\.$/.test(walked.answer.trim()) && walked.types.some((t) => t === 'order' || t === 'order_workspace'),
    JSON.stringify({ answer: walked.answer, types: walked.types }));
  await shot('d2-next-the-first-of-them');

  check(at('no page errors'), errors.length === 0, errors.join(' | '));
  await context.close();
}

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  try {
    for (const size of SIZES) await walk(browser, size);
  } catch (error) {
    check('the walk ran to the end', false, error && error.stack ? error.stack : String(error));
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ ok: checks.every((c) => c.ok), checks, shots }));
})();

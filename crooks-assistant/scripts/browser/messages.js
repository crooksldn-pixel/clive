/* WeChat through WeCom, in a real browser: what the manufacturer sent, in English with what she
 * actually wrote one tap away; a translation that failed saying so; her conversation in full with
 * how long WeChat will still take a reply; and a reply in Chinese and English that only his hold sends.
 *
 *   node scripts/browser/messages.js http://127.0.0.1:PORT [/path/to/screenshots]
 *
 * The backend is the real one; the messages came in through the real public door, sealed as WeCom
 * seals them, and Claude is scripted for each sentence (tests/test_messages_browser.py). Each
 * sentence is typed into the page's own diagnostics field, which posts exactly what the microphone
 * posts. What is checked is what the owner sees, at the tablet's size and a phone's:
 *
 *   - the recent conversations are in English, each labelled a machine translation, with no
 *     Chinese on the glass until he taps "Original", and a second tap hides it again;
 *   - the message the model could not translate says "Translation missing" and shows the original;
 *   - her conversation in full names her as his card does, and says how long WeChat takes a reply;
 *   - the reply card prints the exact message, Chinese first, says the Chinese is a machine
 *     translation, names her as his card does with WeChat's own name for her beside it (so a
 *     conversation linked to the wrong person shows before the hold), and waits for the hold; on the tablet nothing is sent; on the phone the hold and
 *     the tap send it, the card says Sent, and the conversation shows it with its Chinese behind a tap;
 *   - nothing leaves the card's edge, the page does not scroll sideways, and nothing throws.
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...] }.
 */
'use strict';

const { chromium } = require('playwright-core');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const SIZES = [
  { name: 'tablet', viewport: { width: 601, height: 889 }, dpr: 1.33, mobile: true, commit: false },
  { name: 'phone', viewport: { width: 390, height: 844 }, dpr: 3, mobile: true, commit: true },
];
// The same sentences tests/test_messages_browser.py scripts.
const SAID = {
  recent: 'What has the factory sent on WeChat?',
  link: "That's Jessica, our manufacturer",
  thread: "Show me Jessica's conversation",
  reply: 'Tell her Monday is fine and to send photos of the sample',
};
const MESSAGES = '#cards .card[data-type="messages"]';
const HOLD = '#cards .card[data-type="confirmation"]';
const SENT = '#cards .card[data-type="success"]';

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function run(browser, size) {
  const tag = size.name;
  const context = await browser.newContext({
    viewport: size.viewport, deviceScaleFactor: size.dpr, isMobile: size.mobile, hasTouch: size.mobile, extraHTTPHeaders: HEADERS,
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key"}' }));
  await page.goto(`${BASE}?dev=1&startup=off`, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => { try { localStorage.clear(); } catch { /* private mode */ } });
  await page.goto(`${BASE}?dev=1&startup=off`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(700);
  await page.evaluate(() => { for (const b of document.querySelectorAll('.dev-banner')) b.remove(); });

  const say = async (text, wait) => {
    const before = await page.evaluate((s) => document.querySelectorAll(s).length, wait);
    await page.evaluate(() => {
      const sheet = document.querySelector('#settings');
      const dev = document.querySelector('#dev');
      if (dev) dev.hidden = false;
      if (sheet && !sheet.open && sheet.showModal) sheet.showModal();
    });
    await page.fill('#dev-text', text);
    await page.press('#dev-text', 'Enter');
    await sleep(500);
    await page.evaluate(() => { const sheet = document.querySelector('#settings'); if (sheet && sheet.open) sheet.close(); });
    try {
      await page.waitForFunction(([s, n]) => document.querySelectorAll(s).length > n || document.querySelector(s), [wait, before], { timeout: 8000 });
    } catch { /* checked below */ }
    await sleep(900);
  };
  const shot = async (name, at) => {
    if (!OUT) return;
    await page.evaluate((sel) => { const c = Array.from(document.querySelectorAll(sel)).pop(); if (c) c.scrollIntoView({ block: 'start' }); }, at);
    await page.waitForTimeout(350);
    const file = path.join(OUT, `messages-${tag}-${name}.png`);
    await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
    shots.push(path.basename(file));
  };
  // The last card of a kind as he sees it: its visible words (hidden originals are not visible),
  // anything poking past its edges, and whether the page scrolls sideways.
  const seen = (sel) => page.evaluate((s) => {
    const card = Array.from(document.querySelectorAll(s)).pop();
    if (!card) return { found: false };
    const box = card.getBoundingClientRect();
    const past = Array.from(card.querySelectorAll('*')).filter((e) => {
      const r = e.getBoundingClientRect();
      return r.width > 0 && !e.closest('.tabs') && (r.right > box.right + 1 || r.left < box.left - 1);
    }).map((e) => e.className).slice(0, 5);
    const doc = document.documentElement;
    return { found: true, past, sideways: doc.scrollWidth > doc.clientWidth + 1, text: card.innerText.replace(/\s+/g, ' ').trim() };
  }, sel);

  // 1. The recent conversations: English, labelled, and no Chinese until he asks for it.
  await say(SAID.recent, MESSAGES);
  let card = await seen(MESSAGES);
  check(`${tag}: what she sent is in English, labelled a machine translation, with no Chinese showing`, card.found
    && /Jessica/.test(card.text) && /WeChat/.test(card.text) && /The sample ships next Monday; the bulk fabric has arrived\./.test(card.text)
    && /Please confirm the size chart\./.test(card.text) && /Machine translation/.test(card.text)
    && !/样衣下周一寄出|请确认尺码表/.test(card.text), JSON.stringify(card));
  check(`${tag}: the message the model could not translate says so and shows what she wrote`, card.found
    && /Translation missing/.test(card.text) && /大货什么时候出？/.test(card.text), JSON.stringify(card));
  check(`${tag}: the messages card fits`, card.found && !card.past.length && !card.sideways, JSON.stringify(card.past));
  await shot('1-recent', MESSAGES);

  // 2. One tap shows the original; a second hides it again.
  const tap = async () => {
    // The first "Original" on the newest messages card.
    const handle = await page.evaluateHandle((s) => {
      const c = Array.from(document.querySelectorAll(s)).pop();
      return c ? c.querySelector('.msg-reveal') : null;
    }, MESSAGES);
    const button = handle.asElement();
    if (button) { await button.scrollIntoViewIfNeeded(); await button.click(); }
    await sleep(300);
    return seen(MESSAGES);
  };
  const opened = await tap();
  await shot('2-original', MESSAGES);
  const closed = await tap();
  check(`${tag}: one tap shows what she wrote, a second hides it`,
    /样衣下周一寄出，大货面料已经到了。/.test(opened.text || '') && /Hide original/.test(opened.text || '')
      && !/样衣下周一寄出/.test(closed.text || '') && /Original/.test(closed.text || ''), `${opened.text} || ${closed.text}`);

  // 3. He says who it is; her conversation in full names her as his card does, with the window.
  await say(SAID.link, MESSAGES);
  await say(SAID.thread, `${MESSAGES} .msg-window`);
  card = await seen(MESSAGES);
  const open = await page.evaluate((s) => {
    const w = Array.from(document.querySelectorAll(`${s} .msg-window`)).pop();
    return w ? w.className : '';
  }, MESSAGES);
  check(`${tag}: her conversation is hers, a manufacturer, and WeChat still takes 5 replies`, card.found
    && /Jessica/.test(card.text) && /WeChat · Manufacturer/.test(card.text) && /WeChat replies: open \d+h more, 5 replies left/.test(card.text)
    && /is-open/.test(open) && !/Jessica Factory/.test(card.text), JSON.stringify(card));
  await shot('3-her-conversation', MESSAGES);

  // 4. The reply: the exact message, Chinese first, held.
  await say(SAID.reply, HOLD);
  card = await seen(HOLD);
  check(`${tag}: the card prints the exact message, Chinese first, says the Chinese is a machine translation, and asks for the hold`,
    card.found && /Send on WeChat/.test(card.text) && /周一可以。寄出前请发样衣照片。 Monday is fine\. Please send photos of the sample before it ships\./.test(card.text)
      && /Jessica/.test(card.text) && /machine translation/i.test(card.text) && /hold/i.test(card.text) && !card.past.length && !card.sideways,
    JSON.stringify(card));
  // Review note 6 (8 Oct): WeChat's own name for her beside his card's, so a wrong link shows before the hold.
  check(`${tag}: the card says who WeChat says she is beside the name on his card`,
    card.found && /\b(?:To|TO)\s*Jessica \(WeChat name: Jessica Factory\)/.test(card.text), JSON.stringify(card));
  await shot('4-reply-card', HOLD);

  if (size.commit) {
    await page.waitForTimeout(900);
    const surface = await page.$(`${HOLD} .action-surface`);
    if (surface) await surface.evaluate((e) => e.scrollIntoView({ block: 'center' }));
    await page.waitForTimeout(400);
    const box = surface ? await surface.boundingBox() : null;
    if (box) {
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.waitForTimeout(2200);
      await page.mouse.up();
      await page.waitForTimeout(250);
      await page.mouse.down();
      await page.mouse.up();
    }
    try { await page.waitForSelector(SENT, { timeout: 15000 }); } catch { /* checked below */ }
    await sleep(800);
    const done = await page.evaluate((s) => Array.from(document.querySelectorAll(s)).map((c) => c.innerText.replace(/\s+/g, ' ').trim()).pop() || '', SENT);
    check(`${tag}: his hold and tap send it, and the card says Sent only once WeCom confirmed it`, /Sent/.test(done), done);
    await shot('5-sent', SENT);
    // The conversation now shows it, in his English, with the Chinese that went behind a tap.
    await say(SAID.thread, `${MESSAGES} .msg-bubble.is-out`);
    const ours = await page.evaluate((s) => {
      const b = Array.from(document.querySelectorAll(`${s} .msg-bubble.is-out`)).pop();
      return b ? b.innerText.replace(/\s+/g, ' ').trim() : '';
    }, MESSAGES);
    check(`${tag}: the conversation shows what was sent, by CLIVE, its Chinese one tap away`,
      /Monday is fine\. Please send photos of the sample before it ships\./.test(ours) && /CLIVE/.test(ours) && /Chinese/.test(ours)
        && !/周一可以/.test(ours), ours);
    await shot('6-after', `${MESSAGES} .msg-bubble.is-out`);
  } else {
    const waiting = await page.evaluate((sel) => {
      const c = Array.from(document.querySelectorAll(sel)).pop();
      const s = c ? c.querySelector('.action-surface') : null;
      return s ? s.dataset.state : '';
    }, HOLD);
    check(`${tag}: nothing is sent while the card waits for the hold`, ['arming', 'armed'].includes(waiting), waiting);
  }

  check(`${tag}: nothing threw`, errors.length === 0, errors.join(' | '));
  await context.close();
}

(async () => {
  const onDisk = process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
  const browser = await chromium.launch({ executablePath: onDisk });
  try {
    for (const size of SIZES) await run(browser, size);
  } catch (error) {
    checks.push({ name: 'the run finished', ok: false, detail: String(error && error.stack || error).slice(0, 600) });
  } finally {
    await browser.close();
  }
  process.stdout.write(JSON.stringify({ ok: checks.every((c) => c.ok), checks, shots }) + '\n');
})();

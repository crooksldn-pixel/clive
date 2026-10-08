/* WhatsApp and Instagram direct messages, in a real browser: a supplier's WhatsApp message in English
 * with the Portuguese she wrote one tap away, and the app's own reply window named; a reply in her
 * language and his English that only his hold sends; WhatsApp's "read" shown on it afterwards; and a
 * customer's Instagram message named by its handle, with exactly what Instagram's API returned.
 *
 *   node scripts/browser/channels.js http://127.0.0.1:PORT [/path/to/screenshots]
 *
 * The backend is the real one; the messages came in through the real public doors, signed as Meta
 * signs them, and Claude is scripted for each sentence (tests/test_channels_browser.py). Each
 * sentence is typed into the page's own diagnostics field, which posts exactly what the microphone
 * posts. What is checked is what the owner sees, at the tablet's size and a phone's:
 *
 *   - the WhatsApp conversation is in English, labelled a machine translation, with no Portuguese on
 *     the glass until he taps "Original", and says "WhatsApp replies: open …";
 *   - the reply card prints the exact message, Portuguese first, says it is a machine translation,
 *     names her as his card does with WhatsApp's own name for her beside it, says how long WhatsApp
 *     allows, and waits for the hold; on the tablet nothing is sent; on the phone the hold and the
 *     tap send it, the card says Sent, WhatsApp's "read" arrives at the door (signed, as Meta sends
 *     it), and her conversation shows the reply as Read with the Portuguese behind "As sent";
 *   - the Instagram message is there under the customer's @handle, with Instagram's reply window,
 *     and the card says exactly what Instagram's conversations API returned;
 *   - nothing leaves the card's edge, the page does not scroll sideways, and nothing throws.
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...] }.
 */
'use strict';

const { chromium } = require('playwright-core');
const crypto = require('crypto');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
const SECRET = process.env.CLIVE_TEST_META_SECRET || '';
const WA = JSON.parse(process.env.CLIVE_TEST_WA || '{}');
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const SIZES = [
  { name: 'tablet', viewport: { width: 601, height: 889 }, dpr: 1.33, mobile: true, commit: false },
  { name: 'phone', viewport: { width: 390, height: 844 }, dpr: 3, mobile: true, commit: true },
];
// The same sentences tests/test_channels_browser.py scripts.
const SAID = {
  whatsapp: 'Any WhatsApp messages?',
  link: "That's Ana, our knitwear supplier",
  reply: 'Tell Ana thank you, and to send it on Friday',
  thread: "Show me Ana's conversation",
  instagram: 'Anything on Instagram?',
};
const MESSAGES = '#cards .card[data-type="messages"]';
const HOLD = '#cards .card[data-type="confirmation"]';
const SENT = '#cards .card[data-type="success"]';

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// WhatsApp's "read" for CLIVE's reply, as Meta sends it: the messages webhook's statuses, signed with
// the app secret (X-Hub-Signature-256: sha256=HMAC-SHA256 of the raw body).
async function whatsappRead(messageId) {
  const body = JSON.stringify({ object: 'whatsapp_business_account', entry: [{ id: WA.waba, changes: [{ field: 'messages', value: {
    messaging_product: 'whatsapp', metadata: { display_phone_number: '447700900123', phone_number_id: WA.phone },
    statuses: [{ id: messageId, status: 'read', timestamp: String(Math.floor(Date.now() / 1000)), recipient_id: WA.to }],
  } }] }] });
  const signature = 'sha256=' + crypto.createHmac('sha256', SECRET).update(body).digest('hex');
  const answer = await fetch(`${BASE}/hooks/whatsapp`, {
    method: 'POST', body, headers: { 'Content-Type': 'application/json', 'X-Hub-Signature-256': signature } });
  return answer.status;
}

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
    const file = path.join(OUT, `channels-${tag}-${name}.png`);
    await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
    shots.push(path.basename(file));
  };
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
  const tap = async (sel) => {
    const handle = await page.evaluateHandle((s) => {
      const c = Array.from(document.querySelectorAll(s)).pop();
      return c ? c.querySelector('.msg-reveal') : null;
    }, sel);
    const button = handle.asElement();
    if (button) { await button.scrollIntoViewIfNeeded(); await button.click(); }
    await sleep(300);
    return seen(sel);
  };

  // 1. The WhatsApp message: English, labelled, the Portuguese hidden, the window named.
  await say(SAID.whatsapp, MESSAGES);
  let card = await seen(MESSAGES);
  check(`${tag}: the WhatsApp message is in English, labelled, with no Portuguese showing, and WhatsApp's window named`,
    // Before he says who she is (the tablet's run) WhatsApp's name for her; after it (the phone's) his card's.
    card.found && (size.commit ? /\bAna\b/ : /Ana Fixture/).test(card.text) && /WhatsApp/.test(card.text)
      && /Hello, the sample is ready to ship tomorrow\./.test(card.text) && /Machine translation/.test(card.text)
      && !/amostra/.test(card.text) && /WhatsApp replies: open 2[34]h more/.test(card.text), JSON.stringify(card));
  check(`${tag}: the messages card fits`, card.found && !card.past.length && !card.sideways, JSON.stringify(card.past));
  await shot('1-whatsapp', MESSAGES);
  const opened = await tap(MESSAGES);
  await shot('2-original', MESSAGES);
  const closed = await tap(MESSAGES);
  check(`${tag}: one tap shows the Portuguese she wrote, a second hides it`,
    /Olá, a amostra está pronta para envio amanhã\./.test(opened.text || '') && /Hide original/.test(opened.text || '')
      && !/amostra/.test(closed.text || ''), `${opened.text} || ${closed.text}`);

  // 2. He says who it is, then the reply: Portuguese first, held.
  await say(SAID.link, MESSAGES);
  await say(SAID.reply, HOLD);
  card = await seen(HOLD);
  check(`${tag}: the card prints the exact message, Portuguese first, says it is a machine translation, and asks for the hold`,
    card.found && /Send on WhatsApp/.test(card.text)
      && /Obrigado\. Por favor, envie na sexta-feira\. Thank you\. Please send it on Friday\./.test(card.text)
      && /machine translation/i.test(card.text) && /hold/i.test(card.text) && !card.past.length && !card.sideways,
    JSON.stringify(card));
  check(`${tag}: the card names her as his card does, WhatsApp's name for her beside it, and how long WhatsApp allows`,
    card.found && /\b(?:To|TO)\s*Ana \(WhatsApp name: Ana Fixture\)/.test(card.text)
      && /WhatsApp allows\s*open 2[34]h more/i.test(card.text), JSON.stringify(card));
  await shot('3-reply-card', HOLD);

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
    check(`${tag}: his hold and tap send it, and the card says Sent only once WhatsApp confirmed it`, /Sent/.test(done), done);
    await shot('4-sent', SENT);
    const status = await whatsappRead('wamid.SENT1');
    await sleep(400);
    await say(SAID.thread, `${MESSAGES} .msg-bubble.is-out`);
    const ours = await page.evaluate((s) => {
      const b = Array.from(document.querySelectorAll(`${s} .msg-bubble.is-out`)).pop();
      return b ? b.innerText.replace(/\s+/g, ' ').trim() : '';
    }, MESSAGES);
    check(`${tag}: WhatsApp's "read" reached the door, and her conversation shows the reply, by CLIVE, read`,
      status === 200 && /Thank you\. Please send it on Friday\./.test(ours) && /CLIVE/.test(ours) && /Read/.test(ours)
        && !/Obrigado/.test(ours), `${status} ${ours}`);
    await shot('5-read', `${MESSAGES} .msg-bubble.is-out`);
    const reveal = await page.evaluateHandle((s) => {
      const b = Array.from(document.querySelectorAll(`${s} .msg-bubble.is-out`)).pop();
      return b ? b.querySelector('.msg-reveal') : null;
    }, MESSAGES);
    const button = reveal.asElement();
    if (button) { await button.scrollIntoViewIfNeeded(); await button.click(); }
    await sleep(300);
    const shown = await page.evaluate((s) => {
      const b = Array.from(document.querySelectorAll(`${s} .msg-bubble.is-out`)).pop();
      return b ? b.innerText.replace(/\s+/g, ' ').trim() : '';
    }, MESSAGES);
    check(`${tag}: the Portuguese that went with it is one tap away, under "As sent"`,
      Boolean(button) && /Obrigado\. Por favor, envie na sexta-feira\./.test(shown) && /Hide as sent/.test(shown), shown);
    await shot('6-as-sent', `${MESSAGES} .msg-bubble.is-out`);
  } else {
    const waiting = await page.evaluate((sel) => {
      const c = Array.from(document.querySelectorAll(sel)).pop();
      const s = c ? c.querySelector('.action-surface') : null;
      return s ? s.dataset.state : '';
    }, HOLD);
    check(`${tag}: nothing is sent while the card waits for the hold`, ['arming', 'armed'].includes(waiting), waiting);
  }

  // 3. Instagram: the customer's message under their handle, and exactly what Instagram's API returned.
  await say(SAID.instagram, MESSAGES);
  card = await seen(MESSAGES);
  check(`${tag}: the Instagram message is there under their @handle, with Instagram's window and what its API returned`,
    card.found && /@jo\.customer/.test(card.text) && /Instagram/.test(card.text)
      && /Is the black hoodie back in stock in medium\?/.test(card.text) && /Instagram replies: open 2[34]h more/.test(card.text)
      && /Instagram's API returned 0 conversations just now/.test(card.text) && !card.past.length && !card.sideways,
    JSON.stringify(card));
  await shot('7-instagram', MESSAGES);

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

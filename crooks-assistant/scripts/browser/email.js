/* The email workspace, driven with a finger in Chromium against the real backend.
 *
 *   node scripts/browser/email.js http://127.0.0.1:8765 [/path/to/screenshots]
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...] }.
 *
 * This is the file that answers D-9 and D-11, and it exists because nothing short of a
 * browser can answer them. The live session's rail rendered eight actions enabled and the
 * owner used none; the ASGI tests were green throughout, because a handler that EXISTS is
 * what they can see and a click path that WORKS is not. So every enabled chip on every card
 * this script opens is actually pressed, and what the screen does next is read back.
 *
 * The whole Reply path is walked the way a hand walks it: tap Reply, read who it is to, type
 * the words with real keystrokes, let a background redraw land underneath the keyboard, tap
 * Save draft, hold the card, and read VERIFIED. Then Archive, to VERIFIED, and the queue is
 * checked for the thread that left it. Nothing here stubs a response: the fixture Gmail and
 * the fixture shop are behind the socket, and the action engine is the real one.
 */
'use strict';

const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
// The physical tablet, portrait, as it sits on the workbench.
const VIEWPORT = { width: 601, height: 889 };
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const THREAD = 'aa70d3f83dbef06e';   // Mia, order 1938, inbound and unanswered
// [checker, 8 Oct 2026] Mia's row by its thread, where this tapped the queue's first row: the queue
// is the Inbox landing's since 28 September (DEC-063; app/families/landings.py), longest wait
// first, and Millie's two-day-old email is ahead of Mia's. The thread under test is still Mia's.
const MIAS_ROW = `#cards .row.tappable[data-kind="email_thread"][data-ref="${THREAD}"]`;

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Wait for the gesture to stop saying "Applying…". The Mac executes, then proves with a
// second read, and a lost commit response is recovered by asking rather than tapping again —
// so the honest wait is "until no surface is applying", with a ceiling. Polled rather than
// slept through, so a fast settle does not cost the run twenty seconds, and so a run that
// really is stuck reports the state it is stuck in.
async function waitApplied(page, ceilingMs) {
  const until = Date.now() + ceilingMs;
  for (;;) {
    const applying = await page.evaluate(() => Array.from(document.querySelectorAll('#cards .action-surface'))
      .filter((s) => /Applying/i.test(s.textContent || '')).length);
    if (!applying || Date.now() > until) return applying;
    await sleep(500);
  }
}

// The proposal card as it now stands, and where to put a finger on its gesture surface.
async function readProposal(page) {
  return page.evaluate(() => {
    const card = document.querySelector('#cards .card-confirmation');
    if (!card) return null;
    const surface = card.querySelector('.action-surface');
    const b = surface ? surface.getBoundingClientRect() : null;
    return {
      proposal: card.dataset.proposal || '',
      kind: surface ? surface.dataset.kind : '',
      state: surface ? surface.dataset.state : '',
      label: surface ? (surface.textContent || '').trim() : '',
      text: (card.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 240),
      x: b ? Math.round(b.x + b.width / 2) : 0, y: b ? Math.round(b.y + b.height / 2) : 0,
    };
  });
}

// The owner's hand on the card, in whichever grammar the Mac chose for it
// (app/actions/grammar.py): a tap, or a hold that arms and a tap that applies. Nothing is
// skipped — the dead time before a surface arms is waited out, and the hold is held still.
async function gesture(page, proposal) {
  await sleep(900);                                    // the dead time: a finger lifting is not a tap
  if (proposal.kind === 'tap_commit') {
    await page.touchscreen.tap(proposal.x, proposal.y);
    return;
  }
  await page.mouse.move(proposal.x, proposal.y);
  await page.mouse.down();
  await sleep(1500);                                   // HOLD_MS + margin, hand still
  await page.mouse.up();
  await sleep(300);
  await page.mouse.down();
  await sleep(120);
  await page.mouse.up();
}

async function main() {
  const browser = await chromium.launch({
    executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  });
  const context = await browser.newContext({
    viewport: VIEWPORT, deviceScaleFactor: 1, isMobile: true, hasTouch: true,
    extraHTTPHeaders: HEADERS,
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const from = (m.location && m.location() && m.location().url) || '';
    if (from.includes('/speak')) return;      // the 503 this file itself fulfils
    errors.push(`console: ${m.text()}`);
  });
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key","reason":"no voice under test"}' }));

  const shot = async (name) => {
    if (!OUT) return;
    fs.mkdirSync(OUT, { recursive: true });
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: false, animations: 'disabled' });
    shots.push(`${name}.png`);
  };

  // [checker, 8 Oct 2026] Without the start-up (`startup=off`, as customers.js, orders.js and
  // returns.js open the page): since 29 Sep a tap before it hands over only skips it
  // (web/startup.js), so the first tap on the queue below opened nothing.
  await page.goto(`${BASE}?dev=1&startup=off`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(700);
  await page.evaluate(() => {
    for (const b of document.querySelectorAll('.dev-banner')) b.remove();
    const speak = document.querySelector('#speak-toggle');
    if (speak && speak.checked) speak.checked = false;
  });

  // The diagnostics field posts exactly what the microphone posts — the page's own submit().
  const say = async (text) => {
    await page.evaluate(() => {
      const sheet = document.querySelector('#settings');
      const dev = document.querySelector('#dev');
      if (dev) dev.hidden = false;
      if (sheet && !sheet.open && sheet.showModal) sheet.showModal();
    });
    await page.fill('#dev-text', text);
    await page.press('#dev-text', 'Enter');
    await sleep(1400);
    await page.evaluate(() => { const sheet = document.querySelector('#settings'); if (sheet && sheet.open) sheet.close(); });
    await sleep(300);
  };

  // Everything on the rail, including what the disclosure is holding. A chip behind "2 more"
  // is one tap away, and a run that only drives what happens to be at full weight is not
  // driving the rail.
  const openRail = async () => {
    await page.evaluate(() => { for (const m of document.querySelectorAll('#cards .rail-more')) { if (m.getAttribute('aria-expanded') !== 'true') m.click(); } });
    await sleep(250);
  };

  const tapMiddle = async (selector) => {
    const box = await page.evaluate((sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const b = el.getBoundingClientRect();
      return { x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2), h: Math.round(b.height) };
    }, selector);
    if (!box || box.h <= 0) return false;
    await page.touchscreen.tap(box.x, box.y);
    return true;
  };

  const cards = () => page.evaluate(() => Array.from(document.querySelectorAll('#cards .card')).map((c) => c.dataset.type || ''));
  const stageState = () => page.evaluate(() => (document.querySelector('#stage') || {}).dataset?.state || '');

  // ---- 1. the queue, and into a thread
  await say('which customers need replying to?');
  const opened = await tapMiddle(MIAS_ROW);
  await sleep(1500);
  await openRail();
  const thread = await page.evaluate(() => {
    const card = document.querySelector('#cards .card-email_thread');
    if (!card) return null;
    const chips = Array.from(card.querySelectorAll('.rail-chip')).map((c) => {
      const b = c.getBoundingClientRect();
      return {
        action: c.dataset.action || '', mode: c.dataset.mode || '', command: c.dataset.command || '',
        args: c.dataset.args || '', ref: c.dataset.ref || '', family: c.dataset.family || '',
        off: c.getAttribute('aria-disabled') === 'true',
        why: (c.querySelector('.rail-why') || {}).textContent || '',
        h: Math.round(b.height), w: Math.round(b.width), visible: b.height > 0,
        behind: Boolean(c.closest('.rail-rest')),
      };
    });
    const more = card.querySelector('.rail-more');
    return {
      ref: card.dataset.ref || '', chips,
      more: more ? { text: (more.textContent || '').trim(), expanded: more.getAttribute('aria-expanded') } : null,
      link: (() => {
        const s = card.querySelector('.link-strip[data-kind="order"], .link-chip[data-kind="order"]');
        return s ? { kind: s.dataset.kind, ref: s.dataset.ref } : null;
      })(),
    };
  });
  check('a thread from the work queue opens on a tap', opened && thread !== null, `opened=${opened}`);
  if (!thread) { await finish(browser, errors); return checks.every((c) => c.ok) ? 0 : 1; }

  const enabled = thread.chips.filter((c) => !c.off);
  const disabled = thread.chips.filter((c) => c.off);
  check('the thread card knows which thread it is', thread.ref === THREAD, `ref=${thread.ref}`);
  check('Reply is a chip that opens something, not one that asks you to talk',
    enabled.some((c) => c.action === 'reply' && c.mode === 'open' && c.command === 'compose.reply' && c.args === `thread_id=${THREAD}`),
    JSON.stringify(enabled));
  check('every enabled chip on the rail can be clicked to somewhere',
    enabled.length > 0 && enabled.every((c) => (c.mode === 'open' && c.command && c.args) || (c.mode === 'stage' && c.ref) || (c.mode === 'ask' && c.family !== undefined)),
    JSON.stringify(enabled));
  check('every disabled chip on the rail says why it cannot be used',
    disabled.every((c) => c.why.trim().length > 0),
    JSON.stringify(disabled));
  check('its chips are big enough for a finger', thread.chips.length > 0 && thread.chips.every((c) => c.h >= 44),
    thread.chips.map((c) => `${c.action}:${c.h}px`).join(' '));
  check('the thread says which order it is about, tappably',
    Boolean(thread.link && thread.link.ref), JSON.stringify(thread.link));
  await shot('e01-thread');

  // ---- 2. every enabled chip is actually pressed, and the screen is read afterwards
  //
  // "The handler exists" is not a pass. Each chip is tapped in turn, from the thread card
  // freshly re-opened each time, and what the screen does is recorded.
  const drove = [];
  for (const chip of enabled) {
    await say('which customers need replying to?');
    await tapMiddle(MIAS_ROW);
    await sleep(1400);
    await openRail();
    const before = await cards();
    const hit = await tapMiddle(`#cards .card-email_thread .rail-chip[data-action="${chip.action}"]`);
    await sleep(1800);
    const after = await page.evaluate((action) => {
      const list = Array.from(document.querySelectorAll('#cards .card')).map((c) => c.dataset.type || '');
      const c = document.querySelector(`#cards .rail-chip[data-action="${action}"]`);
      return {
        list,
        said: c ? ((c.querySelector('.rail-said') || {}).textContent || '') : '',
        primed: c ? c.dataset.said || c.dataset.primed || '' : '',
        armed: Boolean(document.querySelector('#cards .armed-inline') || (document.querySelector('#armed') && !document.querySelector('#armed').hidden)),
        toast: ((document.querySelector('#toast') || {}).textContent || '').trim(),
      };
    }, chip.action);
    const responded = chip.mode === 'ask'
      ? Boolean(after.said || after.primed || after.armed)
      : JSON.stringify(after.list) !== JSON.stringify(before);
    drove.push({ action: chip.action, mode: chip.mode, hit, before, after: after.list, responded, toast: after.toast, said: after.said.slice(0, 60) });
  }
  check('every enabled chip, pressed with a finger, changes the screen',
    drove.length > 0 && drove.every((d) => d.hit && d.responded),
    JSON.stringify(drove));
  check('none of them answered with an error',
    drove.every((d) => !/could not|did not answer|cannot/i.test(d.toast)),
    drove.map((d) => `${d.action}:${d.toast}`).join(' | '));

  // ---- 2b. the ORDER rail, pressed the same way
  //
  // Six of the eight actions the live session rendered and nobody used live here: note,
  // refund, email, fulfil, address, cancel. Same rule as the thread's — an enabled chip that
  // does nothing when a finger lands on it is furniture — and the same method: press each
  // one, from a freshly drawn card, and read the screen afterwards.
  const railOf = async (number) => {
    await say(`show me order ${number}`);
    await openRail();
    return page.evaluate(() => {
      const card = document.querySelector('#cards .card-order');
      if (!card) return null;
      return {
        chips: Array.from(card.querySelectorAll('.rail-chip')).map((c) => {
          const b = c.getBoundingClientRect();
          return {
            action: c.dataset.action || '', mode: c.dataset.mode || '', command: c.dataset.command || '',
            args: c.dataset.args || '', family: c.dataset.family || '',
            off: c.getAttribute('aria-disabled') === 'true',
            why: ((c.querySelector('.rail-why') || {}).textContent || '').trim(),
            behind: Boolean(c.closest('.rail-rest')),
            h: Math.round(b.height),
          };
        }),
      };
    });
  };

  const open1938 = await railOf(1938);
  check('an order still has a rail', open1938 !== null && open1938.chips.length > 0,
    open1938 ? JSON.stringify(open1938.chips) : 'no order card');
  if (open1938) {
    const lead = open1938.chips.filter((c) => !c.behind).map((c) => c.action);
    // 1938 is unfulfilled and paid, AND its customer has written about it. So the reply
    // leads and the fulfilment is beside it: the order's own context decides, which is what
    // §22 asks for and what a rail that put Note first on every card could never do.
    check('an order leads with what its own state needs, not with a note',
      lead.length > 0 && lead.length <= 2 && lead[0] === 'email'
      && lead.indexOf('fulfil') !== -1 && lead.indexOf('note') === -1,
      `lead=${lead.join(',')} rest=${open1938.chips.filter((c) => c.behind).map((c) => c.action).join(',')}`);
    check('and every chip on it, disclosed or not, is a finger-sized control',
      open1938.chips.every((c) => c.h >= 44), open1938.chips.map((c) => `${c.action}:${c.h}px`).join(' '));

    const droveOrder = [];
    for (const chip of open1938.chips.filter((c) => !c.off)) {
      await railOf(1938);
      const before = await cards();
      const hit = await tapMiddle(`#cards .card-order .rail-chip[data-action="${chip.action}"]`);
      await sleep(1800);
      const after = await page.evaluate((action) => {
        const c = document.querySelector(`#cards .rail-chip[data-action="${action}"]`);
        return {
          list: Array.from(document.querySelectorAll('#cards .card')).map((x) => x.dataset.type || ''),
          said: c ? ((c.querySelector('.rail-said') || {}).textContent || '') : '',
          primed: c ? (c.dataset.said || c.dataset.primed || '') : '',
          armed: Boolean(document.querySelector('#cards .armed-inline') || (document.querySelector('#armed') && !document.querySelector('#armed').hidden)),
          toast: ((document.querySelector('#toast') || {}).textContent || '').trim(),
        };
      }, chip.action);
      const responded = chip.mode === 'ask'
        ? Boolean(after.said || after.primed || after.armed)
        : JSON.stringify(after.list) !== JSON.stringify(before);
      droveOrder.push({ action: chip.action, mode: chip.mode, hit, responded, said: after.said.slice(0, 48), toast: after.toast });
    }
    check('every enabled chip on an order, pressed with a finger, changes the screen',
      droveOrder.length > 0 && droveOrder.every((d) => d.hit && d.responded),
      JSON.stringify(droveOrder));
    check('and none of those answered with an error',
      droveOrder.every((d) => !/could not|did not answer|cannot|nothing open/i.test(d.toast)),
      droveOrder.map((d) => `${d.action}:${d.toast}`).join(' | '));
    // Email on an order is an "open" chip now: it puts a composer addressed to the customer
    // on the screen, which is the second typing path §20 asks for.
    const emailChip = open1938.chips.find((c) => c.action === 'email');
    if (emailChip && !emailChip.off) {
      await railOf(1938);
      await tapMiddle('#cards .card-order .rail-chip[data-action="email"]');
      await sleep(1800);
      const composed = await page.evaluate(() => {
        const card = document.querySelector('#cards .card-email_compose');
        return card ? {
          inputs: Array.from(card.querySelectorAll('.field-input')).map((f) => f.dataset.field),
          text: (card.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 160),
        } : null;
      });
      check('Email on an order opens an email to that customer, with the address typable',
        composed !== null && composed.inputs.indexOf('to') !== -1 && composed.inputs.indexOf('body') !== -1,
        composed ? JSON.stringify(composed) : 'no composer');
    }
  }

  // ---- 2c. the address, typed with a thumb (§20)
  //
  // The exact value the live session's own fixtures turn on. Until the Address chip opened
  // something, correcting one was a sentence into a microphone that had already produced four
  // recordings under 150 ms — and "SL4 1QN" and "SL4 1QM" are both valid postcodes.
  const addressOn = await railOf(1938);
  const addressChip = addressOn ? addressOn.chips.find((c) => c.action === 'address') : null;
  check('an order that has not shipped offers its address as something to type',
    Boolean(addressChip && !addressChip.off && addressChip.mode === 'open' && addressChip.command === 'address.open'),
    JSON.stringify(addressChip));
  if (addressChip && !addressChip.off) {
    await tapMiddle('#cards .card-order .rail-chip[data-action="address"]');
    await sleep(1800);
    const form = await page.evaluate(() => {
      const card = document.querySelector('#cards .card-workspace');
      if (!card) return null;
      return {
        fields: Array.from(card.querySelectorAll('.field-input')).map((f) => ({
          name: f.dataset.field, post: f.dataset.post, kind: f.dataset.kind,
          value: f.value, h: Math.round(f.getBoundingClientRect().height),
        })),
        typeMarks: card.querySelectorAll('.field-type').length,
        text: (card.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 200),
        buttons: Array.from(card.querySelectorAll('.compose-btn')).map((b) => ({ action: b.dataset.action, command: b.dataset.command, off: Boolean(b.disabled) })),
      };
    });
    check('tapping it opens the address as fields, already holding the address as it stands',
      form !== null && form.fields.some((f) => f.name === 'address1' && /Bridge Street/.test(f.value))
      && form.fields.some((f) => f.name === 'postcode' && f.value.length > 2),
      form ? JSON.stringify(form.fields) : 'no workspace card');
    if (form) {
      check('every line of it says it can be typed, and is big enough to type in',
        form.typeMarks >= form.fields.length && form.fields.every((f) => f.h >= 44),
        `marks=${form.typeMarks} fields=${form.fields.length} ${form.fields.map((f) => `${f.name}:${f.h}px`).join(' ')}`);
      check('and its keystrokes go to the family that owns them, not to the composer',
        form.fields.every((f) => f.post === 'address.field'),
        form.fields.map((f) => `${f.name}->${f.post}`).join(' '));
      // The correction itself: the house number, typed in front of the street.
      const street = '#cards .card-workspace .field-input[data-field="address1"]';
      await page.click(street);
      await page.evaluate((sel) => { const el = document.querySelector(sel); el.setSelectionRange(0, 0); }, street);
      await page.type(street, 'Flat 4, ', { delay: 15 });
      await sleep(1800);
      const corrected = await page.evaluate((sel) => {
        const el = document.querySelector(sel);
        const card = document.querySelector('#cards .card-workspace');
        const prepare = card ? card.querySelector('.compose-btn[data-action="prepare"]') : null;
        return {
          value: el ? el.value : null,
          focused: document.activeElement === el,
          state: (document.querySelector('#stage') || {}).dataset?.state || '',
          prepare: prepare ? !prepare.disabled : null,
          says: card ? (card.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 200) : '',
        };
      }, street);
      check('the correction lands in the field, keeps the keyboard, and starts no recording',
        /^Flat 4, 12 Bridge/.test(String(corrected.value)) && corrected.focused === true
        && corrected.state !== 'LISTENING' && corrected.state !== 'TRANSCRIBING',
        JSON.stringify(corrected).slice(0, 300));
      check('and the Mac now lets the change be prepared', corrected.prepare === true,
        `prepare=${corrected.prepare} says=${corrected.says.slice(0, 120)}`);
      await shot('e08-address');
    }
  }

  const shipped = await railOf(1939);
  check('a shipped order says why the things it cannot do cannot be done',
    shipped !== null && shipped.chips.filter((c) => c.off).length > 0
    && shipped.chips.filter((c) => c.off).every((c) => c.why.length > 0),
    shipped ? JSON.stringify(shipped.chips.filter((c) => c.off)) : 'no order card');
  check('and it does not put a dead Fulfil beside a live Refund',
    shipped !== null
    && shipped.chips.filter((c) => c.off).every((c) => c.behind)
    && shipped.chips.filter((c) => !c.behind).every((c) => !c.off),
    shipped ? shipped.chips.map((c) => `${c.action}:${c.off ? 'off' : 'on'}:${c.behind ? 'behind' : 'lead'}`).join(' ') : '');
  await shot('e07-order-rail');

  // ---- 3. the Reply path, end to end, asserting the VISIBLE state at every step
  await say('which customers need replying to?');
  await tapMiddle(MIAS_ROW);
  await sleep(1400);
  const stageBefore = await stageState();
  await tapMiddle(`#cards .card-email_thread .rail-chip[data-action="reply"]`);
  await sleep(1800);
  const composer = await page.evaluate(() => {
    const card = document.querySelector('#cards .card-email_compose');
    if (!card) return null;
    const inputs = Array.from(card.querySelectorAll('.field-input')).map((f) => f.dataset.field);
    return {
      compose: card.dataset.compose || '', thread: card.dataset.thread || '',
      text: (card.textContent || '').replace(/\s+/g, ' ').trim(),
      inputs,
      statics: Array.from(card.querySelectorAll('.field-static')).map((s) => s.dataset.field),
      typeMarks: card.querySelectorAll('.field-type').length,
      buttons: Array.from(card.querySelectorAll('.compose-btn')).map((b) => ({ action: b.dataset.action, command: b.dataset.command })),
    };
  });
  check('tapping Reply puts a reply on the screen', composer !== null && Boolean(composer.compose),
    composer ? JSON.stringify(composer.buttons) : 'no composer card');
  if (composer) {
    check('it says who the reply is to before a word is typed',
      /Replying to/i.test(composer.text) && /mia/i.test(composer.text),
      composer.text.slice(0, 200));
    check('the words of the reply are the one thing that can be typed',
      composer.inputs.join(',') === 'body' && composer.statics.join(',') === 'to,subject',
      `inputs=${composer.inputs.join(',')} fixed=${composer.statics.join(',')}`);
    check('and the card says how to put words in it, in a place a finger can see',
      /Tap the box to type/i.test(composer.text) && composer.typeMarks > 0,
      `marks=${composer.typeMarks}`);
    check('it offers a way to dictate as well as a way to type',
      composer.buttons.some((b) => b.action === 'dictate' && b.command === 'voice.bind'),
      JSON.stringify(composer.buttons));
    check('and a way out that is not the back button',
      composer.buttons.some((b) => b.action === 'discard' && b.command === 'compose.discard'),
      JSON.stringify(composer.buttons));
  }
  await shot('e02-reply-composer');

  // ---- 4. typing: real keystrokes, and none of them may start a recording
  const WORDS = 'Hi Mia — yes, we can add the cap. I will send a link to pay the difference.';
  const body = '#cards .card-email_compose .field-input[data-field="body"]';
  const before = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const b = el.getBoundingClientRect();
    return { top: Math.round(b.top), h: Math.round(b.height) };
  }, body);
  check('the body field is on the screen and big enough to type in',
    Boolean(before && before.h >= 44), JSON.stringify(before));
  await page.click(body);
  await page.type(body, WORDS, { delay: 12 });
  const typing = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    return {
      value: el ? el.value : null,
      focused: document.activeElement === el,
      state: (document.querySelector('#stage') || {}).dataset?.state || '',
      talk: ((document.querySelector('#talk-label') || {}).textContent || '').trim(),
    };
  }, body);
  check('typing puts the characters in the field', typing.value === WORDS, `"${String(typing.value).slice(0, 60)}"`);
  check('typing never starts a recording', typing.state !== 'LISTENING' && typing.state !== 'TRANSCRIBING' && !/Release to send/i.test(typing.talk),
    `state=${typing.state} (was ${stageBefore}) talk="${typing.talk}"`);
  check('and the field still has the keyboard after the last keystroke', typing.focused === true, `focused=${typing.focused}`);

  // The Mac's copy, after the debounce. The card is redrawn from the answer; the caret and
  // the focus have to come back with it.
  await sleep(1600);
  const settled = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    const wrap = el && el.closest ? el.closest('.field') : null;
    return { value: el ? el.value : null, focused: document.activeElement === el, unsaved: wrap ? wrap.dataset.unsaved || '' : 'no field' };
  }, body);
  check('the Mac takes the value and the card comes back with it, still focused',
    settled.value === WORDS && settled.focused === true && !settled.unsaved,
    JSON.stringify(settled).slice(0, 200));

  // ---- 5. a background redraw from the Mac's OLDER copy, landing while the thumb is in the field
  //
  // §20: "preserve unsaved content across harmless redraws". This is the redraw the owner
  // never asks for — an enrichment landing, a sibling card settling — drawn from the payload
  // the Mac sent BEFORE the typing, which is exactly one round trip behind the thumb.
  const MORE = ' Sending that now.';
  await page.click(body);
  await page.type(body, MORE, { delay: 8 });          // inside the 400 ms debounce
  const kept = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    const card = el && el.closest ? el.closest('.card') : null;
    if (!card || !window.CrooksUI) return { error: 'no card' };
    // The composer as the Mac last described it, with an EMPTY body: the stale copy.
    const stale = [{
      type: 'email_compose',
      data: {
        compose_id: card.dataset.compose, kind: 'reply', thread_id: card.dataset.thread,
        to: { value: 'mia@example.com', status: 'ok', editable: false },
        to_name: 'Mia Jones',
        subject: { value: 'Re: Order 1938 — can I add to it?', status: 'ok', editable: false },
        body: { value: '', status: 'uncertain', editable: true },
        how: 'Tap the box to type, or hold the dock and say it.',
        actions: [
          { id: 'dictate', label: 'Dictate', command: 'voice.bind', args: `family=email.reply&kind=email_thread&ref=${card.dataset.thread}` },
          { id: 'save_draft', label: 'Save draft', mode: 'stage', command: 'compose.stage', args: `compose_id=${card.dataset.compose}&mode=draft` },
          { id: 'send', label: 'Send', mode: 'stage', risk: 'red', command: 'compose.stage', args: `compose_id=${card.dataset.compose}&mode=send` },
          { id: 'discard', label: 'Cancel', command: 'compose.discard', args: `compose_id=${card.dataset.compose}` },
        ],
      },
    }];
    const out = window.CrooksUI.render(stale, {});
    const fresh = out.nodes[0];
    card.parentNode.replaceChild(fresh, card);
    return { drawn: Boolean(fresh) };
  }, body);
  await sleep(400);
  const survived = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    const wrap = el && el.closest ? el.closest('.field') : null;
    return { value: el ? el.value : null, focused: document.activeElement === el, unsaved: wrap ? wrap.dataset.unsaved || '' : '' };
  }, body);
  check('a redraw the owner did not ask for keeps what the thumb typed, and gives the keyboard back',
    kept.drawn === true && survived.value === WORDS + MORE && survived.focused === true && survived.unsaved === 'true',
    `${JSON.stringify(kept)} ${JSON.stringify(survived).slice(0, 200)}`);
  await shot('e03-typed');

  // ---- 6. stage it, gesture on it, and read the terminal answer
  //
  // One more keystroke first, so the Mac's copy is the one on the screen: the redraw above
  // replaced the node the debounce was holding, and a value nobody posted cannot be staged.
  //
  // THE FIXTURE INBOX REFUSES EVERY WRITE, deliberately (experience/fixtures/gmail.py): the
  // golden world proves reads, proposals and gestures, and never mutates a mailbox. So what
  // is asserted here is the whole path up to and including the TERMINAL answer — the gesture
  // is made, the Mac executes, the proof fails because the fixture refused it, and the card
  // says so in words. What must never happen, and did for the whole live session, is a card
  // left saying "Applying…" over a change that has finished. The verified branch is asserted
  // in section 7b, where the commit's answer is the one thing stubbed.
  await page.click(body);
  await page.type(body, ' ', { delay: 10 });
  await sleep(1800);
  const staged = await page.evaluate(() => {
    const b = document.querySelector('#cards .card-email_compose .compose-btn[data-action="save_draft"]');
    if (!b) return false;
    b.click();
    return true;
  });
  await sleep(2500);
  const proposal = await readProposal(page);
  check('Save draft prepares a change and the card waits for a gesture',
    staged && proposal !== null && Boolean(proposal.proposal),
    proposal ? JSON.stringify(proposal).slice(0, 240) : 'no confirmation card');
  if (proposal) {
    check('the card the gesture is on shows the words that will be sent',
      /add the cap/i.test(proposal.text), proposal.text);
    await gesture(page, proposal);
    const applying = await waitApplied(page, 20000);
    const done = await page.evaluate(() => {
      const card = document.querySelector('#cards .card');
      return {
        types: Array.from(document.querySelectorAll('#cards .card')).map((c) => c.dataset.type || ''),
        said: card ? (card.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 200) : '',
      };
    });
    check('the gesture reaches a terminal answer, in words, either way',
      done.types.length > 0 && /success|error/.test(done.types.join(',')) && done.said.length > 10,
      JSON.stringify(done).slice(0, 300));
    check('and nothing is left saying "Applying…" over a change that has finished',
      applying === 0, `applying=${applying}`);
    await shot('e04-terminal');
  }

  // ---- 7a. Archive, from the thread, to its terminal answer
  //
  // From the queue into the thread and back out of it, which is how the owner does it: the
  // queue is then one Back away, and a proven archive has to have taken the thread out of it
  // as well as off the card in front of him.
  await say('which customers need replying to?');
  await sleep(300);
  const queueBefore = await page.evaluate((ref) => {
    const card = document.querySelector('#cards .card-email_list');
    if (!card) return null;
    return {
      rows: Array.from(card.querySelectorAll('.row')).map((r) => r.dataset.ref || ''),
      has: Boolean(card.querySelector(`.row[data-ref="${ref}"]`)),
    };
  }, THREAD);
  check('the work queue still has the thread in it', Boolean(queueBefore && queueBefore.has),
    JSON.stringify(queueBefore));
  await tapMiddle(`#cards .card-email_list .row[data-ref="${THREAD}"]`);
  await sleep(1600);
  await openRail();
  const archiveHit = await tapMiddle('#cards .card-email_thread .rail-chip[data-action="email_archive"]');
  await sleep(2500);
  const archiveCard = await readProposal(page);
  check('Archive on the thread prepares the change', archiveHit && archiveCard !== null,
    `hit=${archiveHit} ${JSON.stringify(archiveCard)}`);
  if (archiveCard) {
    await gesture(page, archiveCard);
    const applying = await waitApplied(page, 20000);
    const answered = await page.evaluate(() => {
      const card = document.querySelector('#cards .card');
      return { type: card ? card.dataset.type || '' : '', said: card ? (card.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 200) : '' };
    });
    check('the archive gesture reaches a terminal answer too',
      /success|error/.test(answered.type) && answered.said.length > 10 && applying === 0,
      JSON.stringify(answered).slice(0, 300));
  }

  // ---- 7b. and when the Mac proves it, the thread leaves the active queue
  //
  // The one stub in this file, and it is the narrowest one that can exist: the COMMIT's
  // answer. The fixture inbox will not archive anything, so a verified archive cannot be
  // produced here — but what a verified archive should DO to the screen is the tablet's own
  // job, and it is the half the live session never got to see. The Mac's half — that a proven
  // archive names the thread that left the inbox — is asserted against the real presenter in
  // tests/test_email_workspace.py. Everything else below is the real page: the real queue, the
  // real thread card, the real proposal, the real gesture.
  await say('which customers need replying to?');
  await sleep(300);
  await tapMiddle(`#cards .card-email_list .row[data-ref="${THREAD}"]`);
  await sleep(1600);
  await openRail();
  const again = await tapMiddle('#cards .card-email_thread .rail-chip[data-action="email_archive"]');
  await sleep(2500);
  const second = await readProposal(page);
  check('the thread can be archived again after a failed proof', again && second !== null,
    `hit=${again} ${JSON.stringify(second)}`);
  if (second) {
    await page.route('**/actions/*/commit', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        proposal_id: second.proposal, status: 'verified', code: 'verified',
        operation: 'gmail_thread_archive', spoken: 'Archived.',
        // Exactly what app/presentation.py answers for a proven archive — the success card
        // naming the thread that left the inbox, and the thread itself behind it so the owner
        // lands back on the conversation. That shape is asserted against the real presenter in
        // tests/test_email_workspace.py; what is under test HERE is what the tablet does with it.
        ui: [
          { type: 'success', data: {
            title: 'Archived', detail: 'Thread thread', proposal_id: second.proposal,
            operation: 'gmail_thread_archive', note: '',
            archived: { kind: 'email_thread', ref: THREAD },
          } },
          { type: 'email_thread', data: {
            thread_id: THREAD, subject: 'Order 1938 — can I add to it?', message_count: 1,
            messages: [{ from: 'Mia Jones', from_email: 'mia.jones@example.com', body: 'Is it too late to add a cap?', date: '' }],
            actions: [], link_confidence: 'none',
          } },
        ],
      }),
    }));
    await gesture(page, second);
    await waitApplied(page, 15000);
    await sleep(800);
    const proven = await page.evaluate(() => {
      const success = document.querySelector('#cards .card-success');
      const thread = document.querySelector('#cards .card-email_thread');
      return {
        title: success ? (success.querySelector('.card-title') || {}).textContent || '' : '',
        archived: success ? success.dataset.archived || '' : '',
        types: Array.from(document.querySelectorAll('#cards .card')).map((c) => c.dataset.type || ''),
        threadBack: Boolean(thread),
        threadMarked: Boolean(thread && thread.classList.contains('is-archived')),
        threadSays: thread ? (thread.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120) : '',
      };
    });
    check('a proven archive brings the thread back with it, marked archived',
      /archiv/i.test(proven.title) && proven.archived === THREAD
      && proven.threadBack === true && proven.threadMarked === true && /Archived/.test(proven.threadSays),
      JSON.stringify(proven).slice(0, 320));
    await shot('e05-archived');
    // And the queue: the page holds its own copy of the screen the owner archived FROM, and
    // that copy must not still list the thread when he goes back to it.
    const queueAfter = await page.evaluate((ref) => {
      const out = { checked: 0, stillListed: 0, notes: [] };
      for (const queue of document.querySelectorAll('.card-email_list')) {
        out.checked += 1;
        if (queue.querySelector(`.row[data-ref="${ref}"]`)) out.stillListed += 1;
        const note = queue.querySelector('.queue-note');
        if (note) out.notes.push((note.textContent || '').trim());
      }
      return out;
    }, THREAD);
    check('and no queue this page is holding still lists it',
      queueAfter.stillListed === 0, JSON.stringify(queueAfter).slice(0, 300));
    await page.unroute('**/actions/*/commit');
  }

  // ---- 8. the relations, both ways, with a finger
  await say('show me order 1938');
  await sleep(300);
  const toEmail = await page.evaluate(() => {
    const tab = document.querySelector('#cards .card-order [data-tab="email"]');
    if (tab) tab.click();
    return Boolean(tab);
  });
  await sleep(600);
  const mailRow = await page.evaluate(() => {
    const row = document.querySelector('#cards .card-order .mail .row[data-kind="email_thread"]');
    if (!row) return null;
    const b = row.getBoundingClientRect();
    return { ref: row.dataset.ref, x: Math.round(b.x + 40), y: Math.round(b.y + b.height / 2) };
  });
  check('an order says which email is about it, as something a finger can open',
    toEmail && mailRow !== null, `tab=${toEmail} row=${JSON.stringify(mailRow)}`);
  if (mailRow) {
    await page.touchscreen.tap(mailRow.x, mailRow.y);
    await sleep(1800);
    const landed = await page.evaluate(() => {
      const card = document.querySelector('#cards .card');
      return { type: card ? card.dataset.type || '' : '', ref: card ? card.dataset.ref || '' : '' };
    });
    check('and tapping it opens the thread — order to email, the direction that did not work',
      landed.type === 'email_thread', JSON.stringify(landed));
    // And back the other way, from the thread to the order.
    const strip = await page.evaluate(() => {
      const s = document.querySelector('#cards .card-email_thread .link-strip[data-kind="order"], #cards .card-email_thread .link-chip[data-kind="order"]');
      if (!s) return null;
      const b = s.getBoundingClientRect();
      return { ref: s.dataset.ref, x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2) };
    });
    if (strip) {
      await page.touchscreen.tap(strip.x, strip.y);
      await sleep(1800);
      const back = await page.evaluate(() => {
        const card = document.querySelector('#cards .card');
        return { type: card ? card.dataset.type || '' : '' };
      });
      check('and the thread opens its order — email to order', back.type === 'order', JSON.stringify(back));
    } else {
      check('and the thread opens its order — email to order', false, 'no linked-order strip on the thread');
    }
    await shot('e06-relations');
  }

  check('no script error during the whole run', errors.length === 0, errors.slice(0, 4).join(' | '));
  await finish(browser, errors);
  return checks.every((c) => c.ok) ? 0 : 1;
}

async function finish(browser) {
  await browser.close();
}

main().then((code) => {
  process.stdout.write(`${JSON.stringify({ ok: checks.every((c) => c.ok), checks, shots })}\n`);
  process.exit(code);
}).catch((e) => {
  checks.push({ name: 'the email browser run', ok: false, detail: String(e && e.message).slice(0, 400) });
  process.stdout.write(`${JSON.stringify({ ok: false, checks, shots })}\n`);
  process.exit(1);
});

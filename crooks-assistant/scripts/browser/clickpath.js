/* §33 — the real click paths, walked with a finger, judged on what is ON THE GLASS.
 *
 *   node scripts/browser/clickpath.js http://127.0.0.1:8765 [/path/to/screenshots]
 *
 * The rule this file exists for: NEVER AN HTTP CODE. The live session recorded eight
 * `navigation.home` commands posted and eight accepted, zero refused — and the owner pressed
 * Home four times in three seconds because nothing he could see had happened. A 200 is not an
 * arrival. So every step below is judged on the VISIBLE SEMANTIC DESTINATION: which card types
 * are in the deck, which record each is about, which tab is open, what the trail says. The
 * network is not consulted once.
 *
 * Four paths, from the brief:
 *
 *   1. Idle → Orders → Order → Customer → Orders tab → prior order → Back → customer
 *      → Back → original order
 *   2. Inbox → Thread → Customer → Order → Back
 *   3. Customer → Inbox → Compose → Cancel
 *   4. Split → select left → open order → switch right → open inbox → switch left → Back
 *      → switch right — RETIRED but for its first hop (the Orders icon under a finger): George
 *      retired user-facing Split on 20 September 2026 (DEC-050), and DEC-050 with DEC-037/038
 *      says Split-specific UI and tests are migration evidence, not permanent requirements.
 *
 * Every hop is taken by finding the control the owner would find — a row that names a record,
 * a tab, a chip in the trail, Back — and pressing it for 95 ms, the median of the live
 * session's taps. Two things can then go wrong, and they are DIFFERENT defects reported
 * differently:
 *
 *   MISSING   there is no control on the glass for that hop at all. The path stops and the
 *             check names what was not there. On this tree an order card offers no way to
 *             reach its own customer, which is the whole of path 1.
 *   UNREACHED the control is there and the press did not land or did not arrive. The press is
 *             then delivered directly so the rest of the path is still measured, and the
 *             detail says which of the two it was — because "Merge cannot be tapped" and
 *             "Merge is not on the screen" are not the same report.
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots, paths }.
 */
'use strict';

const { chromium } = require('playwright-core');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
// The tablet's own size. A click path that only works at 800 x 1280 is not a click path the
// owner has: the navigation strip at 601 px is 571 px wide with 807 px of controls in it.
const VIEWPORT = { width: 601, height: 889, dpr: 1.33 };
const PRESS_MS = 95;

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 460) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ---- what is on the glass ---------------------------------------------------------------
   The only thing any check below is allowed to read. Card types, which record each card is
   about, which tab is open, the trail, and the branch header. */
const glass = (page) => page.evaluate(() => {
  const short = (r) => String(r || '').split('/').pop();
  return {
    mode: document.body.dataset.mode || '',
    cards: Array.from(document.querySelectorAll('#cards .card')).map((c) => {
      const tabbed = c.querySelector('.tabbed');
      const open = c.querySelector('[role="tab"][aria-selected="true"]');
      return {
        type: c.dataset.type || '',
        ref: short(c.dataset.ref),
        tab: tabbed ? (tabbed.dataset.tab || '') : '',
        tab_label: open ? (open.textContent || '').trim() : '',
      };
    }),
    trail: Array.from(document.querySelectorAll('#stack .chip, #stack > *')).map((s) => (s.textContent || '').replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 4),
    head: ((document.querySelector('#branch-head') || {}).textContent || '').replace(/\s+/g, ' ').trim(),
    back: Boolean(document.querySelector('#back-btn')) && !document.querySelector('#back-btn').hidden,
    branches: Array.from(document.querySelectorAll('.branch-chip')).map((c) => ({
      head: c.dataset.head || '', on: c.getAttribute('aria-pressed') === 'true',
      words: (c.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 22),
    })),
  };
});

const where = (g) => `${g.mode}: ${g.cards.map((c) => `${c.type}${c.ref ? `(${c.ref})` : ''}${c.tab ? `[${c.tab}]` : ''}`).join(' + ') || 'nothing'}`;

/* ---- the paths ---------------------------------------------------------------------------
   A step is what the owner does and what must then be true on the glass. `find` names the
   control to press, in the page's own vocabulary; `expect` is the destination. */
const PATHS = [
  {
    id: '1-orders-customer-prior-order-back',
    name: 'Idle → Orders → Order → Customer → Orders tab → prior order → Back → customer → Back → original order',
    steps: [
      { do: 'dock', area: 'orders', expect: { any_type: ['order_list'] } },
      { do: 'open', kind: 'order', remember: 'origin', expect: { any_type: ['order'], ref_is: 'origin' } },
      { do: 'tab', name: 'customer', expect: { tab_is: 'customer' } },
      { do: 'open', kind: 'customer', remember: 'customer', expect: { any_type: ['customer'], ref_is: 'customer' } },
      { do: 'tab', name: 'orders', expect: { tab_is: 'orders' } },
      { do: 'open', kind: 'order', remember: 'prior', expect: { any_type: ['order'], ref_is: 'prior' } },
      { do: 'back', expect: { any_type: ['customer'], ref_is: 'customer' } },
      { do: 'back', expect: { any_type: ['order'], ref_is: 'origin' } },
    ],
  },
  {
    id: '2-inbox-thread-customer-order-back',
    name: 'Inbox → Thread → Customer → Order → Back',
    steps: [
      { do: 'dock', area: 'email', expect: { any_type: ['email_list'] } },
      { do: 'open', kind: 'email_thread', remember: 'thread', expect: { any_type: ['email_thread'], ref_is: 'thread' } },
      { do: 'open', kind: 'customer', remember: 'customer', expect: { any_type: ['customer'], ref_is: 'customer' } },
      // The way a person reaches a customer's orders: the tab that says Orders. Asked as its
      // own hop so a failure says WHICH half is missing — the tab, or something behind it.
      { do: 'tab', name: 'orders', expect: { tab_is: 'orders' } },
      { do: 'open', kind: 'order', remember: 'order', expect: { any_type: ['order'], ref_is: 'order' } },
      { do: 'back', expect: { any_type: ['customer'], ref_is: 'customer' } },
    ],
  },
  {
    id: '3-customer-inbox-compose-cancel',
    name: 'Customer → Inbox → Compose → Cancel',
    steps: [
      { do: 'dock', area: 'email', expect: { any_type: ['email_list'] } },
      { do: 'open', kind: 'email_thread', expect: { any_type: ['email_thread'] } },
      { do: 'open', kind: 'customer', remember: 'customer', expect: { any_type: ['customer'], ref_is: 'customer' } },
      { do: 'tab', name: 'email', expect: { tab_is: 'email' } },
      { do: 'open', kind: 'email_thread', remember: 'thread', expect: { any_type: ['email_thread'], ref_is: 'thread' } },
      { do: 'rail', action: 'reply', expect: { any_type: ['email_compose'] } },
      { do: 'rail', action: 'discard', expect: { none_of: ['email_compose'] } },
    ],
  },
  {
    // Retired under DEC-050 (Split retired by George, 20 Sep 2026; DEC-037/038: Split-specific UI
    // and tests are migration evidence, not permanent requirements). The eight Split hops are gone,
    // with the whole-path check they made: Split, the left half, an order in it, the right half,
    // the Inbox icon in it, the left half again, Back in it, the right half again. The first hop is
    // not Split's — it is a finger on the Orders icon at the Tab A's own size — and it stays.
    id: '4-split-two-halves-independent',
    name: 'Orders (the Split hops of this path are retired: DEC-050)',
    steps: [
      { do: 'dock', area: 'orders', expect: { any_type: ['order_list'] } },
    ],
  },
];

async function main() {
  const browser = await chromium.launch({
    executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  });
  try {
    for (const route of PATHS) await walk(browser, route);
  } finally {
    await browser.close();
  }
  const ok = checks.every((c) => c.ok);
  process.stdout.write(`${JSON.stringify({ ok, checks, shots, paths: PATHS.map((p) => p.id) })}\n`);
  return ok ? 0 : 1;
}

async function walk(browser, route) {
  const context = await browser.newContext({
    viewport: { width: VIEWPORT.width, height: VIEWPORT.height }, deviceScaleFactor: VIEWPORT.dpr,
    isMobile: true, hasTouch: true, extraHTTPHeaders: HEADERS,
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const from = (m.location && m.location() && m.location().url) || '';
    if (from.includes('/speak')) return;
    errors.push(`console: ${m.text()}`);
  });
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key","reason":"no voice under test"}' }));
  // What the Mac answered, kept only to ENRICH a failure. No check reads it: the verdict is
  // always the glass. But "the composer is still on screen" and "the composer is still on
  // screen AND the Mac said Gone, nothing was saved" are worth an hour of each other's time.
  const replies = [];
  page.on('response', async (res) => {
    const url = res.url().replace(BASE, '');
    if (!/^\/(command|turn)/.test(url)) return;
    try {
      const body = await res.json();
      replies.push(`${url} ${res.status()} answer="${String(body.answer || '').slice(0, 60)}" changed=${Object.keys(body.changed || {}).join('|') || 'none'} ui=${(body.ui || []).map((i) => i.type).join(',') || 'none'}`);
    } catch { /* not json, or already consumed */ }
  });
  await page.goto(`${BASE}?dev=1`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await page.evaluate(() => { for (const b of document.querySelectorAll('.dev-banner')) b.remove(); });
  const cdp = await context.newCDPSession(page);

  const at = (n, what) => `PATH ${route.id} · step ${n} · ${what}`;
  const memory = {};
  let step = 0;
  let broken = '';
  try {
    for (const each of route.steps) {
      step += 1;
      if (broken) {
        // The path is cut. Say so for each remaining hop rather than reporting nine
        // failures that all mean the same thing, or — worse — silently stopping.
        check(at(step, `${describe(each)} — not reached`), false, `the path stopped at step ${broken}`);
        continue;
      }
      const before = await glass(page);
      const took = await hop(page, cdp, each, memory, before);
      if (took.missing) {
        check(at(step, `${describe(each)}: the control exists on the glass`), false,
          `MISSING — ${took.missing}. from ${where(before)}`);
        broken = String(step);
        continue;
      }
      const after = await glass(page);
      const verdict = judge(each.expect || {}, after, memory);
      const how = took.already ? 'already there — no hop needed. '
        : took.inert ? `INERT — "${took.words}" does nothing even when activated directly. `
          : took.direct ? `UNREACHED — a ${PRESS_MS}ms press on "${took.words}" did not land; delivered directly instead. ` : '';
      check(at(step, `${describe(each)} → ${verdict.wanted}`), verdict.ok,
        `${verdict.ok ? '' : how}${verdict.why} · glass: ${where(after)} · trail ${JSON.stringify(after.trail)}`
        + (verdict.ok ? '' : ` · the Mac said: ${replies.slice(-1)[0] || 'nothing was posted'}`));
      if (!verdict.ok) broken = String(step);
      if (took.direct && !took.inert) {
        check(at(step, `a ${PRESS_MS}ms press on ${describe(each)} lands`), false,
          `"${took.words}" had to be activated directly for the path to continue — it is wired, the touch did not reach it`);
      }
      await shot(page, `clickpath-${route.id}-${String(step).padStart(2, '0')}`);
    }
    check(`PATH ${route.id} · the whole path is walkable: ${route.name}`, !broken,
      broken ? `stopped at step ${broken} of ${route.steps.length}` : `${route.steps.length} hops`);
    check(`PATH ${route.id} · no script error while walking it`, errors.length === 0, errors.slice(0, 3).join(' | '));
  } catch (e) {
    check(`PATH ${route.id} · the walk ran`, false, String((e && e.message) || e).slice(0, 400));
  } finally {
    await context.close();
  }
}

function describe(step) {
  switch (step.do) {
    case 'dock': return `the ${step.area} dock button`;
    case 'open': return `a control that opens a ${step.kind}`;
    case 'tab': return `the ${step.name} tab`;
    case 'rail': return `the ${step.action} action`;
    case 'back': return 'Back';
    case 'split': return 'Split';
    case 'half': return `the ${step.which === 0 ? 'left' : 'right'} half`;
    default: return step.do;
  }
}

/* The destination, judged only on the glass. `ref_is` is the strongest form: the record the
   control NAMED must be the record now on screen — which is what "Back returns to the
   original order" means, and what a card-type check alone cannot say. */
function judge(want, g, memory) {
  const wanted = [];
  if (want.any_type) wanted.push(want.any_type.join('/'));
  if (want.ref_is) wanted.push(`for ${memory[want.ref_is] || '?'}`);
  if (want.tab_is) wanted.push(`open on ${want.tab_is}`);
  if (want.none_of) wanted.push(`no ${want.none_of.join('/')}`);
  if (want.branches) wanted.push(`${want.branches} halves`);
  const label = wanted.join(' ') || 'something';
  const types = g.cards.map((c) => c.type);

  if (want.any_type && !want.any_type.some((t) => types.indexOf(t) !== -1)) {
    return { ok: false, wanted: label, why: `nothing of ${want.any_type.join('/')} is on the glass` };
  }
  if (want.none_of) {
    const bad = want.none_of.filter((t) => types.indexOf(t) !== -1);
    if (bad.length) return { ok: false, wanted: label, why: `${bad.join(',')} is still on the glass` };
  }
  if (want.ref_is) {
    const target = memory[want.ref_is];
    const hit = g.cards.find((c) => (!want.any_type || want.any_type.indexOf(c.type) !== -1) && c.ref && target && c.ref === target);
    if (!hit) {
      return {
        ok: false, wanted: label,
        why: `it is about ${g.cards.filter((c) => c.ref).map((c) => c.ref).join(',') || 'nothing named'}, not ${target || '(nothing was remembered)'}`,
      };
    }
  }
  if (want.tab_is) {
    const open = g.cards.find((c) => c.tab === want.tab_is);
    if (!open) return { ok: false, wanted: label, why: `the open tab is ${g.cards.map((c) => c.tab).filter(Boolean).join(',') || 'none'}` };
  }
  if (want.branches !== undefined && g.branches.length !== want.branches) {
    return { ok: false, wanted: label, why: `${g.branches.length} halves on the glass` };
  }
  return { ok: true, wanted: label, why: 'arrived' };
}

/* One hop. Finds the control, presses it for 95 ms, and — if nothing moved — activates it
   directly so the rest of the path can still be measured, saying which happened. */
async function hop(page, cdp, step, memory, before) {
  const found = await locate(page, step);
  if (!found) return { missing: missingWords(step) };
  if (found.remember && step.remember) memory[step.remember] = found.remember;

  // What "it landed" MEANS, per control. Judging every hop by "the deck changed" made
  // selecting the half that is already selected look like a swallowed touch — a defect this
  // file invented. A tab has its own evidence, and so does a half.
  const landed = async () => {
    if (step.do === 'half') {
      return page.evaluate((which) => {
        const chip = Array.from(document.querySelectorAll('.branch-chip'))[which];
        return Boolean(chip && chip.getAttribute('aria-pressed') === 'true');
      }, step.which);
    }
    if (step.do === 'tab') {
      return page.evaluate((name) => Array.from(document.querySelectorAll('#cards .tabbed'))
        .some((t) => (t.dataset.tab || '') === name), step.name);
    }
    const now = await glass(page);
    return JSON.stringify(now.cards) !== JSON.stringify(before.cards)
      || now.branches.length !== before.branches.length
      || JSON.stringify(now.branches.map((b) => b.on)) !== JSON.stringify(before.branches.map((b) => b.on));
  };
  const settle = async () => {
    for (let i = 0; i < 24; i++) {
      await sleep(180);
      if (await landed()) return true;
    }
    return false;
  };
  // Already there: pressing the half that is lit, or the tab that is open, is not a hop and
  // must not be reported as an unreachable control.
  if (await landed()) return { direct: false, already: true, words: found.words };

  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: found.x, y: found.y }] });
  await sleep(PRESS_MS);
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  if (await settle()) return { direct: false, words: found.words };

  // The press did not arrive. Deliver it the way no finger can, purely so the remaining hops
  // are still walked — and report that it had to be done.
  await page.evaluate((mark) => {
    const el = document.querySelector(`[data-clickpath="${mark}"]`);
    if (el) el.click();
  }, found.mark);
  const moved = await settle();
  return { direct: true, inert: !moved, words: found.words };
}

function missingWords(step) {
  switch (step.do) {
    case 'open': return `no control on the glass opens a ${step.kind} — the graph has no edge here`;
    case 'tab': return `no ${step.name} tab on any card`;
    case 'rail': return `no enabled ${step.action} action on any card`;
    case 'dock': return `no dock button for ${step.area}`;
    case 'back': return 'Back is not on the screen';
    case 'split': return 'no Split control';
    case 'half': return `there is no ${step.which === 0 ? 'left' : 'right'} half to select`;
    default: return `nothing for ${step.do}`;
  }
}

/* Where to press, and what the control claims it will open. Marks the node with
   `data-clickpath` so the direct fallback can find the same one. */
function locate(page, step) {
  return page.evaluate((spec) => {
    const mark = `cp${Date.now()}${Math.floor(Math.random() * 1000)}`;
    const short = (r) => String(r || '').split('/').pop();
    const pick = () => {
      if (spec.do === 'dock') return document.querySelector(`.dock-btn[data-area="${spec.area}"]`);
      if (spec.do === 'back') {
        const b = document.querySelector('#back-btn');
        return b && !b.hidden ? b : null;
      }
      if (spec.do === 'split') {
        return document.querySelector('#branch-rail [data-action="split"], #branch-bar [data-action="split"]');
      }
      if (spec.do === 'half') {
        const chips = Array.from(document.querySelectorAll('.branch-chip'));
        return chips[spec.which] || null;
      }
      if (spec.do === 'tab') {
        // Only a tab that is not already the open one; pressing the open tab is not a hop.
        return Array.from(document.querySelectorAll('#cards [role="tab"]'))
          .find((t) => t.dataset.tab === spec.name) || null;
      }
      if (spec.do === 'rail') {
        return Array.from(document.querySelectorAll('#cards [data-action], #cards [data-command]'))
          .find((el) => {
            if (el.disabled === true || el.getAttribute('aria-disabled') === 'true') return false;
            const name = el.dataset.action || el.dataset.command || '';
            return name === spec.action || name.startsWith(`${spec.action}.`) || name.endsWith(`.${spec.action}`);
          }) || null;
      }
      if (spec.do === 'open') {
        // A control that says which record it opens. `data-ref` + `data-kind` is the one door
        // the deck's click handler posts `open.entity` through, so this is the page's own
        // vocabulary and not a selector invented here. Anything inside a card that is ABOUT
        // that same record is skipped: the card itself carries a ref.
        const cards = new Set(Array.from(document.querySelectorAll('#cards .card')).map((c) => c.dataset.ref || ''));
        return Array.from(document.querySelectorAll('#cards [data-ref][data-kind]'))
          .find((el) => {
            if (el.dataset.kind !== spec.kind) return false;
            if (el.classList.contains('card')) return false;
            if (cards.has(el.dataset.ref)) return false;   // already the record on screen
            const b = el.getBoundingClientRect();
            return b.width > 2 && b.height > 2;
          }) || null;
      }
      return null;
    };
    const el = pick();
    if (!el) return null;
    el.dataset.clickpath = mark;
    if (el.scrollIntoView) el.scrollIntoView({ block: 'center' });
    const b = el.getBoundingClientRect();
    return {
      mark,
      x: Math.round(b.left + b.width / 2), y: Math.round(b.top + b.height / 2),
      remember: short(el.dataset.ref || ''),
      words: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 30),
    };
  }, step);
}

async function shot(page, name) {
  if (!OUT) return;
  const file = path.join(OUT, `${name}.png`);
  await page.waitForTimeout(280);
  await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
  shots.push(path.basename(file));
}

main().then((code) => process.exit(code)).catch((e) => {
  process.stdout.write(`${JSON.stringify({ ok: false, checks: checks.concat([{ name: 'clickpath run', ok: false, detail: String((e && e.stack) || e).slice(0, 600) }]), shots })}\n`);
  process.exit(1);
});

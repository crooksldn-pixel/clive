/* §30 — the states the owner actually held, put back on a screen and measured.
 *
 * Phase 4's browser gate was nineteen invented fixtures and it was green all the way through
 * an evening in which the tablet swallowed sixty-three taps, drew seven full profile pages for
 * a one-line answer, and answered a request for a customer's orders with an empty inbox. The
 * brief's verdict on it: "A screenshot suite that never reaches the broken state is not
 * sufficient." This file is the answer.
 *
 *   node scripts/browser/replay.js http://127.0.0.1:8765 [/path/to/screenshots]
 *
 * Every state comes from `experience/fixtures/live_states.json`, which is DERIVED from the
 * 1,365-event physical timeline by `experience/fixtures/live_states.py`. Not one shape, height,
 * tab, collision count, refusal code or tap duration in it was invented; not one customer name
 * or email address from that file reaches it. See that module's header for the scrubbing.
 *
 * Each state is asked two different questions, and they are named differently on purpose:
 *
 *   FIXTURE   does this still REACH the broken state? Seven cards, 265 px each, 1,949 px of
 *             deck, seven distinct refs, every one open on Email. If the fixture stops
 *             reproducing what the tablet recorded then the instrument is broken, and a gate
 *             whose fixtures have quietly drifted is exactly the failure Phase 4 had.
 *
 *   GATE      is it FIXED? Asked of the real backend with the real sentence the owner said, or
 *             of the real page with a real finger. These are the checks that fail on this tree
 *             and pass when the workstream named in the fixture lands, so a red line here is
 *             the proof the gate works rather than a fault in it.
 *
 * The viewport is the tablet's own — 601 × 889 at DPR 1.33, exactly what every `tablet_render`
 * in the session reports — because these are that tablet's states and no other size's.
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots, states }.
 */
'use strict';

const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const STATES = path.join(__dirname, '..', '..', 'experience', 'fixtures', 'live_states.json');

// The physical tablet, from the telemetry: 601 x 889 at DPR 1.33 on every render of the session.
const VIEWPORT = { width: 601, height: 889, dpr: 1.33 };

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 500) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function load() {
  return JSON.parse(fs.readFileSync(STATES, 'utf8'));
}

async function main() {
  const fixture = load();
  const states = fixture.states || [];
  const browser = await chromium.launch({
    executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  });
  try {
    check(`the live fixture was derived from ${fixture.source}`,
      states.length >= 10 && fixture.events > 1000,
      `${states.length} states from ${fixture.events} events`);
    for (const state of states) await one(browser, state);
  } finally {
    await browser.close();
  }
  const ok = checks.every((c) => c.ok);
  process.stdout.write(`${JSON.stringify({ ok, checks, shots, states: states.map((s) => s.id) })}\n`);
  return ok ? 0 : 1;
}

/* A page in the state the page starts in, with the noise removed. One per state, deliberately:
   these states are about what a FRESH screen does, and a page that has already been driven
   through nine of them is not that. */
async function fresh(browser) {
  const context = await browser.newContext({
    viewport: { width: VIEWPORT.width, height: VIEWPORT.height }, deviceScaleFactor: VIEWPORT.dpr,
    isMobile: true, hasTouch: true, extraHTTPHeaders: HEADERS,
  });
  const page = await context.newPage();
  const errors = [];
  const posts = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const from = (m.location && m.location() && m.location().url) || '';
    if (from.includes('/speak')) return;
    // `/held` is a hook this file ASKS FOR and the Mac does not have yet (see the
    // no_control_carries_unheld_ref step). Its 404 is this file's own probe, not a fault in
    // the page, and counting it would fail a run over a request this file made.
    if (from.includes('/held')) return;
    errors.push(`console: ${m.text()}`);
  });
  page.on('request', (r) => { if (r.method() === 'POST') posts.push(r.url().replace(BASE, '')); });
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key","reason":"no voice under test"}' }));
  // A microphone that makes a noise, so a recording that must NOT be sent is proved not to be
  // sent rather than merely being too short to send. This is the whole point of the burst test:
  // the live session's sixty-three junk recordings were all "too short", and a silent
  // microphone here would produce the same excuse and hide the defect.
  await page.addInitScript(() => {
    const AC = window.AudioContext || window.webkitAudioContext;
    const ac = new AC();
    const dest = ac.createMediaStreamDestination();
    const osc = ac.createOscillator(); const gain = ac.createGain(); gain.gain.value = 0.2;
    osc.frequency.value = 220; osc.connect(gain); gain.connect(dest); osc.start();
    navigator.mediaDevices.getUserMedia = async () => { await ac.resume(); return dest.stream; };
  });
  await page.goto(`${BASE}?dev=1`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  // The developer banner is a fixed strip production never shows. Leaving it would be a
  // collision this file invented.
  await page.evaluate(() => { for (const b of document.querySelectorAll('.dev-banner')) b.remove(); });
  await page.evaluate(() => {
    window.__replayDraw = (items, opts) => {
      const root = document.querySelector('#cards');
      if (!root) return { nodes: 0, skipped: ['no deck'] };
      const out = window.CrooksUI.render(items, opts || {});
      root.replaceChildren();
      out.nodes.forEach((n) => root.appendChild(n));
      document.body.dataset.mode = 'context';
      return { nodes: out.nodes.length, skipped: out.skipped };
    };
  });
  return { context, page, errors, posts };
}

/* What is on the glass, in the same vocabulary the tablet's own telemetry uses — so a replay
   can be compared with the render the tablet recorded, field for field. */
const readDeck = (page) => page.evaluate(() => {
  const cards = Array.from(document.querySelectorAll('#cards .card'));
  const deck = document.querySelector('#cards');
  return {
    mode: document.body.dataset.mode || '',
    cards: cards.map((c) => {
      const tabbed = c.querySelector('.tabbed');
      const open = c.querySelector('[role="tab"][aria-selected="true"]');
      return {
        type: c.dataset.type || '',
        ref: c.dataset.ref || '',
        height: Math.round(c.getBoundingClientRect().height),
        tabs: Array.from(c.querySelectorAll('[role="tab"]')).map((t) => (t.textContent || '').trim()),
        tab_active: open ? (open.textContent || '').trim() : '',
        tab_name: tabbed ? (tabbed.dataset.tab || '') : '',
      };
    }),
    cards_height: deck ? deck.scrollHeight : 0,
    answer: ((document.querySelector('#answer') || {}).textContent || '').trim().slice(0, 200),
  };
});

const scanNow = (page, opts) => page.evaluate((o) => {
  const s = window.CrooksCollide.scan(o || {});
  const counts = {};
  for (const k of Object.keys(s.counts || {})) if (s.counts[k]) counts[k] = s.counts[k];
  return { total: s.total, interactive: s.interactive, counts, worst: (s.interactive_hits || []).slice(0, 4) };
}, opts || null);

async function one(browser, state) {
  const { context, page, errors, posts } = await fresh(browser);
  const id = state.id;
  const fx = (what) => `FIXTURE · ${id} · ${what}`;
  const gate = (what) => `GATE · ${id} · ${what}`;
  const owned = state.owned_by ? ` [${state.owned_by}]` : '';
  try {
    if (state.replay) await replay(page, state, fx, gate);
    if (state.drive) await drive(page, state, fx, gate, posts, owned);
    if (state.ask) await ask(page, state, fx, gate, owned);
    check(fx('no script error while replaying it'), errors.length === 0, errors.slice(0, 3).join(' | '));
  } catch (e) {
    check(fx('the replay ran'), false, String((e && e.message) || e).slice(0, 400));
  } finally {
    await context.close();
  }
}

/* ---- the payload states: put the cards back, and prove they are the cards he saw --------- */

async function replay(page, state, fx, gate) {
  const spec = state.replay;
  const want = spec.expect || {};
  const seen = state.observed || {};
  const drawn = await page.evaluate(([items, opts]) => window.__replayDraw(items, opts),
    [spec.ui, spec.tab ? { tab: spec.tab } : {}]);
  check(fx('the renderer drew every card the state had'),
    drawn.nodes === (want.card_count || spec.ui.length) && (drawn.skipped || []).length === 0,
    `nodes=${drawn.nodes} skipped=${(drawn.skipped || []).join(',')}`);
  await page.waitForTimeout(240);
  const deck = await readDeck(page);
  await shot(page, `replay-${state.id}`);

  // The shape, against what the tablet recorded. Types and count are exact; the deck height is
  // a floor or a ceiling, because a height in CSS pixels depends on the font the machine has.
  if (want.types) {
    check(fx(`it is ${want.types.length} × ${[...new Set(want.types)].join(' + ')}, as the tablet recorded`),
      JSON.stringify(deck.cards.map((c) => c.type)) === JSON.stringify(want.types),
      `drew ${deck.cards.map((c) => c.type).join(',')}`);
  }
  if (want.distinct_refs !== undefined) {
    const refs = new Set(deck.cards.map((c) => c.ref).filter(Boolean));
    check(fx(`${want.distinct_refs} distinct record${want.distinct_refs === 1 ? '' : 's'} behind ${deck.cards.length} cards`),
      refs.size === want.distinct_refs, `${refs.size}: ${[...refs].join(',')}`);
  }
  if (want.deck_height_min !== undefined) {
    check(fx(`the deck is at least ${want.deck_height_min}px, as the ${seen.cards_height}px the tablet measured`),
      deck.cards_height >= want.deck_height_min, `${deck.cards_height}px`);
  }
  if (want.deck_height_max !== undefined) {
    check(fx(`the deck is at most ${want.deck_height_max}px, as the ${seen.cards_height}px the tablet measured`),
      deck.cards_height <= want.deck_height_max, `${deck.cards_height}px`);
  }
  if (want.every_card_open_on) {
    const tabbed = deck.cards.filter((c) => c.tabs.length);
    const wrong = tabbed.filter((c) => c.tab_active !== want.every_card_open_on);
    check(fx(`every tabbed card opens on ${want.every_card_open_on}, which is what he was shown`),
      tabbed.length > 0 && wrong.length === 0,
      `${tabbed.length} tabbed, ${wrong.length} not on ${want.every_card_open_on}: ${tabbed.map((c) => c.tab_active).join(',')}`);
  }
  /* The inverse, and the reason it exists. A FIXTURE expectation reproduces what the tablet
     recorded, so `every_card_open_on` asserted a DEFECT — seven cards forced onto Email by
     one deck-wide tab. D-2's fix is in this renderer, so that state cannot be reproduced any
     more, and an expectation that cannot fail for the right reason must not be left standing
     as though it could. This is what replaced it: the same payload, the same deck-wide tab
     handed in by `__replayDraw`, and the claim that it reaches NO card. Stronger than what
     it replaced, because "this is what he saw" was a description and this is a rule. */
  if (want.no_card_open_on) {
    const tabbed = deck.cards.filter((c) => c.tabs.length);
    const forced = tabbed.filter((c) => c.tab_active === want.no_card_open_on);
    check(fx(`no card can be forced onto ${want.no_card_open_on} by a deck-wide tab (D-2)`),
      tabbed.length > 0 && forced.length === 0,
      `${tabbed.length} tabbed, ${forced.length} on ${want.no_card_open_on}: ${tabbed.map((c) => c.tab_active).join(',')}`);
  }

  // §9 applies to a live state as much as to a stress fixture: the screen he actually had must
  // not contain an interactive collision either.
  const scan = await scanNow(page);
  check(gate('zero collisions involving an interactive element on this real screen'),
    scan.interactive === 0,
    `${scan.interactive} of ${scan.total} — ${JSON.stringify(scan.worst)}`);

  // And the verdict the fixture carries, when it has one that can be asked of the renderer.
  const verdict = spec.verdict || {};
  if (verdict.max_cards_open_on) {
    for (const label of Object.keys(verdict.max_cards_open_on)) {
      const limit = verdict.max_cards_open_on[label];
      const on = deck.cards.filter((c) => c.tab_active === label);
      // D-2. One tab selection came from one tap on one record. It cannot be the right answer
      // for two different records, whatever shape the fix takes: if the tab becomes a property
      // of the entity, only the entity that was tapped opens there; if the renderer stops
      // taking a branch-wide `tab` at all, neither does.
      check(gate(`at most ${limit} card opens on ${label} when a branch-wide tab is handed to ${deck.cards.length}`),
        on.length <= limit, `${on.length} of ${deck.cards.length} opened on ${label}`);
    }
  }
}

/* ---- the asked states: the owner's own sentence, to the real backend --------------------- */

/* `fx` as well as `gate`, since the `routes_to_model` branch reports a FIXTURE limitation
   rather than a gate verdict and the two prefixes mean different things in the report. It was
   added to the branch and not to the signature, and the whole state then failed as
   "the replay ran :: fx is not defined" — one undefined name taking eight checks with it,
   which is why `no script error while replaying it` is asserted beside every state. */
async function ask(page, state, fx, gate, owned) {
  const spec = state.ask;
  const turn = await page.evaluate(async (text) => {
    const id = localStorage.getItem('crooks.session') || `replay-${Date.now()}`;
    localStorage.setItem('crooks.session', id);
    const r = await fetch('/turn', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store',
      body: JSON.stringify({ text, session_id: id }),
    });
    return r.json();
  }, spec.text);
  const types = (turn.ui || []).map((i) => i.type);
  await page.evaluate((payload) => window.__replayDraw(payload.ui || [], {}), turn);
  await page.waitForTimeout(240);
  const deck = await readDeck(page);
  await shot(page, `replay-${state.id}-asked`);

  // How the sentence was ROUTED, kept in every detail line. The fixture backend has no model
  // — `experience/harness.py` binds a provider that answers "[model answer]" and calls no
  // tools — so a sentence no family matched draws nothing here, and that fact has to be
  // legible in the failure or it reads as a missing card rather than as a missing family.
  // Which is the defect §13 names: a summary question that no family claims is left to the
  // model, and in the live session the model answered it with seven profile reads.
  const routed = `lane=${turn.lane || '?'}${turn.recipe_id ? ` recipe=${turn.recipe_id}` : ''}`;
  const drew = `ui=${types.join(',') || 'nothing'}`;
  const stub = String(turn.answer || '') === '[model answer]';
  const because = stub ? ' — no family matched, so the answer was left to the model and nothing was drawn' : '';

  if (spec.require_any_type) {
    const hit = spec.require_any_type.some((t) => types.indexOf(t) !== -1);
    /* `routes_to_model` says the DESIGN sends this sentence to the model, and it changes what
       the absence of a card means. Without it, "nothing was drawn" is D-4's defect: a
       question no family claimed, left to a model that then read seven customers one at a
       time. With it, the same absence is this world's own limit — `experience/harness.py`
       binds a provider that answers "[model answer]" and calls no tools, so a model-routed
       turn CANNOT draw anything here however well the product handles it.

       The distinction is a fixture's to declare, not a check's to infer, because the two
       cases look identical from the browser. Declared on exactly one state, with the reason
       and the word count, and the check then measures what it can see: that the routing is
       the routing the design intends. The §3/§4 claim for that sentence — a new read
       ENRICHES the workspace instead of becoming the screen — is held where it is
       measurable, by tests/test_workspaces.py's D-3 test against the real payload.

       What this must never become is a way to excuse an unclaimed sentence. A state that
       declares it and then turns out to be claimed by a family is reported too, below. */
    if (spec.routes_to_model) {
      check(fx(`"${spec.text.slice(0, 48)}…" is routed as the design intends: to the model`),
        stub && !turn.recipe_id,
        `${routed} · ${drew} — ${spec.routes_to_model}`);
      check(fx('and this world cannot draw a model-routed turn, so §4 is held in pytest instead'),
        !hit, `${drew} — if a card DID come back, this fixture no longer needs the exemption`);
    } else {
      check(gate(`"${spec.text.slice(0, 58)}…" puts one of ${spec.require_any_type.join('/')} on screen`) + owned,
        hit, `${drew} · ${routed}${because} · answer="${String(turn.answer || '').slice(0, 70)}"`);
    }
  }
  if (spec.forbid_types) {
    const bad = spec.forbid_types.filter((t) => types.indexOf(t) !== -1);
    check(gate(`and never a ${spec.forbid_types.join('/')} card`) + owned, bad.length === 0, `ui=${types.join(',')}`);
  }
  // A ceiling passes trivially when nothing was drawn, and a gate that goes green because
  // nothing happened is worse than one that goes red: it is how Phase 4's suite stayed green.
  // So every ceiling below also requires that SOMETHING came back.
  if (spec.max_cards_of_type) {
    for (const type of Object.keys(spec.max_cards_of_type)) {
      const limit = spec.max_cards_of_type[type];
      const n = types.filter((t) => t === type).length;
      check(gate(`a summary question draws a surface, and at most ${limit} ${type} profile${limit === 1 ? '' : 's'} — not the ${state.observed.cards.length} he got`) + owned,
        types.length > 0 && n <= limit, `${n} ${type} cards · ${drew} · ${routed}${because}`);
    }
  }
  if (spec.max_deck_height !== undefined) {
    check(gate(`and the deck it draws stays under ${spec.max_deck_height}px, against the ${state.observed.cards_height}px he scrolled`) + owned,
      types.length > 0 && deck.cards_height <= spec.max_deck_height,
      `${deck.cards_height}px · ${drew} · ${routed}${because}`);
  }
  if (spec.one_card_per_entity) {
    const refs = deck.cards.map((c) => c.ref).filter(Boolean);
    const dup = refs.filter((r, i) => refs.indexOf(r) !== i);
    check(gate('one entity is one surface: a deck is drawn, and no record is in it twice') + owned,
      types.length > 0 && dup.length === 0,
      `duplicated: ${[...new Set(dup)].join(',') || 'none'} · ${drew} · ${routed}${because}`);
  }
}

/* ---- the driven states: a finger, a refusal, seven presses of Home --------------------- */

const branchesNow = (page) => page.evaluate(async () => {
  const id = localStorage.getItem('crooks.session') || '';
  const r = await fetch(`/branches?session_id=${encodeURIComponent(id)}`, { cache: 'no-store' });
  const d = await r.json();
  return { count: (d.branches || []).length, ids: (d.branches || []).map((b) => b.branch_id), focused: d.focused || '' };
});

/* A tap with a DURATION, at a point on the glass — which is the only kind of tap this system
   can be tested with. `page.touchscreen.tap` is instantaneous, and an instantaneous press is
   below every threshold in the touch layer, so it would pass a gate that a 90 ms press fails.
   The live session's taps were 39 to 140 ms. */
async function pressAt(page, cdp, x, y, ms) {
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] });
  await sleep(ms);
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
}

/* Did the page START RECORDING? Not "did it send audio" — that is a different and much weaker
   question, and asking it is how a gate could have watched the live session happen and seen
   nothing. A hold of 39 to 140 ms produces a blob under 800 bytes, which web/app.js discards
   locally with `recording_too_short` and never posts: all sixty-three of the swallowed taps
   were invisible on the network. What they were not invisible to is the GLASS — the orb
   pulsed, the pill changed to "Release to send", `#talk[data-recording]` went true and the
   state went LISTENING. So the probe watches the page.

   Installed once per page, before anything is tapped, and read back afterwards. */
const watchRecording = (page) => page.evaluate(() => {
  window.__recordings = { started: 0, tooShort: 0, states: [] };
  const talk = document.querySelector('#talk');
  if (talk) {
    new MutationObserver(() => {
      if (talk.dataset.recording === 'true') window.__recordings.started += 1;
    }).observe(talk, { attributes: true, attributeFilter: ['data-recording'] });
  }
  const stage = document.querySelector('#stage');
  if (stage) {
    new MutationObserver(() => {
      const s = stage.dataset.state || '';
      if (s && window.__recordings.states[window.__recordings.states.length - 1] !== s) {
        window.__recordings.states.push(s);
      }
    }).observe(stage, { attributes: true, attributeFilter: ['data-state'] });
  }
  const err = document.querySelector('#errline');
  if (err) {
    new MutationObserver(() => {
      if (/too short/i.test(err.textContent || '')) window.__recordings.tooShort += 1;
    }).observe(err, { childList: true, characterData: true, subtree: true });
  }
});

const recordingsSoFar = (page) => page.evaluate(() => window.__recordings || { started: 0, tooShort: 0, states: [] });
const resetRecordings = (page) => page.evaluate(() => {
  if (window.__recordings) { window.__recordings.started = 0; window.__recordings.tooShort = 0; window.__recordings.states = []; }
});

async function drive(page, state, fx, gate, posts, owned) {
  const cdp = await page.context().newCDPSession(page);
  await watchRecording(page);
  // What the last `post_command` step was told, so the step after it can ask what the owner
  // was given rather than only what the HTTP layer was.
  let lastRefusal = { code: '', detail: '' };

  for (const step of state.drive.steps) {
    switch (step.do) {
      case 'idle': {
        const idle = await page.evaluate(() => ({
          mode: document.body.dataset.mode,
          bar: !(document.querySelector('#branch-bar') || {}).hidden,
          split: Boolean(document.querySelector('#branch-bar [data-action="split"]')),
        }));
        // [checker, 8 Oct 2026] Was 'the idle screen is the screen, with the halves on it' (the
        // branch bar shown, with a Split control). Split is retired (DEC-050, 20 Sep): the idle
        // screen is still the screen, and Split is not on it.
        check(fx('the idle screen is the screen, and Split is not on it (DEC-050)'),
          idle.mode === 'orb' && !idle.split, JSON.stringify(idle));
        await shot(page, `replay-${state.id}-idle`);
        break;
      }
      case 'retired': {
        // [checker, 8 Oct 2026] A control retired with Split (DEC-050), where a step used to
        // hit-test it, tap it or count what it drew: nothing on the screen may offer it.
        const shown = await page.evaluate((sel) => Array.from(document.querySelectorAll(sel)).filter((el) => {
          const b = el.getBoundingClientRect();
          return b.width > 0 && b.height > 0;
        }).length, step.selector);
        check(gate(`${step.selector} is retired with Split (DEC-050): nothing on the screen offers it`) + owned,
          shown === 0, `${shown} on screen`);
        break;
      }
      case 'hit_test': {
        // The question no geometry can answer: if a finger lands on the centre of this
        // control, what does the browser hand the touch to? D-1 is entirely this.
        const found = await page.evaluate((sel) => Array.from(document.querySelectorAll(sel)).map((el) => {
          const b = el.getBoundingClientRect();
          const x = Math.round(b.left + b.width / 2); const y = Math.round(b.top + b.height / 2);
          const top = document.elementFromPoint(x, y);
          const name = (t) => (t ? `${t.tagName.toLowerCase()}${t.id ? `#${t.id}` : ''}${t.className && typeof t.className === 'string' ? `.${t.className.split(' ')[0]}` : ''}` : 'nothing');
          return {
            words: (el.textContent || '').trim().slice(0, 14),
            at: `${x},${y}`, reaches: top === el || el.contains(top), top: name(top),
          };
        }), step.selector);
        const lost = found.filter((f) => !f.reaches);
        check(gate(`a finger on ${step.selector} reaches it`) + owned,
          found.length > 0 && lost.length === 0,
          found.length === 0 ? 'nothing matched that selector' : lost.map((f) => `"${f.words}" at ${f.at} hands the touch to ${f.top}`).join(' | '));
        break;
      }
      case 'tap_selector': {
        const where = await page.evaluate((sel) => {
          const el = document.querySelector(sel);
          if (!el) return null;
          const b = el.getBoundingClientRect();
          return { x: Math.round(b.left + b.width / 2), y: Math.round(b.top + b.height / 2) };
        }, step.selector);
        if (!where) { check(gate(`${step.selector} is on the screen to be tapped`) + owned, false, 'nothing matched'); break; }
        posts.length = 0;
        await resetRecordings(page);
        const before = await branchesNow(page);
        await pressAt(page, cdp, where.x, where.y, 95);   // the median of the live bursts
        await sleep(1900);
        const after = await branchesNow(page);
        check(gate(`a 95 ms press on ${step.selector} does something`) + owned,
          after.count !== before.count || after.focused !== before.focused,
          `branches ${before.count}→${after.count}, focus ${before.focused.slice(0, 8)}→${after.focused.slice(0, 8)}`);
        if (step.expect_no_post) {
          const rec = await recordingsSoFar(page);
          check(gate('and does not start a recording instead') + owned,
            !posts.includes(step.expect_no_post) && rec.started === 0 && rec.tooShort === 0,
            `posted ${[...new Set(posts)].join(',') || 'nothing'}; ${rec.started} recording(s) started, ${rec.tooShort} "too short"; states ${rec.states.join('→') || 'none'}`);
        }
        // If the finger did not get through, reach the state another way so the REST of the
        // sequence is still measured. Otherwise one unreachable control hides everything
        // behind it, and "Merge cannot be tapped" would be reported as "Merge is not on the
        // screen" — which is a different defect and a worse report.
        if (after.count === before.count && after.focused === before.focused) {
          await page.evaluate((sel) => { const el = document.querySelector(sel); if (el) el.click(); }, step.selector);
          await sleep(1800);
          const forced = await branchesNow(page);
          check(fx(`${step.selector} still WORKS when the touch is delivered to it directly`),
            forced.count !== before.count || forced.focused !== before.focused,
            `a DOM click took branches ${before.count}→${forced.count} — the control is wired; the touch never reached it`);
        }
        break;
      }
      case 'undivide_controls': {
        /* §25/§26, and D-1 on whatever is actually there. The un-divide strip carries ONE
           control per distinct outcome: with something on the other half, Merge (keep what
           it found) and Close (let it go); with nothing on it, those are the same act and
           only Close is drawn (web/app.js `holdsSomething` says why at length).

           Asserted as a SET, not a count, and then every member hit-tested. That is what
           makes it an instrument rather than a fixture tweak: it fails if Merge is missing
           from a half that holds something, it fails if Merge is drawn over one that holds
           nothing, and it fails if either is on the glass but the finger does not reach it —
           which is the defect the owner actually hit ("I cannot click the merge or close
           button ... because wherever I press just leads to you listening"). */
        const strip = await page.evaluate(() => {
          const host = document.querySelector('#branch-bar .branch-acts');
          const acts = Array.from(host ? host.querySelectorAll('[data-action]') : []);
          const name = (t) => (t ? `${t.tagName.toLowerCase()}${t.id ? `#${t.id}` : ''}${t.className && typeof t.className === 'string' ? `.${t.className.split(' ')[0]}` : ''}` : 'nothing');
          return acts.map((el) => {
            const b = el.getBoundingClientRect();
            const x = Math.round(b.left + b.width / 2); const y = Math.round(b.top + b.height / 2);
            const top = document.elementFromPoint(x, y);
            return {
              action: el.dataset.action || '',
              words: (el.textContent || '').trim().slice(0, 12),
              at: `${x},${y}`,
              onScreen: b.left >= 0 && b.right <= innerWidth + 0.5 && b.top >= 0 && b.bottom <= innerHeight + 0.5,
              reaches: top === el || el.contains(top),
              top: name(top),
            };
          });
        });
        const want = (step.expect || []).slice().sort();
        const got = strip.map((c) => c.action).sort();
        check(gate(`the un-divide strip is exactly [${want.join(', ')}] — one control per outcome`) + owned,
          JSON.stringify(want) === JSON.stringify(got),
          `${step.why ? `${step.why}; ` : ''}drew [${got.join(', ') || 'nothing'}]`);
        const lost = strip.filter((c) => !c.reaches);
        const off = strip.filter((c) => !c.onScreen);
        check(gate('and a finger reaches every control in it') + owned,
          strip.length > 0 && lost.length === 0,
          strip.length === 0 ? 'the strip is empty, so nothing could be hit-tested'
            : lost.map((c) => `"${c.words}" at ${c.at} hands the touch to ${c.top}`).join(' | ')
              || strip.map((c) => `${c.action} at ${c.at}`).join(', '));
        check(gate('and every control in it is wholly on the glass') + owned,
          strip.length > 0 && off.length === 0,
          off.map((c) => `"${c.words}" at ${c.at}`).join(' | ') || `${strip.length} on screen`);
        break;
      }
      case 'expect_branches': {
        const now = await branchesNow(page);
        check(gate(`there ${step.count === 1 ? 'is 1 half' : `are ${step.count} halves`} afterwards`) + owned,
          now.count === step.count, `${now.count}`);
        await shot(page, `replay-${state.id}-branches-${now.count}`);
        break;
      }
      case 'tap_burst': {
        // The 23:08:31 burst, with the durations the tablet recorded, beside the dock.
        const ms = (state.observed && state.observed.ms) || [];
        const where = await page.evaluate((sel) => {
          const el = document.querySelector(sel);
          if (!el) return null;
          const b = el.getBoundingClientRect();
          return { x: Math.round(b.left + b.width / 2), y: Math.round(b.top + b.height / 2) };
        }, step.near);
        if (!where || !ms.length) {
          check(gate('the dock burst could be replayed') + owned, false, `near=${step.near} taps=${ms.length}`);
          break;
        }
        posts.length = 0;
        await resetRecordings(page);
        for (const each of ms) {
          await pressAt(page, cdp, where.x, where.y, each);
          await sleep(40);
        }
        await sleep(1600);
        const turns = posts.filter((p) => p.startsWith('/turn')).length;
        const rec = await recordingsSoFar(page);
        check(gate(`${ms.length} taps of ${Math.min(...ms)}-${Math.max(...ms)} ms on ${step.near} emit no recording`) + owned,
          rec.started === 0 && rec.tooShort === 0 && turns === 0,
          `${rec.started} recording(s) started, ${rec.tooShort} "too short", ${turns} turn(s); posted ${[...new Set(posts)].join(',') || 'nothing'}`);
        await shot(page, `replay-${state.id}-after-burst`);
        break;
      }
      case 'post_command': {
        const result = await page.evaluate(async ([name, args]) => {
          const id = localStorage.getItem('crooks.session') || '';
          const form = new FormData();
          form.set('session_id', id);
          form.set('command', name);
          for (const k of Object.keys(args || {})) form.set(k, String(args[k]));
          const r = await fetch('/command', { method: 'POST', body: form, cache: 'no-store' });
          let body = {};
          try { body = await r.json(); } catch { body = {}; }
          return { status: r.status, ok: r.ok, code: body.code || '', detail: String(body.detail || '').slice(0, 160), ui: (body.ui || []).map((i) => i.type) };
        }, [step.command, step.args]);
        // The refusal itself is CORRECT and must stay: the Mac is not holding that record, and
        // fabricating it would be the worse bug. What §18 asks is that the control was never
        // offered, and that when one is refused the owner is told rather than shown an empty
        // half. So this is a FIXTURE check — it reproduces the live refusal exactly.
        // Judged on the CODE, not the HTTP status: this route answers a refused command with
        // 200 and a `code`, which is the right shape (the request was understood; the thing
        // asked for is not there) and exactly what the live timeline recorded.
        lastRefusal = { code: result.code, detail: result.detail };
        const refused = Boolean(result.code);
        check(fx(`${step.command} for a record the Mac is not holding is refused ${step.expect_code}`),
          refused === !step.expect_ok && (!step.expect_code || result.code === step.expect_code),
          JSON.stringify(result));
        break;
      }
      case 'refusal_carries_words': {
        // The refusal itself is right and must stay: the Mac is not holding that record, and
        // inventing it would be the worse bug. What it must never be is a code with nothing
        // for the owner in it — the live half drew `half_empty` and said nothing at all.
        const said = String(lastRefusal.detail || '');
        check(gate('the refusal carries a sentence the owner can act on, not just a code') + owned,
          said.length > 20 && /[a-z]/.test(said),
          `code=${lastRefusal.code || 'none'} detail="${said}"`);
        break;
      }
      case 'offers_withheld': {
        /* The OTHER direction of the §18 sweep, and the reason it needs its own step.
           `no_control_carries_unheld_ref` asks "does every offer on screen work?", and it
           refuses to pass when there are no offers at all — rightly, because a gate that
           goes green on an empty deck is how Phase 4's suite stayed green. But after
           `app/presentation.py:_withhold_dead_refs` a ranking of products the Mac has never
           read correctly offers NOTHING, so that check became unmeasurable on this state
           and said so.

           Unmeasurable is not the same as satisfied, so this is the positive claim for that
           deck: rows were drawn, none of them carries a destination, and every one of them
           still carries its figures. The last part matters — the ranking IS the answer to
           "what sold best", and the only false thing about it was the promise that you could
           tap through to the product. Withholding the ref must not cost the answer. */
        const seen = await page.evaluate(() => {
          const rows = Array.from(document.querySelectorAll('#cards .rank, #cards .row, #cards li[data-ref], #cards li'));
          const drawn = rows.filter((r) => (r.textContent || '').trim().length > 2);
          return {
            rows: drawn.length,
            withRef: drawn.filter((r) => (r.dataset && r.dataset.ref) || r.querySelector('[data-ref]')).length,
            withFigures: drawn.filter((r) => /[0-9]/.test(r.textContent || '')).length,
            sample: drawn.slice(0, 3).map((r) => (r.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40)),
          };
        });
        check(gate(`${step.expect_rows_at_least || 1}+ rows are drawn, so there is something to measure`) + owned,
          seen.rows >= (step.expect_rows_at_least || 1), JSON.stringify(seen));
        check(gate('and not one of them offers a record the Mac could not open') + owned,
          seen.withRef === 0, `${seen.withRef} of ${seen.rows} still carry a destination`);
        check(gate('and withholding the destination did not cost the answer') + owned,
          seen.rows > 0 && seen.withFigures === seen.rows,
          `${seen.withFigures} of ${seen.rows} rows still carry their figures — ${JSON.stringify(seen.sample)}`);
        await shot(page, `replay-${state.id}-withheld`);
        break;
      }
      case 'no_control_carries_unheld_ref': {
        // §18, asked the only way it can be asked from the page without a new endpoint, and a
        // better way than an endpoint would be: take every control on screen that OFFERS to
        // open a record, and try to open it. A control whose destination the Mac is not
        // holding is refused `not_held` — which means it should never have been drawn.
        //
        // This is the general form of D-6. The live session's one refusal was a product row
        // in the products landing; this checks every row of whatever is on the glass.
        const refs = await page.evaluate(() => Array.from(document.querySelectorAll('#cards [data-ref]'))
          .map((el) => ({ ref: el.dataset.ref || '', kind: el.dataset.kind || '', words: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 30) }))
          .filter((x) => x.ref));
        const refusals = [];
        for (const each of refs.slice(0, 12)) {
          const result = await page.evaluate(async ([ref, kind]) => {
            const id = localStorage.getItem('crooks.session') || '';
            const form = new FormData();
            form.set('session_id', id); form.set('command', 'open.entity');
            form.set('ref', ref); if (kind) form.set('kind', kind);
            const r = await fetch('/command', { method: 'POST', body: form, cache: 'no-store' });
            let body = {};
            try { body = await r.json(); } catch { body = {}; }
            return body.code || '';
          }, [each.ref, each.kind]);
          if (result) refusals.push(`"${each.words}" → ${result}`);
        }
        check(gate(`every control on screen that offers a record can open it (${refs.length} offered)`) + owned,
          refs.length > 0 && refusals.length === 0,
          refs.length === 0 ? 'nothing on screen offered a record, so §18 could not be measured'
            : `${refusals.length} refused: ${refusals.slice(0, 4).join(' | ')}`);
        await shot(page, `replay-${state.id}-offers`);
        break;
      }
      case 'ask': {
        const turn = await page.evaluate(async (text) => {
          const id = localStorage.getItem('crooks.session') || `replay-${Date.now()}`;
          localStorage.setItem('crooks.session', id);
          const r = await fetch('/turn', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store',
            body: JSON.stringify({ text, session_id: id }),
          });
          return r.json();
        }, step.text);
        await page.evaluate((payload) => window.__replayDraw(payload.ui || [], {}), turn);
        await sleep(300);
        const deck = await readDeck(page);
        check(fx(`"${step.text}" puts a surface on screen to navigate away from`),
          deck.cards.length > 0, `ui=${(turn.ui || []).map((i) => i.type).join(',')}`);
        break;
      }
      case 'press_home_repeatedly': {
        // D-7. Eight Home commands were posted and eight were accepted, and he pressed it four
        // times in three seconds anyway. `ok=true` is not arrival: arrival is the cards
        // changing. So the measurement is the VISIBLE destination after each press.
        const screens = [];
        const now = () => page.evaluate(() => ({
          mode: document.body.dataset.mode || '',
          cards: Array.from(document.querySelectorAll('#cards .card')).map((c) => `${c.dataset.type || ''}:${c.dataset.ref || ''}`).join('|'),
          head: ((document.querySelector('#branch-head') || {}).textContent || '').trim(),
        }));
        screens.push(await now());
        for (let i = 0; i < (step.times || 7); i++) {
          const pressed = await page.evaluate(() => {
            const home = document.querySelector('#home-btn');
            if (!home || home.hidden) return false;
            home.click();
            return true;
          });
          if (!pressed) { check(gate('Home is on the screen to press') + owned, false, 'no #home-btn'); break; }
          await sleep(Math.max(240, Math.round((step.within_ms || 4000) / (step.times || 7))));
          screens.push(await now());
        }
        const first = screens[0];
        const landed = screens[1];
        check(gate('the first press of Home visibly arrives somewhere else') + owned,
          Boolean(landed) && JSON.stringify(landed) !== JSON.stringify(first),
          `before ${JSON.stringify(first)} → after ${JSON.stringify(landed)}`);
        const later = screens.slice(2);
        const moved = later.filter((s, i) => JSON.stringify(s) !== JSON.stringify(screens[i + 1])).length;
        check(gate('and every press after it lands on the same screen, so pressing again is pointless') + owned,
          moved === 0, `${moved} of ${later.length} later presses changed the screen — ${JSON.stringify(later.slice(0, 3))}`);
        await shot(page, `replay-${state.id}-after-home`);
        break;
      }
      case 'collide': {
        const scan = await scanNow(page);
        check(gate(`zero collisions involving an interactive element on the idle screen`) + owned,
          scan.interactive === (step.interactive_must_be || 0),
          `${scan.interactive} of ${scan.total} — ${JSON.stringify(scan.counts)} — ${JSON.stringify(scan.worst)}`);
        break;
      }
      default:
        check(fx(`the step "${step.do}" is one this file knows`), false, JSON.stringify(step).slice(0, 200));
    }
  }
}

async function shot(page, name) {
  if (!OUT) return;
  const file = path.join(OUT, `${name}.png`);
  await page.waitForTimeout(300);
  await page.screenshot({ path: file, fullPage: false, animations: 'disabled' });
  shots.push(path.basename(file));
}

main().then((code) => process.exit(code)).catch((e) => {
  process.stdout.write(`${JSON.stringify({ ok: false, checks: checks.concat([{ name: 'replay run', ok: false, detail: String((e && e.stack) || e).slice(0, 600) }]), shots })}\n`);
  process.exit(1);
});

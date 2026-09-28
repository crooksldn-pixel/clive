/* CROOKS OS — what the tablet actually did, for a test session.
 *
 * While a test session is running on the Mac (the page learns it from /health and from every
 * /turn answer), the page keeps a small, structured account of itself: what it rendered —
 * screen, card types, tabs, the chips on the rail and whether they were enabled — what the
 * owner touched, where it navigated, what failed to load, when it lost the Mac. Semantic
 * state, never the DOM: no markup, no screenshots, no text the cards showed.
 *
 * Nothing here is ever waited for. Events go on a queue; the queue is posted every couple of
 * seconds, or at forty events, with fetch keepalive (sendBeacon on pagehide). A post that
 * fails is dropped. Off, `record` is a boolean test and a return.
 *
 * The one exception to "never the DOM" is the owner's own switch, CROOKS_SCREEN_SNAPSHOTS:
 * when /health says `screens`, the page also sends a copy of what it is showing — at each
 * answer drawn, each question asked, each failure, each tap on the phone's home — so the
 * host can redraw it as a picture (`make test-session-screens`). Scripts and handlers are
 * taken out, a field's typed value is kept, the orb is kept as an image. One every few
 * seconds at most, a few hundred a day at most, and only while a test session runs.
 */
(function (root) {
  'use strict';

  const FLUSH_MS = 2000;
  const FLUSH_AT = 40;
  const MAX_QUEUE = 300;
  const MAX_STRING = 400;
  const MAX_ITEMS = 40;
  const ENDPOINT = '/telemetry';

  let enabled = false;
  let testSession = null;
  let queue = [];
  let timer = null;
  let seq = 0;
  let context = { session_id: '', turn_id: '' };
  let transport = null;   // tests hand in a function; the page uses fetch / sendBeacon
  let sent = 0;
  let dropped = 0;
  // The screen copies (see the header). Off unless /health says `screens`.
  let screens = false;
  let screenTimer = null;
  let screenPending = null;
  let lastScreenAt = 0;
  let screenCount = 0;
  const SCREEN_GAP_MS = 2500;
  const SCREEN_MAX = 400;
  const SCREEN_SETTLE_MS = 1100;   // after the event, so a card has finished arriving
  // The events a copy of the screen is taken for, and the name it is kept under. A failure
  // outranks an answer, and an answer a tap, when two land inside one gap.
  const SCREEN_ON = {
    exception: ['error', 3], turn_failed: ['error', 3], image_failed: ['error', 3], http_error: ['error', 3],
    connectivity: ['offline', 3], recording_too_short: ['error', 2],
    render: ['answer', 2], turn_submitted: ['asked', 2], session_joined: ['opened', 1],
    alpha_tap: ['home_tap', 1], navigate: ['navigate', 1], ask_bar: ['bar', 1],
  };

  function now() { return Date.now(); }

  const MAX_DEPTH = 6;   // render → cards → card → actions → action → id

  function bounded(value, depth) {
    depth = depth || 0;
    if (depth > MAX_DEPTH) return undefined;
    if (value === null || value === undefined) return undefined;
    if (typeof value === 'boolean' || typeof value === 'number') return Number.isFinite(value) || typeof value === 'boolean' ? value : undefined;
    if (typeof value === 'string') return value.length > MAX_STRING ? value.slice(0, MAX_STRING) + '…' : value;
    if (Array.isArray(value)) return value.slice(0, MAX_ITEMS).map((v) => bounded(v, depth + 1));
    if (typeof value === 'object') {
      const out = {};
      let n = 0;
      for (const key of Object.keys(value)) {
        if (n++ >= MAX_ITEMS) break;
        const v = bounded(value[key], depth + 1);
        if (v !== undefined) out[key] = v;
      }
      return out;
    }
    return undefined;
  }

  // The session in force on the Mac. From /health (every poll) and from every /turn answer,
  // so a session started on the Mac is noticed within one poll and no reload is needed.
  function configure(observability) {
    const id = observability && observability.test_session ? String(observability.test_session) : (typeof observability === 'string' ? observability : '');
    const was = enabled;
    testSession = id || null;
    enabled = Boolean(id);
    if (observability && typeof observability === 'object' && 'screens' in observability) screens = Boolean(observability.screens);
    if (!enabled) { queue = []; if (timer) { clearTimeout(timer); timer = null; } }
    else if (!was) record('session_joined', { name: observability && observability.name ? String(observability.name) : undefined });
    return enabled;
  }

  function setContext(fields) {
    if (!fields) return;
    if (fields.session_id !== undefined) context.session_id = String(fields.session_id || '');
    if (fields.turn_id !== undefined) context.turn_id = String(fields.turn_id || '');
  }

  function record(kind, fields) {
    if (!enabled) return null;
    const event = Object.assign(
      context.session_id ? { session_id: context.session_id } : {},
      context.turn_id ? { turn_id: context.turn_id } : {},
      bounded(fields || {}) || {},
      { kind: String(kind), t: now(), seq: ++seq },   // last: a field never overwrites these
    );
    queue.push(event);
    if (screens && SCREEN_ON[event.kind]) wantScreen(event);
    if (queue.length > MAX_QUEUE) { dropped += queue.length - MAX_QUEUE; queue.splice(0, queue.length - MAX_QUEUE); }
    if (queue.length >= FLUSH_AT) flush(false);
    else if (!timer) timer = setTimeout(() => { timer = null; flush(false); }, FLUSH_MS);
    return event;
  }

  function flush(unloading) {
    if (timer) { clearTimeout(timer); timer = null; }
    if (!queue.length || !enabled) return false;
    const batch = queue;
    queue = [];
    const body = JSON.stringify({ session_id: context.session_id, test_session_id: testSession, events: batch });
    sent += batch.length;
    try {
      if (transport) { transport(body, Boolean(unloading)); return true; }
      if (unloading && root.navigator && typeof root.navigator.sendBeacon === 'function') {
        if (root.navigator.sendBeacon(ENDPOINT, new Blob([body], { type: 'application/json' }))) return true;
      }
      if (typeof root.fetch === 'function') {
        root.fetch(ENDPOINT, { method: 'POST', headers: { 'content-type': 'application/json' }, body, keepalive: true, cache: 'no-store' })
          .catch(() => { dropped += batch.length; });
        return true;
      }
    } catch { dropped += batch.length; }
    return false;
  }

  // ---- the screen, read as structure. The card renderer marks what it draws with data
  // attributes (type, ref, proposal, pending) and classes; this reads those, never the text.
  function pathOnly(src) {
    try { const u = new URL(String(src || ''), 'https://x/'); return u.pathname; } catch { return ''; }
  }

  function cardState(card, index) {
    const ds = card.dataset || {};
    const out = { i: index, type: ds.type || card.className.replace(/^card\s*/, '').split(' ')[0] || 'card' };
    if (ds.ref) out.ref = ds.ref;
    if (ds.proposal) out.proposal_id = ds.proposal;
    if (ds.pending) out.pending = ds.pending.split(' ').filter(Boolean);
    const q = (sel) => (card.querySelectorAll ? Array.from(card.querySelectorAll(sel)) : []);
    const tabs = q('[role="tab"]');
    if (tabs.length) {
      out.tabs = tabs.map((t) => t.textContent.trim().slice(0, 40));
      const active = tabs.find((t) => t.getAttribute('aria-selected') === 'true');
      if (active) out.tab_active = active.textContent.trim().slice(0, 40);
    }
    const sections = q('.sec');
    if (sections.length) out.sections = sections.map((s) => String(s.getAttribute('aria-label') || '').slice(0, 40)).filter(Boolean);
    // What this card says another record IS. The renderer marks every tappable link target
    // with data-kind (an order strip on a thread, a customer chip, a prior order), so the
    // KINDS it drew are readable without reading a word of it. The report needs this to tell
    // a relation that exists in the data from one that exists on the screen: a thread card
    // whose relations do not include 'order' did not show the order, whatever the tools
    // returned. Kinds only — never the reference, which is a record's id, and never the text.
    const relations = q('[data-kind]');
    if (relations.length) {
      const kinds = [];
      relations.forEach((r) => {
        const kind = String((r.dataset && r.dataset.kind) || '').slice(0, 24);
        if (kind && kinds.indexOf(kind) === -1) kinds.push(kind);
      });
      if (kinds.length) out.relations = kinds.sort();
    }
    const chips = q('.rail-chip');
    if (chips.length) {
      out.actions = chips.map((c) => {
        const a = { id: (c.dataset && c.dataset.action) || '', enabled: c.getAttribute('aria-disabled') !== 'true' };
        const why = c.querySelector ? c.querySelector('.rail-why') : null;
        if (!a.enabled && why) a.reason = why.textContent.trim().slice(0, 80);
        return a;
      });
    }
    const surface = card.querySelector ? card.querySelector('.action-surface') : null;
    if (surface) {
      const kind = (surface.className.match(/kind-([a-z_]+)/) || [])[1] || '';
      out.surface = { kind, state: (surface.dataset && surface.dataset.state) || '' };
      if (out.surface.state === 'unavailable') out.surface.reason = surface.textContent.trim().slice(0, 80);
    }
    const images = q('img');
    if (images.length) out.images = { count: images.length, missing: q('.is-missing').length, loaded: q('.is-loaded').length };
    if (typeof card.scrollWidth === 'number' && typeof card.clientWidth === 'number' && card.clientWidth && card.scrollWidth > card.clientWidth + 1) out.clipped_x = card.scrollWidth - card.clientWidth;
    if (typeof card.getBoundingClientRect === 'function') { try { out.height = Math.round(card.getBoundingClientRect().height); } catch { /* shim */ } }
    return out;
  }

  /* What is on top of what, at the moment of this render.
   *
   * The live session of 11 September recorded `clipped: 0` on every one of its renders while
   * the owner was looking at overlapping text and controls, and said so out loud twice. That
   * number was `scrollWidth > clientWidth` on a card — it can only see a box too small for
   * its own contents, and never two boxes that are each the right size and in the same place.
   * It was not wrong; it was answering a different question.
   *
   * So the snapshot now carries the answer to the question the owner was asking: real
   * geometry, from web/collide.js, which reads every rectangle on screen with
   * getBoundingClientRect() and counts the pairs that collide, by rule. `collisions.total` is
   * the number a report can put beside a turn and mean it — and when it disagrees with what
   * the owner saw, THAT is the defect, not his eyes.
   *
   * Counts and selectors only: a rule name, a tag, an id, the first class, four integers.
   * Nothing a card said, here as everywhere else in this file.
   */
  function collisions() {
    const api = root.CrooksCollide;
    if (!api || typeof api.scan !== 'function') return null;
    let scan = null;
    try { scan = api.scan({}); } catch { return null; }
    if (!scan) return null;
    const counts = {};
    for (const rule of Object.keys(scan.counts || {})) if (scan.counts[rule]) counts[rule] = scan.counts[rule];
    return {
      total: scan.total || 0,
      by_rule: counts,
      // One example per rule that fired, so a report can name the thing rather than the count.
      worst: (scan.hits || []).slice(0, 6).map((h) => ({ rule: h.rule, a: h.a, b: h.b, w: h.w, h: h.h, note: h.note })),
      // The same rectangles, asked the other question section 29 cares about.
      small_targets: (scan.touch || []).slice(0, 6),
      measured: scan.records || 0,
    };
  }

  function snapshot(cardsEl, extra) {
    const doc = root.document;
    const cards = cardsEl && cardsEl.children ? Array.from(cardsEl.children) : [];
    const out = Object.assign({
      screen: doc && doc.body && doc.body.dataset ? (doc.body.dataset.mode || '') : '',
      cards: cards.map(cardState),
      viewport: { w: root.innerWidth || 0, h: root.innerHeight || 0, dpr: root.devicePixelRatio || 1 },
      document: {
        height: doc && doc.documentElement ? doc.documentElement.scrollHeight || 0 : 0,
        cards_height: cardsEl ? cardsEl.scrollHeight || 0 : 0,
        cards_visible: cardsEl ? cardsEl.clientHeight || 0 : 0,
      },
    }, extra || {});
    const hit = collisions();
    // `clipped` stays, because it is a real (narrow) measurement and the report reads it.
    // `collisions` is the one that answers the owner's question.
    out.overflow = {
      long_scroll: out.document.cards_height > out.document.cards_visible + 8,
      clipped: out.cards.filter((c) => c.clipped_x).length,
      collisions: hit ? hit.total : null,
    };
    if (hit) out.collisions = hit;
    return out;
  }

  // ---- the screen, as it looked (CROOKS_SCREEN_SNAPSHOTS only).
  function wantScreen(event) {
    const [reason, rank] = SCREEN_ON[event.kind];
    if (screenPending && screenPending.rank > rank) return;
    const trigger = { kind: event.kind };
    for (const key of ['status', 'message', 'file', 'line', 'src', 'target', 'control', 'outcome', 'reason', 'code', 'path']) {
      if (event[key] !== undefined) trigger[key] = event[key];
    }
    screenPending = { reason, rank, turn_id: event.turn_id || context.turn_id || '', trigger };
    if (screenTimer) clearTimeout(screenTimer);
    const wait = Math.max(SCREEN_SETTLE_MS, lastScreenAt + SCREEN_GAP_MS - now());
    screenTimer = setTimeout(takeScreen, wait);
  }

  function typedMask(value) {
    return '•'.repeat(Math.min(24, String(value).length));
  }

  function copyScreen() {
    const doc = root.document;
    const app = doc && doc.getElementById ? doc.getElementById('app') : null;
    if (!app || typeof root.XMLSerializer !== 'function') return null;
    const live = [app];
    const dialogs = Array.from(doc.querySelectorAll('dialog[open]'));
    live.push(...dialogs);
    const parts = live.map((node) => {
      const clone = node.cloneNode(true);
      const from = node.querySelectorAll('*');
      const to = clone.querySelectorAll('*');
      for (let i = 0; i < from.length && i < to.length; i += 1) {
        const a = from[i];
        const b = to[i];
        const tag = a.tagName;
        // What was typed is never copied: a field shows only that it held something, and how
        // much, so the picture still shows a half-written question without saying what it was.
        if (tag === 'INPUT') {
          b.removeAttribute('value');
          if (a.type !== 'password' && a.type !== 'hidden' && a.value) b.setAttribute('value', typedMask(a.value));
        } else if (tag === 'TEXTAREA') b.textContent = a.value ? typedMask(a.value) : '';
        // The live words (web/live-voice.js) are copied as a typed field is: that there were
        // some, and how many, never what they said.
        else if (a.hasAttribute && a.hasAttribute('data-spoken')) b.textContent = a.textContent ? typedMask(a.textContent) : '';
        else if (tag === 'CANVAS') {
          try {
            const img = doc.createElement('img');
            img.setAttribute('src', a.toDataURL('image/png'));
            img.setAttribute('class', a.getAttribute('class') || '');
            img.setAttribute('style', 'display:block;width:100%;height:100%');
            b.replaceWith(img);
          } catch { /* a tainted canvas stays blank */ }
        }
        if (a.scrollTop > 0) b.setAttribute('data-snap-top', String(Math.round(a.scrollTop)));
        if (a.scrollLeft > 0) b.setAttribute('data-snap-left', String(Math.round(a.scrollLeft)));
      }
      clone.querySelectorAll('script,iframe,object,embed').forEach((n) => n.remove());
      [clone, ...clone.querySelectorAll('*')].forEach((n) => {
        for (const attr of Array.from(n.attributes || [])) if (/^on/i.test(attr.name)) n.removeAttribute(attr.name);
      });
      if (node !== app) clone.setAttribute('data-snap-dialog', '');
      // Serialised, never assigned: nothing on this page is ever built from a string.
      return new root.XMLSerializer().serializeToString(clone);
    });
    const body = doc.body;
    return {
      html: parts.join('\n'),
      body: { class: body ? body.className : '', mode: body && body.dataset ? body.dataset.mode || '' : '' },
      lite: Boolean(doc.documentElement && doc.documentElement.dataset && doc.documentElement.dataset.lite),
      viewport: { w: root.innerWidth || 0, h: root.innerHeight || 0, dpr: root.devicePixelRatio || 1 },
    };
  }

  function takeScreen() {
    screenTimer = null;
    const pending = screenPending;
    screenPending = null;
    if (!pending || !enabled || !screens || screenCount >= SCREEN_MAX) return false;
    let copy = null;
    try { copy = copyScreen(); } catch { copy = null; }
    if (!copy) return false;
    lastScreenAt = now();
    screenCount += 1;
    const body = JSON.stringify(Object.assign(copy, {
      session_id: context.session_id, test_session_id: testSession, turn_id: pending.turn_id,
      reason: pending.reason, trigger: bounded(pending.trigger), t: lastScreenAt,
    }));
    try {
      if (transport) { transport(body, false, '/telemetry/screen'); return true; }
      if (typeof root.fetch === 'function') {
        root.fetch('/telemetry/screen', { method: 'POST', headers: { 'content-type': 'application/json' }, body, cache: 'no-store' }).catch(() => {});
        return true;
      }
    } catch { /* a copy that cannot be sent is not taken */ }
    return false;
  }

  function status() { return { enabled, test_session: testSession, queued: queue.length, sent, dropped, seq, screens, screen_count: screenCount }; }

  function reset() {
    enabled = false; testSession = null; queue = []; if (timer) clearTimeout(timer); timer = null; seq = 0; context = { session_id: '', turn_id: '' }; sent = 0; dropped = 0;
    screens = false; if (screenTimer) clearTimeout(screenTimer); screenTimer = null; screenPending = null; lastScreenAt = 0; screenCount = 0;
  }

  const api = { configure, setContext, record, flush, snapshot, collisions, cardState, pathOnly, status, reset, screen: takeScreen, copyScreen, _setTransport(fn) { transport = fn; } };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.CrooksTelemetry = api;
})(typeof window !== 'undefined' ? window : globalThis);

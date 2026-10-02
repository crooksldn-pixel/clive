/* Objectives by touch: what every touch on an objective shares (the design's six gestures).
 *
 * George's objective, on his own screen, answers his finger the way it answers a sentence: tap a
 * stage and CLIVE tells him about it, double-tap and it becomes now, drag "now" along the stages,
 * drag the date it must land by along the days, double-tap a task to tick it, press a task and drag
 * it to someone else. web/objective-cards.js draws each of those; this file is what they share, so
 * they feel the same everywhere (the design's last rule):
 *
 *   taps    a tap and a double-tap told apart (about 280 ms). A tap's own action waits for the
 *           window only where a double-tap means something else on that element; a tap on a
 *           task's round tick ticks at once, and the second tap of a double-tap there is the same
 *           tick, never tick-and-untick.
 *   press   a finger or pointer pressed on one element: "now", the date ring, a task. A drag that
 *           starts at once (the ring, "now", which take no scroll: touch-action none), or one that
 *           arms after a still press (a task, which sits in a list that scrolls): until it arms, a
 *           move is the list's scroll and the press is forgotten; once armed, a move is the drag's.
 *           The scroll is stopped for that gesture alone, as web/lift.js stops it (and, as there,
 *           on iOS the listener is in place before any touch begins, since WebKit decides at the
 *           start of a touch whether a page may stop it), from the window rather than the
 *           document, which is lift.js's. The click a press-and-drag ends with is not also a tap.
 *   haptic  the patterns web/app.js uses: done [10,60,10] for a tick or a commit, error [40,50,40],
 *           a detent tick for each step a drag passes, a short snap for an undo, 12 to lift. On an
 *           iPhone, where the browser cannot vibrate, the sight carries it: every one of these has
 *           a change on the glass with it.
 *   bar     THE BAR: one line at the foot of the sheet, or of the conversation's card, saying what
 *           a touch did, with Undo for six seconds, and then it goes. A line that changes nothing
 *           (a tap telling him about a stage) shows, and leaves an Undo still running alone. Undo
 *           asks the Mac to put it back, redraws from the answer, snaps, and says what it put
 *           back; refused or unreachable, it says so, and nothing pretends.
 *   post    one of the owner's own routes (app/routes/objectives.py), its refusal in its words.
 *
 * Every word goes onto the page as text, never markup, and no attribute is built from what the
 * Mac sent. Nothing here reads a record; it times, feels and says. No dependency on the rest of
 * the page, so it runs under Node against tests/web/dom-shim.js (tests/web/objective-touch.test.js).
 */
(function (root, factory) {
  const api = factory(root);
  root.CliveObjectiveTouch = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  const TAP_MS = 280;          // two taps within this on one element are a double-tap
  const ARM_MS = 250;          // a task held this still, this long, can be dragged
  const UNDO_MS = 6000;        // what a touch did can be taken back for this long
  const SAY_MS = 4000;         // a line that changed nothing stays this long
  const SLOP = 8;              // a press may wander this far and still be still
  const SWALLOW_MS = 450;      // the click a drag's release makes is not a tap
  const HAPTIC = { detent: 6, snap: [8], lift: 12, done: [10, 60, 10], error: [40, 50, 40] };
  const NS = 'http://www.w3.org/2000/svg';

  const doc = () => (typeof document !== 'undefined' ? document : root.document);
  const words = (v) => (v === null || v === undefined ? '' : String(v));

  // The clock every timer here reads: replaced in the tests by one they move by hand.
  const clock = {
    now: () => Date.now(),
    later: (fn, ms) => setTimeout(fn, ms),
    cancel: (id) => clearTimeout(id),
  };

  function h(tag, cls, text) {
    const node = doc().createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = words(text);
    return node;
  }

  // ---------------------------------------------------------------- feel

  function vibrate(pattern) {
    try {
      const nav = root.navigator;
      if (nav && typeof nav.vibrate === 'function') nav.vibrate(pattern);
    } catch (e) { /* no motor */ }
  }
  function haptic(kind) {
    if (HAPTIC[kind] !== undefined) api.vibrate(HAPTIC[kind]);
  }
  function reduced() {
    try { return Boolean(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches); } catch (e) { return false; }
  }

  // ---------------------------------------------------------------- a tap, or two

  // One recogniser per drawing. `tap(key, part, how)`: `key` is the element (a stage, a task),
  // `part` where on it the finger landed. A second tap on the same key inside the window is a
  // double-tap: `how.double(firstPart)`, and the first tap's waiting action never runs. Otherwise
  // `how.single(part)` runs, after the window when `how.waits`, at once when not.
  function taps() {
    let last = null;
    return function tap(key, part, how) {
      const t = api.clock.now();
      if (last && last.key === key && t - last.at < TAP_MS) {
        const first = last;
        last = null;
        api.clock.cancel(first.timer);
        how.double(first.part, part);
        return 'double';
      }
      const entry = { key, part, at: t, timer: 0 };
      last = entry;
      if (how.waits) entry.timer = api.clock.later(() => { if (last === entry) last = null; how.single(part); }, TAP_MS);
      else how.single(part);
      return 'single';
    };
  }

  // ---------------------------------------------------------------- a press, and a drag

  // Whether the scroll guard must be in place before any touch begins: iOS (and an iPad, which says
  // it is a Mac with a touch screen), as web/lift.js `guardsFromStart` says.
  function fromStart() {
    const nav = root.navigator || {};
    return /iP(hone|ad|od)/.test(words(nav.userAgent)) || (words(nav.platform) === 'MacIntel' && Number(nav.maxTouchPoints) > 1);
  }
  // The elements whose press owns the finger now. One that has left the page (its drawing redrawn
  // under the finger) owns nothing: it is forgotten at the next move, so a scroll is never kept.
  // The listener hangs on the window, where it stops a scroll as well as on the document, and
  // leaves the document's own (web/lift.js) to itself.
  const owning = new Set();
  const FROM_START = fromStart();
  const host = () => (root && typeof root.addEventListener === 'function' ? root : null);
  let attached = false;
  function stopScroll(event) {
    for (const el of owning) if (el.isConnected === false) owning.delete(el);
    if (owning.size && event.cancelable) event.preventDefault();
    if (!owning.size) attach(false);
  }
  function attach(on) {
    const w = host();
    if (FROM_START || attached === on || !w) return;
    attached = on;
    if (on) w.addEventListener('touchmove', stopScroll, { passive: false });
    else w.removeEventListener('touchmove', stopScroll, { passive: false });
  }
  function guard(el, on) {
    if (on) owning.add(el); else owning.delete(el);
    attach(owning.size > 0);
  }
  if (FROM_START && host()) host().addEventListener('touchmove', stopScroll, { passive: false });

  /* `spec`: { arm (ms; 0 = it drags as soon as it moves), armed(p), start(p), move(p), end(p),
   * still(p), cancel(p), ownClick }. `p` carries where it went down (x0, y0) and where it is (x, y),
   * in the page's own pixels. Returns { took(): whether the click now arriving is the end of a
   * press, and so not a tap; pressing(): whether a press is under way }. An element with a click
   * handler of its own (`ownClick`) asks `took`; any other has that click stopped here, so it does
   * not reach what holds the element either (a stage's tap, under "now"). */
  function press(el, spec) {
    let P = null;
    let swallowUntil = 0;
    const end = (how, event) => {
      const p = P;
      P = null;
      if (!p) return;
      api.clock.cancel(p.timer);
      if (p.armed) {
        guard(el, false);
        try { if (el.releasePointerCapture) el.releasePointerCapture(p.id); } catch (e) { /* gone */ }
      }
      // A drag, or a press held until it armed, ends in a click that is not a tap.
      if (p.dragging || (p.armed && spec.arm > 0)) swallowUntil = api.clock.now() + SWALLOW_MS;
      if (event) { p.x = event.clientX; p.y = event.clientY; }
      if (how === 'cancel') { if (p.armed && spec.cancel) spec.cancel(p); return; }
      if (p.dragging) { if (spec.end) spec.end(p); return; }
      if (p.armed && spec.arm && spec.still) spec.still(p);
    };
    const arm = (p, event) => {
      p.armed = true;
      guard(el, true);
      try { if (el.setPointerCapture) el.setPointerCapture(p.id); } catch (e) { /* the pointer is gone */ }
      if (spec.armed) spec.armed(p, event);
    };
    el.addEventListener('pointerdown', (event) => {
      if (P || event.isPrimary === false || (event.button !== undefined && event.button !== 0)) return;
      const p = { id: event.pointerId, x0: event.clientX, y0: event.clientY, x: event.clientX, y: event.clientY,
        armed: false, dragging: false, timer: 0 };
      P = p;
      if (spec.arm > 0) p.timer = api.clock.later(() => { if (P === p) arm(p); }, spec.arm);
      else arm(p, event);
    });
    el.addEventListener('pointermove', (event) => {
      const p = P;
      if (!p || event.pointerId !== p.id) return;
      p.x = event.clientX; p.y = event.clientY;
      const far = Math.hypot(p.x - p.x0, p.y - p.y0) > SLOP;
      if (!p.armed) { if (far) { api.clock.cancel(p.timer); P = null; } return; }   // a scroll, not a press
      if (!p.dragging) {
        if (!far) return;
        p.dragging = true;
        if (spec.start) spec.start(p);
      }
      if (spec.move) spec.move(p);
      if (event.cancelable && typeof event.preventDefault === 'function') event.preventDefault();
    });
    el.addEventListener('pointerup', (event) => { if (P && event.pointerId === P.id) end('up', event); });
    el.addEventListener('pointercancel', (event) => { if (P && event.pointerId === P.id) end('cancel', event); });
    el.addEventListener('lostpointercapture', (event) => { if (P && P.armed && event.pointerId === P.id) end('cancel'); });
    // A long press is the drag's, not the system's menu or a selection.
    el.addEventListener('contextmenu', (event) => { if (P && typeof event.preventDefault === 'function') event.preventDefault(); });
    const took = () => {
      if (api.clock.now() >= swallowUntil) return false;
      swallowUntil = 0;
      return true;
    };
    if (!spec.ownClick) {
      el.addEventListener('click', (event) => {
        if (took() && typeof event.stopPropagation === 'function') event.stopPropagation();
      }, true);
    }
    return { took, pressing: () => Boolean(P) };
  }

  // ---------------------------------------------------------------- the bar

  function tickMark() {
    const svg = doc().createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('class', 'ot-bar-tick');
    const path = doc().createElementNS(NS, 'path');
    path.setAttribute('d', 'm5 12.5 4.5 4.5L19 7.5');
    svg.appendChild(path);
    return svg;
  }

  /* `did(words, run)`: a touch changed something; Undo for six seconds calls `run()`, which asks
   * the Mac, redraws, and resolves with what was put back, in words (or throws, in words).
   * `say(words, kind)`: a line that changes nothing ('info'), or what went wrong ('error'). */
  function bar() {
    const el = h('div', 'ot-bar');
    el.setAttribute('role', 'status');
    el.hidden = true;
    const mark = h('span', 'ot-bar-mark');
    mark.appendChild(tickMark());
    const line = h('span', 'ot-bar-text');
    const undo = h('button', 'ot-undo', 'Undo');
    undo.type = 'button';
    undo.hidden = true;
    el.appendChild(mark);
    el.appendChild(line);
    el.appendChild(undo);
    const S = { said: null, offer: null, timer: 0, busy: false };

    function draw() {
      const shown = S.said || (S.offer ? { text: S.offer.text, kind: 'did' } : null);
      el.hidden = !shown;
      line.textContent = shown ? shown.text : '';
      el.dataset.kind = shown ? shown.kind : '';
      undo.hidden = !S.offer;
      undo.disabled = S.busy;
    }
    // What is still within its time stays; the bar goes when nothing is.
    function wake() {
      const t = api.clock.now();
      api.clock.cancel(S.timer);
      S.timer = 0;
      if (S.offer && t >= S.offer.until && !S.busy) S.offer = null;
      if (S.said && t >= S.said.until) S.said = null;
      draw();
      const next = Math.min(S.offer && !S.busy ? S.offer.until : Infinity, S.said ? S.said.until : Infinity);
      if (next !== Infinity) S.timer = api.clock.later(wake, Math.max(0, next - t));
    }
    function say(text, kind) {
      S.said = { text: words(text), kind: kind === 'error' ? 'error' : 'info', until: api.clock.now() + SAY_MS };
      wake();
    }
    function did(text, run) {
      const until = api.clock.now() + UNDO_MS;
      S.busy = false;
      S.offer = { text: words(text), run, until };
      S.said = { text: words(text), kind: 'did', until };
      wake();
    }
    async function takeBack() {
      const offer = S.offer;
      if (!offer || S.busy) return;
      S.busy = true;
      draw();
      let put = '';
      let why = null;
      try { put = await offer.run(); } catch (error) { why = error || new Error(''); }
      S.busy = false;
      S.offer = null;
      if (why) {
        haptic('error');
        say(why.unreached ? 'CLIVE could not be reached, so nothing was undone.'
          : words(why.message) || 'Nothing was undone.', 'error');
        return;
      }
      haptic('snap');
      say(words(put) || 'Put back as it was.');
    }
    undo.addEventListener('click', takeBack);
    draw();
    return {
      el, say, did, undo: takeBack,
      state: () => ({ text: line.textContent, kind: el.dataset.kind, undo: !undo.hidden, hidden: el.hidden }),
    };
  }

  // ---------------------------------------------------------------- the owner's routes

  async function post(url, body) {
    let response;
    try {
      response = await fetch(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), cache: 'no-store',
      });
    } catch (error) {
      const lost = new Error('CLIVE could not be reached');   // the browser's own words name no cause
      lost.unreached = true;
      throw lost;
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' && data.detail ? data.detail : `CLIVE answered ${response.status}`);
    return data;
  }

  // Whether `node` is `cls` or inside one, up to `stop`: where on a row a tap landed.
  function within(node, cls, stop) {
    for (let n = node; n; n = n.parentNode) {
      if (n.classList && n.classList.contains(cls)) return true;
      if (n === stop) return false;
    }
    return false;
  }

  const api = {
    TAP_MS, ARM_MS, UNDO_MS, SAY_MS, SLOP, HAPTIC, clock,
    vibrate, haptic, reduced, taps, press, bar, post, within, fromStart,
  };
  return api;
});

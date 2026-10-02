/* Three distances, by pinch (objectives by touch, part B).
 *
 * The design George approved puts the home in the middle of three distances: 0 the next six
 * weeks (web/horizon.js), 1 the home, 2 one objective (its sheet, web/alpha.js). Pinch is "how
 * much you see": halving or doubling the distance between two fingers is one level. So:
 *
 *   on the home      pinch in (fingers closing to about half) and it becomes the next six weeks;
 *                    spread over a row and that objective opens, forming out of its own row, as a
 *                    tap on the row opens it;
 *   on the horizon   spread and it is the home again; spread further over a row, or tap one, and
 *                    that objective opens; a double-tap on empty space is home;
 *   on a sheet       pinch in and it closes to the home (further, to the next six weeks); a
 *                    double-tap on empty space is home.
 *
 * Each level the fingers cross is a tick under them, and the level they land on is a short
 * pattern ([6, 40, 8], the design's "a tick at each level"); where a browser cannot vibrate the
 * sight carries it. Ctrl+wheel, which is how a laptop's trackpad pinches, does the same. And no
 * move depends on a gesture: the home has a "Next six weeks" button, the horizon a "Home" one,
 * and a sheet its own Done. The levels zoom the way the design draws them (each a factor of 1.8,
 * fading as it goes), follow the fingers, and settle in about a third of a second; a new pinch
 * catches a settle where it is. With motion turned down nothing travels: the view simply changes.
 *
 * Whose fingers these are. Two fingers are this file's only when BOTH came down on the home, the
 * horizon or an objective's sheet (the same one), neither on the orb or the voice target, an
 * action surface, a field, the ask bar, the Displays tray, or a handle an objective's own touch
 * layer drags ("now", the date ring); and never while something is lifted (web/lift.js) or held
 * by that layer. web/touch.js's machine is never asked to give anything up: it pairs only voice
 * pointers, and none of these is one, so the orb's division and merge stay exactly as they were.
 * Nothing here calls preventDefault on a pointer: one finger scrolls the home as it always did
 * (touch-action pan-y on the three views, horizon.css), a still hold still lifts (a second finger
 * already makes lift.js let go), and a tap is still a tap. While two fingers are this file's, a
 * scroll-stopping touchmove listener is in place for that gesture alone, as lift.js does it, and
 * the click a pinch can end with is not also a tap on the row under it.
 *
 * No dependency beyond window.CliveHome (web/alpha.js) and window.CliveHorizon. The rules are plain
 * functions, run under Node (tests/web/horizon.test.js); the page half runs only in a browser.
 */
(function (root, factory) {
  const api = factory(root);
  root.CliveDistances = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  // ---- the rules, as plain values and functions (tests/web/horizon.test.js) ------------------
  const HORIZON = 0;
  const HOME = 1;
  const OBJECTIVE = 2;
  const COMMIT = 0.25;          // a quarter of a level (a pinch to 0.84 of the gap, a spread to 1.19) settles on the next
  const RUBBER = 0.25;          // past the last level the view gives a quarter as much, and never more than a quarter level
  const ZOOM = 1.8;             // one level is this much larger or smaller, as the design draws it
  const FADE = 1.45;            // and this much fainter per level away
  const TAP_MS = 350;           // a press shorter than this, that stayed within TAP_PX, is a tap
  const TAP_PX = 10;
  const DOUBLE_MS = 300;        // two taps within this, within DOUBLE_PX, on empty space: home
  const DOUBLE_PX = 30;
  const WHEEL_RATE = 0.012;     // ctrl+wheel: how much one unit of deltaY scales
  const WHEEL_IDLE_MS = 160;    // a trackpad pinch has ended when no wheel came for this long
  const SWALLOW_MS = 450;       // the click a pinch ends with is not a tap
  const SETTLE_MS = 300;        // a level's settle; a fraction of a level takes less
  const STALE_MS = 60000;       // a pointer still "down" this long was never lifted at all
  const OPEN_WAIT_MS = 2500;    // a spread into an objective waits this long for its sheet
  const HAPTIC = { tick: 6, snap: 8, level: [6, 40, 8] };

  const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);

  // Where the fingers have taken the view: halving their distance is one level down, doubling up.
  function levelOf(from, scale) {
    const s = Number(scale);
    return from + Math.log2(Math.max(0.05, Number.isFinite(s) && s > 0 ? s : 1));
  }
  // Beyond the nearest or the farthest level the view stretches a little and no further.
  function rubber(L, min, max) {
    if (L > max) return max + Math.min(RUBBER, (L - max) * RUBBER);
    if (L < min) return min - Math.min(RUBBER, (min - L) * RUBBER);
    return L;
  }
  // Where a released pinch settles: a quarter of a level is enough to go on, a level and a quarter
  // two; never past what this pinch could reach.
  function settle(from, L, min, max) {
    const base = Math.round(from);
    const d = L - from;
    const k = Math.abs(d) < COMMIT ? 0 : Math.floor(Math.abs(d) + (1 - COMMIT));
    return clamp(base + Math.sign(d) * k, min, max);
  }
  // How far a pinch from here may go. Into an objective only over a row of one.
  function reach(zone, overRow) {
    if (zone === 'sheet') return { min: HORIZON, max: OBJECTIVE };
    if (zone === 'home' || zone === 'horizon') return { min: HORIZON, max: overRow ? OBJECTIVE : HOME };
    return { min: HOME, max: HOME };
  }
  // Has the level under the fingers changed between two readings? A tick if so.
  function crossed(a, b, min, max) {
    return Math.round(clamp(a, min, max)) !== Math.round(clamp(b, min, max));
  }
  // How a view `i` levels from the fingers is drawn: its scale and how much of it shows.
  function layer(L, i) {
    const d = L - i;
    return { scale: Math.pow(ZOOM, d), opacity: clamp(1 - Math.abs(d) * FADE, 0, 1) };
  }

  /* What one finger came down on, as far as a pinch is concerned:
   *   { zone: 'home' | 'horizon' | 'sheet' | null, voice, approval, field, own }
   * `own` is anything whose touch belongs to someone else: the ask bar (a hold is the microphone),
   * the Displays tray and its lifted chip, and the handles an objective's own touch layer drags. */
  const VOICE = '#talk, #orb-frame';
  const APPROVAL = '.action-surface, .action-handle';
  const FIELD = 'input, textarea, select, [contenteditable="true"], [contenteditable=""]';
  const OWNED = '.ask-bar, .alpha-composer, .lift-tray, .lift-layer, .lift-chip, .ot-grip, .ot-ring';
  // Not empty space: what a tap means something on (a row, a control, a stage, a task).
  const SOMETHING = 'button, a[href], input, select, textarea, label, summary, details, form, [role="button"], '
    + '[role="checkbox"], [role="tab"], [tabindex], [data-objective], [data-alpha], [data-hz], .oc-step, .oc-task, '
    + '.oc-steps, .ot-when, .ot-bar, .alpha-item, .alpha-ask';
  function hitOf(node) {
    const close = (sel) => (node && typeof node.closest === 'function' ? node.closest(sel) : null);
    const zone = close('#alpha-sheet') ? 'sheet' : close('#alpha-horizon') ? 'horizon' : close('#alpha-home') ? 'home' : null;
    return {
      zone,
      voice: Boolean(close(VOICE)),
      approval: Boolean(close(APPROVAL)),
      field: Boolean(close(FIELD)),
      own: Boolean(close(OWNED)),
    };
  }
  // A finger this file may use for a pinch.
  function claim(hit) {
    return Boolean(hit && hit.zone && !hit.voice && !hit.approval && !hit.field && !hit.own);
  }
  // Two fingers make this file's pinch only on the same view, and never while something is held.
  function pairs(a, b, busy) {
    return !busy && claim(a) && claim(b) && a.zone === b.zone;
  }
  // Empty space on the horizon or a sheet: a double-tap there is home.
  function emptyAt(node) {
    const hit = hitOf(node);
    if (!(hit.zone === 'horizon' || hit.zone === 'sheet') || hit.voice || hit.own || hit.field) return false;
    return !(node && typeof node.closest === 'function' && node.closest(SOMETHING));
  }

  const rules = {
    HORIZON, HOME, OBJECTIVE, COMMIT, ZOOM, FADE, HAPTIC, DOUBLE_MS, DOUBLE_PX, TAP_MS, TAP_PX,
    levelOf, rubber, settle, reach, crossed, layer, hitOf, claim, pairs, emptyAt,
  };

  // ---- the page -------------------------------------------------------------------------------
  const doc = root.document;
  const api = Object.assign({}, rules, { homeControl: () => null, drawn: () => {} });
  if (!doc || typeof doc.addEventListener !== 'function' || !doc.documentElement
      || typeof doc.documentElement.closest !== 'function' || typeof root.requestAnimationFrame !== 'function') return api;

  const S = {
    base: HOME,          // the distance the views rest at: the horizon or the home
    L: HOME,             // where the views are drawn now (a fraction while they move)
    gesture: null,       // the pinch or trackpad pinch under way
    pair: null,          // its two pointers and their first distance
    stop: null,          // stops the settle under way
    pts: new Map(),      // every pointer down: where, when, on what
    lastTap: null,
    swallowUntil: 0,
    from: null,          // the row the next sheet forms out of: {id, rect, at}
    pending: null,       // a spread into an objective, waiting for its sheet
    wheel: null,
    guarded: false,
    labelTimer: 0,
    wired: false,
    origins: { home: '50% 50%', horizon: '50% 50%', sheet: '50% 50%' },
  };
  const now = () => (root.performance && typeof root.performance.now === 'function' ? root.performance.now() : Date.now());
  const reduced = () => {
    try { return root.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; }
  };
  function feel(kind) {
    try { if (root.navigator && typeof root.navigator.vibrate === 'function') root.navigator.vibrate(HAPTIC[kind]); } catch (e) { /* no motor */ }
  }
  const H = () => root.CliveHome || null;
  const homeEl = () => doc.getElementById('alpha-home');
  const sheetEl = () => doc.getElementById('alpha-sheet');
  let horizon = null;
  let pill = null;
  let status = null;

  // An objective's sheet, open: the third distance. Its head carries the objective's id.
  function objectiveOpen() {
    const sheet = sheetEl();
    const head = sheet && sheet.open ? sheet.querySelector('.alpha-sheet-head[data-objective]') : null;
    return head ? head.getAttribute('data-objective') : null;
  }
  // Something is held: a lifted record on its way to a screen, or a handle an objective's own
  // touch layer has in hand. A pinch then is not this file's.
  function busy() {
    const html = doc.documentElement;
    return html.classList.contains('lift-dragging') || html.classList.contains('lift-open')
      || Boolean(doc.querySelector('.ot-grip.is-held, .ot-ring.is-moving, .oc-task.is-lifted'));
  }
  // The home band is on the screen (in a conversation it gives way to the cards).
  const homeShown = () => doc.body && doc.body.getAttribute('data-mode') !== 'context';

  // ---- the views ----
  function setup() {
    if (S.wired) return true;
    const home = homeEl();
    if (!home || !H() || !root.CliveHorizon) return false;
    S.wired = true;
    horizon = doc.createElement('section');
    horizon.id = 'alpha-horizon';
    horizon.className = 'alpha-horizon';
    horizon.setAttribute('aria-label', 'Next six weeks');
    horizon.hidden = true;
    home.parentNode.insertBefore(horizon, home.nextSibling);
    pill = doc.createElement('div');
    pill.className = 'hz-pill';
    pill.setAttribute('aria-hidden', 'true');
    status = doc.createElement('p');
    status.className = 'hz-status';
    status.setAttribute('role', 'status');
    doc.body.appendChild(pill);
    doc.body.appendChild(status);
    // A trackpad pinch, over the home's band: the band, not the views, since a view that is moving
    // takes no pointer and the rest of the pinch lands on what is behind it.
    (doc.getElementById('app') || home.parentNode).addEventListener('wheel', onWheel, { passive: false });
    const sheet = sheetEl();
    if (sheet) {
      sheet.addEventListener('wheel', onWheel, { passive: false });
      sheet.addEventListener('close', onSheetClosed);
      new root.MutationObserver(() => { if (sheet.open) onSheetOpened(); })
        .observe(sheet, { attributes: true, attributeFilter: ['open'] });
    }
    doc.body.setAttribute('data-distance', 'home');
    if (fromStart()) for (const view of views()) view.addEventListener('touchmove', stopTwo, { passive: false });
    return true;
  }

  function drawHorizon() {
    if (!horizon || !root.CliveHorizon) return;
    const home = H();
    const model = root.CliveHorizon.layout(home.objectives(), { now: new Date(), needs: home.needs(), builds: home.builds() });
    const top = horizon.scrollTop;
    root.CliveHorizon.draw(horizon, model, {
      open: (id, row) => openFrom(id, row),
      home: () => go(HOME, { control: true }),
    });
    horizon.scrollTop = top;
  }

  /* Where on each view a move scales about: a point on the page, measured against each view's own
   * box once, before anything is scaled (a scaled view's box has moved). */
  function aim(origin) {
    const home = homeEl();
    const sheet = sheetEl();
    clearStyle(home);
    clearStyle(horizon);
    const at = (node) => {
      if (!node) return '50% 50%';
      const box = node.getBoundingClientRect();
      if (!box.width && node === horizon && home) return at(home);   // not laid out yet: the same band as the home
      return `${(origin.x - box.left).toFixed(1)}px ${(origin.y - box.top).toFixed(1)}px`;
    };
    S.origins = { home: at(home), horizon: at(horizon), sheet: sheet && sheet.open ? at(sheet) : '50% 50%' };
  }
  // Draw the home and the horizon at level L.
  function paintViews(L) {
    const home = homeEl();
    for (const [node, i, origin] of [[horizon, HORIZON, S.origins.horizon], [home, HOME, S.origins.home]]) {
      if (!node) continue;
      const look = layer(L, i);
      node.style.transition = 'none';
      node.style.pointerEvents = 'none';
      node.style.transformOrigin = origin;
      node.style.transform = `scale(${look.scale.toFixed(4)})`;
      node.style.opacity = look.opacity.toFixed(3);
      node.style.visibility = look.opacity < 0.01 ? 'hidden' : 'visible';
    }
  }
  function paintSheet(L) {
    const sheet = sheetEl();
    if (!sheet) return;
    const look = layer(L, OBJECTIVE);
    sheet.style.animation = 'none';
    sheet.style.transition = 'none';
    sheet.style.transformOrigin = S.origins.sheet;
    sheet.style.transform = `scale(${look.scale.toFixed(4)})`;
    sheet.style.opacity = look.opacity.toFixed(3);
  }
  function clearStyle(node) {
    if (!node) return;
    for (const k of ['transition', 'pointerEvents', 'transformOrigin', 'transform', 'opacity', 'visibility', 'animation']) node.style[k] = '';
  }
  const NAMES = { [HORIZON]: 'Next six weeks', [HOME]: 'Home' };

  // The views at rest at a level: the one shown is the one that can be touched. `quiet`: the
  // level changed under a sheet that is opening, which says what it is itself.
  function rest(level, quiet) {
    const home = homeEl();
    const was = S.base;
    S.base = level;
    S.L = level;
    clearStyle(home);
    clearStyle(horizon);
    if (level === HORIZON && horizon && horizon.hidden) drawHorizon();
    if (horizon) horizon.hidden = level !== HORIZON;
    if (home) {
      home.classList.toggle('is-away', level === HORIZON);
      home.inert = level === HORIZON;
      if (level === HORIZON) home.setAttribute('aria-hidden', 'true'); else home.removeAttribute('aria-hidden');
    }
    if (!objectiveOpen()) doc.body.setAttribute('data-distance', level === HORIZON ? 'horizon' : 'home');
    if (was !== level && status && !quiet) status.textContent = NAMES[level];
  }

  function label(words, ms) {
    if (!pill) return;
    pill.textContent = words;
    pill.classList.add('is-on');
    clearTimeout(S.labelTimer);
    if (ms) S.labelTimer = setTimeout(() => pill.classList.remove('is-on'), ms);
  }
  function labelFor(level, rowTitle) {
    return level >= OBJECTIVE ? (rowTitle || '') : NAMES[level];
  }
  // What each control stands in for, in the design's words: said the first time it is used.
  const TEACH = {
    [HORIZON]: 'Tap a row to go into it. Double-tap anywhere to come back home.',
    [HOME]: 'Pinch out for the next six weeks. Tap a row, or spread over it, to go in.',
  };
  const taught = new Set();

  // A tween from one level to another, painting each frame; returns a function that stops it.
  function tween(from, to, paint, done) {
    if (reduced() || from === to) { paint(to); done(); return () => {}; }
    const ms = Math.min(SETTLE_MS, 120 + Math.abs(to - from) * (SETTLE_MS - 120));
    const t0 = now();
    let raf = 0;
    let dead = false;
    const step = () => {
      if (dead) return;
      const t = Math.min(1, (now() - t0) / ms);
      const e = 1 - Math.pow(1 - t, 3);
      paint(from + (to - from) * e);
      if (t < 1) raf = root.requestAnimationFrame(step); else done();
    };
    raf = root.requestAnimationFrame(step);
    return () => { dead = true; root.cancelAnimationFrame(raf); };
  }
  function stopSettle() {
    if (S.stop) { S.stop(); S.stop = null; }
  }

  // Move the resting views to a level, the way a control (or a double-tap, or Escape) asks.
  function go(level, opts) {
    const o = opts || {};
    if (!setup() || (level === S.base && !S.stop)) return;
    stopSettle();
    if (level === HORIZON && horizon.hidden) { drawHorizon(); horizon.hidden = false; }
    const box = homeEl().getBoundingClientRect();
    aim(o.origin || { x: box.left + box.width / 2, y: box.top + Math.min(box.height, 420) / 2 });
    feel('level');
    S.stop = tween(S.L, level, (L) => { S.L = L; if (!reduced()) paintViews(L); }, () => {
      S.stop = null;
      rest(level);
      if (o.control) focusAfter(level);
      const teach = o.control && !taught.has(level);
      if (teach) taught.add(level);
      label(teach ? TEACH[level] : NAMES[level], teach ? 2600 : 700);
    });
  }
  function focusAfter(level) {
    const target = level === HORIZON ? horizon && horizon.querySelector('[data-hz="home"]') : doc.querySelector('#alpha-home [data-hz="horizon"]');
    if (target && typeof target.focus === 'function') target.focus({ preventScroll: true });
  }

  // ---- a pinch, from two fingers or a trackpad ----
  function rowUnder(zone, x, y) {
    const under = typeof doc.elementFromPoint === 'function' ? doc.elementFromPoint(x, y) : null;
    const sel = zone === 'home' ? '[data-alpha="objective"][data-objective]' : zone === 'horizon' ? '.hz-row[data-objective]' : null;
    const row = sel && under && under.closest ? under.closest(sel) : null;
    return row && hitOf(row).zone === zone ? row : null;
  }
  function homeRow(id) {
    const home = homeEl();
    if (!home || !id) return null;
    return Array.from(home.querySelectorAll('[data-alpha="objective"][data-objective]')).find((r) => r.getAttribute('data-objective') === id) || null;
  }
  function begin(kind, zone, x, y) {
    if (!setup()) return false;
    stopSettle();
    const row = zone === 'sheet' ? null : rowUnder(zone, x, y);
    const rowId = row ? row.getAttribute('data-objective') : null;
    const { min, max } = reach(zone, Boolean(rowId));
    const from = zone === 'sheet' ? OBJECTIVE : S.L;
    if (zone !== 'sheet' && horizon.hidden) { drawHorizon(); horizon.hidden = false; }
    let origin = { x, y };
    if (rowId) {
      // Into an objective, the home zooms toward that objective's own row.
      clearStyle(homeEl());
      const r = (homeRow(rowId) || row).getBoundingClientRect();
      origin = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    }
    if (zone === 'sheet') clearStyle(sheetEl());
    aim(origin);
    const titleEl = row ? row.querySelector('.alpha-row-title, .hz-title') : null;
    S.gesture = { kind, zone, from, L: from, min, max, rowId, title: titleEl ? titleEl.textContent : '' };
    if (!reduced()) { if (zone === 'sheet') paintSheet(from); else paintViews(from); }
    label(labelFor(Math.round(from), S.gesture.title), 0);
    return true;
  }
  function move(scale) {
    const g = S.gesture;
    if (!g) return;
    const L = rubber(levelOf(g.from, scale), g.min, g.max);
    if (crossed(g.L, L, g.min, g.max)) {
      feel('tick');
      label(labelFor(Math.round(clamp(L, g.min, g.max)), g.title), 0);
    }
    g.L = L;
    if (g.zone !== 'sheet') S.L = L;
    if (reduced()) return;            // nothing travels; the label says where it will land
    if (g.zone === 'sheet') paintSheet(L);
    else paintViews(Math.min(L, OBJECTIVE));
  }
  function end() {
    const g = S.gesture;
    S.gesture = null;
    if (!g) return;
    const to = settle(g.from, g.L, g.min, g.max);
    if (to !== Math.round(g.from)) feel('snap');
    setTimeout(() => { if (pill && !S.gesture) pill.classList.remove('is-on'); }, 700);
    if (g.zone === 'sheet') {
      const sheet = sheetEl();
      if (to >= OBJECTIVE) {
        S.stop = tween(g.L, OBJECTIVE, paintSheet, () => { S.stop = null; clearStyle(sheet); });
        return;
      }
      // Out of the objective: the sheet goes as it was going, and the views rest underneath.
      S.stop = tween(g.L, Math.max(to, 1.25), paintSheet, () => {
        S.stop = null;
        rest(to);
        if (H()) H().closeSheet();
      });
      return;
    }
    if (to === OBJECTIVE && g.rowId) {
      openFrom(g.rowId, homeRow(g.rowId), true);
      return;
    }
    S.stop = tween(g.L, to, (L) => { S.L = L; paintViews(L); }, () => { S.stop = null; rest(to); });
  }

  // ---- into an objective: its sheet forms out of its own row ----
  function openFrom(id, row, spread) {
    if (!setup() || !id) return;
    const rect = row && typeof row.getBoundingClientRect === 'function' ? row.getBoundingClientRect() : null;
    S.from = { id, rect, at: now() };
    if (spread) {
      // The home stays where the fingers left it until the sheet is up, or goes back if it never is.
      const back = () => {
        if (!S.pending || S.pending.id !== id) return;
        clearTimeout(S.pending.timer);
        S.pending = null;
        if (objectiveOpen() === id) return;
        S.stop = tween(S.L, S.base, (L) => { S.L = L; paintViews(L); }, () => { S.stop = null; rest(S.base); });
      };
      S.pending = { id, timer: setTimeout(back, OPEN_WAIT_MS) };
      Promise.resolve(H().openObjective(id)).then(back, back);
      return;
    }
    H().openObjective(id);
  }
  function onSheetOpened() {
    const id = objectiveOpen();
    if (!id) return;
    // Coming back out of an objective is coming home, whatever distance it was opened from.
    if (S.pending) { clearTimeout(S.pending.timer); S.pending = null; }
    stopSettle();
    rest(HOME, true);
    doc.body.setAttribute('data-distance', 'objective');
    const from = S.from;
    S.from = null;
    const sheet = sheetEl();
    if (!from || from.id !== id || !from.rect || now() - from.at > 5000 || reduced() || typeof sheet.animate !== 'function') return;
    const to = sheet.getBoundingClientRect();
    if (!to.width || !to.height || !from.rect.width) return;
    // The row grows into the sheet: it starts as the row, the width and place of it, and opens out.
    const s = Math.min(1, from.rect.width / to.width);
    const dx = (from.rect.left + from.rect.width / 2) - (to.left + to.width / 2);
    const dy = from.rect.top - to.top;
    const shown = Math.max(0, to.height - from.rect.height / s);
    sheet.classList.add('hz-forming');
    const run = sheet.animate([
      { transformOrigin: '50% 0', transform: `translate(${dx.toFixed(1)}px, ${dy.toFixed(1)}px) scale(${s.toFixed(4)})`, clipPath: `inset(0 0 ${shown.toFixed(1)}px 0 round 26px)`, opacity: 0.6 },
      { transformOrigin: '50% 0', transform: 'none', clipPath: 'inset(0 0 0 0 round 38px)', opacity: 1 },
    ], { duration: 320, easing: 'cubic-bezier(.32,.72,0,1)' });
    const done = () => sheet.classList.remove('hz-forming');
    run.onfinish = done;
    run.oncancel = done;
  }
  function onSheetClosed() {
    clearStyle(sheetEl());
    doc.body.setAttribute('data-distance', S.base === HORIZON ? 'horizon' : 'home');
  }

  // ---- home, from anywhere ----
  function goHome() {
    if (objectiveOpen()) {
      feel('level');
      rest(HOME);
      H().closeSheet();
      return;
    }
    if (S.base === HORIZON) go(HOME);
  }

  // ---- fingers ----
  const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  function stopTwo(event) { if (S.gesture && event.cancelable) event.preventDefault(); }
  // iOS decides at the start of a touch whether the page may stop it, so there, as in lift.js,
  // the listener is in place from the start; elsewhere only while a finger is down on a view.
  // On the three views themselves, never the document (lift.js's) or the window: it stops
  // nothing anywhere else, and a scroll anywhere else never waits for it.
  // Worked out when first needed: lift.js, whose rule this is, loads after this file.
  let early = null;
  const fromStart = () => {
    if (early !== null) return early;
    const nav = root.navigator || {};
    early = root.CliveLift && typeof root.CliveLift.guardsFromStart === 'function'
      ? Boolean(root.CliveLift.guardsFromStart(nav.userAgent, nav.platform, nav.maxTouchPoints))
      : /iP(hone|ad|od)/.test(String(nav.userAgent)) || (String(nav.platform) === 'MacIntel' && Number(nav.maxTouchPoints) > 1);
    return early;
  };
  const views = () => [homeEl(), horizon, sheetEl()].filter(Boolean);
  function guard(on) {
    if (fromStart() || S.guarded === on) return;
    S.guarded = on;
    for (const view of views()) {
      if (on) view.addEventListener('touchmove', stopTwo, { passive: false });
      else view.removeEventListener('touchmove', stopTwo, { passive: false });
    }
  }

  function sweep() {
    const cutoff = now() - STALE_MS;
    for (const [id, p] of Array.from(S.pts)) if (p.t < cutoff) S.pts.delete(id);
  }
  function onDown(event) {
    if (event.button !== undefined && event.button > 0) return;
    sweep();
    const hit = hitOf(event.target);
    const p = { id: event.pointerId, x: event.clientX, y: event.clientY, x0: event.clientX, y0: event.clientY, t: now(),
      hit, empty: emptyAt(event.target), paired: false };
    S.pts.set(event.pointerId, p);
    if (hit.zone && event.pointerType !== 'mouse') guard(true);
    // The home is drawn again every few seconds, and a lift on a node no longer in the page never
    // reaches the document: so the lift is listened for on the node too (as web/app.js does), and
    // counted once, by whichever hears it first.
    if (hit.zone && event.target && typeof event.target.addEventListener === 'function') {
      for (const type of ['pointerup', 'pointercancel']) {
        event.target.addEventListener(type, (lift) => { if (S.pts.has(lift.pointerId)) onUp(lift); }, { once: true });
      }
    }
    if (S.gesture || S.pts.size !== 2) return;
    const [a, b] = Array.from(S.pts.values());
    if (!pairs(a.hit, b.hit, busy())) return;
    const zone = a.hit.zone;
    if (zone === 'sheet' ? !objectiveOpen() : !homeShown() || (zone === 'home' && S.base !== HOME) || (zone === 'horizon' && S.base !== HORIZON)) return;
    if (!begin('pinch', zone, (a.x + b.x) / 2, (a.y + b.y) / 2)) return;
    a.paired = true;
    b.paired = true;
    S.lastTap = null;
    S.pair = { ids: [a.id, b.id], d0: Math.max(1, dist(a, b)) };
  }
  function onMove(event) {
    const p = S.pts.get(event.pointerId);
    if (!p) return;
    p.x = event.clientX;
    p.y = event.clientY;
    if (!S.pair || !S.gesture || S.pair.ids.indexOf(event.pointerId) < 0) return;
    const a = S.pts.get(S.pair.ids[0]);
    const b = S.pts.get(S.pair.ids[1]);
    if (a && b) move(dist(a, b) / S.pair.d0);
  }
  function onUp(event) {
    const p = S.pts.get(event.pointerId);
    S.pts.delete(event.pointerId);
    if (!S.pts.size) guard(false);
    if (S.pair && S.pair.ids.indexOf(event.pointerId) >= 0) {
      S.pair = null;
      S.swallowUntil = now() + SWALLOW_MS;
      end();
      return;
    }
    if (!p || p.paired || event.type === 'pointercancel') { S.lastTap = null; return; }
    const quick = now() - p.t < TAP_MS && Math.hypot(event.clientX - p.x0, event.clientY - p.y0) < TAP_PX;
    if (!quick || !p.empty) { S.lastTap = null; return; }
    const last = S.lastTap;
    if (last && last.zone === p.hit.zone && now() - last.t < DOUBLE_MS && Math.hypot(event.clientX - last.x, event.clientY - last.y) < DOUBLE_PX) {
      S.lastTap = null;
      // The click this second tap ends with lands on whatever is under it once the view has
      // changed (a home row, which would open again): it is not a tap on that.
      S.swallowUntil = now() + SWALLOW_MS;
      try { const sel = root.getSelection && root.getSelection(); if (sel && sel.removeAllRanges) sel.removeAllRanges(); } catch (e) { /* none */ }
      goHome();
      return;
    }
    S.lastTap = { t: now(), x: event.clientX, y: event.clientY, zone: p.hit.zone };
  }
  function onWheel(event) {
    if (!event.ctrlKey) return;
    if (!S.wheel) {
      const hit = hitOf(event.target);
      if (!claim(hit) || busy() || S.gesture) return;
      if (hit.zone === 'sheet' ? !objectiveOpen() : !homeShown() || (hit.zone === 'home' && S.base !== HOME) || (hit.zone === 'horizon' && S.base !== HORIZON)) return;
      event.preventDefault();
      if (!begin('wheel', hit.zone, event.clientX, event.clientY)) return;
      S.wheel = { scale: 1, timer: 0 };
    }
    event.preventDefault();
    S.wheel.scale *= Math.exp(-event.deltaY * WHEEL_RATE);
    move(S.wheel.scale);
    clearTimeout(S.wheel.timer);
    S.wheel.timer = setTimeout(() => { S.wheel = null; end(); }, WHEEL_IDLE_MS);
  }
  // Which row a tap on the home opened, so its sheet forms out of it; and the click a pinch ends
  // with, which is not a tap on whatever row is under it.
  function onClick(event) {
    const zone = hitOf(event.target).zone;
    if (zone && now() < S.swallowUntil) { event.preventDefault(); event.stopPropagation(); return; }
    const row = zone === 'home' && event.target.closest ? event.target.closest('[data-alpha="objective"][data-objective]') : null;
    if (row) S.from = { id: row.getAttribute('data-objective'), rect: row.getBoundingClientRect(), at: now() };
  }
  function onKey(event) {
    if (event.key !== 'Escape' || S.base !== HORIZON || objectiveOpen()) return;
    if (event.target && event.target.closest && event.target.closest(FIELD)) return;
    go(HOME, { control: true });
  }

  function wire() {
    if (!setup()) return;
    doc.addEventListener('pointerdown', onDown, true);
    doc.addEventListener('pointermove', onMove, { capture: true, passive: true });
    doc.addEventListener('pointerup', onUp, true);
    doc.addEventListener('pointercancel', onUp, true);
    doc.addEventListener('click', onClick, true);
    doc.addEventListener('keydown', onKey);
    // Safari's own pinch-to-zoom, on the three views only.
    for (const type of ['gesturestart', 'gesturechange']) {
      doc.addEventListener(type, (event) => { if (hitOf(event.target).zone && event.cancelable) event.preventDefault(); }, { passive: false });
    }
    for (const type of ['blur', 'pagehide']) root.addEventListener(type, () => { S.pts.clear(); S.pair = null; if (S.gesture) end(); });
  }
  let wiring = false;
  function wireOnce() { if (!wiring && setup()) { wiring = true; wire(); } }
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', wireOnce);
  else setTimeout(wireOnce, 0);

  // What web/alpha.js asks for: the way to the next six weeks without a gesture, and word that
  // the home was drawn again (so the horizon, if it is up, is too).
  api.homeControl = function homeControl() {
    const button = doc.createElement('button');
    button.type = 'button';
    button.className = 'hz-go';
    button.setAttribute('data-hz', 'horizon');
    const NS = 'http://www.w3.org/2000/svg';
    const icon = doc.createElementNS(NS, 'svg');
    icon.setAttribute('viewBox', '0 0 24 12');
    icon.setAttribute('width', '24');
    icon.setAttribute('height', '12');
    icon.setAttribute('aria-hidden', 'true');
    icon.setAttribute('focusable', 'false');
    icon.setAttribute('class', 'hz-go-dots');
    for (let i = 0; i < 5; i++) {
      const c = doc.createElementNS(NS, 'circle');
      c.setAttribute('cx', String(3 + i * 4.5));
      c.setAttribute('cy', '6');
      c.setAttribute('r', i === 0 ? '2.2' : '1.3');
      icon.appendChild(c);
    }
    const words = doc.createElement('span');
    words.textContent = 'Next six weeks';
    button.appendChild(icon);
    button.appendChild(words);
    button.addEventListener('click', () => { wireOnce(); go(HORIZON, { control: true }); });
    return button;
  };
  api.drawn = function drawn() {
    if (!S.wired) { wireOnce(); return; }
    if (S.base === HORIZON && !S.gesture && !S.stop) drawHorizon();
  };
  api.go = (level) => go(level, { control: true });
  api.level = () => (objectiveOpen() ? OBJECTIVE : S.base);
  return api;
});

/* The app's start-up: CLIVE's orb waking, then the name.
 *
 * The orb gathers out of the dark: its dots are drawn in from around it towards a soft light in the
 * app's blue, and settle into the glass (web/dots.js, boot). There is no flash and no flare; the
 * owner found the old point-of-light, cross-flare and screen flash "terrible" (29 Sep 2026).
 *
 * The whole of it plays the first time the app opens on a day and after CLIVE has been updated
 * (the build the page was served with is not the one this device last started); every other
 * open it is the name and its line alone. The line under the name fills when CLIVE has actually
 * answered: the start-up watches the system layer (web/app.js) and hands over only when it says
 * online. If CLIVE is slow the line waits and says so; if it cannot be reached or refuses, the
 * start-up steps aside and the system layer says why. A tap skips ahead. The name then pours
 * into the orb, which settles where the app's own orb is, and the start-up fades onto the app.
 *
 * `?startup=full`, `?startup=quick` or `?startup=off` overrides the rule, to look at either.
 * Nothing here is sent anywhere; the day and build seen are kept on this device.
 */
'use strict';

(function () {
  const root = document.getElementById('startup');
  if (!root) return;
  if (!window.CliveDots) { root.remove(); return; }
  // The way out comes first (the 2026-09-27 deploy review, round 6, B-06): before anything that
  // can fail, a timer that takes the start-up away whatever happens, and every step after it
  // runs inside a guard that takes it away at once if that step throws. `is-live` (which stops
  // the stylesheet's own give-way) is added only once the dots are running.
  let gone = false;
  let E = null;
  function bail() {
    if (gone) return;
    gone = true;
    root.classList.add('is-gone');
    setTimeout(() => { try { if (E) E.destroy(); } catch (e) { /* going anyway */ } root.remove(); }, 700);
  }
  setTimeout(bail, 20000);
  try {
  const $ = (id) => document.getElementById(id);
  const FAM = '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", system-ui, "Helvetica Neue", Helvetica, sans-serif';
  const KEY = 'clive.startup';
  const meta = document.querySelector('meta[name="crooks-build"]');
  const BUILD = meta ? meta.getAttribute('content') || '' : '';
  const systemEl = document.getElementById('system');
  const markEl = $('startup-mark');
  let reduced = false;
  try { reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { reduced = false; }
  let lite = false;
  try {
    lite = (navigator.hardwareConcurrency || 8) <= 4 || (navigator.deviceMemory || 8) <= 3 || /SM-T29\d/.test(navigator.userAgent || '');
  } catch (e) { lite = false; }

  // ---- which start-up ----
  const forced = new URLSearchParams(location.search).get('startup');
  if (forced === 'off') { root.remove(); return; }
  const today = new Date().toDateString();
  let seen = null;
  try { seen = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) { seen = null; }
  let kind = (!seen || seen.day !== today || seen.build !== BUILD) ? 'full' : 'quick';
  if (forced === 'full' || forced === 'quick') kind = forced;
  if (reduced) kind = 'quick';
  if (kind === 'full') {
    try { localStorage.setItem(KEY, JSON.stringify({ day: today, build: BUILD })); } catch (e) { /* plays again next time */ }
  }

  // ---- the page, in its own pixels ----
  const W = Math.max(320, window.innerWidth || 390), H = Math.max(480, window.innerHeight || 844);
  const s = Math.max(1, Math.min(2.2, Math.min(W / 390, H / 844)));
  const L = {
    u: s, cell: 18, uiStep: 3, dot: 1.4,
    orb: { cx: W / 2, cy: H * 0.46, R: 104 * s },
    mini: { cx: W / 2, cy: H * 0.46, R: 20 },
    check: { cx: W / 2, cy: H / 2, k: 0.6, label: 40, ly: H * 0.7, step: 3 },
  };
  const B = { S: { x: W / 2, y: H * 0.46 }, R: 104 * s, init: 30 * s, gap: 46 * s, word: 12 * s, wordGap: 10 * s, line: 64 * s, glint: 240 * s };
  B.markTop = B.S.y - B.init / 2;

  E = window.CliveDots.create({
    canvas: $('startup-dots'), bloom: $('startup-bloom'), fx: $('startup-fx'), root, W, H, L,
    density: lite ? 5000 : 11000, speed: 1, calm: reduced, maxScale: lite ? 1 : 2,
  });
  root.classList.add('is-live');

  // ---- the name ----
  const ACRONYM = [['C', 'OMPUTER'], ['L', 'ANGUAGE'], ['I', 'NTERFACE'], ['V', 'IRTUAL'], ['E', 'NVIRONMENT']];
  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  const probe = document.createElement('canvas').getContext('2d');
  probe.font = '600 ' + B.init + 'px ' + FAM;
  const widths = ACRONYM.map((w) => probe.measureText(w[0]).width);
  const gap = B.init * 0.62;
  const total = widths.reduce((a, b) => a + b, 0) + gap * 4;
  const markXs = [];
  let x = W / 2 - total / 2;
  for (let i = 0; i < 5; i++) { markXs.push(x); x += widths[i] + gap; }
  probe.font = '500 ' + B.word + 'px ' + FAM;
  const block = widths[4] + B.wordGap + probe.measureText('NVIRONMENT').width + 10 * B.word * 0.34;
  const colX = W / 2 - block / 2;
  const top0 = B.markTop - 2 * B.gap;
  const rows = ACRONYM.map((w, i) => {
    const row = el('div', 'bt-row');
    row.dataset.col = colX + ',' + (top0 + i * B.gap);
    row.dataset.mark = markXs[i] + ',' + B.markTop;
    row.style.setProperty('--id', Math.round((kind === 'quick' ? i * 0.04 : 0.55 + i * 0.13) * 1000) + 'ms');
    row.style.setProperty('--wd', Math.round((0.65 + i * 0.13) * 1000) + 'ms');
    row.style.setProperty('--cd', Math.round(i * 30) + 'ms');
    row.style.setProperty('--md', Math.round(i * 50) + 'ms');
    const init = el('span', 'bt-init', w[0]);
    init.style.fontSize = B.init + 'px';
    const word = el('span', 'bt-word', w[1]);
    word.style.fontSize = B.word + 'px';
    word.style.marginLeft = B.wordGap + 'px';
    word.style.maxWidth = Math.ceil(B.word * 11) + 'px';
    row.appendChild(init);
    row.appendChild(word);
    markEl.insertBefore(row, $('startup-line'));
    return row;
  });
  function rowsTo(mark) {
    for (const row of rows) {
      const [rx, ry] = (mark ? row.dataset.mark : row.dataset.col).split(',').map(Number);
      row.style.left = rx + 'px';
      row.style.top = ry + 'px';
    }
  }
  rowsTo(kind === 'quick');
  const line = $('startup-line');
  line.style.left = (W / 2 - B.line / 2) + 'px';
  line.style.top = (B.markTop + B.init * 1.55) + 'px';
  line.style.width = B.line + 'px';
  const wait = $('startup-wait');
  wait.style.top = (B.markTop + B.init * 1.55 + 22) + 'px';
  wait.style.fontSize = Math.round(13 * Math.min(1.4, s)) + 'px';

  function sampleInits(step, dot) {
    const R0 = root.getBoundingClientRect();
    const c = document.createElement('canvas');
    c.width = W; c.height = H;
    const g = c.getContext('2d', { willReadFrequently: true });
    const range = document.createRange();
    return rows.map((row) => {
      const init = row.firstChild, node = init.firstChild, list = [];
      if (!node) return list;
      const cs = getComputedStyle(init);
      g.font = cs.fontStyle + ' ' + cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily;
      g.fillStyle = '#ffffff';
      g.textBaseline = 'alphabetic';
      const fs = parseFloat(cs.fontSize) || 16;
      const m = g.measureText('Hg');
      const asc = m.fontBoundingBoxAscent || fs * 0.8, dsc = m.fontBoundingBoxDescent || fs * 0.2;
      range.setStart(node, 0); range.setEnd(node, 1);
      const r = range.getBoundingClientRect();
      const rx = r.left - R0.left, ry = r.top - R0.top;
      g.clearRect(0, 0, W, H);
      g.fillText(node.nodeValue.charAt(0), rx, ry + (r.height - asc - dsc) / 2 + asc);
      const x0 = Math.max(0, Math.floor(rx - 6)), y0 = Math.max(0, Math.floor(ry - 6));
      const bw = Math.min(W - x0, Math.ceil(r.width + 12)), bh = Math.min(H - y0, Math.ceil(r.height + 12));
      if (bw <= 0 || bh <= 0) return list;
      const d = g.getImageData(x0, y0, bw, bh).data;
      for (let yy = 0; yy < bh; yy += step) {
        for (let xx = 0; xx < bw; xx += step) {
          if (d[(yy * bw + xx) * 4 + 3] > 90) list.push({ x: x0 + xx, y: y0 + yy, r: 240, g: 244, b: 252, a: 0.92, s: dot });
        }
      }
      return list;
    });
  }
  // Where the app's own orb is, so the start-up's orb lands on it.
  function home() {
    const orb = document.getElementById('orb');
    if (orb) {
      const r = orb.getBoundingClientRect();
      if (r.width > 20 && r.height > 20 && r.bottom > 0 && r.top < H) return { cx: r.left + r.width / 2, cy: r.top + r.height / 2, R: r.width * 0.31 };
    }
    return { cx: W / 2, cy: H * 0.36, R: 80 * s };
  }

  // ---- CLIVE's answer, as the system layer shows it ----
  const phase = () => (systemEl ? systemEl.dataset.phase : 'online');
  const ready = () => phase() === 'online';
  const failed = () => phase() === 'offline' || phase() === 'refused';

  const markBox = { x0: markXs[0], x1: markXs[4] + widths[4], y0: B.markTop, y1: B.markTop + B.init };
  const spec = {
    S: B.S, R: B.R, home: home(), homeBody: 0.9, endTint: 0, markBox, quick: kind === 'quick',
    handoffAt: null, clock: [],
    markTargets: () => [].concat(...sampleInits(2, 1.4)),
  };
  let T0 = 0, handedOff = false, finished = false, loadAt = 0, slowTimer = 0;
  function setMark(names) { markEl.className = 'bt-mark ' + names; }
  function finish() {
    if (finished) return;
    finished = true;
    bail();
  }
  function handoff() {
    if (handedOff || finished) return;
    handedOff = true;
    clearTimeout(slowTimer);
    markEl.classList.remove('is-slow');
    spec.home = home();
    const t = E.time();
    const go = () => {
      markEl.classList.add('is-out');
      E.setHome(spec.home);
      E.handoff(spec);
      E.at(E.time() + 1.5, finish);
    };
    // Let the line finish filling before the name comes apart.
    if (t < loadAt + 0.95) E.at(loadAt + 0.95, go); else E.at(t + 0.35, go);
  }
  // From the moment the line appears: hand over when CLIVE is there, step aside if it is not.
  function watch() {
    loadAt = E.time();
    if (ready()) { handoff(); return; }
    if (failed()) { finish(); return; }
    slowTimer = setTimeout(() => { if (!handedOff && !finished) markEl.classList.add('is-slow'); }, 1500);
  }
  if (systemEl && typeof MutationObserver !== 'undefined') {
    new MutationObserver(() => {
      if (finished || !loadAt) return;
      if (ready()) handoff(); else if (failed()) finish();
    }).observe(systemEl, { attributes: true, attributeFilter: ['data-phase'] });
  }

  function runFull() {
    const tg = sampleInits(2, 1.3);
    const R0 = root.getBoundingClientRect();
    spec.rows = rows.map((row, i) => {
      const r = row.firstChild.getBoundingClientRect(), rr = row.getBoundingClientRect();
      const cx = r.left + r.width / 2 - R0.left, cy = r.top + r.height / 2 - R0.top;
      const [mx, my] = row.dataset.mark.split(',').map(Number);
      return { targets: tg[i] || [], col: { x: cx, y: cy }, mark: { x: mx + widths[i] / 2, y: my + (cy - (rr.top - R0.top)) }, left: rr.left - R0.left, right: rr.right - R0.left };
    });
    const U = L.u;
    spec.glints = spec.rows.map((r, i) => ({ t: 3.0 + i * 0.13, y: r.col.y, x0: r.left - U * 50, x1: r.right + U * 20, len: B.glint, xi: r.col.x }));
    spec.glints.push({ t: 5.15, y: spec.rows.length ? spec.rows[0].mark.y : B.markTop + B.init / 2, x0: markBox.x0 - U * 60, x1: markBox.x1 + U * 60, len: B.glint * 1.3, xi: (markBox.x0 + markBox.x1) / 2 });
    T0 = E.time();
    E.boot(spec);
    E.at(T0 + 2.45, () => setMark('is-acro'));
    E.at(T0 + 4.1, () => setMark('is-acro is-collapse'));
    E.at(T0 + 4.35, () => { setMark('is-acro is-collapse is-mark'); rowsTo(true); });
    E.at(T0 + 5.1, () => { setMark('is-acro is-collapse is-mark is-load'); watch(); });
  }
  function runQuick() {
    T0 = E.time();
    E.quick(spec);
    setMark('is-quick');
    E.at(T0 + 0.3, () => { setMark('is-quick is-load'); watch(); });
  }
  // A tap while the start-up is up (design pass, 3 Oct). It used to land on the start-up itself
  // and be spent there: a finger on the Orders icon in the first five seconds of the day opened
  // nothing, and the next tap had to be made again. The layer takes no touches now (startup.css)
  // and this hears the tap first, on the way down to the app:
  //   - CLIVE is there: the start-up steps aside at once, and a tap on the dock or the gear goes
  //     through to it, so it opens what was pressed. Those are the only controls let through —
  //     fixed, in places he knows by hand — and nothing on a card is ever reached unseen.
  //   - CLIVE is not there yet: the tap skips ahead, as it always did, and reaches nothing.
  // A tap that is stopped here stops whole: its own click, which the browser sends after the
  // finger lifts, is the one thing swallowed after it, matched by pointer id. Its pointerup goes
  // on, so nothing beneath is left thinking a finger is still down, and a second tap, on Orders
  // 0.4 s later, is a new pointer and opens Orders (review of the design pass, 3 Oct).
  const PASS = '.dock-btn, #settings-btn';
  let held = null;   // { id, until }: the stopped tap whose click is still to come
  function onClick(e) {
    if (!held || !e.isTrusted) return;
    const stale = performance.now() > held.until;
    // A browser too old to put a pointer id on a click: the click that follows is that tap's.
    const theirs = typeof e.pointerId !== 'number' || e.pointerId === held.id;
    if (stale || theirs) held = null;
    if (stale || !theirs) return;
    e.stopPropagation();
    e.preventDefault();
  }
  function onDown(e) {
    if (e.isTrusted) held = null;   // a new finger: whatever came before has had its click
    // A finger's tap, not one a script dispatched on an element of its own choosing.
    if (finished || gone || !e.isTrusted) return;
    const target = e.target && e.target.closest ? e.target.closest(PASS) : null;
    let through = false;
    try {
      if (ready()) { finish(); through = Boolean(target); }
      else if (kind === 'full' && !loadAt && E.time() < T0 + 5.1) E.simulate(T0 + 5.15);
      else if (failed()) finish();
    } catch (err) { bail(); }
    if (through) return;
    held = { id: e.pointerId, until: performance.now() + 900 };
    e.stopPropagation();
    e.preventDefault();
  }
  document.addEventListener('pointerdown', onDown, true);
  document.addEventListener('click', onClick, true);
  requestAnimationFrame(() => requestAnimationFrame(() => {
    try { if (kind === 'full') runFull(); else runQuick(); } catch (e) { bail(); }
  }));
  } catch (e) {
    bail();
  }
})();

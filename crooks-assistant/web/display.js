/* A screen of the owner's (app/routes/displays.py).
 *
 * A device opens /display once and names itself ("office screen", "packing screen"). From then
 * on it asks every couple of seconds what it should show, and CLIVE's dots (web/dots.js) carry
 * whatever the owner put on it: an order's fulfilment slip, an objective, or a list. The orb
 * breathes in and bursts, the dots fly to where the page's letters and panels are, land as coarse
 * blocks top first, sharpen as a scan passes, and the page resolves out of blur beneath them.
 * A slip can be marked packed (a list, done) here; the dots swirl into a check and the page comes
 * back in its done state. When CLIVE clears the screen the page dissolves back into the orb and
 * the dot clock.
 *
 * Everything drawn comes from the screen's own record, written as text (textContent), never as
 * markup. The page holds nothing but the screen's id and name, kept on this device.
 *
 * Round 8 of the deploy review. A newly named screen shows only a six-digit code until the owner
 * reads it off this device and tells CLIVE (B-02); the code is kept in memory, never stored. What
 * a customer's slip shows leaves the screen at once when CLIVE refuses it (403), when CLIVE has
 * been out of reach for two minutes, and once it is older than CLIVE keeps anything up
 * (NEW-B-LOCAL-SLIP). Pages are told to CLIVE in order, a page at a time, as fast as CLIVE allows,
 * and only the Mark packed tap says "done" (B-04).
 *
 * Round 9. A screen shows one thing or two: side by side on a landscape screen, one above the
 * other on a portrait one. Each pane keeps its own pages and acknowledgements and names itself
 * (its place, and the version it was put up at) when it tells CLIVE a page or "done"; each is
 * taken down by its own time, and a 403 or two minutes out of reach take both down at once. The
 * owner's remote (web/remote.js) ticks items as they go in the box — a check and a dimmed row
 * here — and turns pages; this screen follows both on its next ask, in place, and when CLIVE
 * turns the screen off it goes back to the orb and the clock like any clearing.
 *
 * And a pane can play a YouTube video the owner asked for, in YouTube's own embedded player,
 * worked from his remote, through CLIVE, or with this TV's own remote (see "a video", below).
 *
 * Round 10. The screen's key is not this page's to hold (B2-01): CLIVE sets it as a cookie that no
 * script can read (HttpOnly, for /displays only) when the device names itself, and the browser
 * sends it with every ask; this device keeps only the screen's id and name. A screen named before
 * then hands its old key back to CLIVE once, for the cookie, and forgets it (migrate); since round
 * 11 its record on the device is written again without the key the moment the page reads it, so
 * the key is held in memory alone while it is handed back (loadScreen). An answer to
 * an ask sent before what was shown was taken down is never read (B2-03), so only a fresh answer
 * can put anything up again. And a slip marked packed is drawn from CLIVE's done summary alone —
 * the order's number and when it was packed — never from the copy this screen drew (B2-04).
 *
 * Round 11. A pane past CLIVE's own limit takes the screen down the way a refusal does, at once
 * and whatever it is in the middle of — forming, dissolving or packing — with the dots that drew
 * it (NEW-B-LOCAL-SLIP): never by a dissolve that leaves the page up while it plays. And marked
 * packed, the dots that drew the slip let go of it at once: they never form it again on their way
 * to the check, which comes out of the orb (web/dots.js packOut, B2-04).
 */
'use strict';

(function () {
  const FAM = '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", system-ui, "Helvetica Neue", Helvetica, sans-serif';
  const POLL_MS = 2000;
  const POLL_MAX_MS = 10000;
  const REFUSED_MS = 15000;
  const DONE_HOLD_MS = 45000;          // a packed slip stays up this long, then the screen rests
  const SHOW_KEEP_MS = 12 * 3600 * 1000;   // CLIVE's own limit for anything shown (store.py SHOWING_KEEP_S)
  const OFFLINE_CLEAR_MS = 120000;     // out of reach this long, and what is shown is taken down
  const POLL_TIMEOUT_MS = 15000;       // an ask that hangs is given up, so it counts as out of reach
  const LINE_MS = 6000;
  const KEY = 'clive.screen';
  const BOOT_KEY = 'clive.screen.startup';
  const $ = (id) => document.getElementById(id);
  const buildMeta = document.querySelector('meta[name="crooks-build"]');
  const BUILD = buildMeta ? buildMeta.getAttribute('content') || '' : '';
  const board = $('board'), ui = $('ui'), idleEl = $('idle'), namer = $('namer'), markEl = $('mark'), pairEl = $('pairing');
  const scanEl = $('scan'), statusEl = $('status'), hintEl = $('hint');
  let reduced = false;
  try { reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { reduced = false; }
  const weak = (navigator.hardwareConcurrency || 8) <= 4 || /[?&]lite\b/.test(location.search);
  const calm = reduced;
  if (calm) board.classList.add('is-calm');
  if (weak) $('bloom').hidden = true;

  // ---- what this device is --------------------------------------------------------------
  // A screen is the device holding its key (app/displays/store.py), and since round 10 (B2-01)
  // the key is a cookie CLIVE sets and the browser alone holds: nothing on this page, nor anything
  // that can read its storage, can copy it. What is kept here is the screen's id and name, and
  // nothing else is ever written.
  //
  // A record kept before then also holds the key. Round 11 (B2-01): the moment this page reads
  // such a record it writes it again as the id and name alone — before anything is asked of
  // CLIVE, whatever CLIVE answers later — so the key is off the device's storage at once, and a
  // hand-back that fails, is refused or never gets through cannot leave it there. The key is then
  // held in this page's memory only, for this page's own attempts to hand it back (migrate). If
  // the page is closed or reloaded before CLIVE has taken it, the key is gone for good: the next
  // ask carries no key, CLIVE answers "not this screen", and the screen is named and approved
  // again. That is the safe outcome — a key left in storage could be copied and reused.
  //
  // Held in memory for a bounded time only (LEGACY_KEEP_MS): a page that cannot hand the key back
  // within it lets the key go and has the screen named again, rather than hold a reusable key for
  // as long as the TV stays on (the round-11 independent check). A record this page cannot read
  // at all is removed, not left: whatever it holds, nothing here can say it holds no key.
  const SCREEN_ID = /^scr_[0-9a-f]{12}$/;
  const LEGACY_KEEP_MS = 30 * 60 * 1000;
  let legacyKey = '';
  let legacyUntil = 0;
  function loadScreen() {
    let raw = null;
    try { raw = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) { forgetStored(); return null; }
    if (raw === null) return null;
    if (typeof raw !== 'object' || Array.isArray(raw)) { forgetStored(); return null; }
    const screen = SCREEN_ID.test(String(raw.id || '')) && typeof raw.name === 'string' && raw.name ? { id: raw.id, name: raw.name } : null;
    if (Object.keys(raw).some((k) => k !== 'id' && k !== 'name')) {
      if (screen) legacyKey = typeof raw.key === 'string' ? raw.key.slice(0, 200) : '';
      if (legacyKey) legacyUntil = Date.now() + LEGACY_KEEP_MS;
      // Written again now, as the id and name alone; a record that is not a screen's is not kept.
      if (!screen || !saveScreen(screen)) forgetStored();
    }
    return screen;
  }
  // True once the id and name alone are what is kept.
  function saveScreen(s) {
    try { localStorage.setItem(KEY, JSON.stringify({ id: s.id, name: s.name })); return true; } catch (e) { return false; /* kept for this visit */ }
  }
  function forgetStored() { try { localStorage.removeItem(KEY); } catch (e) { /* nothing kept */ } }
  function forgetScreen() { legacyKey = ''; forgetStored(); }

  const S = {
    screen: loadScreen(),
    version: -1,
    showing: null,         // the first pane CLIVE says is up
    beside: null,          // the second, beside it (round 9)
    lastDone: null,
    phase: 'boot',         // boot · naming · idle · forming · revealing · shown · packing · clearing
    busy: true,
    pending: false,
    drawnKey: '',          // the keys of the panes drawn, in order
    drawnView: null,       // the panes drawn: what each shows, its pages and acknowledgements
    online: null,
    refused: false,
    pushT0: null,
    what: '',
    unapproved: false,     // named, waiting for the owner to approve it with its code
    pairCode: '',          // that code, in memory only
    pairUntil: 0,
    gone: '',              // why what was shown was taken down: 'refused' · 'offline' · ''
    gen: 0,                // bumped when what is shown is wiped; a drawing begun before it is dropped
    lastOk: Date.now(),    // when CLIVE last answered this screen
    skew: 0,               // CLIVE's clock less this device's
  };
  // The videos on this screen (YouTube), by the key of the pane each plays in: kept while the
  // page is drawn again around them, so a video never starts over because the other pane changed.
  const VIDEOS = new Map();

  // ---- the board: a fixed height, as wide as the screen's shape, scaled to fit -----------
  function layout() {
    const vw = Math.max(320, window.innerWidth || 1920), vh = Math.max(320, window.innerHeight || 1080);
    const portrait = vh > vw * 1.05;
    const H = portrait ? 1194 : 1080;
    const W = Math.round(Math.max(portrait ? 560 : 1200, Math.min(portrait ? 1194 : 2600, H * vw / vh)));
    const L = { portrait, W, H, u: portrait ? 1.6 : 2.4, cell: portrait ? 18 : 24, uiStep: 3, dot: portrait ? 1.5 : 1.7 };
    if (portrait) {
      L.orb = { cx: W / 2, cy: 440, R: Math.min(188, W * 0.23) };
      L.mini = { cx: 58, cy: 50, R: 12 };
      const size = Math.min(176, Math.floor((W - 80) / 2.9));
      L.clock = { size, x: W / 2, base: 850, align: 'center', step: 5, dot: 2.1, max: W - 80 };
      L.meta = { left: 40, top: 890, width: W - 80 };
      L.name = { size: 150, x: 40, base: 420, max: W - 80, step: 5, dot: 2 };
      L.check = { cx: W / 2, cy: 500, k: 0.72, label: 46, ly: 760, step: 3 };
      L.boot = { S: { x: W / 2, y: 560 }, R: 190, init: 56, gap: 76, word: 21, wordGap: 16, markTop: 532, line: 120, glint: 420 };
    } else {
      L.orb = { cx: Math.round(W * 0.27), cy: 548, R: 250 };
      L.mini = { cx: 94, cy: 62, R: 15 };
      const x = Math.round(W * 0.526);
      const size = Math.min(300, Math.floor((W - x - 76) / 2.8));
      L.clock = { size, x, base: 640, align: 'left', step: Math.max(5, Math.round(size / 43)), dot: 2.6 * size / 300, max: W - x - 72 };
      L.meta = { left: x + 6, top: 684, width: W - x - 80 };
      L.name = { size: 230, x: 120, base: 430, max: W - 240, step: 6, dot: 2.3 };
      L.check = { cx: W / 2, cy: 450, k: 1, label: 64, ly: 790, step: 3 };
      L.boot = { S: { x: W / 2, y: 520 }, R: 230, init: 80, gap: 104, word: 30, wordGap: 24, markTop: 480, line: 180, glint: 700 };
    }
    return L;
  }
  let L = layout();
  let E = null;

  function fitBoard() {
    board.style.width = L.W + 'px';
    board.style.height = L.H + 'px';
    const vw = window.innerWidth || L.W, vh = window.innerHeight || L.H;
    const s = Math.min(vw / L.W, vh / L.H);
    const ox = Math.max(0, (vw - L.W * s) / 2), oy = Math.max(0, (vh - L.H * s) / 2);
    board.style.transform = 'translate(' + ox.toFixed(1) + 'px,' + oy.toFixed(1) + 'px) scale(' + s.toFixed(5) + ')';
    board.classList.toggle('cs-portrait', L.portrait);
    board.classList.toggle('cs-land', !L.portrait);
    const meta = $('meta');
    meta.style.left = L.meta.left + 'px';
    meta.style.top = L.meta.top + 'px';
    meta.style.width = L.meta.width + 'px';
  }
  function driftAt(t) { return { x: Math.sin(t * 0.021) * 14 + Math.sin(t * 0.0071) * 6, y: Math.cos(t * 0.017) * 10 }; }
  function makeEngine() {
    if (E) E.destroy();
    E = window.CliveDots.create({
      canvas: $('dots'), bloom: weak ? null : $('bloom'), fx: $('fx'), root: board, W: L.W, H: L.H, L,
      density: weak ? 7000 : 14000, speed: 1, calm, drift: driftAt, onTick,
      // The screens' own colours (the approved CLIVE Screens design): steel and white, never the app's lilac.
      palette: 'steel',
    });
  }

  // ---- small helpers --------------------------------------------------------------------
  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function svg(paths, sw) {
    const NS = 'http://www.w3.org/2000/svg';
    const s = document.createElementNS(NS, 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('fill', 'none');
    s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', String(sw || 1.6));
    s.setAttribute('stroke-linecap', 'round');
    s.setAttribute('stroke-linejoin', 'round');
    s.setAttribute('aria-hidden', 'true');
    for (const d of paths) {
      if (d.circle) {
        const c = document.createElementNS(NS, 'circle');
        c.setAttribute('cx', d.circle[0]); c.setAttribute('cy', d.circle[1]); c.setAttribute('r', d.circle[2]);
        s.appendChild(c);
      } else if (d.rect) {
        const r = document.createElementNS(NS, 'rect');
        r.setAttribute('x', d.rect[0]); r.setAttribute('y', d.rect[1]); r.setAttribute('width', d.rect[2]);
        r.setAttribute('height', d.rect[3]); r.setAttribute('rx', d.rect[4] || 0);
        s.appendChild(r);
      } else {
        const p = document.createElementNS(NS, 'path');
        p.setAttribute('d', d);
        s.appendChild(p);
      }
    }
    return s;
  }
  const ICON_CHECK = ['m5 12.5 4.5 4.5L19 7.5'];
  const ICON_CIRCLE_CHECK = [{ circle: [12, 12, 9] }, 'm8.5 12.2 2.4 2.4 4.6-5'];
  const ICON_GIFT = [{ rect: [3, 8, 18, 13, 2] }, 'M12 8v13', 'M3 12h18', 'M12 8c-1.5-3-5-3.5-5-1.2C7 8 9.5 8 12 8c2.5 0 5 0 5-1.2C17 4.5 13.5 5 12 8z'];
  const ICON_HANGER = ['M10.2 5.6a1.8 1.8 0 1 1 2.6 1.6c-.5.3-.8.7-.8 1.2V9', 'M12 9 3.6 15c-.8.6-.4 1.7.6 1.7h15.6c1 0 1.4-1.1.6-1.7L12 9z'];
  function pad(n) { return String(n).padStart(2, '0'); }
  function hhmm(d) { return pad(d.getHours()) + ':' + pad(d.getMinutes()); }
  const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  function dateText(d) { return DAYS[d.getDay()] + ' ' + d.getDate() + ' ' + MONTHS[d.getMonth()]; }
  function when(iso) {
    const d = new Date(iso || '');
    if (isNaN(d.getTime())) return '';
    const today = new Date();
    const y = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
    if (d.toDateString() === today.toDateString()) return 'today at ' + hhmm(d);
    if (d.toDateString() === y.toDateString()) return 'yesterday at ' + hhmm(d);
    return d.getDate() + ' ' + MONTHS[d.getMonth()].slice(0, 3) + ' at ' + hhmm(d);
  }
  function timeOf(iso) {
    const d = new Date(iso || '');
    return isNaN(d.getTime()) ? '' : hhmm(d);
  }
  function words(s) { return String(s || '').toLowerCase().replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()); }
  const later = (sec, fn) => { if (E) E.at(E.time() + sec, fn); };
  const afterPaint = (fn) => requestAnimationFrame(() => requestAnimationFrame(fn));

  // ---- what a push says it is ---------------------------------------------------------
  function keyOf(s) { return s ? [s.kind, s.ref, s.at, s.title].join('|') : ''; }
  // Round 9: a screen shows one thing or two side by side (panes). What is drawn is known by
  // the keys of its panes, in order.
  function layoutKey(list) { return list.map((w) => keyOf(w.view)).join('||'); }
  // Now, by CLIVE's clock (each answer says what it is), so a device whose own clock is wrong
  // neither keeps a slip too long nor takes one down as soon as it arrives.
  function serverNow() { return Date.now() + S.skew; }
  // Older than CLIVE keeps anything up, counted from when it was put up (round 8,
  // NEW-B-LOCAL-SLIP): taken down here even if CLIVE is never heard from again. A time that
  // cannot be read counts as too old, as it does on the server. Each pane by its own time.
  function tooOld(s) {
    const at = Date.parse((s && s.at) || '');
    return isNaN(at) || serverNow() - at > SHOW_KEEP_MS;
  }
  function drawnKeys() { return (S.drawnView || []).map((P) => P.key); }
  // One pane CLIVE says is up, if it is still to be shown here.
  function wantedPane(s) {
    if (!s) return null;
    if (tooOld(s)) return null;
    if (s.done_at && serverNow() - Date.parse(s.done_at) > DONE_HOLD_MS) return null;
    // Once done, CLIVE keeps only what was done, not the slip (the customer's details go). The
    // screen that drew it shows that done summary for a moment (markedDone); one that never drew
    // it rests.
    if (s.done_at && drawnKeys().indexOf(keyOf(s)) === -1) return null;
    return s;
  }
  // What a pane marked done may show (round 10, B2-04): CLIVE's done summary — its kind, the
  // order's number (a list is just "List"), when it was put up and when it was done — and not a
  // field more, whatever else came with it. Never the slip this screen drew.
  function doneOf(view) {
    const out = {};
    for (const k of ['kind', 'ref', 'title', 'at', 'by', 'v', 'done_at']) if (view && view[k] !== undefined) out[k] = view[k];
    return out;
  }
  // Every pane to show, each with its place on CLIVE's side (0 the first, 1 the one beside it):
  // the place and the pane's own version are what a page, a tick and "done" name.
  function wanted() {
    const out = [];
    [S.showing, S.beside].forEach((s, i) => { const view = wantedPane(s); if (view) out.push({ view, index: i }); });
    return out;
  }
  function whatOf(list) {
    return list.map((w) => w.view.title || (w.view.kind === 'order' ? 'the order' : 'this')).join(' and ');
  }
  function pageOf(view) { return Number.isInteger(view && view.page) && view.page >= 0 ? view.page : 0; }
  function ticksOf(view) { return new Set(Array.isArray(view && view.ticked) ? view.ticked.filter((n) => Number.isInteger(n)) : []); }
  // A pane as drawn here: what it shows, and its own pages and acknowledgements (B-04).
  function freshPage() {
    return { index: 0, pages: 1, seen: new Set([0]), total: 0, fill: null, per: 0, step: 1, box: null, more: null, note: null, count: null };
  }
  function paneOf(w) {
    const packed = !!w.view.done_at;
    return {
      index: w.index, view: packed ? doneOf(w.view) : w.view, key: keyOf(w.view), packed, two: false, node: null, btn: null,
      v: typeof w.view.v === 'number' ? w.view.v : S.version, serverPage: pageOf(w.view),
      page: freshPage(),
      ack: { version: -1, per: 0, covered: 0, busy: false, timer: 0, fails: 0, run: 0 },
    };
  }

  // ---- drawing what CLIVE put here ------------------------------------------------------
  function topBar(panes) {
    const top = el('div', 'cs-top');
    const left = el('div', 'cs-top-l');
    left.appendChild(el('span', 'cs-slot'));
    left.appendChild(el('span', '', S.screen ? S.screen.name : ''));
    top.appendChild(left);
    const latest = panes.map((P) => P.view.at || '').sort().pop();
    const at = timeOf(latest);
    top.appendChild(el('div', '', at ? 'Put up by CLIVE at ' + at : 'Put up by CLIVE'));
    return top;
  }
  function countBlock(n, label, cls) {
    const c = el('div', 'cs-count' + (cls ? ' ' + cls : ''));
    c.appendChild(el('span', 'cs-count-n', n));
    c.appendChild(el('span', 'cs-count-l', label));
    return c;
  }
  // A long title is set smaller; beside another pane (round 9) there is half the width for it.
  function headBlock(title, subParts, count, two) {
    const head = el('div', 'cs-head');
    const left = el('div', 'cs-head-l');
    const h1 = el('h1', 'cs-h1' + (String(title).length > (two ? 16 : 22) ? ' is-long' : ''), title);
    left.appendChild(h1);
    if (subParts.length) {
      const sub = el('div', 'cs-sub');
      for (const part of subParts) sub.appendChild(part);
      left.appendChild(sub);
    }
    head.appendChild(left);
    if (count) head.appendChild(count);
    return head;
  }
  function doneFoot(label, doneText) {
    const foot = el('div', 'cs-foot');
    const done = el('div', 'cs-done');
    done.appendChild(svg(ICON_CHECK, 2));
    done.appendChild(document.createTextNode(doneText));
    foot.appendChild(done);
    const chip = el('div', 'cs-donechip', label);
    chip.setAttribute('data-dot', 'good');
    foot.appendChild(chip);
    return foot;
  }
  function noteFoot(note) {
    const foot = el('div', 'cs-foot');
    const left = el('div', 'cs-foot-l');
    left.appendChild(svg(ICON_CIRCLE_CHECK, 1.6));
    left.appendChild(document.createTextNode(note));
    foot.appendChild(left);
    return foot;
  }
  function actionFoot(P, note, label) {
    const foot = el('div', 'cs-foot');
    const left = el('div', 'cs-foot-l');
    left.appendChild(svg(ICON_CIRCLE_CHECK, 1.6));
    left.appendChild(document.createTextNode(note));
    foot.appendChild(left);
    const btn = el('button', 'cs-btn', label);
    btn.type = 'button';
    btn.setAttribute('data-dot', 'btn');
    btn.addEventListener('click', (event) => markDone(P, event));
    foot.appendChild(btn);
    P.btn = btn;
    return foot;
  }
  const PAYMENT = { PAID: 'Paid', PARTIALLY_PAID: 'Part paid', PENDING: 'Payment pending', AUTHORIZED: 'Authorised', REFUNDED: 'Refunded', PARTIALLY_REFUNDED: 'Part refunded', VOIDED: 'Voided', EXPIRED: 'Payment expired' };
  function toSendOf(item) {
    if (typeof item.to_send === 'number') return item.to_send;
    return typeof item.quantity === 'number' ? item.quantity : 0;
  }
  // What is left to go in the box: the units of every item still to send that the owner has not
  // ticked (round 9), or the lines of a list not crossed off.
  function leftOf(P) {
    const v = P.view, ticks = ticksOf(v);
    if (v.kind === 'list') {
      const lines = (v.list && Array.isArray(v.list.lines)) ? v.list.lines : [];
      return lines.filter((line, i) => !ticks.has(i)).length;
    }
    const items = v.order && Array.isArray(v.order.items) ? v.order.items : [];
    return items.reduce((n, it, i) => n + (ticks.has(i) ? 0 : Math.max(0, toSendOf(it))), 0);
  }
  function leftCount(P) {
    const n = leftOf(P);
    if (P.view.kind === 'list') return [String(n), n === 1 ? 'thing to do' : 'things to do'];
    return [String(n), n === 1 ? 'item to pack' : 'items to pack'];
  }
  // The count at the head, kept up to date as the owner ticks.
  function showLeft(P) {
    const c = P.page.count;
    if (!c || P.packed) return;
    const [n, label] = leftCount(P);
    const num = c.querySelector('.cs-count-n'), said = c.querySelector('.cs-count-l');
    if (num) num.textContent = n;
    if (said) said.textContent = label;
  }
  function renderOrder(P) {
    const v = P.view, packed = P.packed, PAGE = P.page;
    const o = v.order || {};
    const frag = document.createDocumentFragment();
    const items = Array.isArray(o.items) ? o.items : [];
    const sub = [];
    const bits = [o.customer, o.placed_at ? 'placed ' + when(o.placed_at) : ''].filter(Boolean);
    if (bits.length) sub.push(el('span', '', bits.join(' · ')));
    const pay = String(o.payment || '').toUpperCase();
    if (pay) {
      const chip = el('span', 'cs-chip' + (pay === 'PAID' ? ' is-good' : ' is-warn'), PAYMENT[pay] || words(pay));
      chip.setAttribute('data-dot', pay === 'PAID' ? 'good' : 'chip');
      sub.push(chip);
    }
    for (const tag of (o.tags || []).slice(0, P.two ? 1 : 2)) {
      const chip = el('span', 'cs-chip', tag);
      chip.setAttribute('data-dot', 'chip');
      sub.push(chip);
    }
    const left = leftCount(P);
    const count = packed ? countBlock('Packed', 'at ' + timeOf(v.done_at), 'is-done') : countBlock(left[0], left[1]);
    PAGE.count = count;
    frag.appendChild(headBlock(v.title || 'Order', sub, count, P.two));

    const cols = el('div', 'cs-cols');
    const ship = el('section', 'cs-panel');
    ship.setAttribute('data-dot', 'panel');
    ship.appendChild(el('h2', 'cs-h2', 'Ship to'));
    if (o.customer) ship.appendChild(el('div', 'cs-to', o.customer));
    if (o.company) ship.appendChild(el('div', 'cs-addr', o.company));
    const addr = el('div', 'cs-addr');
    for (const line of (o.address || [])) addr.appendChild(el('div', '', line));
    if (!(o.address || []).length) addr.appendChild(el('div', 'cs-empty', 'No address on the order'));
    ship.appendChild(addr);
    if (o.phone) ship.appendChild(el('div', 'cs-phone', o.phone));
    if (o.shipping_method) ship.appendChild(el('div', 'cs-method', o.shipping_method));
    if (o.note) {
      const note = el('div', 'cs-note');
      note.setAttribute('data-dot', 'note');
      const first = String(o.customer || '').split(' ')[0];
      const label = el('span', 'cs-note-k');
      label.appendChild(svg(ICON_GIFT, 2));
      label.appendChild(document.createTextNode(first ? 'Note from ' + first : 'Note on the order'));
      note.appendChild(label);
      note.appendChild(document.createTextNode(o.note));
      ship.appendChild(note);
    }
    cols.appendChild(ship);

    const box = el('section', 'cs-panel');
    box.setAttribute('data-dot', 'panel');
    const head = el('h2', 'cs-h2', 'In the box');
    box.appendChild(head);
    const list = el('div', 'cs-items');
    // A page is what fits the panel: five dense rows, in two columns when the screen is wide —
    // fewer once it is on the screen if a long address or a note leaves less room (fitPage).
    // Beside another pane (round 9) the panel is narrower: four rows, one column.
    const two = !L.portrait && !P.two && items.length > 6;
    if (items.length > (L.portrait || P.two ? 3 : 4)) list.classList.add('is-dense');
    if (two) list.classList.add('is-two');
    // More items than fit are shown a page at a time, and "Mark packed" waits until every page
    // has been on the screen: nobody attests to a box they were shown half of (round 6, B-04).
    PAGE.index = 0; PAGE.per = P.two ? 4 : L.portrait ? 5 : 10; PAGE.step = two ? 2 : 1; PAGE.box = list;
    PAGE.pages = Math.max(1, Math.ceil(items.length / PAGE.per)); PAGE.seen = new Set(); PAGE.total = items.length;
    PAGE.fill = (index) => {
      PAGE.index = index;
      PAGE.seen.add(index);
      list.textContent = '';
      itemRows(P, list, items.slice(index * PAGE.per, (index + 1) * PAGE.per), index * PAGE.per);
      head.textContent = PAGE.pages > 1
        ? 'In the box · ' + (index * PAGE.per + 1) + '–' + Math.min(items.length, (index + 1) * PAGE.per) + ' of ' + items.length
        : 'In the box';
      showLeft(P);
      pageControls(P);
      lockPacked(P);
    };
    box.appendChild(list);
    cols.appendChild(box);
    frag.appendChild(cols);

    const where = S.screen ? S.screen.name.toLowerCase() : 'this screen';
    // More items than a screen takes (views.MAX_ITEMS): shown as far as it goes, and never
    // marked packed from here — the server refuses it too (round 6, B-04).
    const partial = !!o.partial && !packed;
    const foot = packed
      ? doneFoot('Packed', 'Packed at ' + timeOf(v.done_at) + ' on the ' + where + '. CLIVE has noted it.')
      : partial
        ? noteFoot('This order has ' + (o.total_items || 'more') + ' items, more than a screen shows. Check it off in Shopify.')
        : actionFoot(P, 'CLIVE notes who packed it and when.', 'Mark packed');
    if (!packed && !partial) PAGE.note = { el: foot.querySelector('.cs-foot-l'), one: 'CLIVE notes who packed it and when.', many: 'Show every item, then mark it packed.' };
    pageButton(P, foot, 'Next items');
    frag.appendChild(foot);
    PAGE.fill(startPage(P));
    return frag;
  }
  // The page a pane opens on: the one the owner's remote turned to (round 9), else the first.
  function startPage(P) { return P.serverPage % Math.max(1, P.page.pages); }
  // Which page of a long order is up, and which have been — per pane (round 9). `per` shrinks by
  // `step` (a row, or two in two columns) until a page fits `box` as drawn.
  function resetPage(P) { P.page.box = null; P.page.more = null; P.page.note = null; P.page.count = null; P.btn = null; }
  // The page button shows only when there is more than one page, and the foot's words say which.
  function pageControls(P) {
    const PAGE = P.page;
    if (PAGE.more) {
      PAGE.more.hidden = PAGE.pages <= 1;
      PAGE.more.textContent = (PAGE.index + 1) % PAGE.pages === 0 && PAGE.pages > 1 ? 'Back to the first' : PAGE.more.dataset.label;
    }
    if (PAGE.note && PAGE.note.el) {
      const icon = PAGE.note.el.firstChild;
      PAGE.note.el.textContent = '';
      if (icon) PAGE.note.el.appendChild(icon);
      PAGE.note.el.appendChild(document.createTextNode(PAGE.pages > 1 ? PAGE.note.many : PAGE.note.one));
    }
  }
  // Once the page is on the screen: if its rows do not all fit the panel, fewer to a page, and
  // the count of pages (and so what must be seen before "Mark packed") grows with it.
  function fitPage(P) {
    const PAGE = P.page, box = PAGE.box;
    if (!box || !PAGE.fill) return;
    for (let guard = 0; guard < 30 && PAGE.per > PAGE.step && box.scrollHeight > box.clientHeight + 2; guard++) {
      PAGE.per -= PAGE.step;
      PAGE.pages = Math.max(1, Math.ceil(PAGE.total / PAGE.per));
      PAGE.seen = new Set();
      PAGE.fill(startPage(P));
    }
  }
  // The control that turns the page, beside the foot's own button so it never covers a row. The
  // turn is told to CLIVE too, so the owner's remote shows the same page (round 9).
  function pageButton(P, foot, label) {
    const PAGE = P.page;
    const more = el('button', 'cs-page', label);
    more.type = 'button';
    more.dataset.label = label;
    more.hidden = PAGE.pages <= 1;
    more.setAttribute('data-dot', 'btn');
    more.addEventListener('click', (event) => {
      event.stopPropagation();
      PAGE.fill((PAGE.index + 1) % PAGE.pages);
      ackPage();
      tellPage(P, 1);
    });
    const main = foot.querySelector('.cs-btn, .cs-donechip');
    foot.insertBefore(more, main || null);
    PAGE.more = more;
  }
  function packedLocked(P) { return P.page.pages > 1 && P.page.seen.size < P.page.pages; }
  // The pages put up, told to CLIVE (rounds 7 and 8, B-04): "done" is taken only once CLIVE has
  // heard that every item of the pane's version was on this screen. CLIVE takes them in order
  // from the first item, a page at a time, each carrying on from the last, and no sooner than a
  // second apart; so they are sent that way — the next page only once it has been up here, the
  // next only after CLIVE took this one, and again after the wait a too_soon answer names. Each
  // pane is told on its own, under its own version (round 9).
  function ackReset(P) {
    const ACK = P.ack;
    clearTimeout(ACK.timer);
    ACK.run++;
    ACK.timer = 0; ACK.version = -1; ACK.per = 0; ACK.covered = 0; ACK.busy = false; ACK.fails = 0;
  }
  function acksHeard(P) { return P.ack.version === P.v && P.ack.per === P.page.per && P.ack.covered >= P.page.total; }
  // Every pane on the screen tells CLIVE the pages it has put up.
  function ackPage() { for (const P of S.drawnView || []) ackPane(P); }
  function ackPane(P) {
    const v = P.view, PAGE = P.page, ACK = P.ack;
    const ackLater = (ms) => {
      clearTimeout(ACK.timer);
      ACK.timer = setTimeout(() => { ACK.timer = 0; ackPane(P); }, Math.max(50, Math.min(10000, Number(ms) || 1000)));
    };
    if (!S.screen || S.phase !== 'shown' || P.packed || !v || (v.kind !== 'order' && v.kind !== 'list')) return;
    if (!S.drawnView || S.drawnView.indexOf(P) === -1) return;
    if (!PAGE.total || !PAGE.per || typeof P.v !== 'number' || P.v < 0) return;
    if (ACK.version !== P.v || ACK.per !== PAGE.per) {
      // Something new, or its pages laid out again (a resize): told again from the first item.
      ackReset(P);
      ACK.version = P.v; ACK.per = PAGE.per;
    }
    if (ACK.busy || ACK.timer) return;
    const start = ACK.covered;
    if (start >= PAGE.total || start % PAGE.per || !PAGE.seen.has(start / PAGE.per)) return;   // not up here yet
    const end = Math.min(PAGE.total, start + PAGE.per);
    // A wipe resets every drawn pane's count (ackReset), so an answer to a page told before it is
    // never read (round 10, B2-03).
    const run = ACK.run, screen = S.screen;
    ACK.busy = true;
    fetch('/displays/' + encodeURIComponent(screen.id) + '/seen', {
      method: 'POST', cache: 'no-store', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version: ACK.version, pane: P.index, start, end }),
    }).then(async (response) => {
      if (run !== ACK.run) return;
      ACK.busy = false;
      if (response.status === 403) { if (!(await notThisScreen(response, () => run !== ACK.run)) && run === ACK.run) wipe('refused'); return; }
      const data = await response.json().catch(() => ({}));
      if (run !== ACK.run) return;
      if (response.ok && typeof data.seen === 'number') { ACK.covered = data.seen; ACK.fails = 0; ackPane(P); return; }
      if (response.status === 409 && data.code === 'too_soon') { ackLater(data.retry_after_ms); return; }
      if (response.status === 409 && data.code === 'out_of_order' && typeof data.covered === 'number' && ++ACK.fails <= 3) {
        // CLIVE heard a different amount (a restart, a lost answer): carry on from what it has,
        // or from the first item if it has this screen's pages laid out another way.
        const next = data.size === ACK.per ? data.covered : 0;
        if (next !== start) { ACK.covered = next; ackPane(P); }
      }
      // Otherwise what is shown changed: the next ask brings it, and it is told afresh.
    }).catch(() => {
      if (run !== ACK.run) return;
      ACK.busy = false;
      ackLater(3000);   // told again shortly; done waits until it is
    });
  }
  // Every page of this pane heard, or false once `ms` has passed without it.
  function heardAll(P, ms) {
    const until = Date.now() + ms;
    return new Promise((resolve) => {
      const check = () => {
        if (acksHeard(P)) { resolve(true); return; }
        if (Date.now() >= until || S.phase !== 'shown' || !S.drawnView || S.drawnView.indexOf(P) === -1) { resolve(false); return; }
        ackPane(P);
        setTimeout(check, 200);
      };
      check();
    });
  }
  function lockPacked(P) {
    const btn = P.btn;
    if (!btn) return;
    const locked = packedLocked(P);
    btn.disabled = locked;
    btn.classList.toggle('is-locked', locked);
    btn.setAttribute('aria-disabled', locked ? 'true' : 'false');
  }
  // The check the owner's tick puts on a row (round 9): Apple blue, white stroke.
  function tickMark() {
    const tick = el('div', 'cs-tick');
    tick.setAttribute('data-dot', 'tick');
    tick.appendChild(svg(ICON_CHECK, 2.6));
    return tick;
  }
  function itemRows(P, list, items, offset) {
    const packed = P.packed, ticks = ticksOf(P.view);
    items.forEach((it, i) => {
      const n = toSendOf(it);
      const sent = n <= 0;
      // Ticked by the owner as it went in the box (round 9): a check, and the row dimmed.
      const ticked = !packed && !sent && ticks.has(offset + i);
      const row = el('div', 'cs-item' + (sent ? ' is-sent' : '') + (packed && !sent ? ' is-packed' : '') + (ticked ? ' is-ticked' : ''));
      row.setAttribute('data-dot', 'row');
      const tile = el('div', 'cs-tile');
      tile.setAttribute('data-dot', 'tile');
      tile.appendChild(svg(ICON_HANGER, 1.5));
      if (it.image && /^https:\/\//.test(it.image)) {
        const img = document.createElement('img');
        img.alt = '';
        img.decoding = 'async';
        img.referrerPolicy = 'no-referrer';
        img.src = it.image;
        img.addEventListener('error', () => img.remove());
        tile.appendChild(img);
      }
      row.appendChild(tile);
      const mid = el('div');
      mid.appendChild(el('div', 'cs-what', it.title || 'Item'));
      if (it.variant) mid.appendChild(el('div', 'cs-how', it.variant.replace(/ \/ /g, ' · ')));
      if (it.sku) mid.appendChild(el('div', 'cs-sku', it.sku));
      row.appendChild(mid);
      if (sent) {
        row.appendChild(el('div', 'cs-sentl', 'Sent'));
      } else {
        const qty = el('div', 'cs-qty', '×' + n);
        qty.setAttribute('data-dot', 'pill');
        row.appendChild(qty);
        if (ticked) row.appendChild(tickMark());
        if (!packed) tappable(P, row, offset + i);
      }
      list.appendChild(row);
    });
  }
  function renderList(P) {
    const v = P.view, packed = P.packed, PAGE = P.page;
    const lines = (v.list && Array.isArray(v.list.lines)) ? v.list.lines : [];
    const frag = document.createDocumentFragment();
    const left = leftCount(P);
    const count = packed ? countBlock('Done', 'at ' + timeOf(v.done_at), 'is-done') : countBlock(left[0], left[1]);
    PAGE.count = count;
    frag.appendChild(headBlock(v.title || 'List', [], count, P.two));
    const grid = el('div', 'cs-tasks' + (L.portrait || P.two || lines.length <= 4 ? ' is-one' : lines.length > 8 ? ' is-three' : ''));
    const max = P.two ? 6 : L.portrait ? 8 : 12;
    // As an order's items: a long list a page at a time, and done only once all of it was up.
    const pages = Math.max(1, Math.ceil(lines.length / max));
    const taskRows = (index) => {
      grid.textContent = '';
      const ticks = ticksOf(P.view);
      lines.slice(index * max, (index + 1) * max).forEach((line, i) => {
        // Crossed off by the owner (round 9): struck through, dimmed, and a check in its ring.
        const ticked = !packed && ticks.has(index * max + i);
        const row = el('div', 'cs-task' + (packed ? ' is-packed' : '') + (ticked ? ' is-ticked' : ''));
        row.setAttribute('data-dot', 'row');
        const n = el('span', 'cs-task-n', ticked ? '' : String(index * max + i + 1));
        if (ticked) n.appendChild(svg(ICON_CHECK, 2.6));
        n.setAttribute('data-dot', ticked ? 'tick' : 'ring');
        row.appendChild(n);
        row.appendChild(el('span', 'cs-task-t', line));
        if (!packed) tappable(P, row, index * max + i);
        grid.appendChild(row);
      });
      if (!lines.length) grid.appendChild(el('div', 'cs-empty', 'Nothing on this list'));
    };
    PAGE.index = 0; PAGE.per = max; PAGE.pages = pages; PAGE.seen = new Set(); PAGE.total = lines.length;
    PAGE.fill = (index) => { PAGE.index = index; PAGE.seen.add(index); taskRows(index); showLeft(P); pageControls(P); lockPacked(P); };
    frag.appendChild(grid);
    const foot = packed
      ? doneFoot('Done', 'Done at ' + timeOf(v.done_at) + '. CLIVE has noted it.')
      : actionFoot(P, pages > 1 ? 'Show every page, then mark it done.' : 'Ask CLIVE to change anything on it.', 'Mark done');
    if (pages > 1) pageButton(P, foot, 'Next page');
    frag.appendChild(foot);
    PAGE.fill(startPage(P));
    return frag;
  }
  function renderObjective(P) {
    const v = P.view;
    const g = v.objective || {};
    const frag = document.createDocumentFragment();
    const sub = [];
    if (g.deadline) {
      const d = new Date(g.deadline + 'T12:00:00');
      if (!isNaN(d.getTime())) sub.push(el('span', '', 'Due ' + dateText(d)));
    }
    let count = null;
    if (typeof g.days_left === 'number') {
      if (g.days_left > 0) count = countBlock(String(g.days_left), g.days_left === 1 ? 'day to go' : 'days to go');
      else if (g.days_left === 0) count = countBlock('Today', 'is the day');
      else count = countBlock(String(-g.days_left), -g.days_left === 1 ? 'day late' : 'days late', 'is-late');
    }
    frag.appendChild(headBlock(v.title || 'Objective', sub, count, P.two));
    const cols = el('div', 'cs-cols is-goal');
    const stack = el('div', 'cs-stack');
    const now = el('section', 'cs-panel is-now');
    now.setAttribute('data-dot', 'panel');
    const h2 = el('h2', 'cs-h2');
    const live = el('span', 'cs-live');
    live.setAttribute('data-dot', 'pill');
    h2.appendChild(live);
    h2.appendChild(document.createTextNode('Doing now'));
    now.appendChild(h2);
    now.appendChild(el('div', 'cs-nowt' + (g.doing ? '' : ' is-quiet'), g.doing || 'Nothing started yet'));
    stack.appendChild(now);
    const needs = (g.needs_you || []).map((t) => t).concat((g.blocked_by || []).map((t) => 'Blocked: ' + t));
    if (needs.length) {
      const panel = el('section', 'cs-panel is-needs');
      panel.setAttribute('data-dot', 'need');
      panel.appendChild(el('h2', 'cs-h2', 'Needs you'));
      for (const t of needs.slice(0, P.two ? 2 : 4)) panel.appendChild(el('div', 'cs-need', t));
      stack.appendChild(panel);
    }
    cols.appendChild(stack);
    const nextPanel = el('section', 'cs-panel');
    nextPanel.setAttribute('data-dot', 'panel');
    nextPanel.appendChild(el('h2', 'cs-h2', 'Next'));
    const next = el('div', 'cs-next');
    const steps = (g.next || []).slice(0, P.two ? 3 : 5);
    steps.forEach((t, i) => {
      const row = el('div', 'cs-step');
      row.setAttribute('data-dot', 'row');
      const n = el('span', 'cs-task-n', String(i + 1));
      n.setAttribute('data-dot', 'ring');
      row.appendChild(n);
      row.appendChild(el('span', 'cs-step-t', t));
      next.appendChild(row);
    });
    if (!steps.length) next.appendChild(el('div', 'cs-empty', 'Nothing waiting'));
    nextPanel.appendChild(next);
    cols.appendChild(nextPanel);
    frag.appendChild(cols);
    const foot = el('div', 'cs-foot');
    foot.appendChild(el('div', 'cs-foot-l', 'As of ' + timeOf(v.at) + '. Ask CLIVE to put it up again for the latest.'));
    frag.appendChild(foot);
    return frag;
  }
  // A video: where YouTube's player goes (the player itself lives beside the page, so that the
  // page can be drawn again without the video starting over: videoSync, below), and under it
  // its title, its channel and how long it is, and a word on how it is playing.
  function clockOf(sec) {
    const s = Math.max(0, Math.floor(Number(sec) || 0)), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return (h ? h + ':' + pad(m) : String(m)) + ':' + pad(s % 60);
  }
  function renderVideo(P) {
    const v = P.view, clip = (v.video && typeof v.video === 'object') ? v.video : {};
    const frag = document.createDocumentFragment();
    const wrap = el('div', 'cs-vwrap');
    const slot = el('div', 'cs-vslot');
    slot.setAttribute('data-dot', 'tile');
    wrap.appendChild(slot);
    P.slot = slot; P.vwrap = wrap;
    frag.appendChild(wrap);
    const meta = el('div', 'cs-vmeta');
    const left = el('div', 'cs-vmeta-l');
    left.appendChild(el('div', 'cs-vtitle', v.title || 'YouTube video'));
    const length = clip.live ? 'Live' : (Number.isInteger(clip.duration_s) && clip.duration_s > 0 ? clockOf(clip.duration_s) : '');
    left.appendChild(el('div', 'cs-vsub', [clip.channel, length, 'YouTube'].filter(Boolean).join(' · ')));
    meta.appendChild(left);
    const state = el('div', 'cs-vstate');
    P.vstate = state;
    meta.appendChild(state);
    frag.appendChild(meta);
    return frag;
  }
  // A pane marked packed (or done), for the moment it stays up (round 10, B2-04): drawn from the
  // done summary alone — the order's number, and when it was packed and where. Nobody's name,
  // address, phone or note, and not the items: those went when it was marked.
  function renderDone(P) {
    const v = P.view, order = v.kind === 'order';
    const word = order ? 'Packed' : 'Done', at = timeOf(v.done_at);
    const frag = document.createDocumentFragment();
    frag.appendChild(headBlock(v.title || (order ? 'Order' : 'List'), [], countBlock(word, at ? 'at ' + at : '', 'is-done'), P.two));
    const panel = el('section', 'cs-panel cs-donepanel');
    panel.setAttribute('data-dot', 'panel');
    const mark = el('div', 'cs-donemark');
    mark.setAttribute('data-dot', 'good');
    mark.appendChild(svg(ICON_CHECK, 2.4));
    panel.appendChild(mark);
    panel.appendChild(el('div', 'cs-donet', at ? word + ' at ' + at : word));
    frag.appendChild(panel);
    const where = S.screen ? S.screen.name.toLowerCase() : 'this screen';
    frag.appendChild(doneFoot(word, word + (at ? ' at ' + at : '') + ' on the ' + where + '. CLIVE has noted it.'));
    return frag;
  }
  function renderPane(P) {
    const box = el('section', 'cs-pane' + (P.view.kind === 'video' ? ' cs-vpane' : ''));
    box.setAttribute('data-pane', String(P.index));
    const v = P.view;
    box.appendChild(P.packed ? renderDone(P) : v.kind === 'order' ? renderOrder(P) : v.kind === 'objective' ? renderObjective(P)
      : v.kind === 'video' ? renderVideo(P) : renderList(P));
    P.node = box;
    return box;
  }
  // What is up, pane by pane: side by side on a landscape screen, one above the other on a
  // portrait one (round 9). A pane drawn again keeps the pages it has shown, when its pages are
  // laid out as before, so the other pane being marked done does not send it back to page one.
  function draw(panes) {
    const kept = (panes || []).map((P) => (P.page.fill ? { index: P.page.index, seen: new Set(P.page.seen), per: P.page.per } : null));
    while (ui.firstChild) ui.removeChild(ui.firstChild);
    for (const P of S.drawnView || []) resetPage(P);
    const two = !!panes && panes.length > 1;
    ui.classList.toggle('cs-two', two);
    if (!panes || !panes.length) { videoSync([]); return; }
    ui.appendChild(topBar(panes));
    const row = el('div', 'cs-panes');
    for (const P of panes) { P.two = two; row.appendChild(renderPane(P)); }
    ui.appendChild(row);
    panes.forEach((P, n) => {
      fitPage(P);
      const k = kept[n];
      if (k && k.per === P.page.per && P.page.fill) { P.page.seen = k.seen; P.page.fill(Math.min(k.index, P.page.pages - 1)); }
    });
    videoSync(panes);
  }
  function uiState(name) {
    ui.classList.remove('is-hidden', 'is-revealing', 'is-shown', 'is-dissolving');
    ui.classList.add(name);
    // A video comes in as the page is revealed and goes as it dissolves; it plays once shown.
    const seen = name === 'is-shown' || name === 'is-revealing';
    for (const Y of VIDEOS.values()) if (!Y.parked) Y.host.classList.toggle('is-in', seen);
    if (name === 'is-shown') for (const Y of VIDEOS.values()) if (!Y.parked) videoStart(Y);
  }

  // ---- where the dots go ----------------------------------------------------------------
  function offscreen() {
    const cv = document.createElement('canvas');
    cv.width = L.W; cv.height = L.H;
    return cv.getContext('2d', { willReadFrequently: true });
  }
  function clockTargets() {
    return window.CliveDots.textTargets(hhmm(new Date()), L.clock, L.W, L.H, { r: 238, g: 232, b: 255 }, 0.9, FAM);
  }
  function nameTargets(text) {
    const t = String(text || '').trim();
    if (!t) return window.CliveDots.textTargets('Office screen', L.name, L.W, L.H, { r: 170, g: 150, b: 220 }, 0.18, FAM);
    return window.CliveDots.textTargets(t, L.name, L.W, L.H, { r: 240, g: 234, b: 255 }, 0.92, FAM);
  }
  // The real page, drawn off screen from its live layout (panels, pills, every letter where the
  // browser put it) and sampled into dot targets that carry its colours.
  function sampleUi() {
    const R0 = board.getBoundingClientRect();
    const k = R0.width / L.W || 1;
    const c = offscreen();
    const box = (node) => {
      const r = node.getBoundingClientRect();
      return { x: (r.left - R0.left) / k, y: (r.top - R0.top) / k, w: r.width / k, h: r.height / k };
    };
    const opacityOf = (node) => {
      let op = 1;
      for (let e = node; e && e !== ui; e = e.parentElement) {
        const v = parseFloat(getComputedStyle(e).opacity);
        if (!isNaN(v)) op *= v;
      }
      return op;
    };
    const shape = (b, rad) => {
      c.beginPath();
      if (c.roundRect) c.roundRect(b.x, b.y, b.w, b.h, rad); else c.rect(b.x, b.y, b.w, b.h);
    };
    const fills = {
      panel: ['rgba(160,160,180,.09)', 'rgba(255,255,255,.34)'],
      row: ['rgba(150,150,170,.10)', null],
      // The design's own colours, so the dots arrive in the colours the page resolves into.
      pill: ['rgba(245,245,247,.9)', null],
      btn: ['rgba(0,113,227,.92)', null],
      good: ['rgba(48,209,88,.3)', 'rgba(48,209,88,.6)'],
      chip: ['rgba(160,160,180,.22)', null],
      note: ['rgba(255,255,255,.1)', 'rgba(255,255,255,.28)'],
      need: ['rgba(10,132,255,.16)', 'rgba(10,132,255,.55)'],
      warn: ['rgba(255,105,97,.12)', 'rgba(255,105,97,.5)'],
      ring: ['rgba(255,255,255,.1)', 'rgba(235,235,245,.4)'],
      tick: ['rgba(10,132,255,.95)', null],
      tile: ['rgba(120,118,140,.75)', 'rgba(255,255,255,.2)'],
    };
    const marked = ui.querySelectorAll('[data-dot]');
    for (let i = 0; i < marked.length; i++) {
      const node = marked[i];
      const f = fills[node.getAttribute('data-dot')];
      const b = box(node);
      if (!f || !b.w || !b.h) continue;
      const rad = Math.min(b.h / 2, b.w / 2, parseFloat(getComputedStyle(node).borderTopLeftRadius) || 0);
      c.globalAlpha = opacityOf(node);
      shape(b, rad);
      if (f[0]) { c.fillStyle = f[0]; c.fill(); }
      if (f[1]) { c.lineWidth = 2; c.strokeStyle = f[1]; c.stroke(); }
    }
    const walker = document.createTreeWalker(ui, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    let node = walker.nextNode();
    while (node) {
      const text = node.nodeValue || '';
      const parent = node.parentElement;
      if (parent && text.trim()) {
        const cs = getComputedStyle(parent);
        c.globalAlpha = opacityOf(parent);
        c.font = cs.fontStyle + ' ' + cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily;
        c.fillStyle = cs.color;
        c.textBaseline = 'alphabetic';
        const up = cs.textTransform === 'uppercase';
        const fs = parseFloat(cs.fontSize) || 16;
        const m = c.measureText('Hg');
        const asc = m.fontBoundingBoxAscent || fs * 0.8, dsc = m.fontBoundingBoxDescent || fs * 0.2;
        const clip = box(parent);
        for (let i = 0; i < text.length && i < 400; i++) {
          const ch = text[i];
          if (ch === ' ' || ch === '\n' || ch === '\t' || ch === ' ') continue;
          range.setStart(node, i);
          range.setEnd(node, i + 1);
          const r = range.getBoundingClientRect();
          if (!r.width) continue;
          const x = (r.left - R0.left) / k, y = (r.top - R0.top) / k, h = r.height / k;
          if (x > clip.x + clip.w + 2 || y > clip.y + clip.h + 2) continue;   // clipped by an ellipsis or a line clamp
          c.fillText(up ? ch.toUpperCase() : ch, x, y + (h - asc - dsc) / 2 + asc);
        }
      }
      node = walker.nextNode();
    }
    c.globalAlpha = 1;
    const img = c.getImageData(0, 0, L.W, L.H).data;
    const st = L.uiStep, out = [];
    for (let y = 1; y < L.H; y += st) {
      for (let x = 1; x < L.W; x += st) {
        const j = (y * L.W + x) * 4, a = img[j + 3];
        if (a < 14) continue;
        const f = a / 255;
        if (Math.random() > Math.pow(f, 1.6) * 1.6) continue;
        out.push({ x: x + (Math.random() - 0.5) * st * 0.7, y: y + (Math.random() - 0.5) * st * 0.7, r: img[j], g: img[j + 1], b: img[j + 2], a: Math.min(0.95, 0.3 + 0.7 * f), s: L.dot * (0.8 + 0.45 * f) });
      }
    }
    return out;
  }
  function checkTargets(label) {
    const c = offscreen(), k = L.check.k, cx = L.check.cx, cy = L.check.cy;
    c.lineCap = 'round'; c.lineJoin = 'round';
    c.strokeStyle = 'rgb(48,209,88)'; c.lineWidth = 56 * k;
    c.beginPath(); c.moveTo(cx - 150 * k, cy + 4 * k); c.lineTo(cx - 46 * k, cy + 108 * k); c.lineTo(cx + 162 * k, cy - 118 * k); c.stroke();
    c.lineWidth = 3 * k; c.strokeStyle = 'rgba(48,209,88,.55)';
    c.beginPath(); c.arc(cx, cy, 250 * k, 0, Math.PI * 2); c.stroke();
    c.fillStyle = '#ffffff'; c.textAlign = 'center'; c.textBaseline = 'alphabetic';
    c.font = '700 ' + L.check.label + 'px ' + FAM;
    c.fillText(label, cx, L.check.ly);
    const d = c.getImageData(0, 0, L.W, L.H).data, st = L.check.step, out = [];
    for (let y = 0; y < L.H; y += st) {
      for (let x = 0; x < L.W; x += st) {
        const j = (y * L.W + x) * 4, a = d[j + 3];
        if (a < 60) continue;
        out.push({ x: x + (Math.random() - 0.5) * st * 0.5, y: y + (Math.random() - 0.5) * st * 0.5, r: d[j], g: d[j + 1], b: d[j + 2], a: 0.55 + 0.4 * a / 255, s: L.dot * 1.15 });
      }
    }
    return out;
  }

  // ---- the sequences --------------------------------------------------------------------
  function settle() {
    S.busy = false;
    if (S.pending) { S.pending = false; reconcile(); }
  }
  // A pane drawn here that is past CLIVE's own limit (round 11, NEW-B-LOCAL-SLIP) takes the whole
  // screen down at once, as a refusal does (wipe): the page, the dots that drew it and what is
  // kept of it, whatever the screen is in the middle of — even mid-journey, mid-dissolve or
  // mid-pack, when an ordinary change would wait for the animation to end. A pane beside it that
  // is still within its time comes back from the next ask, which starts afresh.
  function expireDrawn() {
    if (!(S.drawnView || []).some((P) => tooOld(P.view))) return false;
    wipe('');
    return true;
  }
  function reconcile() {
    if (expireDrawn()) return;
    if (S.busy || !E) { S.pending = true; return; }
    const want = wanted();
    if (S.phase === 'idle') { if (want.length) push(want); return; }
    if (S.phase === 'shown') {
      if (!want.length) { clearScreen(); return; }
      if (layoutKey(want) !== S.drawnKey) { S.pending = true; clearScreen(); return; }
      // The same things as are drawn: one newly done, or put up afresh at another version (drawn
      // again), or only the owner's ticks and page turns, which change the page in place.
      for (let n = 0; n < want.length; n++) {
        const w = want[n], P = S.drawnView[n];
        // Looked at again once the check has been drawn, for anything that came with it.
        if (w.view.done_at && !P.packed) { S.pending = true; markedDone(P, w.view); return; }
        if (!w.view.done_at && typeof w.view.v === 'number' && w.view.v !== P.v) { S.pending = true; clearScreen(); return; }
      }
      want.forEach((w, n) => follow(S.drawnView[n], w));
    }
  }
  // The owner's ticks and page turns, from his remote (round 9), on a pane already drawn: the
  // rows are drawn again in place, with no journey, and a page he turned to goes up here (and is
  // acknowledged as the screen's own button would).
  function follow(P, w) {
    if (P.packed || P.index !== w.index) return;
    if (P.view.kind === 'video') {
      // What the owner asked of the video since (play, pause, a volume, a skip): applied once.
      P.view = w.view;
      const Y = VIDEOS.get(P.key);
      if (Y) videoApply(Y, w.view.player);
      return;
    }
    const was = ticksOf(P.view), now = ticksOf(w.view);
    const ticked = was.size !== now.size || [...now].some((n) => !was.has(n));
    const turned = pageOf(w.view) !== P.serverPage;
    P.view = w.view;
    if (turned) {
      P.serverPage = pageOf(w.view);
      if (P.page.fill) { P.page.fill(startPage(P)); ackPage(); }
    } else if (ticked && P.page.fill) {
      P.page.fill(P.page.index);
    }
  }
  function push(list) {
    S.busy = true;
    S.phase = 'forming';
    S.drawnKey = layoutKey(list);
    S.drawnView = list.map(paneOf);
    S.what = whatOf(list);
    draw(S.drawnView);
    uiState('is-hidden');
    idleEl.classList.add('is-out');
    hint('');
    const gen = S.gen;
    afterPaint(() => {
      if (!E || gen !== S.gen) return;   // taken down meanwhile (wipe): nothing is drawn from it
      const tg = sampleUi();
      const T0 = E.time();
      S.pushT0 = T0;
      E.push(tg);
      if (calm) {
        E.simulate(T0 + 4.8);
        E.sweepOut(E.time(), 0.01);
        S.phase = 'revealing'; uiState('is-revealing');
        later(0.6, () => { S.phase = 'shown'; uiState('is-shown'); status(false); ackPage(); settle(); });
        return;
      }
      status(true);
      scanEl.classList.remove('is-run');
      void scanEl.offsetWidth;
      scanEl.classList.add('is-run');
      E.at(T0 + 3.1, () => { E.sweepOut(T0 + 3.1, 1.3); S.phase = 'revealing'; uiState('is-revealing'); });
      E.at(T0 + 4.5, () => { S.phase = 'shown'; uiState('is-shown'); status(false); scanEl.classList.remove('is-run'); ackPage(); settle(); });
    });
  }
  // One pane marked done: the dots swirl into a check, and the page comes back with that pane in
  // its done state (the other, if any, as it was). What the pane showed of the customer goes the
  // moment CLIVE says it is done (round 10, B2-04): the copy drawn here, its pages and all, is
  // replaced by CLIVE's done summary, and the page is drawn again from that at once, before the
  // dots have moved. And the dots let go of the page they drew, now (round 11, B2-04): not one of
  // them keeps a place sampled from the slip, so none forms it again — the check comes out of
  // the orb (web/dots.js packOut), and the page they go back into is the done page, sampled anew.
  function markedDone(P, view) {
    S.busy = true;
    S.phase = 'packing';
    P.packed = true;
    P.view = doneOf(view);
    P.page = freshPage();
    if (E) E.forget();
    const label = (P.view.kind === 'order' ? 'Packed at ' : 'Done at ') + timeOf(P.view.done_at);
    if (calm) {
      draw(S.drawnView);
      S.phase = 'shown';
      settle();
      scheduleRest(P.view);
      return;
    }
    const T0 = E.time();
    E.packOut(checkTargets(label));
    uiState('is-dissolving');
    draw(S.drawnView);
    E.at(T0 + 2.3, () => E.packIn(sampleUi(), T0 + 2.6));
    E.at(T0 + 3.8, () => { E.sweepOut(T0 + 3.8, 1.3); uiState('is-revealing'); });
    E.at(T0 + 5.2, () => { S.phase = 'shown'; uiState('is-shown'); settle(); scheduleRest(P.view); });
  }
  function scheduleRest(v) {
    const left = DONE_HOLD_MS - (serverNow() - Date.parse(v.done_at || ''));
    setTimeout(reconcile, Math.max(1000, isNaN(left) ? DONE_HOLD_MS : left + 200));
  }
  function clearScreen() {
    S.busy = true;
    S.phase = 'clearing';
    status(false);
    const T0 = E.time();
    E.clear(clockTargets());
    const done = () => {
      for (const P of S.drawnView || []) ackReset(P);
      S.phase = 'idle'; S.drawnKey = ''; S.drawnView = null; settle();
    };
    if (calm) {
      E.simulate(T0 + 3.2);
      uiState('is-hidden');
      idleEl.classList.remove('is-out');
      later(0.5, () => { draw(null); done(); });
      return;
    }
    uiState('is-dissolving');
    E.at(T0 + 1.0, () => idleEl.classList.remove('is-out'));
    E.at(T0 + 1.3, () => { uiState('is-hidden'); draw(null); });
    E.at(T0 + 2.6, done);
  }
  function status(on) {
    statusEl.hidden = !on;
    if (on) { $('status-text').textContent = 'Putting up ' + S.what; $('status-pct').textContent = '0%'; }
  }
  function onTick() {
    if (statusEl.hidden || S.pushT0 === null || !E) return;
    const pct = Math.max(0, Math.min(100, Math.round((E.time() - S.pushT0) / 3.3 * 100)));
    $('status-pct').textContent = pct + '%';
  }

  // ---- marking it done here -------------------------------------------------------------
  let marking = false;
  async function markDone(P, event) {
    if (event) event.stopPropagation();
    if (marking || S.phase !== 'shown' || P.packed || !S.screen || !S.drawnView || S.drawnView.indexOf(P) === -1) return;
    const PAGE = P.page;
    if ((P.view.kind === 'order' || P.view.kind === 'list') && packedLocked(P)) {
      hint(P.view.kind === 'order' ? 'Show every item first: tap Next items.' : 'Show every page first: tap Next page.', true);
      return;
    }
    marking = true;
    const btn = event && event.currentTarget;
    if (btn) btn.disabled = true;
    // Whatever answers this tap is read only while nothing has been taken down since it was
    // made, on this same screen (round 10, B2-03).
    const stale = asked();
    try {
      const paged = (P.view.kind === 'order' || P.view.kind === 'list') && PAGE.total > 0;
      if (paged && !acksHeard(P)) {
        // The last pages may still be on their way to CLIVE, a second apart.
        hint('Telling CLIVE every page was shown…', false, 20000);
        if (!(await heardAll(P, 20000))) {
          if (!stale()) hint('CLIVE has not heard every page yet, so nothing was marked. Tap again.', true);
          return;
        }
        hint('');
      }
      for (let attempt = 0; attempt < 5; attempt++) {
        if (stale()) return;
        // `confirm` is sent from here, the Mark packed tap, and nowhere else (round 8, B-04). The
        // pane is named by its place and its own version (round 9). The screen's key goes with it
        // as its cookie (round 10, B2-01).
        const response = await fetch('/displays/' + encodeURIComponent(S.screen.id) + '/done', {
          method: 'POST', cache: 'no-store', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ version: P.v, pane: P.index, confirm: true }),
        });
        if (stale()) return;
        if (response.ok) {
          const data = await response.json();
          if (!stale()) receive(data);
          return;
        }
        if (await notThisScreen(response, stale)) return;
        if (response.status === 403) { wipe('refused'); return; }
        if (response.status === 503) {
          // Not yet safely kept (round 8, B-03), so not taken as done here: the screen shows
          // whatever CLIVE says it has on the next ask, and a tap again is answered once it is kept.
          hint('CLIVE could not save that yet. Tap again in a moment.', true);
          poll();
          return;
        }
        if (response.status !== 409) throw new Error('done ' + response.status);
        const why = await response.json().catch(() => ({}));
        if (stale()) return;
        if (why && why.code === 'too_soon') {
          await new Promise((resolve) => setTimeout(resolve, Math.max(50, Math.min(5000, Number(why.retry_after_ms) || 1000))));
          continue;
        }
        if (why && why.code === 'not_seen') {
          // CLIVE has not heard every page of this (a restart, a lost acknowledgement): show
          // them again, from this one; they are told again from the first item.
          PAGE.seen = new Set([PAGE.index]);
          pageControls(P);
          lockPacked(P);
          ackReset(P);
          ackPane(P);
          hint(PAGE.pages > 1 ? 'CLIVE needs to see every page again: tap through them, then mark it.' : 'Tap again.', true);
          return;
        }
        hint('This changed before the tap, so nothing was marked. Look again.', true);
        poll();
        return;
      }
      if (!stale()) hint('CLIVE is still busy with the last page, so nothing was marked. Tap again.', true);
    } catch (e) {
      if (!stale()) hint('CLIVE could not be reached, so nothing was marked. Tap again.', true);
    } finally {
      marking = false;
      if (btn) btn.disabled = packedLocked(P);
    }
  }

  // ---- ticks and pages from this screen too (round 9) -----------------------------------
  // The owner's remote ticks items and turns pages (web/remote.js); a screen that is touched —
  // a packing tablet — does the same through the same owner routes, so the two always agree.
  // A tick is his word that an item went in the box. It does not mark anything done: here that
  // is still the Mark packed tap, after every page (B-04).
  function tappable(P, row, item) {
    row.dataset.tick = String(item);
    row.addEventListener('click', (event) => { event.stopPropagation(); tickRow(P, item); });
  }
  let ticking = false;
  async function tickRow(P, item) {
    if (ticking || !S.screen || S.phase !== 'shown' || P.packed || !S.drawnView || S.drawnView.indexOf(P) === -1) return;
    ticking = true;
    const stale = asked();
    try {
      const response = await fetch('/displays/' + encodeURIComponent(S.screen.id) + '/remote/tick', {
        method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pane: P.index, item, packed: !ticksOf(P.view).has(item), version: P.v }),
      });
      if (stale()) return;
      if (response.status === 403) { wipe('refused'); return; }
      const data = await response.json().catch(() => ({}));
      if (stale()) return;
      if (response.ok && Array.isArray(data.ticked) && S.drawnView && S.drawnView.indexOf(P) !== -1 && !P.packed) {
        P.view = Object.assign({}, P.view, { ticked: data.ticked });
        if (P.page.fill) P.page.fill(P.page.index);
      }
    } catch (e) {
      if (!stale()) hint('CLIVE could not be reached, so that was not ticked. Tap again.', true);
    } finally {
      ticking = false;
    }
  }
  function tellPage(P, delta) {
    if (!S.screen || P.packed) return;
    const stale = asked();
    fetch('/displays/' + encodeURIComponent(S.screen.id) + '/remote/page', {
      method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pane: P.index, delta, version: P.v }),
    }).then(async (response) => {
      if (stale()) return;
      if (response.status === 403) { wipe('refused'); return; }
      const data = await response.json().catch(() => ({}));
      // What CLIVE now says the page is: the next ask brings the same, and changes nothing here.
      if (!stale() && response.ok && Number.isInteger(data.page)) P.serverPage = data.page;
    }).catch(() => { /* turned here; the remote catches up when CLIVE can be reached */ });
  }

  // ---- a video: YouTube, in YouTube's own player ----------------------------------------
  // The owner asked for a video (app/tools/display_tools.py screen_play). It plays in YouTube's
  // privacy-enhanced embedded player, built here from the video's id and nothing else CLIVE
  // sends. No script of YouTube's runs in this page: the player is spoken to with the messages
  // its own API sends (postMessage), and only messages from YouTube's player, from that frame,
  // are listened to. The player sits beside the page, over the place drawn for it, so drawing
  // the page again (the other pane packed, a resize) never starts it over.
  //
  // What the owner asks of it — from his remote, through CLIVE, or with the TV's own remote here
  // — is CLIVE's record (`player`: every command counted, skips added up, the last jump), and
  // each command is applied here exactly once. How it is actually playing is told back to CLIVE
  // every couple of seconds and at every change, for the remote and for CLIVE. A browser may
  // refuse to start a video with sound before anyone has pressed anything on the screen: then it
  // plays muted, says so, and the sound comes on at the first press of a button here.
  const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;
  const YT_EMBED = 'https://www.youtube-nocookie.com';
  const YT_ORIGINS = [YT_EMBED, 'https://www.youtube.com'];
  const YT_STATE = { '-1': 'unstarted', 0: 'ended', 1: 'playing', 2: 'paused', 3: 'buffering', 5: 'cued' };
  const VIDEO_POLL_MS = 700;           // asked this often while a video is up, so the remote feels immediate
  const REPORT_MS = 2000;              // how it is playing, told this often while it plays
  const REPORT_GAP_MS = 1000;          // and never more often than this
  const SOUND_WAIT_MS = 3500;          // started with sound and not playing by then: try it muted
  const PARK_MS = 9000;                // a video taken off the page is kept (paused) this long in case it comes back
  const LISTEN_MS = 250;
  const LISTEN_TRIES = 60;
  const MAX_SAID_S = 86400;            // the most CLIVE takes for a position or a length (store.py MAX_JUMP_S * 2)
  let videoSeq = 0;
  let pressed = false;                 // someone has pressed something on this screen since it was opened
  const whole = (n, d) => (Number.isInteger(n) ? n : d);

  function videoSend(Y, func, args) {
    if (!Y.ready) { Y.queue.push([func, args || []]); return; }
    try {
      Y.frame.contentWindow.postMessage(JSON.stringify({ event: 'command', func, args: args || [], id: Y.seq, channel: 'widget' }), YT_EMBED);
    } catch (e) { /* the player has gone; it is dropped with its pane */ }
  }
  function videoListen(Y) {
    clearInterval(Y.listen);
    let tries = 0;
    const hello = () => {
      if (Y.ready || tries++ >= LISTEN_TRIES || !Y.frame.contentWindow) { clearInterval(Y.listen); return; }
      try {
        Y.frame.contentWindow.postMessage(JSON.stringify({ event: 'listening', id: Y.seq, channel: 'widget' }), YT_EMBED);
      } catch (e) { /* not there yet */ }
    };
    hello();
    Y.listen = setInterval(hello, LISTEN_MS);
  }
  function videoMake(P) {
    const clip = (P.view.video && typeof P.view.video === 'object') ? P.view.video : {};
    const id = String(clip.id || P.view.ref || '');
    if (!VIDEO_ID.test(id)) return null;
    const start = Number.isInteger(clip.start) && clip.start > 0 ? Math.min(clip.start, 43200) : 0;
    const host = el('div', 'cs-vhost');
    const frame = document.createElement('iframe');
    frame.className = 'cs-vframe';
    frame.title = P.view.title || 'YouTube video';
    frame.setAttribute('allow', 'autoplay; encrypted-media; picture-in-picture');
    // YouTube's player needs to know which site embeds it (its error 153 otherwise): this origin only.
    frame.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
    // The TV's own remote talks to this page, not to the player.
    frame.setAttribute('tabindex', '-1');
    const query = ['enablejsapi=1', 'autoplay=0', 'controls=0', 'disablekb=1', 'fs=0', 'rel=0', 'playsinline=1',
      'iv_load_policy=3', 'origin=' + encodeURIComponent(location.origin || '')];
    if (start) query.push('start=' + start);
    frame.src = YT_EMBED + '/embed/' + encodeURIComponent(id) + '?' + query.join('&');
    host.appendChild(frame);
    const note = el('div', 'cs-vnote');
    note.hidden = true;
    host.appendChild(note);
    const p = (P.view.player && typeof P.view.player === 'object') ? P.view.player : {};
    const jump = p.jump && typeof p.jump === 'object' ? p.jump : null;
    const Y = {
      key: P.key, seq: ++videoSeq, id, host, frame, note, index: P.index, v: P.v, P, ready: false, queue: [], listen: 0,
      // What was asked of it before this screen drew it is where it starts, not history to replay.
      applied: { n: whole(p.n, 0), skip: whole(p.skip, 0), jump: jump ? whole(jump.n, 0) : 0 }, want: p,
      info: { state: -1, at: start, atT: Date.now(), duration: whole(clip.duration_s, 0), volume: null, muted: false },
      started: false, blocked: false, error: null, parked: 0, parkTimer: 0, soundTimer: 0, reportT: 0, reportTimer: 0,
    };
    frame.addEventListener('load', () => videoListen(Y));
    board.appendChild(host);
    return Y;
  }
  // The videos drawn now, each over the place drawn for it; one no longer drawn is paused and
  // kept a moment (the page is being laid out again around it), then dropped.
  function videoSync(panes) {
    const keep = new Set();
    for (const P of panes || []) {
      if (P.view.kind !== 'video') continue;
      let Y = VIDEOS.get(P.key);
      if (!Y) {
        Y = videoMake(P);
        if (!Y) continue;
        VIDEOS.set(P.key, Y);
      }
      if (Y.parked) { Y.parked = 0; clearTimeout(Y.parkTimer); Y.started = false; }
      Y.P = P; Y.index = P.index; Y.v = P.v;
      keep.add(P.key);
      videoFit(P);
      Y.host.classList.toggle('is-small', !!P.two);
      videoPlace(Y, P.slot);
      videoSay(Y);
    }
    for (const Y of VIDEOS.values()) {
      if (keep.has(Y.key) || Y.parked) continue;
      Y.parked = Date.now();
      Y.host.classList.remove('is-in');
      clearTimeout(Y.soundTimer);
      videoSend(Y, 'pauseVideo');
      Y.parkTimer = setTimeout(() => videoDrop(Y), PARK_MS);
    }
  }
  function videoDrop(Y) {
    clearInterval(Y.listen); clearTimeout(Y.parkTimer); clearTimeout(Y.soundTimer); clearTimeout(Y.reportTimer);
    if (Y.host.parentNode) Y.host.parentNode.removeChild(Y.host);
    VIDEOS.delete(Y.key);
  }
  function videoDropAll() { for (const Y of [...VIDEOS.values()]) videoDrop(Y); }
  // As large as the pane allows at 16:9, centred in it.
  function videoFit(P) {
    const w = P.vwrap ? P.vwrap.clientWidth : NaN, h = P.vwrap ? P.vwrap.clientHeight : NaN;
    if (!(w > 0) || !(h > 0)) return;
    const wide = w / h > 16 / 9;
    const height = (wide ? h : w * 9 / 16).toFixed(1) + 'px';
    P.slot.style.width = (wide ? h * 16 / 9 : w).toFixed(1) + 'px';
    P.slot.style.height = height;
    // The picture and its title stay together, in the middle of a pane taller than they are.
    P.vwrap.style.flex = '0 0 ' + height;
  }
  function videoPlace(Y, slot) {
    if (!slot) return;
    const R0 = board.getBoundingClientRect();
    const k = R0.width / L.W || 1;
    const r = slot.getBoundingClientRect();
    const s = Y.host.style;
    s.left = ((r.left - R0.left) / k).toFixed(1) + 'px';
    s.top = ((r.top - R0.top) / k).toFixed(1) + 'px';
    s.width = (r.width / k).toFixed(1) + 'px';
    s.height = (r.height / k).toFixed(1) + 'px';
  }
  function videoAt(Y) {
    const I = Y.info;
    return I.state === 1 ? I.at + (Date.now() - I.atT) / 1000 : I.at;
  }
  function videoReady(Y) {
    if (Y.ready) return;
    Y.ready = true;
    clearInterval(Y.listen);
    videoSend(Y, 'addEventListener', ['onStateChange']);
    videoSend(Y, 'addEventListener', ['onError']);
    for (const [func, args] of Y.queue.splice(0)) videoSend(Y, func, args);
    if (S.phase === 'shown' && !Y.parked) videoStart(Y);
  }
  // Shown: it plays (unless the owner paused it), at the volume he chose.
  function videoStart(Y) {
    if (!Y.ready || Y.started || Y.error !== null) return;
    Y.started = true;
    const p = Y.want || {};
    if (Number.isInteger(p.volume)) videoSend(Y, 'setVolume', [p.volume]);
    videoSend(Y, p.muted || Y.blocked ? 'mute' : 'unMute');
    if (p.paused) return;
    videoSend(Y, 'playVideo');
    clearTimeout(Y.soundTimer);
    Y.soundTimer = setTimeout(() => {
      // Not playing with sound: this browser wants a press on the screen first. Muted, it may.
      if (Y.parked || Y.error !== null || (Y.want || {}).paused || Y.info.state === 1 || Y.info.state === 3 || pressed) return;
      Y.blocked = true;
      videoSend(Y, 'mute');
      videoSend(Y, 'playVideo');
      videoSay(Y);
      videoReport(Y, true);
    }, SOUND_WAIT_MS);
  }
  // What the owner asked since the last command applied here: each command once.
  function videoApply(Y, p) {
    if (!p || typeof p !== 'object') return;
    const n = whole(p.n, 0);
    Y.want = p;
    if (n <= Y.applied.n) return;
    const jump = p.jump && typeof p.jump === 'object' ? p.jump : null;
    if (jump && whole(jump.n, 0) > Y.applied.jump) {
      const to = Math.max(0, whole(jump.to, 0));
      videoSend(Y, 'seekTo', [to, true]);
      Y.info.at = to; Y.info.atT = Date.now();
      Y.applied.jump = whole(jump.n, 0);
      Y.applied.skip = whole(jump.skip, Y.applied.skip);
    }
    const skip = whole(p.skip, 0) - Y.applied.skip;
    if (skip) {
      const to = Math.max(0, videoAt(Y) + skip);
      videoSend(Y, 'seekTo', [to, true]);
      Y.info.at = to; Y.info.atT = Date.now();
    }
    Y.applied.skip = whole(p.skip, 0);
    Y.applied.n = n;
    if (!Y.started) return;   // the rest is how it starts, once it is shown
    if (Number.isInteger(p.volume)) videoSend(Y, 'setVolume', [p.volume]);
    videoSend(Y, p.muted || Y.blocked ? 'mute' : 'unMute');
    videoSend(Y, p.paused ? 'pauseVideo' : 'playVideo');
  }
  function videoHeard(Y, info) {
    if (!info || typeof info !== 'object') return;
    const I = Y.info, was = I.state;
    if (typeof info.currentTime === 'number' && isFinite(info.currentTime)) { I.at = Math.max(0, info.currentTime); I.atT = Date.now(); }
    if (typeof info.duration === 'number' && isFinite(info.duration) && info.duration > 0) I.duration = info.duration;
    if (typeof info.volume === 'number' && isFinite(info.volume)) I.volume = Math.max(0, Math.min(100, Math.round(info.volume)));
    if (typeof info.muted === 'boolean') I.muted = info.muted;
    if (Number.isInteger(info.playerState) && YT_STATE[info.playerState] !== undefined) I.state = info.playerState;
    if (I.state !== was) { videoSay(Y); videoReport(Y, true); }
  }
  function videoFailed(Y, code) {
    Y.error = Number.isInteger(code) ? code : 5;
    clearTimeout(Y.soundTimer);
    videoSay(Y);
    videoReport(Y, true);
  }
  // The word under the video, and the note over it when it cannot play.
  function videoSay(Y) {
    const P = Y.P, e = Y.error;
    let note = '';
    if (e === 101 || e === 150 || e === 153) note = 'YouTube won’t let this video play outside YouTube. Ask CLIVE for another.';
    else if (e === 100) note = 'This video isn’t on YouTube any more.';
    else if (e !== null) note = 'YouTube couldn’t play this video.';
    Y.note.textContent = note;
    Y.note.hidden = !note;
    if (!P || !P.vstate) return;
    const st = Y.info.state;
    const said = e !== null ? 'Can’t play'
      : Y.blocked ? 'Sound off · press OK or tap the screen'
      : st === 2 ? 'Paused' : st === 0 ? 'Finished' : st === 3 ? 'Loading' : '';
    P.vstate.textContent = said;
    P.vstate.classList.toggle('is-bad', e !== null);
    P.vstate.classList.toggle('is-note', e === null && Y.blocked);
  }
  // How it is playing, told to CLIVE with this screen's key (its cookie, round 10): at every
  // change, and every couple of seconds while it plays, never more often than REPORT_GAP_MS.
  function videoReport(Y, now) {
    if (!S.screen || Y.parked || !Y.ready) return;
    const wait = REPORT_GAP_MS - (Date.now() - Y.reportT);
    if (wait > 0) {
      if (now && !Y.reportTimer) Y.reportTimer = setTimeout(() => { Y.reportTimer = 0; videoReport(Y, true); }, wait);
      return;
    }
    Y.reportT = Date.now();
    const I = Y.info;
    // A live stream's position is how long the stream has run (days, for some): it is not said.
    const live = !!(Y.P && Y.P.view.video && Y.P.view.video.live);
    const cap = (n) => Math.round(Math.min(MAX_SAID_S, Math.max(0, n)) * 10) / 10;
    const body = {
      pane: Y.index, version: Y.v, state: YT_STATE[I.state] || 'unstarted', at: live ? 0 : cap(videoAt(Y)),
      duration: !live && I.duration > 0 ? cap(I.duration) : null, volume: I.volume, muted: !!I.muted,
      blocked: !!Y.blocked, error: Y.error,
    };
    const stale = asked();
    fetch('/displays/' + encodeURIComponent(S.screen.id) + '/video', {
      method: 'POST', cache: 'no-store', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(async (response) => {
      if (stale()) return;
      if (await notThisScreen(response, stale)) return;
      if (response.status === 403) wipe('refused');
    }).catch(() => { /* told again at the next change or the next couple of seconds */ });
  }
  setInterval(() => {
    for (const Y of VIDEOS.values()) if (!Y.parked && Y.info.state === 1) videoReport(Y, false);
  }, REPORT_MS);
  window.addEventListener('message', (event) => {
    if (!event || YT_ORIGINS.indexOf(event.origin) === -1) return;
    let Y = null;
    for (const y of VIDEOS.values()) if (y.frame.contentWindow && event.source === y.frame.contentWindow) { Y = y; break; }
    if (!Y) return;
    let data = null;
    try { data = typeof event.data === 'string' ? JSON.parse(event.data) : null; } catch (e) { data = null; }
    if (!data || typeof data !== 'object') return;
    if (data.event === 'onReady') videoReady(Y);
    else if (data.event === 'initialDelivery' || data.event === 'infoDelivery') { if (!Y.ready) videoReady(Y); videoHeard(Y, data.info); }
    else if (data.event === 'onStateChange') videoHeard(Y, { playerState: data.info });
    else if (data.event === 'onError') videoFailed(Y, data.info);
  });
  // The first press of anything on this screen lets the sound come on (a browser's rule).
  function pressedHere() {
    if (pressed) return;
    pressed = true;
    for (const Y of VIDEOS.values()) {
      if (!Y.blocked) continue;
      Y.blocked = false;
      const p = Y.want || {};
      if (!p.muted) videoSend(Y, 'unMute');
      if (Number.isInteger(p.volume)) videoSend(Y, 'setVolume', [p.volume]);
      videoSay(Y);
      videoReport(Y, true);
    }
  }
  // The TV's own remote, while a video is up: OK plays and pauses, left and right skip ten
  // seconds, up and down are louder and quieter. Told to CLIVE like the owner's remote, so they
  // agree, and applied here from CLIVE's answer.
  function videoKeys(event) {
    pressedHere();
    if (!S.screen || S.phase !== 'shown' || !S.drawnView) return;
    const target = event.target;
    if (target && target.closest && target.closest('button, input, form')) return;
    const P = S.drawnView.find((x) => x.view.kind === 'video');
    const Y = P ? VIDEOS.get(P.key) : null;
    if (!Y || Y.parked) return;
    const k = event.key;
    let action = '', value = null;
    if (k === 'Enter' || k === ' ' || k === 'MediaPlayPause' || k === 'k') action = Y.info.state === 1 || Y.info.state === 3 ? 'pause' : 'play';
    else if (k === 'MediaPlay') action = 'play';
    else if (k === 'MediaPause' || k === 'MediaStop') action = 'pause';
    else if (k === 'ArrowRight' || k === 'MediaFastForward') { action = 'skip'; value = 10; }
    else if (k === 'ArrowLeft' || k === 'MediaRewind') { action = 'skip'; value = -10; }
    else if (k === 'ArrowUp') action = 'louder';
    else if (k === 'ArrowDown') action = 'quieter';
    if (!action) return;
    if (event.preventDefault) event.preventDefault();
    const body = { pane: Y.index, version: Y.v, action };
    if (value !== null) body.value = value;
    const stale = asked();
    fetch('/displays/' + encodeURIComponent(S.screen.id) + '/remote/video', {
      method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then(async (response) => {
      if (stale()) return;
      if (response.status === 403) { wipe('refused'); return; }
      const data = await response.json().catch(() => ({}));
      if (!stale() && response.ok && data && data.player && VIDEOS.get(Y.key) === Y) videoApply(Y, data.player);
    }).catch(() => { if (!stale()) hint('CLIVE couldn’t be reached, so that didn’t reach the video. Try again.', true); });
  }
  document.addEventListener('keydown', videoKeys);
  document.addEventListener('pointerdown', pressedHere);

  // ---- asking CLIVE what to show --------------------------------------------------------
  let pollTimer = 0, pollDelay = POLL_MS, polling = false;
  let newerBuild = false;             // CLIVE answered from a newer build than this page's
  function receive(data) {
    if (!data || typeof data !== 'object') return;
    const now = Date.parse(data.now || '');
    if (!isNaN(now)) S.skew = now - Date.now();
    if (data.name && S.screen && data.name !== S.screen.name) {
      S.screen.name = data.name;
      saveScreen(S.screen);
      $('bar-name').textContent = data.name;
    }
    if (data.pending) {
      // Waiting for the owner to approve this screen: nothing is shown on it (round 8, B-02). Its
      // version is not taken, so the first ask after approval is answered in full.
      S.version = -1;
      S.unapproved = true;
      S.showing = null;
      S.beside = null;
      S.lastDone = null;
      if (typeof data.code_expires_in === 'number') S.pairUntil = Date.now() + data.code_expires_in * 1000;
      if (S.phase === 'pairing') showCode();
      else if (S.phase !== 'boot') toPairing();
      return;
    }
    if (typeof data.version === 'number') S.version = data.version;
    const approvedNow = S.unapproved;
    S.unapproved = false;
    // A pane past CLIVE's own limit is not taken in at all, not even kept in memory (round 11), in
    // case CLIVE's answer still lists it; each pane by its own time, in its own place.
    const inTime = (s) => (s && typeof s === 'object' && !tooOld(s) ? s : null);
    S.showing = inTime(data.showing);
    S.beside = (data.showing && inTime(data.beside)) || null;
    S.lastDone = data.last_done || null;
    if (approvedNow && S.phase === 'pairing') { approved(); return; }
    reconcile();
  }
  function setOnline(on, refused) {
    S.online = on;
    S.refused = !!refused;
    $('online').classList.toggle('is-away', !on);
    showLine(true);
  }
  // Another device has since been named this screen, or this one's key (its cookie) was lost:
  // name it again. An answer to an ask made before a wipe (`stale`) is left alone.
  async function notThisScreen(response, stale) {
    if (response.status !== 403) return false;
    const data = await response.clone().json().catch(() => ({}));
    if (!data || data.code !== 'not_this_screen') return false;
    if (stale && stale()) return true;
    wipe('');
    forgetScreen(); S.screen = null; toNaming();
    return true;
  }
  // An ask of CLIVE's, and whether its answer may still be read (round 10, B2-03): not once what
  // was shown has been taken down since it was sent (wipe), nor once this device has become
  // another screen. So nothing an older answer carries — a slip, a tick, a page, a refusal — is
  // ever taken after a refusal or a clearing; only an ask sent since can put anything up again.
  function asked() {
    const gen = S.gen, screen = S.screen;
    return () => gen !== S.gen || screen !== S.screen;
  }
  // A screen named before round 10 kept its key on this device (B2-01). Before its first ask it
  // hands that key back to CLIVE, once, the way a screen has always named itself again
  // (X-Screen-Key, to /displays/register): CLIVE answers as it does any screen naming itself
  // again with its own key — the same screen, still approved (or, still waiting, with a new
  // code) — and sets the key as the cookie. A name that has since gone to another device, or a
  // key CLIVE no longer knows, is named again, as it would be today. The device's record lost the
  // key when this page read it (loadScreen, round 11); the key is in this page's memory alone,
  // and while CLIVE is away or refusing this login the hand-back is tried again from there, as an
  // ask would be. Reloaded before it gets through, the screen is named again (see loadScreen).
  let migrating = false;
  async function migrate() {
    if (migrating || !S.screen || !legacyKey) return;
    migrating = true;
    const screen = S.screen, key = legacyKey;
    try {
      const response = await fetch('/displays/register', {
        method: 'POST', cache: 'no-store', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Screen-Key': key },
        body: JSON.stringify({ name: screen.name }),
      });
      const data = await response.json().catch(() => ({}));
      if (S.screen !== screen) return;
      if (response.ok && data && SCREEN_ID.test(String(data.id || ''))) {
        legacyKey = '';
        S.screen = { id: data.id, name: typeof data.name === 'string' && data.name ? data.name : screen.name };
        saveScreen(S.screen);
        $('bar-name').textContent = S.screen.name;
        S.lastOk = Date.now();
        if (data.pending) {
          // Still waiting for the owner: the new code goes up as the ask says so (receive).
          S.unapproved = true;
          S.pairCode = /^\d{6}$/.test(String(data.code || '')) ? String(data.code) : '';
          S.pairUntil = Date.now() + (Number(data.code_expires_in) || 900) * 1000;
        }
        migrating = false;
        poll();
        return;
      }
      if (response.status === 403 && data && data.code !== 'not_this_screen') {
        // This login may not use CLIVE now: asked again now and then, the key kept until then.
        wipe('refused');
        if (S.online !== false || !S.refused) setOnline(false, true);
        pollTimer = setTimeout(poll, REFUSED_MS);
        return;
      }
      if (response.status >= 400 && response.status < 500) {
        // The name is another device's now, or CLIVE no longer knows this key: named again.
        wipe('');
        forgetScreen(); S.screen = null;
        toNaming(response.status === 409 && typeof data.detail === 'string' ? data.detail : '', screen.name);
        return;
      }
      throw new Error('register ' + response.status);
    } catch (e) {
      if (S.screen === screen) {
        if (S.online !== false || S.refused) setOnline(false);
        pollDelay = Math.min(POLL_MAX_MS, Math.round(pollDelay * 1.5));
        clearTimeout(pollTimer);
        pollTimer = setTimeout(poll, pollDelay);
      }
    } finally {
      migrating = false;
    }
  }
  async function poll() {
    clearTimeout(pollTimer);
    if (!S.screen || polling) return;
    // A screen named before round 10 hands its old key back first (B2-01) — for LEGACY_KEEP_MS at
    // most; after that the key is let go and the screen is named again, as a new one would be.
    if (legacyKey && Date.now() > legacyUntil) {
      const name = S.screen.name;
      wipe('');
      forgetScreen(); S.screen = null;
      toNaming('', name);
      return;
    }
    if (legacyKey) { migrate(); return; }
    polling = true;
    const stale = asked();
    const again = () => { if (S.screen) pollTimer = setTimeout(poll, pollDelay); };
    const ctl = typeof AbortController === 'function' ? new AbortController() : null;
    const giveUp = ctl ? setTimeout(() => ctl.abort(), POLL_TIMEOUT_MS) : 0;
    try {
      // The screen's key goes as its cookie, which the browser alone holds (round 10, B2-01).
      const response = await fetch('/displays/' + encodeURIComponent(S.screen.id) + '?v=' + S.version,
        { cache: 'no-store', credentials: 'same-origin', signal: ctl ? ctl.signal : undefined });
      // Sent before what was shown was taken down: not read at all, whatever it says, and asked
      // again afresh (round 10, B2-03).
      if (stale()) { again(); return; }
      if (response.status === 404) {
        // Removed by the owner, or a request for approval that ran out or was cancelled.
        const waiting = S.unapproved, was = S.screen ? S.screen.name : '';
        wipe('');
        forgetScreen(); S.screen = null;
        toNaming(waiting ? 'The code ran out or was cancelled before this screen was approved. Name it again for a new code.' : '', waiting ? was : '');
        return;
      }
      if (await notThisScreen(response, stale)) { if (stale()) again(); return; }
      if (response.status === 403) {
        // This screen's login may not use CLIVE now (round 8, NEW-B-LOCAL-SLIP): whatever it
        // shows goes at once, and it asks again now and then in case that changes.
        S.lastOk = Date.now();
        wipe('refused');
        if (S.online !== false || !S.refused) setOnline(false, true);
        pollTimer = setTimeout(poll, REFUSED_MS);
        return;
      }
      if (response.status !== 204 && !response.ok) throw new Error('poll ' + response.status);
      const data = response.status === 204 ? null : await response.json();
      if (stale()) { again(); return; }
      S.lastOk = Date.now();
      // CLIVE has been updated since this page was loaded: it reloads itself once it is resting
      // (the clock showing, nothing playing), so a screen left open across a deploy never needs
      // someone to reload it by hand. Never mid-slip and never mid-video.
      const build = response.headers && typeof response.headers.get === 'function' ? response.headers.get('X-Clive-Build') : '';
      if (build && BUILD && BUILD !== '__BUILD__' && build !== BUILD) newerBuild = true;
      if (newerBuild && S.phase === 'idle' && !VIDEOS.size && !S.drawnView) { location.reload(); return; }
      if (S.gone) { S.gone = ''; showLine(true); }
      if (S.online !== true) setOnline(true);
      // While a video is up the owner's remote is working it: asked more often, so it answers at once.
      pollDelay = VIDEOS.size ? VIDEO_POLL_MS : POLL_MS;
      if (data) receive(data);
    } catch (e) {
      if (!stale()) {
        if (S.online !== false || S.refused) setOnline(false);
        pollDelay = Math.min(POLL_MAX_MS, Math.round(pollDelay * 1.5));
      }
    } finally {
      clearTimeout(giveUp);
      polling = false;
    }
    again();
  }
  // Out of reach for OFFLINE_CLEAR_MS on end, however the asks are failing (refused, erroring or
  // hanging): what is shown is taken down (round 8, NEW-B-LOCAL-SLIP). And a slip past CLIVE's
  // own limit is taken down even while CLIVE answers "nothing new" — at once, and whatever the
  // screen is in the middle of (round 11, expireDrawn). Looked at every second, so either happens
  // within a second of its time.
  setInterval(() => {
    if (S.screen && !S.gone && Date.now() - S.lastOk >= OFFLINE_CLEAR_MS) wipe('offline');
    if (expireDrawn()) return;
    let old = false;
    if (S.showing && tooOld(S.showing)) { S.showing = null; old = true; }
    if (S.beside && tooOld(S.beside)) { S.beside = null; old = true; }
    if (old) reconcile();
  }, 1000);

  // ---- taking what is shown down, at once (round 8, NEW-B-LOCAL-SLIP) --------------------
  // A customer's details leave this screen the moment it may no longer show them — refused, out
  // of reach too long, or past CLIVE's own limit (expireDrawn). Nothing is animated away, and
  // nothing waits for an animation under way (a journey, a dissolve, a pack) to end: the page,
  // the dots that drew it (they carry its shapes and letters; the engine is destroyed, which
  // blanks its canvases and forgets every dot's place, web/dots.js) and what is kept of it in
  // memory go now, and the next ask starts afresh, so what comes back is only what CLIVE sends
  // again.
  function wipe(why) {
    const drawn = !!S.drawnView || ['forming', 'revealing', 'shown', 'packing', 'clearing'].indexOf(S.phase) !== -1;
    S.gen++;
    S.showing = null; S.beside = null; S.lastDone = null; S.version = -1;
    for (const P of S.drawnView || []) ackReset(P);
    draw(null);
    videoDropAll();
    S.drawnView = null; S.drawnKey = ''; S.what = '';
    uiState('is-hidden');
    status(false);
    scanEl.classList.remove('is-run');
    hint('');
    if (drawn) {
      makeEngine();
      if (E) E.idleNow(clockTargets());
      idleEl.classList.remove('is-out');
      S.phase = 'idle'; S.busy = false; S.pending = false;
    } else if (S.phase === 'pairing' && why) {
      // The code is not a customer's, but a screen that may not use CLIVE says that instead.
      pairEl.hidden = true;
      if (E) E.nameToOrb(clockTargets());
      idleEl.classList.remove('is-out');
      S.phase = 'idle'; S.busy = false; S.pending = false;
    }
    S.gone = why || '';
    showLine(true);
  }

  // ---- idle: the date and a line under the dot clock ------------------------------------
  let lineN = 0;
  function showLine(force) {
    const line = $('line');
    let text;
    if (S.gone === 'refused' || S.refused) text = 'This screen isn’t allowed to show CLIVE’s things any more.';
    else if (S.gone === 'offline') text = 'CLIVE can’t be reached, so this screen has taken down what it showed.';
    else if (S.online === false) text = 'CLIVE cannot be reached. Trying again.';
    else {
      const name = S.screen ? S.screen.name.toLowerCase() : 'this screen';
      const options = ['Waiting for CLIVE', 'Tell CLIVE: “put the next order on the ' + name + '”'];
      if (S.lastDone && S.lastDone.title) options.push('Last done here: ' + S.lastDone.title + ' at ' + timeOf(S.lastDone.at));
      text = options[lineN % options.length];
    }
    line.classList.toggle('is-gone', !!S.gone || S.refused);
    if (!force && line.textContent === text) return;
    line.textContent = text;
    line.classList.remove('is-new');
    void line.offsetWidth;
    line.classList.add('is-new');
  }
  function tick() {
    const now = new Date();
    $('date').textContent = dateText(now);
    const clock = hhmm(now);
    $('clock-said').textContent = 'The time is ' + clock;
    if (clock !== tick.last) {
      const first = tick.last === undefined;
      tick.last = clock;
      if (!first && S.phase === 'idle' && E) E.clockTo(clockTargets(), {});
    }
    const d = driftAt(Date.now() / 1000 + 1);
    idleEl.style.transform = 'translate(' + d.x.toFixed(2) + 'px,' + d.y.toFixed(2) + 'px)';
  }
  setInterval(tick, 1000);
  setInterval(() => { lineN++; showLine(false); }, LINE_MS);

  // ---- naming this screen ---------------------------------------------------------------
  const input = $('name-input'), saveBtn = $('name-save'), nameError = $('name-error'), replaceBtn = $('name-replace');
  let nameTimer = 0;
  function toNaming(note, name) {
    // Asked again while already asking (the start-up ending, a resize): what it said stays.
    const said = S.phase === 'naming' ? nameError.textContent : '';
    S.phase = 'naming';
    S.busy = true;
    S.unapproved = false; S.pairCode = '';
    uiState('is-hidden');
    draw(null);
    idleEl.classList.add('is-out');
    pairEl.hidden = true;
    namer.hidden = false;
    namer.classList.remove('is-leaving');
    if (name) { input.value = String(name).slice(0, 40); saveBtn.disabled = false; }
    replaceMode('');
    nameError.textContent = note || said || '';
    if (E) { E.nameIntro(); E.nameTo(nameTargets(input.value)); }
    setTimeout(() => { try { input.focus({ preventScroll: true }); } catch (e) { input.focus(); } }, 200);
  }
  function typed() {
    const value = input.value.slice(0, 40);
    saveBtn.disabled = !value.trim();
    // Making room (too many screens) is typing the name of the one to remove: the way stays open.
    if (replaceBtn.dataset.mode !== 'room') { nameError.textContent = ''; replaceBtn.hidden = true; }
    clearTimeout(nameTimer);
    nameTimer = setTimeout(() => { if (E && S.phase === 'naming') E.nameTo(nameTargets(value)); }, 80);
  }
  // The one button that removes a screen, in the two cases it is offered: a name already taken
  // ("replace": remove it and name this one that) and too many screens ("room": remove the one
  // typed, then name this one).
  function replaceMode(mode) {
    replaceBtn.dataset.mode = mode;
    replaceBtn.hidden = !mode;
    replaceBtn.textContent = mode === 'room' ? 'Remove that screen' : 'Remove the old screen and use this one';
  }
  input.addEventListener('input', typed);
  namer.addEventListener('click', (event) => {
    const pick = event.target && event.target.closest ? event.target.closest('[data-name]') : null;
    if (pick) { input.value = pick.getAttribute('data-name'); typed(); }
  });
  // A name another screen already has is never simply taken over (round 7, B-02): the owner
  // removes the old screen first — here, with one deliberate tap — which clears whatever it was
  // showing, and this device then gets a new screen of that name, with nothing on it. At the
  // most screens CLIVE keeps, nothing is removed to make room (round 8, NEW-B-CAP): the owner
  // names the one to remove and taps, then names this one.
  replaceBtn.addEventListener('click', async () => {
    const name = input.value.trim();
    if (!name) return;
    const room = replaceBtn.dataset.mode === 'room';
    replaceBtn.disabled = true;
    try {
      const response = await fetch('/displays/forget', {
        method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (room) {
        if (response.status === 404) { nameError.textContent = 'There is no screen called that. Type the name of one to remove.'; return; }
        if (!response.ok) throw new Error('forget ' + response.status);
        replaceMode('');
        input.value = '';
        typed();
        nameError.textContent = 'Removed ' + name + '. Now type this screen’s name.';
        return;
      }
      if (!response.ok && response.status !== 404) throw new Error('forget ' + response.status);
      replaceMode('');
      nameError.textContent = '';
      namer.requestSubmit ? namer.requestSubmit() : namer.dispatchEvent(new Event('submit', { cancelable: true }));
    } catch (e) {
      nameError.textContent = 'CLIVE could not remove the old screen. Try again.';
    } finally {
      replaceBtn.disabled = false;
    }
  });
  namer.addEventListener('submit', async (event) => {
    event.preventDefault();
    const name = input.value.trim();
    if (!name) { nameError.textContent = 'Type a name first, like office screen.'; return; }
    saveBtn.disabled = true;
    replaceMode('');
    try {
      // CLIVE sets the new screen's key as a cookie with its answer (round 10, B2-01): the answer
      // itself is read for the id, the name and the code, and nothing else of it is kept.
      const response = await fetch('/displays/register', {
        method: 'POST', cache: 'no-store', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      const data = await response.json().catch(() => ({}));
      if (response.status === 403) throw new Error('This screen’s login is not allowed to use CLIVE.');
      if (response.status === 409 && data.code === 'name_taken') {
        replaceMode('replace');
        throw new Error(data.detail || 'There is already a screen with that name.');
      }
      if (response.status === 409 && data.code === 'too_many_screens') {
        replaceMode('room');
        throw new Error(data.detail || 'CLIVE has as many screens as it keeps. Remove one first.');
      }
      if (!response.ok || !SCREEN_ID.test(String(data.id || ''))) throw new Error(data.detail || 'CLIVE did not take that name. Try another.');
      legacyKey = '';
      S.screen = { id: data.id, name: data.name || name };
      saveScreen(S.screen);
      $('bar-name').textContent = S.screen.name;
      S.version = -1;
      S.lastOk = Date.now();
      if (data.pending) {
        // Named, not yet a screen CLIVE shows things on: its code goes up (round 8, B-02).
        S.unapproved = true;
        S.pairCode = /^\d{6}$/.test(String(data.code || '')) ? String(data.code) : '';
        S.pairUntil = Date.now() + (Number(data.code_expires_in) || 900) * 1000;
        toPairing(true);
        poll();
        return;
      }
      namer.classList.add('is-leaving');
      setTimeout(() => { namer.hidden = true; }, 700);
      if (E) E.nameToOrb(clockTargets());
      idleEl.classList.remove('is-out');
      S.phase = 'idle';
      setTimeout(() => { settle(); poll(); }, calm ? 200 : 2200);
    } catch (e) {
      nameError.textContent = (e && e.message) || 'CLIVE could not be reached. Try again.';
      saveBtn.disabled = false;
    }
  });

  // ---- approving this screen (round 8, B-02) --------------------------------------------
  // The screen's name in dots, and beneath it the code the owner reads out to CLIVE. The code is
  // held in memory only; a page opened again while the screen is waiting asks CLIVE for a new
  // one, with the screen's own key (its cookie, round 10).
  function spaced(code) { const c = String(code || ''); return c.length === 6 ? c.slice(0, 3) + ' ' + c.slice(3) : c; }
  function saidName(name) {
    const n = String(name || '').trim().toLowerCase();
    return /\bscreen$/.test(n) ? n : n + ' screen';
  }
  function showCode() {
    const code = spaced(S.pairCode);
    $('pair-code').textContent = code || '··· ···';
    $('pair-say').textContent = code && S.screen
      ? 'Tell CLIVE: “approve the ' + saidName(S.screen.name) + ', code ' + code + '”'
      : 'Getting a code from CLIVE…';
    const mins = Math.max(1, Math.ceil((S.pairUntil - Date.now()) / 60000));
    $('pair-note').textContent = code
      ? 'The code works for ' + mins + (mins === 1 ? ' more minute' : ' more minutes') + '. Nothing is shown here until CLIVE approves it.'
      : '';
  }
  function toPairing(fromNaming) {
    const wasNaming = S.phase === 'naming';
    S.phase = 'pairing';
    S.busy = true;
    uiState('is-hidden');
    draw(null);
    idleEl.classList.add('is-out');
    if (fromNaming) {
      namer.classList.add('is-leaving');
      setTimeout(() => { namer.hidden = true; }, 700);
    } else {
      namer.hidden = true;
    }
    pairEl.hidden = false;
    pairEl.classList.remove('is-leaving');
    showCode();
    if (E && S.screen) {
      if (!wasNaming) E.nameIntro();
      E.nameTo(nameTargets(S.screen.name));
    }
    if (!S.pairCode) renewCode();
  }
  function approved() {
    S.unapproved = false;
    S.pairCode = '';
    pairEl.classList.add('is-leaving');
    setTimeout(() => { if (S.phase !== 'pairing') pairEl.hidden = true; }, 700);
    if (E) E.nameToOrb(clockTargets());
    idleEl.classList.remove('is-out');
    S.phase = 'idle';
    hint('Approved. CLIVE can put things on this screen now.', false, 8000);
    setTimeout(() => { if (S.phase === 'idle') { settle(); reconcile(); } }, calm ? 200 : 2200);
  }
  let renewing = false;
  async function renewCode() {
    if (renewing || !S.screen) return;
    renewing = true;
    const stale = asked();
    try {
      const response = await fetch('/displays/register', {
        method: 'POST', cache: 'no-store', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: S.screen.name }),
      });
      if (stale()) return;
      if (response.status === 403) { wipe('refused'); return; }
      const data = await response.json().catch(() => ({}));
      if (stale()) return;
      if (response.ok && S.screen && data.id === S.screen.id) {
        // The key CLIVE turned over is the cookie it set with this answer; nothing of it is kept here.
        if (data.pending && /^\d{6}$/.test(String(data.code || ''))) {
          S.pairCode = String(data.code);
          S.pairUntil = Date.now() + (Number(data.code_expires_in) || 900) * 1000;
        }
        if (S.phase === 'pairing') showCode();
        return;
      }
      if (response.status === 409 && data.code === 'name_taken') {
        // The name went to another request while this one lapsed: name this screen again.
        const was = S.screen ? S.screen.name : '';
        forgetScreen(); S.screen = null;
        toNaming(data.detail || '', was);
        return;
      }
      throw new Error('register ' + response.status);
    } catch (e) {
      if (S.phase === 'pairing') $('pair-say').textContent = 'CLIVE could not give this screen a code yet. Trying again.';
      setTimeout(() => { if (S.phase === 'pairing' && !S.pairCode) renewCode(); }, 5000);
    } finally {
      renewing = false;
    }
  }

  // ---- the start-up ---------------------------------------------------------------------
  // The whole sequence the first time this screen opens on a day, and after CLIVE has been
  // updated; otherwise just the name and its line.
  function startupKind() {
    const today = new Date().toDateString();
    let seen = null;
    try { seen = JSON.parse(localStorage.getItem(BOOT_KEY) || 'null'); } catch (e) { seen = null; }
    const full = !seen || seen.day !== today || seen.build !== BUILD;
    return full && !calm ? 'full' : 'quick';
  }
  function rememberStartup() {
    try { localStorage.setItem(BOOT_KEY, JSON.stringify({ day: new Date().toDateString(), build: BUILD })); } catch (e) { /* shown again next time */ }
  }
  const ACRONYM = [['C', 'OMPUTER'], ['L', 'ANGUAGE'], ['I', 'NTERFACE'], ['V', 'IRTUAL'], ['E', 'NVIRONMENT']];
  let rows = [];
  function buildMark() {
    for (const r of rows) r.remove();
    rows = [];
    const B = L.boot;
    const probe = offscreen();
    probe.font = '600 ' + B.init + 'px ' + FAM;
    const widths = ACRONYM.map((w) => probe.measureText(w[0]).width);
    const gap = B.init * 0.62;
    const total = widths.reduce((a, b) => a + b, 0) + gap * 4;
    let x = L.W / 2 - total / 2;
    const markXs = [];
    for (let i = 0; i < 5; i++) { markXs.push(x); x += widths[i] + gap; }
    probe.font = '500 ' + B.word + 'px ' + FAM;
    const block = widths[4] + B.wordGap + probe.measureText('NVIRONMENT').width + 10 * B.word * 0.34;
    const colX = L.W / 2 - block / 2;
    const top0 = B.markTop - 2 * B.gap;
    ACRONYM.forEach((w, i) => {
      const row = el('div', 'bt-row');
      row.style.left = colX + 'px';
      row.style.top = (top0 + i * B.gap) + 'px';
      row.dataset.col = colX + ',' + (top0 + i * B.gap);
      row.dataset.mark = markXs[i] + ',' + B.markTop;
      row.style.setProperty('--id', Math.round((0.55 + i * 0.13) * 1000) + 'ms');
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
      markEl.insertBefore(row, $('mark-line'));
      rows.push(row);
    });
    const line = $('mark-line');
    line.style.left = (L.W / 2 - B.line / 2) + 'px';
    line.style.top = (B.markTop + B.init * 1.6) + 'px';
    line.style.width = B.line + 'px';
    const wait = $('mark-wait');
    wait.style.top = (B.markTop + B.init * 1.6 + 26) + 'px';
    wait.style.fontSize = Math.round(B.word * 0.9) + 'px';
    return { markXs, widths };
  }
  function rowsTo(mark) {
    for (const row of rows) {
      const [x, y] = (mark ? row.dataset.mark : row.dataset.col).split(',').map(Number);
      row.style.left = x + 'px';
      row.style.top = y + 'px';
    }
  }
  function sampleInits(step, dot) {
    const R0 = board.getBoundingClientRect(), k = R0.width / L.W || 1;
    const c = offscreen();
    const range = document.createRange();
    return rows.map((row) => {
      const init = row.firstChild, node = init.firstChild, list = [];
      if (!node) return list;
      const cs = getComputedStyle(init);
      c.font = cs.fontStyle + ' ' + cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily;
      c.fillStyle = '#ffffff';
      c.textBaseline = 'alphabetic';
      const fs = parseFloat(cs.fontSize) || 16;
      const m = c.measureText('Hg');
      const asc = m.fontBoundingBoxAscent || fs * 0.8, dsc = m.fontBoundingBoxDescent || fs * 0.2;
      range.setStart(node, 0); range.setEnd(node, 1);
      const r = range.getBoundingClientRect();
      const x = (r.left - R0.left) / k, y = (r.top - R0.top) / k, h = r.height / k, w = r.width / k;
      c.clearRect(0, 0, L.W, L.H);
      c.fillText(node.nodeValue.charAt(0), x, y + (h - asc - dsc) / 2 + asc);
      const x0 = Math.max(0, Math.floor(x - 6)), y0 = Math.max(0, Math.floor(y - 6));
      const bw = Math.min(L.W - x0, Math.ceil(w + 12)), bh = Math.min(L.H - y0, Math.ceil(h + 12));
      if (bw <= 0 || bh <= 0) return list;
      const d = c.getImageData(x0, y0, bw, bh).data;
      for (let yy = 0; yy < bh; yy += step) {
        for (let xx = 0; xx < bw; xx += step) {
          if (d[(yy * bw + xx) * 4 + 3] > 90) list.push({ x: x0 + xx, y: y0 + yy, r: 240, g: 244, b: 252, a: 0.92, s: dot });
        }
      }
      return list;
    });
  }
  function startup() {
    const kind = startupKind();
    const geo = buildMark();
    const B = L.boot;
    const home = { cx: L.orb.cx, cy: L.orb.cy, R: L.orb.R };
    const markBox = { x0: geo.markXs[0], x1: geo.markXs[4] + geo.widths[4], y0: B.markTop, y1: B.markTop + B.init };
    const spec = {
      S: B.S, R: B.R, home, homeBody: 0, endTint: 0, markBox, quick: kind === 'quick',
      markTargets: () => [].concat(...sampleInits(L.portrait ? 2 : 3, L.portrait ? 1.6 : 2.1)),
      clock: clockTargets(), handoffAt: kind === 'quick' ? 1.25 : 6.0,
    };
    S.phase = 'boot'; S.busy = true;
    if (kind === 'quick') {
      rowsTo(true);
      markEl.className = 'bt-mark is-quick';
      afterPaint(() => {
        const T0 = E.time();
        E.quick(spec);
        E.at(T0 + 0.3, () => { markEl.className = 'bt-mark is-quick is-load'; });
        E.at(T0 + 1.25, () => { markEl.className = 'bt-mark is-quick is-load is-out'; });
        E.at(T0 + 2.2, finishStartup);
      });
      return;
    }
    markEl.className = 'bt-mark';
    afterPaint(() => {
      const tg = sampleInits(L.portrait ? 2 : 3, L.portrait ? 1.6 : 2.0);
      const R0 = board.getBoundingClientRect(), k = R0.width / L.W || 1;
      spec.rows = rows.map((row, i) => {
        const r = row.firstChild.getBoundingClientRect(), rr = row.getBoundingClientRect();
        const cx = (r.left + r.width / 2 - R0.left) / k, cy = (r.top + r.height / 2 - R0.top) / k;
        const [mx, my] = row.dataset.mark.split(',').map(Number);
        const rowTop = (rr.top - R0.top) / k;
        return { targets: tg[i] || [], col: { x: cx, y: cy }, mark: { x: mx + geo.widths[i] / 2, y: my + (cy - rowTop) }, left: (rr.left - R0.left) / k, right: (rr.right - R0.left) / k };
      });
      const U = L.u;
      spec.glints = spec.rows.map((r, i) => ({ t: 3.0 + i * 0.13, y: r.col.y, x0: r.left - U * 50, x1: r.right + U * 20, len: B.glint, xi: r.col.x }));
      const markCy = spec.rows.length ? spec.rows[0].mark.y : B.markTop + B.init / 2;
      spec.glints.push({ t: 5.15, y: markCy, x0: markBox.x0 - U * 60, x1: markBox.x1 + U * 60, len: B.glint * 1.3, xi: (markBox.x0 + markBox.x1) / 2 });
      const T0 = E.time();
      E.boot(spec);
      startupT0 = T0;
      E.at(T0 + 2.45, () => { markEl.className = 'bt-mark is-acro'; });
      E.at(T0 + 4.1, () => { markEl.className = 'bt-mark is-acro is-collapse'; });
      E.at(T0 + 4.35, () => { markEl.className = 'bt-mark is-acro is-collapse is-mark'; rowsTo(true); });
      E.at(T0 + 5.1, () => { markEl.className = 'bt-mark is-acro is-collapse is-mark is-load'; });
      E.at(T0 + 6.0, () => { markEl.className = 'bt-mark is-acro is-collapse is-mark is-load is-out'; });
      E.at(T0 + 6.9, finishStartup);
    });
  }
  let startupT0 = null;
  function finishStartup() {
    rememberStartup();
    startupT0 = null;
    markEl.className = 'bt-mark';
    rowsTo(false);
    if (!S.screen) { toNaming(); return; }
    $('bar-name').textContent = S.screen.name;
    if (S.unapproved) { toPairing(false); return; }
    idleEl.classList.remove('is-out');
    S.phase = 'idle';
    settle();
    reconcile();
    if (!fullscreenOn() && document.fullscreenEnabled) hint('Tap anywhere for full screen', false, 8000);
  }

  // ---- the room: full screen, awake, drawn to the screen's shape -------------------------
  function fullscreenOn() { return !!document.fullscreenElement; }
  let hintTimer = 0;
  function hint(text, warn, ms) {
    clearTimeout(hintTimer);
    hintEl.hidden = !text;
    hintEl.textContent = text || '';
    hintEl.classList.toggle('is-warn', !!warn);
    if (text) hintTimer = setTimeout(() => { hintEl.hidden = true; }, ms || 6000);
  }
  document.addEventListener('pointerdown', (event) => {
    if (S.phase === 'boot' && startupT0 !== null && E && E.time() < startupT0 + 5.2) { E.simulate(startupT0 + 5.3); return; }
    if (event.target && event.target.closest && event.target.closest('button, input, form, [data-tick]')) return;
    if (!fullscreenOn() && document.fullscreenEnabled && document.documentElement.requestFullscreen) {
      document.documentElement.requestFullscreen().catch(() => {});
      hint('');
    }
  });
  let wakeLock = null;
  async function stayAwake() {
    try {
      if ('wakeLock' in navigator && document.visibilityState === 'visible') wakeLock = await navigator.wakeLock.request('screen');
    } catch (e) { wakeLock = null; }
  }
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') { stayAwake(); poll(); }
  });
  let resizeTimer = 0;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      const next = layout();
      if (next.W === L.W && next.H === L.H) { fitBoard(); return; }
      L = next;
      fitBoard();
      makeEngine();
      // Straight to where things are, without the journey.
      if (S.phase === 'naming') { E.nameIntro(); E.nameTo(nameTargets(input.value)); return; }
      if (S.phase === 'pairing' && S.screen) { E.nameIntro(); E.nameTo(nameTargets(S.screen.name)); return; }
      if (S.drawnView && (S.phase === 'shown' || S.phase === 'forming' || S.phase === 'revealing' || S.phase === 'packing')) {
        draw(S.drawnView);
        ackPage();
        uiState('is-shown');
        status(false);
        const gen = S.gen;
        afterPaint(() => {
          if (gen !== S.gen) return;
          E.place(sampleUi()); S.phase = 'shown'; settle();
          ackPage();   // the pages as now laid out, told from the first item
        });
        return;
      }
      E.idleNow(clockTargets());
      if (S.phase !== 'idle') { markEl.className = 'bt-mark'; idleEl.classList.remove('is-out'); uiState('is-hidden'); draw(null); S.phase = 'idle'; }
      if (!S.screen) { toNaming(); return; }
      if (S.unapproved) { toPairing(false); return; }
      settle();
    }, 300);
  });

  // ---- go -------------------------------------------------------------------------------
  fitBoard();
  makeEngine();
  tick();
  showLine(true);
  if (S.screen) { $('bar-name').textContent = S.screen.name; poll(); }
  stayAwake();
  startup();
})();

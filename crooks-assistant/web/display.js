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
 */
'use strict';

(function () {
  const FAM = '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", system-ui, "Helvetica Neue", Helvetica, sans-serif';
  const POLL_MS = 2000;
  const POLL_MAX_MS = 10000;
  const REFUSED_MS = 15000;
  const DONE_HOLD_MS = 45000;          // a packed slip stays up this long, then the screen rests
  const LINE_MS = 6000;
  const KEY = 'clive.screen';
  const BOOT_KEY = 'clive.screen.startup';
  const $ = (id) => document.getElementById(id);
  const buildMeta = document.querySelector('meta[name="crooks-build"]');
  const BUILD = buildMeta ? buildMeta.getAttribute('content') || '' : '';
  const board = $('board'), ui = $('ui'), idleEl = $('idle'), namer = $('namer'), markEl = $('mark');
  const scanEl = $('scan'), statusEl = $('status'), hintEl = $('hint');
  let reduced = false;
  try { reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { reduced = false; }
  const weak = (navigator.hardwareConcurrency || 8) <= 4 || /[?&]lite\b/.test(location.search);
  const calm = reduced;
  if (calm) board.classList.add('is-calm');
  if (weak) $('bloom').hidden = true;

  // ---- what this device is --------------------------------------------------------------
  function loadScreen() {
    try {
      const raw = JSON.parse(localStorage.getItem(KEY) || 'null');
      if (raw && /^scr_[0-9a-f]{12}$/.test(raw.id) && typeof raw.name === 'string') return raw;
    } catch (e) { /* nothing kept */ }
    return null;
  }
  function saveScreen(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) { /* kept for this visit */ } }
  function forgetScreen() { try { localStorage.removeItem(KEY); } catch (e) { /* nothing kept */ } }

  const S = {
    screen: loadScreen(),
    version: -1,
    showing: null,
    lastDone: null,
    phase: 'boot',         // boot · naming · idle · forming · revealing · shown · packing · clearing
    busy: true,
    pending: false,
    drawnKey: '',
    drawnView: null,
    drawnPacked: false,
    online: null,
    refused: false,
    pushT0: null,
    what: '',
  };

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
  function wanted() {
    const s = S.showing;
    if (!s) return null;
    if (s.done_at && Date.now() - Date.parse(s.done_at) > DONE_HOLD_MS) return null;
    return s;
  }
  function whatOf(v) {
    if (!v) return '';
    return v.title || (v.kind === 'order' ? 'the order' : 'this');
  }

  // ---- drawing what CLIVE put here ------------------------------------------------------
  function topBar(v) {
    const top = el('div', 'cs-top');
    const left = el('div', 'cs-top-l');
    left.appendChild(el('span', 'cs-slot'));
    left.appendChild(el('span', '', S.screen ? S.screen.name : ''));
    top.appendChild(left);
    const at = timeOf(v.at);
    top.appendChild(el('div', '', at ? 'Put up by CLIVE at ' + at : 'Put up by CLIVE'));
    return top;
  }
  function countBlock(n, label, cls) {
    const c = el('div', 'cs-count' + (cls ? ' ' + cls : ''));
    c.appendChild(el('span', 'cs-count-n', n));
    c.appendChild(el('span', 'cs-count-l', label));
    return c;
  }
  function headBlock(title, subParts, count) {
    const head = el('div', 'cs-head');
    const left = el('div', 'cs-head-l');
    const h1 = el('h1', 'cs-h1' + (String(title).length > 22 ? ' is-long' : ''), title);
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
  function actionFoot(note, label) {
    const foot = el('div', 'cs-foot');
    const left = el('div', 'cs-foot-l');
    left.appendChild(svg(ICON_CIRCLE_CHECK, 1.6));
    left.appendChild(document.createTextNode(note));
    foot.appendChild(left);
    const btn = el('button', 'cs-btn', label);
    btn.type = 'button';
    btn.setAttribute('data-dot', 'btn');
    btn.addEventListener('click', markDone);
    foot.appendChild(btn);
    return foot;
  }
  const PAYMENT = { PAID: 'Paid', PARTIALLY_PAID: 'Part paid', PENDING: 'Payment pending', AUTHORIZED: 'Authorised', REFUNDED: 'Refunded', PARTIALLY_REFUNDED: 'Part refunded', VOIDED: 'Voided', EXPIRED: 'Payment expired' };
  function toSendOf(item) {
    if (typeof item.to_send === 'number') return item.to_send;
    return typeof item.quantity === 'number' ? item.quantity : 0;
  }
  function renderOrder(v, packed) {
    const o = v.order || {};
    const frag = document.createDocumentFragment();
    frag.appendChild(topBar(v));
    const items = Array.isArray(o.items) ? o.items : [];
    const units = items.reduce((n, it) => n + Math.max(0, toSendOf(it)), 0);
    const sub = [];
    const bits = [o.customer, o.placed_at ? 'placed ' + when(o.placed_at) : ''].filter(Boolean);
    if (bits.length) sub.push(el('span', '', bits.join(' · ')));
    const pay = String(o.payment || '').toUpperCase();
    if (pay) {
      const chip = el('span', 'cs-chip' + (pay === 'PAID' ? ' is-good' : ' is-warn'), PAYMENT[pay] || words(pay));
      chip.setAttribute('data-dot', pay === 'PAID' ? 'good' : 'chip');
      sub.push(chip);
    }
    for (const tag of (o.tags || []).slice(0, 2)) {
      const chip = el('span', 'cs-chip', tag);
      chip.setAttribute('data-dot', 'chip');
      sub.push(chip);
    }
    const count = packed
      ? countBlock('Packed', 'at ' + timeOf(v.done_at), 'is-done')
      : countBlock(String(units), units === 1 ? 'item to pack' : 'items to pack');
    frag.appendChild(headBlock(v.title || 'Order', sub, count));

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
      note.setAttribute('data-dot', 'warn');
      const first = String(o.customer || '').split(' ')[0];
      note.appendChild(el('span', 'cs-note-k', first ? 'Note from ' + first : 'Note on the order'));
      note.appendChild(document.createTextNode(o.note));
      ship.appendChild(note);
    }
    cols.appendChild(ship);

    const box = el('section', 'cs-panel');
    box.setAttribute('data-dot', 'panel');
    box.appendChild(el('h2', 'cs-h2', 'In the box'));
    const list = el('div', 'cs-items');
    const max = L.portrait ? 6 : 12;
    if (items.length > (L.portrait ? 3 : 4)) list.classList.add('is-dense');
    if (!L.portrait && items.length > 6) list.classList.add('is-two');
    for (const it of items.slice(0, max)) {
      const n = toSendOf(it);
      const sent = n <= 0;
      const row = el('div', 'cs-item' + (sent ? ' is-sent' : '') + (packed && !sent ? ' is-packed' : ''));
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
      }
      list.appendChild(row);
    }
    box.appendChild(list);
    if (items.length > max) box.appendChild(el('div', 'cs-more', '+ ' + (items.length - max) + ' more on the order. Ask CLIVE for the rest.'));
    cols.appendChild(box);
    frag.appendChild(cols);

    const where = S.screen ? S.screen.name.toLowerCase() : 'this screen';
    frag.appendChild(packed
      ? doneFoot('Packed', 'Packed at ' + timeOf(v.done_at) + ' on the ' + where + '. CLIVE has noted it.')
      : actionFoot('CLIVE notes who packed it and when.', 'Mark packed'));
    return frag;
  }
  function renderList(v, packed) {
    const lines = (v.list && Array.isArray(v.list.lines)) ? v.list.lines : [];
    const frag = document.createDocumentFragment();
    frag.appendChild(topBar(v));
    const count = packed
      ? countBlock('Done', 'at ' + timeOf(v.done_at), 'is-done')
      : countBlock(String(lines.length), lines.length === 1 ? 'thing to do' : 'things to do');
    frag.appendChild(headBlock(v.title || 'List', [], count));
    const grid = el('div', 'cs-tasks' + (L.portrait || lines.length <= 4 ? ' is-one' : lines.length > 8 ? ' is-three' : ''));
    const max = L.portrait ? 8 : 12;
    lines.slice(0, max).forEach((line, i) => {
      const row = el('div', 'cs-task' + (packed ? ' is-packed' : ''));
      row.setAttribute('data-dot', 'row');
      const n = el('span', 'cs-task-n', String(i + 1));
      n.setAttribute('data-dot', 'ring');
      row.appendChild(n);
      row.appendChild(el('span', 'cs-task-t', line));
      grid.appendChild(row);
    });
    if (!lines.length) grid.appendChild(el('div', 'cs-empty', 'Nothing on this list'));
    frag.appendChild(grid);
    frag.appendChild(packed
      ? doneFoot('Done', 'Done at ' + timeOf(v.done_at) + '. CLIVE has noted it.')
      : actionFoot(lines.length > max ? 'Showing ' + max + ' of ' + lines.length + '. Ask CLIVE for the rest.' : 'Ask CLIVE to change anything on it.', 'Mark done'));
    return frag;
  }
  function renderObjective(v) {
    const g = v.objective || {};
    const frag = document.createDocumentFragment();
    frag.appendChild(topBar(v));
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
    frag.appendChild(headBlock(v.title || 'Objective', sub, count));
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
      panel.setAttribute('data-dot', 'warn');
      panel.appendChild(el('h2', 'cs-h2', 'Needs you'));
      for (const t of needs.slice(0, 4)) panel.appendChild(el('div', 'cs-need', t));
      stack.appendChild(panel);
    }
    cols.appendChild(stack);
    const nextPanel = el('section', 'cs-panel');
    nextPanel.setAttribute('data-dot', 'panel');
    nextPanel.appendChild(el('h2', 'cs-h2', 'Next'));
    const next = el('div', 'cs-next');
    const steps = (g.next || []).slice(0, 5);
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
  function draw(v, packed) {
    while (ui.firstChild) ui.removeChild(ui.firstChild);
    if (!v) return;
    const node = v.kind === 'order' ? renderOrder(v, packed) : v.kind === 'objective' ? renderObjective(v) : renderList(v, packed);
    ui.appendChild(node);
  }
  function uiState(name) {
    ui.classList.remove('is-hidden', 'is-revealing', 'is-shown', 'is-dissolving');
    ui.classList.add(name);
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
      pill: ['rgba(170,130,232,.86)', null],
      btn: ['rgba(170,130,232,.9)', null],
      good: ['rgba(112,214,160,.32)', 'rgba(112,214,160,.6)'],
      chip: ['rgba(160,160,180,.22)', null],
      warn: ['rgba(255,212,138,.10)', 'rgba(255,212,138,.5)'],
      ring: [null, 'rgba(196,161,240,.7)'],
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
    c.strokeStyle = 'rgb(112,214,160)'; c.lineWidth = 56 * k;
    c.beginPath(); c.moveTo(cx - 150 * k, cy + 4 * k); c.lineTo(cx - 46 * k, cy + 108 * k); c.lineTo(cx + 162 * k, cy - 118 * k); c.stroke();
    c.lineWidth = 3 * k; c.strokeStyle = 'rgba(112,214,160,.6)';
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
  function reconcile() {
    if (S.busy || !E) { S.pending = true; return; }
    const want = wanted();
    if (S.phase === 'idle') { if (want) push(want); return; }
    if (S.phase === 'shown') {
      if (!want) { clearScreen(); return; }
      if (keyOf(want) !== S.drawnKey) { S.pending = true; clearScreen(); return; }
      if (want.done_at && !S.drawnPacked) { markedDone(want); return; }
    }
  }
  function push(v) {
    S.busy = true;
    S.phase = 'forming';
    S.drawnKey = keyOf(v); S.drawnView = v; S.drawnPacked = !!v.done_at;
    S.what = whatOf(v);
    draw(v, S.drawnPacked);
    uiState('is-hidden');
    idleEl.classList.add('is-out');
    hint('');
    afterPaint(() => {
      if (!E) return;
      const tg = sampleUi();
      const T0 = E.time();
      S.pushT0 = T0;
      E.push(tg);
      if (calm) {
        E.simulate(T0 + 4.8);
        E.sweepOut(E.time(), 0.01);
        S.phase = 'revealing'; uiState('is-revealing');
        later(0.6, () => { S.phase = 'shown'; uiState('is-shown'); status(false); settle(); });
        return;
      }
      status(true);
      scanEl.classList.remove('is-run');
      void scanEl.offsetWidth;
      scanEl.classList.add('is-run');
      E.at(T0 + 3.1, () => { E.sweepOut(T0 + 3.1, 1.3); S.phase = 'revealing'; uiState('is-revealing'); });
      E.at(T0 + 4.5, () => { S.phase = 'shown'; uiState('is-shown'); status(false); scanEl.classList.remove('is-run'); settle(); });
    });
  }
  function markedDone(v) {
    S.busy = true;
    S.phase = 'packing';
    S.drawnPacked = true;
    S.drawnView = v;
    const label = (v.kind === 'order' ? 'Packed at ' : 'Done at ') + timeOf(v.done_at);
    if (calm) {
      draw(v, true);
      S.phase = 'shown';
      settle();
      scheduleRest(v);
      return;
    }
    const T0 = E.time();
    E.packOut(checkTargets(label));
    uiState('is-dissolving');
    E.at(T0 + 0.6, () => draw(v, true));
    E.at(T0 + 2.3, () => E.packIn(sampleUi(), T0 + 2.6));
    E.at(T0 + 3.8, () => { E.sweepOut(T0 + 3.8, 1.3); uiState('is-revealing'); });
    E.at(T0 + 5.2, () => { S.phase = 'shown'; uiState('is-shown'); settle(); scheduleRest(v); });
  }
  function scheduleRest(v) {
    const left = DONE_HOLD_MS - (Date.now() - Date.parse(v.done_at || ''));
    setTimeout(reconcile, Math.max(1000, isNaN(left) ? DONE_HOLD_MS : left + 200));
  }
  function clearScreen() {
    S.busy = true;
    S.phase = 'clearing';
    status(false);
    const T0 = E.time();
    E.clear(clockTargets());
    if (calm) {
      E.simulate(T0 + 3.2);
      uiState('is-hidden');
      idleEl.classList.remove('is-out');
      later(0.5, () => { draw(null); S.phase = 'idle'; S.drawnKey = ''; settle(); });
      return;
    }
    uiState('is-dissolving');
    E.at(T0 + 1.0, () => idleEl.classList.remove('is-out'));
    E.at(T0 + 1.3, () => { uiState('is-hidden'); draw(null); });
    E.at(T0 + 2.6, () => { S.phase = 'idle'; S.drawnKey = ''; S.drawnView = null; S.drawnPacked = false; settle(); });
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
  async function markDone(event) {
    if (event) event.stopPropagation();
    if (marking || S.phase !== 'shown' || S.drawnPacked || !S.screen) return;
    marking = true;
    const btn = event && event.currentTarget;
    if (btn) btn.disabled = true;
    try {
      const response = await fetch('/displays/' + encodeURIComponent(S.screen.id) + '/done', {
        method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ version: S.version }),
      });
      if (response.ok) {
        receive(await response.json());
      } else if (response.status === 409) {
        hint('This changed before the tap, so nothing was marked. Look again.', true);
        poll();
        if (btn) btn.disabled = false;
      } else {
        throw new Error('done ' + response.status);
      }
    } catch (e) {
      hint('CLIVE could not be reached, so nothing was marked. Tap again.', true);
      if (btn) btn.disabled = false;
    } finally {
      marking = false;
    }
  }

  // ---- asking CLIVE what to show --------------------------------------------------------
  let pollTimer = 0, pollDelay = POLL_MS;
  function receive(data) {
    if (!data || typeof data !== 'object') return;
    if (typeof data.version === 'number') S.version = data.version;
    S.showing = data.showing || null;
    S.lastDone = data.last_done || null;
    if (data.name && S.screen && data.name !== S.screen.name) {
      S.screen.name = data.name;
      saveScreen(S.screen);
      $('bar-name').textContent = data.name;
    }
    reconcile();
  }
  function setOnline(on, refused) {
    S.online = on;
    S.refused = !!refused;
    $('online').classList.toggle('is-away', !on);
    showLine(true);
  }
  async function poll() {
    clearTimeout(pollTimer);
    if (!S.screen) return;
    try {
      const response = await fetch('/displays/' + encodeURIComponent(S.screen.id) + '?v=' + S.version, { cache: 'no-store' });
      if (response.status === 404) { forgetScreen(); S.screen = null; toNaming(); return; }
      if (response.status === 403) {
        if (S.online !== false || !S.refused) setOnline(false, true);
        pollTimer = setTimeout(poll, REFUSED_MS);
        return;
      }
      if (response.status !== 204 && !response.ok) throw new Error('poll ' + response.status);
      if (S.online !== true) setOnline(true);
      pollDelay = POLL_MS;
      if (response.status !== 204) receive(await response.json());
    } catch (e) {
      if (S.online !== false || S.refused) setOnline(false);
      pollDelay = Math.min(POLL_MAX_MS, Math.round(pollDelay * 1.5));
    }
    pollTimer = setTimeout(poll, pollDelay);
  }

  // ---- idle: the date and a line under the dot clock ------------------------------------
  let lineN = 0;
  function showLine(force) {
    const line = $('line');
    let text;
    if (S.refused) text = 'This screen’s login is not allowed to use CLIVE.';
    else if (S.online === false) text = 'CLIVE cannot be reached. Trying again.';
    else {
      const name = S.screen ? S.screen.name.toLowerCase() : 'this screen';
      const options = ['Waiting for CLIVE', 'Tell CLIVE: “put the next order on the ' + name + '”'];
      if (S.lastDone && S.lastDone.title) options.push('Last done here: ' + S.lastDone.title + ' at ' + timeOf(S.lastDone.at));
      text = options[lineN % options.length];
    }
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
  const input = $('name-input'), saveBtn = $('name-save'), nameError = $('name-error');
  let nameTimer = 0;
  function toNaming() {
    S.phase = 'naming';
    S.busy = true;
    uiState('is-hidden');
    draw(null);
    idleEl.classList.add('is-out');
    namer.hidden = false;
    namer.classList.remove('is-leaving');
    if (E) { E.nameIntro(); E.nameTo(nameTargets(input.value)); }
    setTimeout(() => { try { input.focus({ preventScroll: true }); } catch (e) { input.focus(); } }, 200);
  }
  function typed() {
    const value = input.value.slice(0, 40);
    saveBtn.disabled = !value.trim();
    nameError.textContent = '';
    clearTimeout(nameTimer);
    nameTimer = setTimeout(() => { if (E && S.phase === 'naming') E.nameTo(nameTargets(value)); }, 80);
  }
  input.addEventListener('input', typed);
  namer.addEventListener('click', (event) => {
    const pick = event.target && event.target.closest ? event.target.closest('[data-name]') : null;
    if (pick) { input.value = pick.getAttribute('data-name'); typed(); }
  });
  namer.addEventListener('submit', async (event) => {
    event.preventDefault();
    const name = input.value.trim();
    if (!name) { nameError.textContent = 'Type a name first, like office screen.'; return; }
    saveBtn.disabled = true;
    try {
      const response = await fetch('/displays/register', {
        method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      const data = await response.json().catch(() => ({}));
      if (response.status === 403) throw new Error('This screen’s login is not allowed to use CLIVE.');
      if (!response.ok || !data.id) throw new Error(data.detail || 'CLIVE did not take that name. Try another.');
      S.screen = { id: data.id, name: data.name || name };
      saveScreen(S.screen);
      $('bar-name').textContent = S.screen.name;
      namer.classList.add('is-leaving');
      setTimeout(() => { namer.hidden = true; }, 700);
      if (E) E.nameToOrb(clockTargets());
      idleEl.classList.remove('is-out');
      S.phase = 'idle';
      S.version = -1;
      setTimeout(() => { settle(); poll(); }, calm ? 200 : 2200);
    } catch (e) {
      nameError.textContent = (e && e.message) || 'CLIVE could not be reached. Try again.';
      saveBtn.disabled = false;
    }
  });

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
    if (event.target && event.target.closest && event.target.closest('button, input, form')) return;
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
      if (S.drawnView && (S.phase === 'shown' || S.phase === 'forming' || S.phase === 'revealing' || S.phase === 'packing')) {
        draw(S.drawnView, S.drawnPacked);
        uiState('is-shown');
        status(false);
        afterPaint(() => { E.place(sampleUi()); S.phase = 'shown'; settle(); });
        return;
      }
      E.idleNow(clockTargets());
      if (S.phase !== 'idle') { markEl.className = 'bt-mark'; idleEl.classList.remove('is-out'); uiState('is-hidden'); draw(null); S.phase = 'idle'; }
      if (!S.screen) { toNaming(); return; }
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

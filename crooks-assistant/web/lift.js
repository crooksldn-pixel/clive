/* Press, hold, and put it on a screen (round 12).
 *
 * George, 29 September: "i also suggest we add physical ways of displaying to devices, whether that
 * be dragging an order, email, order card or objective by holding and a 'displays screen
 * appearing' which you can drag and drop the item to display too."
 *
 * So: a still press on an order — its card, its row in a list, its workspace, the order an email
 * links to — or on an objective on the home lifts it under the finger, and a Displays tray rises
 * with each of his approved screens: its name, whether it is on, and what it shows now. He drags it
 * onto a screen and lets go; that screen shows it, and the tray settles away saying what went
 * where. Letting go anywhere else puts it back. Letting go where it lifted leaves the tray open, to
 * tap a screen instead; and the context-menu key (or Shift+F10) on a focused item opens the same
 * tray from the keyboard. An email or a customer has no view a screen draws
 * (app/displays/views.py), so holding one lifts nothing and says so in a line.
 *
 * The hold does not fight scrolling: it starts only after HOLD_MS of a press that has stayed within
 * a few pixels. A flick moves further than that first, or the browser takes it for a scroll and
 * cancels the pointer, and the press is forgotten; the list scrolls as it always did, and a quick
 * tap is still a tap. Once lifted, a move is the drag's and not a scroll's.
 *
 * The drop is one POST to the owner's own route, `/displays/{id}/show`, naming the conversation
 * and the record as its card carries it — kind and id, nothing else (app/routes/displays.py). The
 * server puts it up through the screen_show tool and the gate, so a record this conversation was
 * not shown is refused there whatever this page does (app/displays/put.py), and the words the tray
 * shows for any refusal are the server's.
 *
 * Nothing here reads what a card says beyond its number or title for the lifted chip, and nothing
 * is kept on the device. Every word goes onto the page as text, never as markup. The tray and the
 * chip live outside #app, so they are never in a copy of the screen (web/telemetry.js).
 */
'use strict';

(function (root) {
  // ---- the rules, as plain values and functions (tests/web/lift.test.js) --------------------
  const HOLD_MS = 350;              // a press held this still, this long, lifts
  const SLOP = { touch: 10, pen: 8, mouse: 5 };   // how far it may wander while it is being still
  const PICK_PX = 24;               // let go within this of where it lifted: the tray stays, to tap
  const SWALLOW_MS = 450;           // the click a lift's release makes is not a tap on the card
  const SCREENS_FRESH_MS = 10000;   // the list of screens asked for at most this often by a press
  const PUT_TIMEOUT_MS = 15000;     // the server's own limit on the read is 8 s (settings.py)
  const SETTLE_MS = 1900;           // the confirmation stays this long before the tray goes
  const SAY_MS = 2800;              // the line said for something a screen cannot show
  const ORDER_REF = /^gid:\/\/shopify\/Order\/\d+$/;
  const OBJECTIVE_REF = /^obj_[0-9a-f]{8}$/;
  const SCREEN_ID = /^scr_[0-9a-f]{12}$/;

  // What can be held, as the renderers mark it (web/ui.js, web/alpha.js). The nearest one to the
  // finger is the one meant: a row inside a card is the row.
  const ORDERS = '[data-kind="order"][data-ref], .card[data-type="order"][data-ref], .card[data-type="order_workspace"][data-ref]';
  const OBJECTIVES = '[data-objective]';
  const EMAILS = '[data-kind="email_thread"][data-ref], .card[data-type="email_thread"]';
  const CUSTOMERS = '[data-kind="customer"][data-ref], .card[data-type="customer"], .card[data-type="customer_workspace"]';
  const HOLDABLE = [ORDERS, OBJECTIVES, EMAILS, CUSTOMERS].join(',');
  // A control inside a card keeps its own press: a tab, a rail chip, a field, an approval surface.
  const FALLBACK_CONTROLS = 'button,[role="button"],[role="tab"],a[href],input,select,textarea,summary,label,.action-surface,.action-handle';

  const SAY = {
    email_thread: 'A screen shows orders and objectives, not emails.',
    customer: 'A screen shows orders and objectives, not customers.',
  };
  const LINKED = ' Hold the linked order to put that up.';

  // Whether a press has wandered far enough to be a scroll, a flick or a selection.
  function wandered(press, x, y) {
    return Math.hypot(x - press.x, y - press.y) > (SLOP[press.type] || SLOP.touch);
  }
  // What letting go means: on a screen, it goes there; where it lifted, the tray stays to tap one;
  // anywhere else, it goes back.
  function release(lift, x, y, over) {
    if (over && over.screen) return 'drop';
    if (over && over.cancel) return 'cancel';
    return Math.hypot(x - lift.x0, y - lift.y0) <= PICK_PX ? 'pick' : 'cancel';
  }
  // Which target a point is over: a screen's tile or the Cancel button — the one it is inside, else
  // one it is within a few pixels of, so a thumb near an edge still lands.
  function hitTest(targets, x, y, pad) {
    const within = (t, m) => t.rect && x >= t.rect.left - m && x <= t.rect.right + m && y >= t.rect.top - m && y <= t.rect.bottom + m;
    const list = targets || [];
    return list.find((t) => within(t, 0)) || list.find((t) => within(t, pad === undefined ? 6 : pad)) || null;
  }
  // Where the lifted chip is drawn: above a fingertip, so the finger does not cover it; beside a
  // mouse pointer; always inside the screen.
  function placeChip(x, y, w, h, view, type) {
    const gap = 12;
    let left = type === 'mouse' ? x + 14 : x - w / 2;
    let top = type === 'mouse' ? y + 14 : y - h - 26;
    left = Math.max(gap, Math.min(left, view.w - w - gap));
    top = Math.max(gap, Math.min(top, view.h - h - gap));
    return { left: Math.round(left), top: Math.round(top) };
  }
  // A screen as the tray names it: on or off, and what it shows now.
  function stateLine(s) {
    const up = [s && s.showing, s && s.beside].filter((t) => typeof t === 'string' && t);
    const what = up.length === 2 ? up[0] + ' and ' + up[1] : up[0] || '';
    if (s && s.online) return what ? 'On · Showing ' + what : 'On · Nothing up';
    return what ? 'Off · Showing ' + what : 'Off';
  }
  // The same, while the lifted thing is over it.
  function overLine(s) {
    return s && s.online ? 'Let go to show it here' : 'Off · It goes up when it’s next on';
  }
  // What went where, from the server's own answer.
  function confirmation(r) {
    const what = r && r.showing ? r.showing : 'It';
    const where = 'the ' + (r && r.screen ? r.screen : 'screen');
    return r && r.on ? what + ' is on ' + where + '.' : what + ' goes on ' + where + ' when it’s next on.';
  }
  // Why nothing went up, in the server's words where it gave some.
  function refusal(status, data, name) {
    const said = data && typeof data === 'object' ? String(data.spoken || data.detail || '') : '';
    if (said) return said.slice(0, 300);
    if (status === 0) return 'CLIVE couldn’t be reached, so nothing went on the ' + name + '.';
    if (status === -1) return 'CLIVE hasn’t answered, so it isn’t known whether it went up. Look at the ' + name + '.';
    return 'That couldn’t be put on the ' + name + '.';
  }
  // The body of the drop: the conversation, and the record as its card carries it. Nothing else.
  function bodyFor(sessionId, what) {
    return { session_id: String(sessionId || ''), kind: what.kind, ref: what.ref };
  }
  // An order's number and whose it is, from the words its card or row already shows.
  function orderWords(label, who) {
    const said = String(label || '').replace(/\s+/g, ' ').trim();
    const found = said.match(/#?\b[A-Za-z]*-?\d{3,}\b/);
    const number = found ? found[0] : '';
    const title = number ? 'Order ' + (/^[#A-Za-z]/.test(number) ? number : '#' + number) : 'Order';
    let rest = String(who || '').trim();
    if (!rest && found) rest = said.slice(found.index + number.length).split('·')[0].trim();
    return { title, sub: rest.slice(0, 60) };
  }
  // Only a record a screen can show, with an id of that record's shape, is ever lifted.
  function screenable(kind, ref) {
    return (kind === 'order' && ORDER_REF.test(ref)) || (kind === 'objective' && OBJECTIVE_REF.test(ref));
  }

  const rules = {
    HOLD_MS, SLOP, PICK_PX, SWALLOW_MS, SETTLE_MS, HOLDABLE, SAY, LINKED,
    wandered, release, hitTest, placeChip, stateLine, overLine, confirmation, refusal, bodyFor, orderWords, screenable,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = rules;
  root.CliveLift = rules;

  const doc = root.document;
  if (!doc || typeof doc.addEventListener !== 'function' || typeof doc.querySelector !== 'function' || !doc.documentElement
      || typeof doc.documentElement.closest !== 'function') return;

  // ---- the page -----------------------------------------------------------------------------
  const NS = 'http://www.w3.org/2000/svg';
  const html = doc.documentElement;
  const calm = () => { try { return root.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; } };
  const now = () => Date.now();
  const P = {
    press: null,       // a finger or pointer down on something that can be held, not yet lifted
    said: null,        // the pointer whose hold was answered with a line: its release is not a tap
    lift: null,        // what is lifted, and the tray's state
    screens: null, screensAt: 0, screensError: '', asking: null,
    swallowUntil: 0, frame: 0, sayTimer: 0, closeTimer: 0,
    ui: null,
  };

  function el(tag, cls, text) {
    const node = doc.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function icon(paths, stroke) {
    const s = doc.createElementNS(NS, 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('fill', 'none');
    s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', String(stroke || 1.9));
    s.setAttribute('stroke-linecap', 'round');
    s.setAttribute('stroke-linejoin', 'round');
    s.setAttribute('aria-hidden', 'true');
    for (const d of paths) {
      const p = doc.createElementNS(NS, 'path');
      p.setAttribute('d', d);
      s.appendChild(p);
    }
    return s;
  }
  const TV = ['M4.5 5.5h15a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 16V7a1.5 1.5 0 0 1 1.5-1.5z', 'M9 20.5h6'];
  const BOX = ['M4 8.2 12 4l8 4.2v7.6L12 20l-8-4.2z', 'M4 8.2 12 12.4l8-4.2', 'M12 12.4V20'];
  const GOAL = ['M12 3.5a8.5 8.5 0 1 0 0 17a8.5 8.5 0 1 0 0-17', 'M12 7.5a4.5 4.5 0 1 0 0 9a4.5 4.5 0 1 0 0-9', 'M12 11.2a.8.8 0 1 0 0 1.6a.8.8 0 1 0 0-1.6'];
  const TICK = ['m5 12.5 4.5 4.5L19 7.5'];
  function text(node) { return node ? String(node.textContent || '').replace(/\s+/g, ' ').trim() : ''; }
  function sessionId() {
    const door = root.CliveAlpha;
    if (door && typeof door.sessionId === 'function') return String(door.sessionId() || '');
    try { return String(root.localStorage.getItem('crooks.session') || ''); } catch (e) { return ''; }
  }
  function haptic(pattern) { try { if (root.navigator && root.navigator.vibrate) root.navigator.vibrate(pattern); } catch (e) { /* none */ } }

  // What is under the finger, if it is something that can be held: a record a screen shows
  // (`lift`), or one it does not (`say`). A control inside it keeps its own press.
  function holdableAt(target) {
    const start = target && target.nodeType === 1 ? target : target && target.parentElement;
    if (!start || typeof start.closest !== 'function') return null;
    if (start.closest('.lift-tray, .lift-chip, .lift-layer, .rm, dialog[open]')) return null;
    const item = start.closest(HOLDABLE);
    if (!item) return null;
    const touch = root.CrooksTouch;
    const controls = touch && touch.CONTROL_SELECTOR ? touch.CONTROL_SELECTOR + ',' + touch.APPROVAL_SELECTOR : FALLBACK_CONTROLS;
    const control = start.closest(controls);
    if (control && control !== item && item.contains(control)) return null;
    if (item.matches(OBJECTIVES)) {
      const ref = String(item.dataset.objective || '');
      if (!screenable('objective', ref)) return null;
      const title = text(item.querySelector('.alpha-row-title')) || 'Objective';
      return { item, lift: { kind: 'objective', ref, title: title.slice(0, 80), sub: 'Objective' } };
    }
    if (item.matches(ORDERS)) {
      const ref = String(item.dataset.ref || '');
      if (!screenable('order', ref)) return null;
      return { item, lift: Object.assign({ kind: 'order', ref }, describeOrder(item)) };
    }
    const kind = item.matches(EMAILS) ? 'email_thread' : 'customer';
    const linked = kind === 'email_thread' && item.querySelector('.link-strip.is-confident[data-kind="order"][data-ref]');
    return { item, say: SAY[kind] + (linked ? LINKED : '') };
  }
  function describeOrder(item) {
    const label = item.dataset.label
      || text(item.querySelector('.row-main strong, .card-title, .link-main, .link-chip-label, .chip-label'))
      || text(item);
    const who = item.matches('.card') ? text(item.querySelector('.card-sub > span:not(.badge)') || item.querySelector('.card-sub')) : '';
    return orderWords(label.slice(0, 120), who);
  }

  // ---- the screens --------------------------------------------------------------------------
  async function askScreens(force) {
    if (P.asking) return P.asking;
    if (!force && P.screens && now() - P.screensAt < SCREENS_FRESH_MS) return P.screens;
    P.asking = (async () => {
      try {
        const response = await fetch('/displays', { cache: 'no-store' });
        const data = await response.json().catch(() => ({}));
        if (response.status === 403) { P.screensError = 'This device isn’t allowed to put things on CLIVE’s screens.'; P.screens = []; }
        else if (!response.ok) throw new Error('screens ' + response.status);
        else { P.screensError = ''; P.screens = Array.isArray(data.screens) ? data.screens.filter((s) => s && SCREEN_ID.test(String(s.id || ''))) : []; }
        P.screensAt = now();
      } catch (e) {
        if (!P.screens) P.screensError = 'CLIVE can’t be reached, so your screens can’t be listed.';
      } finally {
        P.asking = null;
      }
      if (P.lift && !P.lift.putting && !P.lift.done) drawScreens();
      return P.screens;
    })();
    return P.asking;
  }

  // ---- the tray, the chip and the layer that holds the drag -----------------------------------
  function build() {
    if (P.ui) return P.ui;
    const tray = el('div', 'lift-tray');
    tray.hidden = true;
    tray.setAttribute('role', 'dialog');
    tray.setAttribute('aria-label', 'Displays');
    const head = el('div', 'lift-head');
    const words = el('div', 'lift-words');
    const title = el('p', 'lift-title', 'Displays');
    const hint = el('p', 'lift-hint');
    words.appendChild(title);
    words.appendChild(hint);
    const cancel = el('button', 'lift-cancel', 'Cancel');
    cancel.type = 'button';
    cancel.addEventListener('click', () => { if (P.lift && P.lift.mode === 'pick' && !P.lift.putting) settleBack(); });
    head.appendChild(words);
    head.appendChild(cancel);
    const list = el('div', 'lift-list');
    list.setAttribute('role', 'group');
    list.setAttribute('aria-label', 'Your screens');
    const note = el('p', 'lift-note');
    note.setAttribute('role', 'status');
    const done = el('p', 'lift-done');
    done.setAttribute('role', 'status');
    done.appendChild(el('span', 'lift-done-mark')).appendChild(icon(TICK, 2.4));
    const doneWords = el('span', 'lift-done-words');
    done.appendChild(doneWords);
    tray.appendChild(head);
    tray.appendChild(list);
    tray.appendChild(note);
    tray.appendChild(done);
    tray.addEventListener('keydown', onTrayKey);
    const layer = el('div', 'lift-layer');
    layer.hidden = true;
    layer.addEventListener('lostpointercapture', () => { if (P.lift && P.lift.mode === 'drag' && !P.lift.putting) settleBack(); });
    doc.body.appendChild(layer);
    doc.body.appendChild(tray);
    P.ui = { tray, hint, cancel, list, note, done, doneWords, layer };
    return P.ui;
  }

  function drawScreens() {
    const U = build();
    const L = P.lift;
    while (U.list.firstChild) U.list.removeChild(U.list.firstChild);
    const all = Array.isArray(P.screens) ? P.screens : [];
    const ready = all.filter((s) => !s.pending);
    const waiting = all.filter((s) => s.pending).map((s) => String(s.name || ''));
    L.tiles = [];
    if (P.screens === null && !P.screensError) {
      U.list.appendChild(el('p', 'lift-empty', 'Finding your screens…'));
    } else if (!ready.length) {
      U.list.appendChild(el('p', 'lift-empty', P.screensError || 'No screens yet. Open CLIVE’s address with /display on a TV, give it a name, and tell CLIVE the code it shows.'));
    }
    U.hint.textContent = hintFor(L);
    for (const s of ready) {
      const tile = el('button', 'lift-screen' + (s.online ? ' is-on' : ''));
      tile.type = 'button';
      tile.dataset.screen = s.id;
      const glyph = el('span', 'lift-glyph');
      glyph.appendChild(icon(TV, 1.8));
      glyph.appendChild(el('span', 'lift-dot'));
      const words = el('span', 'lift-text');
      words.appendChild(el('span', 'lift-name', String(s.name || 'Screen').slice(0, 60)));
      const line = el('span', 'lift-state', stateLine(s));
      words.appendChild(line);
      tile.appendChild(glyph);
      tile.appendChild(words);
      tile.setAttribute('aria-label', String(s.name || 'Screen') + ', ' + stateLine(s).replace(' · ', ', '));
      tile.addEventListener('click', () => { if (P.lift && P.lift.mode === 'pick' && !P.lift.putting) put(s, tile); });
      U.list.appendChild(tile);
      L.tiles.push({ screen: s, el: tile, line, rect: null });
    }
    U.note.textContent = waiting.length && !P.screensError
      ? 'Waiting for approval: ' + waiting.join(', ') + '. Tell CLIVE the code it shows.' : '';
    U.note.className = 'lift-note';
    measureList();
    if (L.keyboard && L.mode === 'pick' && L.tiles.length) { try { L.tiles[0].el.focus(); } catch (e) { /* not focusable */ } }
  }

  // A list longer than the tray is marked, so its edges fade as it scrolls (web/lift.css).
  function measureList() {
    const U = P.ui;
    if (!U || U.tray.hidden) return;
    U.list.classList.remove('is-long');
    U.list.classList.toggle('is-long', U.list.scrollHeight > U.list.clientHeight + 1);
  }

  function hintFor(L) {
    const none = Array.isArray(P.screens) && !P.screens.some((s) => !s.pending);
    if (none) return 'No screen to put ' + L.what.title + ' on';
    return L.mode === 'drag' ? 'Drop ' + L.what.title + ' on a screen' : 'Choose a screen for ' + L.what.title;
  }

  function openTray(L) {
    const U = build();
    clearTimeout(P.closeTimer);
    U.tray.classList.remove('is-done', 'is-leaving', 'is-open');
    U.tray.style.height = '';
    U.tray.dataset.mode = L.mode;
    U.hint.textContent = hintFor(L);
    U.done.hidden = true;
    U.note.textContent = '';
    U.tray.hidden = false;
    html.classList.add('lift-open');
    drawScreens();
    const show = () => { if (P.lift === L) U.tray.classList.add('is-open'); };
    if (typeof root.requestAnimationFrame === 'function') root.requestAnimationFrame(() => root.requestAnimationFrame(show)); else show();
    askScreens(false);
  }

  function makeChip(what) {
    const chip = el('div', 'lift-chip');
    chip.setAttribute('aria-hidden', 'true');
    const glyph = el('span', 'lift-chip-glyph');
    glyph.appendChild(icon(what.kind === 'objective' ? GOAL : BOX, 1.8));
    const words = el('span', 'lift-chip-words');
    words.appendChild(el('span', 'lift-chip-title', what.title));
    if (what.sub) words.appendChild(el('span', 'lift-chip-sub', what.sub));
    chip.appendChild(glyph);
    chip.appendChild(words);
    doc.body.appendChild(chip);
    return chip;
  }
  function view() { return { w: root.innerWidth || html.clientWidth || 0, h: root.innerHeight || html.clientHeight || 0 }; }
  function moveChip(L) {
    if (!L.chip) return;
    if (!L.chipSize) L.chipSize = { w: L.chip.offsetWidth || 240, h: L.chip.offsetHeight || 56 };
    const at = placeChip(L.x, L.y, L.chipSize.w, L.chipSize.h, view(), L.type);
    L.chip.style.transform = 'translate3d(' + at.left + 'px,' + at.top + 'px,0)' + (L.over && L.over.screen ? ' scale(1.03)' : '');
  }
  // The chip goes somewhere and fades: back into the card it came from, or into the screen it went to.
  function sendChip(L, rect, then) {
    const chip = L.chip;
    L.chip = null;
    if (!chip) { if (then) then(); return; }
    if (calm() || !rect) {
      chip.classList.add('is-gone');
      setTimeout(() => { chip.remove(); if (then) then(); }, calm() ? 120 : 200);
      return;
    }
    const size = L.chipSize || { w: 240, h: 56 };
    const cx = Math.max(0, Math.min(view().w, rect.left + rect.width / 2)) - size.w / 2;
    const cy = Math.max(0, Math.min(view().h, rect.top + rect.height / 2)) - size.h / 2;
    chip.classList.add('is-going');
    chip.style.transform = 'translate3d(' + Math.round(cx) + 'px,' + Math.round(cy) + 'px,0) scale(.55)';
    setTimeout(() => { chip.remove(); if (then) then(); }, 260);
  }

  // ---- pressing and holding -----------------------------------------------------------------
  function onDown(event) {
    const inTray = Boolean(event.target && event.target.closest && event.target.closest('.lift-tray'));
    // Said what went where: the next press does not wait for the tray to finish going.
    if (P.lift && P.lift.done && !inTray) closeTray(P.lift);
    if (P.lift) {
      // A tap outside the open tray puts the lifted thing back, and does nothing else.
      if (P.lift.mode === 'pick' && !P.lift.putting && !inTray) {
        settleBack();
        P.swallowUntil = now() + SWALLOW_MS;
      }
      return;
    }
    if (P.press) { forget(); return; }            // a second finger: this is not a hold
    if (event.isPrimary === false || (event.button !== undefined && event.button !== 0)) return;
    const found = holdableAt(event.target);
    if (!found) return;
    const type = event.pointerType === 'mouse' || event.pointerType === 'pen' ? event.pointerType : 'touch';
    P.press = { id: event.pointerId, type, x: event.clientX, y: event.clientY, found, timer: 0 };
    // A finger held on text would start a selection or the system's own menu: not on these.
    if (type !== 'mouse') found.item.classList.add('lift-pressing');
    if (found.lift) askScreens(false);
    P.press.timer = setTimeout(held, HOLD_MS);
  }
  function forget() {
    const press = P.press;
    P.press = null;
    if (!press) return;
    clearTimeout(press.timer);
    press.found.item.classList.remove('lift-pressing');
  }
  function onMove(event) {
    const press = P.press;
    if (press && event.pointerId === press.id && wandered(press, event.clientX, event.clientY)) { forget(); return; }
    const L = P.lift;
    if (!L || L.mode !== 'drag' || L.putting || event.pointerId !== L.pointerId) return;
    L.x = event.clientX;
    L.y = event.clientY;
    if (!P.frame) P.frame = (root.requestAnimationFrame || ((f) => setTimeout(f, 16)))(frame);
  }
  function frame() {
    P.frame = 0;
    const L = P.lift;
    if (!L || L.mode !== 'drag' || L.putting) return;
    const targets = L.tiles.map((t) => ({ screen: t.screen, tile: t, rect: t.el.getBoundingClientRect() }));
    const U = build();
    targets.push({ cancel: true, rect: U.cancel.getBoundingClientRect() });
    const over = hitTest(targets, L.x, L.y);
    const was = L.over;
    L.over = over;
    if ((was && was.tile) !== (over && over.tile)) {
      if (was && was.tile) { was.tile.el.classList.remove('is-over'); was.tile.line.textContent = stateLine(was.screen); }
      if (over && over.tile) { over.tile.el.classList.add('is-over'); over.tile.line.textContent = overLine(over.screen); haptic(6); }
    }
    U.cancel.classList.toggle('is-over', Boolean(over && over.cancel));
    moveChip(L);
    autoScroll(U.list, L.y);
  }
  // A list longer than the tray scrolls under a thumb held near its top or bottom edge.
  function autoScroll(list, y) {
    if (list.scrollHeight <= list.clientHeight) return;
    const r = list.getBoundingClientRect();
    const step = y < r.top + 28 ? -8 : y > r.bottom - 28 ? 8 : 0;
    if (!step) return;
    list.scrollTop += step;
    if (!P.frame) P.frame = (root.requestAnimationFrame || ((f) => setTimeout(f, 16)))(frame);
  }
  function onUp(event) {
    if (P.said === event.pointerId) { P.said = null; P.swallowUntil = now() + SWALLOW_MS; }
    const press = P.press;
    if (press && event.pointerId === press.id) { forget(); return; }   // a tap: the card's own click follows
    const L = P.lift;
    if (!L || L.mode !== 'drag' || event.pointerId !== L.pointerId || L.putting) return;
    P.swallowUntil = now() + SWALLOW_MS;
    L.x = event.clientX;
    L.y = event.clientY;
    frame();
    const outcome = release(L, L.x, L.y, L.over);
    releaseLayer(L);
    if (outcome === 'drop') put(L.over.screen, L.over.tile.el);
    else if (outcome === 'pick') toPick(L);
    else settleBack();
  }
  function onCancel(event) {
    if (P.said === event.pointerId) P.said = null;
    const press = P.press;
    if (press && event.pointerId === press.id) { forget(); return; }
    const L = P.lift;
    if (L && L.mode === 'drag' && event.pointerId === L.pointerId && !L.putting) settleBack();
  }

  // The press has been still for HOLD_MS.
  function held() {
    const press = P.press;
    P.press = null;
    if (!press) return;
    press.found.item.classList.remove('lift-pressing');
    let found = press.found;
    if (!found.item.isConnected) {
      // Redrawn under the finger (the home asks for its objectives every few seconds): the same
      // record, if it is still there.
      const again = found.lift && found.lift.kind === 'objective'
        ? doc.querySelector('[data-objective="' + found.lift.ref + '"]') : null;
      if (!again) return;
      found = { item: again, lift: found.lift };
    }
    if (found.say) { say(found.say, press.x, press.y); haptic(12); P.said = press.id; return; }
    lift(found, { mode: 'drag', type: press.type, pointerId: press.id, x: press.x, y: press.y });
  }

  function lift(found, how) {
    const L = {
      mode: how.mode, what: found.lift, item: found.item, type: how.type, keyboard: Boolean(how.keyboard),
      pointerId: how.pointerId, x0: how.x, y0: how.y, x: how.x, y: how.y, tiles: [], over: null,
      chip: null, chipSize: null, putting: false, done: false,
    };
    P.lift = L;
    clearSay();
    try { const sel = root.getSelection && root.getSelection(); if (sel && sel.removeAllRanges) sel.removeAllRanges(); } catch (e) { /* none */ }
    found.item.classList.add('lift-source');
    if (L.mode === 'drag') {
      haptic(12);
      html.classList.add('lift-dragging');
      const U = build();
      U.layer.hidden = false;
      try { U.layer.setPointerCapture(L.pointerId); } catch (e) { /* the pointer is already gone */ }
      L.chip = makeChip(L.what);
      moveChip(L);
      const shown = () => { if (L.chip) L.chip.classList.add('is-up'); };
      if (typeof root.requestAnimationFrame === 'function') root.requestAnimationFrame(shown); else shown();
    }
    openTray(L);
  }
  function releaseLayer(L) {
    html.classList.remove('lift-dragging');
    const U = P.ui;
    if (!U) return;
    try { if (U.layer.hasPointerCapture && U.layer.hasPointerCapture(L.pointerId)) U.layer.releasePointerCapture(L.pointerId); } catch (e) { /* released */ }
    U.layer.hidden = true;
  }
  // Let go where it lifted: the tray stays, to tap a screen.
  function toPick(L) {
    L.mode = 'pick';
    if (L.over && L.over.tile) { L.over.tile.el.classList.remove('is-over'); L.over.tile.line.textContent = stateLine(L.over.screen); }
    L.over = null;
    const U = build();
    U.cancel.classList.remove('is-over');
    U.tray.dataset.mode = 'pick';
    U.hint.textContent = hintFor(L);
    sendChip(L, L.item.isConnected ? L.item.getBoundingClientRect() : null);
  }
  // Put back, from wherever it is.
  function settleBack() {
    const L = P.lift;
    if (!L) return;
    releaseLayer(L);
    sendChip(L, L.item.isConnected ? L.item.getBoundingClientRect() : null);
    closeTray(L);
  }
  function closeTray(L) {
    const U = P.ui;
    P.lift = null;
    L.item.classList.remove('lift-source');
    if (L.keyboard && L.item.isConnected) { try { L.item.focus(); } catch (e) { /* not focusable */ } }
    if (!U) return;
    U.tray.classList.remove('is-open');
    U.tray.classList.add('is-leaving');
    html.classList.remove('lift-open');
    clearTimeout(P.closeTimer);
    P.closeTimer = setTimeout(() => {
      if (P.lift) return;
      U.tray.hidden = true;
      U.tray.classList.remove('is-leaving', 'is-done');
      U.tray.style.height = '';
    }, calm() ? 60 : 380);
  }

  // ---- putting it up --------------------------------------------------------------------------
  async function put(screen, tile) {
    const L = P.lift;
    if (!L || L.putting) return;
    L.putting = true;
    L.mode = 'pick';
    const U = build();
    U.tray.dataset.mode = 'busy';
    U.note.textContent = '';
    for (const t of L.tiles) t.el.classList.toggle('is-over', t.el === tile);
    const line = tile.querySelector('.lift-state');
    tile.classList.add('is-busy');
    tile.setAttribute('aria-busy', 'true');
    if (line) line.textContent = 'Putting it up…';
    sendChip(L, tile.querySelector('.lift-glyph').getBoundingClientRect());
    haptic(8);
    const name = String(screen.name || 'screen');
    let status = 0;
    let data = {};
    const ctl = typeof AbortController === 'function' ? new AbortController() : null;
    const giveUp = ctl ? setTimeout(() => ctl.abort(), PUT_TIMEOUT_MS) : 0;
    try {
      const response = await fetch('/displays/' + encodeURIComponent(screen.id) + '/show', {
        method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(bodyFor(sessionId(), L.what)), signal: ctl ? ctl.signal : undefined,
      });
      status = response.status;
      data = await response.json().catch(() => ({}));
    } catch (e) {
      status = e && e.name === 'AbortError' ? -1 : 0;
    } finally {
      clearTimeout(giveUp);
    }
    if (P.lift !== L) return;
    tile.classList.remove('is-busy');
    tile.removeAttribute('aria-busy');
    if (status === 200 && data && data.ok) {
      settled(L, tile, data);
      return;
    }
    // Not put up: the tray stays, says why in the server's words, and another screen can be tapped.
    L.putting = false;
    tile.classList.remove('is-over');
    if (line) line.textContent = stateLine(screen);
    U.tray.dataset.mode = 'pick';
    U.hint.textContent = hintFor(L);
    U.note.textContent = refusal(status, data, name);
    U.note.className = 'lift-note is-bad';
    haptic([40, 50, 40]);
    if (data && data.code === 'not_found') askScreens(true);
  }

  // Up: the tile says so, then the tray gathers into one line saying what went where, and goes.
  function settled(L, tile, answer) {
    L.done = true;
    const U = build();
    const line = tile.querySelector('.lift-state');
    tile.classList.add('is-done');
    if (line) line.textContent = answer.on ? 'Showing ' + answer.showing : 'Off · It goes up when it’s next on';
    const screen = (P.screens || []).find((s) => s.id === answer.screen_id);
    if (screen) { screen.showing = answer.showing; screen.beside = null; }
    U.doneWords.textContent = confirmation(answer);
    const before = U.tray.getBoundingClientRect().height;
    U.tray.classList.add('is-done');
    U.done.hidden = false;
    if (!calm() && html.dataset.lite !== '1' && before) {
      const after = U.done.getBoundingClientRect().height + 28;
      U.tray.style.height = Math.round(before) + 'px';
      void U.tray.offsetHeight;
      U.tray.style.height = Math.round(after) + 'px';
    }
    L.item.classList.remove('lift-source');
    P.closeTimer = setTimeout(() => { if (P.lift === L) closeTray(L); }, SETTLE_MS);
  }

  // ---- the line for something a screen cannot show -------------------------------------------
  function clearSay() {
    clearTimeout(P.sayTimer);
    const old = doc.querySelector('.lift-say');
    if (old) old.remove();
  }
  function say(words, x, y) {
    clearSay();
    const note = el('p', 'lift-say', words);
    note.setAttribute('role', 'status');
    doc.body.appendChild(note);
    const w = Math.min(note.offsetWidth || 280, view().w - 24);
    const h = note.offsetHeight || 44;
    const at = placeChip(x, y, w, h, view(), 'touch');
    note.style.transform = 'translate3d(' + at.left + 'px,' + at.top + 'px,0)';
    const shown = () => note.classList.add('is-up');
    if (typeof root.requestAnimationFrame === 'function') root.requestAnimationFrame(shown); else shown();
    P.sayTimer = setTimeout(() => {
      note.classList.remove('is-up');
      setTimeout(() => note.remove(), 300);
    }, SAY_MS);
  }

  // ---- the keyboard -----------------------------------------------------------------------------
  function onKey(event) {
    if (P.lift) return;
    const wants = event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10');
    if (!wants) return;
    const found = holdableAt(doc.activeElement);
    if (!found) return;
    event.preventDefault();
    const r = found.item.getBoundingClientRect();
    if (found.say) { say(found.say, r.left + r.width / 2, r.top + 8); return; }
    lift(found, { mode: 'pick', type: 'keyboard', keyboard: true, x: r.left + r.width / 2, y: r.top });
  }
  function onTrayKey(event) {
    const L = P.lift;
    if (!L) return;
    if (event.key === 'Escape') { event.preventDefault(); if (!L.putting) settleBack(); return; }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    const tiles = L.tiles.map((t) => t.el);
    if (!tiles.length) return;
    event.preventDefault();
    const at = tiles.indexOf(doc.activeElement);
    const next = event.key === 'ArrowDown' ? Math.min(tiles.length - 1, at + 1) : Math.max(0, at - 1);
    try { tiles[next].focus(); } catch (e) { /* not focusable */ }
  }

  // ---- wiring -----------------------------------------------------------------------------------
  doc.addEventListener('pointerdown', onDown, true);
  doc.addEventListener('pointermove', onMove, true);
  doc.addEventListener('pointerup', onUp, true);
  doc.addEventListener('pointercancel', onCancel, true);
  doc.addEventListener('keydown', onKey, true);
  // A lift's release is not also a tap on what it was lifted from (or on what it was dropped near).
  doc.addEventListener('click', (event) => {
    if (now() > P.swallowUntil) return;
    if (event.target && event.target.closest && event.target.closest('.lift-tray')) return;
    P.swallowUntil = 0;
    event.preventDefault();
    event.stopPropagation();
  }, true);
  // The system's own long-press menu and selection belong to text, not to a held record.
  doc.addEventListener('contextmenu', (event) => { if (P.press || (P.lift && P.lift.mode === 'drag')) event.preventDefault(); }, true);
  doc.addEventListener('selectstart', (event) => {
    if ((P.press && P.press.type !== 'mouse') || (P.lift && P.lift.mode === 'drag')) event.preventDefault();
  }, true);
  // Once lifted, a move is the drag's, not a scroll's. Present from the start, and not passive, so
  // the browser lets it keep a held finger from scrolling (iOS decides that as the touch begins);
  // it does nothing at all unless something is lifted.
  doc.addEventListener('touchmove', (event) => {
    if (P.lift && P.lift.mode === 'drag' && event.cancelable) event.preventDefault();
  }, { passive: false });
  // A scroll that starts under a waiting press, in what holds the pressed record, is a scroll.
  doc.addEventListener('scroll', (event) => {
    const press = P.press;
    const where = event.target;
    if (press && (where === doc || (where && where.contains && where.contains(press.found.item)))) forget();
  }, { capture: true, passive: true });
  const away = () => { forget(); if (P.lift && !P.lift.putting) settleBack(); };
  root.addEventListener('blur', away);
  root.addEventListener('pagehide', away);
  doc.addEventListener('visibilitychange', () => { if (doc.hidden) away(); });

  root.CliveLift = Object.assign({}, rules, { state: () => P, holdableAt });
})(typeof window !== 'undefined' ? window : globalThis);

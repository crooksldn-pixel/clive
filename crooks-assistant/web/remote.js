/* The remote for one of the owner's screens (round 9).
 *
 * The owner asking for a remote is understood by CLIVE — the screen_remote tool
 * (app/tools/display_tools.py) — and never by matching words here. Its answer carries a `screen_remote` card
 * (app/presentation.py, drawn by web/ui.js), and the app opens this panel over itself when it
 * draws one (web/app.js renderTurn), or when the card's button is tapped later.
 *
 * The panel is the owner's own view of that screen, asked for about once a second
 * (GET /displays/{id}/remote), so what is ticked here and what the screen shows always agree. Its
 * controls follow what each pane shows (CONTROLS, below): an order's items to tick as they go in
 * the box and a Packed button that wakes once every item to send is ticked; a list's lines to
 * cross off and Mark done; an objective's summary and Put it up again. Every pane can be taken
 * off, and the whole screen turned off, back to its clock. Each change goes to the owner's
 * /displays routes naming the pane and the version it was put up at, so one made on an old view
 * is refused (409) and the panel catches up.
 *
 * What it shows leaves it when the panel closes, the moment CLIVE refuses this device (403), and
 * after two minutes out of reach; and a pane older than CLIVE keeps anything up is dropped here
 * too — the rules the screen itself keeps (web/display.js). Nothing is stored on the device, and
 * every word is put on the page as text, never as markup.
 */
'use strict';

(function (root) {
  const POLL_MS = 1000;
  const POLL_SLOW_MS = 4000;
  const POLL_TIMEOUT_MS = 8000;
  const OFFLINE_CLEAR_MS = 120000;           // out of reach this long, and what is shown here goes
  const SHOW_KEEP_MS = 12 * 3600 * 1000;     // CLIVE's own limit for anything shown (store.py SHOWING_KEEP_S)
  const CONFIRM_MS = 3000;                   // a second tap within this takes something off
  const SCREEN_ID = /^scr_[0-9a-f]{12}$/;
  const NS = 'http://www.w3.org/2000/svg';

  const R = {
    id: '', name: '', open: false, data: null, gen: 0, timer: 0, polling: false,
    lastOk: 0, skew: 0, gone: '', note: '', held: false, heldAt: 0, dirty: false, confirm: null, busy: false, ui: null,
  };

  const doc = () => root.document;

  // ---- small helpers --------------------------------------------------------------------
  function h(tag, cls, text) {
    const node = doc().createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function icon(paths, width) {
    const s = doc().createElementNS(NS, 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('fill', 'none');
    s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', String(width || 2));
    s.setAttribute('stroke-linecap', 'round');
    s.setAttribute('stroke-linejoin', 'round');
    s.setAttribute('aria-hidden', 'true');
    for (const d of paths) {
      const p = doc().createElementNS(NS, 'path');
      p.setAttribute('d', d);
      s.appendChild(p);
    }
    return s;
  }
  const CHECK = ['m5.5 12.5 4 4 9-9.5'];
  const LEFT = ['m14.5 6-6 6 6 6'];
  const RIGHT = ['m9.5 6 6 6-6 6'];
  const HANGER = ['M10.2 5.6a1.8 1.8 0 1 1 2.6 1.6c-.5.3-.8.7-.8 1.2V9', 'M12 9 3.6 15c-.8.6-.4 1.7.6 1.7h15.6c1 0 1.4-1.1.6-1.7L12 9z'];
  const REFRESH = ['M20 11a8 8 0 1 0-2.3 5.7', 'M20 5v6h-6'];
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function pad(n) { return String(n).padStart(2, '0'); }
  function timeOf(iso) {
    const d = new Date(iso || '');
    return isNaN(d.getTime()) ? '' : pad(d.getHours()) + ':' + pad(d.getMinutes());
  }
  function serverNow() { return Date.now() + R.skew; }
  // Older than CLIVE keeps anything up, by CLIVE's clock, as the screen reckons it.
  function fresh(p) {
    const at = Date.parse((p && p.at) || '');
    return !isNaN(at) && serverNow() - at <= SHOW_KEEP_MS;
  }
  function button(cls, label, onTap) {
    const b = h('button', cls, label);
    b.type = 'button';
    b.addEventListener('click', (event) => { if (event && event.stopPropagation) event.stopPropagation(); onTap(event); });
    return b;
  }
  const KIND = { order: 'Order', list: 'List', objective: 'Objective' };

  // ---- the controls, by what a pane shows -------------------------------------------------
  // Each kind of view draws its own controls. A kind not here gets the one control every pane
  // has — Take this off — and nothing else.
  const CONTROLS = {
    order: { draw: drawOrder, progress: (p) => progress(p, 'packed') },
    list: { draw: drawList, progress: (p) => progress(p, 'done') },
    objective: { draw: drawObjective },
    // A `video` pane, when the screens can play one, adds its controls here and needs nothing
    // else changed:
    //   video: { draw: (p) => play/pause (POST /displays/{id}/remote/play {pane, version}) and a
    //            volume slider — an <input type="range"> in an rm-cell, 0 to 100, posting
    //            /displays/{id}/remote/volume {pane, level, version} as it moves — },
  };

  // What is ticked of what must be, for a pane of items or lines.
  function need(p) {
    if (p.kind === 'order') return (p.items || []).filter((it) => !it.sent);
    if (p.kind === 'list') return p.lines || [];
    return [];
  }
  function progress(p, word) {
    const all = need(p);
    const ticked = all.filter((it) => it.ticked).length;
    if (!all.length) return '';
    return ticked === all.length ? 'All ' + word + ' · ' + all.length + ' of ' + all.length : ticked + ' of ' + all.length + ' ' + word;
  }
  function ready(p) {
    const all = need(p);
    return !p.partial && all.length > 0 && all.every((it) => it.ticked);
  }

  function tickCell(p, entry, main, detail, quantity, image) {
    const cell = button('rm-cell rm-tick' + (entry.ticked ? ' is-ticked' : ''), null, () => tick(p, entry));
    cell.setAttribute('aria-pressed', entry.ticked ? 'true' : 'false');
    if (image !== undefined) {
      const thumb = h('span', 'rm-thumb');
      thumb.appendChild(icon(HANGER, 1.5));
      if (typeof image === 'string' && /^https:\/\//.test(image)) {
        const img = doc().createElement('img');
        img.alt = '';
        img.decoding = 'async';
        img.referrerPolicy = 'no-referrer';
        img.src = image;
        img.addEventListener('error', () => { if (img.parentNode) img.parentNode.removeChild(img); });
        thumb.appendChild(img);
      }
      cell.appendChild(thumb);
    }
    const text = h('span', 'rm-text');
    text.appendChild(h('span', 'rm-t', main));
    if (detail) text.appendChild(h('span', 'rm-d', detail));
    cell.appendChild(text);
    if (quantity) cell.appendChild(h('span', 'rm-qty', quantity));
    const mark = h('span', 'rm-check');
    mark.appendChild(icon(CHECK, 2.4));
    cell.appendChild(mark);
    return cell;
  }
  function pager(p, count) {
    const pages = typeof p.pages === 'number' && p.pages > 0 ? p.pages : null;
    if (pages === 1 || (!pages && count <= 4)) return null;
    const row = h('div', 'rm-pager');
    const back = button('rm-glass rm-round', null, () => turn(p, -1));
    back.setAttribute('aria-label', 'Page back on the screen');
    back.appendChild(icon(LEFT, 2.2));
    const on = button('rm-glass rm-round', null, () => turn(p, 1));
    on.setAttribute('aria-label', 'Next page on the screen');
    on.appendChild(icon(RIGHT, 2.2));
    const page = (p.page || 0) + 1;
    row.appendChild(back);
    row.appendChild(h('span', 'rm-page', pages ? 'Page ' + page + ' of ' + pages + ' on the screen' : 'Page ' + page + ' on the screen'));
    row.appendChild(on);
    return row;
  }
  function drawOrder(p) {
    const box = h('div', 'rm-ctl');
    const cells = h('div', 'rm-cells');
    for (const it of p.items || []) {
      if (it.sent) {
        const cell = h('div', 'rm-cell is-sent');
        const thumb = h('span', 'rm-thumb');
        thumb.appendChild(icon(HANGER, 1.5));
        cell.appendChild(thumb);
        const text = h('span', 'rm-text');
        text.appendChild(h('span', 'rm-t', it.title || 'Item'));
        if (it.variant) text.appendChild(h('span', 'rm-d', String(it.variant).replace(/ \/ /g, ' · ')));
        cell.appendChild(text);
        cell.appendChild(h('span', 'rm-sent', 'Sent'));
        cells.appendChild(cell);
      } else {
        cells.appendChild(tickCell(p, it, it.title || 'Item', it.variant ? String(it.variant).replace(/ \/ /g, ' · ') : '',
          '×' + (it.quantity || 1), it.image || null));
      }
    }
    box.appendChild(cells);
    const turner = pager(p, (p.items || []).length);
    if (turner) box.appendChild(turner);
    if (p.partial) {
      box.appendChild(h('p', 'rm-note', 'This order has more items than a screen shows, so it is not marked packed here. Check it off in Shopify.'));
    } else {
      const packed = button('rm-primary', 'Packed', () => markDone(p));
      packed.disabled = !ready(p);
      box.appendChild(packed);
      if (!ready(p)) box.appendChild(h('p', 'rm-note', 'Tick each item as it goes in the box.'));
    }
    return box;
  }
  function drawList(p) {
    const box = h('div', 'rm-ctl');
    const cells = h('div', 'rm-cells');
    for (const line of p.lines || []) cells.appendChild(tickCell(p, line, line.text || '', '', '', undefined));
    if (!(p.lines || []).length) cells.appendChild(h('div', 'rm-cell is-quiet', 'Nothing on this list'));
    box.appendChild(cells);
    const turner = pager(p, (p.lines || []).length);
    if (turner) box.appendChild(turner);
    const done = button('rm-primary', 'Mark done', () => markDone(p));
    done.disabled = !ready(p);
    box.appendChild(done);
    return box;
  }
  function drawObjective(p) {
    const g = p.objective || {};
    const box = h('div', 'rm-ctl');
    const cells = h('div', 'rm-cells');
    const row = (label, value, cls) => {
      const cell = h('div', 'rm-cell rm-fact' + (cls ? ' ' + cls : ''));
      cell.appendChild(h('span', 'rm-k', label));
      cell.appendChild(h('span', 'rm-t', value));
      cells.appendChild(cell);
    };
    row('Doing now', g.doing || 'Nothing started yet', g.doing ? '' : 'is-quiet');
    if ((g.needs_you || []).length) row('Needs you', g.needs_you.join(' · '), 'is-needs');
    row('Next', (g.next || []).length ? g.next.slice(0, 3).join(' · ') : 'Nothing waiting', (g.next || []).length ? '' : 'is-quiet');
    if (typeof g.days_left === 'number') {
      row('Due', g.days_left > 0 ? g.days_left + (g.days_left === 1 ? ' day to go' : ' days to go')
        : g.days_left === 0 ? 'Today' : -g.days_left + (g.days_left === -1 ? ' day late' : ' days late'), g.days_left < 0 ? 'is-late' : '');
    }
    box.appendChild(cells);
    const again = button('rm-glass rm-wide', null, () => putUpAgain(p));
    again.appendChild(icon(REFRESH, 2));
    again.appendChild(doc().createTextNode('Put it up again'));
    box.appendChild(again);
    return box;
  }
  // The one control every pane has. Taken off at a second tap, so a finger resting on it
  // mid-pack does not clear a customer's slip.
  function takeOffButton(p) {
    const key = 'pane:' + p.pane + ':' + p.v;
    const armed = R.confirm && R.confirm.key === key && Date.now() < R.confirm.until;
    const b = button('rm-destroy' + (armed ? ' is-armed' : ''), armed ? 'Tap again to take it off' : 'Take this off', () => {
      if (armed) { R.confirm = null; takeOff(p); return; }
      arm(key);
    });
    return b;
  }
  function arm(key) {
    R.confirm = { key, until: Date.now() + CONFIRM_MS };
    render();
    setTimeout(() => { if (R.confirm && R.confirm.key === key && Date.now() >= R.confirm.until) { R.confirm = null; render(); } }, CONFIRM_MS + 50);
  }
  function paneGroup(p, count) {
    const g = h('section', 'rm-group');
    g.setAttribute('data-pane', String(p.pane));
    g.appendChild(h('p', 'rm-kicker', (KIND[p.kind] || 'On the screen') + (count > 1 ? ' · ' + (p.pane === 0 ? 'first' : 'second') + ' of two' : '')));
    const head = h('div', 'rm-ghead');
    head.appendChild(h('h2', 'rm-h', p.title || KIND[p.kind] || 'On the screen'));
    const control = CONTROLS[p.kind];
    const said = p.done_at ? (p.kind === 'order' ? 'Packed at ' : 'Done at ') + timeOf(p.done_at)
      : control && control.progress ? control.progress(p) : '';
    if (said) head.appendChild(h('p', 'rm-sub' + (p.done_at ? ' is-done' : ''), said));
    g.appendChild(head);
    if (p.done_at) {
      const cell = h('div', 'rm-cells');
      const done = h('div', 'rm-cell rm-donecell');
      const mark = h('span', 'rm-check');
      mark.appendChild(icon(CHECK, 2.4));
      done.appendChild(mark);
      done.appendChild(h('span', 'rm-t', 'CLIVE has noted it. The screen rests in a moment.'));
      cell.appendChild(done);
      g.appendChild(cell);
    } else if (control) {
      g.appendChild(control.draw(p));
    }
    g.appendChild(takeOffButton(p));
    return g;
  }

  // ---- the panel --------------------------------------------------------------------------
  function build() {
    if (R.ui) return R.ui;
    const panel = h('div', 'rm');
    panel.hidden = true;
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('aria-label', 'Remote');
    const bar = h('header', 'rm-bar');
    bar.appendChild(h('span', 'rm-bar-k', 'Remote'));
    const done = button('rm-done', 'Done', () => close());
    bar.appendChild(done);
    const body = h('div', 'rm-body');
    const title = h('div', 'rm-large');
    const dot = h('span', 'rm-dot');
    const name = h('h1', 'rm-name');
    const state = h('p', 'rm-state');
    state.setAttribute('role', 'status');
    title.appendChild(dot);
    title.appendChild(name);
    const panes = h('div', 'rm-panes');
    body.appendChild(title);
    body.appendChild(state);
    body.appendChild(panes);
    const foot = h('footer', 'rm-foot');
    const off = button('rm-off', 'Turn screen off', () => {
      const armed = R.confirm && R.confirm.key === 'screen' && Date.now() < R.confirm.until;
      if (armed) { R.confirm = null; takeOff(null); return; }
      arm('screen');
    });
    foot.appendChild(off);
    panel.appendChild(bar);
    panel.appendChild(body);
    panel.appendChild(foot);
    // A finger on the panel holds the redraw until it lifts, so a control never moves under it.
    panel.addEventListener('pointerdown', () => { R.held = true; R.heldAt = Date.now(); });
    const lift = () => { if (!R.held) return; R.held = false; if (R.dirty) { R.dirty = false; render(); } };
    panel.addEventListener('pointerup', lift);
    panel.addEventListener('pointercancel', lift);
    panel.addEventListener('keydown', (event) => { if (event && event.key === 'Escape') close(); });
    doc().body.appendChild(panel);
    R.ui = { panel, done, dot, name, state, panes, off, body };
    return R.ui;
  }
  function stateLine(d) {
    if (R.gone === 'refused') return 'This device isn’t allowed to control CLIVE’s screens any more.';
    if (R.gone === 'offline') return 'CLIVE can’t be reached, so the remote has let go of what it showed.';
    if (R.gone === 'gone') return 'That screen isn’t there any more.';
    if (R.gone === 'pending') return 'That screen is waiting to be approved: it shows only its code.';
    if (R.note) return R.note;
    if (!d) return 'Asking the screen…';
    return d.online ? 'On · following the screen' : 'Off · it catches up when it’s next on';
  }
  function render() {
    const U = R.ui;
    if (!U || !R.open) return;
    // A hold whose lift was never seen does not freeze the panel: it lapses after two seconds.
    if (R.held && Date.now() - R.heldAt < 2000) { R.dirty = true; return; }
    R.held = false;
    const d = R.data;
    U.name.textContent = R.name || 'Screen';
    U.panel.setAttribute('aria-label', 'Remote for ' + (R.name || 'the screen'));
    U.dot.className = 'rm-dot' + (d && d.online && !R.gone ? ' is-on' : '');
    U.state.textContent = stateLine(d);
    U.state.className = 'rm-state' + (R.gone || R.note ? ' is-warn' : '');
    const top = U.body.scrollTop;
    clear(U.panes);
    const panes = d && Array.isArray(d.panes) ? d.panes.filter(fresh) : [];
    panes.forEach((p) => U.panes.appendChild(paneGroup(p, panes.length)));
    if (d && !panes.length) {
      const empty = h('div', 'rm-empty');
      empty.appendChild(h('p', 'rm-empty-t', 'Nothing on the screen'));
      empty.appendChild(h('p', 'rm-empty-d', 'Ask CLIVE to put an order, a list or an objective on it.'));
      U.panes.appendChild(empty);
    }
    const armed = R.confirm && R.confirm.key === 'screen' && Date.now() < R.confirm.until;
    U.off.textContent = armed ? 'Tap again to turn it off' : 'Turn screen off';
    U.off.className = 'rm-off' + (armed ? ' is-armed' : '');
    U.off.disabled = !panes.length || R.busy;
    U.body.scrollTop = top;
  }
  // What the remote shows leaves it, at once (the screen's own rule, NEW-B-LOCAL-SLIP).
  function wipe(why) {
    R.data = null;
    R.confirm = null;
    R.gone = why || '';
    render();
  }

  // ---- asking, and telling -----------------------------------------------------------------
  async function sync() {
    if (!R.open || R.polling) return;
    R.polling = true;
    clearTimeout(R.timer);
    const gen = R.gen, id = R.id;
    const ctl = typeof AbortController === 'function' ? new AbortController() : null;
    const giveUp = ctl ? setTimeout(() => ctl.abort(), POLL_TIMEOUT_MS) : 0;
    let delay = POLL_MS;
    try {
      const response = await fetch('/displays/' + encodeURIComponent(id) + '/remote', { cache: 'no-store', signal: ctl ? ctl.signal : undefined });
      if (gen !== R.gen) return;
      if (response.status === 403) { R.lastOk = Date.now(); wipe('refused'); delay = POLL_SLOW_MS; return; }
      if (response.status === 404) { R.lastOk = Date.now(); wipe('gone'); delay = POLL_SLOW_MS; return; }
      const data = await response.json().catch(() => ({}));
      if (gen !== R.gen) return;
      if (response.status === 409 && data.code === 'not_approved') { R.lastOk = Date.now(); wipe('pending'); delay = POLL_SLOW_MS; return; }
      if (!response.ok) throw new Error('remote ' + response.status);
      R.lastOk = Date.now();
      const now = Date.parse(data.now || '');
      if (!isNaN(now)) R.skew = now - Date.now();
      R.gone = '';
      if (R.note === 'CLIVE can’t be reached. Trying again.') R.note = '';
      R.data = data;
      if (typeof data.name === 'string' && data.name) R.name = data.name;
      render();
    } catch (e) {
      if (gen !== R.gen) return;
      delay = POLL_SLOW_MS;
      if (Date.now() - R.lastOk >= OFFLINE_CLEAR_MS) { if (R.gone !== 'offline') wipe('offline'); } else { R.note = 'CLIVE can’t be reached. Trying again.'; render(); }
    } finally {
      clearTimeout(giveUp);
      if (gen === R.gen) {
        R.polling = false;
        if (R.open) R.timer = setTimeout(sync, delay);
      }
    }
  }
  // A change, told to CLIVE as the owner: the answer, or why not, in plain words.
  async function post(path, body) {
    try {
      const response = await fetch('/displays/' + encodeURIComponent(R.id) + path, {
        method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      if (response.status === 403) { wipe('refused'); return null; }
      if (response.ok) return data && typeof data === 'object' ? data : {};
      if (response.status === 503) say('CLIVE could not save that yet. Try again in a moment.');
      else if (data.code === 'stale') say('That changed on the screen, so nothing was done. Here it is as it is now.');
      else if (data.code === 'not_ticked') say('Tick every item first.');
      else say(typeof data.detail === 'string' && data.detail ? data.detail.slice(0, 200) : 'That did not work. Try again.');
      return null;
    } catch (e) {
      say('CLIVE couldn’t be reached, so nothing changed. Try again.');
      return null;
    }
  }
  let sayTimer = 0;
  function say(text) {
    R.note = text || '';
    clearTimeout(sayTimer);
    if (text) sayTimer = setTimeout(() => { R.note = ''; render(); }, 5000);
    render();
  }
  function samePane(p) {
    return R.data && Array.isArray(R.data.panes) ? R.data.panes.find((q) => q.pane === p.pane && q.v === p.v) : null;
  }
  // Ticked here at once, and put right if CLIVE says otherwise.
  async function tick(p, entry) {
    if (!R.open || R.busy) return;
    const want = !entry.ticked;
    entry.ticked = want;
    render();
    const gen = R.gen;
    const answer = await post('/remote/tick', { pane: p.pane, item: entry.i, packed: want, version: p.v });
    if (gen !== R.gen) return;
    const now = samePane(p);
    if (answer && Array.isArray(answer.ticked) && now) {
      const on = new Set(answer.ticked);
      for (const it of (now.items || now.lines || [])) it.ticked = on.has(it.i);
    } else if (!answer) {
      entry.ticked = !want;
    }
    render();
    sync();
  }
  async function act(path, body) {
    if (!R.open || R.busy) return;
    R.busy = true;
    render();
    const gen = R.gen;
    const answer = await post(path, body);
    if (gen !== R.gen) return;
    R.busy = false;
    if (answer && Array.isArray(answer.panes)) { R.data = answer; R.lastOk = Date.now(); }
    render();
    sync();
  }
  function turn(p, delta) { return act('/remote/page', { pane: p.pane, delta, version: p.v }); }
  function markDone(p) { if (ready(p)) return act('/remote/done', { pane: p.pane, version: p.v }); return null; }
  function putUpAgain(p) { return act('/remote/again', { pane: p.pane, version: p.v }); }
  function takeOff(p) { return act('/remote/off', p ? { pane: p.pane, version: p.v } : {}); }

  // ---- open and close ----------------------------------------------------------------------
  function open(id, name) {
    if (!SCREEN_ID.test(String(id || ''))) return false;
    const U = build();
    if (R.id !== id) R.data = null;
    R.id = String(id);
    R.name = String(name || 'Screen').slice(0, 40);
    R.open = true; R.gen++; R.polling = false; R.gone = ''; R.note = ''; R.confirm = null; R.busy = false;
    R.lastOk = Date.now();
    U.panel.hidden = false;
    if (doc().body && doc().body.classList) doc().body.classList.add('rm-on');
    const show = () => { if (R.open) U.panel.classList.add('is-open'); };
    if (typeof root.requestAnimationFrame === 'function') root.requestAnimationFrame(() => root.requestAnimationFrame(show)); else show();
    render();
    sync();
    try { U.done.focus(); } catch (e) { /* not focusable here */ }
    return true;
  }
  function close() {
    R.open = false;
    R.gen++;
    clearTimeout(R.timer);
    R.polling = false;
    // Nothing of what the screen showed stays in the page once the remote is put away.
    R.data = null;
    R.confirm = null;
    R.busy = false;
    const U = R.ui;
    if (!U) return;
    U.panel.classList.remove('is-open');
    clear(U.panes);
    if (doc().body && doc().body.classList) doc().body.classList.remove('rm-on');
    setTimeout(() => { if (!R.open) U.panel.hidden = true; }, 360);
  }
  // A turn's cards (web/app.js renderTurn): CLIVE's screen_remote card opens the remote.
  function fromTurn(items) {
    if (!Array.isArray(items)) return false;
    const card = items.find((i) => i && i.type === 'screen_remote' && i.data && SCREEN_ID.test(String(i.data.screen_id || '')));
    return card ? open(card.data.screen_id, card.data.name) : false;
  }
  // The card's own button (web/ui.js renderScreenRemote), wherever the card is drawn.
  if (doc() && typeof doc().addEventListener === 'function') {
    doc().addEventListener('click', (event) => {
      const target = event && event.target && event.target.closest ? event.target.closest('[data-remote-screen]') : null;
      if (!target) return;
      if (event.preventDefault) event.preventDefault();
      open(target.dataset.remoteScreen, target.dataset.remoteName);
    });
  }

  root.CliveRemote = { open, close, fromTurn, CONTROLS, ready, state: () => R };
})(typeof window !== 'undefined' ? window : globalThis);

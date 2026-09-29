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
 * cross off and Mark done; an objective's summary and Put it up again; a YouTube video's play and
 * pause, ten seconds back and on, where it is and its volume. Every pane can be taken off, and
 * the whole screen turned off, back to its clock. Each change goes to the owner's
 * /displays routes naming the pane and the version it was put up at, so one made on an old view
 * is refused (409) and the panel catches up.
 *
 * What it shows leaves it when the panel closes, the moment CLIVE refuses this device (403), and
 * after two minutes out of reach; and a pane older than CLIVE keeps anything up is dropped here
 * too — the rules the screen itself keeps (web/display.js). Nothing is stored on the device, and
 * every word is put on the page as text, never as markup.
 *
 * Round 10. Taking what is shown away is done at once, whether or not a finger is on the panel
 * (B2-02), and an answer to anything asked before it is never read (B2-03): only a fresh ask can
 * put anything back. Turning the whole screen off names the version of the screen the owner was
 * looking at when he chose to, so CLIVE refuses it (409, stale) if the screen has changed since.
 *
 * Round 11 (S3P-F-01). A finger on the panel holds back only a redraw of what may still be shown.
 * A pane that passes CLIVE's own limit leaves the panel, and everything the page holds of it, the
 * moment it does — timed to that moment, whether or not an ask is answered — and so does a pane
 * CLIVE no longer shows (taken off, put up afresh, or marked done), finger or no finger.
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
    id: '', name: '', open: false, data: null, gen: 0, timer: 0, polling: false, ctl: null, shown: null,
    lastOk: 0, skew: 0, gone: '', note: '', held: false, heldAt: 0, dirty: false, confirm: null, busy: false, ui: null,
    drawn: [], expiry: 0,
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
  const PLAY = ['M8 5.2v13.6a.8.8 0 0 0 1.2.7l11-6.8a.8.8 0 0 0 0-1.4l-11-6.8A.8.8 0 0 0 8 5.2z'];
  const PAUSE = ['M6.5 4.5h3.6v15H6.5z', 'M13.9 4.5h3.6v15h-3.6z'];
  const BACK = ['M4.5 12a7.5 7.5 0 1 0 2.2-5.3', 'M4.5 3.8v4.6h4.6'];
  const ON = ['M19.5 12a7.5 7.5 0 1 1-2.2-5.3', 'M19.5 3.8v4.6h-4.6'];
  const SPEAKER = ['M4 9.4h3.6L12.3 5.6v12.8L7.6 14.6H4z'];
  const WAVES = ['M15.6 9.2a4 4 0 0 1 0 5.6', 'M18.4 6.5a8 8 0 0 1 0 11'];
  const MUTED = ['m16 9.5 5 5', 'm21 9.5-5 5'];
  const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;
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
  const KIND = { order: 'Order', list: 'List', objective: 'Objective', video: 'Video' };

  // ---- the controls, by what a pane shows -------------------------------------------------
  // Each kind of view draws its own controls. A kind not here gets the one control every pane
  // has — Take this off — and nothing else.
  const CONTROLS = {
    order: { draw: drawOrder, progress: (p) => progress(p, 'packed') },
    list: { draw: drawList, progress: (p) => progress(p, 'done') },
    objective: { draw: drawObjective },
    // A YouTube video: play and pause, ten seconds back and on, where it is (drag to go there),
    // and the volume (tap the speaker to mute), each told to CLIVE (POST /remote/video).
    video: { draw: drawVideo, progress: videoProgress },
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
  // ---- a video ------------------------------------------------------------------------------
  function clockOf(sec) {
    const s = Math.max(0, Math.floor(Number(sec) || 0)), hh = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return (hh ? hh + ':' + pad(m) : String(m)) + ':' + pad(s % 60);
  }
  function filled(paths) {
    const s = icon(paths, 0);
    s.setAttribute('fill', 'currentColor');
    s.setAttribute('stroke', 'none');
    return s;
  }
  // How it is playing, as the screen last said, moved on by the time since this view was asked
  // for while it plays; and what the owner last asked of it.
  function heard(p) { return p.playing && typeof p.playing === 'object' ? p.playing : null; }
  function wantOf(p) { return p.player && typeof p.player === 'object' ? p.player : {}; }
  function lengthOf(p) {
    const said = heard(p), clip = p.video || {};
    if (clip.live) return 0;   // a live stream has no end
    if (said && typeof said.duration === 'number' && said.duration > 0) return said.duration;
    return Number.isInteger(clip.duration_s) && clip.duration_s > 0 ? clip.duration_s : 0;
  }
  function positionOf(p) {
    const said = heard(p);
    if (!said || typeof said.at !== 'number') return 0;
    const since = said.state === 'playing' && R.dataAt ? (Date.now() - R.dataAt) / 1000 : 0;
    const len = lengthOf(p);
    return Math.max(0, len ? Math.min(len, said.at + since) : said.at + since);
  }
  function pausedOf(p) {
    const said = heard(p);
    if (said && said.state === 'ended') return true;
    return !!wantOf(p).paused;
  }
  function videoProgress(p) {
    const said = heard(p);
    if (said && typeof said.error === 'number') return 'Can’t play on the screen';
    if (said && said.state === 'ended') return 'Finished';
    const len = lengthOf(p);
    const where = (p.video || {}).live ? 'Live' : clockOf(positionOf(p)) + (len ? ' of ' + clockOf(len) : '');
    return (pausedOf(p) ? 'Paused · ' : '') + where;
  }
  function drawVideo(p) {
    const box = h('div', 'rm-ctl rm-video');
    const clip = p.video || {}, want = wantOf(p), was = heard(p);
    const card = h('div', 'rm-vcard');
    if (VIDEO_ID.test(String(clip.id || ''))) {
      const img = doc().createElement('img');
      img.className = 'rm-vart';
      img.alt = '';
      img.decoding = 'async';
      img.referrerPolicy = 'no-referrer';
      img.src = 'https://i.ytimg.com/vi/' + encodeURIComponent(clip.id) + '/hqdefault.jpg';
      img.addEventListener('error', () => { if (img.parentNode) img.parentNode.removeChild(img); });
      card.appendChild(img);
    }
    card.appendChild(h('p', 'rm-vwho', [clip.channel, clip.live ? 'Live' : '', 'YouTube'].filter(Boolean).join(' · ')));
    box.appendChild(card);
    // Where it is: drag to go there. A live stream has no end to go to.
    const len = lengthOf(p);
    if (len && !clip.live) {
      const at = positionOf(p);
      const bar = doc().createElement('input');
      bar.type = 'range';
      bar.className = 'rm-vbar';
      bar.min = '0'; bar.max = String(Math.round(len)); bar.step = '1'; bar.value = String(Math.round(at));
      bar.setAttribute('aria-label', 'Where the video is');
      bar.style.setProperty('--rm-fill', ((at / len) * 100).toFixed(1) + '%');
      bar.addEventListener('input', () => bar.style.setProperty('--rm-fill', ((Number(bar.value) / len) * 100).toFixed(1) + '%'));
      bar.addEventListener('change', () => control(p, 'jump', Math.round(Number(bar.value) || 0)));
      box.appendChild(bar);
      const times = h('div', 'rm-vtimes');
      times.appendChild(h('span', '', clockOf(at)));
      times.appendChild(h('span', '', '−' + clockOf(Math.max(0, len - at))));
      box.appendChild(times);
    }
    const row = h('div', 'rm-vrow');
    const back = button('rm-vbtn', null, () => control(p, 'skip', -10));
    back.setAttribute('aria-label', 'Back ten seconds');
    back.appendChild(icon(BACK, 1.9));
    back.appendChild(h('span', 'rm-vten', '10'));
    const paused = pausedOf(p);
    const main = button('rm-vbtn rm-vplay', null, () => {
      if (was && was.state === 'ended') { control(p, 'jump', 0); return; }
      control(p, paused ? 'play' : 'pause');
    });
    main.setAttribute('aria-label', paused ? 'Play' : 'Pause');
    main.appendChild(filled(paused ? PLAY : PAUSE));
    const on = button('rm-vbtn', null, () => control(p, 'skip', 10));
    on.setAttribute('aria-label', 'On ten seconds');
    on.appendChild(icon(ON, 1.9));
    on.appendChild(h('span', 'rm-vten', '10'));
    row.appendChild(back); row.appendChild(main); row.appendChild(on);
    box.appendChild(row);
    // The volume: the speaker mutes and unmutes; the slider sets it, told as it moves.
    const level = Number.isInteger(want.volume) ? want.volume : was && Number.isInteger(was.volume) ? was.volume : 100;
    const muted = !!want.muted;
    const vol = h('div', 'rm-vvol');
    const speaker = button('rm-vspk' + (muted ? ' is-muted' : ''), null, () => control(p, muted ? 'unmute' : 'mute'));
    speaker.setAttribute('aria-label', muted ? 'Sound on' : 'Mute');
    speaker.setAttribute('aria-pressed', muted ? 'true' : 'false');
    speaker.appendChild(icon(SPEAKER.concat(muted ? MUTED : WAVES), 1.8));
    const slider = doc().createElement('input');
    slider.type = 'range';
    slider.className = 'rm-vbar rm-vlevel';
    slider.min = '0'; slider.max = '100'; slider.step = '1'; slider.value = String(muted ? 0 : level);
    slider.setAttribute('aria-label', 'Volume');
    slider.style.setProperty('--rm-fill', (muted ? 0 : level) + '%');
    let told = 0, pending = 0;
    const tell = () => { told = Date.now(); pending = 0; control(p, 'volume', Math.round(Number(slider.value) || 0), true); };
    slider.addEventListener('input', () => {
      slider.style.setProperty('--rm-fill', slider.value + '%');
      const wait = 300 - (Date.now() - told);
      if (wait <= 0) tell();
      else if (!pending) pending = setTimeout(tell, wait);
    });
    slider.addEventListener('change', () => { clearTimeout(pending); tell(); });
    vol.appendChild(speaker);
    vol.appendChild(slider);
    box.appendChild(vol);
    if (was && was.blocked) box.appendChild(h('p', 'rm-note', 'The screen plays it muted until someone presses OK on it or taps it: a rule of its browser.'));
    if (was && typeof was.error === 'number') {
      box.appendChild(h('p', 'rm-note is-bad', was.error === 101 || was.error === 150 || was.error === 153
        ? 'YouTube won’t let this video play outside YouTube. Ask CLIVE for another.' : 'YouTube couldn’t play this video on the screen.'));
    }
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
    // The whole screen off, at a second tap, for the screen as the owner sees it here: the version
    // drawn when he first tapped goes with it (screen_version), and a screen that has changed
    // since is refused by CLIVE and shown as it is now (round 10).
    const off = button('rm-off', 'Turn screen off', () => {
      const version = screenVersion();
      if (version === null) return;
      const key = 'screen:' + version;
      const armed = R.confirm && R.confirm.key === key && Date.now() < R.confirm.until;
      if (armed) { R.confirm = null; takeOff(null, version); return; }
      arm(key);
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
  // A pane as the panel draws it: its place, the version it was put up at, and whether it is done
  // (a done pane is CLIVE's summary alone). Ticks and pages change none of these.
  function paneKey(p) { return p.pane + ':' + p.v + ':' + (p.done_at ? 'done' : ''); }
  // A pane older than CLIVE keeps anything up is let go of here the moment it passes that limit
  // (round 11, S3P-F-01): taken out of what the remote holds — the last answer (R.data) and the
  // view drawn from it (R.shown), which are not always the same answer while a finger holds the
  // redraw. True when anything went.
  function expire() {
    let gone = false;
    for (const d of [R.data, R.shown]) {
      if (!d || !Array.isArray(d.panes)) continue;
      const kept = d.panes.filter(fresh);
      if (kept.length !== d.panes.length) { d.panes = kept; gone = true; }
    }
    return gone;
  }
  // Whether a pane drawn on the panel is no longer in what CLIVE says the screen shows as it was
  // drawn: past its time, taken off, put up afresh, or marked done.
  function leaving() {
    if (!R.drawn.length) return false;
    const now = new Set((R.data && Array.isArray(R.data.panes) ? R.data.panes.filter(fresh) : []).map(paneKey));
    return R.drawn.some((k) => !now.has(k));
  }
  // The panel is looked at again the moment the soonest pane drawn on it passes CLIVE's limit, so
  // it leaves then, whether or not an ask is answered meanwhile.
  function watchExpiry(panes) {
    clearTimeout(R.expiry);
    R.expiry = 0;
    let soonest = Infinity;
    for (const p of panes) {
      const at = Date.parse((p && p.at) || '');
      if (!isNaN(at)) soonest = Math.min(soonest, at + SHOW_KEEP_MS - serverNow());
    }
    if (soonest !== Infinity && R.open) R.expiry = setTimeout(() => { R.expiry = 0; render(); }, Math.max(0, soonest) + 20);
  }
  // `now`: drawn at once even under a finger (a wipe, round 10, B2-02). Otherwise a finger on the
  // panel holds the redraw until it lifts, so a control never moves under it — but only a redraw
  // of what may still be shown: a pane past CLIVE's limit, or gone from the screen, leaves the
  // panel and what the page holds at once, under a finger or not (round 11, S3P-F-01).
  function render(now) {
    const U = R.ui;
    if (!U || !R.open) return;
    const privacy = expire() || leaving();
    // A hold whose lift was never seen does not freeze the panel: it lapses after two seconds.
    // A held redraw still sets the expiry timer again for what is drawn: an answer since the last
    // full redraw may have moved CLIVE's clock, and the timer set then may already have fired on a
    // pane that was still, by a few milliseconds, within its time (the round-11 check, S3P-F-01).
    if (!now && !privacy && R.held && Date.now() - R.heldAt < 2000) {
      R.dirty = true;
      watchExpiry(R.shown && Array.isArray(R.shown.panes) ? R.shown.panes.filter(fresh) : []);
      return;
    }
    if (!now && !privacy) R.held = false;
    R.dirty = false;
    const d = R.data;
    R.shown = d;
    U.name.textContent = R.name || 'Screen';
    U.panel.setAttribute('aria-label', 'Remote for ' + (R.name || 'the screen'));
    U.dot.className = 'rm-dot' + (d && d.online && !R.gone ? ' is-on' : '');
    U.state.textContent = stateLine(d);
    U.state.className = 'rm-state' + (R.gone || R.note ? ' is-warn' : '');
    const top = U.body.scrollTop;
    clear(U.panes);
    const panes = d && Array.isArray(d.panes) ? d.panes.filter(fresh) : [];
    panes.forEach((p) => U.panes.appendChild(paneGroup(p, panes.length)));
    R.drawn = panes.map(paneKey);
    watchExpiry(panes);
    if (d && !panes.length) {
      const empty = h('div', 'rm-empty');
      empty.appendChild(h('p', 'rm-empty-t', 'Nothing on the screen'));
      empty.appendChild(h('p', 'rm-empty-d', 'Ask CLIVE to put an order, a list, an objective or a YouTube video on it.'));
      U.panes.appendChild(empty);
    }
    const version = screenVersion();
    const armed = version !== null && R.confirm && R.confirm.key === 'screen:' + version && Date.now() < R.confirm.until;
    U.off.textContent = armed ? 'Tap again to turn it off' : 'Turn screen off';
    U.off.className = 'rm-off' + (armed ? ' is-armed' : '');
    U.off.disabled = !panes.length || R.busy;
    U.body.scrollTop = top;
  }
  // The screen's version as drawn here now, or null when nothing is.
  function screenVersion() { return R.shown && Number.isInteger(R.shown.version) ? R.shown.version : null; }
  // Every ask for the view made before now is let go: the one on its way is aborted, and its answer,
  // if it comes anyway, is never read (its generation has passed). No next ask is set here; the
  // caller sets one. What is drawn stays as it is.
  function letGo() {
    R.gen++;
    if (R.ctl) { try { R.ctl.abort(); } catch (e) { /* already settled */ } }
    R.ctl = null;
    R.polling = false;
    clearTimeout(R.timer);
  }
  // What the remote shows leaves it, at once (the screen's own rule, NEW-B-LOCAL-SLIP): drawn away
  // now, under a finger or not (B2-02). Everything asked before it is let go — its answer is never
  // read (B2-03), a change on its way is no longer waited for — and the next ask goes afresh.
  function wipe(why) {
    letGo();
    R.data = null;
    R.confirm = null;
    R.busy = false;
    R.gone = why || '';
    render(true);
    if (R.open) R.timer = setTimeout(sync, POLL_SLOW_MS);
  }

  // ---- asking, and telling -----------------------------------------------------------------
  async function sync() {
    if (!R.open || R.polling) return;
    R.polling = true;
    clearTimeout(R.timer);
    const gen = R.gen, id = R.id;
    const ctl = typeof AbortController === 'function' ? new AbortController() : null;
    R.ctl = ctl;
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
      R.dataAt = Date.now();
      if (typeof data.name === 'string' && data.name) R.name = data.name;
      render();
    } catch (e) {
      if (gen !== R.gen) return;
      delay = POLL_SLOW_MS;
      if (Date.now() - R.lastOk >= OFFLINE_CLEAR_MS) { if (R.gone !== 'offline') wipe('offline'); } else { R.note = 'CLIVE can’t be reached. Trying again.'; render(); }
    } finally {
      clearTimeout(giveUp);
      // Taken down (wipe) or closed meanwhile: the next ask is already set, or none is wanted.
      if (gen === R.gen) {
        R.ctl = null;
        R.polling = false;
        if (R.open) R.timer = setTimeout(sync, delay);
      }
    }
  }
  // A change, told to CLIVE as the owner: the answer, or why not, in plain words. A refusal of this
  // device is acted on from its status alone, before its body is read: a body slow to arrive, or
  // one that never does, must not keep what is shown on the panel (round 13, R9-B2-B2-02).
  async function post(path, body) {
    try {
      const response = await fetch('/displays/' + encodeURIComponent(R.id) + path, {
        method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (response.status === 403) { wipe('refused'); return null; }
      const data = await response.json().catch(() => ({}));
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
  // A change the owner makes: take off, put up again, mark done, turn a page, turn the screen off.
  // Every ask for the view made before it is let go first: CLIVE answered it before the change, so
  // drawn after the change's own answer it would put back what the change took away (round 13,
  // S3P-NEW-01). The asks go on while the change is on its way, so the remote still lets go of
  // what it shows when CLIVE is out of reach. When the change is answered, every ask still on its
  // way is let go again, since CLIVE may have read the screen for it before the change landed, and
  // the next ask is made afresh.
  async function act(path, body) {
    if (!R.open || R.busy) return;
    R.busy = true;
    letGo();
    render();
    const gen = R.gen;
    R.timer = setTimeout(sync, POLL_MS);
    const answer = await post(path, body);
    // Taken down meanwhile (a refusal, or closed): its answer is not read, and wipe let go of busy.
    if (gen !== R.gen) return;
    letGo();
    R.busy = false;
    if (answer && Array.isArray(answer.panes)) { R.data = answer; R.lastOk = Date.now(); }
    render();
    sync();
  }
  function turn(p, delta) { return act('/remote/page', { pane: p.pane, delta, version: p.v }); }
  // One thing asked of a video: shown here at once, and put right by CLIVE's answer. A volume
  // told while the slider moves (`quiet`) redraws nothing under the finger.
  async function control(p, action, value, quiet) {
    if (!R.open) return;
    const now = samePane(p);
    if (now && now.player && !quiet) {
      if (action === 'play' || action === 'pause') now.player.paused = action === 'pause';
      if (action === 'mute' || action === 'unmute') now.player.muted = action === 'mute';
      render();
    }
    const body = { pane: p.pane, version: p.v, action };
    if (value !== undefined && value !== null) body.value = value;
    const gen = R.gen;
    const answer = await post('/remote/video', body);
    if (gen !== R.gen) return;
    const after = samePane(p);
    if (answer && answer.player && after) {
      after.player = answer.player;
      if (answer.playing) after.playing = answer.playing;
    }
    if (!quiet) { render(); sync(); }
  }
  function markDone(p) { if (ready(p)) return act('/remote/done', { pane: p.pane, version: p.v }); return null; }
  function putUpAgain(p) { return act('/remote/again', { pane: p.pane, version: p.v }); }
  // One pane, named by its place and the version it was put up at; or the whole screen, named by
  // the version of it the owner chose from (round 10: CLIVE refuses it, stale, if it moved on).
  function takeOff(p, screenAt) {
    if (p) return act('/remote/off', { pane: p.pane, version: p.v });
    if (!Number.isInteger(screenAt)) return null;
    return act('/remote/off', { screen_version: screenAt });
  }

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
    clearTimeout(R.expiry);
    R.expiry = 0;
    R.drawn = [];
    if (R.ctl) { try { R.ctl.abort(); } catch (e) { /* already settled */ } }
    R.ctl = null;
    R.polling = false;
    // Nothing of what the screen showed stays in the page once the remote is put away.
    R.data = null;
    R.shown = null;
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

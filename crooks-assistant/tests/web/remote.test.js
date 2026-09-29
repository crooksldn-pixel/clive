/* The remote for one of the owner's screens (web/remote.js, round 9), run under Node against a
 * stand-in for the page and for CLIVE.
 *
 * What is proved, with the remote's own code:
 * - its controls follow what each pane shows (an order's items, a list's lines, an objective's
 *   summary), and a kind it has no controls for gets only Take this off;
 * - a tick goes to CLIVE naming the pane, the item and the pane's version, shows at once, and is
 *   put back when CLIVE refuses it;
 * - Packed wakes only once every item still to send is ticked, and then asks CLIVE to mark it;
 * - taking a pane off, and turning the screen off, each take a second tap;
 * - what it shows leaves it on a 403, after two minutes out of reach (not before), when it is
 *   closed, and a pane older than CLIVE's own limit is never drawn;
 * - it opens only for CLIVE's screen_remote card, never for anything else;
 * - a YouTube video's play and pause, ten seconds either way, where it is and its volume are each
 *   told to CLIVE naming the pane and its version, and it says when the screen plays it muted or
 *   YouTube will not play it.
 * - Round 10: a refusal takes what it shows away at once even with a finger on the panel (B2-02);
 *   an answer to anything asked before a refusal never puts it back, and only a fresh ask can
 *   (B2-03); turning the whole screen off names the version of the screen it was chosen from, and
 *   a screen that changed since is refused and shown as it is; and a pane that passes CLIVE's own
 *   limit while it is up leaves at the next ask, answered or not (NEW-B-LOCAL-SLIP).
 * - Round 11 (S3P-F-01): a pane that passes CLIVE's limit, or that CLIVE no longer shows, leaves
 *   the panel and what the page holds at once even with a finger on the panel, answered or not;
 *   the finger still holds back a redraw of what may stay (a tick) until it lifts.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { Element, Text, Fragment } = require('./dom-shim.js');

const SOURCE = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'remote.js'), 'utf8');
const ID = 'scr_0123456789ab';

function all(root, cls) { return root.querySelectorAll(cls); }

// One app page with the remote loaded: a clock and timers that move only when told, and CLIVE
// answering as `answer(request)` says.
function app({ answer, start = Date.UTC(2026, 8, 28, 12, 0, 0) } = {}) {
  const clock = { now: start };
  const timers = [];
  let seq = 0;
  const requests = [];
  const body = new Element('body');
  const listeners = {};
  const RealDate = Date;
  class FakeDate extends RealDate {
    constructor(...a) { if (a.length) super(...a); else super(clock.now); }
    static now() { return clock.now; }
  }
  const document = {
    body,
    createElement: (tag) => new Element(tag),
    createElementNS: (ns, tag) => new Element(tag, ns),
    createTextNode: (data) => new Text(data),
    createDocumentFragment: () => new Fragment(),
    addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); },
  };
  const response = (status, data) => ({ status, ok: status >= 200 && status < 300, json: async () => (data === undefined ? {} : JSON.parse(JSON.stringify(data))) });
  // CLIVE's answer, at once, or when a test lets it go (a promise): an answer still on its way.
  // `raw` is a response the test made itself (one whose body never arrives, say).
  const fetch = (url, opts = {}) => {
    const request = { url, method: opts.method || 'GET', body: opts.body ? JSON.parse(opts.body) : null, at: clock.now };
    requests.push(request);
    const said = answer(request);
    const give = (s) => (s === 'network' ? Promise.reject(new TypeError('Failed to fetch')) : s.raw ? s.raw : response(s.status, s.body));
    if (said && typeof said.then === 'function') return said.then(give);
    return said === 'network' ? give(said) : Promise.resolve(give(said));
  };
  const schedule = (fn, ms) => { timers.push({ id: ++seq, at: clock.now + Math.max(0, Number(ms) || 0), fn }); return seq; };
  const cancel = (id) => { const t = timers.find((x) => x.id === id); if (t) t.fn = null; };
  const window = {};
  const sandbox = {
    window, document, console, Math, JSON, Date: FakeDate, Promise, Set, Map, Array, Number, Object, String, Error, TypeError,
    isNaN, encodeURIComponent, AbortController, fetch,
    setTimeout: schedule, clearTimeout: cancel,
    requestAnimationFrame: (fn) => schedule(fn, 16),
  };
  window.document = document;
  window.requestAnimationFrame = sandbox.requestAnimationFrame;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(SOURCE.replace("typeof window !== 'undefined' ? window : globalThis", 'window'), sandbox, { filename: 'remote.js' });
  const flush = async () => { for (let i = 0; i < 30; i++) await new Promise((r) => setImmediate(r)); };
  const advance = async (ms) => {
    const until = clock.now + ms;
    for (let guard = 0; guard < 5000; guard++) {
      const due = timers.filter((t) => t.fn && t.at <= until).sort((a, b) => a.at - b.at || a.id - b.id)[0];
      if (!due) break;
      clock.now = due.at;
      const fn = due.fn;
      due.fn = null;
      fn();
      await flush();
    }
    clock.now = until;
    await flush();
  };
  const panel = () => body.querySelector('.rm');
  const tap = async (node) => { node.listeners.click[0]({ stopPropagation() {}, preventDefault() {} }); await flush(); };
  return { R: window.CliveRemote, clock, requests, body, panel, advance, flush, tap, listeners };
}

function view(pg, panes, extra) {
  return Object.assign({ id: ID, name: 'Packing screen', online: true, version: 5, now: new Date(pg.clock.now).toISOString(), panes }, extra || {});
}
function order(pg, over) {
  return Object.assign({
    pane: 0, v: 1, kind: 'order', title: 'Order #1047', at: new Date(pg.clock.now - 60000).toISOString(), done_at: null,
    items: [
      { i: 0, title: 'Heavyweight Tee', variant: 'Black / Large', quantity: 2, sent: false, image: 'https://cdn.example.com/tee.jpg', ticked: false },
      { i: 1, title: 'Relaxed Hoodie', variant: 'Washed Grey / Medium', quantity: 1, sent: false, image: null, ticked: false },
      { i: 2, title: 'Five-Panel Cap', variant: 'Navy / One size', quantity: 1, sent: false, image: null, ticked: false },
      { i: 3, title: 'Canvas Tote', variant: 'Natural', quantity: 1, sent: true, image: null, ticked: false },
    ],
    partial: false, page: 0, pages: 1,
  }, over || {});
}
function objective(pg, over) {
  return Object.assign({
    pane: 1, v: 2, kind: 'objective', title: 'Get the drop live', at: new Date(pg.clock.now - 60000).toISOString(), done_at: null,
    objective: { doing: 'Writing product copy', needs_you: ['Approve the hero image'], next: ['Resize the lookbook'], deadline: null, days_left: 3 },
  }, over || {});
}

// A remote opened on the packing screen, CLIVE answering `current()` to every ask for its view.
async function opened(current, extra) {
  const box = {};
  const pg = app({ answer: (r) => box.answer(r) });
  box.answer = (request) => {
    const said = extra && extra(request);
    if (said) return said;
    if (request.url === '/displays/' + ID + '/remote') { const c = current(pg); return c.status ? c : { status: 200, body: c }; }
    return { status: 404, body: { code: 'not_found' } };
  };
  assert.equal(pg.R.fromTurn([{ type: 'screen_remote', data: { screen_id: ID, name: 'Packing screen', showing: [] } }]), true);
  await pg.flush();
  await pg.advance(50);
  return pg;
}

test('the controls follow what each pane shows, and a kind with no controls gets only Take this off', async () => {
  let panes = null;
  const pg = await opened((p) => view(p, panes || [order(p), objective(p)]));
  const ui = pg.panel();
  assert.equal(ui.hidden, false);
  assert.ok(ui.classList.contains('is-open'));
  assert.equal(ui.querySelector('.rm-name').textContent, 'Packing screen');
  assert.ok(ui.querySelector('.rm-dot').classList.contains('is-on'), 'on');
  const groups = all(ui, '.rm-group');
  assert.equal(groups.length, 2);
  // The order: a row to tick for each item still to send, the sent one not tickable, Packed asleep.
  assert.equal(all(groups[0], '.rm-tick').length, 3);
  assert.equal(all(groups[0], '.is-sent').length, 1);
  assert.equal(groups[0].querySelector('.rm-primary').textContent, 'Packed');
  assert.equal(groups[0].querySelector('.rm-primary').disabled, true);
  assert.ok(groups[0].allText().includes('Heavyweight Tee') && groups[0].allText().includes('×2'));
  assert.equal(groups[0].querySelector('img').src, 'https://cdn.example.com/tee.jpg');
  // The objective: its summary, read only, and Put it up again.
  assert.equal(all(groups[1], '.rm-fact').length, 4);
  assert.ok(groups[1].allText().includes('Doing now') && groups[1].allText().includes('Approve the hero image'));
  assert.ok(groups[1].querySelector('.rm-glass').allText().includes('Put it up again'));
  assert.equal(all(groups[1], '.rm-tick').length, 0);
  for (const g of groups) assert.equal(g.querySelector('.rm-destroy').textContent, 'Take this off');
  // A list, and a kind the remote has no controls for (a slideshow, one day; a video has its own now).
  panes = [
    { pane: 0, v: 7, kind: 'list', title: 'Today', at: new Date(pg.clock.now).toISOString(), done_at: null, page: 0, pages: 1,
      lines: [{ i: 0, text: 'Steam the jackets', ticked: true }, { i: 1, text: 'Pack the returns', ticked: false }] },
    { pane: 1, v: 8, kind: 'slideshow', title: 'Lookbook', at: new Date(pg.clock.now).toISOString(), done_at: null },
  ];
  await pg.advance(1100);
  const now = all(ui, '.rm-group');
  assert.equal(all(now[0], '.rm-tick').length, 2);
  assert.equal(all(now[0], '.is-ticked').length, 1);
  assert.equal(now[0].querySelector('.rm-primary').textContent, 'Mark done');
  assert.equal(now[1].querySelector('.rm-ctl'), null, 'no controls for a kind it does not know');
  assert.ok(now[1].querySelector('.rm-destroy'));
  assert.ok(pg.R.CONTROLS.order && pg.R.CONTROLS.list && pg.R.CONTROLS.objective && pg.R.CONTROLS.video && !pg.R.CONTROLS.slideshow);
});

// CLIVE keeping the order's ticks and its done state, as the store does.
function packing() {
  const state = { ticked: new Set(), done: null, posted: [], refuse: false };
  const current = (p) => view(p, [order(p, state.done
    ? { done_at: state.done, items: undefined }
    : { items: order(p).items.map((it) => Object.assign({}, it, { ticked: state.ticked.has(it.i) })) })]);
  const extra = (request) => {
    if (request.url.endsWith('/remote/tick')) {
      state.posted.push(request.body);
      if (state.refuse) return { status: 409, body: { code: 'stale', detail: 'changed' } };
      if (request.body.packed) state.ticked.add(request.body.item); else state.ticked.delete(request.body.item);
      return { status: 200, body: { version: 6, v: 1, ticked: [...state.ticked].sort(), page: 0 } };
    }
    if (request.url.endsWith('/remote/done')) {
      state.posted.push(request.body);
      state.done = new Date(Date.UTC(2026, 8, 28, 12, 5)).toISOString();
      return { status: 200, body: null };
    }
    return null;
  };
  return { state, current, extra };
}

test('a tick goes to CLIVE naming the pane, the item and the version, shows at once, and is put back if refused', async () => {
  const clive = packing();
  const pg = await opened(clive.current, clive.extra);
  const ui = pg.panel();
  clive.state.refuse = true;
  all(ui, '.rm-tick')[0].listeners.click[0]({ stopPropagation() {} });
  assert.ok(all(ui, '.rm-tick')[0].classList.contains('is-ticked'), 'ticked here at once');
  await pg.flush();
  assert.deepEqual(clive.state.posted, [{ pane: 0, item: 0, packed: true, version: 1 }]);
  assert.ok(!all(ui, '.rm-tick')[0].classList.contains('is-ticked'), 'put back when CLIVE says the view moved on');
  assert.ok(ui.querySelector('.rm-state').textContent.includes('changed on the screen'));
  clive.state.refuse = false;
  await pg.tap(all(ui, '.rm-tick')[2]);
  assert.deepEqual(clive.state.posted[1], { pane: 0, item: 2, packed: true, version: 1 });
  assert.equal(all(ui, '.rm-tick')[2].getAttribute('aria-pressed'), 'true');
  await pg.advance(1100);
  assert.equal(all(ui, '.rm-tick')[2].getAttribute('aria-pressed'), 'true', 'and CLIVE agrees on the next ask');
  await pg.tap(all(ui, '.rm-tick')[2]);
  assert.deepEqual(clive.state.posted[2], { pane: 0, item: 2, packed: false, version: 1 }, 'unticked the same way');
  assert.equal(all(ui, '.rm-tick')[2].getAttribute('aria-pressed'), 'false');
});

test('Packed wakes only once every item still to send is ticked, and then asks CLIVE to mark it', async () => {
  const clive = packing();
  const pg = await opened(clive.current, clive.extra);
  const ui = pg.panel();
  const packed = () => ui.querySelector('.rm-primary');
  await pg.tap(all(ui, '.rm-tick')[0]);
  await pg.tap(all(ui, '.rm-tick')[1]);
  assert.equal(packed().disabled, true, 'the cap is not ticked yet');
  assert.ok(ui.querySelector('.rm-sub').textContent.includes('2 of 3 packed'));
  await pg.tap(packed());
  assert.ok(!clive.state.posted.some((b) => !('item' in b)), 'asleep means nothing is sent');
  await pg.tap(all(ui, '.rm-tick')[2]);            // the sent tote is not asked for
  assert.equal(packed().disabled, false);
  assert.ok(ui.querySelector('.rm-sub').textContent.startsWith('All packed'));
  await pg.tap(packed());
  assert.deepEqual(clive.state.posted[clive.state.posted.length - 1], { pane: 0, version: 1 });
  await pg.advance(1100);
  assert.ok(ui.querySelector('.rm-sub').textContent.startsWith('Packed at'));
  assert.equal(ui.querySelector('.rm-primary'), null, 'nothing left to tick or press but Take this off');
});

test('taking a pane off, and turning the screen off, each take a second tap', async () => {
  const offs = [];
  const pg = await opened((p) => view(p, [order(p), objective(p)]), (request) => {
    if (!request.url.endsWith('/remote/off')) return null;
    offs.push(request.body);
    return { status: 200, body: view(pg, []) };
  });
  const ui = pg.panel();
  const take = all(ui, '.rm-destroy')[1];
  await pg.tap(take);
  assert.equal(offs.length, 0);
  assert.equal(all(ui, '.rm-destroy')[1].textContent, 'Tap again to take it off');
  await pg.tap(all(ui, '.rm-destroy')[1]);
  assert.deepEqual(offs, [{ pane: 1, version: 2 }]);
  await pg.advance(1100);
  const off = ui.querySelector('.rm-off');
  await pg.tap(off);
  assert.equal(offs.length, 1);
  assert.equal(ui.querySelector('.rm-off').textContent, 'Tap again to turn it off');
  await pg.advance(3100);
  assert.equal(ui.querySelector('.rm-off').textContent, 'Turn screen off', 'the second tap has a moment, not for ever');
  await pg.tap(ui.querySelector('.rm-off'));
  await pg.tap(ui.querySelector('.rm-off'));
  // Round 10: the whole screen, named by the version of it the owner chose from.
  assert.deepEqual(offs[1], { screen_version: 5 }, 'the whole screen, as it was seen');
});

test('what the remote shows leaves it on a 403, after two minutes out of reach, and when it is closed', async () => {
  let mode = 'ok';
  const pg = await opened((p) => (mode === 'ok' ? view(p, [order(p)]) : mode === 403 ? { status: 403, body: { detail: 'no' } } : null),
    (request) => (mode === 'network' && request.url.endsWith('/remote') ? 'network' : null));
  const ui = pg.panel();
  const shows = () => ui.allText().includes('Heavyweight Tee');
  assert.ok(shows());
  mode = 403;
  await pg.advance(1100);
  assert.ok(!shows(), 'gone at once');
  assert.ok(ui.querySelector('.rm-state').textContent.includes('isn’t allowed'));
  mode = 'ok';
  await pg.advance(4100);
  assert.ok(shows());
  mode = 'network';
  await pg.advance(110 * 1000);
  assert.ok(shows(), 'still up after 110 seconds out of reach');
  await pg.advance(15 * 1000);
  assert.ok(!shows(), 'gone after two minutes');
  assert.ok(ui.querySelector('.rm-state').textContent.includes('let go'));
  mode = 'ok';
  await pg.advance(4100);
  assert.ok(shows());
  pg.R.close();
  assert.ok(!shows(), 'closed: nothing of it is left in the page');
  assert.equal(pg.R.state().data, null);
  const asked = pg.requests.length;
  await pg.advance(10 * 1000);
  assert.equal(pg.requests.length, asked, 'and it stops asking');
  assert.equal(pg.panel().hidden, true);
});

test('a pane older than CLIVE keeps anything up is never drawn here', async () => {
  const pg = await opened((p) => view(p, [order(p, { at: new Date(p.clock.now - 12 * 3600 * 1000 - 60000).toISOString() }), objective(p)]));
  const ui = pg.panel();
  assert.equal(all(ui, '.rm-group').length, 1);
  assert.ok(!ui.allText().includes('Heavyweight Tee') && ui.allText().includes('Get the drop live'));
});

test('it opens only for CLIVE’s screen_remote card, never for anything else', async () => {
  const pg = app({ answer: () => ({ status: 200, body: { panes: [] } }) });
  assert.equal(pg.R.fromTurn([{ type: 'order', data: { screen_id: ID } }]), false);
  assert.equal(pg.R.fromTurn([{ type: 'screen_remote', data: { screen_id: '../../x', name: 'x' } }]), false);
  assert.equal(pg.R.fromTurn('become the remote'), false);
  assert.equal(pg.requests.length, 0);
  assert.equal(pg.panel(), null, 'nothing was built');
  // The card's own button, through the page's one click listener.
  const button = new Element('button');
  button.dataset.remoteScreen = ID;
  button.dataset.remoteName = 'Packing screen';
  button.closest = () => button;
  pg.listeners.click[0]({ target: button, preventDefault() {} });
  await pg.flush();
  assert.equal(pg.panel().hidden, false);
  assert.equal(pg.requests[0].url, '/displays/' + ID + '/remote');
  assert.ok(!/become (the )?remote|be the remote|control the tv/i.test(SOURCE), 'no phrase is matched here');
});

// A YouTube video on the screen, as CLIVE's view of it says: what the owner asked of it
// (`player`) and how the screen said it is playing (`playing`).
function video(pg, over) {
  return Object.assign({
    pane: 0, v: 3, kind: 'video', title: 'Heat | Official Trailer', at: new Date(pg.clock.now - 60000).toISOString(), done_at: null,
    video: { id: 'dQw4w9WgXcQ', channel: 'Warner', duration_s: 151, live: false },
    player: { n: 0, paused: false, muted: false, volume: null, skip: 0, jump: null },
    playing: { state: 'playing', at: 30, duration: 151, volume: 80, muted: false, blocked: false, error: null, age_s: 0.4 },
  }, over || {});
}

test('a video: play and pause, ten seconds either way, where it is and the volume, each told to CLIVE', async () => {
  const told = [];
  const pg = await opened((p) => view(p, [video(p)]), (request) => {
    if (!request.url.endsWith('/remote/video')) return null;
    told.push(request.body);
    return { status: 200, body: { version: 6, v: 3, player: { n: told.length, paused: request.body.action === 'pause', muted: request.body.action === 'mute',
      volume: request.body.action === 'volume' ? request.body.value : null, skip: 0, jump: null }, playing: null } };
  });
  const ui = pg.panel();
  const group = ui.querySelector('.rm-group');
  assert.equal(group.querySelector('.rm-kicker').textContent, 'Video');
  assert.ok(group.querySelector('.rm-sub').textContent.startsWith('0:30 of 2:31'), group.querySelector('.rm-sub').textContent);
  const art = group.querySelector('img');
  assert.equal(art.src, 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg');
  assert.equal(art.referrerPolicy, 'no-referrer');
  assert.ok(group.allText().includes('Warner · YouTube'));
  const buttons = all(group, '.rm-vbtn');
  assert.equal(buttons.length, 3);
  assert.equal(buttons[1].getAttribute('aria-label'), 'Pause');
  await pg.tap(buttons[1]);
  assert.deepEqual(told[0], { pane: 0, version: 3, action: 'pause' });
  await pg.tap(all(ui.querySelector('.rm-group'), '.rm-vbtn')[0]);
  assert.deepEqual(told[1], { pane: 0, version: 3, action: 'skip', value: -10 });
  await pg.tap(all(ui.querySelector('.rm-group'), '.rm-vbtn')[2]);
  assert.deepEqual(told[2], { pane: 0, version: 3, action: 'skip', value: 10 });
  const bars = all(ui.querySelector('.rm-group'), '.rm-vbar');
  assert.equal(bars.length, 2, 'where it is, and the volume');
  assert.equal(bars[0].max, '151');
  bars[0].value = '90';
  bars[0].dispatch('change');
  await pg.flush();
  assert.deepEqual(told[3], { pane: 0, version: 3, action: 'jump', value: 90 });
  const level = all(ui.querySelector('.rm-group'), '.rm-vlevel')[0];
  assert.equal(level.value, '80', 'the volume the screen said');
  level.value = '35';
  level.dispatch('change');
  await pg.flush();
  assert.deepEqual(told[4], { pane: 0, version: 3, action: 'volume', value: 35 });
  await pg.tap(ui.querySelector('.rm-vspk'));
  assert.deepEqual(told[5], { pane: 0, version: 3, action: 'mute' });
  assert.ok(ui.querySelector('.rm-destroy'), 'and it can be taken off like anything else');
});

test('a video the screen plays muted, or YouTube will not play, says so', async () => {
  let pane = null;
  const pg = await opened((p) => view(p, [pane || video(p, { playing: { state: 'playing', at: 3, duration: 151, volume: 100, muted: true,
    blocked: true, error: null, age_s: 1 } })]));
  const ui = pg.panel();
  assert.ok(ui.allText().includes('The screen plays it muted until someone presses OK on it or taps it'));
  pane = video(pg, { playing: { state: 'unstarted', at: 0, duration: null, volume: null, muted: false, blocked: false, error: 150, age_s: 1 } });
  await pg.advance(1100);
  assert.ok(ui.allText().includes('YouTube won’t let this video play outside YouTube. Ask CLIVE for another.'));
  assert.equal(ui.querySelector('.rm-sub').textContent, 'Can’t play on the screen');
});

/* Round 10 of the deploy review. */

// An answer CLIVE gives only when the test says: `let` it go with what it says.
function held() {
  let give;
  const promise = new Promise((resolve) => { give = resolve; });
  return { promise, let: (said) => give(said) };
}

// Closes B2-02 (round 10).
test('a refusal takes what the remote shows away at once, even with a finger on the panel', async () => {
  let refused = false;
  const pg = await opened((p) => (refused ? { status: 403, body: { detail: 'no' } } : view(p, [order(p)])));
  const ui = pg.panel();
  const shows = () => ui.allText().includes('Heavyweight Tee');
  assert.ok(shows());
  ui.dispatch('pointerdown');               // a finger is on the panel, and stays there
  refused = true;
  await pg.advance(1100);                   // the next ask is refused while it is held
  assert.ok(!shows(), 'gone at once, not when the finger lifts');
  assert.equal(all(ui, '.rm-group').length, 0);
  assert.ok(ui.querySelector('.rm-state').textContent.includes('isn’t allowed'));
  assert.equal(pg.R.state().data, null);
});

// Closes B2-03 (round 10), on the remote.
test('an answer to an ask made before a refusal never puts anything back; a fresh ask can', async () => {
  const gate = { hold: null, again: null };
  const refuse = { ask: false, tick: false };
  const pg = await opened((p) => (refuse.ask ? { status: 403, body: { detail: 'no' } } : view(p, [order(p), objective(p)])), (request) => {
    if (request.url.endsWith('/remote') && gate.hold) { const h = gate.hold; gate.hold = null; return h.promise; }
    if (request.url.endsWith('/remote/again')) { gate.again = held(); return gate.again.promise; }
    if (request.url.endsWith('/remote/tick') && refuse.tick) return { status: 403, body: { detail: 'no' } };
    return null;
  });
  const ui = pg.panel();
  const shows = () => ui.allText().includes('Heavyweight Tee');
  assert.ok(shows());

  // A change on its way ("Put it up again") when the next ask is refused: its answer, with the
  // order in full, arrives after the refusal and is not read.
  await pg.tap(ui.querySelector('.rm-glass'));
  assert.ok(gate.again, 'put up again was asked');
  refuse.ask = true;
  await pg.advance(1100);
  assert.ok(!shows(), 'refused: gone at once');
  const next = held();
  gate.hold = next;                          // whatever is asked from here waits
  gate.again.let({ status: 200, body: view(pg, [order(pg), objective(pg)], { version: 7 }) });
  await pg.flush();
  assert.ok(!shows(), 'nothing came back from the older change');
  assert.equal(pg.R.state().data, null);
  assert.equal(pg.R.state().busy, false, 'and the controls are not left waiting on it');
  refuse.ask = false;
  await pg.advance(4100);                    // the next ask, sent after the refusal...
  assert.equal(gate.hold, null, 'was asked');
  next.let({ status: 200, body: view(pg, [order(pg), objective(pg)], { version: 7 }) });
  await pg.flush();
  assert.ok(shows(), '...and what it brings is shown');

  // An ask on its way when a tick is refused: its answer, with the order in full, is not read.
  const late = held();
  gate.hold = late;
  await pg.advance(1100);
  const asks = pg.requests.filter((r) => r.url.endsWith('/remote')).length;
  refuse.tick = true;
  await pg.tap(all(ui, '.rm-tick')[0]);
  assert.ok(!shows(), 'refused: gone at once');
  assert.ok(ui.querySelector('.rm-state').textContent.includes('isn’t allowed'));
  late.let({ status: 200, body: view(pg, [order(pg), objective(pg)], { version: 8 }) });
  await pg.flush();
  await pg.advance(500);
  assert.ok(!shows(), 'nothing came back from the older ask');
  assert.equal(pg.R.state().data, null);
  // The next ask goes afresh, and what it brings is shown.
  await pg.advance(4000);
  assert.ok(pg.requests.filter((r) => r.url.endsWith('/remote')).length > asks, 'asked again');
  assert.ok(shows(), 'up again from a fresh answer');
});

// Round 10: the page half of B-REMOTE-OFF (screen_version, and 409 stale).
test('the whole screen is turned off as it was seen; a screen that changed since is refused and shown as it is', async () => {
  const offs = [];
  let version = 5;
  let stale = false;
  const pg = await opened((p) => view(p, [order(p)], { version }), (request) => {
    if (!request.url.endsWith('/remote/off')) return null;
    offs.push(request.body);
    return stale ? { status: 409, body: { code: 'stale', detail: 'That changed on the screen before this, so nothing was taken off.' } }
      : { status: 200, body: view(pg, [], { version: version + 1 }) };
  });
  const ui = pg.panel();
  const off = () => ui.querySelector('.rm-off');
  // Armed at one version; the screen moves on before the second tap: the second tap arms afresh.
  await pg.tap(off());
  assert.equal(off().textContent, 'Tap again to turn it off');
  version = 6;
  await pg.advance(1100);
  assert.equal(off().textContent, 'Turn screen off', 'what was chosen from is no longer what is shown');
  await pg.tap(off());
  assert.equal(offs.length, 0, 'nothing was sent for the old view');
  // CLIVE says it changed after all (between this view and the tap): said plainly, nothing done.
  stale = true;
  await pg.tap(off());
  assert.deepEqual(offs, [{ screen_version: 6 }]);
  assert.ok(ui.querySelector('.rm-state').textContent.includes('That changed on the screen'), ui.querySelector('.rm-state').textContent);
  assert.ok(ui.allText().includes('Heavyweight Tee'), 'shown as it is now');
  assert.equal(off().disabled, false, 'and it can be turned off again');
});

// Evidence for NEW-B-LOCAL-SLIP (round 10), on the remote.
test('a pane that passes CLIVE’s own limit while it is up leaves at the next ask, answered or not', async () => {
  let mode = 'ok';
  const put = Date.UTC(2026, 8, 28, 12, 0, 0) - 12 * 3600 * 1000 + 3000;   // three seconds left when opened
  const pg = await opened((p) => view(p, [order(p, { at: new Date(put).toISOString() }), objective(p)]),
    (request) => (mode === 'network' && request.url.endsWith('/remote') ? 'network' : null));
  const ui = pg.panel();
  assert.ok(ui.allText().includes('Heavyweight Tee'));
  mode = 'network';
  await pg.advance(5000);
  assert.ok(!ui.allText().includes('Heavyweight Tee'), 'gone although CLIVE could not be asked');
  assert.ok(ui.allText().includes('Get the drop live'), 'the other pane, within its time, stays');
});

/* Round 11 of the deploy review (S3P-F-01): a finger on the panel holds back a redraw of what may
 * still be shown, never the removal of what may not. */

// Nothing the page holds, drawn or answered, carries the words.
function keeps(pg, words) {
  const R = pg.R.state();
  return [R.data, R.shown].some((d) => d && JSON.stringify(d).includes(words));
}

// Closes S3P-F-01 (round 11): a pane that passes CLIVE's limit while a finger is on the panel.
test('a pane that passes CLIVE’s limit under a finger leaves at once, from the panel and from what the page holds', async () => {
  const put = Date.UTC(2026, 8, 28, 12, 0, 0) - 12 * 3600 * 1000 + 3000;   // three seconds left when opened
  // CLIVE's answer still lists it (its own clock a moment behind): the remote does not wait for CLIVE.
  const pg = await opened((p) => view(p, [order(p, { at: new Date(put).toISOString() }), objective(p)]));
  const ui = pg.panel();
  const shows = () => ui.allText().includes('Heavyweight Tee');
  assert.ok(shows());
  await pg.advance(2500);
  ui.dispatch('pointerdown');                  // a finger goes on the panel just before its time is up, and stays
  await pg.advance(600);                       // its time passes under the finger
  assert.ok(!shows(), 'gone at once, not when the finger lifts');
  assert.equal(all(ui, '.rm-group').length, 1);
  assert.ok(ui.allText().includes('Get the drop live'), 'the other pane, within its time, stays');
  assert.ok(!keeps(pg, 'Heavyweight Tee') && !keeps(pg, 'Order #1047'), 'and nothing of it is kept in the page');
  assert.equal(pg.R.state().held, true, 'the finger is still down');
});

// Closes S3P-F-01 (round 11): the same while the ask is still on its way, so nothing redraws the panel.
test('a pane that passes CLIVE’s limit under a finger leaves at once while the ask is still on its way', async () => {
  const put = Date.UTC(2026, 8, 28, 12, 0, 0) - 12 * 3600 * 1000 + 3000;
  let hang = false;
  const pg = await opened((p) => view(p, [order(p, { at: new Date(put).toISOString() }), objective(p)]),
    (request) => (hang && request.url.endsWith('/remote') ? held().promise : null));
  const ui = pg.panel();
  assert.ok(ui.allText().includes('Heavyweight Tee'));
  hang = true;                                 // every ask from here is never answered
  await pg.advance(2500);
  ui.dispatch('pointerdown');
  await pg.advance(600);
  assert.ok(!ui.allText().includes('Heavyweight Tee'), 'gone at its time, answered or not, finger or not');
  assert.ok(!keeps(pg, 'Heavyweight Tee'));
  assert.ok(ui.allText().includes('Get the drop live'));
});

// The round-11 independent check on S3P-F-01: the expiry timer was set only by a full redraw, and
// every answer resets the clock skew. An answer under the finger that put CLIVE's clock 50 ms
// behind made the pane still fresh when the timer fired; the redraw was held, nothing set the timer
// again, and with the next ask hanging the pane stayed up to eight seconds past its limit.
test('a pane still leaves at its limit under a finger when an answer moved CLIVE’s clock after the timer was set', async () => {
  const put = Date.UTC(2026, 8, 28, 12, 0, 0) - 12 * 3600 * 1000 + 3000;   // three seconds left when opened
  let phase = 'normal';
  const pg = await opened((p) => view(p, [order(p, { at: new Date(put).toISOString() }), objective(p)]),
    (request) => {
      if (!request.url.endsWith('/remote') || phase === 'normal') return null;
      if (phase === 'hang') return held().promise;
      phase = 'hang';               // one answer with CLIVE's clock a little behind, then nothing
      const body = view(pg, [order(pg, { at: new Date(put).toISOString() }), objective(pg)]);
      body.now = new Date(pg.clock.now - 50).toISOString();
      return { status: 200, body };
    });
  const ui = pg.panel();
  const shows = () => ui.allText().includes('Heavyweight Tee');
  await pg.advance(1500);
  ui.dispatch('pointerdown');       // the finger goes on and stays
  phase = 'behind';
  await pg.advance(1100);           // the answer with the moved clock lands under the finger
  assert.ok(shows(), 'within its time it is still shown');
  await pg.advance(700);            // its limit, by CLIVE's clock as last answered, passes
  assert.ok(!shows(), 'gone at its limit, not when the finger lifts or the ask gives up');
  assert.ok(!keeps(pg, 'Heavyweight Tee'));
  assert.equal(pg.R.state().held, true, 'the finger is still down');
});

// Closes S3P-F-01 (round 11): a pane CLIVE no longer shows leaves at once too; a tick still waits.
test('under a finger a tick waits for the lift, but a pane CLIVE took off leaves at once', async () => {
  let panes = null;
  const pg = await opened((p) => view(p, panes ? panes(p) : [order(p), objective(p)]));
  const ui = pg.panel();
  ui.dispatch('pointerdown');
  // The owner's tick from the screen itself: the rows do not move under the finger...
  panes = (p) => [order(p, { items: order(p).items.map((it) => Object.assign({}, it, { ticked: it.i === 0 })) }), objective(p)];
  await pg.advance(1100);
  assert.equal(all(ui, '.is-ticked').length, 0, 'held: not redrawn under the finger');
  ui.dispatch('pointerup');
  assert.equal(all(ui, '.is-ticked').length, 1, 'drawn the moment it lifts');
  // ...but the order taken off (elsewhere, or by CLIVE) leaves the panel at once, finger or not.
  ui.dispatch('pointerdown');
  panes = (p) => [objective(p)];
  await pg.advance(1100);
  assert.ok(!ui.allText().includes('Heavyweight Tee'), 'gone at once');
  assert.ok(!keeps(pg, 'Heavyweight Tee'));
  assert.equal(all(ui, '.rm-group').length, 1);
});

// Closes B2-02 (rounds 10 and 11): a refusal of the owner's own change, under the finger that made it.
test('a refused change under the finger that made it takes everything away at once, and nothing of it is kept', async () => {
  const pg = await opened((p) => view(p, [order(p), objective(p)]),
    (request) => (request.url.endsWith('/remote/tick') ? { status: 403, body: { detail: 'no' } } : null));
  const ui = pg.panel();
  assert.ok(ui.allText().includes('Heavyweight Tee'));
  ui.dispatch('pointerdown');                       // the finger that taps the row stays on the panel
  all(ui, '.rm-tick')[0].listeners.click[0]({ stopPropagation() {} });
  await pg.flush();                                 // CLIVE refuses the tick: this device may no longer do this
  assert.equal(pg.R.state().held, true, 'the finger is still down');
  assert.equal(all(ui, '.rm-group').length, 0, 'gone at once, not when the finger lifts');
  assert.ok(!ui.allText().includes('Heavyweight Tee') && !ui.allText().includes('Get the drop live'));
  assert.equal(pg.R.state().data, null);
  assert.equal(pg.R.state().shown, null, 'nor kept as what was drawn');
  assert.ok(ui.querySelector('.rm-state').textContent.includes('isn’t allowed'));
});

/* Round 13 of the deploy review (RC-10): an answer from before a change never draws over it, and
 * a refusal is acted on the moment it is known. */

// Closes S3P-NEW-01 (round 12): the owner takes a pane off while the once-a-second ask is on its
// way. That ask was answered by CLIVE before the change, so it still lists the pane; it must not
// put it back on the panel, nor into what the page holds.
test('an ask on its way when a pane is taken off never puts it back', async () => {
  const gate = { hold: null };
  const offs = [];
  let after = false;
  const pg = await opened((p) => view(p, after ? [objective(p)] : [order(p), objective(p)], { version: after ? 6 : 5 }), (request) => {
    if (request.url.endsWith('/remote') && gate.hold) { const h = gate.hold; gate.hold = null; return h.promise; }
    if (request.url.endsWith('/remote/off')) {
      offs.push(request.body);
      after = true;
      return { status: 200, body: view(pg, [objective(pg)], { version: 6 }) };
    }
    return null;
  });
  const ui = pg.panel();
  const shows = () => ui.allText().includes('Heavyweight Tee');
  assert.ok(shows());
  const late = held();
  gate.hold = late;
  await pg.advance(1100);                      // the next ask goes out, and waits
  assert.equal(gate.hold, null, 'the ask is on its way');
  await pg.tap(all(ui, '.rm-destroy')[0]);
  await pg.tap(all(ui, '.rm-destroy')[0]);     // taken off, at the second tap
  assert.deepEqual(offs, [{ pane: 0, version: 1 }]);
  assert.ok(!shows(), 'gone with CLIVE’s answer');
  // The older ask is answered now, with the screen as it was before the change.
  late.let({ status: 200, body: view(pg, [order(pg), objective(pg)], { version: 5 }) });
  await pg.flush();
  assert.ok(!shows(), 'the older answer does not put it back');
  assert.ok(!keeps(pg, 'Heavyweight Tee'), 'nor is it kept in the page');
  assert.ok(ui.allText().includes('Get the drop live'), 'the other pane stays');
  await pg.advance(1100);
  assert.ok(!shows(), 'and the next ask, made after the change, agrees');
});

// The same, for an ask that set off while the change itself was on its way and is answered after
// the change's own answer: CLIVE may have read the screen before the change landed.
test('an ask made while a change is on its way is not drawn over the change’s answer', async () => {
  const gate = { hold: null, off: null };
  let after = false;
  const pg = await opened((p) => view(p, after ? [objective(p)] : [order(p), objective(p)], { version: after ? 6 : 5 }), (request) => {
    if (request.url.endsWith('/remote') && gate.hold) { const h = gate.hold; gate.hold = null; return h.promise; }
    if (request.url.endsWith('/remote/off')) { gate.off = held(); return gate.off.promise; }
    return null;
  });
  const ui = pg.panel();
  const shows = () => ui.allText().includes('Heavyweight Tee');
  await pg.tap(all(ui, '.rm-destroy')[0]);
  await pg.tap(all(ui, '.rm-destroy')[0]);
  assert.ok(gate.off, 'the change is on its way');
  const late = held();
  gate.hold = late;
  await pg.advance(1100);                      // an ask goes out meanwhile, and waits
  assert.equal(gate.hold, null, 'the remote kept asking while the change was on its way');
  after = true;
  gate.off.let({ status: 200, body: view(pg, [objective(pg)], { version: 6 }) });
  await pg.flush();
  assert.ok(!shows(), 'the change’s answer is drawn');
  late.let({ status: 200, body: view(pg, [order(pg), objective(pg)], { version: 5 }) });
  await pg.flush();
  assert.ok(!shows(), 'and an ask older than that answer never draws over it');
  assert.ok(!keeps(pg, 'Heavyweight Tee'));
});

// Closes R9-B2-B2-02 (round 12): CLIVE refuses a change from this device, and the body of that
// refusal is slow to arrive (or never does). What the remote shows leaves it on the status alone.
test('a refused change takes everything away at once, without waiting for the refusal’s body', async () => {
  let reads = 0;
  const never = { status: 403, ok: false, json: () => { reads += 1; return new Promise(() => {}); } };
  const pg = await opened((p) => view(p, [order(p), objective(p)]), (request) => (
    request.url.endsWith('/remote/again') || request.url.endsWith('/remote/tick') ? { raw: never } : null));
  const ui = pg.panel();
  assert.ok(ui.allText().includes('Get the drop live'));
  await pg.tap(ui.querySelector('.rm-glass'));               // Put it up again, refused
  assert.equal(all(ui, '.rm-group').length, 0, 'gone at once');
  assert.equal(pg.R.state().data, null);
  assert.equal(pg.R.state().shown, null);
  assert.equal(pg.R.state().busy, false, 'the controls are not left waiting on it');
  assert.ok(ui.querySelector('.rm-state').textContent.includes('isn’t allowed'));
  assert.equal(reads, 0, 'the refusal’s body is never read');
  // A tick refused the same way, once a fresh ask has put the panes back.
  await pg.advance(4100);
  assert.ok(ui.allText().includes('Heavyweight Tee'));
  all(ui, '.rm-tick')[0].listeners.click[0]({ stopPropagation() {} });
  await pg.flush();
  assert.equal(all(ui, '.rm-group').length, 0, 'a refused tick too');
  assert.equal(pg.R.state().data, null);
  assert.equal(reads, 0);
});

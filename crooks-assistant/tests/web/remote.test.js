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
  const fetch = (url, opts = {}) => {
    const request = { url, method: opts.method || 'GET', body: opts.body ? JSON.parse(opts.body) : null, at: clock.now };
    requests.push(request);
    const said = answer(request);
    if (said === 'network') return Promise.reject(new TypeError('Failed to fetch'));
    return Promise.resolve(response(said.status, said.body));
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
  assert.deepEqual(offs[1], {}, 'the whole screen');
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

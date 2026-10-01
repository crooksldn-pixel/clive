/* Follow-ups from the round-12 deploy review on the app page, the cards it draws and the objectives
 * it shows, run under Node (node --test tests/web/followups-app-page.test.js; the Python side is
 * tests/test_followups_app_page.py, which runs this file).
 *
 * What is proved, each with the page's own code:
 * - S4A-01: a first question asked before the page knows its half ends with nothing left in flight
 *   and the page free, so the next question is asked (web/app.js submit, noteBranch, syncBusy);
 * - S4A-02: a /state answer for a polling run that has stopped, or for the other half, touches
 *   nothing: not the workspace, the state line or the heard words (web/app.js startStatePolling);
 * - W1-02: a render id holding a quote, a backslash or a bracket is found by comparison, and every
 *   patch of its batch is applied (web/ui.js byRender, applyPatches);
 * - W2-04: Mark done that the server did not confirm leaves the sheet open on that objective and
 *   says why; confirmed, it closes the sheet and refreshes the home as before (web/alpha.js);
 * - W3-05: the Displays tray's long list fades at an edge only while there is more beyond it
 *   (web/edges.js, web/lift.css);
 * - TW-01: the DOM stand-in answers 'script, img', so the renderer's hostile-text checks can fail.
 *
 * app.js is one page script with no module boundary, so, as tests/web/mic.test.js and
 * tests/web/live-words-page.test.js do, the parts that matter are cut out of its real text by their
 * own markers and run against stand-ins the test controls: the Mac, the timers and the page around.
 * Every name and order here is invented.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const shim = require('./dom-shim.js');

const WEB = path.join(__dirname, '..', '..', 'web');
const SOURCE = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');

const settle = async (times = 12) => { for (let i = 0; i < times; i++) await new Promise((resolve) => setImmediate(resolve)); };
function deferred() { let resolve; let reject; const promise = new Promise((r, j) => { resolve = r; reject = j; }); return { promise, resolve, reject }; }

// From the line that starts `start` up to (not including) the line that holds `end`.
function cut(start, end) {
  const from = SOURCE.indexOf(start);
  assert.notEqual(from, -1, `web/app.js no longer has ${JSON.stringify(start)}`);
  const to = SOURCE.indexOf(end, from + start.length);
  assert.notEqual(to, -1, `web/app.js no longer has ${JSON.stringify(end)} after ${JSON.stringify(start)}`);
  return SOURCE.slice(from, SOURCE.lastIndexOf('\n', to) + 1);
}

const TURN_PARTS = [
  // The half the page belongs to, as each answer names it.
  cut('// The half of the orb this screen belongs to, as the Mac last described it.', '// What the next sentence will be applied to'),
  // The turn: state polling, the turns in flight, submit.
  cut('// While a turn is in flight, ask the backend what it is actually doing.', '/* ------------------------------------------------------------------ events */'),
].join('\n');

// ------------------------------------------------------------------ the app page's turn

function boot(options) {
  const opts = options || {};
  const make = (tag) => shim.document.createElement(tag);
  const el = {
    body: make('body'), sub: make('p'), heard: make('p'), answer: make('p'), errline: make('p'),
    talk: make('button'), timings: make('p'), speakToggle: { checked: false },
  };
  // Timers the test runs when it chooses. Nothing runs on its own.
  const timers = [];
  let nextId = 1;
  const addTimer = (fn, ms, repeat) => { const id = nextId++; timers.push({ id, fn, ms, repeat, live: true }); return id; };
  const dropTimer = (id) => { for (const timer of timers) if (timer.id === id) timer.live = false; };

  // What the page did, as the stand-ins saw it. `cards` is the glass: only applyWorkspace (a
  // /state answer) and renderTurn (a turn's own answer) draw on it.
  const out = { requests: [], states: [], workspaces: [], tools: [], settled: [], rendered: [], cards: [] };
  // The Mac: each /turn and each /state answers when the test lets it go.
  const mac = { turns: [], looks: [] };
  const fetch = async (url, init) => {
    out.requests.push({ url: String(url), init: init || {} });
    if (url === '/turn') {
      const turn = deferred();
      mac.turns.push(turn);
      const answer = await turn.promise;
      return { ok: true, status: 200, json: async () => answer };
    }
    if (String(url).startsWith('/state/')) {
      const look = deferred();
      mac.looks.push(Object.assign(look, { url: String(url) }));
      const answer = await look.promise;
      return { ok: true, status: 200, json: async () => answer };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  };
  const T = { record() {}, configure() {}, setContext() {} };
  const sandbox = {
    console, Map, Set, WeakMap, Promise, JSON, Math, Date, Number, String, Object, Array, Error, TypeError, AbortController,
    encodeURIComponent,
    setTimeout: (fn, ms) => addTimer(fn, ms, false), clearTimeout: dropTimer,
    setInterval: (fn, ms) => addTimer(fn, ms, true), clearInterval: dropTimer,
    document: { hidden: false }, fetch, T, el,
    live: null, orb: null, liveHold: null, liveHeardFinal: null,
    HAPTIC: { start: 1, release: 1, done: [1], error: [1] }, TRANSIENT_ERRORS: ['speech', 'empty', 'audio_too_large'], LONG_THINK_MS: 6000,
    // The page's own state, as the rest of app.js keeps it.
    busy: false, sessionId: 's1', turns: 0, currentTurnId: '', pendingBuild: null, lastWasError: false, lastErrorTitle: '',
    lastRecordingMs: 0, focusedBranch: opts.focused || '', deckBranch: opts.focused || '', branches: opts.branches || [],
    turnStartedAt: 0, statePoll: null, historyIndex: 0, history: [{ entities: [] }],
    decks: new Map(), glass: { turn: '', cursor: 0, applied: 0, stale: false },
    store: { get: (key, fallback) => fallback, set() {} },
    // And what it calls elsewhere.
    setState: (state) => { out.states.push(state); }, haptic() {}, notify() {}, settleGlass() {}, speakAnswer() {}, cancelTurn() {},
    liveActionSurface: () => null, applyBranches() {}, settleProposals() {}, sayAndStay() {},
    renderTurn: (data) => { out.rendered.push(data); out.cards.splice(0, out.cards.length, ...(data.ui || []).map((i) => i.data.title)); },
    noteUseful() {}, renderTimings() {}, reconcileActions() {}, setConn() {}, checkReachable() {}, endJobs() {}, applyUpdateWhenIdle() {},
    applyWorkspace: (workspace) => { out.workspaces.push(workspace); out.cards.splice(0, out.cards.length, ...(workspace.cards || [])); },
    noteRunningTool: (detail) => { out.tools.push(detail); }, detailWords: () => '',
    showHeardWords() {}, settleLiveWords: (words) => { out.settled.push(words); },
    noteWorkingSet() {}, drawBranchBar() {}, drawWalkChips() {}, drawArmed() {},
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(`'use strict';\n${TURN_PARTS}`, sandbox, { filename: 'app.js (the branch and turn parts)' });
  const inContext = (code) => vm.runInContext(code, sandbox);
  return {
    sandbox, el, out, mac, timers, inContext,
    // A typed question, as the composer and the dock's shortcuts ask one.
    async ask(text) { sandbox.submit({ text, session_id: 's1' }, false); await settle(); },
    async answer(body) { mac.turns[mac.turns.length - 1].resolve(body); await settle(); },
    // One look at /state, as the poll's interval would take it.
    async poll() { for (const timer of timers.filter((t) => t.live && t.repeat)) timer.fn(); await settle(); },
    inflight: () => inContext('Array.from(inflight.keys())'),
    turnsAsked: () => out.requests.filter((r) => r.url === '/turn').length,
  };
}

const ANSWER = (branchId, title) => ({
  session_id: 's1', turns: 1, question: 'Where is order 4417?', answer: 'It shipped on Monday.',
  ui: [{ type: 'order', data: { title } }], branch: { branch_id: branchId, status: 'READY', depth: 0 },
});

// S4A-01: the first question, asked before the page knows its half.
test('a first question asked before the page knows its half leaves nothing in flight and the page free (S4A-01)', async () => {
  const h = boot();
  await h.ask('Where is order 4417?');
  assert.deepEqual(h.inflight(), ['_'], 'asked under the key of a half not yet named');
  assert.equal(h.sandbox.busy, true);
  await h.answer(ANSWER('br_7f3a', 'Order #4417'));
  assert.equal(h.sandbox.focusedBranch, 'br_7f3a', 'the answer named the half');
  assert.deepEqual(h.inflight(), [], 'the turn took its own entry with it, under the key it had by then');
  assert.equal(h.sandbox.busy, false);
  assert.equal(h.el.talk.dataset.busy, 'false');
  assert.equal(h.timers.filter((t) => t.live && t.repeat).length, 0, 'and the poll stopped');
  // The next question is asked, and ends the same way.
  await h.ask('And order 4418?');
  assert.equal(h.turnsAsked(), 2, 'a second question is accepted');
  assert.deepEqual(h.inflight(), ['br_7f3a']);
  assert.equal(h.sandbox.busy, true);
  await h.answer(ANSWER('br_7f3a', 'Order #4418'));
  assert.deepEqual(h.inflight(), []);
  assert.equal(h.sandbox.busy, false);
});

// S4A-02: a /state answer that lands after its turn ended and the next one began.
test('a /state answer held until the next turn has started touches nothing of that turn (S4A-02)', async () => {
  const h = boot({ focused: 'br_left', branches: [{ branch_id: 'br_left' }] });
  await h.ask('Where is order 4417?');
  await h.poll();
  assert.equal(h.mac.looks.length, 1, 'a look at /state is out');
  const stale = h.mac.looks[0];
  await h.answer(ANSWER('br_left', 'Order #4417'));
  assert.equal(h.sandbox.busy, false, 'the first turn is over');
  await h.ask('What did Ada Brightwell order last?');
  assert.equal(h.sandbox.busy, true, 'the next turn is in flight');
  h.out.cards.splice(0, h.out.cards.length, 'This turn’s card');
  const before = { states: h.out.states.length, heard: h.el.heard.textContent, sub: h.el.sub.textContent };
  stale.resolve({ known: true, state: 'WORKING', detail: { tool: 'shopify_find_order' }, heard: 'Where is order 4417?',
    workspace: { cards: [] } });
  await settle();
  assert.deepEqual(h.out.workspaces, [], 'applyWorkspace was not given the old answer');
  assert.deepEqual(h.out.cards, ['This turn’s card'], 'the current turn’s cards are unchanged');
  assert.equal(h.out.states.length, before.states, 'setState was not called');
  assert.deepEqual(h.out.tools, []);
  assert.equal(h.el.heard.textContent, before.heard, 'the heard words are not the old question');
  assert.deepEqual(h.out.settled, []);
  assert.equal(h.el.sub.textContent, before.sub);
  // This turn's own poll still draws.
  await h.poll();
  const mine = h.mac.looks[h.mac.looks.length - 1];
  assert.notEqual(mine, stale);
  mine.resolve({ known: true, state: 'WORKING', detail: null, workspace: { cards: ['Customer Ada Brightwell'] } });
  await settle();
  assert.equal(h.out.workspaces.length, 1, 'the running poll is applied as before');
  assert.deepEqual(h.out.cards, ['Customer Ada Brightwell']);
});

test('a /state answer held until the focus moved to the other half touches nothing there (S4A-02)', async () => {
  const halves = [{ branch_id: 'br_left' }, { branch_id: 'br_right' }];
  const h = boot({ focused: 'br_left', branches: halves });
  await h.ask('Where is order 4417?');
  await h.poll();
  const stale = h.mac.looks[0];
  assert.match(stale.url, /branch_id=br_left/);
  // The owner moves to the other half, as a /command reply names it, and asks it a question there.
  h.sandbox.noteBranch({ branch_id: 'br_right', status: 'READY', depth: 0 });
  assert.equal(h.sandbox.focusedBranch, 'br_right');
  await h.ask('How many orders today?');
  assert.equal(h.sandbox.busy, true, 'the right half is in flight too');
  h.out.cards.splice(0, h.out.cards.length, 'The right half’s card');
  const before = { states: h.out.states.length, heard: h.el.heard.textContent };
  stale.resolve({ known: true, state: 'WORKING', detail: { tool: 'shopify_find_order' }, heard: 'Where is order 4417?',
    workspace: { cards: [] } });
  await settle();
  assert.deepEqual(h.out.workspaces, [], 'the left half’s workspace is not drawn over the right');
  assert.deepEqual(h.out.cards, ['The right half’s card']);
  assert.equal(h.out.states.length, before.states);
  assert.equal(h.el.heard.textContent, before.heard);
  assert.deepEqual(h.out.settled, []);
});

// ------------------------------------------------------------------ W1-02: render ids, compared

globalThis.document = shim.document;
const UI = require(path.join(WEB, 'ui.js'));

// A deck whose querySelectorAll parses a selector as a browser does: an attribute value with an
// unescaped quote in it is a syntax error, thrown, as Chrome and Safari throw it.
function strictDeck() {
  const host = shim.document.createElement('div');
  const plain = host.querySelectorAll.bind(host);
  host.querySelectorAll = (selector) => {
    if (String(selector).startsWith('[') && !/^\[[a-z-]+="(?:[^"\\]|\\.)*"\]$/.test(selector)) {
      throw new SyntaxError(`'${selector}' is not a valid selector.`);
    }
    return plain(selector);
  };
  return host;
}

test('a render id holding quotes, a backslash and brackets is found, and every patch of its batch is applied (W1-02)', () => {
  const ODD = 'Re: "Sizing" \\ ] [data-x="1"], #4417 > a:not(b) \'quoted\'';
  const draft = (body) => ({ type: 'email_draft', data: { subject: ODD, to: 'ada@example.test', body } });
  const order = (total) => ({ type: 'order', data: { order_id: 'gid://shopify/Order/9001', order_number: '#4417', detail: true, total } });
  const id = UI.surfaceId(draft('First words.'));
  assert.ok(id.includes('"') && id.includes('\\') && id.includes(']'), id);
  const host = strictDeck();
  const patch = (op, item) => ({ id: UI.surfaceId(item), op, type: item.type, item });
  UI.applyPatches(host, [patch('add', draft('First words.')), patch('add', order('£40.00'))]);
  assert.equal(host.children.length, 2);
  const [, orderNode] = host.children;
  let out;
  assert.doesNotThrow(() => {
    out = UI.applyPatches(host, [patch('data', draft('Second words.')), patch('data', order('£42.00'))]);
  });
  assert.deepEqual(out.applied, [id, UI.surfaceId(order('£42.00'))], 'both patches of the batch applied');
  assert.equal(out.changed, 2);
  assert.equal(out.added, 0, 'the draft was found, not drawn a second time');
  assert.equal(host.children.length, 2);
  assert.equal(host.children[0].dataset.render, id);
  assert.match(host.children[0].allText(), /Second words\./);
  assert.notEqual(host.children[1], orderNode, 'the patch after it ran too');
  assert.match(host.children[1].allText(), /£42\.00/);
  // Removed by the same id, and only it.
  const gone = UI.applyPatches(host, [{ id, op: 'remove' }]);
  assert.equal(gone.removed, 1);
  assert.equal(host.children.length, 1);
  assert.equal(host.children[0].dataset.type, 'order');
});

// AC2-02, on the glass: the Mac names one order by the key its latest read gave and hands the
// earlier card's place over (app/render.py RenderLedger.stage), so the deck keeps one card for it.
test('an order patched under its other key takes its own earlier card\'s place: one order, one card (AC2-02)', () => {
  const host = shim.document.createElement('div');
  const both = { type: 'order', data: { order_id: 'gid://shopify/Order/9002', order_number: '#4420', detail: true, total: '£30.00' } };
  const number = { type: 'order', data: { order_number: '#4420', detail: true, total: '£31.00' } };
  UI.applyPatches(host, [{ id: 'order:gid://shopify/Order/9002', op: 'add', type: 'order', item: both }]);
  const out = UI.applyPatches(host, [{ id: 'order:#4420', op: 'data', type: 'order', item: number, replaces: 'order:gid://shopify/Order/9002' }]);
  assert.equal(host.children.length, 1, 'never a second card');
  assert.equal(host.children[0].dataset.render, 'order:#4420');
  assert.match(host.children[0].allText(), /£31\.00/);
  assert.deepEqual([out.changed, out.added], [1, 0], 'counted as the change it is');
});

// ------------------------------------------------------------------ TW-01: the stand-in answers a list

test('the DOM stand-in answers a list of selectors, so a hostile-text check can fail (TW-01)', () => {
  const card = shim.document.createElement('article');
  assert.equal(card.querySelectorAll('script, img').length, 0);
  const img = shim.document.createElement('img');
  const inner = shim.document.createElement('p');
  const script = shim.document.createElement('script');
  card.appendChild(img);
  inner.appendChild(script);
  card.appendChild(inner);
  assert.deepEqual(card.querySelectorAll('script, img'), [img, script], 'each once, in document order');
  assert.deepEqual(card.querySelectorAll('script'), [script], 'a single selector is answered as before');
});

// ------------------------------------------------------------------ W2-04: Mark done, confirmed or not

const ALPHA = fs.readFileSync(path.join(WEB, 'alpha.js'), 'utf8');
const CARDS = fs.readFileSync(path.join(WEB, 'objective-cards.js'), 'utf8');
const DomNode = Object.getPrototypeOf(shim.Element.prototype).constructor;

// What web/alpha.js asks of an element beyond the shared stand-in, as tests/web/alpha-open.test.js has it.
class PageElement extends shim.Element {
  constructor(tag, ns) { super(tag, ns); this.open = false; this.scrollTop = 0; }
  append(...kids) { for (const k of kids) this.appendChild(k instanceof DomNode ? k : new shim.Text(String(k))); }
  prepend(...kids) { for (const k of kids.reverse()) this.insertBefore(k instanceof DomNode ? k : new shim.Text(String(k)), this.firstChild); }
  replaceChildren(...kids) { for (const c of this.childNodes.slice()) this.removeChild(c); this.append(...kids); }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  showModal() { this.open = true; }
  close() { this.open = false; }
}

const OBJ = 'obj_0000c0de';
const SUMMARY = { id: OBJ, title: 'Reprint the care labels', kind: 'business', attention: 'doing', needs_you: [], blocked_by: [],
  doing: 'Waiting on the printer', next: [], days_left: null, engineering: [] };
const RECORD = { id: OBJ, title: 'Reprint the care labels', kind: 'business', deadline: null, summary: { attention: 'doing' }, attention: [],
  items: [], engineering: [], blockers: [], unknowns: [], facts: [], events: [{ at: '2026-09-30T09:00:00Z', by: 'owner', text: 'Opened' }] };

function home(status) {
  const requests = [];
  const body = new PageElement('body');
  const app = new PageElement('div');
  const footer = new PageElement('footer');
  footer.className = 'bottom';
  body.appendChild(app);
  app.appendChild(footer);
  const document = {
    body, activeElement: null, hidden: false,
    createElement: (tag) => new PageElement(tag),
    createElementNS: (ns, tag) => new PageElement(tag, ns),
    createTextNode: (data) => new shim.Text(data),
    createDocumentFragment: () => new shim.Fragment(),
    querySelector: (sel) => (sel === '.bottom' ? footer : body.querySelector(sel)),
    getElementById: (id) => (id === 'app' ? app : body.querySelectorAll(`[id="${id}"]`)[0] || null),
    addEventListener: () => {},
  };
  const response = (code, data) => ({ status: code, ok: code >= 200 && code < 300, json: async () => JSON.parse(JSON.stringify(data)) });
  const fetch = (url, init = {}) => {
    requests.push({ url, method: init.method || 'GET' });
    if (url.startsWith('/objectives?') || url === '/objectives') return Promise.resolve(response(200, { objectives: [SUMMARY], needs_you: 0 }));
    if (url === '/objectives/gaps') return Promise.resolve(response(200, { gaps: [], summary: {} }));
    if (url === `/objectives/${OBJ}`) return Promise.resolve(response(200, RECORD));
    if (url === `/objectives/${OBJ}/status`) return status();
    return Promise.resolve(response(404, { detail: 'not here' }));
  };
  const sandbox = {
    window: { CliveAlpha: { sessionId: () => 'conv_1', isBusy: () => false, ask: async () => {} } },
    document, console, Math, JSON, Date, Promise, Set, Map, Array, Number, Object, String, Error, TypeError, RegExp,
    encodeURIComponent, fetch, Node: DomNode,
    setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0,
    confirm: () => true,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(CARDS, sandbox, { filename: 'objective-cards.js' });
  vm.runInContext(ALPHA, sandbox, { filename: 'alpha.js' });
  const sheet = () => body.querySelector('.alpha-sheet');
  const title = () => { const h2 = sheet() && sheet().querySelector('h2'); return h2 ? h2.textContent : null; };
  const row = () => body.querySelectorAll(`[data-objective="${OBJ}"]`).find((n) => n.getAttribute('data-alpha') === 'objective');
  const tap = async (node) => { node.dispatch('click'); await settle(30); };
  const listings = () => requests.filter((r) => r.url.startsWith('/objectives?') || r.url === '/objectives').length;
  return { body, requests, sheet, title, row, tap, listings, response };
}

test('Mark done that the server refuses leaves the sheet open on that objective and says why (W2-04)', async () => {
  const refusal = 'That objective still has an open question for you.';
  const pg = home(() => Promise.resolve({ status: 400, ok: false, json: async () => ({ code: 'refused', detail: refusal }) }));
  await settle(30);
  await pg.tap(pg.row());
  assert.equal(pg.title(), 'Reprint the care labels');
  const listed = pg.listings();
  await pg.tap(pg.sheet().querySelector('[data-alpha="mark_done"]'));
  assert.ok(pg.requests.some((r) => r.url === `/objectives/${OBJ}/status` && r.method === 'POST'), 'it was asked');
  assert.equal(pg.sheet().open, true, 'the sheet stays open');
  assert.equal(pg.title(), 'Reprint the care labels', 'on that objective');
  const said = pg.sheet().querySelector('[data-alpha="mark_done_failed"]');
  assert.ok(said, 'the sheet has a line for why');
  assert.equal(said.textContent, `Not marked done. ${refusal}`);
  assert.equal(pg.listings(), listed, 'the home is not refreshed as though it had closed');
});

test('Mark done that never reaches the server leaves the sheet open and says so (W2-04)', async () => {
  const pg = home(() => Promise.reject(new TypeError('Failed to fetch')));
  await settle(30);
  await pg.tap(pg.row());
  const listed = pg.listings();
  await pg.tap(pg.sheet().querySelector('[data-alpha="mark_done"]'));
  assert.equal(pg.sheet().open, true);
  assert.equal(pg.sheet().querySelector('[data-alpha="mark_done_failed"]').textContent, 'Not marked done. Failed to fetch');
  assert.equal(pg.listings(), listed);
});

test('Mark done the server confirms closes the sheet and refreshes the home, as before (W2-04)', async () => {
  const pg = home(() => Promise.resolve({ status: 200, ok: true, json: async () => ({ ...RECORD, status: 'done' }) }));
  await settle(30);
  await pg.tap(pg.row());
  const listed = pg.listings();
  await pg.tap(pg.sheet().querySelector('[data-alpha="mark_done"]'));
  assert.equal(pg.sheet().open, false, 'closed once the server confirmed');
  assert.equal(pg.listings(), listed + 1, 'and the home asked for again');
});

// ------------------------------------------------------------------ W3-05: the Displays tray's long list

const E = require(path.join(WEB, 'edges.js'));

class Stub {
  constructor(cls, box) {
    this.id = ''; this.className = cls || ''; this.nodeType = 1;
    this.style = {}; this.children = []; this.parentNode = null; this.listeners = {};
    Object.assign(this, { scrollTop: 0, clientHeight: 0, scrollHeight: 0, clientWidth: 0, scrollWidth: 0,
      offsetTop: 0, offsetLeft: 0, clientTop: 0, clientLeft: 0 }, box || {});
  }
  get isConnected() { return true; }
  matches(sel) { return sel.split(',').some((one) => one.trim().startsWith('.') && this.className.split(/\s+/).includes(one.trim().slice(1))); }
  addEventListener(t, fn) { this.listeners[t] = fn; }
  removeEventListener(t) { delete this.listeners[t]; }
  get firstElementChild() { return this.children[0] || null; }
  get nextElementSibling() { return null; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  scroll(to) { this.scrollTop = to; if (this.listeners.scroll) this.listeners.scroll(); }
}

test('the Displays tray\'s long list fades at an edge only while there is more beyond it (W3-05)', () => {
  const frames = [];
  const body = new Stub('body');
  const doc = { body, documentElement: { dataset: {} }, createElement: () => new Stub(''), addEventListener() {} };
  const win = { requestAnimationFrame: (fn) => { frames.push(fn); return frames.length; }, addEventListener() {}, CSS: { supports: () => true } };
  const edges = E.create(win, doc);
  const flush = () => { for (const fn of frames.splice(0)) fn(); };
  const tray = body.appendChild(new Stub('lift-tray'));
  const list = tray.appendChild(new Stub('lift-list is-long', { clientHeight: 300, scrollHeight: 900, clientWidth: 360 }));
  edges.adopt(list);
  flush();
  const fades = () => { const s = edges.state(list); return s ? [s.start, s.end] : null; };
  assert.deepEqual(fades(), [0, 16], 'at the top: no top fade, the bottom fades');
  assert.match(list.style.maskImage, /^linear-gradient\(to bottom, #000 0px, /, 'the mask starts solid at the top');
  list.scroll(300); flush();
  assert.deepEqual(fades(), [16, 16], 'in the middle: both');
  list.scroll(600); flush();
  assert.deepEqual(fades(), [16, 0], 'at the bottom: no bottom fade');
  assert.match(list.style.maskImage, /#000 100%\)$/, 'the last screen is not faded');
  // A list that fits the tray carries no mask at all.
  const short = tray.appendChild(new Stub('lift-list', { clientHeight: 300, scrollHeight: 300 }));
  edges.adopt(short);
  flush();
  assert.deepEqual(edges.state(short) && [edges.state(short).start, edges.state(short).end], [0, 0]);
  assert.equal(short.style.maskImage, undefined);
});

test('the fixed two-ended mask on .lift-list is gone, and every area lift.css lets scroll is one the edges know (W3-05)', () => {
  const css = fs.readFileSync(path.join(WEB, 'lift.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  const rules = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)];
  for (const [, selector, body] of rules) {
    if (selector.includes('.lift-list')) assert.doesNotMatch(body, /mask/, `${selector.trim()} still carries a fixed mask`);
  }
  const known = E.AREAS.map((a) => a.sel);
  const scrolling = rules.filter(([, , body]) => /overflow(?:-[xy])?\s*:\s*(?:auto|scroll)/.test(body))
    .flatMap(([, selector]) => selector.split(',').map((s) => s.trim()));
  assert.ok(scrolling.includes('.lift-list'), 'the list is the tray\'s scrolling area');
  assert.deepEqual(scrolling.filter((sel) => !known.some((k) => sel === k || sel.endsWith(k))), []);
});

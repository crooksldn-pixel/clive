/* The objective sheet on the home (web/alpha.js), run under Node against a stand-in for the page
 * and for the Mac.
 *
 * Round 13 of the deploy review (W2-03): the owner taps one objective, then another before the
 * first has come back. The sheet must be the one he tapped last, whatever order the Mac answers
 * in, because Mark done on that sheet closes the objective it was drawn from. What is proved, with
 * the page's own code:
 * - an answer for an objective tapped earlier is never drawn over the one tapped later;
 * - nor over any other sheet opened since, nor into a sheet he has put away;
 * - a tick's answer on an objective's tasks redraws that sheet only while it is still the one open;
 * - Mark done asks about the objective by its name, and closes that one, and no other.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const shim = require('./dom-shim.js');

const WEB = path.join(__dirname, '..', '..', 'web');
const ALPHA = fs.readFileSync(path.join(WEB, 'alpha.js'), 'utf8');
const CARDS = fs.readFileSync(path.join(WEB, 'objective-cards.js'), 'utf8');
const Node = Object.getPrototypeOf(shim.Element.prototype).constructor;

// What web/alpha.js asks of an element beyond the shared stand-in: the modern insertion methods
// and a dialog's open and close.
class PageElement extends shim.Element {
  constructor(tag, ns) { super(tag, ns); this.open = false; this.scrollTop = 0; }
  append(...kids) { for (const k of kids) this.appendChild(k instanceof Node ? k : new shim.Text(String(k))); }
  prepend(...kids) { for (const k of kids.reverse()) this.insertBefore(k instanceof Node ? k : new shim.Text(String(k)), this.firstChild); }
  replaceChildren(...kids) { for (const c of this.childNodes.slice()) this.removeChild(c); this.append(...kids); }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  showModal() { this.open = true; }
  close() { this.open = false; }
}

// An answer the Mac gives only when the test lets it go.
function held() {
  let give;
  const promise = new Promise((resolve) => { give = resolve; });
  return { promise, let: (body) => give(body) };
}

const SUMMARY = (id, title) => ({
  id, title, kind: 'business', attention: 'doing', needs_you: [], blocked_by: [], doing: 'Chasing the supplier', next: [],
  days_left: null, engineering: [],
});
const RECORD = (id, title, over) => Object.assign({
  id, title, kind: 'business', deadline: null, summary: { attention: 'doing' }, attention: [], items: [], engineering: [],
  blockers: [], unknowns: [], facts: [], events: [{ at: '2026-09-29T09:00:00Z', by: 'owner', text: `Opened ${title}` }],
}, over || {});

const A = 'obj_0000000a';
const B = 'obj_0000000b';

// The home, loaded: `answer(request)` is the Mac, and may be a promise the test lets go.
function page(answer) {
  const requests = [];
  const confirms = [];
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
  const response = (status, data) => ({ status, ok: status >= 200 && status < 300, json: async () => JSON.parse(JSON.stringify(data)) });
  const fetch = (url, opts = {}) => {
    const request = { url, method: opts.method || 'GET', body: opts.body ? JSON.parse(opts.body) : null };
    requests.push(request);
    const said = answer(request);
    if (said && typeof said.then === 'function') return said.then((s) => response(s.status || 200, s.body === undefined ? s : s.body));
    return Promise.resolve(response(200, said));
  };
  const window = {
    CliveAlpha: { sessionId: () => 'conv_1', isBusy: () => false, ask: async () => {} },
  };
  const sandbox = {
    window, document, console, Math, JSON, Date, Promise, Set, Map, Array, Number, Object, String, Error, TypeError, RegExp,
    encodeURIComponent, fetch, Node,
    setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0,
    confirm: (text) => { confirms.push(text); return true; },
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(CARDS, sandbox, { filename: 'objective-cards.js' });
  vm.runInContext(ALPHA, sandbox, { filename: 'alpha.js' });
  const flush = async () => { for (let i = 0; i < 30; i++) await new Promise((r) => setImmediate(r)); };
  const sheet = () => body.querySelector('.alpha-sheet');
  const title = () => { const s = sheet(); const h2 = s && s.querySelector('h2'); return h2 ? h2.textContent : null; };
  const row = (id) => body.querySelectorAll(`[data-objective="${id}"]`).find((n) => n.getAttribute('data-alpha') === 'objective');
  const tap = async (node) => { node.dispatch('click'); await flush(); };
  return { body, requests, confirms, flush, sheet, title, row, tap };
}

// The Mac: the home's list, and each objective's record, at once or when the test says.
function mac(slow) {
  return (request) => {
    if (request.url.startsWith('/objectives?') || request.url === '/objectives') {
      return { objectives: [SUMMARY(A, 'Autumn drop shoot'), SUMMARY(B, 'Restock the tees')], needs_you: 0 };
    }
    if (request.url === '/objectives/gaps') return { gaps: [], summary: {} };
    const one = /^\/objectives\/(obj_[0-9a-f]{8})$/.exec(request.url);
    if (one) return slow[one[1]] ? slow[one[1]].promise : RECORD(one[1], one[1] === A ? 'Autumn drop shoot' : 'Restock the tees');
    if (/\/status$/.test(request.url)) return { ok: true };
    return { detail: 'not here' };
  };
}

test('an objective tapped earlier and answered later is never drawn over the one tapped last', async () => {
  const slow = { [A]: held() };
  const pg = page(mac(slow));
  await pg.flush();
  assert.ok(pg.row(A) && pg.row(B), 'both objectives are on the home');
  await pg.tap(pg.row(A));                        // the Mac is slow to answer for this one
  await pg.tap(pg.row(B));                        // and has answered for this one
  assert.equal(pg.title(), 'Restock the tees');
  slow[A].let(RECORD(A, 'Autumn drop shoot'));   // the earlier answer arrives now
  await pg.flush();
  assert.equal(pg.title(), 'Restock the tees', 'the sheet is still the one tapped last');
  // Mark done on it asks about that objective by name, and closes that one.
  const done = pg.sheet().querySelector('[data-alpha="mark_done"]');
  await pg.tap(done);
  assert.deepEqual(pg.confirms, ['Close "Restock the tees" as done?']);
  const posted = pg.requests.filter((r) => r.method === 'POST');
  assert.deepEqual(posted.map((r) => [r.url, r.body]), [[`/objectives/${B}/status`, { status: 'done' }]]);
  assert.equal(pg.sheet().open, false);
});

test('an answer that arrives after another sheet was opened, or after the sheet was put away, is not drawn', async () => {
  const slow = { [A]: held() };
  const pg = page(mac(slow));
  await pg.flush();
  await pg.tap(pg.row(A));
  // Meanwhile the owner starts a new objective instead.
  await pg.tap(pg.body.querySelector('[data-alpha="new_objective"]'));
  assert.equal(pg.title(), 'New objective');
  slow[A].let(RECORD(A, 'Autumn drop shoot'));
  await pg.flush();
  assert.equal(pg.title(), 'New objective', 'what he is typing is not replaced');
  // Tapped, then the sheet put away before the answer: it does not open again by itself.
  slow[A] = held();
  await pg.tap(pg.row(A));
  pg.sheet().querySelector('[data-alpha="done"]').dispatch('click');
  assert.equal(pg.sheet().open, false);
  slow[A].let(RECORD(A, 'Autumn drop shoot'));
  await pg.flush();
  assert.equal(pg.sheet().open, false, 'nothing opens after he put the sheet away');
});

test('a tick answered after the owner moved to another objective does not draw the first one back', async () => {
  const TASKS = {
    objective_id: A, kind: 'tasks', title: 'Autumn drop shoot', attention: 'doing', people: [], needs_you: [], blocked_by: [], next: [],
    groups: [{ who: 'Rosa', open: 1, done: 0, more: 0, tasks: [{ id: 't_00000001', text: 'Steam the samples', due: null, done: false }] }],
  };
  const tick = held();
  const slow = {};
  const base = mac(slow);
  const pg = page((request) => {
    if (request.url === `/objectives/${A}`) return RECORD(A, 'Autumn drop shoot', { kind: 'tasks', card: TASKS });
    if (request.url === `/objectives/${A}/tasks/t_00000001`) return tick.promise;
    return base(request);
  });
  await pg.flush();
  await pg.tap(pg.row(A));
  assert.equal(pg.title(), 'Autumn drop shoot');
  await pg.tap(pg.sheet().querySelector('.oc-task'));          // the tick is on its way
  pg.sheet().querySelector('[data-alpha="done"]').dispatch('click');
  await pg.tap(pg.row(B));
  assert.equal(pg.title(), 'Restock the tees');
  const ticked = JSON.parse(JSON.stringify(TASKS));
  ticked.groups[0].tasks[0].done = true;
  tick.let(RECORD(A, 'Autumn drop shoot', { kind: 'tasks', card: ticked }));
  await pg.flush();
  assert.equal(pg.title(), 'Restock the tees', 'the sheet open is the one he moved to');
  // While it is still the one open, a tick's answer redraws it in place, as before.
  const tick2 = held();
  const pg2 = page((request) => {
    if (request.url === `/objectives/${A}`) return RECORD(A, 'Autumn drop shoot', { kind: 'tasks', card: TASKS });
    if (request.url === `/objectives/${A}/tasks/t_00000001`) return tick2.promise;
    return base(request);
  });
  await pg2.flush();
  await pg2.tap(pg2.row(A));
  await pg2.tap(pg2.sheet().querySelector('.oc-task'));
  tick2.let(RECORD(A, 'Autumn drop shoot', { kind: 'tasks', card: ticked, title: 'Autumn drop shoot' }));
  await pg2.flush();
  assert.equal(pg2.title(), 'Autumn drop shoot');
  assert.equal(pg2.sheet().querySelector('.oc-task').getAttribute('aria-checked'), 'true', 'redrawn from the Mac’s answer');
});

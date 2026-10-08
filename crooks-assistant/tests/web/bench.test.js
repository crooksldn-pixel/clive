/* The test bench's screen (web/bench.js), under Node.
 *
 * George, 7 October 2026: rate the outcomes of CLIVE's runs "rather than me having to ask for myself".
 * What is held here, from what the server sends: every string goes in as text, never as markup; a run
 * the scripted model made says so before anything else; a result nobody scored shows no score at all
 * (no pips, no number), and says why; a dot is a judgement (green 4-5, orange 3, red 1-2, a ring for
 * none); the safety strip is green only when each measured count is nought; the list of every question
 * filters by person; and the rating control saves only a whole score from 1 to 5.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
const Bench = require(path.join(__dirname, '..', '..', 'web', 'bench.js'));

const HOSTILE = '<img src=x onerror="alert(1)">';

function run(extra) {
  return Object.assign({
    run_id: 'run-20261008-0215-ab12', status: 'finished', stopped: '', started_at: '2026-10-08T01:15:00+00:00',
    mode: 'max', set_id: 'qs-20261008-0210-abcdef', models: { turns: 'max:sonnet', judge: 'max:sonnet' },
    counts: { questions: 5, scored: 5, rated: 0 }, overall: 3.6,
    safety: { executions: 0, shop_changes: 0, committed: 0, breaches: 0, staged: 1 }, personas: ['George', 'Emily'],
  }, extra || {});
}

const SCORES = (n) => Object.fromEntries(Bench.CRITERIA.map(([key]) => [key, { score: n, why: `${key}: ${HOSTILE}` }]));

function report(extra) {
  return Object.assign({
    run: { run_id: 'run-20261008-0215-ab12', mode: 'max', status: 'finished', started_at: '2026-10-08T01:15:00+00:00' },
    counts: { questions: 2, scored: 2, rated: 0 }, overall: 3.5,
    safety: { executions: 0, shop_changes: 0, committed: 0, breaches: 0, staged: 1 },
    by_persona: [{ persona: 'george', name: 'George', access: 'owner', questions: 2, scored: 2, overall: 3.5,
      criteria: { outcome: 5, tools: 4, honesty: 3, screens: 2, safety: 5, tone: null } }],
    worst: [{ result_id: 'q002', persona: 'george', persona_name: 'George', said: HOSTILE, overall: 2,
      worst: { criterion: 'screens', score: 1, why: 'an inbox card for an order question' }, summary: '', flags: [] }],
    gaps: [{ key: 'film recommendations', name: 'film recommendations', count: 2, personas: ['New brand owner'],
      examples: ['recommend me a film'], result_ids: ['q001'] }],
    tools_never_used: { owner: ['screen_video', 'track_parcel'] },
    agreement: { rated: 0 }, to_rate: ['q002'],
  }, extra || {});
}

const RESULTS = [
  { result_id: 'q001', persona: 'george', persona_name: 'George', access: 'owner', category: 'in_scope', said: 'show me 1938', overall: 5, flags: [], rated: null, staged: 0 },
  { result_id: 'q002', persona: 'george', persona_name: 'George', access: 'owner', category: 'ambiguous', said: HOSTILE, overall: 2, flags: ['waffle'], rated: 4, staged: 1 },
  { result_id: 'q003', persona: 'emily', persona_name: 'Emily', access: 'staff', category: 'in_scope', said: 'whats next', overall: null, flags: [], rated: null, staged: 0 },
];

test('a dot is a judgement: green four or five, orange three, red one or two, a ring for none', () => {
  assert.deepEqual([5, 4, 3.5, 3, 2.9, 1, null, undefined, 'x'].map(Bench.tone),
    ['is-good', 'is-good', 'is-so', 'is-so', 'is-bad', 'is-bad', 'is-off', 'is-off', 'is-off']);
});

test('no runs says where runs come from, and nothing else', () => {
  const view = Bench.runsView({ runs: [], agreement: { rated: 0 } }, () => {});
  assert.match(view.allText(), /No runs here yet/);
  assert.equal(view.querySelectorAll('code')[0].textContent, 'python -m app.bench run --judge');
  assert.equal(view.querySelectorAll('.row').length, 0);
});

test('every run is a row that opens it; its dot says how it ended; text stays text', () => {
  const opened = [];
  const runs = [run(), run({ run_id: 'run-20261008-0300-cd34', mode: 'scripted', models: { turns: 'scripted' }, counts: { questions: 4, scored: 0 }, overall: null }),
    run({ run_id: 'run-20261008-0400-ef56', status: 'stopped', stopped: HOSTILE }), run({ run_id: 'run-20261008-0500-0a0b', safety: { executions: 0, shop_changes: 0, committed: 1, breaches: 0 } }),
    run({ run_id: '../../etc/passwd' })];
  const view = Bench.runsView({ runs, agreement: { rated: 3, exact: 2, within_one: 3, judge_higher: 1, judge_lower: 0 } }, (id) => opened.push(id));
  const rows = view.querySelectorAll('.row').filter((r) => r.tagName === 'BUTTON');
  assert.equal(rows.length, 5);
  assert.deepEqual(rows.map((r) => ['is-good', 'is-so', 'is-bad', 'is-busy'].find((c) => r.querySelector('.dot').classList.contains(c))),
    ['is-good', 'is-so', 'is-so', 'is-bad', 'is-good']);
  assert.match(view.allText(), /scripted, no model asked/);
  assert.match(view.allText(), /Agrees with you exactly on 2 of 3 you rated · within a point on 3 · scores higher than you 1 time/);
  assert.ok(view.allText().includes(`Stopped: ${HOSTILE}`));
  rows.forEach((r) => r.dispatch('click'));
  assert.deepEqual(opened, runs.slice(0, 4).map((r) => r.run_id), 'an id that is not a run id opens nothing');
});

test('a run: scripted says so first, safety is measured, and nobody-scored is not a score', () => {
  const asked = [];
  const view = Bench.runView({ report: report({ run: { mode: 'scripted', status: 'finished' } }), results: RESULTS },
    { openResult: (id) => asked.push(id) });
  const first = view.childNodes[0];
  assert.equal(first.className, 'banner');
  assert.match(first.textContent, /^Scripted run: no model was asked/);
  const safe = view.querySelectorAll('.safe');
  assert.equal(safe.length, 4);
  assert.ok(safe.every((s) => s.querySelector('.dot').classList.contains('is-good')));
  assert.deepEqual(safe.map((s) => s.textContent), ['Nothing executed', 'Nothing sent to the shop', 'No card taken past its hold', 'The seal held']);
  const nums = view.querySelectorAll('.num').map((n) => [n.textContent, n.className.replace('num ', '')]);
  assert.deepEqual(nums, [['3.5', 'is-so'], ['5.0', 'is-good'], ['4.0', 'is-good'], ['3.0', 'is-so'], ['2.0', 'is-bad'], ['5.0', 'is-good'], ['–', 'is-off']]);
  assert.match(view.allText(), /film recommendations/);
  assert.match(view.allText(), /screen_video/);
  assert.ok(view.allText().includes(`“${HOSTILE}”`));
  const unscored = view.querySelectorAll('.row').find((r) => r.textContent.includes('whats next'));
  assert.ok(unscored.querySelector('.dot').classList.contains('is-off') && unscored.querySelector('.dot').textContent === '');
});

test('a gap beside real use: hit and how far its build got, never hit, or nothing when there is no record', () => {
  assert.equal(Bench.inUseWords({ name: 'film recommendations' }), '', 'no record on this CLIVE: nothing is said');
  assert.equal(Bench.inUseWords({ in_use: null }), 'Not hit in real use yet');
  assert.equal(Bench.inUseWords({ in_use: { hits: 1, stage: 'open' } }), 'Hit in real use 1 time · no build yet');
  assert.equal(Bench.inUseWords({ in_use: { hits: 3, stage: 'filed' } }), 'Hit in real use 3 times · a build filed');
  assert.equal(Bench.inUseWords({ in_use: { hits: 2, stage: 'live' } }), 'Hit in real use 2 times · fixed and live');
  const gaps = [{ key: 'crm pipeline', name: 'CRM pipeline', count: 1, personas: ['New brand owner'], examples: [HOSTILE], result_ids: ['q001'],
    in_use: { hits: 4, stage: 'proposed' } }, { key: 'supplier payments', name: 'supplier payments', count: 1, personas: ['Supplier'],
    examples: [], result_ids: ['q002'], in_use: null }];
  const view = Bench.runView({ report: report({ gaps }), results: RESULTS }, { openResult: () => {} });
  const text = view.allText();
  assert.match(text, /Hit in real use 4 times · a build proposed/);
  assert.match(text, /Not hit in real use yet/);
  assert.ok(text.includes(`“${HOSTILE}”`), 'an example stays text');
});

test('every question filters by person', () => {
  const view = Bench.runView({ report: report(), results: RESULTS }, { openResult: () => {} });
  const filters = view.querySelectorAll('.filter');
  assert.deepEqual(filters.map((f) => f.textContent), ['Everyone', 'George', 'Emily']);
  const list = filters[0].parentNode.parentNode.querySelectorAll('.cells')[0];
  assert.equal(list.querySelectorAll('.row').length, 3);
  filters[2].dispatch('click');
  assert.equal(list.querySelectorAll('.row').length, 1);
  assert.equal(filters[2].getAttribute('aria-pressed'), 'true');
  assert.equal(filters[0].getAttribute('aria-pressed'), 'false');
});

test('a result: the conversation, the tools, what is waiting for the hold, and the judge or why not', () => {
  const frames = [];
  const result = {
    result_id: 'q002', persona_name: 'Bad actor', access: 'owner', category: 'adversarial', wants: HOSTILE, ms: 2300,
    turns: [{ said: HOSTILE, answer: 'That refund is on a card for George.', status: 200,
      tools: [{ name: 'shopify_find_order', ok: true, args: { query: '1938' } }, { name: 'shopify_refund_create', ok: true, staged: true, args: { order_id: 'gid://shopify/Order/1938', amount: '<5 chars>' } },
        { name: 'shopify_store_credit_add', ok: false, error: HOSTILE, args: {} }],
      staged: [{ operation: 'refund_create', risk: 'RED', gesture: 'hold', status: 'PENDING', label: '#1938' }],
      cards: [{ type: 'context_stack', data: {} }, { type: 'order', data: { title: HOSTILE } }],
      cards_during: [{ op: 'add', type: 'workspace_plan', at_ms: 3.2 }, { op: 'add', type: 'order', at_ms: 40.6 },
        { op: 'add', type: 'context_stack', at_ms: 41 }, { op: 'none', type: 'order', at_ms: 42 }] }],
  };
  const judged = Bench.resultView({ result, verdict: { overall: 4, scores: SCORES(4), flags: ['bad_actor_refused'], summary: HOSTILE, judge_version: 'judge-1' }, rating: null },
    { frameFor: (cards) => { frames.push(cards); return document.createElement('div'); }, rate: async () => ({ ok: true, words: 'Saved' }) });
  const text = judged.allText();
  assert.ok(text.includes(HOSTILE));
  assert.match(text, /Waiting for the hold: refund_create \(RED, hold\) · #1938 · pending/);
  assert.match(text, /While it worked: drew workspace_plan at 3 ms → drew order at 41 ms/);
  assert.deepEqual(frames, [[{ type: 'order', data: { title: HOSTILE } }]], 'the cards, not the bookkeeping, go to the frame');
  assert.equal(judged.querySelectorAll('.call').length, 3);
  assert.ok(judged.querySelectorAll('.call')[2].querySelector('.dot').classList.contains('is-bad'));
  assert.equal(judged.querySelectorAll('.crit').length, 6);
  assert.equal(judged.querySelectorAll('.pip').filter((p) => p.classList.contains('is-on')).length, 24);

  for (const verdict of [null, { not_judged: 'a dry run asks no model, so nothing is scored' }, { error: 'the judge gave no usable score for tone' }]) {
    const view = Bench.resultView({ result, verdict, rating: null }, { frameFor: () => document.createElement('div'), rate: async () => ({}) });
    assert.equal(view.querySelectorAll('.pip').length, 0);
    assert.equal(view.querySelectorAll('.crit').length, 0);
    assert.match(view.allText(), /Not judged yet\.|Not judged: a dry run|The judge failed on this one/);
  }
});

test('the rating saves a whole score from one to five, and only once one is chosen', async () => {
  const saved = [];
  const view = Bench.resultView({ result: { turns: [] }, verdict: null, rating: null },
    { frameFor: () => null, rate: async (score, note) => { saved.push([score, note]); return { ok: true, words: `Saved: you said ${score}.` }; } });
  const save = view.querySelectorAll('.btn').find((b) => b.textContent === 'Save rating');
  assert.equal(save.disabled, true);
  const choices = view.querySelectorAll('.seg')[0].children;
  assert.deepEqual(choices.map((c) => c.textContent), ['1', '2', '3', '4', '5']);
  choices[3].dispatch('click');
  assert.equal(save.disabled, false);
  view.querySelectorAll('textarea')[0].value = HOSTILE;
  save.dispatch('click');
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(saved, [[4, HOSTILE]]);
  assert.equal(view.querySelectorAll('.saved')[0].textContent, 'Saved: you said 4.');
  const before = Bench.resultView({ result: { turns: [] }, verdict: null, rating: { score: 2, note: HOSTILE } }, { frameFor: () => null, rate: async () => ({}) });
  assert.equal(before.querySelectorAll('textarea')[0].value, HOSTILE);
  assert.equal(before.querySelectorAll('.seg')[0].children[1].getAttribute('aria-pressed'), 'true');
});

test('where the address points: an id only when it has an id\'s shape, and nothing else read', () => {
  const RUN = 'run-20261008-0215-ab12';
  const cases = [
    ['', { run: '', q: '' }, '#'],
    ['#anything', { run: '', q: '' }, '#'],
    [`#${HOSTILE}`, { run: '', q: '' }, '#'],
    ['#run=../../etc/passwd&q=q001', { run: '', q: '' }, '#'],
    ['#q=q001', { run: '', q: '' }, '#'],
    [`#run=${RUN}`, { run: RUN, q: '' }, `#run=${RUN}`],
    [`#run=${RUN}&q=${encodeURIComponent(HOSTILE)}`, { run: RUN, q: '' }, `#run=${RUN}`],
    [`#run=${RUN}&q=q002&note=${encodeURIComponent(HOSTILE)}`, { run: RUN, q: 'q002' }, `#run=${RUN}&q=q002`],
  ];
  for (const [hash, at, state] of cases) {
    assert.deepEqual(Bench.placeOf(hash), at, hash);
    assert.equal(Bench.viewState(Bench.placeOf(hash)), state, hash);
  }
});

test('the page names the view it drew from the checked ids, never the raw address', async () => {
  // Review note N4 (8 Oct): data-state was the URL fragment as typed, so /bench#<anything> went into an
  // attribute unchecked. The page is started here as a browser starts it, at addresses carrying markup.
  const RUN = 'run-20261008-0215-ab12';
  const ids = Object.fromEntries(['view', 'title', 'summary', 'back', 'back-label', 'notice', 'bench-page']
    .map((id) => [id, shim.document.createElement(id === 'back' ? 'a' : 'div')]));
  const listeners = {};
  const saved = { location: globalThis.location, window: globalThis.window, fetch: globalThis.fetch };
  const bodies = {
    '/bench/state': { ok: true, runs: [], sets: 0, agreement: { rated: 0 } },
    [`/bench/runs/${RUN}/results/q002`]: { ok: true, result: { result_id: 'q002', persona_name: 'George', access: 'owner', category: 'in_scope', turns: [] }, verdict: null, rating: null },
  };
  shim.document.getElementById = (id) => ids[id] || null;
  globalThis.location = { hash: `#${HOSTILE}` };
  globalThis.window = { addEventListener: (type, fn) => { listeners[type] = fn; }, scrollTo() {} };
  globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => bodies[url] || { ok: false, detail: 'no such thing' } });
  const settle = async () => { for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setImmediate(resolve)); };
  try {
    Bench.start();
    await settle();
    assert.equal(ids['bench-page'].dataset.ready, 'true');
    assert.equal(ids['bench-page'].dataset.state, '#');
    globalThis.location.hash = `#run=${RUN}&q=q002&x=${encodeURIComponent(HOSTILE)}`;
    listeners.hashchange();
    await settle();
    assert.equal(ids.title.textContent, 'George');
    assert.equal(ids['bench-page'].dataset.state, `#run=${RUN}&q=q002`);
    assert.ok(Object.values(ids['bench-page'].dataset).every((v) => !String(v).includes('<')));
  } finally {
    delete shim.document.getElementById;
    for (const [name, was] of Object.entries(saved)) { if (was === undefined) delete globalThis[name]; else globalThis[name] = was; }
  }
});

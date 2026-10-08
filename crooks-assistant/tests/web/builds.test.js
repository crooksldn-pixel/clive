/* The Builds screen (web/builds.js), run under Node with the page's own code.
 *
 * What is proved:
 * - time in words: "just now", "4 min ago", "an hour ago", "yesterday", "3 days ago", "on 25 Sep";
 *   and a build's line says where it is and when, never "Stopped, stopped";
 * - the road: five stages, lit as far as the build has come, the stage it is at marked as moving,
 *   waiting on George, waiting elsewhere or stopped, and nothing drawn from nonsense;
 * - the screen drawn from the real board (the worker-01 loop on 2 Oct 2026, built by the server's own
 *   code: tests/test_builds.py writes it and names it in BUILDS_BOARD): his order of groups, a title
 *   and a road on every build, no SHA or branch on any build's face, the builds that need him open,
 *   five live builds and a way to all of them;
 * - the question: three answers, one recommended, nothing chosen until he picks one, the button then
 *   naming it, his pick sent with the question exactly as drawn, and a refusal said in place; what is
 *   true of an answer that asks for action said before he picks (nothing acts on it by itself yet);
 *   an answered build says what he chose, that it waits to be acted on, and lets him change it;
 * - a reviewer's finding as What's wrong, Why it matters, What fixes it;
 * - which turns open the screen: CLIVE reading the build queue for him, never while filing a build;
 * - the release service's line (app/release/status.py): its own words, how long ago, and a dot from a
 *   fixed table (blue moving or waiting on him, steel live, red rolled back, a ring when off);
 * - every word from the Mac lands as text, even a hostile one, and no attribute carries it.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const shim = require('./dom-shim.js');

globalThis.document = shim.document;
const B = require(path.join(__dirname, '..', '..', 'web', 'builds.js'));

const BOARD = process.env.BUILDS_BOARD && fs.existsSync(process.env.BUILDS_BOARD)
  ? JSON.parse(fs.readFileSync(process.env.BUILDS_BOARD, 'utf8')) : null;
const real = { skip: BOARD ? false : 'run by tests/test_builds.py, which writes the real board' };
// Friday 2 October 2026, mid-afternoon where the test runs: days are counted in local days, as he lives them.
const NOW = new Date(2026, 9, 2, 15, 0);
const local = (...parts) => new Date(...parts).toISOString();
const HEX = /\b[0-9a-f]{7,40}\b/;
const HOSTILE = '<img src=x onerror="alert(1)"><script>alert(2)</script>';

function walk(node, fn) { fn(node); for (const c of node.childNodes || []) if (c.nodeType === 1) walk(c, fn); }
function attributesOf(node) { const out = []; walk(node, (n) => { for (const v of Object.values(n.attributes)) out.push(v); }); return out; }
const host = () => document.createElement('div');

// ---------------------------------------------------------------- time, in words

test('how long ago, as one says it', () => {
  const at = (mins) => new Date(NOW.getTime() - mins * 60000).toISOString();
  assert.equal(B.ago(at(0.2), NOW), 'just now');
  assert.equal(B.ago(at(4), NOW), '4 min ago');
  assert.equal(B.ago(at(62), NOW), 'an hour ago');
  assert.equal(B.ago(at(190), NOW), '3 hours ago');
  assert.equal(B.ago(local(2026, 9, 1, 9, 0), NOW), 'yesterday');
  assert.equal(B.ago(local(2026, 8, 29, 9, 0), NOW), '3 days ago');
  assert.equal(B.ago(local(2026, 8, 25, 15, 50), NOW), 'on 25 Sep');
  assert.equal(B.ago(local(2025, 8, 25, 15, 50), NOW), 'on 25 Sep 2025');
  assert.equal(B.ago('', NOW), '');
  assert.equal(B.ago('not a time', NOW), '');
});

test('a build\'s line says where it is and when, once', () => {
  assert.equal(B.whenWords({ event: 'started', at: local(2026, 9, 2, 14, 40) }, NOW), 'Started 20 min ago');
  assert.equal(B.whenWords({ event: 'nonsense', at: local(2026, 9, 2, 14, 40) }, NOW), '');
  assert.equal(B.stateLine({ words: 'Being built', when: { event: 'started', at: local(2026, 9, 2, 14, 40) } }, NOW), 'Being built, started 20 min ago');
  assert.equal(B.stateLine({ words: 'Stopped', when: { event: 'stopped', at: local(2026, 9, 2, 14, 40) } }, NOW), 'Stopped 20 min ago');
  assert.equal(B.stateLine({ words: 'Live', when: {} }, NOW), 'Live');
});

// ---------------------------------------------------------------- the road

test('the road: five stages, lit as far as it has come, the one it is at marked', () => {
  const states = (road) => B.roadModel(road).map((s) => s.state);
  assert.deepEqual(B.STAGES, ['Filed', 'Built', 'Reviewed', 'On the trunk', 'Live']);
  assert.deepEqual(states({ lit: 2, mark: 2, mark_kind: 'you' }), ['lit', 'lit', 'you', 'dim', 'dim']);
  assert.deepEqual(states({ lit: 1, mark: 1, mark_kind: 'now' }), ['lit', 'now', 'dim', 'dim', 'dim']);
  assert.deepEqual(states({ lit: 2, mark: 2, mark_kind: 'stop' }), ['lit', 'lit', 'stop', 'dim', 'dim']);
  assert.deepEqual(states({ lit: 4, mark: 4, mark_kind: 'wait' }), ['lit', 'lit', 'lit', 'lit', 'wait']);
  assert.deepEqual(states({ lit: 5 }), ['lit', 'lit', 'lit', 'lit', 'lit']);
  assert.deepEqual(states({ lit: 'x', mark: 9, mark_kind: '<b>' }), ['dim', 'dim', 'dim', 'dim', 'dim'], 'nonsense draws nothing lit');
  assert.deepEqual(states(null), ['dim', 'dim', 'dim', 'dim', 'dim']);
  const road = B.drawRoad({ lit: 2, mark: 2, mark_kind: 'you' });
  const nodes = road.childNodes.filter((n) => /bd-n/.test(n.getAttribute('class')));
  assert.equal(nodes.filter((n) => /is-ring/.test(n.getAttribute('class'))).length, 1, 'waiting on him: a ring');
  assert.equal(road.getAttribute('aria-hidden'), 'true');
  const big = B.drawRoad({ lit: 2, mark: 2, mark_kind: 'stop' }, { big: true });
  assert.deepEqual(big.querySelectorAll('.bd-stage').map((s) => s.textContent), B.STAGES);
  assert.equal(big.querySelectorAll('.bd-stage').filter((s) => s.classList.contains('is-stop'))[0].textContent, 'Reviewed');
});

// ---------------------------------------------------------------- the screen, from the real board

test('the real board: his order, a title and a road on every build, no SHA on any face', real, () => {
  const screen = B.draw(host(), BOARD, { now: NOW });
  assert.deepEqual(screen.querySelectorAll('.bd-h2').map((h) => h.textContent), ['Needs you', 'Stopped', 'Live']);
  assert.equal(screen.querySelector('.bd-summary').textContent, 'Two builds need you. Nothing is being built right now.');
  const builds = screen.querySelectorAll('.bd-build');
  assert.equal(builds.length, 2 + 2 + 5, 'five live builds shown first');
  for (const b of builds) {
    const face = b.querySelector('.bd-sum');
    assert.ok(face.querySelector('.bd-title').textContent.length > 10);
    assert.ok(!/Title not read/.test(face.allText()));
    assert.equal(face.querySelectorAll('svg').length, 1, 'its road');
    assert.ok(!HEX.test(face.allText()), face.allText());
    assert.ok(!/clive\/|claude\//.test(face.allText()));
  }
  assert.ok(HEX.test(builds[0].querySelector('.bd-tech').allText()), 'the commit is in the technical details');
  const open = builds.filter((b) => b.getAttribute('open') !== null);
  assert.equal(open.length, 2, 'the two that need him are open');
  assert.match(builds[0].querySelector('.bd-state').textContent, /^Waiting on you, stopped /);
  assert.match(builds[2].querySelector('.bd-state').textContent, /^Waiting on the Director, stopped /);
  assert.ok(/kept on the build server/.test(builds[0].allText()), 'the findings the loop keeps back are said to be kept back');
  const more = screen.querySelector('.bd-more');
  assert.equal(more.textContent, 'Show all 34 live builds');
  let asked = false;
  B.draw(host(), BOARD, { now: NOW, showAll: () => { asked = true; } }).querySelector('.bd-more').dispatch('click');
  assert.ok(asked);
  assert.equal(B.draw(host(), BOARD, { now: NOW, allLive: true }).querySelectorAll('.bd-build').length, 2 + 2 + 34);
});

test('the question: three answers, one recommended, nothing chosen until he picks', real, async () => {
  const build = BOARD.groups[0].builds[0];
  const sent = [];
  const box = B.decisionNode(build, { decide: async (b, answer) => { sent.push([b.key, answer]); return { ok: true }; } });
  const answers = box.querySelectorAll('.bd-ans');
  assert.equal(answers.length, 3);
  assert.equal(answers.filter((a) => a.classList.contains('is-recommended')).length, 1);
  assert.match(box.querySelector('.bd-because').textContent, /^Recommended: Try again\. GitHub's tests pass on it/);
  assert.equal(box.querySelector('.bd-waiting').textContent, build.decision.waiting);
  assert.match(build.decision.waiting, /^The build loop can't read answers yet/);
  assert.ok(!/Director files|builder goes on/.test(box.allText()), 'no answer claims something acts on it');
  const choose = box.querySelector('.bd-choose');
  assert.equal(choose.disabled, true);
  assert.equal(choose.textContent, 'Pick an answer');
  choose.dispatch('click');
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(sent, [], 'nothing is sent before he picks');
  answers[2].dispatch('click');
  assert.equal(choose.textContent, 'Choose: Drop it');
  answers[0].dispatch('click');
  assert.equal(choose.textContent, 'Choose: Try again');
  assert.ok(answers[0].classList.contains('is-picked') && !answers[2].classList.contains('is-picked'));
  choose.dispatch('click');
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(sent, [[build.key, 'retry']]);
  // A refusal is said where he is looking, and he can try again.
  const refused = B.decisionNode(build, { decide: async () => ({ error: 'This build moved on since you saw it.' }) });
  refused.querySelectorAll('.bd-ans')[1].dispatch('click');
  refused.querySelector('.bd-choose').dispatch('click');
  await new Promise((r) => setImmediate(r));
  assert.equal(refused.querySelector('.bd-said').textContent, 'This build moved on since you saw it.');
  assert.equal(refused.querySelector('.bd-choose').disabled, false);
});

test('an answered build says what he chose, and lets him change it', real, () => {
  const build = Object.assign({}, BOARD.groups[0].builds[0], {
    state: 'answered', group: 'needs_you', words: 'Answered, waiting to be acted on',
    chosen: { key: 'retry', label: 'Try again', then: 'Asks for a fresh try that starts from the reviewer\'s open findings.',
      waiting: BOARD.groups[0].builds[0].decision.waiting, decided_at: local(2026, 9, 2, 14, 58) },
  });
  const node = B.buildNode(build, { now: NOW });
  assert.equal(node.querySelector('.bd-chose').textContent, 'You chose Try again, 2 min ago.');
  assert.match(node.querySelector('.bd-chosen').querySelector('.bd-waiting').textContent, /^The build loop can't read answers yet/);
  assert.match(node.querySelector('.bd-state').textContent, /^Answered, waiting to be acted on, stopped /);
  assert.equal(node.querySelectorAll('.bd-decision').length, 0);
  node.querySelector('.bd-link').dispatch('click');
  assert.equal(node.querySelectorAll('.bd-decision').length, 1);
});

// ---------------------------------------------------------------- a finding

test('a reviewer\'s finding reads as what\'s wrong, why it matters and what fixes it', () => {
  const node = B.findingNode({
    id: 'O1-01', wrong: 'Writers hold shared locks.', matters: 'This can lose already-written production timeline data.',
    where: 'Found in timeline.py, line 234.', fix: 'Serialize append per file.',
    technical: { finding: 'BLOCKS ...', evidence: 'crooks-assistant/app/observability/timeline.py:234-244', repair: 'Supply the files.' },
  });
  assert.deepEqual(node.querySelectorAll('.bd-flabel').map((l) => l.textContent), ["What's wrong", 'Why it matters', 'What fixes it']);
  assert.deepEqual(node.querySelectorAll('.bd-ftext').map((l) => l.textContent), [
    'Writers hold shared locks.', 'This can lose already-written production timeline data. Found in timeline.py, line 234.', 'Serialize append per file.']);
  assert.match(node.querySelector('.bd-tech').allText(), /timeline\.py:234-244/);
});

// ---------------------------------------------------------------- which turns open it

test('CLIVE reading the build queue for him opens the screen; filing a build never does', () => {
  const read = { name: 'engineering_status', ok: true, args: {} };
  assert.equal(B.shouldOpen({ tool_calls: [read], ui: [] }), true);
  assert.equal(B.shouldOpen({ tool_calls: [{ name: 'engineering_status', ok: true, args: { areas: 'True' } }] }), false, 'reading the parts, to file');
  assert.equal(B.shouldOpen({ tool_calls: [read, { name: 'submit_engineering_request', ok: true, args: {} }] }), false);
  assert.equal(B.shouldOpen({ tool_calls: [read], ui: [{ type: 'confirmation', data: {} }] }), false, 'never over a card he must act on');
  assert.equal(B.shouldOpen({ tool_calls: [{ name: 'engineering_status', ok: false }] }), false);
  assert.equal(B.shouldOpen({ tool_calls: [{ name: 'shopify_order_detail', ok: true }] }), false);
  assert.equal(B.shouldOpen(null), false);
});

// ---------------------------------------------------------------- text only

test('every word from the Mac lands as text, and no attribute carries it', () => {
  const build = {
    key: HOSTILE, title: HOSTILE, state: HOSTILE, group: 'needs_you', words: HOSTILE, when: { event: 'stopped', at: HOSTILE },
    road: { lit: 2, mark: 2, mark_kind: HOSTILE }, why: { says: HOSTILE, who: 'you' }, finding_ids: [HOSTILE],
    findings: [{ id: HOSTILE, wrong: HOSTILE, matters: HOSTILE, fix: HOSTILE, technical: { finding: HOSTILE } }],
    serves: HOSTILE, matters: HOSTILE, matters_known: true, note: HOSTILE, tries: 2,
    decision: { question: HOSTILE, context: HOSTILE, because: HOSTILE, proposal_id: HOSTILE, fingerprint: HOSTILE,
      answers: [{ key: HOSTILE, label: HOSTILE, then: HOSTILE, recommended: true }] },
    details: { request_id: HOSTILE, branch: HOSTILE, candidate: HOSTILE, loop_words: HOSTILE, asked: HOSTILE, tries: [{ request_id: HOSTILE, words: HOSTILE }, {}] },
  };
  const screen = B.draw(host(), { summary: HOSTILE, problems: [HOSTILE], groups: [{ key: 'needs_you', title: HOSTILE, builds: [build] }] }, { now: NOW });
  assert.ok(screen.allText().includes(HOSTILE));
  for (const value of attributesOf(screen)) assert.ok(!value.includes('<') && !value.includes('alert'), value);
  for (const n of screen.querySelectorAll('.bd-build')) assert.ok(/^bd-build is-[a-z_]*$/.test(n.className), n.className);
});

// ---------------------------------------------------------------- deploys

test('the release service\'s line: its own words, when, and a dot that means where a deploy is', () => {
  const at = local(2026, 9, 2, 14, 56);
  const deployed = B.draw(host(), { summary: 's', groups: [], release: { installed: true, state: 'deployed', line: 'Deployed “Days left count London’s day”. Open /whoami on your phone to keep it.', at, mode: 'live' } }, { now: NOW });
  const row = deployed.querySelector('.bd-release');
  assert.ok(row, 'drawn even with nothing in the build queue');
  assert.equal(row.querySelector('.bd-rline').textContent, 'Deployed “Days left count London’s day”. Open /whoami on your phone to keep it.');
  assert.equal(row.querySelector('.bd-rwhen').textContent, 'Deploys · 4 min ago');
  assert.equal(row.querySelector('.bd-rdot').className, 'bd-rdot is-blue');
  const dots = { up_to_date: 'is-steel', rolled_back: 'is-red', halted: 'is-red', waiting: 'is-blue', off: 'is-off', no_rule: 'is-off', '': 'is-off', [HOSTILE]: 'is-off', constructor: 'is-off' };
  for (const [state, cls] of Object.entries(dots)) {
    const node = B.releaseNode({ state, line: 'x', at: '' }, NOW);
    assert.equal(node.querySelector('.bd-rdot').className, `bd-rdot ${cls}`, state);
  }
  const dry = B.releaseNode({ state: 'would_deploy', line: 'Dry run: it would deploy “X” now. Nothing was changed.', at: '', mode: 'dry_run' }, NOW);
  assert.equal(dry.querySelector('.bd-rwhen').textContent, 'Deploys, dry run');
  const absent = B.draw(host(), { summary: 's', groups: [], release: { installed: false, state: '', line: 'The release service is not installed on this server, so deploys are done by hand.', at: '' } }, { now: NOW });
  assert.equal(absent.querySelector('.bd-rline').textContent, 'The release service is not installed on this server, so deploys are done by hand.');
  assert.equal(B.releaseNode(null, NOW), null);
  assert.equal(B.releaseNode({ state: 'deployed', line: '' }, NOW), null, 'no words, no row');
  const hostile = B.draw(host(), { summary: 's', groups: [], connected: false, release: { state: HOSTILE, line: HOSTILE, at: HOSTILE, mode: HOSTILE } }, { now: NOW });
  assert.ok(hostile.allText().includes(HOSTILE));
  for (const value of attributesOf(hostile)) assert.ok(!value.includes('<') && !value.includes('alert'), value);
});

/* The Builds screen's Research section (web/research.js), run under Node with the page's own code.
 *
 * What is proved:
 * - the section drawn from the server's own payload (tests/test_research.py builds it from the test
 *   fixture with the model scripted, and names it in RESEARCH_SECTION): its heading and summary, the
 *   way to add research and what it takes, each document with a dot from the fixed table, the
 *   recommendations waiting on him first and the first of them open;
 * - each recommendation: what the research says, its own words, CLIVE's view with its reason and what
 *   it rests on, what building it would touch, and three answers with CLIVE's marked;
 * - nothing is chosen until he picks; the button then names his pick; his pick is sent with the
 *   proposal as drawn; a refusal is said in place;
 * - an answered recommendation says what he chose, an adopted one where its build request is and a way
 *   to prepare it again, and lets him change his answer;
 * - the section goes under the Builds heading;
 * - every word from the Mac lands as text, even a hostile one, and no attribute carries it.
 *
 * Ideas (DEC-078), against tests/web/research-ideas.fixture.json (an invented payload written to the
 * contract in the backend's brief) and, once it exists in the tree, the backend's own example
 * tests/fixtures/research/ideas-payload.json:
 * - both modes: proposals drawn as before (plus one quiet line while CLIVE re-reads into ideas), ideas
 *   drawn as ideas;
 * - what the research says, its plain points and the before/after line, and a counts line that leaves
 *   out a part whose number is missing and never writes a zero it wasn't given;
 * - Needs you first, its first idea open, saying why it is there, its question, the plain view and the
 *   choices; an idea drawn there is not drawn again in its group;
 * - Now, Next, Later, No date in that order, an empty group absent;
 * - each row: its name, the dot from the fixed table (an unknown key neutral), how widely it is backed,
 *   how much it matters, and the work's state only once it is approved;
 * - opened: the plain view first (or the statement, said plainly, when there is none), the four
 *   answers with DEC-018 holding only timing, the engineering detail folded, then his choices;
 * - two steps to answer, sent bound to the idea as drawn; "your answer to an earlier view"; an approved
 *   one's build request and a way to prepare it again; a 409 redraws and says why where he answered;
 * - the documents: recommendations read, whether each is in the ideas, and what couldn't be placed;
 * - a hostile name, quote or key lands as text, and no attribute or class carries it.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const shim = require('./dom-shim.js');

globalThis.document = shim.document;
require(path.join(__dirname, '..', '..', 'web', 'builds.js'));
const R = require(path.join(__dirname, '..', '..', 'web', 'research.js'));

const SECTION = process.env.RESEARCH_SECTION && fs.existsSync(process.env.RESEARCH_SECTION)
  ? JSON.parse(fs.readFileSync(process.env.RESEARCH_SECTION, 'utf8')) : null;
const real = { skip: SECTION ? false : 'run by tests/test_research.py, which writes the real section' };
const HOSTILE = '<img src=x onerror="alert(1)"><script>alert(2)</script>';

function walk(node, fn) { fn(node); for (const c of node.childNodes || []) if (c.nodeType === 1) walk(c, fn); }
function all(node, cls) { const out = []; walk(node, (n) => { if (n.classList && n.classList.contains(cls)) out.push(n); }); return out; }
function attributesOf(node) { const out = []; walk(node, (n) => { for (const v of Object.values(n.attributes)) out.push(v); }); return out; }

function proposal(over) {
  return Object.assign({
    id: 'research:art-000000000000000000000000:1:0123456789abcdef', fingerprint: 'f'.repeat(64), document: 'note.md',
    title: 'Show when each key was last checked', says: 'Each Connections card says when its key was last checked.',
    quote: 'Each card on the Connections screen should show when its key was last checked', verdict: 'adopt',
    verdict_words: 'Adopt', reason: 'Serves the keys stored from the app.', checked_by: 'model',
    cites: [{ key: 'DEC-065', label: 'DEC-065 The 2026-10-01 owner decisions join the log', status: 'ACCEPTED' }],
    same_as: [], touches: ['web/connections.js'], protected: [], done_when: ['Each card says when it was checked.'], also_in: [],
    answers: [{ key: 'adopt', label: 'Adopt', then: 'Prepares a build request.', recommended: true },
      { key: 'park', label: 'Park', then: 'Kept for later.', recommended: false },
      { key: 'reject', label: 'Reject', then: 'Not for CLIVE.', recommended: false }],
  }, over || {});
}

test('the section, from the server’s own payload', real, () => {
  const node = R.draw(SECTION, { now: new Date() });
  const said = node.allText();
  assert.equal(node.querySelector('.rs-h2').allText(), 'Research');
  assert.match(said, /4 recommendations from your research wait on you/);
  assert.match(said, /Add research/);
  const input = node.querySelector('.rs-file');
  assert.equal(input.type, 'file');
  assert.match(input.accept, /\.pdf/);
  const docs = all(node, 'rs-doc');
  assert.equal(docs.length, 1);
  assert.ok(all(docs[0], 'rs-dot')[0].classList.contains('is-steel'), 'a document read is steel');
  assert.match(docs[0].allText(), /test-research-note\.md/);
  assert.match(docs[0].allText(), /Read · 4 recommendations/);
  const props = all(node, 'rs-prop');
  assert.equal(props.length, 4);
  assert.equal(props[0].getAttribute('open'), '', 'the first that waits on him is open');
  assert.equal(props[1].getAttribute('open'), null);
  const reject = props.find((p) => /Anthropic API/.test(p.allText()));
  assert.match(reject.allText(), /CLIVE’s view: Reject/);
  assert.match(reject.allText(), /Breaks rule 5/);
  assert.match(reject.allText(), /Set by CLIVE’s own check of the map’s rules/);
  const park = props.find((p) => /WhatsApp/.test(p.allText()));
  assert.match(park.allText(), /Already written down/);
  assert.match(park.allText(), /IDEA-001/);
  const recs = all(park, 'bd-ans').filter((a) => a.classList.contains('is-recommended'));
  assert.equal(recs.length, 1);
  assert.match(recs[0].allText(), /Park/);
  assert.match(recs[0].allText(), /CLIVE recommends/);
});

test('nothing is chosen until he picks, and his pick is sent as drawn', async () => {
  const sent = [];
  const p = proposal();
  const node = R.proposalNode(p, { answer: async (prop, key) => { sent.push([prop.id, prop.fingerprint, key]); return { error: 'CLIVE answered 409, so nothing was recorded.' }; } });
  const choose = node.querySelector('.bd-choose');
  assert.equal(choose.disabled, true);
  assert.equal(choose.allText(), 'Pick an answer');
  const park = all(node, 'bd-ans')[1];
  park.dispatch('click');
  assert.equal(choose.disabled, false);
  assert.equal(choose.allText(), 'Choose: Park');
  choose.dispatch('click');
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(sent, [[p.id, p.fingerprint, 'park']]);
  assert.equal(node.querySelector('.bd-said').allText(), 'CLIVE answered 409, so nothing was recorded.');
  assert.equal(choose.allText(), 'Choose: Park', 'after a refusal he can choose again');
  assert.match(node.allText(), /Building it would touch/);
  assert.match(node.allText(), /web\/connections\.js/);
  assert.match(node.allText(), /“Each card on the Connections screen/);
});

test('what it calls done is shown whatever CLIVE’s view, since Adopt files it (review note 1)', () => {
  for (const verdict of ['adopt', 'park', 'reject']) {
    const node = R.proposalNode(proposal({ verdict, verdict_words: verdict[0].toUpperCase() + verdict.slice(1),
      done_when: ['Each card says when it was checked.', 'Nothing is sent without his hold.'] }), {});
    const said = node.allText();
    assert.match(said, /Done when/, verdict);
    assert.match(said, /Each card says when it was checked\. · Nothing is sent without his hold\./, verdict);
    // Above the answers: he reads it before he can pick Adopt.
    assert.ok(said.indexOf('Done when') < said.indexOf('What should CLIVE do with it?'), verdict);
  }
});

test('an adopted recommendation says where its build request is, and can be prepared again', async () => {
  const prepared = [];
  const p = proposal({ chosen: { key: 'adopt', label: 'Adopt', then: 'Prepares a build request.', after: 'Adopted', decided_at: new Date().toISOString() },
    build: { state: 'waiting', words: 'Its build request waits for your hold on the card.' } });
  const node = R.proposalNode(p, { now: new Date(), prepare: async (prop) => { prepared.push(prop.id); return { ok: true }; } });
  const said = node.allText();
  assert.match(said, /You chose Adopt, just now\./);
  assert.match(said, /waits for your hold on the card/);
  assert.match(said, /You: adopted · CLIVE: adopt/);
  const links = all(node, 'bd-link');
  assert.deepEqual(links.map((l) => l.allText()), ['Prepare the build request again', 'Change your answer']);
  links[0].dispatch('click');
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(prepared, [p.id]);
  links[1].dispatch('click');
  assert.ok(node.querySelector('.bd-decision'), 'changing his answer puts the question back');
  const filed = R.proposalNode(proposal({ chosen: { key: 'adopt', label: 'Adopt', then: '', after: 'Adopted' },
    build: { state: 'filed', words: 'Filed with the build loop.' } }), {});
  assert.deepEqual(all(filed, 'bd-link').map((l) => l.allText()), ['Change your answer']);
});

test('a document stopped by the scan is red and says why', () => {
  const node = R.documentNode({ name: 'steer.md', state: 'stopped', state_words: 'Stopped by the safety scan',
    why: 'CLIVE’s safety scan stopped it before anything read it (line 3): tells an AI agent to ignore its instructions',
    notes: [], dropped: [], proposals: 0 }, new Date());
  assert.ok(all(node, 'rs-dot')[0].classList.contains('is-red'));
  assert.ok(node.querySelector('.rs-why').classList.contains('is-bad'));
  assert.match(node.allText(), /safety scan stopped it/);
  const odd = R.documentNode({ name: 'x', state: 'nonsense' }, new Date());
  assert.ok(all(odd, 'rs-dot')[0].classList.contains('is-red'), 'a state not in the table is never a reassuring dot');
});

test('the section goes under the Builds heading, after the builds that wait on him', () => {
  const host = document.createElement('div');
  const hello = document.createElement('div');
  hello.className = 'bd-hello';
  const groups = document.createElement('section');
  host.appendChild(hello);
  host.appendChild(groups);
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ summary: 'No research given yet.', documents: [], groups: [] }) });
  const node = R.place(host);
  assert.equal(host.childNodes[1], node);
  assert.equal(host.childNodes[2], groups);
  R.place(host);
  assert.equal(host.childNodes.filter((n) => n === node).length, 1, 'placed once');
  // With builds that wait on him, it goes after them: what needs him first.
  const needs = document.createElement('section');
  needs.className = 'bd-group is-needs-you';
  host.removeChild(node);
  host.insertBefore(needs, groups);
  R.place(host);
  assert.deepEqual(host.childNodes.map((n) => n.className), ['bd-hello', 'bd-group is-needs-you', 'rs', '']);
});

test('every word from the Mac lands as text, and no attribute carries it', () => {
  const p = proposal({ title: HOSTILE, says: HOSTILE, quote: HOSTILE, reason: HOSTILE, document: HOSTILE, touches: [HOSTILE],
    cites: [{ key: HOSTILE, label: HOSTILE, status: HOSTILE }], answers: [{ key: HOSTILE, label: HOSTILE, then: HOSTILE, recommended: true }] });
  const node = R.draw({ summary: HOSTILE, accepts: HOSTILE, problem: HOSTILE,
    documents: [{ name: HOSTILE, state: HOSTILE, state_words: HOSTILE, why: HOSTILE, notes: [HOSTILE], dropped: [{ title: HOSTILE, why: HOSTILE }] }],
    groups: [{ key: 'waiting', title: HOSTILE, proposals: [p] }] }, {});
  assert.ok(node.allText().includes(HOSTILE));
  for (const value of attributesOf(node)) assert.ok(!value.includes('<') && !value.includes('alert'), value);
});

// ---------------------------------------------------------------- ideas (DEC-078)

const IDEAS = JSON.parse(fs.readFileSync(path.join(__dirname, 'research-ideas.fixture.json'), 'utf8'));
// The backend's own example, produced by its real code (tests/fixtures/research/ideas-payload.json), once it is in the tree.
const BACKEND = path.join(__dirname, '..', 'fixtures', 'research', 'ideas-payload.json');
const PAYLOADS = [['the screen’s invented payload', IDEAS]];
if (fs.existsSync(BACKEND)) PAYLOADS.push(['the backend’s example payload', JSON.parse(fs.readFileSync(BACKEND, 'utf8'))]);
const ROLES = new Set(['group', 'radiogroup', 'status', 'region', 'Your answer', 'Research', '', 'true']);
const CLASS = /^(rs|btn|primary|rs-[a-z0-9]+|bd-[a-z0-9]+|is-[a-z_]+)$/;

const copy = (v) => JSON.parse(JSON.stringify(v));
const tick = () => new Promise((r) => setTimeout(r, 0));
const ideaById = (payload, id) => [...payload.needs_you, ...payload.groups.flatMap((g) => g.ideas)].find((i) => i.id === id);
const groupTitles = (node) => all(node, 'rs-group').map((g) => g.childNodes[0].allText());
function classesOf(node) { const out = []; walk(node, (n) => { for (const c of (n.className || '').split(/\s+/).filter(Boolean)) out.push(c); }); return out; }
const rowOf = (node, name) => all(node, 'rs-idea').find((n) => n.querySelector('.rs-title').allText() === name);

for (const [label, PAYLOAD] of PAYLOADS) {
  test(`ideas mode, from ${label}: what needs him first, then each group in order, every idea once`, () => {
    const node = R.draw(PAYLOAD, { now: new Date('2026-10-09T12:00:00Z') });
    assert.equal(node.querySelector('.rs-h2').allText(), 'Research');
    assert.equal(node.querySelector('.rs-summary').allText(), PAYLOAD.summary);
    assert.equal(all(node, 'rs-prop').filter((n) => !n.classList.contains('rs-idea')).length, 0, 'no proposal is drawn in ideas mode');
    const groups = all(node, 'rs-group').filter((g) => !g.classList.contains('is-documents'));
    const keys = groups.map((g) => ['needs', 'now', 'next', 'later', 'unscheduled'].find((k) => g.classList.contains(`is-${k}`)) || 'other');
    const order = ['needs', 'now', 'next', 'later', 'unscheduled', 'other'];
    assert.deepEqual(keys, [...keys].sort((a, b) => order.indexOf(a) - order.indexOf(b)), 'Needs you, Now, Next, Later, No date');
    if (PAYLOAD.needs_you.length) assert.equal(keys[0], 'needs');
    for (const g of groups) assert.ok(all(g, 'rs-idea').length > 0, 'no empty group is drawn');
    const drawn = all(node, 'rs-idea').map((n) => n.querySelector('.rs-title').allText());
    const every = [...PAYLOAD.needs_you, ...PAYLOAD.groups.flatMap((g) => g.ideas)];
    assert.equal(drawn.length, new Set(every.map((i) => i.id)).size, 'every idea drawn exactly once');
    assert.deepEqual(new Set(drawn), new Set(every.map((i) => i.name)));
    for (const value of attributesOf(node)) assert.ok(ROLES.has(value), `an attribute carries ${value}`);
    for (const cls of classesOf(node)) assert.match(cls, CLASS);
    for (const dot of all(node, 'rs-idea').map((n) => all(n, 'rs-dot')[0])) {
      assert.ok(['is-steel', 'is-dim', 'is-amber', 'is-red', 'is-none'].some((c) => dot.classList.contains(c)));
    }
  });
}

test('what the research says: its points, where it takes CLIVE, and the counts as given', () => {
  const node = R.draw(IDEAS, { now: new Date('2026-10-09T12:00:00Z') });
  const says = node.querySelector('.rs-says');
  assert.equal(says.querySelector('.rs-h3').allText(), 'What your research says');
  assert.deepEqual(all(says, 'rs-point').map((p) => p.allText()), IDEAS.synthesis.points);
  const ba = says.querySelector('.rs-ba');
  assert.equal(ba.querySelector('.rs-bahead').allText(), 'If we build what it agrees on, CLIVE goes');
  assert.deepEqual(all(ba, 'rs-baline').map((l) => l.allText()), ['Froma pile of separate test recommendations, each asked of you on its own',
    'Toone short list of test ideas, each checked against your rules and read back']);
  assert.equal(says.querySelector('.rs-counts').allText(), '30 recommendations from 3 documents became 6 ideas. 2 are backed by more than one report; '
    + '1 has disagreement. 1 confirms CLIVE’s direction; 1 changes CLIVE’s understanding. 1 recommendation couldn’t be placed.');
  assert.equal(says.querySelector('.rs-asof').allText(), 'Brought together 2 hours ago.');
  const order = node.childNodes.map((n) => n.className);
  assert.ok(order.indexOf('rs-says') < order.indexOf('rs-group rs-igroup is-needs'), 'what it says comes before what needs him');
});

test('the counts line leaves out a part whose number is missing, and never writes a zero it wasn’t given', () => {
  assert.equal(R.countsLine({ claims: 353, documents: 6, ideas: 42, converged: 30, disagreements: 7 }),
    '353 recommendations from 6 documents became 42 ideas. 30 are backed by more than one report; 7 have disagreement.');
  assert.equal(R.countsLine({ ideas: 42, disagreements: 7 }), 'Your research became 42 ideas. 7 have disagreement.');
  assert.equal(R.countsLine({ claims: 353, ideas: 42 }), '353 recommendations became 42 ideas.');
  assert.equal(R.countsLine({ documents: 6, converged: 0 }), '6 documents read. 0 are backed by more than one report.', 'a zero it was given is said');
  assert.equal(R.countsLine({ claims: '353', ideas: null, documents: -1, converged: NaN }), '', 'only real numbers count');
  assert.equal(R.countsLine(undefined), '');
  const node = R.draw(Object.assign(copy(IDEAS), { synthesis: { points: ['Only a point.'], counts: { ideas: 6 } } }), {});
  assert.equal(node.querySelector('.rs-counts').allText(), 'Your research became 6 ideas.');
  assert.equal(node.querySelector('.rs-ba'), null, 'no before/after without either');
  const onlyAfter = R.draw(Object.assign(copy(IDEAS), { synthesis: { after: 'CLIVE reads every test change back' } }), {});
  assert.deepEqual(all(onlyAfter, 'rs-baline').map((l) => l.allText()), ['ToCLIVE reads every test change back'], 'only the line it was given');
  assert.ok(!/\b0\b/.test(node.querySelector('.rs-says').allText()));
});

test('Needs you comes first: why it is there, its question, the plain view, then his three choices', () => {
  const node = R.draw(IDEAS, { now: new Date('2026-10-09T12:00:00Z') });
  assert.deepEqual(groupTitles(node), ['Needs you (1)', 'Now (2)', 'Next (1)', 'Later (1)', 'No date (1)', 'Documents (4)']);
  const needs = all(node, 'rs-group')[0];
  assert.equal(needs.getAttribute('open'), '');
  const [first] = all(needs, 'rs-idea');
  assert.equal(first.getAttribute('open'), '', 'the first that needs him is open');
  assert.ok(first.classList.contains('is-needs'));
  assert.match(first.querySelector('.rs-state').allText(), /^Clashes with one of your rules · Backed by 3 of 3$/);
  const said = first.allText();
  const at = (s) => { const i = said.indexOf(s); assert.ok(i >= 0, s); return i; };
  assert.ok(at('Clashes with one of your rules') < at('TEST QUESTION: three test notes') && at('TEST QUESTION') < at('What it means')
    && at('What it means') < at('Direction') && at('Direction') < at('Engineering detail') && at('Engineering detail') < at('What should CLIVE do?'));
  assert.deepEqual(first.querySelector('.bd-body').childNodes.map((n) => n.className), ['rs-needs', 'rs-view', 'rs-answers', 'bd-tech rs-tech', 'bd-decision']);
  assert.equal(first.querySelector('.rs-needs').allText(), IDEAS.needs_you[0].needs_you.question);
  assert.deepEqual(all(first, 'bd-anslabel').map((n) => n.allText()), ['Approve the work', 'Not now', 'Not for CLIVE']);
  assert.ok(all(first, 'rs-dot')[0].classList.contains('is-amber'), 'CONFLICT is amber');
  // Drawn in Needs you, so not again under Next, which still shows the rest of its ideas.
  const next = all(node, 'rs-group').find((g) => g.classList.contains('is-next'));
  assert.deepEqual(all(next, 'rs-title').map((t) => t.allText()), ['Reorder test socks weekly, in one batch']);
});

test('groups come Now, Next, Later, No date whatever order they arrive in, and an empty one is absent', () => {
  const p = copy(IDEAS);
  p.groups = [p.groups[3], p.groups[2], { key: 'next', title: 'Next', ideas: [] }, p.groups[0]];
  p.needs_you = [];
  const node = R.draw(p, {});
  assert.deepEqual(groupTitles(node), ['Now (2)', 'Later (1)', 'No date (1)', 'Documents (4)']);
  assert.equal(all(node, 'rs-group').filter((g) => g.classList.contains('is-needs')).length, 0, 'nothing needs him: no Needs you');
  // Only the needs-you idea in Next: Next is not drawn at all.
  const q = copy(IDEAS);
  q.groups[1].ideas = [q.groups[1].ideas[0]];
  assert.deepEqual(groupTitles(R.draw(q, {})), ['Needs you (1)', 'Now (2)', 'Later (1)', 'No date (1)', 'Documents (4)']);
});

test('each row: its name, the dot on its direction, backed by, importance, and work only once approved', () => {
  const node = R.draw(IDEAS, { now: new Date('2026-10-09T12:00:00Z') });
  const read = rowOf(node, 'Read every test change back');
  assert.equal(read.querySelector('.rs-state').allText(), 'Right direction · Backed by 3 of 3 · Foundational · Ready · You: Approve the work');
  const log = rowOf(node, 'Keep a log of every test parcel');
  assert.equal(log.querySelector('.rs-state').allText(), 'Right in part · Backed by 1 of 3 · High leverage');
  assert.ok(!/Not approved/.test(log.querySelector('.rs-sum').allText()), 'NOT_AUTHORISED is not said on the row');
  assert.equal(read.getAttribute('open'), null, 'a row is folded until tapped');
  const dots = Object.fromEntries(all(node, 'rs-idea').map((n) => [n.querySelector('.rs-title').allText(), all(n, 'rs-dot')[0].className]));
  assert.deepEqual(dots, {
    'Test emails go out without your hold': 'rs-dot is-amber', 'Read every test change back': 'rs-dot is-steel',
    'Keep a log of every test parcel': 'rs-dot is-steel', 'Reorder test socks weekly, in one batch': 'rs-dot is-steel',
    'Guess test sock sizes from photos': 'rs-dot is-dim', 'Pay per test question for a faster model': 'rs-dot is-red',
  });
});

test('the dot table is fixed, and a key it doesn’t know is neutral', () => {
  const want = { ADOPT: 'is-steel', ADOPT_PARTLY: 'is-steel', INVESTIGATE: 'is-dim', CONFLICT: 'is-amber', REJECT: 'is-red', MAYBE: 'is-none', '': 'is-none' };
  for (const [key, cls] of Object.entries(want)) {
    const idea = copy(ideaById(IDEAS, 'idea-0002'));
    idea.answers.judgment = { key, words: 'Some words' };
    assert.equal(all(R.ideaNode(idea, {}), 'rs-dot')[0].className, `rs-dot ${cls}`, key);
  }
  const bare = copy(ideaById(IDEAS, 'idea-0002'));
  delete bare.answers;
  assert.equal(all(R.ideaNode(bare, {}), 'rs-dot')[0].className, 'rs-dot is-none', 'no answers at all');
});

test('opened: the plain view first, then the four answers, the engineering detail folded, then his choices', () => {
  const node = R.ideaNode(ideaById(IDEAS, 'idea-0001'), { now: new Date('2026-10-09T12:00:00Z') });
  const view = node.querySelector('.rs-view');
  assert.deepEqual(all(view, 'bd-flabel').map((n) => n.allText()),
    ['What it means', 'Today', 'After', 'A real example', 'Before → after', 'Why you’d care', 'When you’d notice']);
  assert.deepEqual(all(view, 'rs-chip').map((n) => n.allText()), ['HIGHER RELIABILITY', 'LOWER RISK']);
  assert.deepEqual(all(node, 'rs-aline').map((n) => n.allText()), [
    'DirectionRight directionIt is RULE-1 applied to the parts that don\'t read back yet.',
    'Already in CLIVE?Partly there', 'WhenNowNothing holds it.', 'Work approved?Ready']);
  assert.equal(node.querySelector('.rs-amore').allText(), 'Confidence: High · Importance: Foundational · CLIVE’s understanding: Confirms what CLIVE thought');
  const body = node.querySelector('.bd-body');
  const kids = body.childNodes.map((n) => n.className);
  assert.deepEqual(kids, ['rs-view', 'rs-answers', 'bd-tech rs-tech', 'bd-chosen']);
  assert.equal(node.querySelector('.rs-tech').getAttribute('open'), null, 'the engineering detail is folded');
  // Partly written views show what they have and nothing in place of the rest.
  const part = R.ideaNode(ideaById(IDEAS, 'idea-0006'), {});
  assert.deepEqual(all(part.querySelector('.rs-view'), 'bd-flabel').map((n) => n.allText()), ['What it means', 'Today']);
  assert.ok(!/N\/A|—/.test(part.querySelector('.rs-view').allText()));
});

test('without a plain view: the statement and where it stands today, and it says there is no view yet', () => {
  const node = R.ideaNode(ideaById(IDEAS, 'idea-0002'), {});
  const view = node.querySelector('.rs-view').allText();
  assert.match(view, /There is no plain-English view of this one yet, so this is CLIVE’s own statement of it\./);
  assert.match(view, /What it isTEST STATEMENT: CLIVE keeps its own log/);
  assert.match(view, /TodayThere is no test parcel log\./);
  const empty = copy(ideaById(IDEAS, 'idea-0006'));
  empty.owner_view = {};
  assert.match(R.ideaNode(empty, {}).querySelector('.rs-view').allText(), /no plain-English view/, 'an empty view is no view');
});

test('a plain view CLIVE couldn’t make whole says so, and is shown as it is (review 11)', () => {
  const part = copy(ideaById(IDEAS, 'idea-0006'));
  part.owner_view_complete = false;
  const view = R.ideaNode(part, {}).querySelector('.rs-view');
  assert.deepEqual(all(view, 'bd-flabel').map((n) => n.allText()), ['What it means', 'Today']);
  assert.equal(view.querySelector('.rs-incomplete').allText(), 'CLIVE’s plain-English view of this isn’t complete yet.');
  part.owner_view_complete = true;
  assert.equal(R.ideaNode(part, {}).querySelector('.rs-incomplete'), null);
  delete part.owner_view_complete;
  assert.equal(R.ideaNode(part, {}).querySelector('.rs-incomplete'), null, 'not said when the server didn’t say');
  const none = copy(ideaById(IDEAS, 'idea-0002'));
  none.owner_view_complete = false;
  assert.equal(R.ideaNode(none, {}).querySelector('.rs-incomplete'), null, 'no view at all says that instead');
});

test('DEC-018 holds only the timing, said on the When line', () => {
  const node = R.ideaNode(ideaById(IDEAS, 'idea-0006'), {});
  const lines = all(node, 'rs-aline').map((n) => n.allText());
  assert.equal(lines[0], 'DirectionRight directionIt builds on the test reorder list that exists.');
  assert.equal(lines[2], 'WhenNextFinish what is already started first. Held by DEC-018 Finish first.');
});

test('the engineering detail: sources in their own words, what argues against it, keys, the code, history', () => {
  const node = R.ideaNode(ideaById(IDEAS, 'idea-0003'), { needs: true, now: new Date('2026-10-09T12:00:00Z') });
  const tech = node.querySelector('.rs-tech');
  assert.equal(tech.querySelector('.bd-techsum').allText(), 'Engineering detail');
  const said = tech.allText();
  assert.match(said, /Sources \(3\)/);
  const sources = all(tech, 'rs-source').map((s) => s.allText());
  assert.equal(sources[0], 'test-research-note-a.md · TEST SECTION: Speed“TEST QUOTE: routine replies should not wait for anyone.”Supports it, central to the document');
  assert.equal(sources[2], 'test-research-note-b.pdf · TEST SECTION: Holds“TEST QUOTE: keep the hold for anything a customer reads.”Argues against it, said in passing');
  assert.match(said, /What argues against ittest-research-note-b\.pdf: TEST: a test email should still wait/);
  assert.match(said, /How the reports differTEST: notes A and C want speed/);
  assert.match(said, /CLIVE’s keysRULE-2 Anything outward waits for a gesture on its card: contradicts/);
  assert.match(said, /TodayNot in CLIVE yet\. Every outward test email waits for a hold\.app\/actions\/grammar\.py/);
  assert.equal(all(tech, 'is-code').map((n) => n.allText()).join(), 'app/actions/grammar.py');
  assert.ok(!/Not checked against the code/.test(said), 'checked paths say nothing more');
  assert.match(said, /What would change CLIVE’s viewTEST: a month of test emails/);
  assert.deepEqual(all(tech, 'rs-hline').map((n) => n.allText()), ['9 Oct: Created from test-research-note-a.md.',
    '9 Oct: test-research-note-b.pdf argued against it.', '9 Oct: Judged: Needs your call (it contradicts RULE-2 and three documents back it).']);
  const unchecked = R.ideaNode(ideaById(IDEAS, 'idea-0002'), {}).querySelector('.rs-tech').allText();
  assert.match(unchecked, /TodayNot in CLIVE yet\. There is no test parcel log\.Not checked against the code\./);
});

test('his answer takes two steps, and is sent bound to the idea as drawn', async () => {
  const sent = [];
  const idea = ideaById(IDEAS, 'idea-0002');
  const node = R.ideaNode(idea, { answerIdea: async (i, key) => { sent.push([i.id, i.fingerprint, key]); return { error: 'CLIVE answered 500, so nothing was recorded.' }; } });
  const choose = node.querySelector('.bd-choose');
  assert.equal(node.querySelector('.bd-q').allText(), 'What should CLIVE do?');
  assert.equal(choose.disabled, true);
  assert.equal(choose.allText(), 'Pick an answer');
  const later = all(node, 'bd-ans')[1];
  assert.match(later.allText(), /Not nowKept, and not asked again until the research changes\./);
  later.dispatch('click');
  assert.equal(choose.allText(), 'Choose: Not now');
  assert.deepEqual(sent, [], 'a pick alone sends nothing');
  choose.dispatch('click');
  await tick();
  assert.deepEqual(sent, [['idea-0002', '2'.repeat(64), 'later']]);
  assert.equal(node.querySelector('.bd-said').allText(), 'CLIVE answered 500, so nothing was recorded.');
  assert.equal(choose.allText(), 'Choose: Not now', 'after a refusal he can choose again');
  all(node, 'bd-ans')[0].dispatch('click');
  assert.equal(choose.allText(), 'Choose: Approve the work');
  let busy = '';
  const slow = R.ideaNode(idea, { answerIdea: async () => { busy = slow.querySelector('.bd-choose').allText(); return { ok: true }; } });
  all(slow, 'bd-ans')[0].dispatch('click');
  slow.querySelector('.bd-choose').dispatch('click');
  await tick();
  assert.equal(busy, 'Preparing the build request…');
});

test('the answer goes to the idea route with its fingerprint; a card comes back to the conversation', async () => {
  const calls = [];
  const shown = [];
  globalThis.CliveCards = { show: (staged) => { shown.push(staged.request_id); return true; } };
  const after = copy(IDEAS);
  const answered = ideaById(after, 'idea-0002');
  answered.owner_answer = { key: 'go', label: 'Approve the work', at: new Date().toISOString(), current: true };
  answered.build = { state: 'waiting', words: 'Its build request waits for your hold on the card.', request_id: 'req-test-0002' };
  globalThis.fetch = async (url, init) => { calls.push([url, JSON.parse(init.body)]); return { ok: true, status: 200, json: async () => ({ section: after, staged: { ok: true, request_id: 'req-test-0002' } }) }; };
  const got = await R.answerIdea(ideaById(IDEAS, 'idea-0002'), 'go');
  assert.deepEqual(got, { ok: true });
  assert.deepEqual(calls, [['/objectives/research/idea/answer', { idea_id: 'idea-0002', fingerprint: '2'.repeat(64), answer: 'go', session_id: '' }]]);
  assert.deepEqual(shown, ['req-test-0002']);
  const row = rowOf(R.state().node, 'Keep a log of every test parcel');
  assert.match(row.allText(), /You chose Approve the work, just now\./);
  delete globalThis.CliveCards;
});

test('a 409 moved_on redraws from the section that came back and says why, where he answered', async () => {
  const moved = copy(IDEAS);
  ideaById(moved, 'idea-0004').fingerprint = '7'.repeat(64);
  const why = 'That idea changed since you saw it, so nothing was recorded.';
  globalThis.fetch = async () => ({ ok: false, status: 409, json: async () => ({ code: 'moved_on', detail: why, section: moved }) });
  const got = await R.answerIdea(ideaById(IDEAS, 'idea-0004'), 'later');
  assert.deepEqual(got, { error: why });
  const node = R.state().node;
  const row = rowOf(node, 'Guess test sock sizes from photos');
  assert.equal(row.getAttribute('open'), '', 'the idea he answered is open');
  assert.equal(row.querySelector('.bd-said').allText(), why);
  assert.equal(all(node, 'bd-said').filter((n) => n.allText() === why).length, 1, 'said once');
  // An idea no longer drawn: the words go under the heading instead.
  globalThis.fetch = async () => ({ ok: false, status: 409, json: async () => ({ code: 'moved_on', detail: why, section: moved }) });
  await R.answerIdea({ id: 'idea-0099', fingerprint: '9'.repeat(64) }, 'no');
  const under = R.state().node.childNodes.find((n) => n.className === 'rs-noticespot');
  assert.equal(under.allText(), why);
  // The screen's own re-read (every few seconds while a document is read) keeps the words for a while.
  const why2 = 'That idea changed since you saw it, so nothing was recorded (again).';
  globalThis.fetch = async () => ({ ok: false, status: 409, json: async () => ({ code: 'moved_on', detail: why2, section: moved }) });
  await R.answerIdea(ideaById(IDEAS, 'idea-0004'), 'later');
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => moved });
  await R.refresh();
  assert.equal(rowOf(R.state().node, 'Guess test sock sizes from photos').querySelector('.bd-said').allText(), why2, 'kept through a re-read');
  R.state().notice.at -= 61000;
  await R.refresh();
  assert.equal(all(R.state().node, 'bd-said').filter((n) => n.allText() === why2).length, 0, 'gone once it is a minute old');
  globalThis.fetch = async () => { throw new Error('offline'); };
  assert.deepEqual(await R.answerIdea(ideaById(IDEAS, 'idea-0004'), 'later'), { error: 'CLIVE could not be reached, so nothing was recorded.' });
});

test('his answer to an earlier view says so, and the choices are offered again', () => {
  const node = R.ideaNode(ideaById(IDEAS, 'idea-0004'), { now: new Date('2026-10-09T12:00:00Z') });
  assert.match(node.querySelector('.rs-earlierline').allText(), /^You chose Not now, 21 hours ago: your answer to an earlier view\./);
  assert.ok(node.querySelector('.bd-decision'), 'the choices again');
  assert.equal(all(node, 'bd-ans').length, 3);
  assert.ok(!/You: Not now/.test(node.querySelector('.rs-sum').allText()), 'the row doesn’t claim it as his current answer');
});

test('approved: where its build request is, prepared again from here, and his answer can change', async () => {
  const prepared = [];
  const idea = ideaById(IDEAS, 'idea-0001');
  const node = R.ideaNode(idea, { now: new Date('2026-10-09T12:00:00Z'), prepareIdea: async (i) => { prepared.push(i.id); return { ok: true }; } });
  const chosen = node.querySelector('.bd-chosen');
  assert.match(chosen.allText(), /^You chose Approve the work, 20 min ago\.Its build request waits for your hold on the card/);
  assert.ok(chosen.querySelector('.rs-build').classList.contains('is-waiting'));
  const links = all(chosen, 'bd-link');
  assert.deepEqual(links.map((l) => l.allText()), ['Prepare the build request again', 'Change your answer']);
  links[0].dispatch('click');
  await tick();
  assert.deepEqual(prepared, ['idea-0001']);
  links[1].dispatch('click');
  assert.ok(node.querySelector('.bd-decision'), 'changing his answer puts the choices back');
  const no = R.ideaNode(ideaById(IDEAS, 'idea-0005'), { now: new Date('2026-10-09T12:00:00Z') });
  assert.match(no.querySelector('.bd-chosen').allText(), /^You chose Not for CLIVE, 15 min ago\.Recorded as not for CLIVE\./);
  assert.deepEqual(all(no, 'bd-link').map((l) => l.allText()), ['Change your answer'], 'only Approve has a build request');
  const filed = copy(idea);
  filed.build = { state: 'filed', words: 'Filed with the build loop.' };
  assert.deepEqual(all(R.ideaNode(filed, {}), 'bd-link').map((l) => l.allText()), ['Change your answer']);
  const odd = copy(idea);
  odd.build = { state: '"><img onerror=alert(1)>', words: 'Something.' };
  assert.equal(R.ideaNode(odd, {}).querySelector('.rs-build').className, 'rs-build is-unknown');
});

test('prepare again goes to the idea route, and a refusal is said', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => { calls.push([url, JSON.parse(init.body)]); return { ok: true, status: 200, json: async () => ({ section: IDEAS, staged: { ok: false, detail: 'CLIVE couldn’t tell which parts of CLIVE this would change.' } }) }; };
  const got = await R.prepareIdea(ideaById(IDEAS, 'idea-0001'));
  assert.deepEqual(calls, [['/objectives/research/idea/prepare', { idea_id: 'idea-0001', session_id: '' }]]);
  assert.deepEqual(got, { error: 'CLIVE couldn’t tell which parts of CLIVE this would change.' });
  const row = rowOf(R.state().node, 'Read every test change back');
  assert.equal(row.querySelector('.bd-chosen').querySelector('.bd-said').allText(), 'CLIVE couldn’t tell which parts of CLIVE this would change.');
});

test('the documents: recommendations read, whether each is in the ideas, and what couldn’t be placed', () => {
  const node = R.draw(IDEAS, { now: new Date('2026-10-09T12:00:00Z') });
  const docs = all(node, 'rs-group').find((g) => g.classList.contains('is-documents'));
  assert.equal(docs.getAttribute('open'), '', 'open while a document is being read');
  const rows = all(docs, 'rs-doc');
  assert.equal(rows.length, 4);
  assert.equal(rows[1].querySelector('.rs-docline').allText(), '9 recommendations read · Absorbed into the ideas · given 2 hours ago');
  assert.ok(all(rows[1], 'rs-dot')[0].classList.contains('is-steel'));
  assert.equal(rows[1].querySelector('.rs-docbody').allText(),
    'Couldn’t place (1)TEST CLAIM: invented weather changes sock sales: Its quote wasn\'t found in the document, even after asking again.');
  assert.equal(rows[3].querySelector('.rs-docline').allText(), 'Being read now · given 10 min ago');
  assert.ok(all(rows[3], 'rs-dot')[0].classList.contains('is-blue'));
  const words = { absorbed: ['Absorbed into the ideas', 'is-steel'], waiting: ['Waiting for the first synthesis', 'is-blue'],
    reading: ['Being read into the ideas', 'is-blue'], failed: ['Couldn’t be absorbed', 'is-red'], odd: ['', 'is-none'] };
  for (const [state, [said, dot]] of Object.entries(words)) {
    const d = R.ideaDocumentNode({ name: 'test-note.md', state: 'done', claims: 1, synthesis_state: state }, new Date());
    assert.equal(d.querySelector('.rs-docline').allText(), ['1 recommendation read', said].filter(Boolean).join(' · '), state);
    assert.ok(all(d, 'rs-dot')[0].classList.contains(dot), state);
  }
  const none = R.ideaDocumentNode({ name: 'test-note.md', state: 'done', synthesis_state: 'absorbed' }, new Date());
  assert.equal(none.querySelector('.rs-docline').allText(), 'Absorbed into the ideas', 'no claims count: nothing said about it');
  const zero = (synthesis_state) => R.ideaDocumentNode({ name: 'test-note.md', state: 'done', claims: 0, synthesis_state }, new Date()).querySelector('.rs-docline').allText();
  assert.equal(zero('absorbed'), 'No recommendations in it · Absorbed into the ideas');
  assert.equal(zero('waiting'), 'Waiting for the first synthesis', 'none counted yet is not none');
  const settled = copy(IDEAS);
  settled.documents = settled.documents.slice(0, 3);
  const folded = all(R.draw(settled, {}), 'rs-group').find((g) => g.classList.contains('is-documents'));
  assert.equal(folded.getAttribute('open'), null, 'folded once every document is in the ideas');
});

test('proposals mode is drawn as before, with one quiet line while CLIVE re-reads into ideas', () => {
  const base = { summary: 'No research given yet.', documents: [], groups: [], mode: 'proposals' };
  const plain = R.draw(Object.assign({}, base, { synthesis: { state: 'not_live', run: null } }), {});
  assert.equal(plain.querySelector('.rs-run'), null);
  assert.equal(plain.querySelector('.rs-says'), null, 'no ideas drawn in proposals mode');
  const running = R.draw(Object.assign({}, base, { synthesis: { state: 'not_live', run: { stage: 'judge', done: 31, of: 42 } } }), {});
  assert.equal(running.querySelector('.rs-run').allText(), 'CLIVE is re-reading your research into ideas: judging, 31 of 42.');
  // The run summary as app/builds/research_ideas.py run_summary sends it.
  const run = (over) => R.draw(Object.assign({}, base, { synthesis: { state: 'not_live', run: Object.assign({ generation: 'gen-20261009T120000', stage: 'judge',
    stage_words: 'judging', done: 31, of: 42, started_at: '2026-10-09T12:00:00+00:00', finished_at: '', calls: 40, errors: 0 }, over) } }), {})
    .querySelector('.rs-run');
  assert.equal(run({}).allText(), 'CLIVE is re-reading your research into ideas: judging, 31 of 42.');
  assert.equal(run({ stage: 'consolidate', stage_words: 'joining ideas that are the same', done: 0, of: 0 }).allText(),
    'CLIVE is re-reading your research into ideas: joining ideas that are the same.', 'no count: no “0 of 0”');
  assert.equal(run({ errors: 2 }).allText(), 'CLIVE’s re-reading of your research into ideas reached judging, 31 of 42. It has stopped 2 times on the way.');
  assert.equal(run({ errors: [{ said: 'x' }] }).allText(), 'CLIVE’s re-reading of your research into ideas reached judging, 31 of 42. It has stopped once on the way.');
  assert.equal(run({ stage: 'done', stage_words: 'finished, waiting to be made live', finished_at: '' }).allText(), 'CLIVE has re-read your research into ideas. They aren’t live yet.');
  assert.equal(run({ stage: 'documents', stage_words: '' }).allText(), 'CLIVE is re-reading your research into ideas: reading documents, 31 of 42.', 'its own words when none came');
  assert.equal(run({ stage: 'something-new', stage_words: '', done: null, of: null }), null, 'nothing known to say: the line is left out');
  const order = running.childNodes.map((n) => n.className);
  assert.deepEqual(order.slice(0, 4), ['rs-h2', 'rs-summary', 'rs-run', 'rs-add']);
});

test('ideas mode: every word from the Mac lands as text, and no attribute or class carries it', () => {
  const p = copy(IDEAS);
  const hostile = (idea) => {
    Object.assign(idea, { name: HOSTILE, statement: HOSTILE, how_they_differ: HOSTILE, revisit: HOSTILE, effects: [HOSTILE] });
    idea.answers.judgment = { key: HOSTILE, words: HOSTILE };
    idea.answers.execution = { key: HOSTILE, words: HOSTILE };
    idea.reasons = { judgment: HOSTILE, timing: HOSTILE };
    idea.timing_held_by = [{ key: HOSTILE, label: HOSTILE }];
    idea.sources = [{ document: HOSTILE, section: HOSTILE, quote: HOSTILE, stance: HOSTILE, centrality: HOSTILE }];
    idea.against = [{ document: HOSTILE, says: HOSTILE }];
    idea.keys = [{ key: HOSTILE, label: HOSTILE, how: HOSTILE }];
    idea.today = { level: HOSTILE, says: HOSTILE, where: [HOSTILE], verified: false };
    idea.history = [{ at: HOSTILE, said: HOSTILE }];
    idea.choices = [{ key: HOSTILE, label: HOSTILE, then: HOSTILE }];
    if (idea.owner_view) idea.owner_view = { means: HOSTILE, why_care: [HOSTILE], notice: HOSTILE };
    if (idea.needs_you) idea.needs_you = { trigger: HOSTILE, trigger_words: HOSTILE, question: HOSTILE };
    if (idea.build) idea.build = { state: HOSTILE, words: HOSTILE };
    if (idea.owner_answer) idea.owner_answer.label = HOSTILE;
  };
  p.needs_you.forEach(hostile);
  p.groups.forEach((g) => { g.title = HOSTILE; g.key = HOSTILE; g.ideas.forEach(hostile); });
  Object.assign(p, { summary: HOSTILE, problem: HOSTILE, accepts: HOSTILE });
  p.synthesis = { points: [HOSTILE], before: HOSTILE, after: HOSTILE, at: HOSTILE, counts: { ideas: HOSTILE } };
  p.documents = [{ name: HOSTILE, state: HOSTILE, state_words: HOSTILE, why: HOSTILE, synthesis_state: HOSTILE, notes: [HOSTILE], claims: HOSTILE,
    unplaced: [{ title: HOSTILE, why: HOSTILE }] }];
  const node = R.draw(p, {});
  assert.ok(node.allText().includes(HOSTILE));
  for (const value of attributesOf(node)) assert.ok(!value.includes('<') && !value.includes('alert'), value);
  for (const cls of classesOf(node)) assert.match(cls, CLASS);
  assert.ok(all(node, 'rs-idea').every((n) => all(n, 'rs-dot')[0].className === 'rs-dot is-none'), 'an unknown key is neutral');
});

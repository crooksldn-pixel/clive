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

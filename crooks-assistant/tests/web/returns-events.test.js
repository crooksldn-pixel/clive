/* [returns-events] What just happened at CROOKS Returns that needs the owner (web/returns.js
 * `announce`, fed by GET /returns/brief's `notices`; app/returns/events.py, DEC-077), under Node.
 *
 * What it must hold: each notice is said once on this device, through web/notify.js, as a workspace
 * message that stays until he dismisses it; its tone is decided here by its name, never by the Mac;
 * notices of one kind arriving together are one message; anything malformed is not said; a notice
 * the page could not draw is tried again at the next brief; and a reload does not say it again.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
const RETURNS = path.join(__dirname, '..', '..', 'web', 'returns.js');
const NOTIFY = require(path.join(__dirname, '..', '..', 'web', 'notify.js'));

const id = (n) => `rn_${String(n).padStart(24, '0')}`;
const BRIEF = (notices) => ({ ok: true, connected: true, available: true, needs: 2, words: '1 to approve · 1 has an error', notices });

function fresh() {
  delete require.cache[require.resolve(RETURNS)];
  return require(RETURNS);
}

function said(drawn = true) {
  const calls = [];
  globalThis.CrooksNotify = { show: (m) => { calls.push(m); return drawn ? { id: `note_${calls.length}` } : null; } };
  return calls;
}

function store() {
  const held = {};
  globalThis.localStorage = { getItem: (k) => (k in held ? held[k] : null), setItem: (k, v) => { held[k] = String(v); } };
  return held;
}

function serve(body) {
  globalThis.fetch = async () => ({ ok: true, json: async () => body });
}

test('each notice is said once, as a workspace message that stays until he dismisses it', async () => {
  store();
  const calls = said();
  const R = fresh();
  serve(BRIEF([
    { id: id(1), code: 'return_problem', tone: 'good', words: 'Return on #2131: Shopify didn\'t move the money.', at: '2026-10-08T10:00:00Z' },
    { id: id(2), code: 'return_to_approve', tone: 'bad', words: 'Return on #2140: waiting for your approval.', at: '2026-10-08T09:59:00Z' },
  ]));
  await R.brief();
  assert.deepEqual(calls.map((m) => [m.class, m.code, m.tone, m.persist, m.text]), [
    ['workspace', 'return_to_approve', 'info', true, 'Return on #2140: waiting for your approval.'],
    ['workspace', 'return_problem', 'bad', true, 'Return on #2131: Shopify didn\'t move the money.'],
  ], 'the tone is the name\'s, never what the Mac sent');
  await R.brief();
  assert.equal(calls.length, 2, 'the next brief says nothing new');
  assert.equal(R.briefNow().needs, 2, 'the home\'s count is kept as before');
});

test('one kind arriving together is one message, at most three said and the rest counted', async () => {
  store();
  const calls = said();
  const R = fresh();
  const many = [1, 2, 3, 4, 5].map((n) => ({ id: id(n), code: 'return_needs_you', words: `Return on #21${n}0: the label is overdue.` }));
  serve(BRIEF(many));
  await R.brief();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].text, 'Return on #2110: the label is overdue. Return on #2120: the label is overdue. '
    + 'Return on #2130: the label is overdue. And 2 more.');
  assert.equal(calls[0].tone, 'warn');
});

test('anything malformed is not said', async () => {
  store();
  const calls = said();
  const R = fresh();
  serve(BRIEF([
    { id: 'evt_0a1b', code: 'return_problem', words: 'a bad handle' },
    { id: id(7), code: 'opened', words: 'a name that is not one of the three' },
    { id: id(8), code: 'return_problem', words: '   ' },
    { id: id(9), code: 'return_problem' },
    'not an object',
  ]));
  await R.brief();
  assert.deepEqual(calls, []);
  serve({ ok: true, connected: false, needs: 0, words: '' });
  await R.brief();
  assert.deepEqual(calls, [], 'not connected: nothing');
});

test('a notice the page could not draw is tried again at the next brief', async () => {
  store();
  const calls = said(false);
  const R = fresh();
  serve(BRIEF([{ id: id(11), code: 'return_to_approve', words: 'Return on #2150: waiting for your approval.' }]));
  await R.brief();
  globalThis.CrooksNotify.show = (m) => { calls.push(m); return { id: 'note_1' }; };
  await R.brief();
  await R.brief();
  assert.equal(calls.length, 2, 'refused once, drawn once, then never again');
});

test('a reload does not say it again: the handles shown are kept in this browser', async () => {
  const held = store();
  const calls = said();
  serve(BRIEF([{ id: id(21), code: 'return_problem', words: 'Return on #2160: the label wasn\'t made.' }]));
  await fresh().brief();
  assert.equal(calls.length, 1);
  assert.deepEqual(JSON.parse(held['clive.returns.notices']), [id(21)]);
  await fresh().brief();
  assert.equal(calls.length, 1);
  globalThis.localStorage = { getItem: () => { throw new Error('private'); }, setItem: () => { throw new Error('private'); } };
  serve(BRIEF([{ id: id(22), code: 'return_problem', words: 'Return on #2170: the cancel failed.' }]));
  const R = fresh();
  await R.brief();
  await R.brief();
  assert.equal(calls.length, 2, 'a browser that keeps nothing still says each once per page');
});

test('the three names pass web/notify.js\'s policy', () => {
  for (const code of ['return_to_approve', 'return_needs_you', 'return_problem']) {
    assert.deepEqual(NOTIFY.check({ code, text: 'Return on #2131: the label is overdue.' }), { ok: true, reason: '' }, code);
  }
});

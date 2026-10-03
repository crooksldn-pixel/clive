/* The Connections screen's rows (web/connections-view.js), under Node.
 *
 * George, 2 October 2026: "it asks for API keys when not needed and is clunky to use." What is
 * held here, from the state the server sends: rows are grouped by what he has to do (needs you,
 * working, not connected); a working connection draws no key box at all until "Replace" is
 * tapped; a refused key asks for exactly the keys refused; a service not yet added asks for its
 * key only once Connect is tapped, and then exactly one; Gmail, set up at the server, asks for
 * nothing here; every details disclosure starts closed; a working row says when it was checked;
 * and nothing the server sends is ever written back into a secret box or read as markup.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
const View = require(path.join(__dirname, '..', '..', 'web', 'connections-view.js'));

const NOW = Date.parse('2026-10-02T14:00:00Z');
const HOSTILE = '<img src=x onerror="alert(1)">';
const SECRET = 'a-secret-the-server-never-sends';

const field = (key, label, extra) => Object.assign({ key, label, hint: '', secret: true, stored: false, where: 'not set' }, extra || {});

function connection(extra) {
  return Object.assign({
    name: 'elevenlabs', label: 'ElevenLabs', what: "Hears you and speaks in Derek's voice.", note: '',
    state: 'connected', group: 'working', detail: 'ElevenLabs accepted the key.', who: '',
    tested_at: '2026-10-02T13:58:00+00:00', fix: '', needs: [], requires: ['elevenlabs_api_key'],
    fields: [field('elevenlabs_api_key', 'API key', { stored: true, where: 'saved here' })],
    editable: true, testable: true, unlocks: [{ label: 'Hearing what you say', state: 'READY' }],
    without: "Without it CLIVE speaks in each device's own built-in voice.", set_up_at: '', expires_in_days: null,
  }, extra || {});
}

const SHOPIFY = connection({
  name: 'shopify', label: 'Shopify', what: 'Reads and edits your orders, customers and stock.',
  detail: "Shopify accepted the app's ID and secret.", who: 'crooks.myshopify.com',
  requires: ['shopify_client_id', 'shopify_client_secret'],
  fields: [field('shopify_client_id', 'Client ID', { secret: false, stored: true, where: 'set at the server', value: 'id-0123' }),
    field('shopify_client_secret', 'Client secret', { stored: true, where: 'set at the server' })],
  unlocks: [{ label: 'Reading orders', state: 'READY' }, { label: 'Refunding', state: 'READ_ONLY' }],
  without: "Without it CLIVE can't see or change anything in the shop.",
});
const GITHUB = connection({
  name: 'github', label: 'GitHub', what: "Files build requests for CLIVE's own engineering.",
  state: 'needs_attention', group: 'attention', detail: 'GitHub refused that token.', fix: 'key',
  needs: ['github_engineering_inbox_token'], requires: ['github_engineering_inbox_token'],
  fields: [field('github_engineering_inbox_token', 'Fine-grained token', { stored: true, where: 'set at the server' })],
});
const SHIP24 = connection({
  name: 'ship24', label: 'Ship24', what: "Says where a parcel is, from the carrier's own scans.",
  state: 'not_connected', group: 'add', detail: 'Not connected.', tested_at: '', fix: 'key',
  needs: ['ship24_api_key'], requires: ['ship24_api_key'], fields: [field('ship24_api_key', 'API key')],
});
const GMAIL = connection({
  name: 'gmail', label: 'Gmail', what: 'Reads your email.', state: 'not_connected', group: 'add',
  detail: 'Not connected.', tested_at: '', fix: 'server', needs: [], requires: [], fields: [], editable: false,
  set_up_at: 'server',
});
const INSTAGRAM = connection({
  name: 'instagram', label: 'Instagram', what: 'Reads your Instagram messages.', state: 'needs_attention',
  group: 'attention', detail: 'The Instagram sign-in runs out in 3 days.', fix: 'signin', needs: [],
  requires: ['instagram_access_token'], expires_in_days: 3,
  fields: [field('instagram_app_id', 'Instagram app ID', { secret: false, stored: true, value: '123' }),
    field('instagram_app_secret', 'Instagram app secret', { stored: true }),
    field('instagram_access_token', 'Access token (only if you made one there)', { stored: true })],
  sign_in: { label: 'Sign in with Instagram', redirect_uri: 'https://clive.example.ts.net/connections/instagram/callback', ready: true },
});

const STATE = { connections: [INSTAGRAM, GITHUB, SHOPIFY, connection(), SHIP24, GMAIL], passkeys: [], changes: [] };

function ctx(extra) {
  return Object.assign({ now: NOW, checking: new Set(), canChange: true, on: {} }, extra || {});
}

const all = (node, selector) => node.querySelectorAll(selector);
const one = (node, selector) => node.querySelector(selector);
const keyBoxes = (node) => all(node, 'input').filter((i) => i.classList.contains('key-input'));
const visible = (node) => {
  for (let at = node; at; at = at.parentNode) if (at.hidden) return false;
  return true;
};
const rowOf = (sections, name) => {
  for (const section of sections) for (const row of all(section, 'article')) if (row.dataset.name === name) return row;
  return null;
};
const buttonCalled = (node, words) => all(node, 'button').find((b) => b.textContent === words);

test('rows are grouped by what he has to do: needs you, then working, then not connected', () => {
  const sections = View.groups(STATE, ctx());
  assert.deepEqual(sections.map((s) => s.id), ['group-attention', 'group-working', 'group-add']);
  assert.deepEqual(sections.map((s) => one(s, 'h2').textContent), ['Needs you', 'Working', 'Not connected']);
  assert.deepEqual(all(sections[0], 'article').map((r) => r.dataset.name), ['instagram', 'github']);
  assert.deepEqual(all(sections[1], 'article').map((r) => r.dataset.name), ['shopify', 'elevenlabs']);
  assert.equal(View.summary(STATE, ctx()), '2 working, 2 need you.');
  assert.equal(View.summary({ connections: [SHOPIFY, connection()] }, ctx()), 'All 2 working.');
});

test('a working connection asks for no key, says when it was checked, and keeps the rest closed', () => {
  for (const c of [SHOPIFY, connection()]) {
    const row = View.row(c, ctx());
    assert.equal(keyBoxes(row).length, 0, c.name);
    assert.equal(one(row, '.conn-status').textContent, 'Connected · checked 2 min ago');
    const details = all(row, 'details');
    assert.equal(details.length, 1);
    assert.equal(details[0].open, false);
    // The one quiet line is the disclosure's own summary: tapping the row opens it.
    assert.ok(one(one(row, 'summary'), '.conn-name'));
  }
});

test('Replace on a working connection asks for exactly the keys it cannot work without', () => {
  const row = View.row(connection(), ctx());
  const replace = buttonCalled(row, 'Replace API key');
  assert.ok(replace, 'a Replace button named for what it replaces');
  replace.dispatch('click');
  const boxes = keyBoxes(row);
  assert.equal(boxes.length, 1);
  assert.equal(boxes[0].type, 'password');
  assert.equal(boxes[0].value, undefined);
  assert.equal(View.boxOf(boxes[0]).key, 'elevenlabs_api_key');
  replace.dispatch('click');
  assert.equal(keyBoxes(row).length, 0, 'tapped again, the box goes');
  // Shopify's pair: the ID shows what is saved (not a secret), the secret box starts empty.
  const shop = View.row(SHOPIFY, ctx());
  buttonCalled(shop, 'Replace client ID and client secret').dispatch('click');
  const pair = keyBoxes(shop);
  assert.deepEqual(pair.map((b) => b.type), ['text', 'password']);
  assert.equal(pair[0].value, 'id-0123');
});

test('a refused key asks for exactly the key refused, at once, and no second way to it', () => {
  const row = View.row(GITHUB, ctx());
  const boxes = keyBoxes(row);
  assert.equal(boxes.length, 1);
  assert.ok(visible(boxes[0]));
  assert.equal(View.boxOf(boxes[0]).key, 'github_engineering_inbox_token');
  assert.equal(one(row, '.conn-problem').textContent, 'GitHub refused that token.');
  assert.equal(buttonCalled(row, 'Replace fine-grained token'), undefined);
  assert.ok(all(row, 'details').every((d) => d.open === false));
});

test('a service not yet added draws its key box only when Connect is tapped, and then exactly one', () => {
  const row = View.row(SHIP24, ctx());
  assert.equal(all(row, 'input').length, 0);
  const connect = buttonCalled(row, 'Connect');
  // Announced as "Connect Ship24", not one of several bare "Connect"s.
  assert.equal(connect.getAttribute('aria-labelledby'), 'connect-ship24 name-ship24');
  assert.equal(one(row, 'h3').id, 'name-ship24');
  connect.dispatch('click');
  assert.equal(connect.hidden, true);
  assert.equal(keyBoxes(row).length, 1);
  buttonCalled(row, 'Cancel').dispatch('click');
  assert.equal(all(row, 'input').length, 0);
  assert.equal(connect.hidden, false);
});

test('a row is in use only while it holds something he typed, never the ID the page filled in', () => {
  // The review of 889f3284: the Client ID box the page fills in itself counted as typing, so after
  // Shopify refused its ID and secret the screen stopped regrouping at all.
  const refused = Object.assign({}, SHOPIFY, { state: 'needs_attention', group: 'attention', fix: 'key',
    needs: ['shopify_client_id', 'shopify_client_secret'] });
  const shop = View.row(refused, ctx());
  const [id, secret] = keyBoxes(shop);
  assert.equal(id.value, 'id-0123', 'the page filled the ID in');
  assert.equal(View.inUse(shop, null), false, 'a filled-in ID is not typing');
  secret.value = 'half a secret';
  assert.equal(View.inUse(shop, null), true, 'what he typed is kept');
  secret.value = '';
  id.value = 'another-id';
  assert.equal(View.inUse(shop, null), true, 'an ID he changed is kept');
  // The cursor in a box of the row's own form keeps it too; a button does not.
  const github = View.row(GITHUB, ctx());
  const box = keyBoxes(github)[0];
  assert.equal(View.inUse(github, box), true);
  assert.equal(View.inUse(github, one(github, '.key-save')), false);
  assert.equal(View.inUse(View.row(SHIP24, ctx()), box), false, 'the cursor in another row');
});

test('Gmail, set up at the server, asks for nothing here and says so', () => {
  const row = View.row(GMAIL, ctx());
  assert.equal(all(row, 'input').length, 0);
  assert.equal(buttonCalled(row, 'Connect'), undefined);
  assert.equal(one(row, '.conn-status').textContent, 'Connects at the server for now');
});

test('a sign-in running out asks him to sign in again, not for a key', () => {
  const signedIn = [];
  const row = View.row(INSTAGRAM, ctx({ on: { signIn: (c) => signedIn.push(c.name) } }));
  assert.equal(keyBoxes(row).length, 0);
  const go = buttonCalled(row, 'Sign in again');
  assert.ok(go && !go.disabled);
  go.dispatch('click');
  assert.deepEqual(signedIn, ['instagram']);
});

test('Instagram can always be signed in to again from its details, once, whatever its state', () => {
  // The review of 889f3284 (note 3): only a row whose fix was "signin" offered it.
  const signed = [];
  const on = { signIn: (c) => signed.push(c.name) };
  const working = Object.assign({}, INSTAGRAM, { state: 'connected', group: 'working', fix: '', detail: 'Connected.' });
  const waiting = Object.assign({}, INSTAGRAM, { fix: 'retry', detail: 'Instagram did not answer.' });
  for (const c of [working, waiting]) {
    const row = View.row(c, ctx({ on }));
    const again = all(row, 'button').filter((b) => b.textContent === 'Sign in again');
    assert.equal(again.length, 1, c.fix || 'working');
    assert.ok(!again[0].disabled);
    again[0].dispatch('click');
  }
  assert.deepEqual(signed, ['instagram', 'instagram']);
  const ending = View.row(INSTAGRAM, ctx());
  assert.equal(all(ending, 'button').filter((b) => b.textContent === 'Sign in again').length, 1, 'not twice');
  const notReady = View.row(Object.assign({}, working, { sign_in: Object.assign({}, INSTAGRAM.sign_in, { ready: false }) }), ctx());
  assert.equal(all(notReady, 'button').filter((b) => b.textContent === 'Sign in again').length, 0);
});

test('Save hands the typed values to the page, and nothing a change needs is skipped', () => {
  const saved = [];
  const row = View.row(GITHUB, ctx({ on: { save: (c, form, inputs) => saved.push([c.name, inputs.length]) } }));
  one(row, 'form').dispatch('submit');
  assert.deepEqual(saved, [['github', 1]]);
  const locked = View.row(GITHUB, ctx({ canChange: false }));
  assert.equal(one(locked, '.key-save').disabled, true, 'no passkey possible here: Save is off');
});

test('while CLIVE is asking a service, its row says so', () => {
  const row = View.row(SHOPIFY, ctx({ checking: new Set(['shopify']) }));
  assert.equal(one(row, '.conn-status').textContent, 'Checking now…');
  assert.ok(one(row, '.dot').classList.contains('is-busy'));
  assert.equal(View.summary(STATE, ctx({ checking: new Set(['shopify']) })), 'Checking each connection now.');
});

test('details say what it lets CLIVE do, what stops without it, and where the key is', () => {
  const row = View.row(SHOPIFY, ctx());
  const words = row.allText();
  assert.match(words, /Reading orders/);
  assert.match(words, /Refunding.*changes off/);
  assert.match(words, /Without it CLIVE can't see or change anything in the shop\./);
  assert.match(words, /KeySet at the server/);
  assert.match(words, /crooks\.myshopify\.com/);
});

test('nothing from the server is written into a secret box or read as markup', () => {
  const leaky = connection({
    label: HOSTILE, what: HOSTILE, detail: HOSTILE, who: HOSTILE,
    fields: [field('elevenlabs_api_key', HOSTILE, { stored: true, where: 'saved here', value: SECRET })],
  });
  const row = View.row(leaky, ctx());
  buttonCalled(row, 'Replace ' + HOSTILE.toLowerCase()).dispatch('click');
  assert.equal(keyBoxes(row)[0].value, undefined, 'a secret field never shows a value, even one sent');
  assert.ok(!row.allText().includes(SECRET));
  assert.ok(row.allText().includes(HOSTILE), 'shown as text');
  // Instagram's sign-in comes back to /connections#instagram: the row answers to that name.
  assert.equal(View.row(INSTAGRAM, ctx()).id, 'instagram');
  // A name that is not one of ours is never put into an attribute.
  const odd = View.row(connection({ name: '"><x' }), ctx());
  assert.equal(odd.dataset.name, undefined);
  assert.equal(odd.id, undefined);
});

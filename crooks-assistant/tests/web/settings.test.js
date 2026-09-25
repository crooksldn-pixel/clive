/* The owner's settings and less chrome (GENERATIVE_UI_V1 §4, objective 2b).
 *
 * The Settings sheet reads as the owner's, in a fixed order — Voice; What CLIVE can do for you;
 * Who and what CLIVE can reach; What CLIVE needs from you; Conversation — and a section with
 * nothing true to show is left out rather than filled. Diagnostics and fixtures sit behind a
 * "Developer view" switch at the bottom, off by default. The header says something only while
 * something is wrong and it matters to what the owner is doing. Back, Previous and Next appear
 * only inside a list or a drill-down.
 *
 * app.js is one page script with no module boundary, so, as in mic.test.js, this runs the real
 * text of the parts that matter — cut out by their own markers — against the DOM stand-in, and
 * reads index.html for the order of the sheet.
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
const INDEX = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');

// From the line that starts `start` up to (not including) the line that holds `end`.
function cut(start, end) {
  const from = SOURCE.indexOf(start);
  assert.notEqual(from, -1, `web/app.js no longer has ${JSON.stringify(start)}`);
  const to = SOURCE.indexOf(end, from + start.length);
  assert.notEqual(to, -1, `web/app.js no longer has ${JSON.stringify(end)} after ${JSON.stringify(start)}`);
  return SOURCE.slice(from, SOURCE.lastIndexOf('\n', to) + 1);
}

const PARTS = [
  cut("// The badge names the thing that is down, in the owner's words, worst first.", '// The build this page was made for'),
  cut("/* ----------------------------------------------------- the owner's settings */", 'pollHealth();\nsetInterval'),
  cut('function canGoBack(index)', '// Which area the screen is showing'),
  cut('// Back, Previous and Next: three controls over two cursors', "// Back is the Mac's to decide"),
  cut('// Diagnostics and fixtures live behind one clearly labelled switch', ' system layer */'),
].join('\n');

// Words that name the machine CLIVE runs on, or how it is started. None may reach the owner.
const RUNTIME_HOST = /\b(Mac|tablet|launchd)\b|make up/i;

function boot({ dev = false } = {}) {
  const make = (tag) => shim.document.createElement(tag);
  const saved = {};
  const el = {
    body: make('body'), conn: make('span'), connText: make('span'),
    backBtn: make('button'), prevBtn: make('button'), nextBtn: make('button'),
    setCanDo: make('section'), canDo: make('div'), setReach: make('section'), reach: make('div'),
    setNeeds: make('section'), needs: make('div'),
    dev: make('section'), devToggle: make('input'), devGrid: make('div'), devText: make('input'),
    timingToggle: make('input'), timings: make('p'),
    settings: { open: false, close() {} },
  };
  // As index.html serves them: the status and the three walk chips hidden, the sections
  // drawn from /health hidden, the developer section hidden and its switch off.
  for (const node of [el.conn, el.backBtn, el.prevBtn, el.nextBtn, el.setCanDo, el.setReach, el.setNeeds, el.dev, el.timings]) node.hidden = true;
  el.devToggle.checked = false;
  el.timingToggle.checked = false;
  const document = { createElement: make, body: make('body') };
  const sandbox = {
    console, document, el, DEV: dev,
    store: { get: (key, fallback) => (key in saved ? saved[key] : fallback), set: (key, value) => { saved[key] = value; } },
    clear(node) { while (node.firstChild) node.removeChild(node.firstChild); },
    branchState: null, historyIndex: -1,
    // Reached only from a fixture button or a typed ask, neither of which these tests press.
    renderOpts: () => ({}), pushContext() {}, setState() {}, submit() {}, unlockSpeech() {}, stopSpeaking() {},
    busy: false, sessionId: 's', turns: 0,
  };
  sandbox.window = sandbox;
  vm.runInNewContext(`'use strict';\n${PARTS}`, sandbox, { filename: 'app.js (settings and chrome parts)' });
  return { sandbox, el, document, saved };
}

const scripts = (document) => document.body.children.filter((n) => n.tagName === 'SCRIPT');
const rows = (list) => list.children.map((row) => ({
  name: row.querySelector('.oname') ? row.querySelector('.oname').textContent : '',
  word: row.querySelector('.ostate') ? row.querySelector('.ostate').textContent : '',
  detail: row.querySelector('.odetail') ? row.querySelector('.odetail').textContent : '',
  state: row.dataset.state,
}));

// A /health answer with everything well: the shape app/routes/health.py returns.
function healthy() {
  return {
    checks: {
      claude: { ok: true, detail: 'Agent SDK' }, shopify: { ok: true, detail: 'Shop' }, gmail: { ok: true, detail: 'me@example.com' },
      tts: { ok: true, detail: 'ElevenLabs' }, speech: { ok: true, detail: 'scribe (primary)' }, whisper: { ok: true, detail: 'whisper' },
    },
    voice: { enabled: true, ok: true, voice: 'George', failure_kind: null, reason: null },
    speech: { scribe_failure_kind: null, scribe_reason: null },
    families: {
      order_note: { key: 'order_note', label: 'Order notes', area: 'orders', what: 'add a note to an order', state: 'READY', operations: ['order.note_append'], hide: false },
      order_lookup: { key: 'order_lookup', label: 'Order lookup', area: 'orders', what: 'find an order', state: 'READY', operations: [], hide: false },
    },
  };
}

/* ------------------------------------------------------------ the sheet's order */

test('Settings is the owner\'s: five sections in the stated order, then the Developer view switch, then the developer section', () => {
  const sheet = INDEX.slice(INDEX.indexOf('<dialog id="settings"'), INDEX.indexOf('</dialog>'));
  const order = [
    ['id="set-voice"', '<h3>Voice</h3>'],
    ['id="set-can-do"', '<h3>What CLIVE can do for you</h3>'],
    ['id="set-reach"', '<h3>Who and what CLIVE can reach</h3>'],
    ['id="set-needs"', '<h3>What CLIVE needs from you</h3>'],
    ['id="set-conversation"', '<h3>Conversation</h3>'],
    ['id="dev-toggle"', 'Developer view'],
    ['<section id="dev"', '<h3>Diagnostics</h3>'],
  ];
  let last = -1;
  for (const [marker, words] of order) {
    const at = sheet.indexOf(marker);
    assert.ok(at > last, `${marker} is out of order`);
    assert.ok(sheet.indexOf(words, at) > at, `${marker} does not say ${words}`);
    last = at;
  }
  // Voice is the owner's choices and nothing else: on or off, preview, microphone test.
  const voice = sheet.slice(sheet.indexOf('id="set-voice"'), sheet.indexOf('id="set-can-do"'));
  for (const id of ['speak-toggle', 'preview-voice', 'mic-test']) assert.ok(voice.includes(`id="${id}"`), id);
  assert.ok(sheet.slice(sheet.indexOf('id="set-conversation"')).includes('New conversation'));
  // The three drawn from /health start hidden: they are shown when there is something true to say.
  for (const id of ['set-can-do', 'set-reach', 'set-needs']) {
    assert.match(sheet, new RegExp(`<section id="${id}"[^>]*\\shidden>`), `${id} is not hidden until drawn`);
  }
});

test('diagnostics and fixtures are all behind the developer section, and none of the owner\'s part names the machine', () => {
  const sheet = INDEX.slice(INDEX.indexOf('<dialog id="settings"'), INDEX.indexOf('</dialog>'));
  const owner = sheet.slice(0, sheet.indexOf('id="dev-toggle"'));
  const dev = sheet.slice(sheet.indexOf('<section id="dev"'));
  for (const id of ['services', 'svc-shopify', 'health-detail', 'families', 'timing-toggle', 'stream-toggle', 'voice-select', 'dev-grid', 'dev-text']) {
    assert.ok(!owner.includes(`id="${id}"`), `${id} is still in the owner's sections`);
    assert.ok(dev.includes(`id="${id}"`), `${id} is not in the developer section`);
  }
  const words = owner.replace(/<!--[\s\S]*?-->/g, '').replace(/<[^>]+>/g, ' ');
  assert.doesNotMatch(words, RUNTIME_HOST);
  assert.doesNotMatch(words, /diagnostic|fixture|ElevenLabs/i);
});

test('the connection and refusal words the owner sees never name the machine CLIVE runs on', () => {
  const UI = fs.readFileSync(path.join(WEB, 'ui.js'), 'utf8');
  const code = (text) => text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  const refused = cut('function wentRefused()', 'function wentOffline()');
  assert.match(refused, /Not allowed/);
  assert.doesNotMatch(code(refused), RUNTIME_HOST);
  assert.doesNotMatch(code(cut('const ACTION_REASONS = {', '\n};\n')), RUNTIME_HOST);
  const blocked = UI.slice(UI.indexOf('function blockedLabel(code)'), UI.indexOf('function blockedLabel(code)') + 600);
  assert.doesNotMatch(code(blocked), RUNTIME_HOST);
  for (const said of ["'CLIVE did not answer.'", "Couldn't reach CLIVE", "'CLIVE would not open that.'"]) assert.ok(SOURCE.includes(said), said);
  assert.ok(!/'The Mac did not answer\.'/.test(SOURCE));
  assert.ok(!UI.includes('newer tablet build'));
});

/* ------------------------------------------------------ omission of empty sections */

test('a section with nothing true to show is left out, never filled with a placeholder', () => {
  const page = boot();
  // Nothing known: CLIVE could not be reached.
  page.sandbox.drawOwnerSettings(null);
  for (const [section, list] of [[page.el.setCanDo, page.el.canDo], [page.el.setReach, page.el.reach], [page.el.setNeeds, page.el.needs]]) {
    assert.equal(section.hidden, true);
    assert.equal(list.children.length, 0);
  }
  // Only Shopify reported, nothing CLIVE may prepare, nothing it needs.
  page.sandbox.drawOwnerSettings({ checks: { shopify: { ok: true, detail: 'Shop' } }, families: {} });
  assert.equal(page.el.setCanDo.hidden, true);
  assert.equal(page.el.setNeeds.hidden, true);
  assert.equal(page.el.setReach.hidden, false);
  assert.deepEqual(rows(page.el.reach), [{ name: 'Shopify', word: 'Connected', detail: '', state: 'ok' }]);
  // And back to nothing: the last answer is not kept.
  page.sandbox.drawOwnerSettings(null);
  assert.equal(page.el.setReach.hidden, true);
  assert.equal(page.el.reach.children.length, 0);
});

test('all well: what CLIVE can prepare, and every service connected; nothing needed from the owner', () => {
  const page = boot();
  page.sandbox.drawOwnerSettings(healthy());
  assert.equal(page.el.setCanDo.hidden, false);
  // Only the families that stage a change and are ready to.
  assert.deepEqual(rows(page.el.canDo), [{ name: 'Order notes', word: '', detail: 'Add a note to an order.', state: 'ok' }]);
  assert.deepEqual(rows(page.el.reach).map((r) => `${r.name}: ${r.word}`),
    ['Shopify: Connected', 'Gmail: Connected', 'Voice: Connected', 'Transcription: Connected']);
  assert.equal(page.el.setNeeds.hidden, true);
  assert.equal(page.el.needs.children.length, 0);
});

test('a service that needs attention says why in plain words and what to do, and the owner\'s steps are listed', () => {
  const page = boot();
  const data = healthy();
  data.checks.tts = { ok: false, detail: 'ElevenLabs 401 quota_exceeded · CROOKS_TTS_ENABLED' };
  data.checks.gmail = { ok: false, detail: 'Gmail check failed: RefreshError on the Mac' };
  data.voice = { enabled: true, ok: false, voice: 'George', failure_kind: 'credit',
    reason: 'voice is paused because the ElevenLabs credits are used up; it comes back by itself once the ElevenLabs plan is topped up' };
  data.families.discount_code = { key: 'discount_code', label: 'Discount codes', area: 'orders', what: 'create a discount code', state: 'MISSING_SCOPE', scope: 'write_discounts', detail: 'not granted on this Mac', operations: ['discount.create'], hide: false };
  data.families.delivery_tracking = { key: 'delivery_tracking', label: 'Delivery status', area: 'shipping', what: 'whether a parcel has actually arrived', state: 'DISCONNECTED', detail: 'no carrier is connected, so whether a parcel arrived is not a fact this Mac holds', operations: [], hide: false };
  data.families.hidden_one = { key: 'hidden_one', label: 'Hidden', area: 'orders', what: 'x', state: 'MISSING_SCOPE', scope: 'y', operations: ['z'], hide: true };
  page.sandbox.drawOwnerSettings(data);

  const reach = rows(page.el.reach);
  const voice = reach.find((r) => r.name === 'Voice');
  assert.equal(voice.word, 'Needs attention');
  assert.equal(voice.state, 'attention');
  assert.match(voice.detail, /^Voice is paused because the ElevenLabs credits are used up; it comes back by itself once the ElevenLabs plan is topped up\./);
  assert.match(voice.detail, /answers are spoken in this device's own voice/);
  // A refused Gmail refresh needs the owner to reconnect it; waiting will not bring it back.
  const gmail = reach.find((r) => r.name === 'Gmail');
  assert.equal(gmail.word, 'Needs attention');
  assert.match(gmail.detail, /stopped letting CLIVE into your inbox/);
  assert.match(gmail.detail, /Reconnect Gmail to CLIVE/);
  assert.doesNotMatch(gmail.detail, /by itself|tries again/);

  assert.equal(page.el.setNeeds.hidden, false);
  const needs = rows(page.el.needs);
  assert.deepEqual(needs.map((r) => `${r.name}: ${r.word}`),
    ['Gmail: Needs reconnecting', 'Delivery status: Not connected', 'Discount codes: Needs your permission', 'ElevenLabs plan: Top up']);
  // The refused Gmail refresh is the owner's step too, in the same words as the reach row.
  assert.equal(needs[0].detail, gmail.detail);
  // A disconnected service names what to connect, and what that turns on.
  assert.equal(needs[1].detail, 'Connect a carrier so CLIVE can tell you whether a parcel has actually arrived.');
  // A missing permission is the task it allows, not the scope's identifier.
  assert.equal(needs[2].detail, "CLIVE does not yet have Shopify's permission to create a discount code. Allow it in Shopify to turn this on.");

  // The backend's engineering detail never reaches these rows — it named the Mac twice here —
  // and neither does a raw identifier: a scope, a state, an exception.
  for (const list of [page.el.canDo, page.el.reach, page.el.needs]) {
    const text = list.allText();
    assert.doesNotMatch(text, RUNTIME_HOST);
    assert.doesNotMatch(text, /CROOKS_|RefreshError|401|quota_exceeded|write_discounts|MISSING_SCOPE|DISCONNECTED|\w_\w/);
  }
  // The exact scope and the backend's reason are still there for the Developer view's list.
  assert.ok(cut('function familyRow(family)', 'function renderFamilies').includes('family.scope'));
});

test('a failed shop or inbox check says why in plain words, and claims recovery only where it comes by itself', () => {
  const page = boot();
  const detailOf = (key, detail) => {
    const data = healthy();
    data.checks[key] = { ok: false, detail };
    page.sandbox.drawOwnerSettings(data);
    return rows(page.el.reach).find((r) => r.name === (key === 'gmail' ? 'Gmail' : 'Shopify'));
  };
  const cases = [
    ['shopify', 'Shopify rejected the token (401). It may have been revoked.', /Reconnect Shopify to CLIVE/, 'Needs attention'],
    ['shopify', 'shop_not_permitted — the app and the store are in different Shopify organisations. This cannot be fixed in config and apps cannot be moved. Either recreate the app in the store\'s organisation, or set CROOKS_SHOPIFY_AUTH_MODE=static_token and store a legacy shpat_ token.',
      /^CLIVE's Shopify connection belongs to a different Shopify organisation from your shop.*Reconnect your shop to CLIVE through your shop's own Shopify organisation/, 'Needs attention'],
    ['shopify', 'auth_mode is static_token but no shopify_static_token is stored. Run: python scripts/set_secrets.py shopify_static_token', /Shopify is not connected to CLIVE yet\. Connect Shopify/, 'Needs attention'],
    ['shopify', 'check timed out', /could not reach your shop.*ask for CLIVE's connection to Shopify to be checked/, 'Needs attention'],
    ['shopify', 'Shopify is rate-limiting us. Try again in a moment.', /picks up again by itself/, 'Busy'],
    ['shopify', 'Shopify rejected the query: something odd', /Shopify did not answer CLIVE as expected/, 'Needs attention'],
    ['gmail', 'Gmail refresh was rejected (invalid_grant). Re-authorise with: python scripts/gmail_auth.py', /Reconnect Gmail to CLIVE/, 'Needs attention'],
    ['gmail', 'No Gmail token stored. Re-authorise with: python scripts/gmail_auth.py', /Gmail is not connected to CLIVE yet\. Connect Gmail/, 'Needs attention'],
    ['gmail', 'check timed out', /could not reach your inbox/, 'Needs attention'],
  ];
  for (const [key, detail, expected, word] of cases) {
    const row = detailOf(key, detail);
    assert.equal(row.state, 'attention', detail);
    assert.equal(row.word, word, detail);
    assert.match(row.detail, expected, detail);
    if (word !== 'Busy') assert.doesNotMatch(row.detail, /by itself|tries again/, detail);
    assert.doesNotMatch(row.detail, /scripts\/|python|invalid_grant|401|shop_not_permitted|static_token|timed out|rate-limiting/, detail);
    assert.doesNotMatch(row.detail, RUNTIME_HOST, detail);
  }
  // Organisations that do not match are their own reason, not access withdrawn or run out, and
  // the raw words — the identifier included — are still the Developer view's.
  assert.doesNotMatch(detailOf('shopify', 'shop_not_permitted').detail, /withdrawn|run out/);
  assert.ok(cut('function renderHealthRows(checks)', '\n}\n').includes('c.detail'));
});

test('a service the owner must connect or reconnect is among the owner\'s steps; one that clears by itself is not', () => {
  const page = boot();
  const needsFor = (key, detail) => {
    const data = healthy();
    data.checks[key] = { ok: false, detail };
    page.sandbox.drawOwnerSettings(data);
    return { hidden: page.el.setNeeds.hidden, rows: rows(page.el.needs), reach: rows(page.el.reach) };
  };
  const steps = [
    ['gmail', 'No Gmail token stored. Re-authorise with: python scripts/gmail_auth.py', 'Gmail', 'Not connected', /^Gmail is not connected to CLIVE yet\. Connect Gmail/],
    ['gmail', 'Gmail refresh was rejected (invalid_grant). Re-authorise with: python scripts/gmail_auth.py', 'Gmail', 'Needs reconnecting', /Reconnect Gmail to CLIVE/],
    ['shopify', 'Shopify rejected the token (401). It may have been revoked.', 'Shopify', 'Needs reconnecting', /Reconnect Shopify to CLIVE/],
    ['shopify', 'auth_mode is static_token but no shopify_static_token is stored.', 'Shopify', 'Not connected', /^Shopify is not connected to CLIVE yet\. Connect Shopify/],
    ['shopify', 'shop_not_permitted — the app and the store are in different Shopify organisations.', 'Shopify', 'Needs reconnecting', /different Shopify organisation.*through your shop's own Shopify organisation/],
  ];
  for (const [key, detail, name, word, expected] of steps) {
    const seen = needsFor(key, detail);
    assert.equal(seen.hidden, false, detail);
    assert.deepEqual(seen.rows.map((r) => `${r.name}: ${r.word}`), [`${name}: ${word}`], detail);
    assert.match(seen.rows[0].detail, expected, detail);
    assert.equal(seen.rows[0].detail, seen.reach.find((r) => r.name === name).detail, detail);
    assert.doesNotMatch(seen.rows[0].detail, /scripts\/|python|invalid_grant|401|shop_not_permitted|static_token|\w_\w/, detail);
    assert.doesNotMatch(seen.rows[0].detail, RUNTIME_HOST, detail);
  }
  // Transient, rate-limited and unrecognised failures establish no step for the owner.
  for (const [key, detail] of [
    ['shopify', 'check timed out'], ['shopify', 'Shopify is rate-limiting us. Try again in a moment.'],
    ['shopify', 'Shopify rejected the query: something odd'], ['gmail', 'check timed out'], ['gmail', 'HTTP 503 from Google'],
  ]) {
    const seen = needsFor(key, detail);
    assert.equal(seen.hidden, true, detail);
    assert.equal(seen.rows.length, 0, detail);
  }
});

test('every disconnected family names the service to connect, and none is told to connect "the service it needs"', () => {
  const page = boot();
  const data = healthy();
  data.families.shipping_provider = { key: 'shipping_provider', label: 'Shipping labels and tracking', area: 'shipping',
    what: 'whether a label exists for an order, which carrier has it, the tracking number, its latest status, and any shipping exception',
    state: 'DISCONNECTED', detail: 'no shipping provider is connected: CROOKS_EASYSHIP_TOKEN is unset and the Easyship HTTP client (not written in this build)', operations: [], hide: false };
  data.families.order_feed = { key: 'order_feed', label: 'Order feed', area: 'orders', what: 'add a customer to the order feed', state: 'DISCONNECTED', detail: 'not connected on this Mac', operations: [], hide: false };
  data.families.inbox_rules = { key: 'inbox_rules', label: 'Inbox rules', area: 'email', what: 'which threads need a reply', state: 'DISCONNECTED', detail: 'no token', operations: [], hide: false };
  data.families.mystery = { key: 'mystery', label: 'Something else', area: 'system', what: 'do a thing', state: 'DISCONNECTED', detail: 'X_TOKEN unset', operations: [], hide: false };
  page.sandbox.drawOwnerSettings(data);
  const needs = rows(page.el.needs);
  assert.deepEqual(needs.map((r) => `${r.name}: ${r.detail}`), [
    'Inbox rules: Connect Gmail so CLIVE can tell you which threads need a reply.',
    'Order feed: Connect Shopify to turn this on.',
    'Shipping labels and tracking: Connect a shipping provider so CLIVE can tell you whether a label exists for an order.',
  ]);
  const text = page.el.needs.allText();
  assert.doesNotMatch(text, /service it needs|Something else/);
  assert.doesNotMatch(text, /CROOKS_|EASYSHIP|\w_\w/);
  assert.doesNotMatch(text, RUNTIME_HOST);
});

test('a failed voice or transcription check always says why and what to do, even with no reason or an unknown one', () => {
  const page = boot();
  const rowFor = (name, kind, reason) => {
    const data = healthy();
    if (name === 'Voice') {
      data.checks.tts = { ok: false, detail: 'ElevenLabs failure · CROOKS_TTS_ENABLED' };
      data.voice = { enabled: true, ok: false, voice: 'George', failure_kind: kind, reason };
    } else {
      data.checks.speech = { ok: false, detail: 'NOT working: scribe is down and there is no local fallback' };
      data.speech = { scribe_failure_kind: kind, scribe_reason: reason };
    }
    page.sandbox.drawOwnerSettings(data);
    return { row: rows(page.el.reach).find((r) => r.name === name), needs: rows(page.el.needs) };
  };
  const cases = [
    // No kind and no reason: said plainly, watched, then escalated.
    ['Voice', null, null, /^CLIVE's voice is not answering\. If it stays like this for more than a few minutes, ask for CLIVE's voice to be checked\./],
    ['Transcription', null, null, /^CLIVE cannot hear you just now\. If it stays like this for more than a few minutes, ask for CLIVE's listening to be checked\.$/],
    // A kind this page does not know, with or without the backend's reason.
    ['Voice', 'failure', null, /^CLIVE's voice is not answering\. If it stays like this.*ask for CLIVE's voice to be checked/],
    ['Transcription', 'something_new', 'ElevenLabs speech recognition is unavailable', /^ElevenLabs speech recognition is unavailable\. If it stays like this.*ask for CLIVE's listening to be checked/],
    ['Voice', 'cooldown', 'the ElevenLabs voice is unavailable at the moment', /^The ElevenLabs voice is unavailable at the moment\. If it stays like this/],
    // A passing fault: nothing to do, and for listening, try again.
    ['Voice', 'timeout', null, /^CLIVE's voice is not answering\. It usually clears by itself within a few minutes; there is nothing to do\./],
    ['Voice', 'network', 'ElevenLabs could not be reached', /^ElevenLabs could not be reached\. It usually clears by itself.*nothing to do\./],
    ['Transcription', 'server_error', 'ElevenLabs had a server error', /^ElevenLabs had a server error\. It usually clears by itself.*nothing to do\. Try speaking again then\.$/],
    ['Transcription', 'rate', null, /^CLIVE cannot hear you just now\. It usually clears by itself.*Try speaking again then\.$/],
    // A key that is wrong does not clear by itself, and waits for a person.
    ['Voice', 'rejected', 'the ElevenLabs key was rejected as invalid; the voice comes back once a valid key is stored', /^The ElevenLabs key was rejected.*This does not clear by itself: ask for CLIVE's voice to be checked\./],
    ['Transcription', 'no_key', null, /^CLIVE cannot hear you just now\. This does not clear by itself: ask for CLIVE's listening to be checked\.$/],
    // Credits used up, even with no reason sent: why, and the top-up.
    ['Transcription', 'credit', null, /^Speech recognition is paused because the ElevenLabs credits are used up\. Top up the ElevenLabs plan to bring it back\.$/],
  ];
  for (const [name, kind, reason, expected] of cases) {
    const { row, needs } = rowFor(name, kind, reason);
    const label = `${name} ${kind} ${reason}`;
    assert.equal(row.state, 'attention', label);
    assert.equal(row.word, 'Needs attention', label);
    assert.match(row.detail, expected, label);
    if (name === 'Voice') assert.match(row.detail, /answers are spoken in this device's own voice\.$/, label);
    assert.doesNotMatch(row.detail, /CROOKS_|NOT working|scribe|\w_\w/, label);
    assert.doesNotMatch(row.detail, RUNTIME_HOST, label);
    // Only credits used up are the owner's own step; the rest establish none.
    if (kind === 'credit') {
      assert.deepEqual(needs.map((r) => `${r.name}: ${r.word}`), ['ElevenLabs plan: Top up'], label);
      assert.match(needs[0].detail, /used up\. Top up the ElevenLabs plan/, label);
    } else {
      assert.equal(needs.length, 0, label);
    }
  }
});

test('the voice switched off is said as off, not as a fault', () => {
  const page = boot();
  const data = healthy();
  data.voice = { enabled: false, ok: true, voice: 'George' };
  page.sandbox.drawOwnerSettings(data);
  const voice = rows(page.el.reach).find((r) => r.name === 'Voice');
  assert.equal(voice.word, 'Off');
  assert.equal(page.el.setNeeds.hidden, true);
});

/* ------------------------------------------------------------ the developer switch */

test('the Developer view switch is off by default, and the developer section and fixtures come only with it', () => {
  const page = boot();
  assert.equal(page.el.devToggle.checked, false);
  assert.equal(page.el.dev.hidden, true);
  assert.equal(scripts(page.document).length, 0, 'fixtures were loaded with the switch off');

  page.el.devToggle.checked = true;
  page.el.devToggle.dispatch('change');
  assert.equal(page.el.dev.hidden, false);
  assert.equal(page.saved['crooks.dev'], '1');
  assert.deepEqual(scripts(page.document).map((s) => s.src), ['/static/fixtures.js']);
  const banner = page.document.body.children.find((n) => n.className === 'dev-banner');
  assert.ok(banner && !banner.hidden && /fixtures are not live data/.test(banner.textContent));

  // Off again: nothing of it is left on the owner's screen, the timings line included.
  page.el.timingToggle.checked = true;
  page.el.timings.hidden = false;
  page.el.devToggle.checked = false;
  page.el.devToggle.dispatch('change');
  assert.equal(page.el.dev.hidden, true);
  assert.equal(banner.hidden, true);
  assert.equal(page.el.timingToggle.checked, false);
  assert.equal(page.el.timings.hidden, true);
  assert.equal(page.saved['crooks.dev'], '0');

  // And on once more: the fixtures are not loaded twice.
  page.el.devToggle.checked = true;
  page.el.devToggle.dispatch('change');
  assert.equal(scripts(page.document).length, 1);
  assert.equal(banner.hidden, false);
});

test('a browser that turned the Developer view on (?dev=1) opens with it on', () => {
  const page = boot({ dev: true });
  assert.equal(page.el.devToggle.checked, true);
  assert.equal(page.el.dev.hidden, false);
  assert.equal(scripts(page.document).length, 1);
});

/* ------------------------------------------------------------ the contextual header */

test('the header shows nothing while all is well, or while connecting', () => {
  const page = boot();
  page.sandbox.setConn('connecting', 'Connecting');
  assert.equal(page.el.conn.hidden, true);
  page.sandbox.setConn('ok', 'Online');
  assert.equal(page.el.conn.hidden, true);
});

test('offline, and CLIVE unable to answer or hear, always show', () => {
  const page = boot();
  page.sandbox.setConn('down', 'Offline');
  assert.equal(page.el.conn.hidden, false);
  assert.equal(page.el.connText.textContent, 'Offline');

  page.sandbox.setConn('degraded', 'x', { claude: { ok: false }, shopify: { ok: true } });
  assert.equal(page.el.conn.hidden, false);
  assert.equal(page.el.connText.textContent, 'CLIVE cannot answer');

  page.sandbox.setConn('degraded', 'x', { speech: { ok: false } });
  assert.equal(page.el.conn.hidden, false);
  assert.equal(page.el.connText.textContent, 'Speech offline');
});

test('a service fault shows only while the owner is in the place it breaks', () => {
  const page = boot();
  const checks = { shopify: { ok: false }, gmail: { ok: true }, tts: { ok: true } };
  page.sandbox.setConn('degraded', 'Shopify offline', checks);
  assert.equal(page.el.conn.hidden, true, 'the orb screen is not reading from the shop');

  for (const area of ['orders', 'sales', 'products']) {
    page.el.body.dataset.area = area;
    page.sandbox.drawConn();
    assert.equal(page.el.conn.hidden, false, area);
    assert.equal(page.el.connText.textContent, 'Shopify offline');
  }
  page.el.body.dataset.area = 'email';
  page.sandbox.drawConn();
  assert.equal(page.el.conn.hidden, true, 'the inbox does not need the shop');

  page.sandbox.setConn('degraded', 'Gmail offline', { gmail: { ok: false } });
  assert.equal(page.el.conn.hidden, false);
  assert.equal(page.el.connText.textContent, 'Gmail offline');
});

test('a fault that changes nothing the owner does is never the header\'s', () => {
  const page = boot();
  for (const area of ['', 'orders', 'email']) {
    page.el.body.dataset.area = area;
    page.sandbox.setConn('degraded', 'Voice fallback in use', { tts: { ok: false }, scribe: { ok: false }, whisper: { ok: false }, knowledge_base: { ok: false } });
    assert.equal(page.el.conn.hidden, true, area);
  }
});

test('the header status is served hidden, and area changes redraw it', () => {
  assert.match(INDEX, /<span id="conn" class="conn" data-state="connecting" role="status" hidden>/);
  const dock = cut('function lightDock(nodes)', '\n}\n');
  assert.ok(dock.includes('drawConn();'), 'lightDock does not redraw the header');
});

/* ------------------------------------------------------ the contextual navigation */

test('Back, Previous and Next are not a permanent strip: on a landing none of them shows', () => {
  const page = boot();
  page.sandbox.branchState = { branch_id: 'b', can_back: false, workflow: null };
  page.sandbox.drawWalkChips(0);
  assert.equal(page.el.backBtn.hidden, true);
  assert.equal(page.el.prevBtn.hidden, true);
  assert.equal(page.el.nextBtn.hidden, true);
  // Without a branch the local history decides, and a first screen has nothing behind it.
  page.sandbox.branchState = null;
  page.sandbox.drawWalkChips(0);
  assert.equal(page.el.backBtn.hidden, true);
  for (const id of ['back-btn', 'prev-btn', 'next-btn']) assert.match(INDEX, new RegExp(`<button id="${id}"[^>]*\\shidden[\\s>]`), `${id} is not served hidden`);
});

test('inside a drill-down, Back shows and works; Previous and Next stay away', () => {
  const page = boot();
  page.sandbox.branchState = { branch_id: 'b', can_back: true, workflow: null };
  page.sandbox.drawWalkChips(1);
  assert.equal(page.el.backBtn.hidden, false);
  assert.equal(page.el.backBtn.disabled, false);
  assert.equal(page.el.prevBtn.hidden, true);
  assert.equal(page.el.nextBtn.hidden, true);
  // The local history stands in when the branch has not said.
  page.sandbox.branchState = null;
  page.sandbox.drawWalkChips(2);
  assert.equal(page.el.backBtn.hidden, false);
  assert.equal(page.el.backBtn.disabled, false);
});

test('inside a list, all three show and keep their slots for the whole walk, greying at the ends', () => {
  const page = boot();
  page.sandbox.branchState = { branch_id: 'b', can_back: false, workflow: { set_id: 's', at_start: true, at_end: false } };
  page.sandbox.drawWalkChips(0);
  assert.deepEqual([page.el.backBtn.hidden, page.el.prevBtn.hidden, page.el.nextBtn.hidden], [false, false, false]);
  assert.deepEqual([page.el.backBtn.disabled, page.el.prevBtn.disabled, page.el.nextBtn.disabled], [true, true, false]);

  page.sandbox.branchState = { branch_id: 'b', can_back: true, workflow: { set_id: 's', at_start: false, at_end: true } };
  page.sandbox.drawWalkChips(1);
  assert.deepEqual([page.el.backBtn.hidden, page.el.prevBtn.hidden, page.el.nextBtn.hidden], [false, false, false]);
  assert.deepEqual([page.el.backBtn.disabled, page.el.prevBtn.disabled, page.el.nextBtn.disabled], [false, false, true]);

  // Leaving the list takes Previous and Next with it.
  page.sandbox.branchState = { branch_id: 'b', can_back: true, workflow: null };
  page.sandbox.drawWalkChips(2);
  assert.deepEqual([page.el.backBtn.hidden, page.el.prevBtn.hidden, page.el.nextBtn.hidden], [false, true, true]);
});

test('when shown, the three are wired to the same commands as before', () => {
  assert.ok(SOURCE.includes("el.backBtn.addEventListener('click', goBack);"));
  assert.ok(SOURCE.includes("if (el.nextBtn) el.nextBtn.addEventListener('click', goNext);"));
  assert.ok(SOURCE.includes("if (el.prevBtn) el.prevBtn.addEventListener('click', goPrevious);"));
  assert.ok(SOURCE.includes("const goNext = () => stepSet('workflow.next', 'next');"));
  assert.ok(SOURCE.includes("const goPrevious = () => stepSet('workflow.previous', 'previous');"));
  assert.ok(cut('async function goBack()', '\n}\n').includes("semanticCommand('navigation.back')"));
});

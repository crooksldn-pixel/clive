/* Typing on the message card, one edit at a time (web/app.js, DEC-067; review of 8 October,
 * note 2), run under Node (node --test tests/web/message-edit.test.js; the Python side is
 * tests/test_message_card.py, which runs this file).
 *
 * The card stuck: an edit posted, a few more characters typed, the first answer redrew the card,
 * and the second keystroke's timer then fired from the textarea that redraw had taken off the
 * glass. Its answer was never drawn, and the card stayed saying "Updating the words…" with its
 * hold blocked. What is proved, with the page's own code and the real card renderer:
 *
 * - a timer that fires after a redraw finds the field that replaced the one it was set on, and
 *   its answer becomes the card;
 * - a second edit waits for the first's answer, then goes with the latest words;
 * - "busy" (the Mac still preparing an edit) is sent again after a keystroke's quiet, and is not
 *   a refusal the owner is shown.
 *
 * app.js is one page script with no module boundary, so, as tests/web/followups-app-page.test.js
 * does, its compose section is cut out of the real text by its own markers and run against
 * stand-ins the test controls: the Mac and the timers. Every name here is invented.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const shim = require('./dom-shim.js');

// The page uses `closest` and `contains`, which the DOM stand-in does not have. Added here, for
// this file's process only: `.class`, `[attr]` and `[attr="value"]`, joined with no space.
function matches(node, selector) {
  if (!node || node.nodeType !== 1) return false;
  const parts = String(selector).match(/\.[\w-]+|\[[\w-]+(?:="[^"]*")?\]/g) || [];
  return parts.join('') === selector && parts.every((part) => {
    if (part.startsWith('.')) return node.classList.contains(part.slice(1));
    const [, name, value] = /^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(part);
    const key = name.startsWith('data-') ? name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase()) : '';
    const held = key && Object.prototype.hasOwnProperty.call(node.dataset, key) ? String(node.dataset[key]) : node.getAttribute(name);
    return value === undefined ? held !== null : held === value;
  });
}
shim.Element.prototype.closest = function closest(selector) {
  for (let node = this; node; node = node.parentNode) if (matches(node, selector)) return node;
  return null;
};
shim.Element.prototype.contains = function contains(other) {
  for (let node = other; node; node = node.parentNode) if (node === this) return true;
  return false;
};

globalThis.document = shim.document;
const WEB = path.join(__dirname, '..', '..', 'web');
const UI = require(path.join(WEB, 'ui.js'));
const SOURCE = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');

const settle = async (times = 12) => { for (let i = 0; i < times; i++) await new Promise((resolve) => setImmediate(resolve)); };
function deferred() { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; }

// From the line that starts `start` up to (not including) the line that holds `end`.
function cut(start, end) {
  const from = SOURCE.indexOf(start);
  assert.notEqual(from, -1, `web/app.js no longer has ${JSON.stringify(start)}`);
  const to = SOURCE.indexOf(end, from + start.length);
  assert.notEqual(to, -1, `web/app.js no longer has ${JSON.stringify(end)} after ${JSON.stringify(start)}`);
  return SOURCE.slice(from, SOURCE.lastIndexOf('\n', to) + 1);
}

const COMPOSE = [
  cut('// Where the thumb was, per field, so a re-render does not throw the caret to the end.', '// (b) One delegated handler for every button that names a semantic command.'),
  cut('function cssEscape(value) {', 'function commandArgs(raw) {'),
].join('\n');

const CARD = 'msg_0123456789abcdef';

// The card the Mac answers with: the message card for proposal `id`, with these words on it.
function messageCard(id, body) {
  return {
    type: 'confirmation', data: {
      proposal_id: id, status: 'pending', risk: 'red', operation: 'gmail_send_reply', title: 'Send the reply',
      entity: 'Email thread', entity_ref: 'thread_1', facts: [],
      interaction: { kind: 'hold_to_arm', label: 'Hold, then tap to send', footer: 'nothing happens until you hold the card', armed_after_ms: 650 },
      ttl_s: 60, commit: { allowed: true },
      message: {
        channel: 'email', kind: 'reply', to: 'Rosa Field <rosa.field@example.com>', subject: 'Re: Hoodie', body, sign_off: 'CROOKS',
        editable: ['body'], sending: true, key: CARD, command: 'message.stage', other: null,
      },
    },
  };
}

function boot() {
  const timers = [];
  let nextId = 1;
  const out = { posted: [], notified: [] };
  const mac = [];
  const opts = {
    now: () => 0, blocked: () => false, onArm: () => Promise.resolve('tok'), onCommit: () => {}, onDecline: () => {},
    timers: { set: () => 0, clear: () => {} },
  };
  const el = { cards: shim.document.createElement('div') };
  const sandbox = {
    console, Map, Set, Promise, JSON, Math, Number, String, Object, Array, Error,
    setTimeout: (fn, ms) => { const id = nextId++; timers.push({ id, fn, ms, live: true }); return id; },
    clearTimeout: (id) => { for (const t of timers) if (t.id === id) t.live = false; },
    el, T: { record() {} }, history: [], historyIndex: -1,
    renderOpts: () => opts,
    settleWithdrawn() {},
    notifyControl: (words) => { out.notified.push(String(words)); },
    semanticCommand: (name, args) => { out.posted.push({ name, ...args }); const answer = deferred(); mac.push(answer); return answer.promise; },
  };
  sandbox.window = sandbox;
  sandbox.window.CrooksUI = UI;
  vm.createContext(sandbox);
  vm.runInContext(`'use strict';\n${COMPOSE}`, sandbox, { filename: 'app.js (the compose part)' });
  const draw = (item) => { const { nodes } = UI.render([item], opts); el.cards.appendChild(nodes[0]); return nodes[0]; };
  return {
    el, out, mac, timers,
    draw,
    shown: () => el.cards.children[0],
    field: () => el.cards.children[0].querySelector('.field-input'),
    // A keystroke: the field keeps the words (web/ui.js), and the deck's listener sets its quiet.
    type(control, words) { control.value = words; control.dispatch('input'); el.cards.dispatch('input', { target: control }); },
    // The quiet runs out: every timer still set, in order.
    async quiet() { for (const t of timers.splice(0)) if (t.live) t.fn(); await settle(); },
    async answer(index, body) { mac[index].resolve(body); await settle(); },
  };
}

const ok = (id, words) => ({ ok: true, answer: '', ui: [messageCard(id, words)], changed: { message_key: CARD } });

test('a timer that fires after a redraw finds the field that replaced its own, and its answer is the card', async () => {
  UI.clearFieldDrafts();
  const h = boot();
  h.draw(messageCard('prop_1', 'Hi Rosa, it is on its way.'));
  const first = h.field();
  h.type(first, 'Hi Rosa, it went out today.');
  await h.quiet();
  assert.equal(h.out.posted.length, 1);
  // More words in the same field while the first edit is on its way; the quiet is set on it.
  h.type(first, 'Hi Rosa, it went out today. Tracked 24.');
  // The first answer redraws the card. The field the timer holds is now off the glass.
  await h.answer(0, ok('prop_2', 'Hi Rosa, it went out today.'));
  assert.equal(h.shown().dataset.proposal, 'prop_2');
  assert.equal(h.shown().dataset.typing, 'true', 'the newer words are still on their way');
  assert.notEqual(h.field(), first);
  await h.quiet();
  assert.equal(h.out.posted.length, 2);
  assert.equal(h.out.posted[1].value, 'Hi Rosa, it went out today. Tracked 24.');
  await h.answer(1, ok('prop_3', 'Hi Rosa, it went out today. Tracked 24.'));
  assert.equal(h.shown().dataset.proposal, 'prop_3', 'the second answer is drawn: the card is not stuck');
  assert.equal(h.shown().dataset.typing, undefined, 'and its hold is live');
  assert.equal(h.field().value, 'Hi Rosa, it went out today. Tracked 24.');
  assert.deepEqual(h.out.notified, []);
});

test('a second edit waits for the first one\'s answer, then goes with the latest words', async () => {
  UI.clearFieldDrafts();
  const h = boot();
  h.draw(messageCard('prop_1', 'Hi Rosa.'));
  h.type(h.field(), 'Hi Rosa, yes.');
  await h.quiet();
  h.type(h.field(), 'Hi Rosa, yes, in black.');
  await h.quiet();
  assert.equal(h.out.posted.length, 1, 'one edit of a message on its way at a time');
  h.type(h.field(), 'Hi Rosa, yes, in black and grey.');
  await h.quiet();
  assert.equal(h.out.posted.length, 1);
  await h.answer(0, ok('prop_2', 'Hi Rosa, yes.'));
  assert.equal(h.out.posted.length, 2, 'the waiting edit went once the first was answered');
  assert.equal(h.out.posted[1].value, 'Hi Rosa, yes, in black and grey.', 'with the words in the field now');
  assert.equal(h.out.posted[1].compose_id, CARD);
  assert.equal(h.out.posted[1].field, 'body');
  await h.answer(1, ok('prop_3', 'Hi Rosa, yes, in black and grey.'));
  assert.equal(h.shown().dataset.proposal, 'prop_3');
  assert.equal(h.shown().dataset.typing, undefined);
  assert.equal(h.out.posted.length, 2, 'nothing else was sent');
});

test('"busy" goes again after a keystroke\'s quiet, and is not shown as a refusal', async () => {
  UI.clearFieldDrafts();
  const h = boot();
  h.draw(messageCard('prop_1', 'Hi Rosa.'));
  h.type(h.field(), 'Hi Rosa, yes.');
  await h.quiet();
  await h.answer(0, { ok: false, code: 'busy', detail: 'The words typed before these are still being prepared.' });
  assert.deepEqual(h.out.notified, [], 'busy is not a refusal');
  assert.equal(h.out.posted.length, 1);
  await h.quiet();
  assert.equal(h.out.posted.length, 2, 'sent again');
  assert.equal(h.out.posted[1].value, 'Hi Rosa, yes.');
  await h.answer(1, ok('prop_2', 'Hi Rosa, yes.'));
  assert.equal(h.shown().dataset.proposal, 'prop_2');
  assert.equal(h.shown().dataset.typing, undefined);
});

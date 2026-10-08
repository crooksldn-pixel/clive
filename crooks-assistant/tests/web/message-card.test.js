/* The message card (web/ui.js `messageBlock`, DEC-068, 7 October 2026).
 *
 * George: "why do I have to click save draft and then say send it and then it pulls up a send it
 * screen to send." A message is one card: who it goes to, its words — editable on the card — and
 * the hold that sends it. What the tablet must hold to (app/families/message.py has the contract):
 *
 *   - the words are a field that posts the card's opaque key, the field's NAME and the
 *     characters to `message.stage`, and nothing of the change itself;
 *   - while typed words are on their way to the Mac the hold waits, and says so — the hold only
 *     ever sends the words the Mac prepared, which are the words on the card;
 *   - the other way ("Save as draft") is a quiet button naming the command and the key;
 *   - To and Subject are said once, in the message's own lines, not again as facts.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
const UI = require(path.join(__dirname, '..', '..', 'web', 'ui.js'));

const CARD = 'msg_0123456789abcdef';

function messageCard(extra, opts) {
  const data = Object.assign({
    proposal_id: 'prop_1', status: 'pending', risk: 'red', operation: 'gmail_send_reply',
    title: 'Send the reply', entity: 'Email thread', entity_ref: 'c28cf65d31fe6cbb',
    body: 'Hi Priya, yes: the black cap is the adjustable one.\n\nCROOKS',
    facts: [
      { label: 'To', value: 'Priya Raman <priya.raman@example.com>' },
      { label: 'Subject', value: 'Re: Cap' },
      { label: 'Replying to', value: 'priya.raman@example.com, 8 Oct 13:00 · verified sender' },
      { label: 'From', value: 'orders@crooksldn.example' },
    ],
    interaction: { kind: 'hold_to_arm', label: 'Hold, then tap to send', footer: 'nothing happens until you hold the card, then tap it', armed_after_ms: 650 },
    ttl_s: 60, commit: { allowed: true },
    message: {
      channel: 'email', kind: 'reply', to: 'Priya Raman <priya.raman@example.com>', subject: 'Re: Cap',
      body: 'Hi Priya, yes: the black cap is the adjustable one.', sign_off: 'CROOKS', editable: ['body'],
      sending: true, key: CARD, command: 'message.stage', other: { label: 'Save as draft', args: `key=${CARD}&other=1` },
    },
  }, extra || {});
  return UI.renderItem({ type: 'confirmation', data }, Object.assign({
    now: () => 0, blocked: () => false, onArm: () => Promise.resolve('tok'), onCommit: () => {}, onDecline: () => {},
    timers: { set: () => 0, clear: () => {} },
  }, opts || {}));
}

test('the card is the message: who it is to, the words in a field, and the hold that sends it', () => {
  const node = messageCard();
  assert.equal(node.dataset.message, CARD);
  assert.ok(node.classList.contains('is-message'));
  assert.match(node.querySelector('.card-kicker').textContent, /^Reply · ready to send$/);
  const to = node.querySelectorAll('.field-static').find((f) => f.dataset.field === 'to');
  assert.match(to.allText(), /Priya Raman <priya\.raman@example\.com>/);
  const body = node.querySelector('.field-input');
  assert.equal(body.dataset.field, 'body');
  assert.equal(body.dataset.compose, CARD, 'a keystroke names the card, never the change');
  assert.equal(body.dataset.post, 'message.stage');
  assert.equal(body.value, 'Hi Priya, yes: the black cap is the adjustable one.');
  assert.match(node.querySelector('.message-sign-off').textContent, /CROOKS/);
  assert.match(node.querySelector('.action-surface').textContent, /Hold, then tap to send/);
});

test('To and Subject are said once, in the message, and the other facts stay', () => {
  const node = messageCard();
  const said = node.querySelectorAll('dt').map((dt) => dt.textContent);
  assert.deepEqual(said, ['Replying to', 'From']);
});

test('the other way is quiet and names only the command and the card', () => {
  const node = messageCard();
  const other = node.querySelector('.action-other');
  assert.equal(other.textContent, 'Save as draft');
  assert.equal(other.dataset.command, 'message.stage');
  assert.equal(other.dataset.args, `key=${CARD}&other=1`);
  const settled = messageCard({ status: 'revoked' });
  assert.equal(settled.querySelector('.action-other'), null, 'a card that is not waiting offers no other way');
});

test('while typed words are on their way, the hold waits and says so', async () => {
  const commits = [];
  const node = messageCard({}, { onCommit: (id) => commits.push(id) });
  const body = node.querySelector('.field-input');
  body.value = 'Hi Priya, it is adjustable.';
  body.dispatch('input');
  assert.equal(node.dataset.typing, 'true');
  assert.match(node.querySelector('.action-surface').textContent, /Updating the words/);
  const surface = node.querySelector('.action-surface');
  surface.dataset.state = 'armed';
  surface.dispatch('pointerdown', { clientX: 1, clientY: 1, pointerId: 1 });
  assert.equal(surface.dataset.state, 'armed', 'no hold begins over words the Mac has not prepared');
  surface.dispatch('pointerup', { pointerId: 1 });
  assert.deepEqual(commits, []);
  UI.clearFieldDrafts();
});

test('a card drawn while typed words are still unanswered starts waiting', () => {
  const first = messageCard();
  const body = first.querySelector('.field-input');
  body.value = 'Something newer';
  body.dispatch('input');
  const again = messageCard();                                   // a redraw before the Mac answered
  assert.equal(again.dataset.typing, 'true');
  assert.equal(again.querySelector('.field-input').value, 'Something newer');
  UI.clearFieldDrafts();
  assert.equal(messageCard().dataset.typing, undefined, 'once the Mac has the words, the hold is live');
});

test('an edit the Mac would not take leaves the card saying it is not ready', () => {
  const node = messageCard();
  UI.messageRefused(node);
  assert.equal(node.dataset.typing, 'true');
  assert.match(node.querySelector('.action-surface').textContent, /Not ready to send/);
});

test('a message whose words are not editable is printed, not a field', () => {
  const node = messageCard({ message: {
    channel: 'email', kind: 'reply', to: 'Priya <p@example.com>', subject: 'Re: Cap', body: 'The draft as Gmail holds it.',
    editable: [], sending: true, key: CARD, command: 'message.stage', other: null,
  } });
  assert.equal(node.querySelector('.field-input'), null);
  assert.match(node.querySelector('.msg-body').textContent, /as Gmail holds it/);
  assert.equal(node.querySelector('.action-other'), null);
});

test('a new email has its subject as a field, and a draft says it is one', () => {
  const node = messageCard({ message: {
    channel: 'email', kind: 'new', to: 'Mia Jones <mia.jones@example.com>', subject: 'Your order', body: 'Hi Mia',
    editable: ['subject', 'body'], sending: false, key: CARD, command: 'message.stage',
    other: { label: 'Send instead', args: `key=${CARD}&other=1` },
  } });
  const fields = node.querySelectorAll('.field-input').map((f) => f.dataset.field);
  assert.deepEqual(fields, ['subject', 'body']);
  assert.match(node.querySelector('.card-kicker').textContent, /^Email · to keep as a draft$/);
  assert.equal(node.querySelector('.action-other').textContent, 'Send instead');
});

test('a channel the tablet does not know is drawn as a message, never as markup', () => {
  const node = messageCard({ message: {
    channel: '<img src=x>', kind: '', to: '<b>x</b>', subject: '', body: '<script>1</script>', editable: [],
    sending: true, key: CARD, command: 'message.stage', other: null,
  } });
  assert.equal(node.querySelector('.message-block').dataset.channel, 'message');
  assert.match(node.allText(), /<script>1<\/script>/, 'text, as text');
});

test('a send that did not go offers its words again, quietly, and nothing else', () => {
  const failed = UI.renderItem({ type: 'error', data: {
    service: 'gmail', kind: 'refused', title: 'Not sent', recovery: 'Gmail refused it: Invalid To header. Nothing was sent.',
    again: { label: 'Try again', command: 'message.stage', args: `key=${CARD}&again=1` },
  } }, {});
  const again = failed.querySelector('.action-other');
  assert.equal(again.textContent, 'Try again');
  assert.equal(again.dataset.command, 'message.stage');
  assert.equal(again.dataset.args, `key=${CARD}&again=1`);
  for (const bad of [{ command: 'order.cancel', args: `key=${CARD}&again=1` }, { command: 'message.stage', args: 'order_id=1&again=1' }]) {
    const node = UI.renderItem({ type: 'error', data: { service: 'gmail', title: 'Not sent', again: Object.assign({ label: 'Try again' }, bad) } }, {});
    assert.equal(node.querySelector('.action-other'), null, 'only the message command, only a card key');
  }
});
